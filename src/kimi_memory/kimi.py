"""The pinned current Kimi transcript contract. No raw-log or legacy fallbacks."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode

from .config import ApiConfig
from .errors import CompatibilityError, IncompleteHistoryError, TransportError
from .files import digest
from .http import JsonHttp, local_origin


def timestamp(value: object) -> float:
    if not isinstance(value, str):
        raise CompatibilityError("Expected an ISO timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("missing timezone")
        return result.timestamp()
    except ValueError as exc:
        raise CompatibilityError("Invalid timestamp in Kimi response") from exc


def obj(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise CompatibilityError(f"Expected {label} object")
    return value


def array(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise CompatibilityError(f"Expected {label} array")
    return value


def string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise CompatibilityError(f"Expected nonempty {label}")
    return value


@dataclass(frozen=True)
class Source:
    id: str
    updated_at: float
    created_at: float
    cwd: str
    workspace_id: str
    busy: bool = False
    archived: bool = False
    title: str = ""

    @classmethod
    def from_json(cls, raw: object):
        data = obj(raw, "session")
        if type(data.get("busy")) is not bool:
            raise CompatibilityError("Session busy status is missing")
        if "archived" in data and type(data["archived"]) is not bool:
            raise CompatibilityError("Invalid archived state")
        meta = obj(data.get("metadata"), "session metadata")
        return cls(
            id=string(data.get("id"), "session id"),
            updated_at=timestamp(data.get("updated_at")),
            created_at=timestamp(data.get("created_at")),
            cwd=string(meta.get("cwd"), "session cwd"),
            workspace_id=string(data.get("workspace_id"), "workspace id"),
            busy=data["busy"],
            archived=data.get("archived", False),
            title=data.get("title", "") if isinstance(data.get("title", ""), str) else "",
        )


@dataclass(frozen=True)
class Transcript:
    source: Source
    items: list[dict]
    interactions: list[dict]
    attachments: list[dict]
    tasks: list[dict]
    prompts: list[dict]

    @property
    def version(self) -> str:
        return digest(
            {
                "items": self.items,
                "interactions": self.interactions,
                "attachments": self.attachments,
                "tasks": self.tasks,
                "cwd": self.source.cwd,
            }
        )


class KimiClient:
    def __init__(self, origin: str, token, config: ApiConfig, *, http: JsonHttp | None = None):
        self.origin = local_origin(origin)
        self.token = token
        self.config = config
        self.http = http or JsonHttp(
            timeout=config.request_timeout_seconds, max_bytes=config.max_response_bytes
        )
        self.server_id = ""
        self.server_version = ""
        self.started_at = 0.0
        self.unverified = False

    def raw_get(self, path: str):
        for attempt in range(2):
            credential = self.token()
            if not isinstance(credential, str) or not credential:
                raise TransportError("Kimi server authentication is unavailable")
            try:
                return self.http.request(
                    self.origin + path,
                    headers={
                        "Authorization": f"Bearer {credential}",
                    },
                )
            except TransportError as exc:
                if getattr(exc, "status", None) != 401 or attempt:
                    raise
        raise TransportError("Kimi authentication failed")

    def get(self, path: str):
        envelope = obj(self.raw_get(path), "API envelope")
        if type(envelope.get("code")) is not int or envelope["code"] != 0:
            raise TransportError("Kimi API returned a non-success envelope")
        return envelope.get("data")

    def handshake(self, expected_id: str | None = None) -> None:
        data = obj(self.get("/api/v1/meta"), "meta")
        self.server_id = string(data.get("server_id"), "server id")
        self.server_version = string(data.get("server_version"), "server version")
        self.started_at = timestamp(data.get("started_at"))
        if expected_id and self.server_id != expected_id:
            raise CompatibilityError("API server identity differs from the previous handshake")
        if data.get("dangerous_bypass_auth") is True or data.get("backend") != "v2":
            raise CompatibilityError("Expected an authenticated Kimi v2 backend")
        # Product versions are diagnostic, not a schema lock. Try the actual contract.
        self.unverified = self.server_version != "2.1.0"
        spec = obj(self.raw_get("/openapi.json"), "OpenAPI document")
        paths = obj(spec.get("paths"), "OpenAPI paths")
        for path in ("/api/v1/sessions", "/api/v1/sessions/{session_id}/transcript"):
            if not isinstance(paths.get(path), dict) or "get" not in paths[path]:
                raise CompatibilityError("Required Kimi history route is unavailable")

    def sessions(self, *, since: float, limit: int) -> list[Source]:
        result: list[Source] = []
        seen: set[str] = set()
        cursor = None
        while True:
            query: dict[str, Any] = {"page_size": self.config.page_size, "include_archive": "true"}
            if cursor:
                query["before_id"] = cursor
            page = obj(self.get("/api/v1/sessions?" + urlencode(query)), "session page")
            entries = array(page.get("items"), "sessions")
            more = page.get("has_more")
            if type(more) is not bool or (more and not entries):
                raise IncompleteHistoryError("Invalid session pagination")
            for item in entries:
                source = Source.from_json(item)
                if source.id in seen:
                    raise IncompleteHistoryError("Session pagination moved or repeated")
                seen.add(source.id)
                if source.updated_at < since:
                    return result
                result.append(source)
                if len(result) > limit:
                    raise IncompleteHistoryError(
                        "Session scan cap reached before the retention horizon"
                    )
            if not more:
                return result
            cursor = Source.from_json(entries[-1]).id

    def source(self, source_id: str) -> Source:
        data = self.get("/api/v1/sessions/" + quote(source_id, safe=""))
        source = Source.from_json(data)
        if source.id != source_id:
            raise CompatibilityError("Session identity mismatch")
        return source

    def transcript(self, source: Source) -> Transcript:
        import json

        pages: list[list[dict]] = []
        before = None
        seen_cursors: set[str] = set()
        total_bytes = 0
        global_data = None
        global_hash = None
        for _ in range(self.config.max_transcript_pages):
            query = {"agent_id": "main", "page_size": self.config.page_size}
            if before:
                query["before_turn"] = before
            page = obj(
                self.get(
                    "/api/v1/sessions/"
                    + quote(source.id, safe="")
                    + "/transcript?"
                    + urlencode(query)
                ),
                "transcript page",
            )
            total_bytes += len(json.dumps(page, ensure_ascii=False).encode())
            if total_bytes > self.config.max_transcript_bytes:
                raise IncompleteHistoryError(
                    "Transcript byte cap reached; source was not processed"
                )
            validate_page(page)
            globals_now = {
                key: page.get(key, [])
                for key in ("interactions", "attachments", "tasks", "prompts")
            }
            stamp = digest({**globals_now, "seq": page.get("seq")})
            if global_hash is not None and stamp != global_hash:
                raise IncompleteHistoryError("Transcript changed during pagination")
            global_data, global_hash = globals_now, stamp
            items = page["items"]
            pages.append(items)
            if not page["has_more"]:
                all_items = [item for entries in reversed(pages) for item in entries]
                turn_ids = [item["turnId"] for item in all_items if item["kind"] == "turn"]
                if len(turn_ids) != len(set(turn_ids)):
                    raise IncompleteHistoryError("Overlapping transcript pages")
                current = self.source(source.id)
                if current.updated_at != source.updated_at or current.busy != source.busy:
                    raise IncompleteHistoryError("Session changed during history read")
                return Transcript(source, all_items, **global_data)
            turns = [item for item in items if item["kind"] == "turn"]
            if not turns or turns[0]["turnId"] in seen_cursors:
                raise IncompleteHistoryError("Invalid transcript cursor")
            before = turns[0]["turnId"]
            seen_cursors.add(before)
        raise IncompleteHistoryError("Transcript page cap reached; source was not processed")


def validate_page(page: dict) -> None:
    if page.get("agent_id") != "main" or type(page.get("has_more")) is not bool:
        raise CompatibilityError("Invalid transcript identity or pagination flag")
    for key in ("items", "interactions", "attachments", "tasks", "prompts"):
        for value in array(page.get(key), key):
            obj(value, key)
    for item in page["items"]:
        kind = item.get("kind")
        if kind in {"marker", "taskref"}:
            continue
        if kind != "turn":
            raise CompatibilityError("Unknown transcript item kind")
        string(item.get("turnId"), "turn id")
        if item.get("state") not in {"queued", "running", "completed", "failed", "cancelled"}:
            raise CompatibilityError("Unknown turn state")
        origin = obj(item.get("origin"), "turn origin")
        if origin.get("kind") not in {
            "user",
            "cron",
            "task",
            "hook",
            "compaction",
            "side",
            "other",
        }:
            raise CompatibilityError("Unknown turn origin")
        if "prompt" in item and not isinstance(item["prompt"], str):
            raise CompatibilityError("Invalid turn prompt")
        for raw in array(item.get("steps"), "steps"):
            step = obj(raw, "step")
            string(step.get("stepId"), "step id")
            if step.get("state") not in {"running", "completed", "interrupted", "failed"}:
                raise CompatibilityError("Unknown step state")
            for raw_frame in array(step.get("frames"), "frames"):
                frame = obj(raw_frame, "frame")
                frame_kind = frame.get("kind")
                if frame_kind == "text":
                    if frame.get("role") not in {"user", "assistant"} or not isinstance(
                        frame.get("text"), str
                    ):
                        raise CompatibilityError("Invalid text frame")
                elif frame_kind == "tool":
                    string(frame.get("toolCallId"), "tool call id")
                    string(frame.get("name"), "tool name")
                    if frame.get("state") not in {"running", "done", "error"}:
                        raise CompatibilityError("Unknown tool state")
                elif frame_kind not in {"thinking", "notice"}:
                    raise CompatibilityError("Unknown frame kind")
    for interaction in page["interactions"]:
        string(interaction.get("interactionId"), "interaction id")
        if interaction.get("interactionKind") not in {"question", "approval"}:
            raise CompatibilityError("Unknown interaction kind")
        if interaction.get("state") not in {
            "pending",
            "approved",
            "rejected",
            "cancelled",
            "answered",
            "dismissed",
        }:
            raise CompatibilityError("Unknown interaction state")
        if (
            interaction.get("interactionKind") == "question"
            and interaction.get("state") == "answered"
        ):
            if interaction.get("request") is None or interaction.get("response") is None:
                raise CompatibilityError(
                    "Answered question is missing its request or human response"
                )

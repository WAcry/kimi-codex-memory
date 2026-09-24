import copy
import json
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from kimi_memory.cli import initialize
from kimi_memory.config import ApiConfig, GenerationConfig, WorkerConfig
from kimi_memory.files import atomic_write, write_json
from kimi_memory.kimi import Source, Transcript
from kimi_memory.workspace import HEADINGS, ensure_layout


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


def valid_summary(body=""):
    return "v1\n\n" + "\n\n".join(HEADINGS) + "\n" + body + "\n"


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    home = tmp_path / "memory"
    kimi = tmp_path / "kimi"
    kimi.mkdir()
    atomic_write(kimi / "server.token", "test-native-token-never-log")
    monkeypatch.setenv("KIMI_MEMORY_HOME", str(home))
    monkeypatch.setenv("KIMI_CODE_HOME", str(kimi))
    monkeypatch.setenv("KIMI_MEMORY_NO_AUTOSTART", "1")
    monkeypatch.setenv("KIMI_MEMORY_API_KEY", "test-model-token-never-log")
    for key in ("KIMI_MEMORY_READER_CONFIG", "KIMI_MEMORY_WORKER_CONFIG", "KIMI_MEMORY_INTERNAL"):
        monkeypatch.delenv(key, raising=False)
    initialize(home)
    yield


@pytest.fixture
def home(tmp_path):
    return tmp_path / "memory"


@pytest.fixture
def config():
    return WorkerConfig(
        api=ApiConfig(auto_start=False),
        generation=GenerationConfig(
            consolidation_cooldown_seconds=0,
            retry_delay_seconds=0,
            lease_seconds=60,
            heartbeat_seconds=1,
        ),
    )


@pytest.fixture
def source():
    now = float(int(time.time()))
    return Source(
        "session_example", now - 36000, now - 40000, "/workspace/example", "workspace_example"
    )


def source_json(source):
    return {
        "id": source.id,
        "workspace_id": source.workspace_id,
        "title": source.title,
        "created_at": iso(source.created_at),
        "updated_at": iso(source.updated_at),
        "busy": source.busy,
        "archived": source.archived,
        "metadata": {"cwd": source.cwd},
    }


def turn(source, ordinal=1, text="The task was verified."):
    ended = iso(source.updated_at - 60 + ordinal)
    return {
        "kind": "turn",
        "turnId": f"t{ordinal}",
        "ordinal": ordinal,
        "state": "completed",
        "origin": {"kind": "user"},
        "triggerPromptId": f"prompt_{source.id}_{ordinal}",
        "prompt": "Please preserve exact task scope. RAW-INPUT-NOT-FOR-DURABLE-STORAGE",
        "startedAt": iso(source.updated_at - 120 + ordinal),
        "endedAt": ended,
        "steps": [
            {
                "kind": "step",
                "stepId": f"t{ordinal}.1",
                "turnId": f"t{ordinal}",
                "ordinal": 1,
                "state": "completed",
                "endedAt": ended,
                "frames": [
                    {
                        "kind": "text",
                        "frameId": f"t{ordinal}.1.f1",
                        "role": "assistant",
                        "text": text,
                    }
                ],
            }
        ],
    }


@pytest.fixture
def transcript(source):
    return Transcript(source, [turn(source)], [], [], [], [])


def transcript_page(transcript, items=None, more=False):
    return {
        "agent_id": "main",
        "items": transcript.items if items is None else items,
        "has_more": more,
        "interactions": transcript.interactions,
        "attachments": transcript.attachments,
        "tasks": transcript.tasks,
        "prompts": transcript.prompts,
        "meta": {},
        "agents": [{"agentId": "main"}],
        "pending_interactions": [],
    }


def seed_published(home, body="Previously published user preference."):
    ensure_layout(home)
    generation = uuid.uuid4().hex
    directory = home / "_generations" / generation
    (directory / "rollout_summaries").mkdir(parents=True)
    atomic_write(directory / "memory_summary.md", valid_summary(body))
    write_json(
        directory / "_manifest.json",
        {
            "format": 1,
            "generation": generation,
            "input_hash": "seed",
            "published_at": time.time(),
            "sources": [],
        },
    )
    write_json(home / "current.json", {"format": 1, "generation": generation})
    return directory


@contextmanager
def serve(callback):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def dispatch(self):
            size = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(size) if size else b""
            if self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
                body = {key: values[0] for key, values in parse_qs(raw.decode()).items()}
            else:
                body = json.loads(raw) if size else None
            requests.append((self.command, self.path, body, dict(self.headers)))
            status, payload, *extra = callback(self.command, self.path, body, dict(self.headers))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if extra:
                for name, value in extra[0].items():
                    self.send_header(name, value)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        do_GET = dispatch
        do_POST = dispatch

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class NativeApi:
    def __init__(self, transcripts, version="2.1.0"):
        self.transcripts = {t.source.id: t for t in transcripts}
        self.version = version
        self.started_at = iso(time.time())
        self.overrides = {}

    def __call__(self, method, path, body, headers):
        path, query = urlsplit(path).path, parse_qs(urlsplit(path).query)
        if headers.get("Authorization") != "Bearer test-native-token-never-log":
            return 401, {"error": "no auth"}
        if path in self.overrides:
            return self.overrides[path]
        if path == "/openapi.json":
            return 200, {
                "paths": {
                    "/api/v1/sessions": {"get": {}},
                    "/api/v1/sessions/{session_id}/transcript": {"get": {}},
                }
            }
        if path == "/api/v1/meta":
            data = {
                "server_id": "test-native",
                "server_version": self.version,
                "backend": "v2",
                "dangerous_bypass_auth": False,
                "started_at": self.started_at,
            }
        elif path == "/api/v1/config":
            data = {}
        elif path == "/api/v1/sessions":
            sources = sorted(
                (t.source for t in self.transcripts.values()),
                key=lambda s: (s.updated_at, s.id),
                reverse=True,
            )
            cursor = query.get("before_id", [None])[0]
            if cursor:
                sources = sources[next(i for i, s in enumerate(sources) if s.id == cursor) + 1 :]
            size = int(query.get("page_size", [100])[0])
            data = {
                "items": [source_json(s) for s in sources[:size]],
                "has_more": len(sources) > size,
            }
        elif path.startswith("/api/v1/sessions/"):
            parts = path[len("/api/v1/sessions/") :].split("/")
            source_id = unquote(parts[0])
            transcript = self.transcripts.get(source_id)
            if not transcript:
                return 404, {"code": 40401}
            if len(parts) == 1:
                data = source_json(transcript.source)
            else:
                items = transcript.items
                before = query.get("before_turn", [None])[0]
                if before:
                    items = items[
                        : next(i for i, item in enumerate(items) if item.get("turnId") == before)
                    ]
                size = int(query.get("page_size", [100])[0])
                data = transcript_page(transcript, items[-size:], len(items) > size)
        else:
            return 404, {}
        return 200, {"code": 0, "data": copy.deepcopy(data)}


class ScriptModel:
    def __init__(
        self,
        *,
        summary="# Task\nThe user requested exact scope; the result was verified.",
        fail=False,
    ):
        self.summary, self.fail = summary, fail
        self.calls = []

    def ready(self):
        pass

    def complete(self, messages, *, tools=None, json_mode=False):
        from kimi_memory.errors import ModelError

        self.calls.append(copy.deepcopy(messages))
        if self.fail:
            raise ModelError("Synthetic model failure")
        if tools is None:
            return {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "rollout_summary": self.summary,
                        "rollout_slug": "exact-scope" if self.summary else "",
                    }
                ),
            }
        tool_messages = [m for m in messages if m["role"] == "tool"]
        count = len(tool_messages)
        if count == 0:
            name, args = "read_file", {"path": "phase2_workspace_diff.md"}
        elif count == 1:
            name, args = "list_files", {}
        elif count == 2:
            names = json.loads(tool_messages[-1]["content"])["files"]
            source = next(
                (n for n in names if n.startswith("rollout_summaries/")),
                "extensions/ad_hoc/instructions.md",
            )
            name, args = "read_file", {"path": source}
        elif count == 3:
            names = json.loads(tool_messages[1]["content"])["files"]
            pointers = [name for name in names if name.startswith("rollout_summaries/")]
            body = "\n".join("- " + name + " — exact prior task context" for name in pointers)
            name, args = "write_summary", {"content": valid_summary(body)}
        else:
            return {"role": "assistant", "content": "Done"}
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"call-{count}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ],
        }

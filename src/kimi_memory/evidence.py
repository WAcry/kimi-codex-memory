"""Normalize native transcripts and preserve human evidence before budgeting."""

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .files import utf8_head
from .kimi import Transcript

TIERS = {"Human": 0, "Final": 1, "OtherAgent": 2, "Commentary": 3, "Context": 4, "Tool": 5}
SECRET_NAMES = r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|authorization|signature|token)"
ASSIGNMENT = re.compile(rf"(?i)(\b{SECRET_NAMES}[\"']?\s*[:=]\s*[\"']?)([^\s\"'&,<>]+)")
URLS = re.compile(r"https?://[^\s<>\"']+")
PRIVATE_KEY = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.S)


def redact(text: str) -> str:
    text = PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", text)
    text = re.sub(
        r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
        "[REDACTED]",
        text,
    )
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED JWT]", text)

    def clean_url(match):
        try:
            parts = urlsplit(match.group())
            netloc = parts.netloc.rsplit("@", 1)[-1]
            keys = re.compile(
                r"(?i)(token|key|secret|pass|signature|credential|authorization|^sig$|^code$)"
            )
            query = urlencode(
                [
                    (k, "[REDACTED]" if keys.search(k) else v)
                    for k, v in parse_qsl(parts.query, keep_blank_values=True)
                ]
            )
            fragment = "[REDACTED]" if keys.search(parts.fragment) else parts.fragment
            return urlunsplit((parts.scheme, netloc, parts.path, query, fragment))
        except ValueError:
            return "[REDACTED URL]"

    text = URLS.sub(clean_url, text)
    return ASSIGNMENT.sub(lambda m: m.group(1) + "[REDACTED]", text)


def estimate_tokens(text: str) -> int:
    # Same estimate used by Kimi's llm-adapter/contract/tokens.ts, not an exact tokenizer.
    ascii_count = sum(ord(ch) <= 127 for ch in text)
    return (ascii_count + 3) // 4 + len(text) - ascii_count


def clip_tokens(text: str, budget: int) -> str:
    if estimate_tokens(text) <= budget:
        return text
    marker = "\n[... evidence omitted for budget ...]\n"
    available = budget - estimate_tokens(marker)
    if available <= 0:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[: mid // 2] + text[len(text) - (mid - mid // 2) :]
        if estimate_tokens(candidate) <= available:
            lo = mid
        else:
            hi = mid - 1
    return text[: lo // 2] + marker + text[len(text) - (lo - lo // 2) :]


@dataclass(frozen=True)
class Evidence:
    tier: str
    text: str
    sequence: int


def _json(value: object) -> str:
    return json.dumps(_without_media_bytes(value), ensure_ascii=False, sort_keys=True)


def _without_media_bytes(value):
    if isinstance(value, str):
        if value.startswith(("data:", "blobref:")):
            return "[inline or blob media omitted; content not inspected]"
        return value
    if isinstance(value, list):
        return [_without_media_bytes(item) for item in value]
    if isinstance(value, dict):
        if value.get("kind") == "base64" or value.get("type") == "base64":
            return {
                "kind": "media_placeholder",
                "media_type": value.get("media_type"),
                "note": "Media bytes are omitted",
            }
        return {key: _without_media_bytes(item) for key, item in value.items()}
    return value


def normalize(transcript: Transcript, *, memory_root: str = "") -> list[Evidence]:
    result: list[Evidence] = []
    answered: set[str] = set()
    questions: dict[str, list[dict]] = {}
    for interaction in transcript.interactions:
        if interaction.get("interactionKind") == "question":
            questions.setdefault(interaction.get("toolCallId", ""), []).append(interaction)
    attachments = {item.get("attachmentId"): item for item in transcript.attachments}

    def add(tier: str, text: str) -> None:
        if text.strip():
            result.append(Evidence(tier, redact(text), len(result)))

    def add_attachments(ids) -> None:
        for attachment_id in ids or []:
            item = attachments.get(attachment_id, {})
            add(
                "Context",
                _json(
                    {
                        "attachment": attachment_id,
                        "media_type": item.get("mediaType"),
                        "name": item.get("name"),
                        "source": item.get("source"),
                        "note": "Media bytes are not part of this text-only extraction",
                    }
                ),
            )

    def add_question(item: dict) -> None:
        if item.get("state") != "answered" or item["interactionId"] in answered:
            return
        answered.add(item["interactionId"])
        add(
            "Human",
            "Human answer to question (not an assistant suggestion):\n"
            + _json(
                {
                    "question": item.get("request"),
                    "answer": item.get("response"),
                }
            ),
        )

    for turn in transcript.items:
        if turn.get("kind") != "turn":
            # Injection and compaction markers are not human evidence.
            continue
        origin = turn["origin"]["kind"]
        add(
            "Context",
            _json(
                {
                    "turn": turn["turnId"],
                    "origin": origin,
                    "state": turn["state"],
                    "started_at": turn.get("startedAt"),
                    "ended_at": turn.get("endedAt"),
                }
            ),
        )
        prompt_tier = (
            "Human" if origin == "user" else "OtherAgent" if origin == "task" else "Context"
        )
        if origin not in {"hook", "compaction"}:
            add(prompt_tier, turn.get("prompt", ""))
        add_attachments(turn.get("attachmentIds"))
        for step in turn["steps"]:
            has_tools = any(frame.get("kind") == "tool" for frame in step["frames"])
            for frame in step["frames"]:
                if frame["kind"] == "text":
                    if frame["role"] == "assistant":
                        text = re.sub(
                            r"<oai-mem-citation>.*?</oai-mem-citation>",
                            "",
                            frame["text"],
                            flags=re.S,
                        )
                        tier = (
                            "Final"
                            if step["state"] == "completed" and not has_tools
                            else "Commentary"
                        )
                    else:
                        text = frame["text"]
                        origin_data = frame.get("origin") or {}
                        human = origin_data.get("kind") in {"user", "skill_activation"}
                        tier = (
                            "Human" if human else "OtherAgent" if frame.get("taskId") else "Context"
                        )
                    add(tier, text)
                    add_attachments(frame.get("attachmentIds"))
                elif frame["kind"] == "tool":
                    for item in questions.get(frame["toolCallId"], []):
                        add_question(item)
                    if memory_root and memory_root in _json(frame.get("input")):
                        add(
                            "Context",
                            "A tool read existing memory; its historical contents are not new human evidence.",
                        )
                        continue
                    add(
                        "Tool",
                        _json(
                            {
                                "tool": frame["name"],
                                "state": frame["state"],
                                "input": frame.get("input"),
                                "output": frame.get("output"),
                            }
                        ),
                    )
                elif frame["kind"] == "notice":
                    add("Context", str(frame.get("message", "")))
                # Thinking frames are deliberately excluded.
    for item in transcript.interactions:
        if item.get("interactionKind") == "question":
            add_question(item)
    return result


def budget_evidence(evidence: list[Evidence], *, max_tokens: int, max_tool_bytes: int) -> str:
    selected: dict[int, str] = {}
    remaining = max(0, max_tokens - 64)
    for item in sorted(evidence, key=lambda e: (TIERS[e.tier], -e.sequence)):
        text = item.text
        if item.tier == "Tool" and len(text.encode()) > max_tool_bytes:
            text = utf8_head(text, max_tool_bytes - 32) + "\n[Tool evidence truncated]"
        header = f"[{item.tier} evidence #{item.sequence}]\n"
        allowance = remaining - estimate_tokens(header) - 1
        if allowance <= 0:
            continue
        text = clip_tokens(text, allowance)
        if not text:
            continue
        block = header + text + "\n"
        cost = estimate_tokens(block)
        if cost <= remaining:
            selected[item.sequence] = block
            remaining -= cost
    parts = [selected[key] for key in sorted(selected)]
    omitted = len(evidence) - len(selected)
    if omitted:
        parts.append(
            f"[{omitted} evidence blocks omitted for input budget; absence is not evidence.]\n"
        )
    return "".join(parts)

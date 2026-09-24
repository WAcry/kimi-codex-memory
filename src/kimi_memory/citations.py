"""Citation output is a model convention; receipts make subsequent replay idempotent."""

import re
from dataclasses import dataclass

from .errors import IncompleteHistoryError
from .files import digest
from .kimi import Transcript, timestamp


def citation_ids(text: str) -> set[str]:
    outside: list[str] = []
    fence = ""
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            outside.append("")
        elif not fence:
            outside.append(line)
    raw = "\n".join(outside).rstrip()
    block = re.search(
        r"<oai-mem-citation>((?:(?!<oai-mem-citation>).)*)</oai-mem-citation>$", raw, re.S
    )
    if block is None:
        return set()
    ids = re.search(r"<rollout_ids>(.*?)</rollout_ids>", block.group(1), re.S)
    if ids is None:
        return set()
    return {
        line.strip()
        for line in ids.group(1).splitlines()
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,511}", line.strip())
    }


@dataclass(frozen=True)
class CitationUse:
    event_key: str
    source_ids: frozenset[str]
    used_at: float


def collect_citations(transcript: Transcript) -> list[CitationUse]:
    result = []
    prompt_times = {p.get("promptId"): p.get("finishedAt") for p in transcript.prompts}
    for turn in transcript.items:
        if turn.get("kind") != "turn":
            continue
        for step in turn["steps"]:
            if step["state"] != "completed":
                continue
            text = "".join(
                f["text"]
                for f in step["frames"]
                if f.get("kind") == "text" and f.get("role") == "assistant"
            )
            source_ids = citation_ids(text)
            if not source_ids:
                continue
            ended = (
                step.get("endedAt")
                or turn.get("endedAt")
                or prompt_times.get(turn.get("triggerPromptId"))
            )
            if ended is None:
                raise IncompleteHistoryError(
                    "Cited assistant output lacks a reliable completion timestamp"
                )
            used_at = timestamp(ended)
            prompt_id = turn.get("triggerPromptId")
            # Native cold step IDs are display ordinals, not raw completion UUIDs.
            # Forked history preserves prompt identity and timestamps. Use those, not the
            # containing session ID, so copying history cannot create new usage.
            identity = {
                "prompt": prompt_id,
                "ended_at": ended,
                "ordinal": step.get("ordinal", step["stepId"].rsplit(".", 1)[-1]),
                "text_hash": digest(text),
            }
            result.append(CitationUse(digest(identity), frozenset(source_ids), used_at))
    return result

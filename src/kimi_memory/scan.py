"""Read independent session snapshots; never confuse a failed read with empty history."""

import fnmatch
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from .citations import collect_citations
from .config import WorkerConfig
from .errors import IncompleteHistoryError, MemoryErrorBase, MissingSessionError, TransportError
from .files import read_json
from .issues import Issues
from .kimi import KimiClient, Transcript
from .store import Store


def allowed(source_id: str, cwd: str, config: WorkerConfig) -> bool:
    def matches(pattern: str) -> bool:
        value, pattern = cwd.replace("\\", "/"), pattern.replace("\\", "/")
        if os.name == "nt":
            value, pattern = value.casefold(), pattern.casefold()
        return fnmatch.fnmatchcase(value, pattern)

    gen = config.generation
    return (
        source_id not in gen.exclude_session_ids
        and not any(matches(p) for p in gen.exclude_cwds)
        and (not gen.include_cwds or any(matches(p) for p in gen.include_cwds))
    )


def clean_events(events: list, now: float) -> list[dict]:
    result = []
    for event in events:
        if not isinstance(event, dict):
            continue
        identity, kind, stamp = event.get("session_id"), event.get("event"), event.get("time", now)
        if (
            not isinstance(identity, str)
            or not 1 <= len(identity) <= 1024
            or not isinstance(kind, str)
            or kind
            not in {"SessionStart", "TurnStarted", "Stop", "SessionEnd", "Interrupt", "StopFailure"}
            or type(stamp) not in (int, float)
        ):
            continue
        try:
            stamp = float(stamp)
        except (OverflowError, ValueError):
            continue
        if not math.isfinite(stamp):
            continue
        result.append({"session_id": identity, "event": kind, "time": stamp})
    return result


@dataclass
class ScanResult:
    inputs: list[Transcript] = field(default_factory=list)
    citations: int = 0
    complete: bool = True
    acknowledged: set[str] = field(default_factory=set)
    missing: int = 0


def collect_inputs(
    client: KimiClient,
    store: Store,
    config: WorkerConfig,
    home: Path,
    events: list[dict],
    now: float,
    issues: Issues,
) -> ScanResult:
    gen = config.generation
    result = ScanResult()
    events = clean_events(events, now)
    forced = {event["session_id"] for event in events}
    recent = now - max(3600, gen.min_idle_hours * 3600)
    current_ids = {
        event["session_id"]
        for event in events
        if event["event"] in {"SessionStart", "TurnStarted"} and event["time"] >= recent
    }

    def failed(exc, identity=None, stage="history"):
        result.complete = False
        issues.add(stage, exc, identity)

    sources = client.sessions(
        since=now - gen.retention_days * 86400,
        limit=gen.max_session_scan,
        on_error=lambda exc, identity: failed(exc, identity, "session_list"),
    )
    known = {source.id for source in sources}
    for identity in sorted(forced - known):
        if identity in gen.exclude_session_ids:
            result.acknowledged.add(identity)
            continue
        try:
            sources.append(client.source(identity))
        except MissingSessionError:
            result.missing += 1
            result.acknowledged.add(identity)
        except (MemoryErrorBase, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            failed(exc, identity)
            if isinstance(exc, TransportError) and (
                exc.unavailable or exc.status in {401, 403, 429}
            ):
                break

    active = set()
    for path in (home / "activity").glob("*.json"):
        try:
            data = read_json(path, 4096)
            if data.get("active") and data.get("time", 0) > recent:
                active.add(data["session_id"])
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue

    for source in sorted(sources, key=lambda item: (item.updated_at, item.id), reverse=True):
        if not allowed(source.id, source.cwd, config):
            result.acknowledged.add(source.id)
            continue
        extract = (
            not source.busy
            and not source.archived
            and source.id not in active
            and source.id not in current_ids
            and gen.min_idle_hours * 3600
            <= now - source.updated_at
            <= gen.source_max_age_days * 86400
            and len(result.inputs) < gen.max_extractions
            and store.extraction_due(source, now)
        )
        if not extract and store.scan_is_current(source) and source.id not in forced:
            result.acknowledged.add(source.id)
            continue
        try:
            transcript = client.transcript(source)
            before = issues.count
            uses = collect_citations(
                transcript,
                now=now,
                on_error=lambda exc, identity=source.id: failed(exc, identity, "citation"),
            )
            version = transcript.version
        except MissingSessionError:
            result.missing += 1
            result.acknowledged.add(source.id)
            continue
        except (MemoryErrorBase, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            failed(exc, source.id)
            if isinstance(exc, TransportError) and (
                exc.unavailable or exc.status in {401, 403, 429}
            ):
                break
            continue
        # Storage failures remain global. Valid receipts from this source are one
        # transaction; no failed or partially read source gets a success watermark.
        result.citations += store.record_citations(uses, now=now)
        empty_existing = (
            extract
            and not any(item.get("kind") == "turn" for item in transcript.items)
            and store.has_summary(source.id)
        )
        if empty_existing:
            failed(IncompleteHistoryError("Existing source has no readable turns"), source.id)
        if issues.count == before:
            store.scanned(source, version, now)
            result.acknowledged.add(source.id)
        if extract:
            if any(item.get("kind") == "turn" for item in transcript.items):
                result.inputs.append(transcript)
    return result

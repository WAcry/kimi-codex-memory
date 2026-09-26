"""Offline prompt rendering. No database, API, worker, or model imports here."""

import os
import time
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import BusyError, UnsafePathError
from .files import (
    atomic_write,
    digest,
    memory_home,
    published_root,
    read_json,
    snapshot_lock,
    utf8_head,
    write_json,
)


@dataclass(frozen=True)
class ReaderConfig:
    enabled: bool = True
    max_summary_bytes: int = 10_000


def _parse_reader(raw: object) -> ReaderConfig:
    allowed = asdict(ReaderConfig())
    if not isinstance(raw, dict) or set(raw) - set(allowed):
        raise ValueError("Unknown reader option")
    config = ReaderConfig(**raw)
    if any(type(getattr(config, k)) is not type(v) for k, v in allowed.items()):
        raise ValueError("Invalid reader option type")
    if not 256 <= config.max_summary_bytes <= 131_072:
        raise ValueError("Invalid reader byte limit")
    return config


def load_reader_config(home: Path) -> ReaderConfig:
    path = Path(os.environ.get("KIMI_MEMORY_READER_CONFIG", str(home / "reader.toml")))
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        config = _parse_reader(raw)
        try:
            write_json(home / "reader-last-good.json", asdict(config))
        except OSError:
            pass
        return config
    except (OSError, ValueError, TypeError):
        # Writer configuration is separate; even a broken reader edit falls back locally.
        try:
            saved = read_json(home / "reader-last-good.json")
            return _parse_reader(saved)
        except (OSError, ValueError, TypeError):
            pass
        return ReaderConfig()


def _notes_only(home: Path) -> str:
    template = (Path(__file__).parent / "prompts/notes_only.md").read_text(encoding="utf-8")
    return template.replace(
        "{{ notes_path }}", (home / "memories_v2/extensions/ad_hoc/notes").as_posix()
    )


@dataclass(frozen=True)
class RenderedMemory:
    text: str
    generation: str | None = None
    summary_hash: str | None = None


def _render_snapshot(home: Path, config: ReaderConfig) -> RenderedMemory:
    """Caller holds snapshot_lock through selection, read and optional pin registration."""
    if not config.enabled:
        return RenderedMemory("")
    try:
        root = published_root(home)
    except (OSError, ValueError, UnsafePathError):
        return RenderedMemory(_notes_only(home))
    if root is None:
        return RenderedMemory(_notes_only(home))
    summary = ""
    try:
        with (root / "memory_summary.md").open("rb") as handle:
            raw = handle.read(config.max_summary_bytes + 1)
        summary = raw[: config.max_summary_bytes].decode("utf-8", errors="ignore")
        if len(raw) > config.max_summary_bytes:
            marker = "\n[Summary truncated; read the local summary file for remaining routes.]"
            summary = utf8_head(summary, config.max_summary_bytes - len(marker.encode())) + marker
    except (OSError, ValueError):
        pass
    if not summary.strip():
        # Keep explicit note writing discoverable without inventing history or citations.
        return RenderedMemory(_notes_only(home))
    template = (Path(__file__).parent / "prompts/read_path_v2.md").read_text(encoding="utf-8")
    text = (
        template.replace("{{ base_path }}", root.as_posix())
        .replace("{{ notes_path }}", (home / "memories_v2/extensions/ad_hoc/notes").as_posix())
        .replace("{{ memory_summary }}", summary)
    )
    return RenderedMemory(text, root.name, digest(summary))


def render(home: Path | None = None) -> str:
    home = home or memory_home()
    config = load_reader_config(home)
    try:
        with snapshot_lock(home):
            return _render_snapshot(home, config).text
    except BusyError:
        return _notes_only(home) if config.enabled else ""
    except OSError:
        # A read-only bookkeeping directory is not a reason to disable local
        # file reading. Without a writable lock/pin, this is explicitly best effort.
        return _render_snapshot(home, config).text


def _receipt_path(home: Path, session_id: str) -> Path:
    return home / "injections" / f"{digest(session_id)}.json"


def _read_receipt(home: Path, session_id: str) -> dict:
    try:
        value = read_json(_receipt_path(home, session_id), 8192)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _generation_exists(home: Path, value: object) -> bool:
    if value is None:
        return True
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(c not in "0123456789abcdef" for c in value)
    ):
        return False
    root = home / "_generations" / value
    return not root.is_symlink() and root.is_dir() and (root / "memory_summary.md").is_file()


def _prompt_hashes(prompt: object) -> list[str]:
    if isinstance(prompt, str):
        return [digest(prompt)]
    parts = (
        [
            p["text"]
            for p in prompt
            if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str)
        ]
        if isinstance(prompt, list)
        else []
    )
    # TurnStarted strips bundled Skill text blocks. Store only a few suffix hashes,
    # never the user's text; the normal whole-text hash always participates.
    texts = ["".join(parts)]
    texts.extend("".join(parts[index:]) for index in range(max(1, len(parts) - 8), len(parts)))
    return sorted({digest(text) for text in texts})


def injection_for(session_id: str, home: Path | None = None, *, prompt: object = None) -> str:
    home = home or memory_home()
    config = load_reader_config(home)
    if not config.enabled:
        return ""
    prepared = None
    try:
        with snapshot_lock(home):
            state = _read_receipt(home, session_id)
            if state.get("checked") and _generation_exists(home, state.get("generation")):
                state["last_seen"] = time.time()
                write_json(_receipt_path(home, session_id), state)
                return ""
            prepared = _render_snapshot(home, config)
            if state.get("checked") and state.get("generation") and prepared.text:
                prepared = RenderedMemory(
                    "The earlier memory snapshot is no longer available. Use this refreshed memory context instead.\n\n"
                    + prepared.text,
                    prepared.generation,
                    prepared.summary_hash,
                )
            now = time.time()
            write_json(
                _receipt_path(home, session_id),
                {
                    "phase": "prepared",
                    "checked": False,
                    "injected": False,
                    "generation": prepared.generation,
                    "summary_hash": prepared.summary_hash,
                    "prompt_hashes": _prompt_hashes(prompt),
                    "time": now,
                    "last_seen": now,
                },
            )
    except BusyError:
        # No false delivery acknowledgement. Lock contention retries at the next
        # input; a bookkeeping write failure still permits an already read prompt.
        return prepared.text if prepared else ""
    except OSError:
        return prepared.text if prepared else _render_snapshot(home, config).text
    return prepared.text


def acknowledge_injection(session_id: str, payload: dict, home: Path | None = None) -> None:
    """Best-effort acknowledgement from a matched user turn after Kimi's prompt gate.

    This is not a durable exactly-once guarantee. A lost or mismatched event can
    cause one repeat rather than permanently losing the only memory injection.
    """
    if payload.get("origin_kind") != "user" or type(payload.get("turn_id")) not in (str, int):
        return
    home = home or memory_home()
    try:
        with snapshot_lock(home):
            state = _read_receipt(home, session_id)
            if state.get("phase") != "prepared" or not set(
                _prompt_hashes(payload.get("prompt"))
            ) & set(state.get("prompt_hashes", [])):
                return
            state.update(
                phase="committed",
                checked=True,
                injected=True,
                last_seen=time.time(),
                turn_id=payload["turn_id"],
            )
            state.pop("prompt_hashes", None)
            write_json(_receipt_path(home, session_id), state)
    except (OSError, BusyError, TypeError):
        pass


def touch_injection(session_id: str, home: Path | None = None) -> None:
    """Refresh only the snapshot pin, without injecting or claiming delivery."""
    home = home or memory_home()
    try:
        with snapshot_lock(home):
            state = _read_receipt(home, session_id)
            if state:
                state["last_seen"] = time.time()
                write_json(_receipt_path(home, session_id), state)
    except (OSError, BusyError):
        pass


def reset_injection(session_id: str, home: Path | None = None) -> None:
    home = home or memory_home()
    try:
        with snapshot_lock(home):
            atomic_write(_receipt_path(home, session_id), "{}\n")
    except (OSError, BusyError):
        pass

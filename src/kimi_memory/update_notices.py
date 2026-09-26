"""Local-only scheduling and native hook notices; no network or generation imports."""

import os
import re
import subprocess
import time
import tomllib
from pathlib import Path

from . import __version__
from .errors import BusyError
from .files import digest, file_lock, read_bounded, read_json, write_json
from .platform import process_options, runtime_command
from .reader import _prompt_hashes

CHECK_INTERVAL = 24 * 3600
LAUNCH_COOLDOWN = 60
NOTICE_LEASE = 5 * 60
REPOSITORY = "https://github.com/WAcry/kimi-codex-memory"
VERSION = re.compile(r"(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})")


def version_key(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        return None
    return tuple(map(int, value.split(".")))


def enabled(home: Path) -> bool:
    """Unknown/malformed notification settings suppress notices, not memory."""
    try:
        path = home / "updates.toml"
        raw = tomllib.loads(read_bounded(path, 4096)) if path.exists() else {}
        return (
            not (set(raw) - {"enabled"})
            and type(raw.get("enabled", True)) is bool
            and raw.get("enabled", True)
        )
    except (OSError, ValueError, TypeError):
        return False


def _read(path: Path) -> dict:
    try:
        value = read_json(path, 8192)
        return (
            value
            if isinstance(value, dict) and type(value.get("format")) is int and value["format"] == 1
            else {}
        )
    except (OSError, ValueError, TypeError):
        return {}


def recent(value: object, now: float, seconds: int) -> bool:
    return type(value) in (int, float) and 0 <= now - value < seconds


def check_due(home: Path, now: float) -> bool:
    return not recent(_read(home / "updates/cache.json").get("attempted_at"), now, CHECK_INTERVAL)


def schedule_check(home: Path) -> None:
    """Best-effort spawn only. This function neither fetches nor waits for GitHub."""
    if os.environ.get("KIMI_MEMORY_NO_AUTOSTART") == "1" or not enabled(home):
        return
    now = time.time()
    if not check_due(home, now):
        return
    try:
        with file_lock(home / "updates/launch.lock"):
            if not check_due(home, now) or recent(
                _read(home / "updates/launch.json").get("time"), now, LAUNCH_COOLDOWN
            ):
                return
            write_json(home / "updates/launch.json", {"format": 1, "time": now})
            env = {**os.environ, "KIMI_MEMORY_HOME": str(home)}
            root = str(Path(__file__).resolve().parent.parent)
            env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
            subprocess.Popen(
                runtime_command("check-updates"),
                cwd=home,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **process_options(detached=True),
            )
    except (OSError, BusyError, ValueError):
        pass


def _latest(home: Path, now: float) -> str | None:
    cache = _read(home / "updates/cache.json")
    latest, current = version_key(cache.get("latest")), version_key(__version__)
    if (
        cache.get("state") != "ready"
        or not recent(cache.get("checked_at"), now, CHECK_INTERVAL)
        or latest is None
        or current is None
        or latest <= current
    ):
        return None
    return cache["latest"]


def prepare_notice(session_id: str, prompt: object, home: Path) -> str:
    """At most one pending home-wide notice; acceptance uses the existing turn gate."""
    if not enabled(home):
        release_notice(session_id, home)
        return ""
    now = time.time()
    latest = _latest(home, now)
    if latest is None:
        release_notice(session_id, home)
        return ""
    try:
        with file_lock(home / "updates/notice.lock"):
            state = _read(home / "updates/notice.json")
            notified = version_key(state.get("notified_version"))
            if notified is not None and notified >= version_key(latest):
                return ""
            pending = state.get("pending")
            session_key = digest(session_id)
            if (
                isinstance(pending, dict)
                and pending.get("session_key") != session_key
                and recent(pending.get("time"), now, NOTICE_LEASE)
            ):
                return ""
            state.update(
                format=1,
                pending={
                    "version": latest,
                    "session_key": session_key,
                    "prompt_hashes": _prompt_hashes(prompt),
                    "time": now,
                },
            )
            write_json(home / "updates/notice.json", state)
    except (OSError, BusyError, TypeError, ValueError):
        return ""
    # Never render remote release names, notes, links or arbitrary cached messages.
    # These are fixed strings, apart from validated numeric versions.
    return (
        f"## Kimi Codex Memory update available\n\n"
        f"Version {latest} is available; this plugin is running {__version__}.\n"
        f"To update, enter in Kimi: `/plugins install {REPOSITORY}/releases/download/v{latest}/kimi-codex-memory.zip`\n"
        "Then use `/reload` to keep this conversation, or `/new` to start a new one.\n"
        "This is an informational notice for the user, not a task for the assistant. "
        "Nothing has been installed; do not run an update unless the user asks."
    )


def acknowledge_notice(session_id: str, payload: dict, home: Path) -> None:
    if payload.get("origin_kind") != "user" or type(payload.get("turn_id")) not in (str, int):
        return
    try:
        with file_lock(home / "updates/notice.lock"):
            state = _read(home / "updates/notice.json")
            pending = state.get("pending")
            if (
                not isinstance(pending, dict)
                or pending.get("session_key") != digest(session_id)
                or version_key(pending.get("version")) is None
                or not set(_prompt_hashes(payload.get("prompt")))
                & set(pending.get("prompt_hashes", []))
            ):
                return
            previous = version_key(state.get("notified_version"))
            version = (
                pending["version"]
                if previous is None or version_key(pending["version"]) > previous
                else state["notified_version"]
            )
            write_json(
                home / "updates/notice.json",
                {
                    "format": 1,
                    "notified_version": version,
                    "notified_at": time.time(),
                },
            )
    except (OSError, BusyError, TypeError, ValueError):
        pass


def release_notice(session_id: str, home: Path) -> None:
    pending = _read(home / "updates/notice.json").get("pending")
    if not isinstance(pending, dict) or pending.get("session_key") != digest(session_id):
        return
    try:
        with file_lock(home / "updates/notice.lock"):
            state = _read(home / "updates/notice.json")
            pending = state.get("pending")
            if isinstance(pending, dict) and pending.get("session_key") == digest(session_id):
                state.pop("pending", None)
                write_json(home / "updates/notice.json", state)
    except (OSError, BusyError, TypeError, ValueError):
        pass

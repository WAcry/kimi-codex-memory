"""Fail-open Kimi hooks: render locally first, then best-effort wake a separate process."""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .files import digest, memory_home, private_dir, write_json
from .reader import injection_for, reset_injection

WAKE_EVENTS = {"SessionStart", "TurnStarted", "Stop", "SessionEnd", "Interrupt", "StopFailure"}


def enqueue(payload: dict, home: Path) -> None:
    event = payload.get("hook_event_name", "")
    session_id = payload.get("session_id", "")
    # Never persist prompts, responses, attachments, or the complete hook payload.
    data = {"event": event, "session_id": session_id, "time": time.time()}
    write_json(home / "queue" / f"{time.time_ns()}-{uuid.uuid4().hex}.json", data)
    if event in {"TurnStarted", "Stop", "SessionEnd", "Interrupt", "StopFailure"}:
        write_json(
            home / "activity" / f"{digest(session_id)}.json",
            {**data, "active": event == "TurnStarted"},
        )


def wake(home: Path) -> None:
    if os.environ.get("KIMI_MEMORY_NO_AUTOSTART") == "1":
        return
    private_dir(home)
    env = dict(os.environ)
    source_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
    env["KIMI_MEMORY_HOME"] = str(home)
    # stdout/stderr are disconnected: no inherited hook pipe can keep the hook waiting.
    subprocess.Popen(
        [sys.executable, "-m", "kimi_memory", "worker", "--drain"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        cwd=home,
        env=env,
    )


def handle(payload: dict, home: Path | None = None, *, spawn: bool = True) -> dict:
    home = home or memory_home()
    event = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if not isinstance(event, str) or not isinstance(session_id, str) or not session_id:
        return {}
    if len(session_id) > 1024 or os.environ.get("KIMI_MEMORY_INTERNAL") == "1":
        return {}
    if event in {"SessionStart", "PostCompact"}:
        reset_injection(session_id, home)
    if event == "UserPromptSubmit":
        # This path never even loads generation config, database, or API compatibility state.
        message = injection_for(session_id, home)
        return {"message": message} if message else {}
    if event in WAKE_EVENTS:
        try:
            enqueue(payload, home)
            if spawn:
                wake(home)
        except (OSError, ValueError):
            pass
    return {}


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(1_048_577)
        if len(raw) > 1_048_576:
            result = {}
        else:
            payload = json.loads(raw)
            result = handle(payload) if isinstance(payload, dict) else {}
    except Exception:
        # Kimi exit code 2 means block. Memory never uses it, including on malformed input.
        result = {}
    try:
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except (OSError, BrokenPipeError):
        pass
    return 0

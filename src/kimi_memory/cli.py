"""User commands with lazy imports so generation cannot take down offline reading."""

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from . import __version__
from .errors import UnsafePathError
from .files import atomic_write, memory_home, published_root, read_json, write_json


def initialize(home: Path) -> dict:
    from .workspace import ensure_layout

    ensure_layout(home)
    defaults = Path(__file__).parent / "defaults"
    for name in ("reader.toml", "worker.toml"):
        target = home / name
        if target.exists():
            continue
        text = (defaults / name).read_text(encoding="utf-8")
        atomic_write(target, text)
    return {
        "home": str(home),
        "reader_config": str(home / "reader.toml"),
        "worker_config": str(home / "worker.toml"),
    }


def build_plugin(home: Path, output: Path) -> dict:
    # This development helper copies all Python sources; released plugins bundle a runtime.
    package = Path(__file__).resolve().parent
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        package,
        output / "python/kimi_memory",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    project = package.parents[1]
    if not (project / "plugin/launch.mjs").is_file():
        raise ValueError("Use the release plugin ZIP for installation")
    shutil.copytree(project / "plugin", output / "plugin", dirs_exist_ok=True)
    shutil.copy2(project / "kimi.plugin.json", output / "kimi.plugin.json")
    write_json(output / "development.json", {"python": sys.executable, "home": str(home)})
    return {"plugin": str(output), "install_command": "/plugins install " + str(output)}


def local_status(home: Path) -> dict:
    from .reader import load_reader_config

    reader = load_reader_config(home)
    try:
        worker = read_json(home / "worker-status.json", 32_768)
    except (OSError, ValueError):
        worker = {"state": "not_run"}
    try:
        root = published_root(home)
    except (OSError, ValueError, UnsafePathError):
        root = None
    return {
        "version": __version__,
        "home": str(home),
        "reading_enabled": reader.enabled,
        "summary_available": root is not None and (root / "memory_summary.md").is_file(),
        "memory_path": str(root) if root is not None else None,
        "generation": worker,
    }


def doctor(home: Path, *, probe: bool = False) -> dict:
    from .config import load_worker_config
    from .errors import MemoryErrorBase
    from .models import Model
    from .server import ServerManager

    result = local_status(home)
    result["git_available"] = shutil.which("git") is not None
    try:
        config = load_worker_config(home)
        result["worker_config_valid"] = True
        result["generation_enabled"] = config.generation.enabled
        for name, settings in (
            ("extraction", config.extraction),
            ("consolidation", config.consolidation),
        ):
            try:
                Model(settings).ready()
                result[name + "_configured"] = True
            except MemoryErrorBase as exc:
                result[name + "_configured"] = False
                result[name + "_issue"] = str(exc)
        if probe:
            with ServerManager(config.api) as client:
                result["api"] = {
                    "reachable": True,
                    "version": client.server_version,
                    "server_id": client.server_id,
                }
    except MemoryErrorBase as exc:
        result["worker_issue"] = {"code": exc.code, "message": str(exc)}
    return result


def add_note(home: Path, kind: str, text: str, *, wake_worker: bool = True) -> Path:
    from .evidence import redact
    from .hooks import wake
    from .workspace import ensure_layout

    if not text.strip() or len(text.encode()) > 65_536:
        raise ValueError("Note must be nonempty and at most 65536 bytes")
    ensure_layout(home)
    name = (
        time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
        + "-"
        + uuid.uuid4().hex[:12]
        + "-"
        + kind
        + ".md"
    )
    path = home / "memories_v2/extensions/ad_hoc/notes" / name
    atomic_write(
        path,
        "# Explicit user memory request\n\nOperation: "
        + kind
        + "\n\n"
        + redact(text.strip())
        + "\n",
    )
    if wake_worker:
        try:
            wake(home)
        except OSError:
            pass
    return path


def run_worker_command(home: Path, *, drain: bool) -> dict:
    import signal

    from .worker import run

    def terminate(_signal, _frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        return run(home, drain=drain)
    except KeyboardInterrupt:
        return {"state": "cancelled", "reader_available": True}
    finally:
        signal.signal(signal.SIGTERM, previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kimi-codex-memory", description="Local memory for Kimi Code"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--home", type=Path, help="Memory data directory (or KIMI_MEMORY_HOME)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "init", help="Create configuration without enabling a Kimi plugin or calling models"
    )
    sub.add_parser("render", help="Render prompt and last published summary entirely offline")
    sub.add_parser("hook", help="Read a Kimi hook JSON payload on stdin; always fail open")
    status = sub.add_parser("status", help="Show local status without connecting to Kimi")
    status.add_argument("--json", action="store_true")
    diag = sub.add_parser(
        "doctor", help="Check configuration; no network unless --probe is specified"
    )
    diag.add_argument(
        "--probe",
        action="store_true",
        help="Connect to Kimi (may launch an owned helper), without calling a model",
    )
    plugin = sub.add_parser(
        "plugin", help="Build a local installable plugin with this Python interpreter"
    )
    plugin.add_argument("--output", type=Path)
    worker = sub.add_parser(
        "worker", help="Synchronize and generate memory using configured model budgets"
    )
    worker.add_argument("--drain", action="store_true", help="Coalesce pending hook notifications")
    worker.add_argument("--once", action="store_true", help="Run one pass (the default)")
    note = sub.add_parser("note", help="Record an explicit remember/forget/correction request")
    note.add_argument("kind", choices=["remember", "forget", "correct"])
    note.add_argument("text", nargs="?", help="Request text; omit to read stdin")
    note.add_argument("--no-wake", action="store_true")
    sub.add_parser("update", help="Show the native plugin upgrade command; never upgrades Kimi")
    args = parser.parse_args(argv)
    home = args.home.expanduser().resolve() if args.home else memory_home()
    if args.home:
        os.environ["KIMI_MEMORY_HOME"] = str(home)
    try:
        if args.command == "update":
            print(
                "/plugins marketplace https://raw.githubusercontent.com/WAcry/kimi-codex-memory/main/marketplace.json"
            )
            return 0
        if args.command == "hook":
            from .hooks import main as hook_main

            return hook_main()
        if args.command == "render":
            from .reader import render

            sys.stdout.write(render(home))
            return 0
        if args.command == "init":
            result = initialize(home)
        elif args.command == "plugin":
            result = build_plugin(home, (args.output or home / "plugin").expanduser().resolve())
        elif args.command == "status":
            result = local_status(home)
        elif args.command == "doctor":
            result = doctor(home, probe=args.probe)
        elif args.command == "note":
            text = args.text if args.text is not None else sys.stdin.read(65_537)
            result = {
                "note": str(add_note(home, args.kind, text, wake_worker=not args.no_wake)),
                "status": "queued; published memory has not been changed yet",
            }
        else:
            result = run_worker_command(home, drain=args.drain)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "worker":
            return {"paused": 1, "cancelled": 130}.get(result.get("state"), 0)
        return 0
    except Exception as exc:
        from .errors import MemoryErrorBase

        error = (
            str(exc)
            if isinstance(exc, (MemoryErrorBase, ValueError))
            else "Operation failed; existing published memory was not intentionally removed"
        )
        print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
        return 1

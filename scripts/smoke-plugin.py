"""Exercise the installed artifact after relocation; no paid models or real user data."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from kimi_memory.config import ApiConfig
from kimi_memory.server import ServerManager


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin", type=Path)
    args = parser.parse_args()
    system = {"Windows": "win32", "Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    name = "kimi-codex-memory.exe" if system == "win32" else "kimi-codex-memory"
    native_kimi = os.environ.get("KIMI_MEMORY_NATIVE_KIMI") or shutil.which("kimi")
    if not native_kimi:
        raise ValueError("A test-owned Kimi is required")
    with tempfile.TemporaryDirectory() as directory:
        # Windows temporary paths can use an 8.3 alias; the runtime resolves its home.
        base = Path(directory).resolve()
        root = base / "installed plugin with spaces 中文"
        shutil.copytree(args.plugin, root)
        binary = root / "runtime" / f"{system}-{arch}" / "kimi-codex-memory" / name
        home = base / "memory"
        env = {
            key: value
            for key, value in os.environ.items()
            if not any(word in key.upper() for word in ("API_KEY", "ACCESS_TOKEN", "REFRESH_TOKEN"))
        }
        env.update(
            {
                "KIMI_MEMORY_HOME": str(home),
                "KIMI_CODE_HOME": str(base / "kimi"),
                "KIMI_PLUGIN_ROOT": str(root),
                "KIMI_MEMORY_NO_AUTOSTART": "1",
                "PYTHONUTF8": "1",
                "KIMI_CODE_NO_AUTO_UPDATE": "1",
            }
        )
        # No Python or Node executable on PATH is needed by the released plugin.
        git = shutil.which("git")
        system_path = (
            str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
            if os.name == "nt"
            else "/usr/bin:/bin"
        )
        env["PATH"] = os.pathsep.join(
            [str(Path(native_kimi).parent), str(Path(git).parent) if git else "", system_path]
        )
        host_home = base / "kimi"
        host_home.mkdir()
        (host_home / "config.toml").write_text("telemetry = false\n", encoding="utf-8")
        # Install through the actual native plugin manager, not just a directory copy.
        with patch.dict(os.environ, env, clear=True):
            with ServerManager(
                ApiConfig(kimi_command=(native_kimi,), port=61627), home=host_home
            ) as api:
                result = api.http.request(
                    api.origin + "/api/v1/plugins",
                    headers={"Authorization": "Bearer " + api.token()},
                    body={"source": str(root)},
                )
                if result.get("code") != 0 or result.get("data", {}).get("state") != "ok":
                    raise RuntimeError("Native Kimi plugin installation did not succeed")
        root.rename(base / "original download moved away")
        root = host_home / "plugins/managed/kimi-codex-memory"
        env["KIMI_PLUGIN_ROOT"] = str(root)
        binary = root / "runtime" / f"{system}-{arch}" / "kimi-codex-memory" / name

        def run(arguments, **kwargs):
            result = subprocess.run(
                arguments,
                cwd=root,
                env=env,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=30,
                **kwargs,
            )
            if result.returncode:
                raise RuntimeError(result.stderr[:500])
            return result.stdout

        manifest = json.loads((root / "kimi.plugin.json").read_text(encoding="utf-8"))
        host_path = env["PATH"]
        # A fake incompatible host and Node precede PATH during all reader tests.
        # No package-reader operation is permitted to invoke either executable.
        poison = base / "unavailable-host"
        poison.mkdir()
        marker = poison / "invoked"
        for name in ("kimi.cmd", "node.cmd") if os.name == "nt" else ("kimi", "node"):
            script = poison / name
            text = (
                ('@echo off\necho called > "' + str(marker) + '"\nexit /b 97\n')
                if os.name == "nt"
                else ('#!/bin/sh\nprintf called > "' + str(marker) + '"\nexit 97\n')
            )
            script.write_text(text, encoding="utf-8")
            script.chmod(0o755)
        env["PATH"] = str(poison) + os.pathsep + system_path
        assert run([str(binary), "--version"]).strip() == manifest["version"]
        assert (binary.parent / "licenses/CPython-LICENSE.txt").is_file()
        assert (binary.parent / "licenses/PyInstaller-COPYING.txt").is_file()
        run([str(binary), "init"])
        hook = next(h["command"] for h in manifest["hooks"] if h["event"] == "UserPromptSubmit")
        initial_payload = json.dumps(
            {"hook_event_name": "UserPromptSubmit", "session_id": "first-context"}
        )
        note_guidance = json.loads(run(hook, input=initial_payload, shell=True))["message"]
        assert "## Memory notes" in note_guidance
        assert (home / "memories_v2/extensions/ad_hoc/notes").as_posix() in note_guidance
        assert "MEMORY_SUMMARY" not in note_guidance and "Memory citations:" not in note_guidance
        accepted = json.dumps(
            {
                "hook_event_name": "TurnStarted",
                "session_id": "first-context",
                "origin_kind": "user",
                "turn_id": 1,
                "prompt": "",
            }
        )
        assert run(hook, input=accepted, shell=True) == ""
        assert run(hook, input=initial_payload, shell=True) == ""
        assert not (home / "current.json").exists()
        generation = "a" * 32
        published = home / "_generations" / generation
        (published / "rollout_summaries").mkdir(parents=True)
        (published / "memory_summary.md").write_text(
            "v1\n\n## User Profile\nSynthetic preserved memory.\n\n## User preferences\n\n## General Tips\n\n## What's in Memory\n",
            encoding="utf-8",
        )
        (home / "current.json").write_text(
            json.dumps({"format": 1, "generation": generation}), encoding="utf-8"
        )
        (home / "worker.toml").write_text("intentionally broken [", encoding="utf-8")
        (home / "state.sqlite").write_text("not a database", encoding="utf-8")
        assert run(hook, input=initial_payload, shell=True) == ""
        payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "smoke-session"})
        first = json.loads(run(hook, input=payload, shell=True))
        assert "Synthetic preserved memory" in first["message"]
        assert (
            run(
                hook,
                input=json.dumps(
                    {
                        "hook_event_name": "TurnStarted",
                        "session_id": "smoke-session",
                        "origin_kind": "user",
                        "turn_id": 1,
                        "prompt": "",
                    }
                ),
                shell=True,
            )
            == ""
        )
        assert run(hook, input=payload, shell=True) == ""
        assert json.loads(run([str(binary), "status"]))["summary_available"]
        assert not marker.exists(), "Offline reader invoked Kimi or Node"
        env["PATH"] = host_path
        # Exercise the frozen writer against an empty native Kimi home; no LLM is called.
        empty = base / "empty-memory"
        (base / "kimi").mkdir(exist_ok=True)
        (base / "kimi/config.toml").write_text("telemetry = false\n", encoding="utf-8")
        reply = json.loads(run([str(binary), "--home", str(empty), "worker", "--once"]))
        assert reply["state"] == "ready" and reply["model_calls"] == 0
        # A detached frozen worker must outlive its short hook, without a Python executable.
        background_home = base / "background-memory"
        background_home.mkdir()
        (background_home / "worker.toml").write_text(
            "[generation]\nenabled = false\n", encoding="utf-8"
        )
        env["KIMI_MEMORY_HOME"] = str(background_home)
        env.pop("KIMI_MEMORY_NO_AUTOSTART")
        assert (
            run(
                hook,
                input=json.dumps(
                    {"hook_event_name": "SessionStart", "session_id": "background-smoke"}
                ),
                shell=True,
            )
            == ""
        )
        status = background_home / "worker-status.json"
        deadline = time.monotonic() + 15
        while not status.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert json.loads(status.read_text(encoding="utf-8"))["state"] == "disabled"
        print(
            "PASS native plugin installation, relocated runtime, first-note guidance, offline injection, snapshot, failure isolation, frozen worker"
        )


if __name__ == "__main__":
    main()

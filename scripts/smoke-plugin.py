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
        base = Path(directory)
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

        assert run([str(binary), "--version"]).strip() == "0.2.0"
        run([str(binary), "init"])
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
        manifest = json.loads((root / "kimi.plugin.json").read_text(encoding="utf-8"))
        hook = next(h["command"] for h in manifest["hooks"] if h["event"] == "UserPromptSubmit")
        payload = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "smoke-session"})
        first = json.loads(run(hook, input=payload, shell=True))
        assert "Synthetic preserved memory" in first["message"]
        assert json.loads(run(hook, input=payload, shell=True)) == {}
        assert json.loads(run([str(binary), "status"]))["summary_available"]
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
            json.loads(
                run(
                    hook,
                    input=json.dumps(
                        {"hook_event_name": "SessionStart", "session_id": "background-smoke"}
                    ),
                    shell=True,
                )
            )
            == {}
        )
        status = background_home / "worker-status.json"
        deadline = time.monotonic() + 15
        while not status.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert json.loads(status.read_text(encoding="utf-8"))["state"] == "disabled"
        print(
            "PASS native plugin installation, relocated runtime, offline injection, snapshot, failure isolation, frozen worker"
        )


if __name__ == "__main__":
    main()

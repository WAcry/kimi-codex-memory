"""Build a self-contained platform runtime; CI assembles the universal plugin ZIP."""

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist/plugin")
    args = parser.parse_args()
    target = args.output.resolve()
    system = {"Windows": "win32", "Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    destination = target / "runtime" / f"{system}-{arch}"
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            "kimi-codex-memory",
            "--distpath",
            str(destination),
            "--workpath",
            str(ROOT / "build/frozen"),
            "--specpath",
            str(ROOT / "build"),
            "--paths",
            str(ROOT / "src"),
            "--collect-data",
            "kimi_memory",
            str(ROOT / "scripts/runtime-entry.py"),
        ],
        check=True,
    )
    for name in ("kimi.plugin.json", "LICENSE", "NOTICE", "README.md", "upstream.toml"):
        shutil.copy2(ROOT / name, target / name)
    shutil.copytree(
        ROOT / "plugin",
        target / "plugin",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "hook.py"),
    )
    binary = (
        destination
        / "kimi-codex-memory"
        / ("kimi-codex-memory.exe" if system == "win32" else "kimi-codex-memory")
    )
    subprocess.run([str(binary), "--version"], check=True)
    print(json.dumps({"plugin": str(target), "platform": f"{system}-{arch}"}))


if __name__ == "__main__":
    main()

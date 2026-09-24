"""Build a self-contained platform runtime; CI assembles the universal plugin ZIP."""

import argparse
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import sysconfig
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
    notices = binary.parent / "licenses"
    notices.mkdir(exist_ok=True)
    python_license = next(
        (
            p
            for p in (
                Path(sys.base_prefix) / "LICENSE.txt",
                Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
            )
            if p.is_file()
        ),
        None,
    )
    if python_license is None:
        raise RuntimeError("CPython redistribution license was not found")
    shutil.copy2(python_license, notices / "CPython-LICENSE.txt")
    distribution = importlib.metadata.distribution("pyinstaller")
    copying = next(p for p in distribution.files if str(p).endswith("COPYING.txt"))
    shutil.copy2(distribution.locate_file(copying), notices / "PyInstaller-COPYING.txt")
    print(json.dumps({"plugin": str(target), "platform": f"{system}-{arch}"}))


if __name__ == "__main__":
    main()

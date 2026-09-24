"""Preserve executable modes and dereference runtime links for Kimi's ZIP installer."""

import argparse
import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path


def pack(root: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for current, directories, files in os.walk(root, followlinks=True):
            directories.sort()
            for name in sorted(files):
                path = Path(current) / name
                relative = path.relative_to(root).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
                info.create_system = 3
                mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(
        f"{checksum}  {destination.name}\n", encoding="utf-8"
    )


def unpack(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            path = (destination / member.filename).resolve()
            if not path.is_relative_to(destination.resolve()):
                raise ValueError("Unsafe archive path")
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Installer archives must contain regular files, not links")
            path.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(member)
            if path.exists() and path.read_bytes() != data:
                raise ValueError(f"Conflicting platform payload: {member.filename}")
            path.write_bytes(data)
            if os.name != "nt":
                path.chmod((member.external_attr >> 16) & 0o777 or 0o644)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("pack")
    build.add_argument("root", type=Path)
    build.add_argument("destination", type=Path)
    merge = sub.add_parser("merge")
    merge.add_argument("inputs", type=Path)
    merge.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.action == "pack":
        pack(args.root.resolve(), args.destination.resolve())
        return
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        archives = sorted(args.inputs.rglob("plugin-*.zip"))
        if not archives:
            raise ValueError("No platform artifacts were produced")
        for archive in archives:
            unpack(archive, root)
        platforms = sorted(path.name for path in (root / "runtime").iterdir())
        expected = {
            "linux-x64",
            "linux-arm64",
            "darwin-x64",
            "darwin-arm64",
            "win32-x64",
            "win32-arm64",
        }
        if set(platforms) != expected:
            raise ValueError(f"Missing or unexpected release platforms: {platforms}")
        pack(root, args.destination.resolve())
        print(json.dumps({"platforms": platforms, "archive": str(args.destination)}))


if __name__ == "__main__":
    main()

"""Install a pinned native Kimi into a CI-only directory, never a user's PATH/home."""

import argparse
import hashlib
import io
import json
import os
import re
import tomllib
import urllib.request
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument(
        "--version", default="pinned", help="pinned, minimum, latest or an explicit version"
    )
    parser.add_argument("--directory", type=Path, default=Path(".host/native"))
    args = parser.parse_args()
    contract = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "src/kimi_memory/defaults/host.toml").read_text(
            encoding="utf-8"
        )
    )
    if args.version in {"pinned", "minimum"}:
        args.version = contract["tested_version" if args.version == "pinned" else "minimum_version"]
    if args.version == "latest":
        request = urllib.request.Request(
            "https://api.github.com/repos/MoonshotAI/kimi-code/releases/latest"
        )
        if os.environ.get("GH_TOKEN"):
            request.add_header("Authorization", "Bearer " + os.environ["GH_TOKEN"])
        with urllib.request.urlopen(request, timeout=90) as response:
            tag = json.load(response)["tag_name"]
        args.version = tag.rsplit("@", 1)[-1]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", args.version):
        raise ValueError("Unexpected Kimi release version")
    base = "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%40"
    url = base + args.version + "/kimi-code-" + args.target + ".zip"
    with urllib.request.urlopen(url + ".sha256", timeout=90) as response:
        checksum = response.read().decode().split()[0]
    with urllib.request.urlopen(url, timeout=180) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError("Kimi test artifact checksum mismatch")
    name = "kimi.exe" if args.target.startswith("win32") else "kimi"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        binary = archive.read(name)
    args.directory.mkdir(parents=True, exist_ok=True)
    path = (args.directory / name).resolve()
    path.write_bytes(binary)
    path.chmod(0o755)
    if os.environ.get("GITHUB_PATH"):
        with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8") as output:
            output.write(str(path.parent) + "\n")
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
            output.write("KIMI_MEMORY_NATIVE_KIMI=" + str(path) + "\n")
            output.write("KIMI_MEMORY_TEST_HOST_VERSION=" + args.version + "\n")
    print("Verified test-owned Kimi " + args.version)
    print(path)


if __name__ == "__main__":
    main()

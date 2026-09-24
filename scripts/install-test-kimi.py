"""Install a pinned native Kimi into a CI-only directory, never a user's PATH/home."""

import argparse
import hashlib
import io
import os
import urllib.request
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--version", default="2.1.0")
    parser.add_argument("--directory", type=Path, default=Path(".host/native"))
    args = parser.parse_args()
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
    print(path)


if __name__ == "__main__":
    main()

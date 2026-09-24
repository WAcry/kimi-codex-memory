"""Small local-only building blocks shared by the independent reader and writer."""

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import BusyError, UnsafePathError


def memory_home() -> Path:
    return Path(os.environ.get("KIMI_MEMORY_HOME", "~/.kimi-code-memory")).expanduser().resolve()


def private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def atomic_write(path: Path, data: str | bytes, mode: int = 0o600) -> None:
    private_dir(path.parent)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data.encode("utf-8") if isinstance(data, str) else data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def read_json(path: Path, max_bytes: int = 1_048_576) -> object:
    return json.loads(read_bounded(path, max_bytes))


def read_bounded(path: Path, max_bytes: int) -> str:
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"File exceeds the configured {max_bytes}-byte limit")
    return raw.decode("utf-8")


def digest(value: str | bytes | object) -> str:
    if not isinstance(value, (str, bytes)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def safe_component(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}", value):
        raise UnsafePathError("Invalid path component")
    return value


def within(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise UnsafePathError("Only relative paths inside the workspace are allowed")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise UnsafePathError("Path escapes the workspace")
    return resolved


def utf8_head(text: str, max_bytes: int) -> str:
    return text.encode("utf-8")[:max(0, max_bytes)].decode("utf-8", errors="ignore")


@contextmanager
def file_lock(path: Path, *, blocking: bool = False):
    # POSIX is the explicit initial platform target (Linux and macOS).
    import fcntl

    private_dir(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise BusyError("Another process owns this operation") from exc
        yield
    finally:
        os.close(fd)

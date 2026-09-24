"""Small local-only building blocks shared by the independent reader and writer."""

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .errors import BusyError, UnsafePathError


def memory_home() -> Path:
    if os.environ.get("KIMI_MEMORY_HOME"):
        return Path(os.environ["KIMI_MEMORY_HOME"]).expanduser().resolve()
    return (Path.home() / ".kimi-codex-memory").resolve()


def private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def atomic_write(path: Path, data: str | bytes, mode: int = 0o600) -> None:
    private_dir(path.parent)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if os.name != "nt":
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data.encode("utf-8") if isinstance(data, str) else data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(10):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if os.name != "nt" or attempt == 9:
                    raise
                time.sleep(0.02 * (attempt + 1))
        sync_dir(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def sync_dir(path: Path) -> None:
    if os.name == "nt":
        return  # Windows cannot open directories using POSIX fsync semantics.
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
    return text.encode("utf-8")[: max(0, max_bytes)].decode("utf-8", errors="ignore")


def utf8_middle(text: str, max_bytes: int) -> str:
    """Codex truncate_middle_chars semantics: retain both ends plus an omission marker."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    left_budget = max(0, max_bytes // 2)
    right_budget = max(0, max_bytes - left_budget)
    prefix = raw[:left_budget].decode("utf-8", errors="ignore")
    suffix = raw[-right_budget:].decode("utf-8", errors="ignore") if right_budget else ""
    removed = len(text) - len(prefix) - len(suffix)
    # As upstream, the marker is additional to the retained-text byte budget.
    return prefix + f"…{removed} chars truncated…" + suffix


@contextmanager
def file_lock(path: Path, *, blocking: bool = False):
    private_dir(path.parent)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BusyError("Another process owns this operation") from exc
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as exc:
                raise BusyError("Another process owns this operation") from exc
        yield
    finally:
        os.close(fd)


def published_root(home: Path) -> Path | None:
    """Resolve one immutable generation without opening the generation database."""
    pointer = home / "current.json"
    if pointer.exists():
        data = read_json(pointer, 4096)
        if not isinstance(data, dict) or type(data.get("format")) is not int or data["format"] != 1:
            raise UnsafePathError("Unrecognized publication pointer")
        generation = data.get("generation", "")
        if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation):
            raise UnsafePathError("Invalid published generation")
        root = home / "_generations" / generation
        if root.is_symlink() or not root.is_dir():
            raise UnsafePathError("Published generation missing or replaced")
        return root
    return None

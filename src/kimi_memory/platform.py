"""Small OS boundary shared by the launcher and worker; no API/model imports."""

import os
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path

from .errors import UnsafePathError


def remove_owned_tree(path: Path) -> None:
    """Remove our staging/baseline tree, including Windows read-only Git objects."""
    if path.is_symlink():
        raise UnsafePathError("Refusing to remove a linked runtime tree")
    root = path.resolve()

    def retry_readonly(function, name, info):
        error = info[1]
        target = Path(name)
        if (
            os.name != "nt"
            or not isinstance(error, PermissionError)
            or target.is_symlink()
            or not target.resolve().is_relative_to(root)
        ):
            raise error
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
        function(name)

    shutil.rmtree(path, onerror=retry_readonly)


def process_options(*, detached: bool = False) -> dict:
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        if detached:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        return {"creationflags": flags, "close_fds": True}
    return {"start_new_session": True, "close_fds": True}


def process_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except ProcessLookupError:
            return False
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def stop_owned(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        child.wait(timeout=10)
        return
    # Native staged updates may re-exec under a waiting wrapper in this owned group.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


def kimi_command(configured: tuple[str, ...] = ()) -> list[str]:
    """Resolve the host on each worker start, including the standard Windows npm shim."""
    command = list(configured)
    if not command:
        candidate = os.environ.get("KIMI_MEMORY_HOST_EXECUTABLE")
        # An installer may remove a launcher hint between this worker's batches.
        if not candidate or not Path(candidate).is_file():
            candidate = shutil.which("kimi")
        if not candidate:
            raise OSError("Kimi Code is not on PATH")
        command = [candidate]
    path = Path(command[0]).expanduser().absolute()
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat"}:
        entry = path.parent / "node_modules/@moonshot-ai/kimi-code/dist/main.mjs"
        node = path.parent / "node.exe"
        node_path = str(node) if node.is_file() else shutil.which("node")
        if not entry.is_file() or not node_path:
            raise OSError("Cannot resolve this npm shim; use the official Kimi installer")
        return [node_path, str(entry), *command[1:]]
    return [str(path), *command[1:]]


def worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "worker", "--drain"]
    return [sys.executable, "-m", "kimi_memory", "worker", "--drain"]

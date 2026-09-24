"""Run the pinned original Kimi OAuth lifecycle in the installed host runtime."""

import json
import os
import subprocess
import threading
from pathlib import Path

from . import __version__
from .errors import ConfigurationError
from .platform import kimi_command, process_options

_lock = threading.Lock()


def native_auth(home: Path, ref: dict | None, *, force=False, command=()) -> dict:
    entry = Path(__file__).parent / "native/auth.mjs"
    if not entry.is_file():
        raise ConfigurationError("The bundled Kimi authentication bridge is missing")
    if ref is not None and ref.get("storage", "file") != "file":
        raise ConfigurationError(
            "This Kimi authentication storage is not supported by the host bridge"
        )
    request = {
        "home": str(home),
        "version": __version__,
        "operation": "headers" if ref is None else "token",
        "key": (ref or {}).get("key", "oauth/kimi-code"),
        "oauth_host": (ref or {}).get("oauth_host") or (ref or {}).get("oauthHost"),
        "force": force,
    }
    try:
        with _lock:
            result = subprocess.run(
                [*kimi_command(tuple(command)), "__plugin_run_node", str(entry)],
                input=json.dumps(request),
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=150,
                env={
                    **os.environ,
                    "KIMI_PLUGIN_ROOT": str(entry.parent),
                    "KIMI_CODE_HOME": str(home),
                    "KIMI_MEMORY_INTERNAL": "1",
                    "KIMI_CODE_NO_AUTO_UPDATE": "1",
                },
                **process_options(),
                check=False,
            )
        if result.returncode or len(result.stdout) > 65536:
            raise ValueError("bridge unavailable")
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or not isinstance(data.get("headers"), dict):
            raise ValueError("invalid auth reply")
        if ref is not None and not isinstance(data.get("access_token"), str):
            raise ValueError("missing access token")
        return data
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ConfigurationError(
            "Kimi authentication is temporarily unavailable; existing memory remains readable"
        ) from exc

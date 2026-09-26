"""Bounded private pipe to the vendored Kimi requesters; never starts an agent/session."""

import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

from .errors import ModelError
from .platform import kimi_command, process_options


def native_request(connection, messages, tools, *, json_mode, config, command=()):
    entry = Path(__file__).parent / "native/model.mjs"
    if not entry.is_file():
        raise ModelError("The bundled Kimi model requester is unavailable")
    request = {
        "connection": asdict(connection),
        "messages": messages,
        "tools": tools or [],
        "json_mode": json_mode,
        "timeout_seconds": config.timeout_seconds,
        "max_response_bytes": config.max_response_bytes,
    }
    encoded = json.dumps(request, ensure_ascii=False)
    if len(encoded.encode()) > 64 * 1024 * 1024:
        raise ModelError("Native model request exceeds its size limit")
    try:
        result = subprocess.run(
            [*kimi_command(tuple(command)), "__plugin_run_node", str(entry)],
            input=encoded,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=config.timeout_seconds + 15,
            env={
                **os.environ,
                "KIMI_PLUGIN_ROOT": str(entry.parent),
                "KIMI_MEMORY_INTERNAL": "1",
                "KIMI_CODE_NO_AUTO_UPDATE": "1",
            },
            **process_options(),
            check=False,
        )
        if result.returncode:
            error = ModelError(f"Kimi model requester process exited with code {result.returncode}")
            error.code = "model_process_exit"
            raise error
        if len(result.stdout.encode()) > config.max_response_bytes * 2 + 4096:
            error = ModelError("Kimi model requester response exceeds its byte limit")
            error.code = "model_response_limit"
            raise error
        reply = json.loads(result.stdout)
        if not isinstance(reply, dict):
            raise ValueError("invalid native response")
    except subprocess.TimeoutExpired as exc:
        error = ModelError("Kimi model requester timed out")
        error.code = "model_timeout"
        raise error from exc
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        error = ModelError("Kimi model requester did not return a valid protocol response")
        error.code = "model_requester_protocol"
        raise error from exc
    if reply.get("error"):
        error = ModelError("Native Kimi model request did not return a completed final response")
        if type(reply.get("status")) is int:
            error.status = reply["status"]
        kind = reply.get("kind", reply["error"])
        if kind in {
            "empty_response",
            "syntax",
            "rate_limit",
            "quota_exhausted",
            "context_overflow",
            "request_too_large",
            "response_limit",
            "native_request_incomplete",
        }:
            error.code = "model_" + kind
        raise error
    response = reply.get("result")
    if (
        not isinstance(response, dict)
        or response.get("role") != "assistant"
        or not isinstance(response.get("content"), str)
    ):
        raise ModelError("Invalid native model reply")
    return response

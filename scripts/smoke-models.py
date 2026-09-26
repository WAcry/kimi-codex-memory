"""Run the shipped Python+JS requesters end-to-end, with local synthetic providers only."""

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from dataclasses import replace
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import NativeApi, ScriptModel, serve, turn  # noqa: E402

from kimi_memory.files import atomic_write, write_json  # noqa: E402
from kimi_memory.kimi import Source, Transcript  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin", type=Path)
    args = parser.parse_args()
    system = {"Windows": "win32", "Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    executable = "kimi-codex-memory.exe" if system == "win32" else "kimi-codex-memory"
    binary = (
        args.plugin.resolve() / "runtime" / f"{system}-{arch}" / "kimi-codex-memory" / executable
    )
    kimi = os.environ.get("KIMI_MEMORY_NATIVE_KIMI") or shutil.which("kimi")
    assert kimi and binary.is_file()
    with tempfile.TemporaryDirectory(prefix="frozen-models-") as folder:
        base = Path(folder).resolve()
        host = base / "kimi"
        atomic_write(host / "config.toml", "telemetry = false\n")
        atomic_write(host / "server.token", "test-native-token-never-log")
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("KIMI_", "OPENAI_", "ANTHROPIC_"))
            and not any(
                word in key.upper() for word in ("API_KEY", "ACCESS_TOKEN", "REFRESH_TOKEN")
            )
        }
        env.update(
            KIMI_CODE_HOME=str(host),
            KIMI_CODE_NO_AUTO_UPDATE="1",
            KIMI_MEMORY_NO_AUTOSTART="1",
            PYTHONUTF8="1",
            KIMI_MEMORY_API_KEY="synthetic-model-key",
        )
        git = shutil.which("git")
        system_path = (
            str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
            if os.name == "nt"
            else "/usr/bin:/bin"
        )
        env["PATH"] = os.pathsep.join(
            [str(Path(kimi).parent), str(Path(git).parent) if git else "", system_path]
        )
        now = float(int(time.time()))
        source = Source(
            "session_synthetic", now - 36000, now - 40000, str(base / "workspace"), "workspace_test"
        )
        good = Transcript(source, [turn(source)], [], [], [], [])
        bad = replace(
            good,
            source=Source(
                "session_bad", now - 35000, now - 40000, str(base / "workspace"), "workspace_test"
            ),
        )
        for protocol, mode in product(
            ("openai", "openai_responses", "anthropic"),
            ("multiple_tools", "invalid_tools", "no_tools"),
        ):
            home = base / f"{protocol}-{mode}"
            env["KIMI_MEMORY_HOME"] = str(home)
            script = ScriptModel()
            expected = {
                "rollout_summary": f"Verified {protocol} {mode}. " * 40,
                "rollout_slug": "selected",
            }

            def provider(
                method,
                path,
                body,
                headers,
                protocol=protocol,
                script=script,
                mode=mode,
                expected=expected,
            ):
                if not script.calls:
                    assert len(body["tools"]) == 1
                    tool = body["tools"][0].get("function", body["tools"][0])
                    assert tool["name"] == "submit_memory_extraction"
                    schema = tool.get("parameters", tool.get("input_schema"))
                    assert set(schema["required"]) == {"rollout_summary", "rollout_slug"}
                    assert schema["additionalProperties"] is False
                    assert body["tool_choice"] == (
                        {"type": "auto"} if protocol == "anthropic" else "auto"
                    )
                    assert "response_format" not in body and "output_config" not in body
                    assert "format" not in body.get("text", {})
                if protocol == "openai":
                    messages = body["messages"]
                elif protocol == "openai_responses":
                    messages = [{"role": "system", "content": body["instructions"]}]
                    for item in body["input"]:
                        if item.get("type") == "function_call_output":
                            text = item["output"]
                            if isinstance(text, list):
                                text = "".join(part.get("text", "") for part in text)
                            messages.append({"role": "tool", "content": text})
                else:
                    messages = [
                        {
                            "role": "system",
                            "content": "\n".join(part["text"] for part in body["system"]),
                        }
                    ]
                    for message in body["messages"]:
                        for part in message["content"]:
                            if part.get("type") == "tool_result":
                                text = part["content"]
                                if isinstance(text, list):
                                    text = "".join(item.get("text", "") for item in text)
                                messages.append({"role": "tool", "content": text})
                response = script.complete(messages, tools=body.get("tools"))
                if len(script.calls) == 1:
                    first = response["tool_calls"][0]
                    invalid = {"rollout_summary": "WRONG LARGE INVALID " * 500, "raw_memory": "v1"}
                    bad_call = {
                        **first,
                        "id": "bad-result",
                        "function": {**first["function"], "arguments": json.dumps(invalid)},
                    }
                    if mode == "multiple_tools":
                        corrected = {
                            **first,
                            "id": "corrected-result",
                            "function": {**first["function"], "arguments": json.dumps(expected)},
                        }
                        response["tool_calls"] = [first, corrected, bad_call]
                        response["content"] = json.dumps(
                            {
                                "rollout_summary": "IGNORED LARGE FINAL " * 500,
                                "rollout_slug": "ignored",
                            }
                        )
                    else:
                        response["tool_calls"] = [bad_call] if mode == "invalid_tools" else []
                        small = json.dumps(
                            {"rollout_summary": "short example", "rollout_slug": "short"}
                        )
                        response["content"] = (
                            "Example: "
                            + small
                            + "\n"
                            + json.dumps(invalid)
                            + "\n"
                            + json.dumps(expected)
                            + "\n"
                            + small
                        )
                if protocol == "openai":
                    return 200, {
                        "choices": [
                            {
                                "finish_reason": "tool_calls"
                                if response.get("tool_calls")
                                else "stop",
                                "message": response,
                            }
                        ]
                    }
                if protocol == "openai_responses":
                    output = [
                        {
                            "type": "function_call",
                            "call_id": call["id"],
                            "name": call["function"]["name"],
                            "arguments": call["function"]["arguments"],
                        }
                        for call in response.get("tool_calls", [])
                    ]
                    if response.get("content"):
                        output += [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": response["content"]}],
                            }
                        ]
                    return 200, {"status": "completed", "output": output}
                content = [
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "input": json.loads(call["function"]["arguments"]),
                    }
                    for call in response.get("tool_calls", [])
                ]
                return 200, {
                    "stop_reason": "tool_use" if content else "end_turn",
                    "content": content
                    + (
                        [{"type": "text", "text": response["content"]}]
                        if response.get("content")
                        else []
                    ),
                }

            native = NativeApi([bad, good])

            def api_callback(method, path, body, headers, native=native):
                if path.startswith("/api/v1/sessions/session_bad/transcript"):
                    return 500, {"code": 50001}
                return native(method, path, body, headers)

            with serve(api_callback) as (api_url, _), serve(provider) as (model_url, requests):
                atomic_write(
                    home / "worker.toml",
                    f'''
[api]
server_url = "{api_url}"
auto_start = false
[extraction]
base_url = "{model_url}/v1"
model = "local-scripted-model"
protocol = "{protocol}"
api_key_env = "KIMI_MEMORY_API_KEY"
''',
                )
                write_json(
                    home / "queue/deleted.json", {"event": "Stop", "session_id": "already_deleted"}
                )
                result = subprocess.run(
                    [str(binary), "--home", str(home), "worker", "--once"],
                    env=env,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    timeout=60,
                )
                assert result.returncode == 0, result.stderr[-1000:]
                status = json.loads(result.stdout)
                assert status["state"] == "degraded" and status["extractions"] == ["extracted"], (
                    protocol,
                    mode,
                    status,
                )
                assert status["missing_sessions"] == 1 and status["retention_deferred"]
                assert status["model_calls"] == len(requests) == 6
                generation = json.loads((home / "current.json").read_text(encoding="utf-8"))[
                    "generation"
                ]
                assert (home / "_generations" / generation / "memory_summary.md").is_file()
                with closing(sqlite3.connect(home / "state.sqlite")) as db:
                    row = db.execute(
                        "SELECT summary,slug FROM summaries WHERE source_id=?", (source.id,)
                    ).fetchone()
                    assert row == (expected["rollout_summary"].strip(), expected["rollout_slug"])
                assert not (home / "queue/deleted.json").exists()
    print(
        "PASS frozen requester: last valid tool and largest valid final JSON on Chat, Responses, Anthropic; bad/deleted sources isolated; one extraction call; only local synthetic models."
    )


if __name__ == "__main__":
    main()

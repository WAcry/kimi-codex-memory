"""Inspect actual native Kimi requests using only a local scripted model."""

import json
import os
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer

import pytest
from conftest import seed_published
from native_protocol_events import anthropic_events, response_events

from kimi_memory.cli import build_plugin
from kimi_memory.config import ApiConfig
from kimi_memory.files import atomic_write, write_json
from kimi_memory.server import ServerManager

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIMI_MEMORY_NATIVE_KIMI"), reason="opt-in native request inspection"
)


@contextmanager
def scripted_model(protocol="openai", *, note_path=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            raw = json.dumps({"object": "list", "data": [{"id": "prompt-probe"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            chunks = [
                {
                    "id": "chatcmpl-local",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": "prompt-probe",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "Synthetic response."},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-local",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": "prompt-probe",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 200, "completion_tokens": 3, "total_tokens": 203},
                },
            ]
            if note_path is not None and len(requests) == 1:
                assert protocol == "openai"
                tool = next(
                    tool["function"]
                    for tool in body["tools"]
                    if tool["function"]["name"] == "Write"
                )
                assert {"path", "content"} <= tool["parameters"]["properties"].keys()
                chunks[0]["choices"][0]["delta"] = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_note_local",
                            "type": "function",
                            "function": {
                                "name": "Write",
                                "arguments": json.dumps(
                                    {
                                        "path": str(note_path),
                                        "content": "# Explicit synthetic memory request\n\nUse pnpm for this example project.\n",
                                    }
                                ),
                            },
                        }
                    ],
                }
                chunks[1]["choices"][0]["finish_reason"] = "tool_calls"
            if protocol == "openai_responses":
                chunks = response_events()
            elif protocol == "anthropic":
                chunks = anthropic_events()
            raw = (
                "".join(
                    ("event: " + chunk["type"] + "\n" if "type" in chunk else "")
                    + "data: "
                    + json.dumps(chunk)
                    + "\n\n"
                    for chunk in chunks
                )
                + ("data: [DONE]\n\n" if protocol == "openai" else "")
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    class LoopbackServer(ThreadingHTTPServer):
        def server_bind(self):
            TCPServer.server_bind(self)
            self.server_name = "localhost"
            self.server_port = self.server_address[1]

    server = LoopbackServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def text_content(message):
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") for part in content or [] if isinstance(part, dict))


def isolate_host(tmp_path, monkeypatch):
    binary = Path(os.environ["KIMI_MEMORY_NATIVE_KIMI"]).absolute()
    for key in list(os.environ):
        if key.startswith(("KIMI_", "OPENAI_", "ANTHROPIC_", "MOONSHOT_")) or any(
            value in key.upper() for value in ("API_KEY", "ACCESS_TOKEN", "REFRESH_TOKEN")
        ):
            monkeypatch.delenv(key)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / "kimi"))
    monkeypatch.setenv("KIMI_MEMORY_HOME", str(tmp_path / "memory"))
    monkeypatch.setenv("KIMI_MEMORY_NO_AUTOSTART", "1")
    monkeypatch.setenv("KIMI_CODE_NO_AUTO_UPDATE", "1")
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ.get("PATH", ""))
    return binary


def configure_model(native_home, origin, protocol="openai"):
    atomic_write(
        native_home / "config.toml",
        f'''
telemetry = false
default_model = "probe/default"
[providers.probe]
type = "{protocol}"
base_url = "{origin}/v1"
api_key = "synthetic-local-only"
[models."probe/default"]
provider = "probe"
model = "prompt-probe"
protocol = "{protocol}"
max_context_size = 256000
max_output_size = 4096
capabilities = ["tool_use"]
''',
    )


def install_plugins(binary, native_home, plugin_roots):
    owner = ServerManager(ApiConfig(kimi_command=(str(binary),), port=61627), home=native_home)
    with owner as api:
        for root in plugin_roots:
            result = api.http.request(
                api.origin + "/api/v1/plugins",
                headers={"Authorization": "Bearer " + owner.token()},
                body={"source": str(root)},
            )
            assert result["code"] == 0 and result["data"]["state"] == "ok"


def invoke(binary, cwd, prompt, extra=()):
    result = subprocess.run(
        [str(binary), *extra, "--output-format", "stream-json", "-p", prompt],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
    )
    assert result.returncode == 0, (result.stdout[-4000:], result.stderr[-4000:])
    return result


def request_parts(request, protocol):
    if protocol == "openai_responses":
        return request.get("instructions", ""), request["input"]
    if protocol == "anthropic":
        return text_content({"content": request.get("system", [])}), request["messages"]
    system = "\n".join(text_content(m) for m in request["messages"] if m["role"] == "system")
    return system, request["messages"]


@pytest.mark.parametrize("protocol", ["openai", "openai_responses", "anthropic"])
@pytest.mark.parametrize("custom_system", ["default", "standalone", "base_prompt"])
def test_native_plugin_system_is_automatic_but_custom_templates_can_omit_it(
    tmp_path, home, monkeypatch, custom_system, protocol
):
    binary = isolate_host(tmp_path, monkeypatch)
    native_home = tmp_path / "kimi"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    seed_published(home, "NATIVE_MEMORY_FIXTURE")
    memory_plugin = tmp_path / "memory-plugin"
    build_plugin(home, memory_plugin)
    probe_plugin = tmp_path / "probe-plugin"
    write_json(
        probe_plugin / "kimi.plugin.json",
        {
            "name": "system-prompt-probe",
            "version": "1.0.0",
            "systemPrompt": "AUTOMATIC_STATIC_PLUGIN_SENTINEL",
        },
    )
    if custom_system != "default":
        text = "CUSTOM_SYSTEM_SENTINEL\nAnswer the user."
        if custom_system == "base_prompt":
            text += "\n${base_prompt}"
        atomic_write(native_home / "SYSTEM.md", text)
    atomic_write(home / "worker.toml", "broken TOML [")
    atomic_write(home / "state.sqlite", "broken SQLite")
    with scripted_model(protocol) as (origin, requests):
        configure_model(native_home, origin, protocol)
        install_plugins(binary, native_home, [memory_plugin, probe_plugin])
        invoke(binary, workspace, "NATIVE_PLAIN_USER_REQUEST")
        invoke(binary, workspace, "NATIVE_CONTINUED_REQUEST", extra=("--continue",))
    assert requests
    for request in requests:
        _, messages = request_parts(request, protocol)
        all_text = "\n".join(text_content(m) for m in messages)
        assert all_text.count("Use the injected MEMORY_SUMMARY") == 1
        assert all_text.count("Memory citations:") == 1
        assert all_text.count("========= MEMORY_SUMMARY BEGINS =========") == 1
        assert "Kimi host adaptation" not in all_text
    system, messages = request_parts(requests[-1], protocol)
    assert ("AUTOMATIC_STATIC_PLUGIN_SENTINEL" in system) is (custom_system != "standalone")
    assert ("CUSTOM_SYSTEM_SENTINEL" in system) is (custom_system != "default")
    assert "Use the injected MEMORY_SUMMARY" not in system
    assert all(m["role"] == "user" for m in messages if "<hook_result" in text_content(m))
    hooks = [
        text_content(m)
        for m in messages
        if '<hook_result hook_event="UserPromptSubmit">' in text_content(m)
    ]
    assert len(hooks) == 1 and "NATIVE_MEMORY_FIXTURE" in hooks[0]
    assert "Memory citations:" in hooks[0]
    assert "copy the `session_id` value from each cited summary's header" in hooks[0]
    assert (home / "memories_v2/extensions/ad_hoc/notes").as_posix() in hooks[0]


@pytest.mark.parametrize("protocol", ["openai", "openai_responses", "anthropic"])
def test_native_first_context_gets_only_note_guidance_and_disabled_plugin_gets_nothing(
    tmp_path, home, monkeypatch, protocol
):
    binary = isolate_host(tmp_path, monkeypatch)
    native_home = tmp_path / "kimi"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plugin = tmp_path / "memory-plugin"
    build_plugin(home, plugin)
    atomic_write(native_home / "SYSTEM.md", "Custom system with no plugin sections.")
    with scripted_model(protocol) as (origin, requests):
        configure_model(native_home, origin, protocol)
        install_plugins(binary, native_home, [plugin])
        invoke(binary, workspace, "NATIVE_EMPTY_REQUEST")
        seed_published(home, "FIRST_PUBLISHED_MEMORY")
        invoke(binary, workspace, "NATIVE_KEEP_CURRENT_CONTEXT", extra=("--continue",))
        for request in requests:
            assert "Memory citations:" not in json.dumps(request)
            assert "FIRST_PUBLISHED_MEMORY" not in json.dumps(request)
            assert "MEMORY_SUMMARY" not in json.dumps(request)
            system, messages = request_parts(request, protocol)
            notes = [m for m in messages if "## Memory notes" in text_content(m)]
            assert len(notes) == 1 and notes[0]["role"] == "user"
            assert "Memory notes" not in system
            assert (home / "memories_v2/extensions/ad_hoc/notes").as_posix() in text_content(
                notes[0]
            )
        owner = ServerManager(ApiConfig(kimi_command=(str(binary),), port=61627), home=native_home)
        with owner as api:
            result = api.http.request(
                api.origin + "/api/v1/plugins/kimi-codex-memory:disable",
                headers={"Authorization": "Bearer " + owner.token()},
                body={},
            )
            assert result["code"] == 0
        requests.clear()
        invoke(binary, workspace, "NATIVE_DISABLED_PLUGIN_REQUEST")
        assert requests and "Memory citations:" not in json.dumps(requests)
        assert "<hook_result" not in json.dumps(requests)
        assert "## Memory notes" not in json.dumps(requests)


def test_native_first_remember_request_can_write_a_note_without_summary(
    tmp_path, home, monkeypatch
):
    binary = isolate_host(tmp_path, monkeypatch)
    native_home = tmp_path / "kimi"
    plugin = tmp_path / "memory-plugin"
    build_plugin(home, plugin)
    note_path = home / "memories_v2/extensions/ad_hoc/notes/explicit-synthetic.md"
    assert not (home / "current.json").exists()
    with scripted_model(note_path=note_path) as (origin, requests):
        configure_model(native_home, origin)
        install_plugins(binary, native_home, [plugin])
        invoke(binary, tmp_path, "Please remember to use pnpm for this example project.")
    assert len(requests) == 2
    assert "## Memory notes" in json.dumps(requests[0])
    assert "MEMORY_SUMMARY" not in json.dumps(requests[0])
    assert "Use pnpm for this example project." in note_path.read_text(encoding="utf-8")
    assert not (home / "current.json").exists()

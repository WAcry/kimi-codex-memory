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

from kimi_memory.cli import build_plugin
from kimi_memory.config import ApiConfig
from kimi_memory.files import atomic_write, write_json
from kimi_memory.server import ServerManager

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIMI_MEMORY_NATIVE_KIMI"), reason="opt-in native request inspection"
)


@contextmanager
def scripted_model():
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
            raw = (
                "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                + "data: [DONE]\n\n"
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


def configure_model(native_home, origin):
    atomic_write(
        native_home / "config.toml",
        f'''
telemetry = false
default_model = "probe/default"
[providers.probe]
type = "openai"
base_url = "{origin}/v1"
api_key = "synthetic-local-only"
[models."probe/default"]
provider = "probe"
model = "prompt-probe"
protocol = "openai"
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


@pytest.mark.parametrize("custom_system", ["default", "standalone", "base_prompt"])
def test_native_plugin_system_is_automatic_but_custom_templates_can_omit_it(
    tmp_path, home, monkeypatch, custom_system
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
    with scripted_model() as (origin, requests):
        configure_model(native_home, origin)
        install_plugins(binary, native_home, [memory_plugin, probe_plugin])
        invoke(binary, workspace, "NATIVE_PLAIN_USER_REQUEST")
        invoke(binary, workspace, "NATIVE_CONTINUED_REQUEST", extra=("--continue",))
    assert requests
    for request in requests:
        messages = request["messages"]
        all_text = "\n".join(text_content(m) for m in messages)
        assert all_text.count("Use the injected MEMORY_SUMMARY") == 1
        assert all_text.count("Memory citations:") == 1
        assert all_text.count("========= MEMORY_SUMMARY BEGINS =========") == 1
        assert "Kimi host adaptation" not in all_text
    messages = requests[-1]["messages"]
    system = "\n".join(text_content(m) for m in messages if m["role"] in {"system", "developer"})
    assert ("AUTOMATIC_STATIC_PLUGIN_SENTINEL" in system) is (custom_system != "standalone")
    assert ("CUSTOM_SYSTEM_SENTINEL" in system) is (custom_system != "default")
    assert "Use the injected MEMORY_SUMMARY" not in system
    hooks = [
        text_content(m)
        for m in messages
        if '<hook_result hook_event="UserPromptSubmit">' in text_content(m)
    ]
    assert len(hooks) == 1 and "NATIVE_MEMORY_FIXTURE" in hooks[0]
    assert "Memory citations:" in hooks[0]
    assert "copy the `session_id` value from each cited summary's header" in hooks[0]
    assert (home / "memories_v2/extensions/ad_hoc/notes").as_posix() in hooks[0]


def test_native_empty_first_context_and_disabled_plugin_do_not_inject_rules(
    tmp_path, home, monkeypatch
):
    binary = isolate_host(tmp_path, monkeypatch)
    native_home = tmp_path / "kimi"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plugin = tmp_path / "memory-plugin"
    build_plugin(home, plugin)
    with scripted_model() as (origin, requests):
        configure_model(native_home, origin)
        install_plugins(binary, native_home, [plugin])
        invoke(binary, workspace, "NATIVE_EMPTY_REQUEST")
        seed_published(home, "FIRST_PUBLISHED_MEMORY")
        invoke(binary, workspace, "NATIVE_KEEP_CURRENT_CONTEXT", extra=("--continue",))
        for request in requests:
            assert "Memory citations:" not in json.dumps(request)
            assert "FIRST_PUBLISHED_MEMORY" not in json.dumps(request)
            assert "<hook_result" not in json.dumps(request)
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

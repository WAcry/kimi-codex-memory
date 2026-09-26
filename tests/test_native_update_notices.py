"""Actual Kimi accepts and displays a cached notice without asking a model to compose it."""

import json
import os
import shlex
import subprocess
import sys

import pytest
from conftest import seed_published
from test_native_prompts import (
    configure_model,
    install_plugins,
    invoke,
    isolate_host,
    request_parts,
    scripted_model,
    text_content,
)
from test_update_notices import seed_release

from kimi_memory.cli import build_plugin
from kimi_memory.files import atomic_write, read_json, write_json

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIMI_MEMORY_NATIVE_KIMI"), reason="opt-in native notice delivery tests"
)
MARKER = "Kimi Codex Memory update available"


@pytest.mark.parametrize("protocol", ["openai", "openai_responses", "anthropic"])
def test_native_cached_notice_is_delivered_once_then_globally_suppressed(
    tmp_path, home, monkeypatch, protocol
):
    binary = isolate_host(tmp_path, monkeypatch)
    native_home, workspace, plugin = tmp_path / "kimi", tmp_path / "workspace", tmp_path / "plugin"
    workspace.mkdir()
    seed_published(home, "PRESERVED_NATIVE_MEMORY")
    atomic_write(home / "worker.toml", "broken [")
    atomic_write(home / "state.sqlite", "corrupt")
    atomic_write(
        native_home / "SYSTEM.md", "Custom prompt with no plugin sections. Answer the user."
    )
    build_plugin(home, plugin)
    with scripted_model(protocol) as (origin, requests):
        configure_model(native_home, origin, protocol)
        install_plugins(binary, native_home, [plugin])
        invoke(binary, workspace, "Normal first input")
        seed_release(home, "9.8.7")
        shown = invoke(binary, workspace, "Normal continued input", extra=("--continue",))
        assert len(requests) == 2
        system, messages = request_parts(requests[-1], protocol)
        notices = [m for m in messages if MARKER in text_content(m)]
        assert len(notices) == 1 and notices[0]["role"] == "user"
        assert MARKER not in system
        assert "MEMORY_SUMMARY" not in text_content(notices[0])
        assert "do not run an update unless the user asks" in text_content(notices[0])
        assert read_json(home / "updates/notice.json")["notified_version"] == "9.8.7"
        assert all(MARKER not in text_content(m) for m in messages if m["role"] == "assistant")
        events = [json.loads(line) for line in shown.stdout.splitlines() if line.startswith("{")]
        notices_to_ui = [
            event
            for event in events
            if isinstance(event.get("content"), str)
            and event["content"].startswith("UserPromptSubmit hook\n")
            and MARKER in event["content"]
        ]
        assert len(notices_to_ui) == 1, events
        # Native print mode serializes UI hook cards as assistant display entries;
        # the actual model request above correctly contains a user hook message.
        assert notices_to_ui[0]["role"] == "assistant"
        invoke(binary, workspace, "Third continuation", extra=("--continue",))
        _, messages = request_parts(requests[-1], protocol)
        text = "\n".join(text_content(m) for m in messages)
        assert text.count(MARKER) == 1 and text.count("PRESERVED_NATIVE_MEMORY") == 1
        invoke(binary, workspace, "New independent conversation")
        _, messages = request_parts(requests[-1], protocol)
        assert MARKER not in "\n".join(text_content(m) for m in messages)
        seed_release(home, "9.8.8")
        invoke(binary, workspace, "Newer release in continued conversation", extra=("--continue",))
        _, messages = request_parts(requests[-1], protocol)
        text = "\n".join(text_content(m) for m in messages)
        assert text.count(MARKER) == 1 and "Version 9.8.8" in text
        assert read_json(home / "updates/notice.json")["notified_version"] == "9.8.8"
    assert len(requests) == 5


@pytest.mark.parametrize("with_memory", [False, True])
def test_native_blocked_first_notice_is_not_lost_then_is_not_repeated(
    tmp_path, home, monkeypatch, with_memory
):
    binary = isolate_host(tmp_path, monkeypatch)
    host, workspace, plugin = tmp_path / "kimi", tmp_path / "workspace", tmp_path / "plugin"
    workspace.mkdir()
    if with_memory:
        seed_published(home, "MEMORY_AND_NOTICE")
    seed_release(home)
    build_plugin(home, plugin)
    blocker = tmp_path / "blocker"
    script = blocker / "block.py"
    atomic_write(
        script,
        "import sys\nfrom pathlib import Path\np=Path(__file__).with_name('blocked')\nif not p.exists():\n p.touch()\n print('Synthetic notice block',file=sys.stderr)\n raise SystemExit(2)\n",
    )
    command = (
        subprocess.list2cmdline([sys.executable, str(script)])
        if os.name == "nt"
        else shlex.join([sys.executable, str(script)])
    )
    write_json(
        blocker / "kimi.plugin.json",
        {
            "name": "notice-blocker",
            "version": "1.0.0",
            "hooks": [{"event": "UserPromptSubmit", "command": command}],
        },
    )
    with scripted_model() as (origin, requests):
        configure_model(host, origin)
        install_plugins(binary, host, [plugin, blocker])
        blocked = subprocess.run(
            [str(binary), "--output-format", "stream-json", "-p", "Blocked input"],
            cwd=workspace,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=45,
        )
        assert blocked.returncode in (0, 1) and "Synthetic notice block" in blocked.stdout
        assert not requests and "notified_version" not in read_json(home / "updates/notice.json")
        assert "pending" in read_json(home / "updates/notice.json")
        invoke(binary, workspace, "Accepted second input", extra=("--continue",))
        assert len(requests) == 1 and MARKER in json.dumps(requests[0])
        assert read_json(home / "updates/notice.json")["notified_version"] == "9.8.7"
        invoke(binary, workspace, "Third input", extra=("--continue",))
        assert json.dumps(requests[-1]).count(MARKER) == 1
        memory_marker = "MEMORY_AND_NOTICE" if with_memory else "## Memory notes"
        assert json.dumps(requests[-1]).count(memory_marker) == 1

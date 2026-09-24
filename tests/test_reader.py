import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import seed_published, valid_summary

from kimi_memory.cli import build_plugin, local_status
from kimi_memory.files import atomic_write
from kimi_memory.hooks import handle
from kimi_memory.reader import injection_for, render


def test_reader_survives_broken_worker_config_database_and_status(home):
    seed_published(home)
    atomic_write(home / "worker.toml", "[invalid\n")
    atomic_write(home / "state.sqlite", "not a database")
    atomic_write(
        home / "worker-status.json",
        json.dumps({"state": "paused", "error_code": "incompatible_kimi"}),
    )
    text = handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1"}, home)["message"]
    assert "Previously published user preference" in text
    assert "rg/Grep" in text and "<oai-mem-citation>" in text
    assert local_status(home)["summary_available"] is True


def test_render_import_graph_does_not_load_generation(home):
    seed_published(home)
    code = """
import sys
for name in ('worker', 'store', 'config', 'kimi', 'models', 'http', 'server'):
    sys.modules['kimi_memory.' + name] = None
from kimi_memory.cli import main
raise SystemExit(main(['render']))
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    assert "Previously published" in result.stdout


def test_inject_once_and_restore_on_resume_and_compaction(home):
    seed_published(home)
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s1"}
    assert handle(payload, home).get("message")
    assert handle(payload, home) == {}
    handle({**payload, "hook_event_name": "PostCompact"}, home)
    assert handle(payload, home).get("message")
    handle({**payload, "hook_event_name": "SessionStart", "source": "resume"}, home, spawn=False)
    assert handle(payload, home).get("message")


def test_no_summary_is_not_fabricated_and_first_summary_can_arrive_later(home):
    assert "No published summary" in injection_for("s1", home)
    seed_published(home)
    assert "Previously published" in injection_for("s1", home)


def test_local_disable_is_independent(home):
    seed_published(home)
    atomic_write(home / "reader.toml", "enabled = false\n")
    assert render(home) == ""
    assert handle({"hook_event_name": "UserPromptSubmit", "session_id": "s"}, home) == {}


def test_reader_keeps_last_good_configuration_on_bad_edit(home):
    seed_published(home)
    atomic_write(home / "reader.toml", "enabled = false\n")
    assert render(home) == ""
    atomic_write(home / "reader.toml", "enabled = [bad")
    assert render(home) == ""


def test_corrupt_reader_backup_still_falls_back_to_safe_defaults(home):
    seed_published(home)
    atomic_write(home / "reader.toml", "enabled = [bad")
    atomic_write(home / "reader-last-good.json", '{"max_summary_bytes": "invalid"}')
    assert "Previously published" in render(home)


def test_utf8_truncation_is_bounded_and_explicit(home):
    seed_published(home, "中文" * 6000)
    atomic_write(home / "reader.toml", "max_summary_bytes = 512\n")
    text = render(home)
    summary = (
        text.split("========= MEMORY_SUMMARY BEGINS =========\n")[1]
        .split("========= MEMORY_SUMMARY ENDS")[0]
        .strip()
    )
    assert len(summary.encode()) <= 512
    assert "truncated" in summary and "�" not in summary


def test_generation_disabled_does_not_disable_reading(home):
    seed_published(home)
    atomic_write(home / "worker.toml", "[generation]\nenabled = false\n")
    from kimi_memory.worker import run

    assert run(home)["state"] == "disabled"
    assert "Previously published" in render(home)


def test_bad_generation_configuration_pauses_only_worker(home):
    seed_published(home)
    atomic_write(home / "worker.toml", "[unknown]\nvalue = 3\n")
    from kimi_memory.worker import run

    assert run(home)["state"] == "paused"
    assert "Previously published" in render(home)


@pytest.mark.parametrize(
    "payload", [None, {}, {"hook_event_name": "UserPromptSubmit"}, {"session_id": []}]
)
def test_hook_entry_fails_open_on_bad_payload(home, payload):
    script = Path(__file__).parents[1] / "plugin/hook.py"
    result = subprocess.run(
        [sys.executable, script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_hook_does_not_save_prompt_or_response(home):
    handle(
        {
            "hook_event_name": "TurnStarted",
            "session_id": "s1",
            "prompt": "SECRET-RAW-INPUT",
            "response": "SECRET-RAW-OUTPUT",
        },
        home,
        spawn=False,
    )
    for path in (home / "queue").glob("*.json"):
        assert "SECRET-RAW" not in path.read_text()


def test_generated_plugin_runs_with_spaces_in_paths(home):
    seed_published(home)
    output = home / "plugin with spaces"
    build_plugin(home, output)
    manifest = json.loads((output / "kimi.plugin.json").read_text())
    hook = next(item for item in manifest["hooks"] if item["event"] == "UserPromptSubmit")
    result = subprocess.run(
        hook["command"],
        shell=True,
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "from-plugin"}),
        env={**os.environ, "KIMI_PLUGIN_ROOT": str(output)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0
    assert "Previously published" in json.loads(result.stdout)["message"]


def test_internal_worker_sessions_do_not_recurse(home, monkeypatch):
    monkeypatch.setenv("KIMI_MEMORY_INTERNAL", "1")
    assert handle({"hook_event_name": "UserPromptSubmit", "session_id": "internal"}, home) == {}
    assert handle({"hook_event_name": "TurnStarted", "session_id": "internal"}, home) == {}


def test_inject_every_prompt_and_refresh_policies(home):
    directory = seed_published(home)
    atomic_write(home / "reader.toml", "inject_every_prompt = true\n")
    assert injection_for("s", home) and injection_for("s", home)
    atomic_write(home / "reader.toml", "refresh_on_change = true\n")
    atomic_write(directory / "memory_summary.md", valid_summary("Changed preference"))
    assert "Changed preference" in injection_for("s", home)

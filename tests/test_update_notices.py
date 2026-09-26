"""Local-only notices, per-release deduplication and detached checks independent of memory."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from conftest import seed_published

from kimi_memory import update_notices as updates
from kimi_memory.files import atomic_write, read_json, write_json
from kimi_memory.hooks import handle
from kimi_memory.reader import render

NEXT = "9.8.7"


def seed_release(home, version=NEXT, **fields):
    now = time.time()
    write_json(
        home / "updates/cache.json",
        {
            "format": 1,
            "state": "ready",
            "attempted_at": now,
            "checked_at": now,
            "latest": version,
            **fields,
        },
    )


def ack(home, session="s", prompt="hello", **extra):
    updates.acknowledge_notice(
        session, {"origin_kind": "user", "turn_id": 1, "prompt": prompt, **extra}, home
    )


@pytest.mark.parametrize(
    "version",
    [
        None,
        True,
        {},
        "",
        "1.0",
        "v2.0.0",
        "02.0.0",
        "2.0.0-alpha",
        "2.0.0+build",
        "2.0.0\nINJECT",
        "2.0.0;run",
        "9999999.0.0",
    ],
)
def test_only_bounded_plain_stable_versions_are_accepted(version):
    assert updates.version_key(version) is None


def test_numeric_comparison_not_string_comparison(home, monkeypatch):
    monkeypatch.setattr(updates, "__version__", "1.9.0")
    seed_release(home, "1.10.0")
    assert "1.10.0" in updates.prepare_notice("s", "hello", home)


@pytest.mark.parametrize("state", ["ready", "unavailable", "checking"])
def test_missing_current_older_or_unready_releases_are_silent(home, state):
    assert updates.prepare_notice("s", "hello", home) == ""
    for version in ("0.9.0", updates.__version__):
        seed_release(home, version, state=state)
        assert updates.prepare_notice("s", "hello", home) == ""
    if state != "ready":
        seed_release(home, state=state)
        assert updates.prepare_notice("s", "hello", home) == ""


@pytest.mark.parametrize("timestamp", [0, "today", True, float("nan"), float("inf")])
def test_bad_or_stale_cache_cannot_emit_a_notice(home, timestamp):
    seed_release(home, checked_at=timestamp)
    assert updates.prepare_notice("s", "hello", home) == ""
    seed_release(home, checked_at=time.time() - updates.CHECK_INTERVAL - 1)
    assert updates.prepare_notice("s", "hello", home) == ""
    seed_release(home, checked_at=time.time() + 500)
    assert updates.prepare_notice("s", "hello", home) == ""


def test_notice_uses_only_fixed_copy_and_numeric_version(home):
    secret = "NEVER_RENDER_REMOTE_INSTRUCTIONS_OR_SECRETS"
    seed_release(
        home, body=secret, message=secret, html_url="https://untrusted.invalid/", name=secret
    )
    text = updates.prepare_notice("s", secret, home)
    assert text.startswith("## Kimi Codex Memory update available")
    assert (
        f"/plugins install {updates.REPOSITORY}/releases/download/v{NEXT}/kimi-codex-memory.zip"
        in text
    )
    assert "Nothing has been installed" in text
    assert secret not in text and "untrusted.invalid" not in text
    state = read_json(home / "updates/notice.json")
    assert secret not in json.dumps(state) and state["pending"]["version"] == NEXT


def test_prepared_notice_retries_until_matching_turn_then_suppresses_globally(home):
    seed_release(home)
    assert updates.prepare_notice("s", "blocked", home)
    ack(home, prompt="unrelated")
    ack(home, prompt="blocked", origin_kind="task")
    ack(home, session="different", prompt="blocked")
    assert "notified_version" not in read_json(home / "updates/notice.json")
    assert updates.prepare_notice("s", "hello", home)
    ack(home)
    assert read_json(home / "updates/notice.json")["notified_version"] == NEXT
    assert updates.prepare_notice("s", "next", home) == ""
    assert updates.prepare_notice("different", "new conversation", home) == ""
    handle({"hook_event_name": "PostCompact", "session_id": "s"}, home, spawn=False)
    assert updates.prepare_notice("s", "after compact", home) == ""
    seed_release(home, "9.8.8")
    assert "9.8.8" in updates.prepare_notice("different", "new release", home)


def test_updated_installation_does_not_show_old_cached_notice(home, monkeypatch):
    seed_release(home)
    assert updates.prepare_notice("s", "hello", home)
    monkeypatch.setattr(updates, "__version__", NEXT)
    assert updates.prepare_notice("s", "later", home) == ""


def test_disabling_a_prepared_notice_does_not_falsely_confirm_it_on_same_input(home):
    seed_release(home)
    assert updates.prepare_notice("s", "hello", home)
    atomic_write(home / "updates.toml", "enabled = false\n")
    assert updates.prepare_notice("s", "hello", home) == ""
    ack(home)
    assert "notified_version" not in read_json(home / "updates/notice.json")
    atomic_write(home / "updates.toml", "enabled = true\n")
    assert updates.prepare_notice("s", "hello", home)


def test_concurrent_sessions_share_one_pending_notice_and_abandoned_lease_expires(
    home, monkeypatch
):
    seed_release(home)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda index: updates.prepare_notice(str(index), "hello", home), range(8))
        )
    assert sum(bool(text) for text in results) == 1
    assert updates.prepare_notice("other", "hello", home) == ""
    future = time.time() + updates.NOTICE_LEASE + 1
    monkeypatch.setattr(updates.time, "time", lambda: future)
    assert updates.prepare_notice("other", "hello", home)
    ack(home, session="other")
    assert updates.prepare_notice("next", "hello", home) == ""


@pytest.mark.parametrize("event", ["PostCompact", "SessionEnd"])
def test_closed_or_compacted_preparation_releases_the_unacknowledged_notice(home, event):
    seed_release(home)
    assert updates.prepare_notice("s", "hello", home)
    assert updates.prepare_notice("other", "hello", home) == ""
    handle({"hook_event_name": event, "session_id": "s"}, home, spawn=False)
    assert updates.prepare_notice("other", "hello", home)


@pytest.mark.parametrize(
    "config",
    ["enabled = false\n", 'enabled = "true"', "broken [", "unknown_option = true", "x" * 5000],
)
def test_optout_or_invalid_update_settings_do_not_affect_memory(home, config, monkeypatch):
    seed_published(home)
    seed_release(home)
    atomic_write(home / "updates.toml", config)
    assert not updates.enabled(home)
    assert updates.prepare_notice("s", "hello", home) == ""
    monkeypatch.delenv("KIMI_MEMORY_NO_AUTOSTART")

    def forbidden(*_, **__):
        raise AssertionError("Disabled updates must not spawn")

    monkeypatch.setattr(updates.subprocess, "Popen", forbidden)
    updates.schedule_check(home)
    assert (
        "Previously published"
        in handle(
            {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "hello"}, home
        )["message"]
    )


def test_notice_only_does_not_reinject_accepted_memory_or_modify_its_snapshot(home):
    seed_published(home)
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "first"}
    assert "Previously published" in handle(payload, home)["message"]
    handle(
        {**payload, "hook_event_name": "TurnStarted", "origin_kind": "user", "turn_id": 1},
        home,
        spawn=False,
    )
    seed_release(home)
    text = handle({**payload, "prompt": "second"}, home)["message"]
    assert "update available" in text and "MEMORY_SUMMARY" not in text
    handle(
        {
            **payload,
            "prompt": "second",
            "hook_event_name": "TurnStarted",
            "origin_kind": "user",
            "turn_id": 2,
        },
        home,
        spawn=False,
    )
    assert handle({**payload, "prompt": "third"}, home) == {}
    assert "update available" not in render(home)


def test_updates_are_independent_of_reader_generation_and_memory_receipt(home):
    atomic_write(home / "reader.toml", "enabled = false\n")
    atomic_write(home / "worker.toml", "broken [")
    atomic_write(home / "state.sqlite", "corrupt")
    seed_release(home)
    text = handle(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "hello"}, home
    )["message"]
    assert "update available" in text and "MEMORY_SUMMARY" not in text
    assert not (home / "current.json").exists()


def test_notice_import_or_runtime_error_cannot_drop_prepared_memory(home, monkeypatch):
    seed_published(home)

    def broken(*_, **__):
        raise RuntimeError("test notice implementation failure")

    monkeypatch.setattr(updates, "prepare_notice", broken)
    assert (
        "Previously published"
        in handle(
            {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "hello"}, home
        )["message"]
    )


def test_scheduling_is_coalesced_and_never_coupled_to_worker_status(home, monkeypatch):
    atomic_write(home / "worker.toml", "broken [")
    write_json(
        home / "worker-status.json",
        {"worker_version": updates.__version__, "retry_at": time.time() + 999999},
    )
    monkeypatch.delenv("KIMI_MEMORY_NO_AUTOSTART")
    spawned = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda *a, **kw: spawned.append((a, kw)))
    for _ in range(4):
        handle({"hook_event_name": "SessionStart", "session_id": "s"}, home)
    assert len(spawned) == 1 and spawned[0][0][0][-1] == "check-updates"
    options = spawned[0][1]
    assert options["stdin"] == options["stdout"] == options["stderr"] == subprocess.DEVNULL
    assert options["env"]["KIMI_MEMORY_HOME"] == str(home)
    seed_release(home)
    updates.schedule_check(home)
    assert len(spawned) == 1


def test_spawn_failure_retries_only_after_launch_cooldown(home, monkeypatch):
    monkeypatch.delenv("KIMI_MEMORY_NO_AUTOSTART")
    calls = []

    def failed(*_, **__):
        calls.append(1)
        raise OSError("not available")

    monkeypatch.setattr(updates.subprocess, "Popen", failed)
    updates.schedule_check(home)
    updates.schedule_check(home)
    assert len(calls) == 1
    future = time.time() + updates.LAUNCH_COOLDOWN + 1
    monkeypatch.setattr(updates.time, "time", lambda: future)
    updates.schedule_check(home)
    assert len(calls) == 2


def test_frozen_checker_launches_own_runtime_not_an_external_python_or_kimi(monkeypatch):
    from kimi_memory.platform import runtime_command

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert runtime_command("check-updates") == [sys.executable, "check-updates"]


def test_hot_hook_can_render_notice_with_all_network_and_model_modules_unavailable(home):
    seed_published(home)
    seed_release(home)
    code = """
import sys
for name in ('release_check', 'worker', 'store', 'config', 'kimi', 'models', 'http', 'server', 'workspace'):
    sys.modules['kimi_memory.' + name] = None
for name in ('urllib.request', 'http.client', 'socket'):
    sys.modules[name] = None
from kimi_memory.cli import main
raise SystemExit(main(['hook']))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(
            {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "hello"}
        ),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    text = json.loads(result.stdout)["message"]
    assert "update available" in text and "Previously published" in text


@pytest.mark.parametrize(
    "raw",
    ["broken [", "[]", '{"format": true}', '{"format": 999}', '{"format": 1, "pending": ["bad"]}'],
)
def test_bad_notice_state_does_not_disable_memory_or_accept_an_unrelated_turn(home, raw):
    seed_published(home)
    atomic_write(home / "updates/notice.json", raw)
    ack(home, prompt="unrelated")
    assert (
        "Previously published"
        in handle(
            {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "hello"}, home
        )["message"]
    )


def test_internal_generation_hooks_never_emit_notices_or_schedule_checks(home, monkeypatch):
    seed_release(home)
    monkeypatch.setenv("KIMI_MEMORY_INTERNAL", "1")

    def forbidden(*_, **__):
        raise AssertionError("Internal work must not touch notices")

    monkeypatch.setattr(updates, "prepare_notice", forbidden)
    monkeypatch.setattr(updates, "schedule_check", forbidden)
    for event in ("SessionStart", "UserPromptSubmit", "Stop", "TurnStarted"):
        assert handle({"hook_event_name": event, "session_id": "internal"}, home) == {}

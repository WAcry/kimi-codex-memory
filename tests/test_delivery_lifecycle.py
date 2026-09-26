"""Reader delivery retries, immutable snapshot pins and clean publication regressions."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace

from conftest import ScriptModel, seed_published
from test_store import save

from kimi_memory.files import atomic_write, digest, read_json, snapshot_lock, write_json
from kimi_memory.hooks import handle
from kimi_memory.issues import Issues
from kimi_memory.reader import acknowledge_injection, injection_for, touch_injection
from kimi_memory.store import Store
from kimi_memory.worker import phase_two
from kimi_memory.workspace import clean_current_publication, current_generation, prune_generations


def receipt(home, session="s"):
    return read_json(home / "injections" / f"{digest(session)}.json")


def commit(home, prompt="hello", session="s"):
    acknowledge_injection(session, {"origin_kind": "user", "turn_id": 1, "prompt": prompt}, home)


def test_preparation_is_not_delivery_and_blocked_input_retries(home):
    seed_published(home)
    assert injection_for("s", home, prompt="blocked")
    assert receipt(home)["phase"] == "prepared" and receipt(home)["checked"] is False
    handle(
        {"hook_event_name": "SessionStart", "source": "resume", "session_id": "s"},
        home,
        spawn=False,
    )
    assert injection_for("s", home, prompt="hello")
    commit(home)
    assert receipt(home)["phase"] == "committed" and receipt(home)["checked"] is True
    assert injection_for("s", home, prompt="next") == ""


def test_wrong_or_missing_ack_is_not_delivery_and_never_persists_prompt(home):
    seed_published(home)
    prompt = "PRIVATE_USER_PROMPT_NOT_TO_PERSIST"
    injection_for("s", home, prompt=prompt)
    commit(home, "unrelated")
    acknowledge_injection("s", {"origin_kind": "task", "turn_id": 1, "prompt": prompt}, home)
    assert not receipt(home)["checked"]
    assert injection_for("s", home, prompt=prompt)
    commit(home, prompt)
    assert receipt(home)["checked"]
    assert prompt not in json.dumps(receipt(home))


def test_skill_prefix_can_be_removed_by_native_turn_started(home):
    seed_published(home)
    injection_for(
        "s",
        home,
        prompt=[{"type": "text", "text": "skill instructions"}, {"type": "text", "text": "hello"}],
    )
    commit(home)
    assert receipt(home)["checked"]


def test_one_pointer_read_binds_text_receipt_and_pin(home, monkeypatch):
    from kimi_memory import reader

    a = seed_published(home, "SNAPSHOT_A")
    b = seed_published(home, "SNAPSHOT_B")
    calls = []

    def selected(_):
        calls.append(1)
        return a if len(calls) == 1 else b

    monkeypatch.setattr(reader, "published_root", selected)
    text = injection_for("s", home, prompt="hello")
    assert a.as_posix() in text and "SNAPSHOT_A" in text
    assert receipt(home)["generation"] == a.name and len(calls) == 1
    for _ in range(5):
        seed_published(home)
    prune_generations(home, 3)
    assert a.exists()


def test_gc_waits_until_render_has_pinned_the_snapshot(home, monkeypatch):
    from kimi_memory import reader

    a = seed_published(home, "PINNED_A")
    entered, release = threading.Event(), threading.Event()
    original = reader._render_snapshot

    def blocked(*args):
        result = original(*args)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(reader, "_render_snapshot", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        render_future = pool.submit(injection_for, "s", home, prompt="hello")
        assert entered.wait(5)

        # The normal publisher shares this same lock and cannot switch/retire A here.
        def publish_and_gc():
            with snapshot_lock(home, timeout=5):
                for _ in range(5):
                    seed_published(home)
            prune_generations(home, 3)

        gc_future = pool.submit(publish_and_gc)
        time.sleep(0.05)
        assert not gc_future.done()
        release.set()
        assert "PINNED_A" in render_future.result()
        gc_future.result()
    assert a.exists() and receipt(home)["generation"] == a.name


def test_resume_renews_pin_without_reinjection_and_missing_old_pin_rebuilds_once(home):
    a = seed_published(home, "LONG_SESSION_A")
    injection_for("s", home, prompt="hello")
    commit(home)
    state = receipt(home)
    state.update(time=time.time() - 40 * 86400, last_seen=time.time() - 40 * 86400)
    write_json(home / "injections" / f"{digest('s')}.json", state)
    touch_injection("s", home)
    for _ in range(5):
        seed_published(home)
    prune_generations(home, 3)
    assert a.exists() and injection_for("s", home, prompt="next") == ""
    state = receipt(home)
    state["last_seen"] = time.time() - 31 * 86400
    write_json(home / "injections" / f"{digest('s')}.json", state)
    prune_generations(home, 3)
    assert not a.exists()
    touch_injection("s", home)
    text = injection_for("s", home, prompt="return")
    assert "earlier memory snapshot is no longer available" in text
    assert current_generation(home).as_posix() in text
    commit(home, "return")
    assert injection_for("s", home, prompt="continue") == ""


def test_deleted_source_never_survives_in_current_diff_or_git_objects(home, config, source):
    store = Store(home / "state.sqlite")
    marker = "UNIQUE_REMOVED_SOURCE_MARKER"
    try:
        save(store, source, summary=marker)
        old = phase_two(store, config, home, ScriptModel())
        config = replace(
            config, generation=replace(config.generation, exclude_session_ids=(source.id,))
        )
        phase_two(store, config, home, ScriptModel())
        current = current_generation(home)
        assert current.name != old
        assert (
            not (current / ".git").exists() and not (current / "phase2_workspace_diff.md").exists()
        )
        assert all(
            marker.encode() not in path.read_bytes()
            for path in current.rglob("*")
            if path.is_file()
        )
        # Existing snapshots/DB are not a cryptographic erasure promise.
        assert store.has_summary(source.id)
    finally:
        store.close()


def test_old_published_processing_artifacts_are_removed_without_regeneration(home):
    current = seed_published(home)
    atomic_write(current / "phase2_workspace_diff.md", "old deleted data")
    atomic_write(current / ".git/objects/old", "old deleted data")
    summary = (current / "memory_summary.md").read_bytes()
    clean_current_publication(home, issues=Issues())
    assert not (current / ".git").exists() and not (current / "phase2_workspace_diff.md").exists()
    assert (current / "memory_summary.md").read_bytes() == summary


def test_bookkeeping_write_failure_does_not_disable_readable_memory(home, monkeypatch):
    from kimi_memory.reader import render

    seed_published(home, "STILL_READABLE_LOCAL_MEMORY")

    @contextmanager
    def readonly(*_, **__):
        raise PermissionError("test snapshot lock is not writable")
        yield

    monkeypatch.setattr("kimi_memory.reader.snapshot_lock", readonly)
    assert "STILL_READABLE_LOCAL_MEMORY" in render(home)
    assert "STILL_READABLE_LOCAL_MEMORY" in injection_for("s", home, prompt="hello")
    assert not (home / "injections" / f"{digest('s')}.json").exists()

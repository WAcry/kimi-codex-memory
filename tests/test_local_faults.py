import json
import time
from dataclasses import replace

import pytest
from conftest import NativeApi, ScriptModel, iso, serve, turn
from test_evidence import BLOCK
from test_session_isolation import pair, run_with
from test_store import save

from kimi_memory.files import atomic_write, published_root, write_json
from kimi_memory.issues import Issues
from kimi_memory.kimi import KimiClient
from kimi_memory.scan import clean_events
from kimi_memory.server import live_instances
from kimi_memory.store import Store
from kimi_memory.worker import phase_two, run
from kimi_memory.workspace import Workspace


@pytest.mark.parametrize("damage", ["removed", "invalid_utf8", "oversize", "symlink"])
def test_one_bad_note_is_skipped_without_discarding_healthy_inputs(
    home, config, source, tmp_path, monkeypatch, damage
):
    notes = home / "memories_v2/extensions/ad_hoc/notes"
    broken = notes / "a-bad.md"
    healthy = notes / "b-good.md"
    atomic_write(broken, "original explicit user request")
    atomic_write(healthy, "healthy user correction")
    store = Store(home / "state.sqlite")
    save(store, source)
    phase_two(store, config, home, ScriptModel())
    old = published_root(home)
    if damage == "invalid_utf8":
        atomic_write(broken, b"\xff\xfe")
    elif damage == "oversize":
        atomic_write(broken, "x" * 3000)
    elif damage == "symlink":
        broken.unlink()
        outside = tmp_path / "outside.md"
        atomic_write(outside, "must never read this private unrelated file")
        broken.symlink_to(outside)
    if damage == "removed":
        from kimi_memory import workspace as module

        original = module.read_bounded

        def read(path, *args):
            if path == broken:
                path.unlink(missing_ok=True)
                raise FileNotFoundError(path)
            return original(path, *args)

        monkeypatch.setattr(module, "read_bounded", read)
    config = replace(config, generation=replace(config.generation, max_notes_bytes=2048))
    atomic_write(healthy, "changed healthy correction")
    issues = Issues()
    try:
        phase_two(store, config, home, ScriptModel(), issues=issues)
        current = published_root(home)
        assert current != old and issues.count > 0
        assert (
            current / "extensions/ad_hoc/notes/a-bad.md"
        ).read_text() == "original explicit user request"
        assert (
            current / "extensions/ad_hoc/notes/b-good.md"
        ).read_text() == "changed healthy correction"
        assert "private unrelated" not in json.dumps(issues.summary())
    finally:
        store.close()


def test_generation_cleanup_failure_cannot_turn_a_committed_publication_into_failure(
    home, config, source, monkeypatch
):
    store = Store(home / "state.sqlite")
    save(store, source)
    phase_two(store, config, home, ScriptModel())
    old = published_root(home)
    atomic_write(home / "memories_v2/extensions/ad_hoc/notes/change.md", "a new explicit request")

    from kimi_memory.platform import remove_owned_tree

    def denied(path):
        if path.name.startswith("gc-"):
            raise PermissionError("simulated locked retired directory")
        return remove_owned_tree(path)

    monkeypatch.setattr("kimi_memory.workspace.remove_owned_tree", denied)
    issues = Issues()
    try:
        output = phase_two(
            store,
            replace(config, generation=replace(config.generation, retained_generations=1)),
            home,
            ScriptModel(),
            issues=issues,
        )
        assert published_root(home).name == output and published_root(home) != old
        assert not old.exists() and issues.count >= 1
        assert list((home / "_staging").glob("gc-*"))
        assert store.pending_publication() is None
    finally:
        store.close()


def test_read_snapshot_keeps_deleted_baseline_available_to_model(home, config, source):
    store = Store(home / "state.sqlite")
    save(store, source)
    phase_two(store, config, home, ScriptModel())
    workspace = Workspace(home, store.selected(cutoff=0, limit=10), config.generation)
    try:
        (published_root(home) / "memory_summary.md").unlink()
        workspace.prepare()
        assert (workspace.path / "memory_summary.md").read_text().startswith("v1")
    finally:
        workspace.close()
        store.close()


def test_partial_citations_count_valid_steps_but_preserve_retention(home, config, transcript):
    store = Store(home / "state.sqlite")
    save(store, replace(transcript.source, id="session_source"))
    store.close()
    good = turn(transcript.source, 1, BLOCK)
    bad = turn(transcript.source, 2, BLOCK)
    bad["steps"][0]["endedAt"] = "bad clock"
    third = turn(transcript.source, 3, BLOCK)
    third["steps"][0]["endedAt"] = iso(time.time() + 36000)
    t = replace(transcript, items=[good, bad, third])
    result, _ = run_with(home, config, NativeApi([t]))
    assert result["citations_counted"] == 1 and result["retention_deferred"]
    assert result["issues"]["counts"]["citation:incomplete_history"] >= 1
    store = Store(home / "state.sqlite")
    try:
        assert not store.scan_is_current(transcript.source)
        assert (
            store.db.execute(
                "SELECT usage_count FROM summaries WHERE source_id='session_source'"
            ).fetchone()[0]
            == 1
        )
    finally:
        store.close()


def test_failed_queued_source_is_retried_without_replaying_good_notifications(
    home, config, transcript, monkeypatch
):
    bad, good = pair(transcript)
    native = NativeApi([bad, good])

    def callback(method, path, body, headers):
        if path.startswith("/api/v1/sessions/session_bad/transcript"):
            return 500, {"code": 50001}
        return native(method, path, body, headers)

    write_json(home / "queue/good.json", {"event": "Stop", "session_id": good.source.id})
    write_json(home / "queue/bad.json", {"event": "Stop", "session_id": bad.source.id})
    write_json(home / "queue/missing.json", {"event": "Stop", "session_id": "deleted"})
    write_json(home / "queue/malformed.json", {"event": [], "session_id": "broken", "time": []})
    from kimi_memory import worker

    original = worker.run_pass
    calls = 0
    with serve(callback) as (origin, _):

        def patched(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(
                *args,
                **kwargs,
                client=KimiClient(origin, lambda: "test-native-token-never-log", config.api),
                models=(ScriptModel(), ScriptModel()),
            )

        monkeypatch.setattr(worker, "run_pass", patched)
        monkeypatch.setattr(worker, "load_worker_config", lambda _: config)
        result = run(home, drain=True)
    assert result["state"] == "degraded" and calls == 1
    assert [p.name for p in (home / "queue").glob("*.json")] == ["bad.json"]


def test_malformed_notifications_cannot_throw_during_sanitization():
    for event in [
        None,
        {},
        {"event": [], "session_id": "x"},
        {"event": "Stop", "session_id": "x", "time": 10**1000},
        {"event": "Stop", "session_id": "x", "time": float("nan")},
        {"event": "Stop", "session_id": []},
        {"event": "Stop", "session_id": "x", "time": {}},
    ]:
        assert clean_events([event], time.time()) == []


def test_diagnostics_are_bounded_and_do_not_include_paths_or_error_contents():
    issues = Issues()
    for index in range(100):
        issues.add("history", ValueError("private transcript"), "private-path-" + str(index))
    data = issues.summary()
    assert data["count"] == 100 and len(data["samples"]) == 10
    assert "private" not in json.dumps(data)


def test_new_requester_rearms_failed_jobs_once_without_reextracting_successes(home, source):
    store = Store(home / "state.sqlite")
    success = replace(source, id="success")
    save(store, success)
    owner = store.claim("extract:failed", "v1", now=10, lease=60, attempts=1)
    store.fail("extract:failed", owner, now=11, delay=3600, code="model_error")
    store.prepare_extraction_requester("native-v2", 3)
    row = store.db.execute("SELECT * FROM jobs WHERE job_key='extract:failed'").fetchone()
    assert row["attempts_left"] == 3 and row["retry_after"] == 0
    owner = store.claim("extract:failed", "v1", now=12, lease=60, attempts=3)
    store.fail("extract:failed", owner, now=13, delay=3600, code="invalid_extraction_output")
    store.prepare_extraction_requester("native-v2", 3)
    row = store.db.execute("SELECT * FROM jobs WHERE job_key='extract:failed'").fetchone()
    assert row["attempts_left"] == 2 and row["retry_after"] == 3613
    assert store.has_summary(success.id)
    store.close()


def test_invalid_server_registration_does_not_hide_a_healthy_peer(home, monkeypatch):
    import os

    root = home / "server/instances"
    write_json(
        root / "bad.json",
        {
            "pid": os.getpid(),
            "port": 12345,
            "host": "127.0.0.1",
            "server_id": "bad",
            "started_at": "broken",
        },
    )
    write_json(
        root / "good.json",
        {
            "pid": os.getpid(),
            "port": 12346,
            "host": "127.0.0.1",
            "server_id": "good",
            "started_at": 1,
        },
    )
    assert [entry["server_id"] for entry in live_instances(home)] == ["good"]

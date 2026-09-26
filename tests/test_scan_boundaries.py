import time
from dataclasses import replace
from urllib.parse import urlsplit

from conftest import NativeApi, ScriptModel, source_json
from test_session_isolation import pair, run_with
from test_store import save

from kimi_memory.files import published_root
from kimi_memory.store import Store
from kimi_memory.worker import phase_two


def test_later_session_page_failure_keeps_prior_work_and_does_not_evict_old_selection(
    home, config, transcript
):
    old = replace(transcript.source, id="old", updated_at=1)
    store = Store(home / "state.sqlite")
    save(store, old)
    store.db.execute("UPDATE summaries SET selected=1")
    store.close()
    native = NativeApi([transcript])

    def callback(method, path, body, headers):
        if urlsplit(path).path == "/api/v1/sessions":
            if "before_id=" in path:
                return 500, {"code": 50001}
            return 200, {
                "code": 0,
                "data": {"items": [source_json(transcript.source)], "has_more": True},
            }
        return native(method, path, body, headers)

    result, _ = run_with(home, config, callback)
    assert result["summaries"] == 2 and result["retention_deferred"]
    assert len(list((published_root(home) / "rollout_summaries").glob("*.md"))) == 2


def test_malformed_last_row_can_still_use_its_cursor_and_reach_good_next_page(
    home, config, transcript
):
    bad, good = pair(transcript)
    native = NativeApi([bad, good])

    def callback(method, path, body, headers):
        status, value = native(method, path, body, headers)
        if urlsplit(path).path == "/api/v1/sessions" and "before_id=" not in path:
            value["data"]["items"][0]["metadata"] = []
        return status, value

    result, _ = run_with(home, replace(config, api=replace(config.api, page_size=1)), callback)
    assert result["state"] == "degraded" and result["extractions"] == ["extracted"]


def test_session_scan_budget_does_not_discard_every_valid_candidate(home, config, transcript):
    bad, good = pair(transcript)
    result, _ = run_with(
        home,
        replace(config, generation=replace(config.generation, max_session_scan=1)),
        NativeApi([bad, good]),
    )
    assert result["extractions"] == ["extracted"] and result["retention_deferred"]
    assert result["summaries"] == 1


def test_deleted_second_session_after_a_success_is_not_a_global_error(home, config, transcript):
    first, second = pair(transcript)
    native = NativeApi([first, second])

    def callback(method, path, body, headers):
        status, value = native(method, path, body, headers)
        if urlsplit(path).path == "/api/v1/sessions/session_bad":
            native.transcripts.pop(second.source.id, None)
        return status, value

    result, _ = run_with(home, config, callback)
    assert result["state"] == "ready" and result["extractions"] == ["extracted"]
    assert result["missing_sessions"] == 1


def test_all_faulty_histories_still_allow_explicit_note_consolidation(home, config, transcript):
    from kimi_memory.files import atomic_write

    atomic_write(
        home / "memories_v2/extensions/ad_hoc/notes/user.md",
        "Remember this explicit synthetic preference.",
    )
    native = NativeApi([transcript])

    def callback(method, path, body, headers):
        if "/transcript?" in path:
            return 500, {"code": 50001}
        return native(method, path, body, headers)

    result, _ = run_with(home, config, callback)
    assert result["state"] == "degraded" and result["retention_deferred"]
    assert (published_root(home) / "extensions/ad_hoc/notes/user.md").is_file()


def test_metadata_budget_does_not_remove_previous_selected_rows_when_limit_decreased(home, source):
    store = Store(home / "state.sqlite")
    try:
        for index in range(3):
            save(store, replace(source, id=f"source{index}", updated_at=index + 1))
        store.db.execute("UPDATE summaries SET selected=1")
        rows = store.selected(cutoff=time.time() - 86400, limit=1, preserve=True)
        assert len(rows) == 3
        assert store.selected(cutoff=time.time() - 86400, limit=1) == []
    finally:
        store.close()


def test_empty_replacement_during_partial_sync_preserves_other_progress(home, config, transcript):
    old = replace(transcript, source=replace(transcript.source, id="empty-old"))
    good = replace(
        transcript,
        source=replace(
            transcript.source, id="good-new", updated_at=transcript.source.updated_at - 1
        ),
    )
    broken = replace(
        transcript,
        source=replace(transcript.source, id="broken", updated_at=transcript.source.updated_at + 1),
    )
    store = Store(home / "state.sqlite")
    save(store, old.source)
    phase_two(store, config, home, ScriptModel())
    store.close()
    native = NativeApi([broken, old, good])

    def callback(method, path, body, headers):
        if path.startswith("/api/v1/sessions/broken/transcript"):
            return 500, {"code": 50001}
        return native(method, path, body, headers)

    class Selective(ScriptModel):
        def complete(self, messages, **kwargs):
            if "session_id: empty-old" in messages[-1]["content"]:
                return {"content": '{"rollout_summary":"","rollout_slug":""}'}
            return super().complete(messages, **kwargs)

    result, _ = run_with(home, config, callback, models=(Selective(), ScriptModel()))
    assert result["state"] == "degraded" and result["summaries"] == 2
    assert sorted(result["extractions"]) == ["extracted", "failed"]
    assert len(list((published_root(home) / "rollout_summaries").glob("*.md"))) == 2

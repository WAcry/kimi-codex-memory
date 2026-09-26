import json
from dataclasses import replace
from urllib.parse import urlsplit

import pytest
from conftest import NativeApi, ScriptModel, serve, turn
from test_evidence import BLOCK
from test_store import save

from kimi_memory.files import published_root, write_json
from kimi_memory.kimi import KimiClient
from kimi_memory.store import Store
from kimi_memory.worker import phase_two, run_pass


def pair(transcript):
    bad = replace(transcript, source=replace(transcript.source, id="session_bad"))
    good = replace(
        transcript,
        source=replace(
            transcript.source, id="session_good", updated_at=transcript.source.updated_at - 2
        ),
    )
    return bad, good


def run_with(home, config, api, events=(), models=None, **kwargs):
    with serve(api) as (origin, requests):
        client = KimiClient(origin, lambda: "test-native-token-never-log", config.api)
        result = run_pass(
            home,
            config,
            list(events),
            client=client,
            models=models or (ScriptModel(), ScriptModel()),
            **kwargs,
        )
    return result, requests


@pytest.mark.parametrize("status,code", [(404, 40401), (410, 40401), (200, 40401)])
@pytest.mark.parametrize("when", ["forced", "listed", "page", "recheck"])
def test_deleted_source_at_each_read_boundary_does_not_block_healthy_source(
    home, config, transcript, status, code, when
):
    bad, good = pair(transcript)
    bad = replace(bad, items=[turn(bad.source, 1), turn(bad.source, 2)])
    native = NativeApi([good] if when == "forced" else [bad, good])
    transcript_reads = 0

    def callback(method, path, body, headers):
        nonlocal transcript_reads
        route = urlsplit(path).path
        if route.startswith("/api/v1/sessions/session_bad"):
            if route.endswith("/transcript"):
                transcript_reads += 1
            fail = (
                when in {"forced", "listed"}
                or (when == "page" and transcript_reads > 1)
                or (when == "recheck" and not route.endswith("/transcript"))
            )
            if fail:
                return status, {"code": code}
        return native(method, path, body, headers)

    events = [{"event": "SessionEnd", "session_id": bad.source.id}] if when == "forced" else []
    ack = set()
    config = replace(config, api=replace(config.api, page_size=1))
    result, _ = run_with(home, config, callback, events, acknowledged=ack)
    assert result["state"] == "ready" and result["missing_sessions"] == 1
    assert result["extractions"] == ["extracted"]
    assert bad.source.id in ack
    store = Store(home / "state.sqlite")
    try:
        assert [r["source_id"] for r in store.selected(cutoff=0, limit=10)] == [good.source.id]
        assert (
            store.db.execute(
                "SELECT 1 FROM scan_state WHERE source_id=?", (bad.source.id,)
            ).fetchone()
            is None
        )
    finally:
        store.close()


@pytest.mark.parametrize("status,code", [(401, 40101), (403, 40301), (500, 50001), (200, 50001)])
def test_non_missing_errors_do_not_acknowledge_deletion(home, config, transcript, status, code):
    native = NativeApi([transcript])

    def callback(method, path, body, headers):
        if path.startswith("/api/v1/sessions/unreadable"):
            return status, {"code": code}
        return native(method, path, body, headers)

    ack = set()
    result, _ = run_with(
        home, config, callback, [{"event": "Stop", "session_id": "unreadable"}], acknowledged=ack
    )
    assert result["missing_sessions"] == 0 and result["retention_deferred"]
    assert "unreadable" not in ack and result["state"] == "degraded"


@pytest.mark.parametrize("damage", ["origin", "missing_frames", "large", "citation", "metadata"])
def test_bad_session_is_isolated_and_old_selected_sources_are_not_expired(
    home, config, transcript, damage
):
    bad, good = pair(transcript)
    old = replace(transcript.source, id="session_source", updated_at=1, created_at=0)
    store = Store(home / "state.sqlite")
    save(store, old)
    store.db.execute("UPDATE summaries SET selected=1")
    store.close()
    native = NativeApi([bad, good])

    def callback(method, path, body, headers):
        status, payload = native(method, path, body, headers)
        if path.startswith("/api/v1/sessions/session_bad/transcript"):
            page = payload["data"]
            if damage == "origin":
                page["items"][0]["origin"]["kind"] = "unknown-future-kind"
            if damage == "missing_frames":
                page["items"][0]["steps"][0].pop("frames")
            if damage == "large":
                page["items"][0]["prompt"] = "x" * 10000
            if damage == "citation":
                step = page["items"][0]["steps"][0]
                step["frames"][0]["text"] = BLOCK
                step["endedAt"] = "not-a-date"
        if damage == "metadata" and urlsplit(path).path == "/api/v1/sessions":
            payload["data"]["items"][0]["updated_at"] = "not-a-date"
        return status, payload

    if damage == "large":
        config = replace(config, api=replace(config.api, max_transcript_bytes=5000))
    result, _ = run_with(home, config, callback)
    assert result["state"] == "degraded" and result["retention_deferred"] and result["pruned"] == 0
    assert "extracted" in result["extractions"]
    store = Store(home / "state.sqlite")
    try:
        assert store.has_summary(good.source.id) and store.has_summary(old.id)
        assert (
            store.db.execute(
                "SELECT selected FROM summaries WHERE source_id=?", (old.id,)
            ).fetchone()[0]
            == 1
        )
        assert not store.scan_is_current(bad.source)
    finally:
        store.close()
    assert len(list((published_root(home) / "rollout_summaries").glob("*.md"))) >= 2


@pytest.mark.parametrize(
    "field,value",
    [("archived", True), ("busy", True), ("updated_at", 9999999999), ("cwd", "/moved")],
)
def test_metadata_change_during_transcript_does_not_publish_inconsistent_source(
    home, config, transcript, field, value
):
    bad, good = pair(transcript)
    native = NativeApi([bad, good])

    def callback(method, path, body, headers):
        status, payload = native(method, path, body, headers)
        if urlsplit(path).path == "/api/v1/sessions/session_bad":
            if field == "cwd":
                payload["data"]["metadata"]["cwd"] = value
            else:
                payload["data"][field] = value
        return status, payload

    result, _ = run_with(home, config, callback)
    assert result["extractions"] == ["extracted"] and result["state"] == "degraded"


@pytest.mark.parametrize("phase", ["extraction", "consolidation"])
@pytest.mark.parametrize("action", ["delete", "archive", "close"])
def test_source_change_after_snapshot_does_not_abort_generation(
    home, config, transcript, phase, action
):
    native = NativeApi([transcript])
    generating = False

    def callback(*args):
        assert not generating, "No live history should be reread during model work"
        return native(*args)

    class MutatingModel(ScriptModel):
        def complete(self, *args, **kwargs):
            nonlocal generating
            generating = True
            if action == "delete":
                native.transcripts.clear()
            elif action == "archive":
                native.transcripts[transcript.source.id] = replace(
                    transcript, source=replace(transcript.source, archived=True)
                )
            write_json(
                home / "queue/during-model.json",
                {"event": "SessionEnd", "session_id": transcript.source.id},
            )
            return super().complete(*args, **kwargs)

    models = (
        (MutatingModel(), ScriptModel())
        if phase == "extraction"
        else (ScriptModel(), MutatingModel())
    )
    result, _ = run_with(home, config, callback, models=models, initial_queue=set())
    assert result["state"] == "ready" and result["summaries"] == 1
    assert result["retention_deferred"] and result["pruned"] == 0
    assert (home / "queue/during-model.json").exists()


def test_one_invalid_model_output_does_not_block_other_extraction_or_consolidation(
    home, config, transcript
):
    bad, good = pair(transcript)

    class Selective(ScriptModel):
        def complete(self, messages, **kwargs):
            if "session_id: session_bad" in messages[-1]["content"]:
                return {"content": "not JSON; no private response should be logged"}
            return super().complete(messages, **kwargs)

    result, _ = run_with(home, config, NativeApi([bad, good]), models=(Selective(), ScriptModel()))
    assert sorted(result["extractions"]) == ["extracted", "failed"]
    assert result["state"] == "degraded" and result["summaries"] == 1
    assert result["issues"]["counts"]["extraction:invalid_extraction_output"] == 1
    assert "private response" not in json.dumps(result)
    assert list((published_root(home) / "rollout_summaries").glob("*.md"))


def test_existing_summary_is_not_erased_when_cold_transcript_is_empty(home, config, transcript):
    bad, good = pair(transcript)
    store = Store(home / "state.sqlite")
    save(store, bad.source)
    phase_two(store, config, home, ScriptModel())
    store.close()
    native = NativeApi([replace(bad, items=[]), good])
    result, _ = run_with(home, config, native)
    assert result["state"] == "degraded" and result["summaries"] == 2
    store = Store(home / "state.sqlite")
    try:
        assert not store.scan_is_current(bad.source)
    finally:
        store.close()

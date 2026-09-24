import copy
import time
from dataclasses import replace

import pytest
from conftest import NativeApi, ScriptModel, seed_published, serve, turn
from test_evidence import BLOCK
from test_store import save

from kimi_memory.errors import CompatibilityError, ModelError
from kimi_memory.files import write_json
from kimi_memory.hooks import handle
from kimi_memory.kimi import KimiClient
from kimi_memory.store import Store
from kimi_memory.worker import extract_one, run_pass
from kimi_memory.workspace import current_generation


def test_end_to_end_history_extraction_publication_and_offline_injection(home, config, transcript):
    extraction, consolidation = ScriptModel(), ScriptModel()
    with serve(NativeApi([transcript])) as (origin, requests):
        api = KimiClient(origin, lambda: "test-native-token-never-log", config.api)
        api.handshake()
        result = run_pass(home, config, [], client=api, models=(extraction, consolidation))
    assert result["state"] == "ready" and result["summaries"] == 1
    assert result["extractions"] == ["extracted"]
    assert all(request[0] == "GET" for request in requests)
    message = handle({"hook_event_name": "UserPromptSubmit", "session_id": "new-session"}, home)[
        "message"
    ]
    assert "rollout_summaries/" in message and "Grep or rg" in message
    assert "RAW-INPUT-NOT-FOR-DURABLE-STORAGE" in extraction.calls[0][1]["content"]
    for path in home.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert b"RAW-INPUT-NOT-FOR-DURABLE-STORAGE" not in path.read_bytes()


def test_second_pass_does_not_repeat_extraction_or_consolidation(home, config, transcript):
    extraction, consolidation = ScriptModel(), ScriptModel()
    with serve(NativeApi([transcript])) as (origin, _):
        api = KimiClient(origin, lambda: "test-native-token-never-log", config.api)
        first = run_pass(home, config, [], client=api, models=(extraction, consolidation))
        calls = (len(extraction.calls), len(consolidation.calls))
        second = run_pass(home, config, [], client=api, models=(extraction, consolidation))
    assert first["state"] == second["state"] == "ready"
    assert (len(extraction.calls), len(consolidation.calls)) == calls
    assert second["publication"] == "unchanged"


def test_long_extraction_preserves_final_corrections_like_codex(home, config, transcript):
    store = Store(home / "state.sqlite")
    try:
        text = "EARLIER TASK\n" + "证据" * 5000 + "\nFINAL USER CORRECTION"
        extract_one(transcript, store, config, ScriptModel(summary=text), home)
        summary = store.selected(cutoff=0, limit=1)[0]["summary"]
        assert summary.startswith("EARLIER TASK") and summary.endswith("FINAL USER CORRECTION")
        assert "chars truncated" in summary and "�" not in summary
        assert len(summary.encode()) <= config.generation.max_rollout_summary_bytes + 64
    finally:
        store.close()


def test_citation_sync_before_idle_generation_and_retention(home, config, transcript):
    store = Store(home / "state.sqlite")
    cited = replace(transcript.source, id="session_source", updated_at=time.time() - 31 * 86400)
    save(store, cited)
    store.close()
    recent_source = replace(transcript.source, updated_at=float(int(time.time())) - 30)
    data = replace(transcript, source=recent_source, items=[turn(recent_source, text=BLOCK)])
    with serve(NativeApi([data])) as (origin, _):
        result = run_pass(
            home,
            config,
            [],
            client=KimiClient(origin, lambda: "test-native-token-never-log", config.api),
            models=(ScriptModel(), ScriptModel()),
        )
    assert result["citations_counted"] == 1 and result["pruned"] == 0
    assert result["extractions"] == []
    store = Store(home / "state.sqlite")
    try:
        row = store.selected(cutoff=0, limit=1)[0]
        assert row["usage_count"] == 1
        assert row["last_usage"] < time.time() - 30
    finally:
        store.close()


def test_generation_failure_preserves_old_memory_and_hooks(home, config, transcript):
    old = seed_published(home)
    with serve(NativeApi([transcript])) as (origin, _), pytest.raises(ModelError):
        run_pass(
            home,
            config,
            [],
            client=KimiClient(origin, lambda: "test-native-token-never-log", config.api),
            models=(ScriptModel(fail=True), ScriptModel()),
        )
    assert current_generation(home) == old
    assert (
        "Previously published"
        in handle({"hook_event_name": "UserPromptSubmit", "session_id": "s"}, home)["message"]
    )


def test_broken_api_never_prunes_or_overwrites_old_memory(home, config, transcript):
    old = seed_published(home)
    store = Store(home / "state.sqlite")
    save(store, replace(transcript.source, updated_at=1))
    store.close()
    server = NativeApi([transcript])
    page = copy.deepcopy(transcript.items)
    page[0]["origin"]["kind"] = "new-schema-origin"
    server.transcripts[transcript.source.id] = replace(transcript, items=page)
    with serve(server) as (origin, _), pytest.raises(CompatibilityError):
        run_pass(
            home,
            config,
            [],
            client=KimiClient(origin, lambda: "test-native-token-never-log", config.api),
            models=(ScriptModel(), ScriptModel()),
        )
    store = Store(home / "state.sqlite")
    try:
        assert store.stats()["summaries"] == 1
    finally:
        store.close()
    assert current_generation(home) == old


def test_current_active_archived_and_excluded_sources_are_not_extracted(home, config, transcript):
    cases = [
        replace(transcript, source=replace(transcript.source, id="active", busy=True)),
        replace(transcript, source=replace(transcript.source, id="archived", archived=True)),
        replace(transcript, source=replace(transcript.source, id="excluded")),
        replace(transcript, source=replace(transcript.source, id="current")),
    ]
    config = replace(
        config, generation=replace(config.generation, exclude_session_ids=("excluded",))
    )
    extraction = ScriptModel()
    with serve(NativeApi(cases)) as (origin, _):
        result = run_pass(
            home,
            config,
            [{"session_id": "current", "event": "TurnStarted"}],
            client=KimiClient(origin, lambda: "test-native-token-never-log", config.api),
            models=(extraction, ScriptModel()),
        )
    assert result["extractions"] == [] and extraction.calls == []


def test_new_hook_notifications_delay_retention(home, config, transcript):
    old = seed_published(home)
    write_json(home / "queue/new.json", {"event": "Stop", "session_id": transcript.source.id})
    with serve(NativeApi([transcript])) as (origin, _):
        result = run_pass(
            home,
            config,
            [],
            initial_queue=set(),
            client=KimiClient(origin, lambda: "test-native-token-never-log", config.api),
            models=(ScriptModel(), ScriptModel()),
        )
    assert result["state"] == "pending_citations"
    assert current_generation(home) == old


def test_bad_extraction_json_does_not_write_memory(home, config, transcript):
    class InvalidModel(ScriptModel):
        def complete(self, *_, **__):
            return {"content": '{"rollout_summary":"fake","raw_memory":"v1 shape"}'}

    store = Store(home / "state.sqlite")
    try:
        with pytest.raises(ModelError):
            extract_one(transcript, store, config, InvalidModel(), home)
        assert store.stats()["summaries"] == 0
    finally:
        store.close()


def test_successful_empty_extraction_removes_old_source_not_reading(home, config, transcript):
    store = Store(home / "state.sqlite")
    try:
        save(store, transcript.source, "old")
        assert extract_one(transcript, store, config, ScriptModel(summary=""), home) == "empty"
        assert store.stats()["summaries"] == 0
        assert extract_one(transcript, store, config, ScriptModel(), home) == "skipped"
    finally:
        store.close()

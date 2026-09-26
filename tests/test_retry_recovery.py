"""External conditions defer; bounded invalid sources recover after a real config change."""

import json
import time
from dataclasses import replace

import pytest
from conftest import NativeApi, ScriptModel, serve
from test_store import save

from kimi_memory.cli import retry_sources
from kimi_memory.config import ModelConfig
from kimi_memory.errors import BudgetError, ConfigurationError, ExtractionOutputError, ModelError
from kimi_memory.files import atomic_write
from kimi_memory.kimi import KimiClient
from kimi_memory.models import CallBudget, Model
from kimi_memory.store import Store
from kimi_memory.worker import extract_one, run_pass


def error_for(kind):
    if kind == "budget":
        return BudgetError("test budget exhausted")
    if kind == "auth":
        return ConfigurationError("test OAuth unavailable")
    if kind == "network":
        return ConnectionError("test local network failure")
    error = ModelError("test provider failure")
    if isinstance(kind, int):
        error.status = kind
    else:
        error.code = "model_" + kind
    return error


@pytest.mark.parametrize(
    "kind",
    [
        "budget",
        "auth",
        "network",
        "connection",
        "timeout",
        "rate_limit",
        "quota_exhausted",
        "overloaded",
        400,
        401,
        403,
        429,
        500,
        503,
    ],
)
def test_recovered_external_condition_can_extract_after_more_than_three_failures(
    home, config, transcript, kind
):
    class Failing(ScriptModel):
        def complete(self, *_, **__):
            raise error_for(kind)

    store = Store(home / "state.sqlite")
    try:
        for _ in range(5):
            with pytest.raises(type(error_for(kind))):
                extract_one(transcript, store, config, Failing(), home)
            row = store.db.execute("SELECT * FROM jobs").fetchone()
            assert row["attempts_left"] == config.generation.max_extraction_attempts
        assert extract_one(transcript, store, config, ScriptModel(), home) == "extracted"
        assert store.has_summary(transcript.source.id)
    finally:
        store.close()


def test_daily_budget_defers_until_reset_without_burning_the_source(
    home, config, transcript, monkeypatch
):
    clock = time.time()
    monkeypatch.setattr("kimi_memory.worker.time.time", lambda: clock)
    store = Store(home / "state.sqlite")
    store.reserve_model_call(now=clock, daily_limit=1)

    class Budgeted(ScriptModel):
        def complete(self, *args, **kwargs):
            store.reserve_model_call(now=clock, daily_limit=1)
            return super().complete(*args, **kwargs)

    try:
        with pytest.raises(BudgetError):
            extract_one(transcript, store, config, Budgeted(), home)
        row = store.db.execute("SELECT * FROM jobs").fetchone()
        assert row["attempts_left"] == 3 and row["retry_after"] >= (int(clock) // 86400 + 1) * 86400
        assert extract_one(transcript, store, config, ScriptModel(), home) == "skipped"
        clock = row["retry_after"] + 1
        assert extract_one(transcript, store, config, Budgeted(), home) == "extracted"
    finally:
        store.close()


def test_per_run_budget_error_is_a_deferred_condition(home):
    store = Store(home / "state.sqlite")
    try:
        budget = CallBudget(store, daily=10, per_run=1)
        budget.reserve()
        with pytest.raises(BudgetError):
            budget.reserve()
        assert budget.calls == 1
    finally:
        store.close()


def test_invalid_output_is_bounded_then_config_change_recovers_without_upgrading_plugin(
    home, config, transcript
):
    class Invalid(ScriptModel):
        def complete(self, *_, **__):
            raise ExtractionOutputError("test malformed result")

    settings = ModelConfig(base_url="http://127.0.0.1:1", model="before")
    config = replace(config, extraction=settings)
    good = replace(transcript, source=replace(transcript.source, id="successful-other-source"))
    store = Store(home / "state.sqlite")
    save(store, good.source, good.version)
    store.scanned(good.source, good.version, time.time())
    store.close()
    with serve(NativeApi([transcript, good])) as (origin, _):
        client = KimiClient(origin, lambda: "test-native-token-never-log", config.api)
        for _ in range(3):
            result = run_pass(home, config, [], client=client, models=(Invalid(), ScriptModel()))
            assert result["extractions"] == ["failed"]
        result = run_pass(home, config, [], client=client, models=(ScriptModel(), ScriptModel()))
        assert result["extractions"] == [] and result["failed_extractions"] == 1
        changed = replace(config, extraction=replace(settings, model="after"))
        result = run_pass(home, changed, [], client=client, models=(ScriptModel(), ScriptModel()))
        assert result["extractions"] == ["extracted"] and result["failed_extractions"] == 0
        assert (
            run_pass(home, changed, [], client=client, models=(ScriptModel(), ScriptModel()))[
                "extractions"
            ]
            == []
        )
    store = Store(home / "state.sqlite")
    try:
        assert store.has_summary(good.source.id)
        assert store.has_summary(transcript.source.id)
    finally:
        store.close()


def test_effective_native_default_model_changes_retry_identity_without_credential_rotation(
    tmp_path,
):
    atomic_write(
        tmp_path / "config.toml",
        '[providers.p]\ntype="openai"\napi_key="private-test-token"\n[models.a]\nprovider="p"\nmodel="a"\n[models.b]\nprovider="p"\nmodel="b"\n',
    )
    a = Model(ModelConfig(), home=tmp_path, effective={"default_model": "a"}).retry_identity()
    b = Model(ModelConfig(), home=tmp_path, effective={"default_model": "b"}).retry_identity()
    assert a != b
    path = tmp_path / "config.toml"
    atomic_write(path, path.read_text().replace("private-test-token", "rotated-private-token"))
    assert (
        a == Model(ModelConfig(), home=tmp_path, effective={"default_model": "a"}).retry_identity()
    )
    assert "private" not in a and len(a) == 64


def test_explicit_retry_only_resets_failed_requested_source_and_never_calls_models(home, source):
    store = Store(home / "state.sqlite")
    success = replace(source, id="successful")
    save(store, success)
    for identity in ("first", "second"):
        owner = store.claim("extract:" + identity, "v", now=10, lease=60, attempts=1)
        store.fail(
            "extract:" + identity, owner, now=11, delay=3600, code="invalid_extraction_output"
        )
    store.close()
    before = retry_sources(home, list_only=True)
    assert len(before["failed_sources"]) == 2
    assert retry_sources(home, source_id="first")["reset"] == 1
    assert retry_sources(home, source_id="successful")["reset"] == 0
    assert retry_sources(home)["reset"] == 1
    assert retry_sources(home)["reset"] == 0
    store = Store(home / "state.sqlite")
    try:
        assert store.has_summary(success.id)
        assert store.db.execute("SELECT COUNT(*) FROM counters").fetchone()[0] == 0
        assert json.dumps(store.failed_sources()) == "[]"
    finally:
        store.close()


def test_provider_behavior_header_change_resets_identity_but_auth_header_does_not(
    tmp_path, monkeypatch
):
    config = ModelConfig(base_url="http://127.0.0.1:1", model="local")
    monkeypatch.setenv(
        "KIMI_CODE_CUSTOM_HEADERS", "Authorization: Bearer old\nX-Provider-Mode: stable"
    )
    before = Model(config, home=tmp_path).retry_identity()
    monkeypatch.setenv(
        "KIMI_CODE_CUSTOM_HEADERS", "Authorization: Bearer new\nX-Provider-Mode: stable"
    )
    assert Model(config, home=tmp_path).retry_identity() == before
    monkeypatch.setenv(
        "KIMI_CODE_CUSTOM_HEADERS", "Authorization: Bearer new\nX-Provider-Mode: fixed"
    )
    assert Model(config, home=tmp_path).retry_identity() != before

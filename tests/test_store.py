import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from kimi_memory.citations import CitationUse
from kimi_memory.errors import ConfigurationError, LeaseLostError, ModelError
from kimi_memory.store import Store


@pytest.fixture
def store(home):
    db = Store(home / "state.sqlite")
    yield db
    db.close()


def save(store, source, version="v1", now=None, summary="Retained history"):
    now = now or time.time()
    owner = store.claim("extract:" + source.id, version, now=now, lease=60, attempts=3)
    assert owner is not None
    store.save_extraction(source, version, summary, "retained" if summary else "", owner, now)


def test_only_one_owner_can_claim_a_job(store):
    now = time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        owners = list(
            pool.map(
                lambda _: store.claim("extract:s", "v", now=now, lease=60, attempts=3), range(8)
            )
        )
    assert sum(owner is not None for owner in owners) == 1


def test_lease_fencing_rejects_old_owner_and_does_not_clear_new_owner(store, source):
    now = time.time()
    old = store.claim("extract:" + source.id, "v", now=now, lease=10, attempts=3)
    new = store.claim("extract:" + source.id, "v", now=now + 11, lease=10, attempts=3)
    with pytest.raises(LeaseLostError):
        store.save_extraction(source, "v", "wrong", "wrong", old, now + 12)
    store.fail("extract:" + source.id, old, now=now + 12, delay=50, code="old")
    store.assert_owner("extract:" + source.id, new, now + 12)


def test_success_watermark_and_empty_result_prevent_repeated_models(store, source):
    save(store, source)
    assert store.claim("extract:" + source.id, "v1", now=time.time(), lease=60, attempts=3) is None
    save(store, source, "v2", summary="")
    assert store.stats()["summaries"] == 0
    assert store.claim("extract:" + source.id, "v2", now=time.time(), lease=60, attempts=3) is None


def test_retries_backoff_and_new_source_reset(store):
    now = time.time()
    for _attempt in range(3):
        owner = store.claim("extract:s", "v1", now=now, lease=60, attempts=3)
        assert owner
        store.fail("extract:s", owner, now=now, delay=10, code="model")
        assert store.claim("extract:s", "v1", now=now + 1, lease=60, attempts=3) is None
        now += 11
    assert store.claim("extract:s", "v1", now=now, lease=60, attempts=3) is None
    assert store.claim("extract:s", "v2", now=now, lease=60, attempts=3)


def test_citation_receipts_are_idempotent_and_event_time_does_not_regress(store, source):
    save(store, source)
    now = time.time()
    recent = CitationUse("event-new", frozenset({source.id}), now - 5)
    older = CitationUse("event-old", frozenset({source.id}), now - 100)
    assert store.record_citations([recent, recent, older], now=now) == 2
    row = store.selected(cutoff=0, limit=10)[0]
    assert row["usage_count"] == 2 and row["last_usage"] == now - 5
    assert store.record_citations([older, recent], now=now) == 0


def test_unknown_citation_never_creates_a_memory(store):
    use = CitationUse("event", frozenset({"missing"}), time.time())
    assert store.record_citations([use], now=time.time()) == 0
    assert store.stats() == {"summaries": 0, "citation_receipts": 1, "running_jobs": 0}


def test_future_citation_rolls_back_receipts(store, source):
    save(store, source)
    with pytest.raises(ConfigurationError):
        store.record_citations(
            [CitationUse("event", frozenset({source.id}), time.time() + 10000)], now=time.time()
        )
    assert store.stats()["citation_receipts"] == 0


def test_retention_matches_coalesce_not_max_or_generation_time(store, source):
    now = time.time()
    save(store, replace(source, updated_at=now - 100))
    store.record_citations([CitationUse("old", frozenset({source.id}), now - 10000)], now=now)
    assert store.selected(cutoff=now - 1000, limit=10) == []


def test_usage_count_beats_recency_but_does_not_bypass_expiry(store, source):
    now = time.time()
    old = replace(source, id="older-source", updated_at=now - 10000)
    recent = replace(source, id="recent-source", updated_at=now - 100)
    save(store, old)
    save(store, recent)
    store.record_citations([CitationUse("event", frozenset({old.id}), now - 500)], now=now)
    assert store.selected(cutoff=now - 1000, limit=1)[0]["source_id"] == old.id
    assert store.selected(cutoff=now - 200, limit=1)[0]["source_id"] == recent.id


def test_pruning_protects_previously_selected_sources(store, source):
    old = replace(source, updated_at=1)
    save(store, old)
    save(store, replace(old, id="unselected"))
    with store.transaction() as db:
        db.execute("UPDATE summaries SET selected=1 WHERE source_id=?", (old.id,))
    assert store.prune(cutoff=100, limit=200) == 1
    assert [r["source_id"] for r in store.selected(cutoff=0, limit=10)] == [old.id]


def test_reextraction_preserves_usage_statistics(store, source):
    save(store, source)
    use = CitationUse("event", frozenset({source.id}), time.time() - 10)
    store.record_citations([use], now=time.time())
    save(store, source, "v2")
    row = store.selected(cutoff=0, limit=1)[0]
    assert (row["source_version"], row["usage_count"], row["last_usage"]) == ("v2", 1, use.used_at)


def test_selected_snapshot_does_not_mark_concurrently_replaced_source(store, source):
    save(store, source, "before")
    now = time.time()
    owner = store.claim("consolidate", "inputs", now=now, lease=60, attempts=3, repeat=True)
    manifest = {
        "input_hash": "inputs",
        "sources": [{"source_id": source.id, "source_version": "before"}],
    }
    store.publication_intent("generation", owner, manifest, now)
    save(store, source, "after")
    store.finalize_publication("generation", now=now)
    assert store.selected(cutoff=0, limit=1)[0]["selected"] == 0


def test_global_success_cooldown_and_noop(store):
    now = time.time()
    owner = store.claim("consolidate", "a", now=now, lease=60, attempts=3, repeat=True)
    store.finish_noop(owner, "a", now)
    assert (
        store.claim("consolidate", "b", now=now + 1, lease=60, attempts=3, repeat=True, cooldown=10)
        is None
    )
    assert store.claim(
        "consolidate", "b", now=now + 11, lease=60, attempts=3, repeat=True, cooldown=10
    )


def test_daily_model_budget_survives_restart(store, home):
    now = time.time()
    store.reserve_model_call(now=now, daily_limit=1)
    another = Store(home / "state.sqlite")
    try:
        with pytest.raises(ModelError):
            another.reserve_model_call(now=now, daily_limit=1)
        another.reserve_model_call(now=now + 86400, daily_limit=1)
    finally:
        another.close()

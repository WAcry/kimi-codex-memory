"""Keep the first public format usable as future releases change implementation."""

import hashlib
import shutil
import sqlite3
from pathlib import Path

from kimi_memory.citations import CitationUse
from kimi_memory.config import load_worker_config
from kimi_memory.files import memory_home, published_root
from kimi_memory.kimi import Source
from kimi_memory.reader import injection_for, load_reader_config, render
from kimi_memory.store import SCHEMA_VERSION, Store

FIXTURE = Path(__file__).parent / "fixtures/release-v1"


def test_published_fixture_has_not_been_rewritten():
    for line in (FIXTURE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        assert hashlib.sha256((FIXTURE / relative).read_bytes()).hexdigest() == expected


def test_first_public_release_data_remains_usable_without_regeneration(home):
    shutil.copytree(FIXTURE / "home", home, dirs_exist_ok=True)
    with sqlite3.connect(home / "state.sqlite") as database:
        database.executescript((FIXTURE / "state.sql").read_text(encoding="utf-8"))
    original = {
        path.relative_to(FIXTURE / "home"): path.read_bytes()
        for path in (FIXTURE / "home").rglob("*")
        if path.is_file()
    }
    assert memory_home() == home
    config = load_worker_config(home)
    assert config.generation.enabled is False and config.generation.max_extractions == 1
    assert load_reader_config(home).max_summary_bytes == 4096
    assert "Synthetic public release fixture" in render(home)
    assert published_root(home).name == "11111111111111111111111111111111"
    assert injection_for("release-existing-context", home) == ""
    assert "Synthetic public release fixture" in injection_for("new-context", home)
    store = Store(home / "state.sqlite")
    try:
        rows = store.selected(cutoff=0, limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["source_id"] == "session_public_baseline"
        assert row["usage_count"] == 1 and row["last_usage"] == 1700000000
        assert row["selected"] == 1
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        source = Source(
            row["source_id"], row["source_updated_at"], 1699999000, row["cwd"], "workspace_example"
        )
        assert store.scan_is_current(source)
        assert not store.extraction_due(source, now=1700001000)
        assert (
            store.record_citations(
                [CitationUse("fixture-event", frozenset({source.id}), 1700000000)], now=1700001000
            )
            == 0
        )
        assert store.selected(cutoff=0, limit=1)[0]["usage_count"] == 1
    finally:
        store.close()
    for relative, contents in original.items():
        assert (home / relative).read_bytes() == contents

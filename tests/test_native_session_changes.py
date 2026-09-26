"""Archive/delete through real Kimi routes in a temporary home; local fake models only."""

import os
from dataclasses import replace

import pytest
from conftest import ScriptModel
from test_native_prompts import configure_model, invoke, isolate_host, scripted_model

from kimi_memory.config import ApiConfig
from kimi_memory.errors import MissingSessionError
from kimi_memory.server import ServerManager
from kimi_memory.store import Store
from kimi_memory.worker import extract_one, run_pass

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIMI_MEMORY_NATIVE_KIMI"), reason="opt-in native session mutation test"
)


def test_native_archive_delete_and_already_captured_snapshot(tmp_path, home, config, monkeypatch):
    binary = isolate_host(tmp_path, monkeypatch)
    host = tmp_path / "kimi"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with scripted_model() as (origin, _):
        configure_model(host, origin)
        invoke(binary, workspace, "Synthetic task one.")
        invoke(binary, workspace, "Synthetic task two.")
        manager = ServerManager(ApiConfig(kimi_command=(str(binary),), port=62627), home=host)
        with manager as api:
            sources = api.sessions(since=0, limit=10)
            assert len(sources) == 2
            source = sources[-1]
            snapshot = api.transcript(source)
            assert snapshot.items
            response = api.http.request(
                api.origin + f"/api/v1/sessions/{source.id}:archive",
                headers={"Authorization": "Bearer " + manager.token()},
                body={},
            )
            assert response["code"] == 0 and api.source(source.id).archived
            assert any(s.id == source.id and s.archived for s in api.sessions(since=0, limit=10))
            response = api.http.request(
                api.origin + f"/api/v1/sessions/{source.id}:delete",
                headers={"Authorization": "Bearer " + manager.token()},
                body={},
            )
            assert response["code"] == 0
            with pytest.raises(MissingSessionError):
                api.source(source.id)
            with pytest.raises(MissingSessionError):
                api.transcript(source)
            result = run_pass(
                home,
                replace(config, generation=replace(config.generation, min_idle_hours=0)),
                [{"event": "SessionEnd", "session_id": source.id}],
                client=api,
                models=(ScriptModel(), ScriptModel()),
            )
            assert result["state"] == "ready" and result["missing_sessions"] == 1
            assert result["extractions"] == ["extracted"]
        # This was acquired before deletion: model work needs no live source or server.
        store = Store(home / "state.sqlite")
        try:
            assert extract_one(snapshot, store, config, ScriptModel(), home) == "extracted"
            assert store.has_summary(source.id)
        finally:
            store.close()

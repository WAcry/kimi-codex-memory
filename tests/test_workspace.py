import time
from dataclasses import replace

import pytest
from conftest import ScriptModel, seed_published, valid_summary
from test_store import save

from kimi_memory.errors import LeaseLostError, ModelError, ResyncRequired
from kimi_memory.files import atomic_write, published_root
from kimi_memory.reader import render
from kimi_memory.store import Store
from kimi_memory.worker import phase_two
from kimi_memory.workspace import (
    Workspace,
    current_generation,
    recover_publication,
    validate_summary,
)


@pytest.fixture
def store(home):
    store = Store(home / "state.sqlite")
    yield store
    store.close()


def test_successful_publication_is_readable_and_repeated_inputs_skip_models(
    home, config, source, store
):
    save(store, source)
    model = ScriptModel()
    generation = phase_two(store, config, home, model)
    assert current_generation(home).name == generation
    assert "rollout_summaries/" in render(home)
    assert len(list((published_root(home) / "rollout_summaries").glob("*.md"))) == 1
    calls = len(model.calls)
    assert phase_two(store, config, home, model) == "unchanged"
    assert len(model.calls) == calls
    assert store.selected(cutoff=0, limit=1)[0]["selected"] == 1


def test_failed_consolidation_never_changes_published_memory(home, config, source, store):
    old = seed_published(home)
    before = render(home)
    save(store, source)
    with pytest.raises(ModelError):
        phase_two(store, config, home, ScriptModel(fail=True))
    assert render(home) == before
    assert current_generation(home) == old
    assert list((home / "_staging").iterdir()) == []


def test_source_deletion_appears_in_diff_and_removes_file_after_success(
    home, config, source, store
):
    save(store, source)
    phase_two(store, config, home, ScriptModel())
    filename = next((published_root(home) / "rollout_summaries").glob("*.md")).name
    save(store, source, "empty-version", summary="")
    workspace = Workspace(home, [], config.generation)
    try:
        workspace.prepare()
        diff = (workspace.path / "phase2_workspace_diff.md").read_text()
        assert "deleted file" in diff and filename in diff
    finally:
        workspace.close()
    phase_two(store, config, home, ScriptModel())
    assert list((published_root(home) / "rollout_summaries").glob("*.md")) == []
    assert filename not in render(home)


def test_tool_sandbox_rejects_paths_and_requires_diff_first(home, config, source, store, tmp_path):
    save(store, source)
    workspace = Workspace(home, store.selected(cutoff=0, limit=10), config.generation)
    try:
        workspace.prepare()
        with pytest.raises(ModelError):
            workspace.execute("write_summary", {"content": valid_summary()})
        with pytest.raises(ModelError):
            workspace.execute("read_file", {"path": "memory_summary.md"})
        workspace.execute("read_file", {"path": "phase2_workspace_diff.md"})
        for path in ("../worker.toml", "/etc/passwd", ".git/config", "kimi-session:example"):
            with pytest.raises(ModelError):
                workspace.execute("read_file", {"path": path})
        with pytest.raises(ModelError):
            workspace.execute("exec", {"command": "anything"})
    finally:
        workspace.close()


def test_notes_survive_resource_expiration_including_a_notes_subfolder_named_resources(
    home, config
):
    root = home / "memories_v2"
    note = root / "extensions/ad_hoc/notes/resources/2000-01-01-old-note.md"
    resource = root / "extensions/screen/resources/2000-01-01T00-00-00-old.md"
    atomic_write(note, "explicit user request that must stay")
    atomic_write(resource, "expired resource")
    workspace = Workspace(home, [], config.generation)
    try:
        assert note.relative_to(root).as_posix() in workspace.files
        assert resource.relative_to(root).as_posix() not in workspace.files
        assert workspace.expired_resources[0][0] == resource
        assert resource.exists()
    finally:
        workspace.close()


def test_notes_edit_changes_consolidation_inputs(home, config, store):
    note = home / "memories_v2/extensions/ad_hoc/notes/correction.md"
    atomic_write(note, "Please remember task scope A")
    first = phase_two(store, config, home, ScriptModel())
    atomic_write(note, "Correction: scope B supersedes scope A")
    workspace = Workspace(home, [], config.generation)
    try:
        workspace.prepare()
        diff = (workspace.path / "phase2_workspace_diff.md").read_text()
        assert "+Correction: scope B" in diff and "-Please remember task scope A" in diff
    finally:
        workspace.close()
    second = phase_two(store, config, home, ScriptModel())
    assert first != second and note.exists()
    assert not (current_generation(home) / "phase2_workspace_diff.md").exists()
    assert not (current_generation(home) / ".git").exists()


def test_symlink_notes_are_never_followed(home, config, tmp_path):
    outside = tmp_path / "outside.md"
    atomic_write(outside, "not authorized as a memory source")
    (home / "memories_v2/extensions/ad_hoc/notes/link.md").symlink_to(outside)
    workspace = Workspace(home, [], config.generation)
    try:
        assert "extensions/ad_hoc/notes/link.md" not in workspace.files
        assert workspace.issues.count == 1
        assert all("not authorized" not in text for text in workspace.files.values())
    finally:
        workspace.close()


@pytest.mark.parametrize(
    "summary",
    [
        "v2\nwrong format",
        valid_summary() + "\n## User Profile",
        valid_summary("rollout_summaries/nonexistent.md"),
        "v1\n" + "x" * 11000,
    ],
)
def test_invalid_summary_cannot_be_published(summary):
    with pytest.raises(ModelError):
        validate_summary(summary, 10000, set())


def test_new_events_during_model_work_prevent_source_removal(home, config, source, store):
    save(store, source)
    phase_two(store, config, home, ScriptModel())
    old = current_generation(home)
    save(store, source, "no-longer-useful", summary="")
    with pytest.raises(ResyncRequired):
        phase_two(store, config, home, ScriptModel(), can_publish=lambda: False)
    assert current_generation(home) == old


def test_recovery_finishes_sqlite_after_pointer_was_published(
    home, config, source, store, monkeypatch
):
    save(store, source)
    original = store.finalize_publication

    def fail_after_switch(*_, **__):
        raise RuntimeError("simulated crash after pointer publication")

    monkeypatch.setattr(store, "finalize_publication", fail_after_switch)
    with pytest.raises(RuntimeError):
        phase_two(store, config, home, ScriptModel())
    assert "rollout_summaries/" in render(home)
    assert store.pending_publication() is not None
    monkeypatch.setattr(store, "finalize_publication", original)
    recover_publication(home, store)
    assert store.pending_publication() is None
    assert store.selected(cutoff=0, limit=1)[0]["selected"] == 1


def test_recovery_abandons_an_intent_without_switching_files(home, store):
    before = seed_published(home)
    owner = store.claim("consolidate", "new", now=time.time(), lease=60, attempts=3, repeat=True)
    store.publication_intent(
        "not-published", owner, {"input_hash": "new", "sources": []}, time.time()
    )
    recover_publication(home, store)
    assert current_generation(home) == before
    assert store.pending_publication() is None


def test_lost_owner_cannot_publish(home, config, source, store):
    old = seed_published(home)
    save(store, source)
    workspace = Workspace(home, store.selected(cutoff=0, limit=10), config.generation)
    try:
        workspace.prepare()
        workspace.execute("read_file", {"path": "phase2_workspace_diff.md"})
        workspace.execute("write_summary", {"content": valid_summary()})
        with pytest.raises(LeaseLostError):
            workspace.publish(store, "expired-owner")
        assert current_generation(home) == old
    finally:
        workspace.close()


def test_old_generation_cleanup_preserves_recent_and_current(home, config, source, store):
    save(store, source)
    config = replace(config, generation=replace(config.generation, retained_generations=2))
    for i in range(4):
        atomic_write(
            home / "memories_v2/extensions/ad_hoc/notes/note.md", f"User note revision {i}"
        )
        phase_two(store, config, home, ScriptModel())
    assert len(list((home / "_generations").iterdir())) == 2
    assert current_generation(home).is_dir()
    assert "rollout_summaries/" in render(home)

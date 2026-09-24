import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import seed_published

from kimi_memory.errors import ConfigurationError
from kimi_memory.files import atomic_write, file_lock, published_root
from kimi_memory.hooks import handle, wake
from kimi_memory.platform import kimi_command, process_alive, remove_owned_tree, worker_command
from kimi_memory.reader import render
from kimi_memory.store import Store
from kimi_memory.worker import run


def test_failed_worker_keeps_queue_and_success_acknowledges_it(home):
    seed_published(home)
    handle({"hook_event_name": "Stop", "session_id": "example"}, home, spawn=False)
    atomic_write(home / "worker.toml", "broken [")
    pending = list((home / "queue").glob("*.json"))
    assert pending and run(home)["state"] == "paused"
    assert all(path.exists() for path in pending)
    assert "Previously published" in render(home)
    atomic_write(home / "worker.toml", "[generation]\nenabled = false\n")
    assert run(home)["state"] == "disabled"
    assert not list((home / "queue").glob("*.json"))


def test_quiet_backoff_does_not_spawn_or_block_injection(home, monkeypatch):
    import time

    from kimi_memory.files import write_json

    seed_published(home)
    monkeypatch.delenv("KIMI_MEMORY_NO_AUTOSTART")
    write_json(home / "worker-status.json", {"state": "paused", "retry_at": time.time() + 3600})

    def forbidden(*_, **__):
        raise AssertionError("A quiet backoff must not spawn")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    wake(home)
    assert (
        "Previously published"
        in handle({"hook_event_name": "UserPromptSubmit", "session_id": "s"}, home)["message"]
    )


def test_database_v1_upgrade_backs_up_committed_wal_and_preserves_data(home):
    path = home / "state.sqlite"
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE sentinel (value TEXT)")
    db.execute("INSERT INTO sentinel VALUES ('must-survive')")
    db.execute("PRAGMA user_version=1")
    db.commit()
    store = Store(path)
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert store.db.execute("SELECT value FROM sentinel").fetchone()[0] == "must-survive"
    backup_path = next((home / "backups").glob("*.sqlite"))
    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("SELECT value FROM sentinel").fetchone()[0] == "must-survive"
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
    store.close()
    db.close()
    again = Store(path)
    again.close()
    assert len(list((home / "backups").glob("*.sqlite"))) == 1


def test_future_database_version_is_not_downgraded_and_reader_survives(home):
    seed_published(home)
    with sqlite3.connect(home / "state.sqlite") as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ConfigurationError):
        Store(home / "state.sqlite")
    assert "Previously published" in render(home)
    with sqlite3.connect(home / "state.sqlite") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


def test_publication_and_reading_never_need_symlink_privileges(home, monkeypatch):
    def forbidden(*_, **__):
        raise AssertionError("No Windows Developer Mode requirement")

    monkeypatch.setattr(Path, "symlink_to", forbidden)
    directory = seed_published(home)
    assert published_root(home) == directory
    assert "Previously published" in render(home)
    assert not any(path.is_symlink() for path in home.rglob("*"))


def test_native_lock_excludes_a_separate_process(home):
    path = home / "cross-process.lock"
    code = """
import sys
from pathlib import Path
from kimi_memory.files import file_lock
from kimi_memory.errors import BusyError
try:
    with file_lock(Path(sys.argv[1])): pass
except BusyError:
    raise SystemExit(23)
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    with file_lock(path):
        result = subprocess.run([sys.executable, "-c", code, str(path)], env=env, timeout=10)
        assert result.returncode == 23
    result = subprocess.run([sys.executable, "-c", code, str(path)], env=env, timeout=10)
    assert result.returncode == 0


def test_frozen_worker_restarts_own_binary_not_python_module(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert worker_command() == [sys.executable, "worker", "--drain"]


def test_process_liveness_does_not_signal_or_terminate_current_process():
    assert process_alive(os.getpid())
    assert not process_alive(0)


def test_owned_git_cleanup_handles_windows_readonly_objects(tmp_path):
    import stat

    root = tmp_path / "owned-staging"
    obj = root / ".git/objects/aa/synthetic"
    atomic_write(obj, "test-owned Git object")
    obj.chmod(stat.S_IREAD)
    remove_owned_tree(root)
    assert not root.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows npm shim contract")
def test_windows_npm_shim_is_resolved_without_shell_injection(tmp_path):
    shim = tmp_path / "npm folder/kimi.cmd"
    atomic_write(shim, "@echo off\n")
    entry = shim.parent / "node_modules/@moonshot-ai/kimi-code/dist/main.mjs"
    atomic_write(entry, "// synthetic entry")
    node = shim.parent / "node.exe"
    node.touch()
    assert kimi_command((str(shim),)) == [str(node), str(entry)]

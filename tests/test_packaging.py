import hashlib
import importlib.util
import json
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

from kimi_memory import __version__
from kimi_memory.cli import add_note, initialize
from kimi_memory.files import atomic_write

ROOT = Path(__file__).resolve().parents[1]


def test_platform_archive_preserves_unix_launcher_mode_even_on_windows(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "archive_plugin", ROOT / "scripts/archive-plugin.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "package"
    launcher = root / "plugin/run-hook"
    atomic_write(launcher, "#!/bin/sh\nexit 0\n", mode=0o600)
    archive = tmp_path / "plugin-win32-x64.zip"
    module.pack(root, archive)
    with zipfile.ZipFile(archive) as zipped:
        entry = zipped.getinfo("plugin/run-hook")
        assert (entry.external_attr >> 16) & 0o777 == 0o755
        assert zipped.read(entry) == b"#!/bin/sh\nexit 0\n"


def test_upstream_prompts_and_notices_are_byte_identical_to_the_pinned_manifest():
    manifest = tomllib.loads((ROOT / "upstream.toml").read_text())
    assert len(manifest["files"]) == 7
    for entry in manifest["files"]:
        assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    for entry in manifest["kimi_files"]:
        assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]


def test_native_distribution_versions_match_and_no_pypi_workflow():
    plugin = json.loads((ROOT / "kimi.plugin.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "marketplace.json").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert (
        plugin["version"] == catalog["plugins"][0]["version"] == package["version"] == __version__
    )
    assert plugin["name"] == catalog["plugins"][0]["id"] == "kimi-codex-memory"
    assert package["private"] is True


def test_runtime_package_has_no_external_dependencies_and_pinned_entry():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == []
    assert project["version"] == __version__
    assert project["scripts"]["kimi-memory"] == "kimi_memory.cli:main"


def test_initialize_preserves_existing_configuration(home):
    atomic_write(home / "reader.toml", "enabled = false\n")
    atomic_write(home / "worker.toml", "[generation]\nenabled = false\n")
    before = [(home / name).read_bytes() for name in ("reader.toml", "worker.toml")]
    initialize(home)
    assert before == [(home / name).read_bytes() for name in ("reader.toml", "worker.toml")]


def test_explicit_note_is_local_and_does_not_need_generation_config(home):
    atomic_write(home / "worker.toml", "invalid TOML [")
    note = add_note(home, "forget", "Remove the obsolete preference", wake_worker=False)
    assert "Operation: forget" in note.read_text()
    assert "Remove the obsolete preference" in note.read_text()
    assert not (home / "state.sqlite").exists()


def test_cli_offline_commands_run_from_outside_the_repository(tmp_path):
    command = [sys.executable, str(ROOT / "bin/kimi-memory")]
    result = subprocess.run(
        [*command, "--version"], cwd=tmp_path, capture_output=True, text=True, timeout=5
    )
    assert result.stdout.strip() == __version__
    result = subprocess.run(
        [*command, "status"], cwd=tmp_path, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["generation"]["state"] == "not_run"

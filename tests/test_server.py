import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import NativeApi, ScriptModel, serve

from kimi_memory.citations import collect_citations
from kimi_memory.config import ApiConfig, GenerationConfig, WorkerConfig
from kimi_memory.errors import TransportError
from kimi_memory.evidence import normalize
from kimi_memory.files import atomic_write, published_root, write_json
from kimi_memory.kimi import Source
from kimi_memory.platform import process_options
from kimi_memory.server import ServerManager, live_instances
from kimi_memory.worker import run_pass


def test_borrowed_server_is_not_stopped(tmp_path):
    with serve(NativeApi([])) as (origin, _):
        manager = ServerManager(ApiConfig(server_url=origin), home=tmp_path / "kimi")
        with manager as api:
            assert api.server_version == "2.1.0" and manager.borrowed
            assert manager.child is None
        assert manager._connect(origin).sessions(since=0, limit=10) == []


def test_discovery_validates_registered_identity(tmp_path):
    home = tmp_path / "kimi"
    with serve(NativeApi([])) as (origin, _):
        write_json(
            home / "server/instances/test.json",
            {
                "pid": os.getpid(),
                "host": "127.0.0.1",
                "port": int(origin.rsplit(":", 1)[1]),
                "server_id": "registry-identity-not-the-api-identity",
                "host_version": "2.1.0",
                "started_at": 1,
            },
        )
        manager = ServerManager(ApiConfig(auto_start=False), home=home)
        with manager as api:
            assert api.server_id == "test-native"
        assert (home / "server/instances/test.json").exists()


def test_new_server_uses_the_same_contract_without_legacy_fallback(tmp_path):
    with serve(NativeApi([], version="9.9.9")) as (origin, _):
        manager = ServerManager(ApiConfig(server_url=origin), home=tmp_path / "kimi")
        api = manager.connect()
        assert api.sessions(since=0, limit=10) == []
        assert manager.child is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission-bit assertion")
def test_unsafe_server_token_permissions_are_not_weakened(tmp_path):
    home = tmp_path / "kimi"
    token = home / "server.token"
    token.chmod(0o644)
    manager = ServerManager(ApiConfig(), home=home)
    with pytest.raises(TransportError, match="permissions"):
        manager.token()
    assert token.stat().st_mode & 0o777 == 0o644


def test_helper_startup_failure_is_bounded_and_child_is_reaped(tmp_path):
    script = tmp_path / "fake-kimi.py"
    atomic_write(
        script,
        "import sys\nif len(sys.argv) == 2: print(str(2.1) + chr(46) + str(0))\nelse: raise SystemExit(23)\n",
    )
    manager = ServerManager(
        ApiConfig(kimi_command=(sys.executable, str(script)), startup_timeout_seconds=2),
        home=tmp_path / "kimi",
    )
    with pytest.raises(TransportError, match="exited"):
        manager.connect()
    assert manager.child is None


def test_new_installed_version_is_tried_before_contract_failure(tmp_path):
    script = tmp_path / "fake-kimi.py"
    marker = tmp_path / "started"
    atomic_write(
        script,
        f"import sys\nfrom pathlib import Path\nif len(sys.argv) == 2: print(str(9.9) + chr(46) + str(9))\nelse: Path({str(marker)!r}).touch()\n",
    )
    manager = ServerManager(
        ApiConfig(kimi_command=(sys.executable, str(script))), home=tmp_path / "kimi"
    )
    with pytest.raises(TransportError):
        manager.connect()
    assert marker.exists()


def test_owner_close_only_reaps_its_actual_child(tmp_path):
    manager = ServerManager(ApiConfig(), home=tmp_path / "kimi")
    options = dict(
        **process_options(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    owned = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **options)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **options)
    try:
        manager.child = owned
        manager.close()
        assert owned.poll() is not None
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
        if owned.poll() is None:
            owned.terminate()
            owned.wait(timeout=5)


@pytest.mark.skipif(
    not os.environ.get("KIMI_MEMORY_NATIVE_KIMI"), reason="opt-in installed Kimi integration"
)
def test_installed_native_kimi_helper_and_borrowed_peer(tmp_path, monkeypatch):
    binary = Path(os.environ["KIMI_MEMORY_NATIVE_KIMI"]).resolve()
    assert binary.is_absolute() and binary.is_file()
    home = tmp_path / "kimi"
    for key in list(os.environ):
        if any(word in key.upper() for word in ("API_KEY", "ACCESS_TOKEN", "REFRESH_TOKEN")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("HOME", str(tmp_path))
    atomic_write(home / "config.toml", "telemetry = false\n")
    config = ApiConfig(kimi_command=(str(binary),), port=61627, startup_timeout_seconds=60)
    owner = ServerManager(config, home=home)
    try:
        api = owner.connect()
        assert api.server_version == "2.1.0"
        assert api.sessions(since=0, limit=10) == []
        pid = owner.child.pid
        peer = ServerManager(config, home=home)
        with peer as borrowed:
            assert borrowed.server_id == api.server_id and peer.child is None
        assert owner.child.poll() is None
        assert any(instance["pid"] == pid for instance in live_instances(home))
    finally:
        owner.close()
    assert live_instances(home) == []


@pytest.mark.skipif(
    not os.environ.get("KIMI_MEMORY_NATIVE_KIMI"), reason="opt-in installed Kimi integration"
)
def test_native_cold_transcript_and_memory_pipeline(tmp_path, monkeypatch, home):
    binary = Path(os.environ["KIMI_MEMORY_NATIVE_KIMI"]).resolve()
    native_home = tmp_path / "kimi"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for key in list(os.environ):
        if any(word in key.upper() for word in ("API_KEY", "ACCESS_TOKEN", "REFRESH_TOKEN")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("HOME", str(tmp_path))
    atomic_write(native_home / "config.toml", "telemetry = false\n")
    api_config = ApiConfig(kimi_command=(str(binary),), port=61627, startup_timeout_seconds=60)
    creator = ServerManager(api_config, home=native_home)
    with creator as api:
        envelope = api.http.request(
            api.origin + "/api/v1/sessions",
            headers={"Authorization": "Bearer " + creator.token()},
            body={"metadata": {"cwd": str(workspace)}, "title": "Synthetic memory integration"},
        )
        assert envelope["code"] == 0
        source = Source.from_json(envelope["data"])
    now_ms = int(time.time() * 1000) - 36_000_000

    def message(role, text, **extra):
        return {"role": role, "content": [{"type": "text", "text": text}], "toolCalls": [], **extra}

    citation = "<oai-mem-citation>\n<rollout_ids>\nsession_existing_source\n</rollout_ids>\n</oai-mem-citation>"
    records = [
        {"type": "metadata", "protocol_version": "1.5", "created_at": now_ms},
        {
            "type": "turn.prompt",
            "turnId": 0,
            "promptId": "prompt-native",
            "origin": {"kind": "user"},
            "time": now_ms,
        },
        {
            "type": "context.append_message",
            "message": message(
                "user", "Preserve exact task scope", id="prompt-native", origin={"kind": "user"}
            ),
            "time": now_ms,
        },
        {
            "type": "context.append_message",
            "message": message(
                "assistant",
                "Which scope?",
                toolCalls=[
                    {
                        "type": "function",
                        "id": "question-native",
                        "name": "AskUserQuestion",
                        "arguments": "{}",
                    }
                ],
            ),
            "time": now_ms + 1000,
        },
        {
            "type": "interaction.request",
            "id": "q-native",
            "kind": "question",
            "toolCallId": "question-native",
            "request": {
                "toolCallId": "question-native",
                "questions": [{"question": "Scope?", "options": [{"label": "Only v2"}]}],
            },
            "time": now_ms + 2000,
        },
        {
            "type": "interaction.resolved",
            "id": "q-native",
            "response": {"answers": {"Scope?": "Only v2"}},
            "time": now_ms + 3000,
        },
        {
            "type": "context.append_message",
            "message": message("tool", "The user chose Only v2", toolCallId="question-native"),
            "time": now_ms + 4000,
        },
        {
            "type": "context.append_message",
            "message": message("assistant", "Implemented and verified.\n" + citation),
            "time": now_ms + 5000,
        },
        {"type": "turn.ended", "turnId": 0, "reason": "completed", "time": now_ms + 6000},
    ]
    wire = native_home / "sessions" / source.workspace_id / source.id / "agents/main/wire.jsonl"
    atomic_write(wire, "".join(json.dumps(record) + "\n" for record in records))
    reader = ServerManager(api_config, home=native_home)
    with reader as api:
        sources = api.sessions(since=0, limit=10)
        assert len(sources) == 1
        transcript = api.transcript(sources[0])
        evidence = normalize(transcript)
        assert any(item.tier == "Human" and "Only v2" in item.text for item in evidence)
        assert any("Implemented and verified" in item.text for item in evidence)
        citations = collect_citations(transcript)
        assert len(citations) == 1
        assert citations[0].source_ids == frozenset({"session_existing_source"})
        config = WorkerConfig(
            api=api_config,
            generation=GenerationConfig(min_idle_hours=0, consolidation_cooldown_seconds=0),
        )
        result = run_pass(home, config, [], client=api, models=(ScriptModel(), ScriptModel()))
        assert result["state"] == "ready" and result["extractions"] == ["extracted"]
    assert (published_root(home) / "memory_summary.md").is_file()
    assert live_instances(native_home) == []

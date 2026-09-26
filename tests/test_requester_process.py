"""Safe diagnostics for native process failures, without provider text or thoughts."""

import subprocess

import pytest

from kimi_memory.config import ModelConfig
from kimi_memory.errors import ModelError
from kimi_memory.model_config import resolve_connection
from kimi_memory.requester import native_request


@pytest.mark.parametrize(
    "case, code",
    [
        ("exit", "model_process_exit"),
        ("limit", "model_response_limit"),
        ("timeout", "model_timeout"),
        ("protocol", "model_requester_protocol"),
    ],
)
def test_native_process_error_is_categorized_without_logging_output(
    tmp_path, monkeypatch, case, code
):
    config = ModelConfig(base_url="http://127.0.0.1:1", model="synthetic", max_response_bytes=1024)
    connection = resolve_connection(config, home=tmp_path)

    def run(*args, **kwargs):
        if case == "timeout":
            raise subprocess.TimeoutExpired("synthetic", 1, output="private thought")
        return subprocess.CompletedProcess(
            "synthetic",
            7 if case == "exit" else 0,
            stdout="private thought" * (1000 if case == "limit" else 1),
        )

    monkeypatch.setattr("kimi_memory.requester.subprocess.run", run)
    with pytest.raises(ModelError) as error:
        native_request(
            connection,
            [{"role": "user", "content": "synthetic"}],
            None,
            json_mode=True,
            config=config,
        )
    assert error.value.code == code
    assert "private thought" not in str(error.value)
    if case == "exit":
        assert "code 7" in str(error.value)

import json
from dataclasses import replace

import pytest
from conftest import NativeApi, ScriptModel, serve

from kimi_memory.config import ModelConfig, load_worker_config
from kimi_memory.errors import ConfigurationError, ModelError
from kimi_memory.files import atomic_write, published_root
from kimi_memory.kimi import KimiClient
from kimi_memory.models import CallBudget, Model, resolve_connection
from kimi_memory.store import Store
from kimi_memory.worker import run_pass


def test_openai_request_and_strict_completion_reason():
    def respond(method, path, body, headers):
        assert method == "POST" and path == "/v1/chat/completions"
        assert headers["Authorization"] == "Bearer test-model-token-never-log"
        assert "test-model-token-never-log" not in json.dumps(body)
        assert body["response_format"] == {"type": "json_object"}
        return 200, {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}

    with serve(respond) as (origin, _):
        model = Model(
            ModelConfig(
                api_key_env="KIMI_MEMORY_API_KEY", base_url=origin + "/v1", model="test-model"
            )
        )
        result = model.complete(
            [
                {
                    "role": "user",
                    "content": "A copied key test-model-token-never-log must be removed",
                }
            ],
            json_mode=True,
        )
    assert result["role"] == "assistant" and result["content"] == '{"ok":true}'
    assert result["_native_message"]["content"] == [{"type": "text", "text": '{"ok":true}'}]


@pytest.mark.parametrize("finish", ["length", "content_filter", None])
def test_truncated_or_filtered_model_output_is_not_accepted(finish):
    with serve(
        lambda *_: (
            200,
            {"choices": [{"finish_reason": finish, "message": {"content": "partial"}}]},
        )
    ) as (origin, _):
        model = Model(
            ModelConfig(
                api_key_env="KIMI_MEMORY_API_KEY", base_url=origin + "/v1", model="test-model"
            )
        )
        with pytest.raises(ModelError):
            model.complete([{"role": "user", "content": "task"}])


def test_anthropic_tool_turn_preserves_native_blocks():
    calls = 0

    def respond(method, path, body, headers):
        nonlocal calls
        calls += 1
        assert path == "/v1/messages"
        assert headers["X-Api-Key"] == "test-model-token-never-log"
        if calls == 1:
            return 200, {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "transient reasoning",
                        "signature": "signature",
                    },
                    {"type": "tool_use", "id": "tool-1", "name": "list_files", "input": {}},
                ],
            }
        assert body["messages"][-2]["content"][0]["type"] == "thinking"
        assert body["messages"][-1]["content"][0]["type"] == "tool_result"
        return 200, {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Done"}]}

    with serve(respond) as (origin, _):
        model = Model(
            ModelConfig(
                api_key_env="KIMI_MEMORY_API_KEY",
                protocol="anthropic",
                base_url=origin,
                model="test-model",
            )
        )
        messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "task"}]
        response = model.complete(
            messages,
            tools=[
                {
                    "function": {
                        "name": "list_files",
                        "description": "list",
                        "parameters": {"type": "object"},
                    }
                }
            ],
        )
        messages += [response, {"role": "tool", "tool_call_id": "tool-1", "content": "[]"}]
        assert model.complete(messages)["content"] == "Done"


def test_kimi_provider_selection_does_not_expose_or_mutate_credentials(tmp_path, monkeypatch):
    kimi = tmp_path / "kimi"
    monkeypatch.delenv("KIMI_MEMORY_API_KEY")
    atomic_write(
        kimi / "config.toml",
        '[providers.example]\nbase_url = "https://example.test/v1"\ndefault_model = "example-model"\napi_key_env = "MY_TEST_PROVIDER_KEY"\n',
    )
    monkeypatch.setenv("MY_TEST_PROVIDER_KEY", "provider-private-key")
    config = ModelConfig(kimi_provider="example", model="example-model")
    result = resolve_connection(config, home=kimi)
    assert (result.base_url, result.model, result.key) == (
        "https://example.test/v1",
        "example-model",
        "provider-private-key",
    )
    assert "provider-private-key" not in (kimi / "config.toml").read_text()


def test_subscription_config_uses_native_oauth_ref_without_reading_tokens(tmp_path):
    kimi = tmp_path / "kimi"
    atomic_write(
        kimi / "config.toml",
        """
default_model = "kimi/model"
[models."kimi/model"]
provider = "managed:kimi-code"
model = "wire-model"
protocol = "openai_responses"
[providers."managed:kimi-code"]
type = "kimi"
[providers."managed:kimi-code".oauth]
storage = "file"
key = "oauth/kimi-code"
""",
    )
    result = resolve_connection(ModelConfig(), home=kimi)
    assert result.oauth_ref["key"] == "oauth/kimi-code"
    assert result.model == "wire-model" and result.protocol == "openai_responses"
    assert not (kimi / "credentials").exists()


def test_daily_and_per_run_model_call_limits(home):
    store = Store(home / "state.sqlite")
    try:
        budget = CallBudget(store, daily=10, per_run=1)
        budget.reserve()
        with pytest.raises(ModelError, match="Per-run"):
            budget.reserve()
        assert budget.calls == 1
    finally:
        store.close()


def test_model_input_budget_prevents_network_request():
    with serve(lambda *_: (200, {})) as (origin, requests):
        model = Model(
            ModelConfig(api_key_env="KIMI_MEMORY_API_KEY", base_url=origin, model="model"),
            input_limit=1,
        )
        with pytest.raises(ModelError, match="input budget"):
            model.complete([{"role": "user", "content": "long text"}])
    assert requests == []


def test_full_pipeline_through_native_and_model_http(home, config, transcript):
    scripted = ScriptModel()

    def provider(method, path, body, headers):
        result = scripted.complete(
            body["messages"], tools=body.get("tools"), json_mode="response_format" in body
        )
        return 200, {
            "choices": [
                {
                    "finish_reason": "tool_calls" if result.get("tool_calls") else "stop",
                    "message": result,
                }
            ]
        }

    with serve(NativeApi([transcript])) as (api_url, _), serve(provider) as (model_url, requests):
        model_cfg = ModelConfig(
            api_key_env="KIMI_MEMORY_API_KEY", base_url=model_url + "/v1", model="integration-model"
        )
        config = replace(config, extraction=model_cfg, consolidation=model_cfg)
        api = KimiClient(api_url, lambda: "test-native-token-never-log", config.api)
        api.handshake()
        result = run_pass(home, config, [], client=api)
    assert result["state"] == "ready"
    assert result["model_calls"] == len(requests) == 6
    assert (published_root(home) / "memory_summary.md").is_file()


def test_partial_consolidation_config_inherits_extraction(home):
    atomic_write(
        home / "worker.toml",
        '[extraction]\nbase_url = "https://example.test/v1"\nmodel = "fast"\n[consolidation]\nmodel = "careful"\n',
    )
    config = load_worker_config(home)
    assert config.consolidation.base_url == config.extraction.base_url
    assert config.consolidation.model == "careful"


@pytest.mark.parametrize(
    "text",
    [
        "[api]\npage_size = 0",
        "[api]\nport = 58627",
        '[api]\nkimi_command = ["kimi"]',
        "[generation]\nretention_days = nan",
        "[generation]\nmax_extractions = false",
        "[generation]\nheartbeat_seconds = 4000",
        "[generation]\nunknown_flag = true",
        '[extraction]\nprotocol = "unsupported"',
    ],
)
def test_invalid_configuration_is_rejected(home, text):
    atomic_write(home / "worker.toml", text)
    with pytest.raises(ConfigurationError):
        load_worker_config(home)

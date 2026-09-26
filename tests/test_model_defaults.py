import pytest
from conftest import NativeApi, ScriptModel, serve

from kimi_memory.config import ModelConfig, load_worker_config
from kimi_memory.errors import ConfigurationError, ModelError
from kimi_memory.files import atomic_write, published_root
from kimi_memory.kimi import KimiClient
from kimi_memory.model_config import resolve_connection
from kimi_memory.models import Model
from kimi_memory.worker import run_pass


def setup_model(home, protocol="openai", context=1_000_000, override=400_000):
    atomic_write(
        home / "config.toml",
        f'''
default_model = "example/selected"
[providers.example]
type = "{protocol}"
base_url = "https://example.test/v1"
api_key_env = "EXAMPLE_PROVIDER_KEY"
[providers.example.custom_headers]
"X-Example" = "custom"
[models."example/selected"]
provider = "example"
model = "wire-model"
max_context_size = {context}
[models."example/selected".overrides]
max_context_size = {override}
''',
    )


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "openai_responses"])
def test_default_alias_protocol_key_and_configured_context(tmp_path, monkeypatch, protocol):
    home = tmp_path / "kimi"
    setup_model(home, protocol)
    monkeypatch.setenv("EXAMPLE_PROVIDER_KEY", "synthetic-provider-key")
    result = resolve_connection(ModelConfig(), home=home)
    assert (result.alias, result.model, result.protocol) == (
        "example/selected",
        "wire-model",
        protocol,
    )
    assert result.key == "synthetic-provider-key"
    assert result.context_window == 400_000
    assert result.input_budget() == 280_000
    assert result.headers["X-Example"] == "custom"


def test_effective_camel_case_records_and_max_input_limit(tmp_path, monkeypatch):
    setup_model(tmp_path / "kimi")
    monkeypatch.setenv("EXAMPLE_PROVIDER_KEY", "synthetic-provider-key")
    config = {
        "default_model": "example/selected",
        "models": {
            "example/selected": {
                "provider": "example",
                "name": "resolved-wire",
                "maxContextSize": 1_000_000,
                "overrides": {"maxContextSize": 400_000, "maxInputSize": 300_000},
            }
        },
    }
    result = resolve_connection(ModelConfig(), home=tmp_path / "kimi", effective=config)
    assert result.model == "resolved-wire"
    assert result.input_budget() == 210_000


def test_unknown_context_uses_256k_fallback_not_a_model_name_guess(tmp_path):
    config = ModelConfig(base_url="https://example.test/v1", model="new-model")
    result = resolve_connection(config, home=tmp_path)
    assert result.context_window == 256_000 and result.input_budget() == 179_200


def test_kimi_output_limit_is_inherited_without_a_memory_override(tmp_path, monkeypatch):
    setup_model(tmp_path)
    monkeypatch.setenv("EXAMPLE_PROVIDER_KEY", "synthetic-provider-key")
    effective = {"models": {"example/selected": {"maxOutputSize": 32000}}}
    connection = resolve_connection(ModelConfig(), home=tmp_path, effective=effective)
    assert connection.max_output == 32000
    assert connection.input_budget() == 280000
    connection = resolve_connection(
        ModelConfig(max_output_tokens=1024), home=tmp_path, effective=effective
    )
    assert connection.max_output == 1024


def test_explicit_provider_uses_its_default_not_another_global_alias(tmp_path, monkeypatch):
    setup_model(tmp_path)
    monkeypatch.setenv("EXAMPLE_PROVIDER_KEY", "synthetic-provider-key")
    effective = {
        "default_model": "unrelated/alias",
        "providers": {"example": {"default_model": "example/selected"}},
    }
    connection = resolve_connection(
        ModelConfig(kimi_provider="example"), home=tmp_path, effective=effective
    )
    assert connection.alias == "example/selected"


def test_openai_reasoning_model_uses_native_max_completion_tokens(tmp_path):
    with serve(
        lambda *_: (200, {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})
    ) as (origin, requests):
        model = Model(ModelConfig(base_url=origin, model="gpt-5-example"), home=tmp_path)
        model.complete([{"role": "user", "content": "synthetic request"}])
        assert requests[0][2]["max_completion_tokens"] == 8192
        assert "max_tokens" not in requests[0][2]


def test_memory_override_cannot_inflate_user_configured_window(tmp_path, monkeypatch):
    setup_model(tmp_path / "kimi")
    monkeypatch.setenv("EXAMPLE_PROVIDER_KEY", "synthetic-provider-key")
    result = resolve_connection(ModelConfig(context_window=1_000_000), home=tmp_path / "kimi")
    assert result.context_window == 400_000
    result = resolve_connection(ModelConfig(context_window=100_000), home=tmp_path / "kimi")
    assert result.input_budget() == 70_000


def test_model_alias_typo_does_not_choose_an_unrelated_provider(tmp_path):
    with pytest.raises(ConfigurationError):
        resolve_connection(ModelConfig(model="unknown-alias"), home=tmp_path)


def test_gemini_is_not_silently_treated_as_openai(tmp_path, monkeypatch):
    setup_model(tmp_path / "kimi", protocol="google-genai")
    monkeypatch.setenv("EXAMPLE_PROVIDER_KEY", "synthetic-provider-key")
    with pytest.raises(ConfigurationError, match="Gemini"):
        resolve_connection(ModelConfig(), home=tmp_path / "kimi")


def test_hook_environment_model_is_resolved(tmp_path, monkeypatch):
    for key, value in {
        "KIMI_MODEL_NAME": "env-model",
        "KIMI_MODEL_PROVIDER_TYPE": "openai_responses",
        "KIMI_MODEL_BASE_URL": "https://example.test/v1",
        "KIMI_MODEL_API_KEY": "synthetic-env-key",
        "KIMI_MODEL_MAX_CONTEXT_SIZE": "400000",
    }.items():
        monkeypatch.setenv(key, value)
    result = resolve_connection(ModelConfig(), home=tmp_path)
    assert (result.model, result.protocol, result.key) == (
        "env-model",
        "openai_responses",
        "synthetic-env-key",
    )
    assert result.input_budget() == 280_000


def test_unknown_api_configuration_is_reported(home):
    atomic_write(home / "worker.toml", "[api]\nunknown_option = true\n")
    with pytest.raises(ConfigurationError, match="Unknown ApiConfig option"):
        load_worker_config(home)


def test_zero_configuration_full_responses_pipeline(
    home, config, transcript, tmp_path, monkeypatch
):
    scripted = ScriptModel()

    def provider(method, path, body, headers):
        assert path == "/v1/responses" and body["store"] is False
        assert headers["Authorization"] == "Bearer synthetic-inherited-key"
        assert body["model"] == "actual-wire-name"
        messages = [{"role": "system", "content": body["instructions"]}]
        for item in body["input"]:
            if item.get("type") == "function_call_output":
                content = item["output"]
                if isinstance(content, list):
                    content = "".join(part.get("text", "") for part in content)
                messages.append({"role": "tool", "content": content})
            elif item.get("role") in {"user", "assistant"} and isinstance(item.get("content"), str):
                messages.append(item)
        result = scripted.complete(messages, tools=body.get("tools"))
        if result.get("tool_calls"):
            output = [
                {
                    "type": "function_call",
                    "call_id": call["id"],
                    "name": call["function"]["name"],
                    "arguments": call["function"]["arguments"],
                }
                for call in result["tool_calls"]
            ]
        else:
            output = [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": result["content"]}],
                }
            ]
        return 200, {"status": "completed", "output": output}

    with serve(provider) as (origin, requests):
        atomic_write(
            tmp_path / "kimi/config.toml",
            f'''
default_model = "provider/default"
[providers.provider]
type = "openai_responses"
base_url = "{origin}/v1"
api_key_env = "INHERITED_TEST_KEY"
[models."provider/default"]
provider = "provider"
model = "actual-wire-name"
max_context_size = 400000
''',
        )
        monkeypatch.setenv("INHERITED_TEST_KEY", "synthetic-inherited-key")
        with serve(NativeApi([transcript], version="2.1.7")) as (api_url, _):
            api = KimiClient(api_url, lambda: "test-native-token-never-log", config.api)
            api.handshake()
            result = run_pass(home, config, [], client=api)
    assert result["state"] == "ready" and result["model_calls"] == len(requests) == 6
    assert config.extraction == ModelConfig()
    assert (published_root(home) / "memory_summary.md").is_file()


def test_subscription_401_refreshes_once_and_quota_failure_does_not_retry(tmp_path, monkeypatch):
    atomic_write(
        tmp_path / "kimi/config.toml",
        """
default_model = "kimi/default"
[providers."managed:kimi-code"]
type = "kimi"
[providers."managed:kimi-code".oauth]
storage = "file"
key = "oauth/kimi-code"
[models."kimi/default"]
provider = "managed:kimi-code"
model = "wire"
""",
    )
    attempts = []

    def auth(*_, force=False, **__):
        attempts.append(force)
        return {"access_token": "refreshed" if force else "initial", "headers": {}}

    monkeypatch.setattr("kimi_memory.models.native_auth", auth)

    def respond(_method, _path, _body, headers):
        if headers["Authorization"] == "Bearer initial":
            return 401, {"error": "synthetic rejection"}
        return 200, {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}

    with serve(respond) as (origin, requests):
        model = Model(ModelConfig(base_url=origin), home=tmp_path / "kimi")
        assert model.complete([{"role": "user", "content": "task"}])["content"] == "ok"
        assert len(requests) == 2 and attempts == [False, True]
    with serve(lambda *_: (429, {"error": "quota"})) as (origin, requests):
        model = Model(ModelConfig(base_url=origin), home=tmp_path / "kimi")
        with pytest.raises(ModelError):
            model.complete([{"role": "user", "content": "task"}])
        assert len(requests) == 1

import json

import pytest
from conftest import serve

from kimi_memory.config import ModelConfig
from kimi_memory.errors import ExtractionOutputError, ModelError
from kimi_memory.extraction_output import parse_extraction
from kimi_memory.files import atomic_write
from kimi_memory.models import Model

OUTPUT = {"rollout_summary": "Verified task evidence", "rollout_slug": "example"}
FENCE = chr(96) * 3


@pytest.mark.parametrize(
    "wrapper", ["{}", "\ufeff{}", FENCE + "json\n{}\n" + FENCE, FENCE + "\n{}\n" + FENCE]
)
def test_extraction_accepts_only_full_final_json_or_a_single_whole_fence(wrapper):
    assert parse_extraction({"content": wrapper.format(json.dumps(OUTPUT))}) == OUTPUT


@pytest.mark.parametrize(
    "content",
    [
        "",
        None,
        [],
        "{}",
        "[]",
        "prefix " + json.dumps(OUTPUT),
        "<think>" + json.dumps(OUTPUT) + "</think>",
        json.dumps(OUTPUT) + " another object {}",
        '{"rollout_summary":3,"rollout_slug":"x"}',
    ],
)
def test_extraction_never_salvages_a_thought_or_arbitrary_substring(content):
    with pytest.raises(ExtractionOutputError):
        parse_extraction({"content": content, "reasoning_content": json.dumps(OUTPUT)})


@pytest.mark.parametrize("protocol", ["openai", "openai_responses", "anthropic"])
def test_native_json_extraction_on_three_protocols(tmp_path, protocol):
    def callback(method, path, body, headers):
        assert body["stream"] is True
        if protocol == "openai":
            assert body["response_format"] == {"type": "json_object"}
            return 200, {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(OUTPUT)}}]
            }
        if protocol == "openai_responses":
            assert body["store"] is False and body["text"]["format"]["type"] == "json_object"
            return 200, {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(OUTPUT)}],
                    }
                ],
            }
        assert body["output_config"]["format"]["type"] == "json_schema"
        return 200, {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(OUTPUT)}],
        }

    with serve(callback) as (origin, requests):
        model = Model(
            ModelConfig(base_url=origin + "/v1", model="model", protocol=protocol), home=tmp_path
        )
        assert (
            parse_extraction(
                model.complete([{"role": "user", "content": "Return JSON."}], json_mode=True)
            )
            == OUTPUT
        )
    assert len(requests) == 1


def test_native_thinking_metadata_and_custom_channel_are_preserved_not_promoted(tmp_path):
    def callback(method, path, body, headers):
        assert body["reasoning_effort"] == "high"
        if len(body["messages"]) > 1:
            assistant = next(m for m in body["messages"] if m["role"] == "assistant")
            assert assistant["reasoning"] == "transient private planning"
        return 200, {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(OUTPUT),
                        "reasoning": "transient private planning",
                    },
                }
            ]
        }

    with serve(callback) as (origin, requests):
        atomic_write(
            tmp_path / "config.toml",
            f'''
default_model = "provider/default"
[providers.provider]
type = "openai"
base_url = "{origin}/v1"
[models."provider/default"]
model = "arbitrary-provider-model"
provider = "provider"
capabilities = ["always_thinking", "tool_use"]
reasoning_key = "reasoning"
support_efforts = ["low", "high"]
default_effort = "high"
''',
        )
        model = Model(ModelConfig(), home=tmp_path)
        messages = [{"role": "user", "content": "Return JSON."}]
        response = model.complete(messages, json_mode=True)
        assert parse_extraction(response) == OUTPUT
        assert any(part["type"] == "think" for part in response["_native_message"]["content"])
        assert "private planning" not in response["content"]
        model.complete([*messages, response, {"role": "user", "content": "Continue."}])
    assert len(requests) == 2


def test_thinking_only_reply_is_not_an_empty_memory(tmp_path):
    with serve(
        lambda *_: (
            200,
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "", "reasoning_content": json.dumps(OUTPUT)},
                    }
                ]
            },
        )
    ) as (origin, _):
        model = Model(ModelConfig(base_url=origin, model="model"), home=tmp_path)
        with pytest.raises(ModelError) as error:
            model.complete([{"role": "user", "content": "task"}], json_mode=True)
        assert error.value.code == "model_empty_response"


def test_native_stdin_preserves_large_multibyte_input(tmp_path):
    content = "真实输入 🐈\n" * 12000

    def callback(method, path, body, headers):
        assert body["messages"][0]["content"] == content
        return 200, {"choices": [{"finish_reason": "stop", "message": {"content": "完整"}}]}

    with serve(callback) as (origin, _):
        model = Model(ModelConfig(base_url=origin, model="model"), home=tmp_path)
        assert model.complete([{"role": "user", "content": content}])["content"] == "完整"


def test_responses_preserves_encrypted_reasoning_and_tool_result_with_native_codec(tmp_path):
    output = [
        {"type": "reasoning", "id": "rs1", "summary": [], "encrypted_content": "opaque-signature"},
        {
            "type": "function_call",
            "id": "fc1",
            "call_id": "call1",
            "name": "read_file",
            "arguments": "{}",
        },
    ]

    def callback(method, path, body, headers):
        assert body["store"] is False and "previous_response_id" not in body
        if any(item.get("type") == "function_call_output" for item in body["input"]):
            assert any(
                item.get("encrypted_content") == "opaque-signature" for item in body["input"]
            )
            return 200, {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Done"}],
                    }
                ],
            }
        return 200, {"status": "completed", "output": output}

    with serve(callback) as (origin, _):
        model = Model(
            ModelConfig(base_url=origin, model="test", protocol="openai_responses"), home=tmp_path
        )
        messages = [{"role": "user", "content": "task"}]
        response = model.complete(messages)
        assert response["tool_calls"][0]["id"] == "call1"
        assert (
            model.complete(
                [
                    *messages,
                    response,
                    {"role": "tool", "tool_call_id": "call1", "content": "evidence"},
                ]
            )["content"]
            == "Done"
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "incomplete", "output": []},
        {"status": "failed", "output": []},
        {"status": "completed", "output": [{"type": "computer_call"}]},
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "refusal", "refusal": "no"}],
                }
            ],
        },
    ],
)
def test_unusable_responses_still_fail_closed_for_this_source_only(tmp_path, payload):
    with serve(lambda *_: (200, payload)) as (origin, _):
        model = Model(
            ModelConfig(base_url=origin, model="model", protocol="openai_responses"), home=tmp_path
        )
        with pytest.raises(ModelError):
            model.complete([{"role": "user", "content": "task"}])


def test_response_cap_and_redirects_do_not_disclose_provider_output(tmp_path):
    with serve(
        lambda *_: (
            200,
            {"choices": [{"finish_reason": "stop", "message": {"content": "private" * 3000}}]},
        )
    ) as (origin, _):
        model = Model(
            ModelConfig(base_url=origin, model="model", max_response_bytes=1024), home=tmp_path
        )
        with pytest.raises(ModelError) as error:
            model.complete([{"role": "user", "content": "task"}])
        assert "private" not in str(error.value)
    with serve(lambda *_: (302, {}, {"Location": "https://should-not-contact.invalid/"})) as (
        origin,
        requests,
    ):
        model = Model(ModelConfig(base_url=origin, model="model"), home=tmp_path)
        with pytest.raises(ModelError):
            model.complete([{"role": "user", "content": "task"}])
        assert len(requests) == 1

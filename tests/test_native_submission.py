"""Actual bundled Kimi requesters + local streaming servers, with no paid calls."""

import json

import pytest
from conftest import serve
from provider_stream import stream_response
from test_extraction_fallback import prose, tool
from test_tool_submission import OUTPUT, submitted

from kimi_memory.config import ModelConfig
from kimi_memory.errors import ExtractionOutputError, ModelError
from kimi_memory.extraction_output import EXTRACTION_TOOL, extraction_tool, parse_extraction
from kimi_memory.models import Model

PROTOCOLS = ["openai", "openai_responses", "anthropic"]


def wire_result(protocol, result=None, *, finish=None):
    result = result or submitted()
    calls = result.get("tool_calls", [])
    if protocol == "openai":
        return {
            "choices": [
                {
                    "finish_reason": finish or ("tool_calls" if calls else "stop"),
                    "message": {
                        **result,
                        "reasoning_content": json.dumps(
                            {"rollout_summary": "NOT A RESULT", "rollout_slug": "wrong"}
                        ),
                    },
                }
            ]
        }
    if protocol == "openai_responses":
        return {
            "status": finish or "completed",
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs1",
                    "summary": [],
                    "encrypted_content": "opaque-test-reasoning",
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": result["content"]}],
                },
                *[
                    {
                        "type": "function_call",
                        "id": f"fc{i}",
                        "call_id": call["id"],
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"],
                    }
                    for i, call in enumerate(calls)
                ],
            ],
        }
    return {
        "stop_reason": finish or ("tool_use" if calls else "end_turn"),
        "content": [
            {
                "type": "thinking",
                "thinking": "private thought, not a result",
                "signature": "opaque-test-signature",
            },
            {"type": "text", "text": result["content"]},
            *[
                {
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["function"]["name"],
                    "input": json.loads(call["function"]["arguments"]),
                }
                for call in calls
            ],
        ],
    }


def invoke(model):
    return model.complete(
        [{"role": "user", "content": "Submit the session extraction using the result tool."}],
        tools=[extraction_tool()],
        output_tool=EXTRACTION_TOOL,
    )


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("json_mode", [True, False])
def test_extraction_wire_uses_only_tools_not_response_json_and_preserves_channels(
    tmp_path, protocol, json_mode, monkeypatch
):
    monkeypatch.setenv("OPENAI_LOG", "debug")
    monkeypatch.setenv("ANTHROPIC_LOG", "debug")

    def provider(method, path, body, headers):
        assert body["stream"] is True
        assert len(body["tools"]) == 1
        assert "response_format" not in body and "output_config" not in body
        assert "format" not in body.get("text", {})
        tool = body["tools"][0].get("function", body["tools"][0])
        assert tool["name"] == EXTRACTION_TOOL and tool.get("strict") is not True
        schema = tool.get("parameters", tool.get("input_schema"))
        assert schema == extraction_tool()["function"]["parameters"]
        assert body["tool_choice"] == ({"type": "auto"} if protocol == "anthropic" else "auto")
        assert "parallel_tool_calls" not in body
        if protocol == "openai_responses":
            assert body["store"] is False and "previous_response_id" not in body
        return 200, wire_result(protocol)

    with serve(provider) as (origin, requests):
        model = Model(
            ModelConfig(
                base_url=origin + "/v1",
                model="thinking-compatible-gateway",
                protocol=protocol,
                json_mode=json_mode,
            ),
            home=tmp_path,
        )
        response = invoke(model)
        assert parse_extraction(response) == OUTPUT
        assert any(p["type"] == "think" for p in response["_native_message"]["content"])
        assert len(requests) == 1


@pytest.mark.parametrize("protocol", ["openai", "openai_responses"])
def test_official_openai_policy_reaches_the_final_wire_not_just_a_python_tool_dict(
    tmp_path, protocol, monkeypatch
):
    # Route the already unit-tested official-endpoint policy to a local server only.
    monkeypatch.setattr(
        "kimi_memory.requester.output_tool_policy", lambda _, name: {"name": name, "strict": True}
    )

    def provider(method, path, body, headers):
        tool = body["tools"][0].get("function", body["tools"][0])
        assert tool["strict"] is True
        assert body["tool_choice"] == "required" and body["parallel_tool_calls"] is False
        assert "response_format" not in body and "format" not in body.get("text", {})
        return 200, wire_result(protocol)

    with serve(provider) as (origin, requests):
        model = Model(
            ModelConfig(base_url=origin + "/v1", model="test-only", protocol=protocol),
            home=tmp_path,
        )
        assert parse_extraction(invoke(model)) == OUTPUT
    assert len(requests) == 1


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("failure", ["text_only", "wrong_name", "wrong_schema", "multiple_calls"])
def test_tool_output_falls_back_to_final_text_only_when_no_valid_tool_exists(
    tmp_path, protocol, failure
):
    result = submitted(content=json.dumps(OUTPUT))
    if failure == "text_only":
        result["tool_calls"] = []
    elif failure == "wrong_name":
        result["tool_calls"][0]["function"]["name"] = "shell"
    elif failure == "wrong_schema":
        result["tool_calls"][0]["function"]["arguments"] = (
            '{"rollout_summary": false, "rollout_slug": "bad"}'
        )
    else:
        result["tool_calls"].append({**result["tool_calls"][0], "id": "second-call"})
    with serve(lambda *_: (200, wire_result(protocol, result))) as (origin, requests):
        model = Model(
            ModelConfig(base_url=origin, model="test-only", protocol=protocol), home=tmp_path
        )
        assert parse_extraction(invoke(model)) == OUTPUT
    assert len(requests) == 1


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_native_multiple_submissions_select_last_valid_tool_not_larger_final_json(
    tmp_path, protocol
):
    corrected = {"rollout_summary": "Corrected completed task", "rollout_slug": "corrected"}
    final = {"rollout_summary": "IGNORED LARGE PROSE " * 400, "rollout_slug": "ignored"}
    result = prose(
        json.dumps(final),
        [tool({}), tool(), tool(corrected), tool({"rollout_summary": False, "rollout_slug": "x"})],
    )
    for index, call in enumerate(result["tool_calls"]):
        call["id"] = f"call-{index}"
    with serve(lambda *_: (200, wire_result(protocol, result))) as (origin, requests):
        model = Model(ModelConfig(base_url=origin, model="local", protocol=protocol), home=tmp_path)
        response = invoke(model)
        assert len(response["tool_calls"]) == 4
        assert parse_extraction(response) == corrected
    assert len(requests) == 1


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("has_invalid_calls", [False, True])
def test_native_final_fallback_selects_largest_valid_object_across_text_blocks(
    tmp_path, protocol, has_invalid_calls
):
    largest = {"rollout_summary": "Meaningful final evidence 猫 " * 50, "rollout_slug": "largest"}
    huge_invalid = {"rollout_summary": "not valid " * 1000, "raw_memory": "wrong schema"}
    fence = chr(96) * 3
    text = (
        "Brief example: "
        + json.dumps(OUTPUT)
        + "\n"
        + json.dumps(huge_invalid)
        + "\n"
        + fence
        + "json\n"
        + json.dumps(largest, ensure_ascii=False)
        + "\n"
        + fence
        + "\n"
        + json.dumps(OUTPUT)
    )
    result = prose(text, [tool({})] if has_invalid_calls else [])
    with serve(lambda *_: (200, wire_result(protocol, result))) as (origin, requests):
        model = Model(ModelConfig(base_url=origin, model="local", protocol=protocol), home=tmp_path)
        response = invoke(model)
        assert parse_extraction(response) == largest
        assert any(p["type"] == "think" for p in response["_native_message"]["content"])
    assert len(requests) == 1


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize(
    "final",
    [
        "No result",
        '{"rollout_summary": false, "rollout_slug": "x"}',
        '{"rollout_summary":"x","rollout_summary":"y","rollout_slug":"x"}',
    ],
)
def test_invalid_tool_and_final_text_still_fail_without_promoting_reasoning(
    tmp_path, protocol, final
):
    result = prose(final, [tool({})])
    with serve(lambda *_: (200, wire_result(protocol, result))) as (origin, requests):
        model = Model(ModelConfig(base_url=origin, model="local", protocol=protocol), home=tmp_path)
        response = invoke(model)
        with pytest.raises(ExtractionOutputError):
            parse_extraction(response)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "protocol,finish",
    [
        ("openai", "length"),
        ("openai", "content_filter"),
        ("openai_responses", "incomplete"),
        ("anthropic", "max_tokens"),
    ],
)
@pytest.mark.parametrize("has_tool", [False, True])
def test_even_complete_looking_arguments_are_rejected_when_response_is_incomplete(
    tmp_path, protocol, finish, has_tool
):
    result = submitted() if has_tool else prose(json.dumps(OUTPUT))
    with serve(lambda *_: (200, wire_result(protocol, result, finish=finish))) as (
        origin,
        requests,
    ):
        model = Model(
            ModelConfig(base_url=origin, model="test-only", protocol=protocol), home=tmp_path
        )
        with pytest.raises(ModelError):
            invoke(model)
    assert len(requests) == 1


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("has_tool", [False, True])
def test_complete_tool_arguments_without_a_response_completion_event_are_not_accepted(
    tmp_path, protocol, has_tool
):
    def provider(method, path, body, headers):
        result = submitted() if has_tool else prose(json.dumps(OUTPUT))
        raw = stream_response(path, wire_result(protocol, result))
        blocks = []
        for block in raw.split(b"\n\n"):
            data = next(
                (line[6:] for line in block.splitlines() if line.startswith(b"data: ")), None
            )
            if data is None or data == b"[DONE]":
                continue
            item = json.loads(data)
            if item.get("type") in {"response.completed", "message_delta", "message_stop"}:
                continue
            if any(choice.get("finish_reason") is not None for choice in item.get("choices", [])):
                continue
            blocks.append(block)
        return 200, b"\n\n".join(blocks) + b"\n\n"

    with serve(provider) as (origin, requests):
        model = Model(
            ModelConfig(base_url=origin, model="test-only", protocol=protocol), home=tmp_path
        )
        with pytest.raises(ModelError):
            invoke(model)
    assert len(requests) == 1

"""Terminal extraction contract: one tool, no text/reasoning fallback, no tool execution."""

import json
from dataclasses import replace

import pytest
from conftest import NativeApi, ScriptModel
from test_session_isolation import pair, run_with
from test_store import save

from kimi_memory.config import ModelConfig
from kimi_memory.errors import ExtractionOutputError, ModelError
from kimi_memory.extraction_output import EXTRACTION_TOOL, extraction_tool, parse_extraction
from kimi_memory.model_config import resolve_connection
from kimi_memory.requester import native_request, output_tool_policy
from kimi_memory.store import Store
from kimi_memory.worker import extract_one

OUTPUT = {"rollout_summary": "# Task\nValidated history 🐈", "rollout_slug": "task-history"}


def submitted(arguments=None, **extras):
    return {
        "role": "assistant",
        "content": "Incidental commentary is not the extraction result.",
        "tool_calls": [
            {
                "type": "function",
                "id": "result-1",
                "function": {
                    "name": EXTRACTION_TOOL,
                    "arguments": json.dumps(OUTPUT, ensure_ascii=False)
                    if arguments is None
                    else arguments,
                },
            }
        ],
        **extras,
    }


def test_tool_schema_uses_codex_v2_two_required_string_fields():
    tool = extraction_tool()
    assert tool["type"] == "function" and tool["function"]["name"] == EXTRACTION_TOOL
    schema = tool["function"]["parameters"]
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]) == set(OUTPUT)
    assert all(p["type"] == "string" and p["description"] for p in schema["properties"].values())
    assert "ends extraction" in tool["function"]["description"]


def test_valid_tool_arguments_are_the_only_result_even_when_text_and_reasoning_conflict():
    result = submitted(
        content=json.dumps({"rollout_summary": "WRONG TEXT", "rollout_slug": "text"}),
        reasoning_content=json.dumps(
            {"rollout_summary": "WRONG REASONING", "rollout_slug": "reasoning"}
        ),
        _native_message={"content": [{"type": "think", "think": "not source evidence"}]},
    )
    assert parse_extraction(result) == OUTPUT
    assert parse_extraction(submitted(content="")) == OUTPUT
    assert parse_extraction(submitted(json.dumps({"rollout_summary": "", "rollout_slug": ""}))) == {
        "rollout_summary": "",
        "rollout_slug": "",
    }


@pytest.mark.parametrize(
    "calls", [None, [], {}, [None], ["text"], [{}], [submitted()["tool_calls"][0]] * 2]
)
def test_missing_or_multiple_calls_never_fall_back_to_json_text(calls):
    with pytest.raises(ExtractionOutputError):
        parse_extraction(submitted(content=json.dumps(OUTPUT), tool_calls=calls))


@pytest.mark.parametrize(
    "arguments",
    [
        "",
        "{}",
        "[]",
        "null",
        "not JSON",
        "prefix " + json.dumps(OUTPUT),
        json.dumps(OUTPUT) + " {}",
        chr(96) * 3 + "json\n" + json.dumps(OUTPUT) + "\n" + chr(96) * 3,
        '{"rollout_summary": 3, "rollout_slug": "x"}',
        '{"rollout_summary": false, "rollout_slug": "x"}',
        '{"rollout_summary": "x", "rollout_slug": null}',
        '{"rollout_summary": "x", "rollout_slug": "x", "extra": 1}',
        '{"rollout_summary": "x", "rollout_summary": "y", "rollout_slug": "x"}',
        '{"rollout_summary": NaN, "rollout_slug": "x"}',
        '{"rollout_summary": Infinity, "rollout_slug": "x"}',
        json.dumps({"rollout_summary": chr(0xD800), "rollout_slug": "x"}),
        {},
        None,
        1,
    ],
)
def test_invalid_tool_arguments_are_rejected_without_salvaging_or_coercion(arguments):
    response = submitted()
    response["tool_calls"][0]["function"]["arguments"] = arguments
    with pytest.raises(ExtractionOutputError) as error:
        parse_extraction(response)
    assert "WRONG" not in str(error.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("type", "custom"),
        ("function", None),
        ("function", {"name": "shell", "arguments": json.dumps(OUTPUT)}),
    ],
)
def test_only_the_declared_function_can_submit(field, value):
    response = submitted()
    response["tool_calls"][0][field] = value
    with pytest.raises(ExtractionOutputError):
        parse_extraction(response)


@pytest.mark.parametrize("role", ["tool", "user", "system", None])
def test_tool_or_user_messages_are_not_a_model_submission(role):
    with pytest.raises(ExtractionOutputError):
        parse_extraction(submitted(role=role))


@pytest.mark.parametrize(
    "url,protocol,strict",
    [
        ("https://api.openai.com/v1", "openai", True),
        ("https://api.openai.com:443/v1", "openai_responses", True),
        ("https://api.openai.com:8443/v1", "openai", False),
        ("https://api.openai.com.evil.test/v1", "openai", False),
        ("https://gateway.example/api.openai.com", "openai_responses", False),
        ("https://api.moonshot.ai/v1", "openai", False),
        ("https://api.anthropic.com", "anthropic", False),
        ("http://127.0.0.1:1234/v1", "openai", False),
    ],
)
def test_strict_support_is_not_guessed_from_a_model_name(tmp_path, url, protocol, strict):
    connection = resolve_connection(
        ModelConfig(base_url=url, protocol=protocol, model="gpt-5"), home=tmp_path
    )
    assert output_tool_policy(connection, EXTRACTION_TOOL) == {
        "name": EXTRACTION_TOOL,
        "strict": strict,
    }


def test_wrong_tool_declaration_is_rejected_before_network(tmp_path, monkeypatch):
    config = ModelConfig(base_url="http://127.0.0.1:1", model="synthetic")
    connection = resolve_connection(config, home=tmp_path)

    def forbidden(*_, **__):
        raise AssertionError("No process/network for an invalid request contract")

    monkeypatch.setattr("kimi_memory.requester.subprocess.run", forbidden)
    for tools, json_mode in [
        (None, False),
        ([extraction_tool()] * 2, False),
        ([extraction_tool()], True),
    ]:
        with pytest.raises(ModelError):
            native_request(
                connection,
                [],
                tools,
                json_mode=json_mode,
                config=config,
                output_tool=EXTRACTION_TOOL,
            )


def test_tool_schema_is_included_in_request_budget(tmp_path):
    from conftest import serve

    from kimi_memory.models import Model

    with serve(lambda *_: (200, {})) as (origin, requests):
        model = Model(
            ModelConfig(base_url=origin, model="synthetic"), input_limit=64, home=tmp_path
        )
        with pytest.raises(ModelError, match="input budget"):
            model.complete(
                [{"role": "user", "content": "task"}],
                tools=[extraction_tool()],
                output_tool=EXTRACTION_TOOL,
            )
    assert not requests


@pytest.mark.parametrize("json_mode", [True, False])
def test_extraction_uses_one_terminal_tool_without_json_mode_or_confirmation(
    home, config, transcript, json_mode
):
    class Checked(ScriptModel):
        def complete(self, messages, **kwargs):
            assert kwargs == {"tools": [extraction_tool()], "output_tool": EXTRACTION_TOOL}
            assert len(messages) == 2 and all(m["role"] != "tool" for m in messages)
            return super().complete(messages, **kwargs)

    model = Checked()
    store = Store(home / "state.sqlite")
    try:
        config = replace(config, extraction=replace(config.extraction, json_mode=json_mode))
        assert extract_one(transcript, store, config, model, home) == "extracted"
        assert len(model.calls) == 1
        assert store.has_summary(transcript.source.id)
    finally:
        store.close()


def test_plain_text_json_fails_one_source_without_erasing_previous_memory_or_blocking_peers(
    home, config, transcript
):
    bad, good = pair(transcript)
    store = Store(home / "state.sqlite")
    save(store, bad.source, "previous version", summary="previous version")
    store.close()

    class BadText(ScriptModel):
        def complete(self, messages, **kwargs):
            if "session_id: session_bad" in messages[-1]["content"]:
                return {"role": "assistant", "content": json.dumps(OUTPUT)}
            return super().complete(messages, **kwargs)

    result, _ = run_with(home, config, NativeApi([bad, good]), models=(BadText(), ScriptModel()))
    assert result["state"] == "degraded"
    assert sorted(result["extractions"]) == ["extracted", "failed"]
    store = Store(home / "state.sqlite")
    try:
        assert store.has_summary(bad.source.id) and store.has_summary(good.source.id)
        row = store.db.execute(
            "SELECT summary FROM summaries WHERE source_id=?", (bad.source.id,)
        ).fetchone()
        assert row[0] == "previous version"
    finally:
        store.close()

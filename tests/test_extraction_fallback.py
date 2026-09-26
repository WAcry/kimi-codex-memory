"""Last valid tool, then largest complete schema-valid final-text object, never thoughts."""

import json
import random

import pytest
from conftest import NativeApi, ScriptModel
from test_session_isolation import pair, run_with
from test_store import save
from test_tool_submission import OUTPUT, submitted

from kimi_memory.errors import ExtractionOutputError, ResyncRequired
from kimi_memory.extraction_output import parse_extraction
from kimi_memory.store import Store
from kimi_memory.worker import extract_one

FENCE = chr(96) * 3


def tool(output=None, *, raw=None, name=None):
    call = submitted(json.dumps(OUTPUT if output is None else output) if raw is None else raw)[
        "tool_calls"
    ][0]
    if name is not None:
        call["function"]["name"] = name
    return call


def prose(content, calls=None, **extras):
    return {"role": "assistant", "content": content, "tool_calls": calls or [], **extras}


def test_last_valid_tool_wins_not_last_call_or_largest_payload():
    earlier = {"rollout_summary": "earlier " * 300, "rollout_slug": "earlier"}
    latest = {"rollout_summary": "Corrected task history", "rollout_slug": "corrected"}
    calls = [
        tool(raw="broken"),
        tool(earlier),
        tool(latest),
        tool(raw="{}"),
        tool(earlier, name="unknown"),
    ]
    assert parse_extraction(prose(json.dumps(earlier), calls)) == latest


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"rollout_summary": 2, "rollout_slug": "x"},
        {"rollout_summary": "x", "rollout_slug": "a" * 257},
        {"rollout_summary": "x", "rollout_slug": "猫" * 86},
        {"rollout_summary": " \n", "rollout_slug": "not-empty"},
        {"rollout_summary": chr(0xD800), "rollout_slug": "bad"},
    ],
)
def test_invalid_later_submission_does_not_hide_earlier_valid_result(invalid):
    assert parse_extraction(prose("", [tool(), tool(invalid)])) == OUTPUT


def test_last_valid_empty_tool_result_beats_earlier_nonempty_result_and_prose():
    empty = {"rollout_summary": "", "rollout_slug": ""}
    assert parse_extraction(prose(json.dumps(OUTPUT), [tool(), tool(empty)])) == empty


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        ("", ""),
        ("\ufeff", ""),
        ("Here is the result:\n", "\nAll done."),
        (FENCE + "json\n", "\n" + FENCE),
        (FENCE + "\x60json\n", "\n" + FENCE + "\x60"),
        ('{"wrapper": [', "]}"),
        ("Invalid initial object {\n", ""),
        ('{"broken": "unfinished literal\n', "\n"),
    ],
)
def test_final_output_json_is_located_without_repairing_or_stripping_wrapper(prefix, suffix):
    assert parse_extraction(prose(prefix + json.dumps(OUTPUT) + suffix)) == OUTPUT


def test_largest_schema_valid_json_not_largest_arbitrary_json_is_selected():
    large = {"rollout_summary": "Substantial history " * 100, "rollout_slug": "large"}
    huge_invalid = {"rollout_summary": "irrelevant " * 500, "raw_memory": "v1 shape"}
    text = "\n".join(map(json.dumps, [OUTPUT, huge_invalid, large, OUTPUT]))
    assert parse_extraction(prose(text, [tool(raw="malformed")])) == large


def test_largest_means_source_utf8_bytes_and_equal_sizes_prefer_later():
    ascii_result = {"rollout_summary": "a" * 20, "rollout_slug": "x"}
    unicode_result = {"rollout_summary": "猫" * 10, "rollout_slug": "x"}
    text = json.dumps(unicode_result, ensure_ascii=False) + json.dumps(ascii_result)
    assert parse_extraction(prose(text)) == unicode_result
    later = {**ascii_result, "rollout_summary": "b" * 20}
    assert parse_extraction(prose(json.dumps(ascii_result) + json.dumps(later))) == later


def test_quotes_escapes_and_json_looking_text_inside_strings_are_not_nested_candidates():
    embedded = json.dumps({"rollout_summary": "fake nested result" * 20, "rollout_slug": "fake"})
    real = {
        "rollout_summary": 'Quotes \\" and braces { } and nested text: ' + embedded,
        "rollout_slug": "real",
    }
    assert parse_extraction(prose(json.dumps(real))) == real
    # A string containing an encoded result is not a result object; do not unescape it.
    with pytest.raises(ExtractionOutputError):
        parse_extraction(prose(json.dumps({"message": embedded})))


@pytest.mark.parametrize(
    "invalid",
    [
        '{"rollout_summary": "x", "rollout_summary": "y", "rollout_slug": "x"}',
        '{"rollout_summary": NaN, "rollout_slug": "x"}',
        '{"rollout_summary": "x", "rollout_slug": Infinity}',
        '{"rollout_summary": "x", "rollout_slug": "x",}',
        '{"rollout_summary": "x", "rollout_slug": "x"',
        json.dumps({"rollout_summary": chr(0xD800), "rollout_slug": "bad"}),
        json.dumps({"rollout_summary": " ", "rollout_slug": "not-empty"}),
        json.dumps({"rollout_summary": "x", "rollout_slug": "x" * 257}),
    ],
)
def test_invalid_final_json_is_never_repaired_or_coerced(invalid):
    with pytest.raises(ExtractionOutputError):
        parse_extraction(prose("prefix\n" + invalid + "\nsuffix"))


@pytest.mark.parametrize("field", ["reasoning", "reasoning_content", "thinking", "_native_message"])
def test_fallback_never_searches_other_response_channels(field):
    thought = json.dumps(OUTPUT)
    value = (
        {"content": [{"type": "think", "think": thought}]}
        if field == "_native_message"
        else thought
    )
    with pytest.raises(ExtractionOutputError) as exc:
        parse_extraction(prose("No final result", [tool(raw="invalid")], **{field: value}))
    assert "Validated history" not in str(exc.value)


def test_valid_tool_bypasses_text_scan_entirely(monkeypatch):
    def forbidden(_):
        raise AssertionError("Never search text after finding a valid tool")

    monkeypatch.setattr("kimi_memory.extraction_output._json_objects", forbidden)
    assert parse_extraction(prose(json.dumps(OUTPUT), [tool()])) == OUTPUT


def test_deep_objects_are_scanned_once_not_reparsed_quadratically(monkeypatch):
    from kimi_memory import extraction_output

    original = extraction_output._decode_candidate
    attempts = []

    def counted(candidate):
        attempts.append(len(candidate))
        return original(candidate)

    monkeypatch.setattr(extraction_output, "_decode_candidate", counted)
    result = json.dumps(OUTPUT)
    text = "{" * 50000 + result + "}" * 50000
    assert parse_extraction(prose(text)) == OUTPUT
    assert attempts == [len(result)]


def test_shared_candidate_validation_skips_bad_tool_and_bad_prose_before_valid_fallback():
    bad = {"rollout_summary": "invalid despite being much longer " * 100, "rollout_slug": "x" * 257}
    assert parse_extraction(prose(json.dumps(bad) + json.dumps(OUTPUT), [tool(bad)])) == OUTPUT


def test_final_json_fallback_and_tools_both_make_progress_in_the_same_batch(
    home, config, transcript
):
    fallback, regular = pair(transcript)
    large = {"rollout_summary": "Final corrected details " * 30, "rollout_slug": "fallback"}

    class Selective(ScriptModel):
        def complete(self, messages, **kwargs):
            if "session_id: session_bad" in messages[-1]["content"]:
                return prose(
                    json.dumps(OUTPUT) + "\n" + FENCE + "json\n" + json.dumps(large) + "\n" + FENCE
                )
            return super().complete(messages, **kwargs)

    result, _ = run_with(
        home, config, NativeApi([fallback, regular]), models=(Selective(), ScriptModel())
    )
    assert result["state"] == "ready" and result["extractions"] == ["extracted", "extracted"]
    store = Store(home / "state.sqlite")
    try:
        row = store.db.execute(
            "SELECT summary FROM summaries WHERE source_id=?", (fallback.source.id,)
        ).fetchone()
        assert row[0] == large["rollout_summary"].strip()
        assert store.has_summary(regular.source.id)
    finally:
        store.close()


def test_many_valid_string_encodings_and_wrappers_keep_the_exact_object():
    randomizer = random.Random(105)
    alphabet = 'abc{}[]"\\\n\t\r🐈中' + chr(0)
    for index in range(200):
        result = {
            "rollout_summary": "Evidence " + "".join(randomizer.choices(alphabet, k=200)),
            "rollout_slug": "test",
        }
        encoded = json.dumps(result, ensure_ascii=index % 2 == 0, indent=2 if index % 3 else None)
        assert parse_extraction(prose('A wrapper {"items": [' + encoded + "]} End.")) == result


@pytest.mark.parametrize("mode", ["final", "multi"])
def test_empty_result_from_either_path_still_obeys_the_removal_guard(
    home, config, transcript, mode
):
    empty = {"rollout_summary": "", "rollout_slug": ""}

    class EmptyResult(ScriptModel):
        def complete(self, *_, **__):
            return prose(json.dumps(empty), [tool(), tool(empty)] if mode == "multi" else [])

    store = Store(home / "state.sqlite")
    try:
        save(store, transcript.source, "old-version", summary="Retained useful history")
        with pytest.raises(ResyncRequired):
            extract_one(transcript, store, config, EmptyResult(), home, allow_removal=lambda: False)
        assert store.has_summary(transcript.source.id)
        assert (
            store.db.execute("SELECT summary FROM summaries").fetchone()[0]
            == "Retained useful history"
        )
    finally:
        store.close()

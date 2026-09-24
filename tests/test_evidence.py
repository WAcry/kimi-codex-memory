import copy
from dataclasses import replace

import pytest
from conftest import turn

from kimi_memory.citations import citation_ids, collect_citations
from kimi_memory.errors import IncompleteHistoryError
from kimi_memory.evidence import Evidence, budget_evidence, estimate_tokens, normalize, redact

BLOCK = "<oai-mem-citation>\n<citation_entries>\nrollout_summaries/example.md:1-3|note=[context]\n</citation_entries>\n<rollout_ids>\nsession_source\nsession_source\n</rollout_ids>\n</oai-mem-citation>"


def test_native_ids_and_duplicate_ids():
    assert citation_ids("Answer\n" + BLOCK) == {"session_source"}


@pytest.mark.parametrize(
    "text",
    ["```xml\n" + BLOCK + "\n```", "~~~\n" + BLOCK + "\n~~~", BLOCK + "\nnot-final", BLOCK[:-15]],
)
def test_examples_and_incomplete_blocks_are_not_usage(text):
    assert citation_ids(text) == set()


def test_forked_history_does_not_create_another_receipt(transcript):
    original = replace(transcript, items=[turn(transcript.source, text=BLOCK)])
    fork = replace(original, source=replace(original.source, id="session_fork"))
    assert collect_citations(original) == collect_citations(fork)


def test_different_completed_outputs_create_distinct_receipts(transcript):
    data = replace(
        transcript, items=[turn(transcript.source, 1, BLOCK), turn(transcript.source, 2, BLOCK)]
    )
    assert len({use.event_key for use in collect_citations(data)}) == 2


def test_only_completed_assistant_text_is_counted(transcript):
    item = turn(transcript.source, text=BLOCK)
    item["steps"][0]["state"] = "running"
    assert collect_citations(replace(transcript, items=[item])) == []
    item["steps"][0]["state"] = "completed"
    item["steps"][0]["frames"][0]["role"] = "user"
    assert collect_citations(replace(transcript, items=[item])) == []


def test_missing_completion_time_does_not_refresh_at_scan_time(transcript):
    item = turn(transcript.source, text=BLOCK)
    del item["endedAt"]
    del item["steps"][0]["endedAt"]
    with pytest.raises(IncompleteHistoryError):
        collect_citations(replace(transcript, items=[item]))


def test_human_question_answers_have_priority_and_are_not_duplicated(transcript):
    item = copy.deepcopy(transcript.items[0])
    item["steps"][0]["frames"].append(
        {
            "kind": "tool",
            "toolCallId": "question-call",
            "name": "AskUserQuestion",
            "state": "done",
            "output": "choice A",
        }
    )
    question = {
        "interactionId": "q",
        "interactionKind": "question",
        "toolCallId": "question-call",
        "state": "answered",
        "request": {"question": "Choose an approach"},
        "response": {"answer": "use the simple approach"},
    }
    data = replace(transcript, items=[item], interactions=[question])
    evidence = normalize(data)
    matches = [e for e in evidence if "use the simple approach" in e.text]
    assert len(matches) == 1 and matches[0].tier == "Human"


def test_injection_thinking_and_memory_tool_output_are_not_human_evidence(transcript):
    item = copy.deepcopy(transcript.items[0])
    item["steps"][0]["frames"] += [
        {"kind": "thinking", "text": "INTERNAL-THINKING"},
        {
            "kind": "tool",
            "toolCallId": "read-memory",
            "name": "Read",
            "state": "done",
            "input": {"path": "/memory/memories_v2/memory_summary.md"},
            "output": "OLD-MEMORY-CONTENT",
        },
    ]
    marker = {"kind": "marker", "marker": "hook_result", "payload": "INJECTED-RULE"}
    result = normalize(replace(transcript, items=[marker, item]), memory_root="/memory/memories_v2")
    combined = str(result)
    assert not any(
        term in combined for term in ("INTERNAL-THINKING", "OLD-MEMORY-CONTENT", "INJECTED-RULE")
    )


def test_budget_keeps_human_before_large_tool_output():
    evidence = [
        Evidence("Human", "Critical user correction: do not deploy.", 0),
        Evidence("Tool", "noisy output " * 10000, 1),
    ]
    result = budget_evidence(evidence, max_tokens=100, max_tool_bytes=1000)
    assert "Critical user correction" in result
    assert estimate_tokens(result) <= 100


def test_budget_preserves_chronological_order():
    evidence = [Evidence("Tool", "older observation", 0), Evidence("Human", "later correction", 1)]
    result = budget_evidence(evidence, max_tokens=200, max_tool_bytes=1000)
    assert result.index("older observation") < result.index("later correction")


def test_kimi_token_estimate_handles_non_ascii():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("中文") == 2


def test_attachment_payloads_are_not_copied_into_text_evidence(transcript):
    item = copy.deepcopy(transcript.items[0])
    item["attachmentIds"] = ["image-one"]
    attachment = {
        "attachmentId": "image-one",
        "mediaType": "image/png",
        "name": "diagram.png",
        "source": {"kind": "url", "url": "data:image/png;base64,PRIVATE-IMAGE-BYTES"},
    }
    text = str(normalize(replace(transcript, items=[item], attachments=[attachment])))
    assert "diagram.png" in text and "PRIVATE-IMAGE-BYTES" not in text


def test_redacts_secrets_but_keeps_safe_routes():
    text = (
        "api_key=super-secret-value Bearer abc.def.token "
        "https://example.test/project?id=42&access_token=hidden-secret "
        "https://example.test/#token=hidden-fragment "
        "-----BEGIN PRIVATE KEY-----private-material-----END PRIVATE KEY-----"
    )
    result = redact(text)
    for secret in (
        "super-secret-value",
        "abc.def.token",
        "hidden-secret",
        "hidden-fragment",
        "private-material",
    ):
        assert secret not in result
    assert "example.test/project" in result and "id=42" in result

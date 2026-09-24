"""One self-contained prompt and one source-identifier format, at the actual read boundary."""

import re

from conftest import ScriptModel, seed_published, valid_summary

from kimi_memory.citations import citation_ids
from kimi_memory.files import atomic_write
from kimi_memory.reader import render
from kimi_memory.store import Store
from kimi_memory.worker import extract_one
from kimi_memory.workspace import PROMPTS, Workspace, summary_file


def test_render_contains_only_one_template_and_unchanged_summary(home):
    body = "Literal historical text: rollout UUIDs and 019c6e27-e55b-73d1-87d8-4e01f1f75043; {{ base_path }}."
    root = seed_published(home, body)
    actual = render(home)
    template = (PROMPTS / "read_path_v2.md").read_text(encoding="utf-8")
    expected = (
        template.replace("{{ base_path }}", root.as_posix())
        .replace("{{ notes_path }}", (home / "memories_v2/extensions/ad_hoc/notes").as_posix())
        .replace("{{ memory_summary }}", valid_summary(body))
    )
    assert actual == expected
    assert actual.endswith("========= MEMORY_SUMMARY ENDS =========\n")
    assert actual.count("Memory citations:") == 1
    assert "Kimi host adaptation" not in actual
    assert body in actual


def test_source_header_and_example_citation_share_the_same_session_identifier():
    template = (PROMPTS / "read_path_v2.md").read_text(encoding="utf-8")
    block = re.search(r"<oai-mem-citation>.*?</oai-mem-citation>", template, re.S).group()
    ids = citation_ids(block)
    assert len(ids) == 1
    identifier = next(iter(ids))
    record = summary_file(
        {
            "source_id": identifier,
            "source_updated_at": 1700000000,
            "cwd": "/workspace/example",
            "summary": "Synthetic evidence",
        }
    )
    assert record.splitlines()[0] == f"session_id: {identifier}"
    assert "thread_id" not in record and "kimi-session:" not in record
    assert "copy the `session_id` value from each cited summary's header" in template


def test_notes_point_to_live_notes_not_the_immutable_generation(home):
    root = seed_published(home)
    actual = render(home)
    assert (home / "memories_v2/extensions/ad_hoc/notes").as_posix() in actual
    assert (root / "extensions/ad_hoc/notes").as_posix() not in actual
    assert "Saving a note\ndoes not mean the generated memory has already changed" in actual


def test_no_summary_prompt_contains_only_explicit_note_guidance(home):
    atomic_write(home / "worker.toml", "[generation]\nenabled = false\n")
    actual = render(home)
    template = (PROMPTS / "notes_only.md").read_text(encoding="utf-8")
    assert actual == template.replace(
        "{{ notes_path }}", (home / "memories_v2/extensions/ad_hoc/notes").as_posix()
    )
    assert "Only when the user explicitly asks" in actual
    assert "Do not edit generated" in actual and "Saving a note" in actual
    for absent in ("MEMORY_SUMMARY", "rollout_summaries", "Grep", "citation", "session_id"):
        assert absent not in actual
    assert not (home / "current.json").exists()
    assert not (home / "state.sqlite").exists()
    seed_published(home)
    full = render(home)
    assert "## Memory notes" not in full
    assert full.count("append a small Markdown note") == 1


def test_actual_extraction_request_uses_real_session_metadata(home, config, transcript):
    model = ScriptModel()
    store = Store(home / "state.sqlite")
    try:
        extract_one(transcript, store, config, model, home)
    finally:
        store.close()
    messages = model.calls[0]
    assert messages[0]["content"] == (PROMPTS / "stage_one_system_v2.md").read_text(
        encoding="utf-8"
    )
    content = messages[1]["content"]
    assert f"session_id: {transcript.source.id}" in content
    assert "normalized from the Kimi session transcript" in content
    assert "{{" not in content and "kimi-session:" not in content


def test_consolidation_declares_its_actual_tools_and_one_session_header(home, config):
    workspace = Workspace(home, [], config.generation)
    try:
        prompt = workspace.prompt()
        assert "session_id=<exact session_id from the supplied summary's header>" in prompt
        assert "thread" not in prompt and "{{" not in prompt
        assert prompt.count("Use `write_summary`") == 1
        assert "10,000 UTF-8 bytes" in prompt
        assert prompt.endswith("summary if no supported content remains.\n")
    finally:
        workspace.close()

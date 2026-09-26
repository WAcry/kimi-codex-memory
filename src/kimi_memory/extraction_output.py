"""The sole terminal extraction tool; never mine assistant prose or reasoning for JSON."""

import json

from .errors import ExtractionOutputError

EXTRACTION_TOOL = "submit_memory_extraction"


def extraction_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": EXTRACTION_TOOL,
            "description": (
                "Submit the final memory extraction for the supplied session. "
                "Call exactly once after reviewing the evidence. Provide a faithful, "
                "self-contained Markdown task history and a descriptive filesystem-safe slug; "
                "use empty strings for both fields when nothing merits retention. "
                "This submits the result and ends extraction; it does not read files, "
                "execute commands or require a follow-up answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rollout_summary": {
                        "type": "string",
                        "description": "Faithful Markdown task history based only on the supplied evidence.",
                    },
                    "rollout_slug": {
                        "type": "string",
                        "description": "Descriptive filesystem-safe slug, or empty when the summary is empty.",
                    },
                },
                "required": ["rollout_summary", "rollout_slug"],
                "additionalProperties": False,
            },
        },
    }


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate tool argument key")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError("Non-JSON constant")


def parse_extraction(response: dict) -> dict[str, str]:
    calls = response.get("tool_calls") if isinstance(response, dict) else None
    if (
        not isinstance(response, dict)
        or response.get("role") != "assistant"
        or not isinstance(calls, list)
        or len(calls) != 1
    ):
        raise ExtractionOutputError("Extraction must submit exactly one result tool call")
    call = calls[0]
    function = call.get("function") if isinstance(call, dict) else None
    if (
        not isinstance(call, dict)
        or call.get("type") != "function"
        or not isinstance(function, dict)
        or function.get("name") != EXTRACTION_TOOL
        or not isinstance(function.get("arguments"), str)
    ):
        raise ExtractionOutputError("Extraction did not call the declared submission tool")
    try:
        output = json.loads(
            function["arguments"], object_pairs_hook=_object, parse_constant=_invalid_constant
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise ExtractionOutputError(
            "Extraction tool arguments are not a complete JSON object"
        ) from exc
    if (
        not isinstance(output, dict)
        or set(output) != {"rollout_summary", "rollout_slug"}
        or any(not isinstance(value, str) for value in output.values())
    ):
        raise ExtractionOutputError(
            "Extraction tool requires exactly two string fields: rollout_summary and rollout_slug"
        )
    try:
        for value in output.values():
            value.encode("utf-8")
    except UnicodeError as exc:
        raise ExtractionOutputError("Extraction tool arguments contain invalid Unicode") from exc
    return output

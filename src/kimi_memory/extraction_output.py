"""Prefer the last valid submission; otherwise select the largest valid final-text object."""

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


def _decode_candidate(source: str) -> dict[str, str]:
    """Apply the same JSON, schema and result rules before ranking any candidate."""
    try:
        output = json.loads(source, object_pairs_hook=_object, parse_constant=_invalid_constant)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ExtractionOutputError("Extraction candidate is not a complete JSON object") from exc
    if (
        not isinstance(output, dict)
        or set(output) != {"rollout_summary", "rollout_slug"}
        or any(not isinstance(value, str) for value in output.values())
    ):
        raise ExtractionOutputError(
            "Extraction requires exactly two string fields: rollout_summary and rollout_slug"
        )
    try:
        for value in output.values():
            value.encode("utf-8")
    except UnicodeError as exc:
        raise ExtractionOutputError("Extraction candidate contains invalid Unicode") from exc
    summary, slug = output["rollout_summary"].strip(), output["rollout_slug"].strip()
    if len(slug.encode("utf-8")) > 256 or (not summary and slug):
        raise ExtractionOutputError("Extraction candidate has an invalid slug or empty result")
    return output


def _json_objects(text: str):
    """Scan brace-balanced leaf objects once, respecting JSON quotes and escapes.

    A two-string result cannot contain an actual nested object, so only leaf
    objects can match the schema. Ignoring their parents avoids quadratic
    parsing of deeply nested or malformed output. Braces inside JSON strings
    are never object boundaries; no missing quotes/braces are repaired.
    """
    depth = 0
    start = None
    quoted = escaped = False
    for offset, char in enumerate(text):
        if quoted:
            if ord(char) < 32:
                # Literal control characters invalidate a JSON string. Resume
                # scanning later output instead of swallowing the next block.
                depth, start, quoted, escaped = 0, None, False, False
            elif escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == "{":
            depth += 1
            start = offset
        elif char == "}" and depth:
            depth -= 1
            if start is not None:
                yield text[start : offset + 1]
                start = None
        elif char == '"' and depth:
            quoted = True


def parse_extraction(response: dict) -> dict[str, str]:
    if not isinstance(response, dict) or response.get("role") != "assistant":
        raise ExtractionOutputError("Extraction is not an assistant response")
    calls = response.get("tool_calls")
    for call in reversed(calls) if isinstance(calls, list) else ():
        function = call.get("function") if isinstance(call, dict) else None
        if (
            not isinstance(call, dict)
            or call.get("type") != "function"
            or not isinstance(function, dict)
            or function.get("name") != EXTRACTION_TOOL
            or not isinstance(function.get("arguments"), str)
        ):
            continue
        try:
            return _decode_candidate(function["arguments"])
        except ExtractionOutputError:
            continue

    # content is Kimi's final text projection, not _native_message/think parts.
    # Tool parameters never compete with prose: any valid tool submission wins.
    text = response.get("content")
    best, largest = None, -1
    if isinstance(text, str):
        for source in _json_objects(text):
            try:
                candidate = _decode_candidate(source)
                size = len(source.encode("utf-8"))
            except (ExtractionOutputError, UnicodeError):
                continue
            if size >= largest:  # Equal-sized objects favor the later occurrence.
                best, largest = candidate, size
    if best is not None:
        return best
    raise ExtractionOutputError(
        "Extraction has no valid submission or matching JSON object in final text"
    )

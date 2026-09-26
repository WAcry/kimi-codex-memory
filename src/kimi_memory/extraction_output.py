"""Validate the final answer, never a reasoning channel or a guessed JSON substring."""

import json
import re

from .errors import ExtractionOutputError


def parse_extraction(response: dict) -> dict[str, str]:
    text = response.get("content")
    if not isinstance(text, str):
        raise ExtractionOutputError("Extraction final output is not text")
    text = text.lstrip("\ufeff").strip()
    fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        output = json.loads(text)
    except (ValueError, TypeError) as exc:
        # No output contents in durable diagnostics. A plausible thought is not evidence.
        raise ExtractionOutputError("Extraction final output is not a JSON object") from exc
    if (
        not isinstance(output, dict)
        or set(output) != {"rollout_summary", "rollout_slug"}
        or any(not isinstance(value, str) for value in output.values())
    ):
        raise ExtractionOutputError(
            "Extraction must contain exactly two string fields: rollout_summary and rollout_slug"
        )
    return output

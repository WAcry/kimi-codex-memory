"""Stateless Responses API adapter, including replay of encrypted reasoning and calls."""

from .errors import ModelError
from .model_config import Connection


def responses_body(messages: list[dict], tools, connection: Connection, json_mode: bool) -> dict:
    instructions = []
    items = []
    for message in messages:
        role = message["role"]
        if role == "system":
            instructions.append(message["content"])
        elif role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": message["content"],
                }
            )
        elif role == "assistant" and "_responses_output" in message:
            items.extend(message["_responses_output"])
        elif role in {"user", "assistant"}:
            items.append({"role": role, "content": message.get("content", "")})
        else:
            raise ModelError("Unsupported Responses conversation role")
    result = {
        "model": connection.model,
        "input": items,
        "instructions": "\n\n".join(instructions),
        "store": False,
        "stream": False,
        "max_output_tokens": connection.max_output,
        "include": ["reasoning.encrypted_content"],
    }
    if json_mode:
        result["text"] = {"format": {"type": "json_object"}}
    if tools:
        result["tools"] = [{"type": "function", **t["function"], "strict": False} for t in tools]
    effort = connection.options.get("default_effort")
    if effort:
        result["reasoning"] = {"effort": effort}
    return result


def responses_result(response: object) -> dict:
    if (
        not isinstance(response, dict)
        or response.get("status") != "completed"
        or response.get("error")
    ):
        raise ModelError("Responses output failed, was truncated, or did not complete")
    output = response.get("output")
    if not isinstance(output, list):
        raise ModelError("Responses output must be an array")
    texts, calls = [], []
    for item in output:
        if not isinstance(item, dict):
            raise ModelError("Invalid Responses output item")
        kind = item.get("type")
        if kind == "function_call":
            if not all(
                isinstance(item.get(k), str) and item[k] for k in ("call_id", "name", "arguments")
            ):
                raise ModelError("Incomplete Responses function call")
            calls.append(
                {
                    "id": item["call_id"],
                    "type": "function",
                    "function": {"name": item["name"], "arguments": item["arguments"]},
                }
            )
        elif kind == "message":
            if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                raise ModelError("Invalid Responses assistant message")
            for part in item["content"]:
                if (
                    not isinstance(part, dict)
                    or part.get("type") != "output_text"
                    or not isinstance(part.get("text"), str)
                ):
                    raise ModelError("Responses refusal or unknown content type")
                texts.append(part["text"])
        elif kind != "reasoning":
            raise ModelError("Unexpected Responses tool or output type")
    if not texts and not calls:
        raise ModelError("Responses did not return text or tool calls")
    result = {"role": "assistant", "content": "".join(texts), "_responses_output": output}
    if calls:
        result["tool_calls"] = calls
    return result

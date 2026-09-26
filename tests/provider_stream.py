"""Translate local test fixtures to real streaming wire responses, never production output."""

import json


def stream_response(path, payload):
    events = []
    if path.endswith("/chat/completions"):
        choices = payload.get("choices", [])
        if choices:
            choice = choices[0]
            message = dict(choice.get("message", {}))
            calls = message.get("tool_calls", [])
            if calls:
                message["tool_calls"] = [
                    dict(call, index=index, function={**call["function"], "arguments": ""})
                    for index, call in enumerate(calls)
                ]
            events = [
                {
                    "id": "chat-local",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": message, "finish_reason": None}],
                },
                {
                    "id": "chat-local",
                    "object": "chat.completion.chunk",
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason")}
                    ],
                },
            ]
            for index, call in enumerate(calls):
                arguments = call["function"].get("arguments", "")
                step = max(1, len(arguments) // 3)
                for offset in range(0, len(arguments), step):
                    events.insert(
                        -1,
                        {
                            "id": "chat-local",
                            "object": "chat.completion.chunk",
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": None,
                                    "delta": {
                                        "tool_calls": [
                                            {
                                                "index": index,
                                                "function": {
                                                    "arguments": arguments[offset : offset + step]
                                                },
                                            }
                                        ]
                                    },
                                }
                            ],
                        },
                    )
    elif path.endswith("/responses"):
        for index, item in enumerate(payload.get("output", [])):
            item = dict(item, id=item.get("id", f"item_{index}"))
            events.append(
                {
                    "type": "response.output_item.added",
                    "output_index": index,
                    "item": {**item, "arguments": ""} if item["type"] == "function_call" else item,
                }
            )
            if item["type"] == "function_call":
                arguments = item.get("arguments", "")
                step = max(1, len(arguments) // 3)
                for offset in range(0, len(arguments), step):
                    events.append(
                        {
                            "type": "response.function_call_arguments.delta",
                            "item_id": item["id"],
                            "output_index": index,
                            "delta": arguments[offset : offset + step],
                        }
                    )
                events.append(
                    {
                        "type": "response.function_call_arguments.done",
                        "item_id": item["id"],
                        "output_index": index,
                        "arguments": arguments,
                    }
                )
            if item.get("type") == "message":
                for part_index, part in enumerate(item["content"]):
                    if part.get("type") == "output_text":
                        events.append(
                            {
                                "type": "response.output_text.delta",
                                "item_id": item["id"],
                                "output_index": index,
                                "content_index": part_index,
                                "delta": part["text"],
                            }
                        )
            events.append(
                {"type": "response.output_item.done", "output_index": index, "item": item}
            )
        events.append(
            {
                "type": "response.completed"
                if payload.get("status") == "completed"
                else "response.incomplete",
                "response": dict(payload, id="resp-local"),
            }
        )
    elif path.endswith("/messages"):
        events.append(
            {
                "type": "message_start",
                "message": {
                    "id": "msg-local",
                    "type": "message",
                    "role": "assistant",
                    "model": "test-model",
                    "content": [],
                    "stop_reason": None,
                    "usage": {"input_tokens": 100, "output_tokens": 0},
                },
            }
        )
        for index, part in enumerate(payload.get("content", [])):
            kind = part["type"]
            if kind in {"thinking", "text", "tool_use"}:
                block = dict(part)
                if kind == "thinking":
                    block.update(thinking="", signature="")
                    delta = {"type": "thinking_delta", "thinking": part["thinking"]}
                elif kind == "text":
                    block["text"] = ""
                    delta = {"type": "text_delta", "text": part["text"]}
                else:
                    block["input"] = {}
                    delta = {"type": "input_json_delta", "partial_json": json.dumps(part["input"])}
                events.append(
                    {"type": "content_block_start", "index": index, "content_block": block}
                )
                if kind == "tool_use":
                    text = delta["partial_json"]
                    step = max(1, len(text) // 3)
                    for offset in range(0, len(text), step):
                        events.append(
                            {
                                "type": "content_block_delta",
                                "index": index,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": text[offset : offset + step],
                                },
                            }
                        )
                else:
                    events.append({"type": "content_block_delta", "index": index, "delta": delta})
                if kind == "thinking":
                    events.append(
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {"type": "signature_delta", "signature": part["signature"]},
                        }
                    )
                events.append({"type": "content_block_stop", "index": index})
        events.extend(
            [
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": payload.get("stop_reason"), "stop_sequence": None},
                    "usage": {"output_tokens": 10},
                },
                {"type": "message_stop"},
            ]
        )
    return (
        "".join(
            ("event: " + event["type"] + "\n" if "type" in event else "")
            + "data: "
            + json.dumps(event)
            + "\n\n"
            for event in events
        ).encode()
        + b"data: [DONE]\n\n"
    )

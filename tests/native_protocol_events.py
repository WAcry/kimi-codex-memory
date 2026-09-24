"""Small deterministic streams for inspecting the real Kimi protocol encoders."""


def response_events():
    item = {
        "id": "msg_local",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "Synthetic response.", "annotations": []}],
    }
    response = {
        "id": "resp_local",
        "object": "response",
        "created_at": 1700000000,
        "status": "completed",
        "model": "prompt-probe",
        "output": [item],
        "usage": {"input_tokens": 200, "output_tokens": 3, "total_tokens": 203},
    }
    return [
        {
            "type": "response.created",
            "response": {**response, "status": "in_progress", "output": []},
        },
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**item, "status": "in_progress", "content": []},
        },
        {
            "type": "response.content_part.added",
            "item_id": item["id"],
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        },
        {
            "type": "response.output_text.delta",
            "item_id": item["id"],
            "output_index": 0,
            "content_index": 0,
            "delta": "Synthetic response.",
        },
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {"type": "response.completed", "response": response},
    ]


def anthropic_events():
    return [
        {
            "type": "message_start",
            "message": {
                "id": "msg_local",
                "type": "message",
                "role": "assistant",
                "model": "prompt-probe",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 200, "output_tokens": 0},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Synthetic response."},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 3},
        },
        {"type": "message_stop"},
    ]

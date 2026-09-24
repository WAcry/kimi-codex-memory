"""Small OpenAI-compatible/Anthropic adapters; never start a user coding session."""

import json
import re
import threading
import time
from dataclasses import replace
from pathlib import Path

from .config import ModelConfig
from .errors import ModelError, TransportError
from .evidence import estimate_tokens
from .http import JsonHttp
from .model_config import Connection, resolve_connection
from .oauth import native_auth
from .responses import responses_body, responses_result
from .server import kimi_home
from .store import Store


class CallBudget:
    def __init__(self, store: Store, *, daily: int, per_run: int):
        self.store, self.daily, self.per_run = store, daily, per_run
        self.calls = 0
        self.lock = threading.Lock()

    def reserve(self):
        with self.lock:
            if self.calls >= self.per_run:
                raise ModelError("Per-run model-call budget reached")
            self.store.reserve_model_call(now=time.time(), daily_limit=self.daily)
            self.calls += 1


class Model:
    def __init__(
        self,
        config: ModelConfig,
        *,
        budget: CallBudget | None = None,
        input_limit: int = 0,
        home: Path | None = None,
        effective: dict | None = None,
        kimi_command: tuple[str, ...] = (),
    ):
        self.config, self.budget, self.input_limit, self.home = config, budget, input_limit, home
        self.effective, self.kimi_command = effective, kimi_command
        self.connection = None
        self.auth_headers = None
        self.http = JsonHttp(
            timeout=config.timeout_seconds, max_bytes=config.max_response_bytes, use_proxy=True
        )

    def ready(self) -> None:
        self.connection = resolve_connection(self.config, home=self.home, effective=self.effective)

    def input_budget(self) -> int:
        if self.connection is None:
            self.ready()
        return self.connection.input_budget(self.input_limit)

    def _connection(self, force=False) -> Connection:
        if self.connection is None:
            self.ready()
        connection = self.connection
        if connection.oauth:
            auth = native_auth(
                self.home or kimi_home(),
                connection.oauth_ref,
                force=force,
                command=self.kimi_command,
            )
            return replace(
                connection,
                key=auth["access_token"],
                headers={**auth["headers"], **connection.headers},
            )
        if connection.provider_type == "kimi":
            if self.auth_headers is None:
                self.auth_headers = native_auth(
                    self.home or kimi_home(), None, command=self.kimi_command
                )["headers"]
            return replace(connection, headers={**self.auth_headers, **connection.headers})
        return connection

    def complete(
        self, messages: list[dict], *, tools: list[dict] | None = None, json_mode: bool = False
    ) -> dict:
        connection = self._connection()
        if estimate_tokens(json.dumps(messages, ensure_ascii=False)) > self.input_budget():
            raise ModelError("Model input budget exceeded; no request was sent")
        if connection.protocol == "anthropic":
            body = self._anthropic_body(messages, tools, connection.model)
            body["max_tokens"] = connection.max_output
            endpoint = connection.base_url + (
                "/messages" if connection.base_url.endswith("/v1") else "/v1/messages"
            )
            auth = (
                {"Authorization": f"Bearer {connection.key}"}
                if connection.oauth
                else {"x-api-key": connection.key}
            )
            headers = {**connection.headers, **auth, "anthropic-version": "2023-06-01"}
        elif connection.protocol == "openai_responses":
            body = responses_body(messages, tools, connection, json_mode and self.config.json_mode)
            endpoint = connection.base_url + "/responses"
            headers = {**connection.headers, "Authorization": f"Bearer {connection.key}"}
        else:
            body = {
                "model": connection.model,
                "messages": [
                    {k: v for k, v in message.items() if not k.startswith("_")}
                    for message in messages
                ],
                "stream": False,
                "max_tokens": connection.max_output,
            }
            # Mirror Kimi's Chat Completions output-cap encoding for OpenAI reasoning models.
            if re.match(r"^(?:o\d(?:$|[-.])|gpt-5(?:$|[-.]))", connection.model.lower()):
                body["max_completion_tokens"] = min(body.pop("max_tokens"), 128 * 1024)
            if tools:
                body["tools"] = tools
            if json_mode and self.config.json_mode:
                body["response_format"] = {"type": "json_object"}
            endpoint = connection.base_url + "/chat/completions"
            headers = {**connection.headers, "Authorization": f"Bearer {connection.key}"}
        if not connection.key:
            headers.pop("Authorization", None)
            headers.pop("x-api-key", None)

        # Defense in depth: do not send an accidentally quoted live credential as history.
        def scrub(value):
            if isinstance(value, str):
                return value.replace(connection.key, "[REDACTED]") if connection.key else value
            if isinstance(value, list):
                return [scrub(item) for item in value]
            if isinstance(value, dict):
                return {key: scrub(item) for key, item in value.items()}
            return value

        for field in ("messages", "input", "instructions"):
            if field in body:
                body[field] = scrub(body[field])
        if "system" in body:
            body["system"] = scrub(body["system"])
        if self.budget:
            self.budget.reserve()
        try:
            response = self.http.request(endpoint, headers=headers, body=body)
        except TransportError as exc:
            if getattr(exc, "status", None) == 401 and connection.oauth:
                connection = self._connection(force=True)
                headers["Authorization"] = f"Bearer {connection.key}"
                try:
                    if self.budget:
                        self.budget.reserve()
                    response = self.http.request(endpoint, headers=headers, body=body)
                except TransportError as retry:
                    raise ModelError(str(retry)) from retry
            else:
                raise ModelError(str(exc)) from exc
        if connection.protocol == "anthropic":
            return self._anthropic_response(response)
        if connection.protocol == "openai_responses":
            return responses_result(response)
        try:
            choice = response["choices"][0]
            if choice.get("finish_reason") not in {"stop", "tool_calls"}:
                raise ModelError("Model output was truncated, filtered, or unfinished")
            message = choice["message"]
            result = {"role": "assistant", "content": message.get("content") or ""}
            if not isinstance(result["content"], str):
                raise ModelError("Unexpected model content shape")
            if message.get("tool_calls"):
                result["tool_calls"] = message["tool_calls"]
            if "reasoning_content" in message:
                result["reasoning_content"] = message["reasoning_content"]
            return result
        except (KeyError, TypeError, IndexError) as exc:
            raise ModelError("Unexpected model response shape") from exc

    def _anthropic_body(self, messages: list[dict], tools, model: str) -> dict:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        converted = []
        for message in messages:
            role = message["role"]
            if role == "system":
                continue
            if role == "tool":
                role = "user"
                content = [
                    {
                        "type": "tool_result",
                        "tool_use_id": message["tool_call_id"],
                        "content": message["content"],
                    }
                ]
            elif "_anthropic_content" in message:
                content = message["_anthropic_content"]
            else:
                content = [{"type": "text", "text": message.get("content") or " "}]
            if converted and converted[-1]["role"] == role:
                converted[-1]["content"].extend(content)
            else:
                converted.append({"role": role, "content": content})
        body = {
            "model": model,
            "system": system,
            "messages": converted,
            "max_tokens": self.config.max_output_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "input_schema": t["function"]["parameters"],
                }
                for t in tools
            ]
        return body

    def _anthropic_response(self, response) -> dict:
        try:
            if response.get("stop_reason") not in {"end_turn", "tool_use", "stop_sequence"}:
                raise ModelError("Model output was truncated or unfinished")
            content = response["content"]
            text = "".join(p["text"] for p in content if p["type"] == "text")
            calls = [
                {
                    "id": p["id"],
                    "type": "function",
                    "function": {
                        "name": p["name"],
                        "arguments": json.dumps(p["input"], ensure_ascii=False),
                    },
                }
                for p in content
                if p["type"] == "tool_use"
            ]
            result = {"role": "assistant", "content": text, "_anthropic_content": content}
            if calls:
                result["tool_calls"] = calls
            return result
        except (KeyError, TypeError, AttributeError) as exc:
            raise ModelError("Unexpected model response shape") from exc

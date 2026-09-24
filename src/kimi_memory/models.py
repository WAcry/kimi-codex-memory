"""Small OpenAI-compatible/Anthropic adapters; never start a user coding session."""

import json
import os
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .config import ModelConfig
from .errors import ConfigurationError, ModelError, TransportError
from .evidence import estimate_tokens
from .files import read_json, safe_component
from .http import JsonHttp, model_origin
from .server import kimi_home
from .store import Store


@dataclass(frozen=True)
class Connection:
    base_url: str
    model: str
    key: str
    headers: dict
    oauth: bool = False


def resolve_connection(config: ModelConfig, *, home: Path | None = None) -> Connection:
    provider = {}
    home = home or kimi_home()
    key = os.environ.get(config.api_key_env, "") if config.api_key_env else ""
    oauth = False
    if config.kimi_provider:
        try:
            data = tomllib.loads((home / "config.toml").read_text())
            provider = data["providers"][config.kimi_provider]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigurationError(
                "Configured Kimi provider is not available in config.toml"
            ) from exc
        if not isinstance(provider, dict):
            raise ConfigurationError("Invalid Kimi provider declaration")
        credentials = [bool(provider.get(name)) for name in ("api_key", "api_key_env", "oauth")]
        if sum(credentials) > 1:
            raise ConfigurationError("Kimi provider declares conflicting credential sources")
        if not key:
            if provider.get("api_key"):
                key = provider["api_key"]
            elif provider.get("api_key_env"):
                key = os.environ.get(provider["api_key_env"], "")
            elif provider.get("oauth"):
                ref = provider["oauth"]
                if not isinstance(ref, dict) or ref.get("storage") != "file":
                    raise ConfigurationError(
                        "Only explicitly selected file-backed Kimi OAuth is supported"
                    )
                token_path = home / "credentials" / (safe_component(ref.get("key", "")) + ".json")
                try:
                    if token_path.stat().st_mode & 0o077:
                        raise ConfigurationError("Kimi credential file must be private")
                    token = read_json(token_path, 65_536)
                except (OSError, ValueError) as exc:
                    raise ConfigurationError("Kimi OAuth token unavailable") from exc
                if not isinstance(token, dict) or not isinstance(
                    token.get("expires_at"), (int, float)
                ):
                    raise ConfigurationError("Invalid Kimi OAuth token shape")
                if token["expires_at"] <= time.time() + 30:
                    raise ConfigurationError(
                        "Kimi OAuth token expired; refresh through Kimi, then retry"
                    )
                key = token.get("access_token", "")
                oauth = True
    base = config.base_url or provider.get("base_url", "")
    model = config.model or provider.get("default_model", "")
    if not base or not model or not isinstance(key, str) or not key:
        raise ConfigurationError(
            "Configure a model, base_url, and credential source in worker.toml"
        )
    headers = provider.get("custom_headers", {})
    if not isinstance(headers, dict) or any(not isinstance(v, str) for v in headers.values()):
        raise ConfigurationError("Invalid provider custom_headers")
    return Connection(model_origin(base), model, key, headers, oauth)


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
        input_limit: int = 100_000,
        home: Path | None = None,
    ):
        self.config, self.budget, self.input_limit, self.home = config, budget, input_limit, home
        self.http = JsonHttp(timeout=config.timeout_seconds, max_bytes=config.max_response_bytes)

    def ready(self) -> None:
        resolve_connection(self.config, home=self.home)

    def complete(
        self, messages: list[dict], *, tools: list[dict] | None = None, json_mode: bool = False
    ) -> dict:
        connection = resolve_connection(self.config, home=self.home)
        if estimate_tokens(json.dumps(messages, ensure_ascii=False)) > self.input_limit:
            raise ModelError("Model input budget exceeded; no request was sent")
        if self.config.protocol == "anthropic":
            body = self._anthropic_body(messages, tools, connection.model)
            endpoint = connection.base_url + (
                "/messages" if connection.base_url.endswith("/v1") else "/v1/messages"
            )
            auth = (
                {"Authorization": f"Bearer {connection.key}"}
                if connection.oauth
                else {"x-api-key": connection.key}
            )
            headers = {**connection.headers, **auth, "anthropic-version": "2023-06-01"}
        else:
            body = {
                "model": connection.model,
                "messages": [
                    {k: v for k, v in message.items() if not k.startswith("_")}
                    for message in messages
                ],
                "stream": False,
                "max_tokens": self.config.max_output_tokens,
            }
            if tools:
                body["tools"] = tools
            if json_mode and self.config.json_mode:
                body["response_format"] = {"type": "json_object"}
            endpoint = connection.base_url + "/chat/completions"
            headers = {**connection.headers, "Authorization": f"Bearer {connection.key}"}

        # Defense in depth: do not send an accidentally quoted live credential as history.
        def scrub(value):
            if isinstance(value, str):
                return value.replace(connection.key, "[REDACTED]")
            if isinstance(value, list):
                return [scrub(item) for item in value]
            if isinstance(value, dict):
                return {key: scrub(item) for key, item in value.items()}
            return value

        body["messages"] = scrub(body["messages"])
        if "system" in body:
            body["system"] = scrub(body["system"])
        if self.budget:
            self.budget.reserve()
        try:
            response = self.http.request(endpoint, headers=headers, body=body)
        except TransportError as exc:
            raise ModelError(str(exc)) from exc
        if self.config.protocol == "anthropic":
            return self._anthropic_response(response)
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

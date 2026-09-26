"""Budgeted native model requests; never start a user coding session."""

import json
import threading
import time
from dataclasses import replace
from pathlib import Path

from .config import ModelConfig
from .errors import ModelError
from .evidence import estimate_tokens
from .model_config import Connection, resolve_connection
from .oauth import native_auth
from .requester import native_request
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
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        json_mode: bool = False,
        output_tool: str | None = None,
    ) -> dict:
        connection = self._connection()
        payload = {"messages": messages, "tools": tools or []}
        if estimate_tokens(json.dumps(payload, ensure_ascii=False)) > self.input_budget():
            raise ModelError("Model input budget exceeded; no request was sent")

        def scrub(value):
            if isinstance(value, str):
                return value.replace(connection.key, "[REDACTED]") if connection.key else value
            if isinstance(value, list):
                return [scrub(item) for item in value]
            if isinstance(value, dict):
                return {key: scrub(item) for key, item in value.items()}
            return value

        messages = scrub(messages)
        if self.budget:
            self.budget.reserve()
        try:
            return native_request(
                connection,
                messages,
                tools,
                json_mode=json_mode and self.config.json_mode,
                config=self.config,
                command=self.kimi_command,
                output_tool=output_tool,
            )
        except ModelError as exc:
            if getattr(exc, "status", None) != 401 or not connection.oauth:
                raise
            connection = self._connection(force=True)
            if self.budget:
                self.budget.reserve()
            return native_request(
                connection,
                messages,
                tools,
                json_mode=json_mode and self.config.json_mode,
                config=self.config,
                command=self.kimi_command,
                output_tool=output_tool,
            )

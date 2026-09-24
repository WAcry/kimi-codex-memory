"""Resolve Kimi's effective default alias without copying credentials into memory state."""

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .config import ModelConfig
from .errors import ConfigurationError
from .http import model_origin
from .server import kimi_home

FALLBACK_CONTEXT = 256_000
PROTOCOLS = {"openai", "anthropic", "openai_responses"}
ENDPOINTS = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    "openai_responses": ("https://api.openai.com/v1", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    "anthropic": ("https://api.anthropic.com", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
    "kimi": ("https://api.kimi.com/coding/v1", "KIMI_API_KEY", "KIMI_CODE_BASE_URL"),
}


def canonical(record: dict) -> dict:
    result = {re.sub(r"[A-Z]", lambda m: "_" + m[0].lower(), k): v for k, v in record.items()}
    for field_name in ("overrides", "oauth"):
        if isinstance(result.get(field_name), dict):
            result[field_name] = canonical(result[field_name])
    return result


def mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigurationError(f"Invalid {label} configuration")
    return value


def positive(value) -> int | None:
    return value if type(value) is int and value > 0 else None


@dataclass(frozen=True)
class Connection:
    base_url: str
    model: str
    key: str
    headers: dict
    oauth: bool = False
    protocol: str = "openai"
    context_window: int = FALLBACK_CONTEXT
    max_input: int = FALLBACK_CONTEXT
    max_output: int = 8192
    provider_type: str = "openai"
    oauth_ref: dict | None = None
    alias: str = ""
    options: dict = field(default_factory=dict)

    def input_budget(self, override=0) -> int:
        window = min(self.context_window, self.max_input)
        result = min(int(window * 0.70), max(1, self.context_window - self.max_output - 4096))
        return min(result, override) if override > 0 else result


def resolve_connection(
    config: ModelConfig, *, home: Path | None = None, effective: dict | None = None
) -> Connection:
    home = home or kimi_home()
    try:
        raw = (
            tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
            if (home / "config.toml").exists()
            else {}
        )
    except (OSError, ValueError) as exc:
        raise ConfigurationError("Kimi configuration could not be read") from exc
    providers = {
        k: canonical(mapping(v, "provider"))
        for k, v in mapping(raw.get("providers", {}), "providers").items()
    }
    models = {
        k: canonical(mapping(v, "model"))
        for k, v in mapping(raw.get("models", {}), "models").items()
    }
    runtime = mapping(effective, "effective Kimi") if effective is not None else {}
    for collection, target in (("providers", providers), ("models", models)):
        for key, item in mapping(runtime.get(collection, {}), collection).items():
            if isinstance(item, dict):
                safe = {
                    k: v for k, v in canonical(item).items() if k != "has_api_key" and v is not None
                }
                target[key] = {**target.get(key, {}), **safe}
    default = runtime.get("default_model", raw.get("default_model", ""))
    # A helper borrowed from another process cannot inherit this hook's environment.
    if os.environ.get("KIMI_MODEL_NAME") and not config.model:
        default = "__memory_env__"
        models[default] = {
            "model": os.environ["KIMI_MODEL_NAME"],
            "provider": default,
            "max_context_size": int(
                os.environ.get("KIMI_MODEL_MAX_CONTEXT_SIZE", FALLBACK_CONTEXT)
            ),
            "max_output_size": int(os.environ.get("KIMI_MODEL_MAX_OUTPUT_SIZE", 8192)),
        }
        providers[default] = {
            "type": os.environ.get("KIMI_MODEL_PROVIDER_TYPE", "kimi"),
            "base_url": os.environ.get("KIMI_MODEL_BASE_URL", ""),
            "api_key": os.environ.get("KIMI_MODEL_API_KEY", ""),
        }
    alias = config.model or (
        providers.get(config.kimi_provider, {}).get("default_model", "")
        if config.kimi_provider
        else default
    )
    if not alias:
        raise ConfigurationError(
            "Select a default model in Kimi Code; memory needs no separate model configuration"
        )
    record = models.get(alias, {})
    if not record and not (config.base_url or config.kimi_provider):
        raise ConfigurationError("The requested Kimi model alias is not configured")
    record = {**record, **mapping(record.get("overrides", {}), "model overrides")}
    provider_id = (
        config.kimi_provider
        or record.get("provider_id")
        or record.get("provider")
        or runtime.get("default_provider", raw.get("default_provider", ""))
    )
    if provider_id and provider_id not in providers:
        raise ConfigurationError("The selected Kimi provider is unavailable")
    provider = providers.get(provider_id, {})
    if not record and not config.model:
        raise ConfigurationError("Kimi's default model alias is not resolvable")
    wire_name = record.get("name") or record.get("model") or config.model
    if not isinstance(wire_name, str) or not wire_name:
        raise ConfigurationError("The selected model has no wire-facing name")
    provider_type = provider.get("type") or record.get("protocol") or config.protocol or "openai"
    protocol = (
        config.protocol
        or record.get("protocol")
        or ("openai" if provider_type == "kimi" else provider_type)
    )
    if protocol not in PROTOCOLS:
        raise ConfigurationError("This model protocol is not supported; Gemini is not enabled")
    endpoint, key_env, url_env = ENDPOINTS.get(provider_type, ENDPOINTS[protocol])
    env = {**os.environ, **mapping(provider.get("env", {}), "provider environment")}
    base = (
        config.base_url
        or record.get("base_url")
        or provider.get("base_url")
        or env.get(url_env)
        or endpoint
    )
    key = os.environ.get(config.api_key_env, "") if config.api_key_env else ""
    if config.api_key_env and not key:
        raise ConfigurationError("The configured memory API-key environment variable is empty")
    oauth_ref = None
    chosen = record if record.get("api_key") or record.get("oauth") else provider
    kinds = sum(bool(chosen.get(k)) for k in ("api_key", "api_key_env", "oauth"))
    if kinds > 1:
        raise ConfigurationError("Kimi model/provider declares conflicting credential sources")
    if not key:
        if chosen.get("api_key"):
            key = chosen["api_key"]
        elif chosen.get("api_key_env"):
            key = os.environ.get(chosen["api_key_env"], "")
            if not key:
                raise ConfigurationError("The Kimi provider API-key environment variable is empty")
        elif chosen.get("oauth"):
            oauth_ref = chosen["oauth"]
            if provider_type != "kimi" or not isinstance(oauth_ref, dict):
                raise ConfigurationError("Only Kimi subscription OAuth is supported")
        else:
            key = env.get(key_env, "")
    headers = {}
    for line in os.environ.get("KIMI_CODE_CUSTOM_HEADERS", "").splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip():
            headers[name.strip()] = value.strip()
    headers.update(mapping(provider.get("custom_headers", {}), "provider headers"))
    if not isinstance(key, str) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()
    ):
        raise ConfigurationError("Invalid provider authentication or custom headers")
    context = positive(record.get("max_context_size")) or FALLBACK_CONTEXT
    if config.context_window > 0:
        context = min(context, config.context_window)
    input_size = min(context, positive(record.get("max_input_size")) or context)
    output_size = positive(record.get("max_output_size")) or 8192
    if config.max_output_tokens > 0:
        output_size = min(output_size, config.max_output_tokens)
    output_size = min(output_size, max(1, context - 1024))
    return Connection(
        model_origin(base),
        wire_name,
        key,
        headers,
        oauth_ref is not None,
        protocol,
        context,
        input_size,
        output_size,
        provider_type,
        oauth_ref,
        alias,
        {
            k: v
            for k, v in record.items()
            if k in {"default_effort", "reasoning_key", "capabilities", "adaptive_thinking"}
        },
    )

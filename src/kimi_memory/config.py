"""Generation configuration. Deliberately not imported by reader or hook rendering."""

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from .errors import ConfigurationError


@dataclass(frozen=True)
class ApiConfig:
    kimi_command: tuple[str, ...] = ()
    server_url: str = ""
    auto_start: bool = True
    port: int = 59627
    allowed_versions: tuple[str, ...] = ("2.1.0",)
    allow_unverified_version: bool = False
    request_timeout_seconds: int = 20
    startup_timeout_seconds: int = 60
    max_response_bytes: int = 32 * 1024 * 1024
    max_transcript_pages: int = 1000
    max_transcript_bytes: int = 128 * 1024 * 1024
    page_size: int = 100


@dataclass(frozen=True)
class GenerationConfig:
    enabled: bool = True
    min_idle_hours: float = 6.0
    source_max_age_days: float = 10.0
    retention_days: float = 30.0
    max_session_scan: int = 5000
    max_extractions: int = 2
    extraction_concurrency: int = 2
    max_consolidation_sources: int = 256
    prune_batch_size: int = 200
    lease_seconds: int = 3600
    heartbeat_seconds: int = 90
    retry_delay_seconds: int = 3600
    max_extraction_attempts: int = 3
    consolidation_cooldown_seconds: int = 21600
    max_input_tokens: int = 100_000
    max_tool_bytes: int = 8192
    max_rollout_summary_bytes: int = 9000
    max_memory_summary_bytes: int = 10_000
    max_tool_read_bytes: int = 32_768
    max_consolidation_steps: int = 24
    max_daily_model_calls: int = 100
    max_run_model_calls: int = 32
    include_cwds: tuple[str, ...] = ()
    exclude_cwds: tuple[str, ...] = ()
    exclude_session_ids: tuple[str, ...] = ()
    retained_generations: int = 3
    max_notes_bytes: int = 2 * 1024 * 1024
    resource_retention_days: float = 7.0


@dataclass(frozen=True)
class ModelConfig:
    protocol: str = "openai"
    base_url: str = ""
    model: str = ""
    api_key_env: str = "KIMI_MEMORY_API_KEY"
    kimi_provider: str = ""
    timeout_seconds: int = 180
    max_output_tokens: int = 8192
    json_mode: bool = True
    max_response_bytes: int = 2 * 1024 * 1024


@dataclass(frozen=True)
class WorkerConfig:
    api: ApiConfig = ApiConfig()
    generation: GenerationConfig = GenerationConfig()
    extraction: ModelConfig = ModelConfig()
    consolidation: ModelConfig = ModelConfig()


def _section(cls, value: object):
    if not isinstance(value, dict):
        raise ConfigurationError(f"{cls.__name__} must be a table")
    defaults = cls()
    allowed = {field.name for field in fields(cls)}
    unknown = set(value) - allowed
    if unknown:
        raise ConfigurationError(f"Unknown {cls.__name__} option: {sorted(unknown)[0]}")
    parsed = {}
    for name, item in value.items():
        default = getattr(defaults, name)
        if isinstance(default, tuple):
            if not isinstance(item, list) or any(not isinstance(v, str) for v in item):
                raise ConfigurationError(f"{name} must be an array of strings")
            parsed[name] = tuple(item)
        elif isinstance(default, float) and type(item) in (float, int):
            parsed[name] = float(item)
        elif type(item) is type(default):
            parsed[name] = item
        else:
            raise ConfigurationError(f"Invalid type for {name}")
    return cls(**parsed)


def load_worker_config(home: Path) -> WorkerConfig:
    path = Path(os.environ.get("KIMI_MEMORY_WORKER_CONFIG", str(home / "worker.toml")))
    try:
        raw = tomllib.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError) as exc:
        raise ConfigurationError(
            "Cannot parse worker.toml; the offline reader is unaffected"
        ) from exc
    if set(raw) - {"api", "generation", "extraction", "consolidation"}:
        raise ConfigurationError("Unknown worker configuration section")
    extraction_raw = raw.get("extraction", {})
    consolidation_raw = raw.get("consolidation", {})
    if not isinstance(extraction_raw, dict) or not isinstance(consolidation_raw, dict):
        raise ConfigurationError("Model settings must be tables")
    config = WorkerConfig(
        api=_section(ApiConfig, raw.get("api", {})),
        generation=_section(GenerationConfig, raw.get("generation", {})),
        extraction=_section(ModelConfig, extraction_raw),
        consolidation=_section(ModelConfig, {**extraction_raw, **consolidation_raw}),
    )
    _validate(config)
    return config


def _validate(config: WorkerConfig) -> None:
    import math

    for section in (config.api, config.generation, config.extraction, config.consolidation):
        for field in fields(section):
            value = getattr(section, field.name)
            if type(value) in (int, float) and (not math.isfinite(value) or value < 0):
                raise ConfigurationError(f"{field.name} must be finite and non-negative")
    api, gen = config.api, config.generation
    if not 1 <= api.page_size <= 100 or not 1024 <= api.port <= 65435:
        raise ConfigurationError("page_size must be 1..100; helper port must be 1024..65435")
    if 58627 <= api.port <= 58727:
        raise ConfigurationError("Keep helper ports outside Kimi's default user port range")
    if api.kimi_command and not Path(api.kimi_command[0]).is_absolute():
        raise ConfigurationError("api.kimi_command must start with an absolute executable path")
    for name in (
        "request_timeout_seconds",
        "startup_timeout_seconds",
        "max_response_bytes",
        "max_transcript_pages",
        "max_transcript_bytes",
    ):
        if getattr(api, name) <= 0:
            raise ConfigurationError(f"{name} must be positive")
    if not api.allowed_versions and not api.allow_unverified_version:
        raise ConfigurationError("At least one validated Kimi version is required")
    for name in (
        "max_session_scan",
        "extraction_concurrency",
        "max_consolidation_sources",
        "lease_seconds",
        "heartbeat_seconds",
        "max_extraction_attempts",
        "max_input_tokens",
        "max_tool_bytes",
        "max_tool_read_bytes",
        "max_consolidation_steps",
        "max_run_model_calls",
        "max_daily_model_calls",
        "retained_generations",
        "retention_days",
        "max_notes_bytes",
    ):
        if getattr(gen, name) <= 0:
            raise ConfigurationError(f"{name} must be positive")
    if gen.heartbeat_seconds * 2 >= gen.lease_seconds:
        raise ConfigurationError("lease_seconds must be more than twice heartbeat_seconds")
    if gen.source_max_age_days > gen.retention_days:
        raise ConfigurationError("source_max_age_days must not exceed retention_days")
    if not 256 <= gen.max_memory_summary_bytes <= 131_072:
        raise ConfigurationError("max_memory_summary_bytes must be 256..131072")
    if not 256 <= gen.max_rollout_summary_bytes <= 131_072:
        raise ConfigurationError("max_rollout_summary_bytes must be 256..131072")
    for model in (config.extraction, config.consolidation):
        if model.protocol not in ("openai", "anthropic"):
            raise ConfigurationError("model protocol must be openai or anthropic")
        if min(model.timeout_seconds, model.max_output_tokens, model.max_response_bytes) <= 0:
            raise ConfigurationError("Model timeout/output limits must be positive")

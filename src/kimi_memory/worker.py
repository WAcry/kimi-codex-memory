"""Generation orchestration. Importing/starting this is never necessary to read memory."""

import fnmatch
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .citations import collect_citations
from .config import WorkerConfig, load_worker_config
from .errors import BusyError, MemoryErrorBase, ModelError, ResyncRequired, UnsafePathError
from .evidence import budget_evidence, normalize, redact
from .files import file_lock, memory_home, read_json, utf8_middle, write_json
from .kimi import KimiClient, Transcript
from .models import CallBudget, Model
from .server import ServerManager
from .store import Store, keep_lease
from .workspace import (
    MINIMAL_SUMMARY,
    PROMPTS,
    Workspace,
    ensure_layout,
    prune_generations,
    recover_publication,
    validate_summary,
)


def allowed(source_id: str, cwd: str, config: WorkerConfig) -> bool:
    gen = config.generation

    # Kimi emits native paths; accept the portable forward-slash spelling in overrides.
    def matches(pattern: str) -> bool:
        import os

        value, pattern = cwd.replace("\\", "/"), pattern.replace("\\", "/")
        if os.name == "nt":
            value, pattern = value.casefold(), pattern.casefold()
        return fnmatch.fnmatchcase(value, pattern)

    return (
        source_id not in gen.exclude_session_ids
        and not any(matches(p) for p in gen.exclude_cwds)
        and (not gen.include_cwds or any(matches(p) for p in gen.include_cwds))
    )


def queue_entries(home: Path) -> list[Path]:
    return sorted((home / "queue").glob("*.json"))


def collect_inputs(
    client: KimiClient,
    store: Store,
    config: WorkerConfig,
    home: Path,
    events: list[dict],
    now: float,
) -> tuple[list[Transcript], int]:
    gen = config.generation
    sources = client.sessions(since=now - gen.retention_days * 86400, limit=gen.max_session_scan)
    forced = {e["session_id"] for e in events if isinstance(e.get("session_id"), str)}
    current_ids = {
        e["session_id"]
        for e in events
        if e.get("event") in {"SessionStart", "TurnStarted"}
        and e.get("time", now) >= now - max(3600, gen.min_idle_hours * 3600)
    }
    known = {source.id for source in sources}
    for source_id in sorted(forced - known):
        sources.append(client.source(source_id))
    active = set()
    for path in (home / "activity").glob("*.json"):
        try:
            data = read_json(path, 4096)
            if data.get("active") and data.get("time", 0) > now - max(
                3600, gen.min_idle_hours * 3600
            ):
                active.add(data["session_id"])
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    candidates = []
    uses = []
    scans = []
    for source in sorted(sources, key=lambda s: (s.updated_at, s.id), reverse=True):
        if not allowed(source.id, source.cwd, config):
            continue
        age = now - source.updated_at
        extract = (
            not source.busy
            and not source.archived
            and source.id not in active
            and source.id not in current_ids
            and gen.min_idle_hours * 3600 <= age <= gen.source_max_age_days * 86400
            and len(candidates) < gen.max_extractions
            and store.extraction_due(source, now)
        )
        if not extract and store.scan_is_current(source) and source.id not in forced:
            continue
        transcript = client.transcript(source)
        uses.extend(collect_citations(transcript))
        scans.append((source, transcript.version))
        if extract:
            candidates.append(transcript)
    # Only after every required page/session is valid. No partial scan can drive forgetting.
    count = store.record_citations(uses, now=now)
    for source, version in scans:
        store.scanned(source, version, now)
    return candidates, count


def extract_one(
    transcript: Transcript, store: Store, config: WorkerConfig, model, home: Path
) -> str:
    gen = config.generation
    version = transcript.version
    owner = store.claim(
        "extract:" + transcript.source.id,
        version,
        now=time.time(),
        lease=gen.lease_seconds,
        attempts=gen.max_extraction_attempts,
    )
    if owner is None:
        return "skipped"
    key = "extract:" + transcript.source.id
    try:
        with keep_lease(store, key, owner, interval=gen.heartbeat_seconds, lease=gen.lease_seconds):
            evidence = normalize(transcript, memory_root=str(home))
            input_limit = (
                model.input_budget()
                if hasattr(model, "input_budget")
                else (gen.max_input_tokens or 179_200)
            )
            contents = budget_evidence(
                evidence,
                max_tokens=max(256, input_limit - 4096),
                max_tool_bytes=gen.max_tool_bytes,
            )
            system = (PROMPTS / "stage_one_system_v2.md").read_text(encoding="utf-8")
            template = (PROMPTS / "stage_one_input_v2.md").read_text(encoding="utf-8")
            replacements = {
                "{{ rollout_path }}": "kimi-session:" + transcript.source.id,
                "{{ rollout_cwd }}": transcript.source.cwd,
                "{{ rollout_git_branch }}": "unknown; rely only on conversation evidence",
                "{{ rollout_contents }}": contents,
                "pre-rendered from rollout `.jsonl`; filtered response items": "normalized from the native Kimi transcript API; filtered evidence",
            }
            for old, new in replacements.items():
                template = template.replace(old, new)
            response = model.complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": redact(template)},
                ],
                json_mode=True,
            )
            if response.get("tool_calls"):
                raise ModelError("Extraction has no tools")
            try:
                output = json.loads(response["content"])
            except (ValueError, TypeError, KeyError) as exc:
                raise ModelError("Extraction did not return a JSON object") from exc
            if (
                not isinstance(output, dict)
                or set(output) != {"rollout_summary", "rollout_slug"}
                or any(not isinstance(v, str) for v in output.values())
            ):
                raise ModelError(
                    "Extraction must return exactly rollout_summary and rollout_slug strings"
                )
            summary, slug = (
                redact(output["rollout_summary"].strip()),
                output["rollout_slug"].strip(),
            )
            summary = utf8_middle(summary, gen.max_rollout_summary_bytes)
            if len(slug.encode()) > 256:
                raise ModelError("Extracted slug exceeds its byte limit")
            if not summary and slug:
                raise ModelError("Empty extraction must also have an empty slug")
        store.save_extraction(transcript.source, version, summary, slug, owner, time.time())
        return "extracted" if summary else "empty"
    except Exception as exc:
        store.fail(
            key,
            owner,
            now=time.time(),
            delay=gen.retry_delay_seconds,
            code=exc.code if isinstance(exc, MemoryErrorBase) else "extraction_failed",
        )
        raise


def consolidate_agent(workspace: Workspace, model) -> None:
    messages = [
        {"role": "system", "content": workspace.prompt()},
        {
            "role": "user",
            "content": "Consolidate the supplied memory workspace. Read phase2_workspace_diff.md first.",
        },
    ]
    for _ in range(workspace.config.max_consolidation_steps):
        response = model.complete(messages, tools=workspace.tools())
        messages.append(response)
        calls = response.get("tool_calls", [])
        if not calls:
            if not workspace.diff_read:
                raise ModelError("Consolidator did not read the source diff")
            path = workspace.path / "memory_summary.md"
            if not path.is_file():
                raise ModelError("Consolidator did not produce memory_summary.md")
            validate_summary(
                path.read_text(encoding="utf-8"),
                workspace.config.max_memory_summary_bytes,
                workspace.source_files,
            )
            return
        if not isinstance(calls, list) or len(calls) > 32:
            raise ModelError("Invalid consolidation tool-call batch")
        for call in calls:
            try:
                call_id = call["id"]
                function = call["function"]
                args = json.loads(function["arguments"])
                if not isinstance(args, dict) or not isinstance(call_id, str):
                    raise ValueError("invalid tool arguments")
            except (TypeError, KeyError, ValueError) as exc:
                raise ModelError("Malformed consolidation tool call") from exc
            try:
                result = workspace.execute(function["name"], args)
            except (ModelError, OSError, ValueError, UnsafePathError) as exc:
                result = {
                    "error": str(exc) if isinstance(exc, ModelError) else "File access refused"
                }
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    raise ModelError("Consolidation exceeded its step budget")


def phase_two(store: Store, config: WorkerConfig, home: Path, model, *, can_publish=None) -> str:
    gen = config.generation
    rows = store.selected(
        cutoff=time.time() - gen.retention_days * 86400,
        limit=gen.max_consolidation_sources,
        accept=lambda row: allowed(row["source_id"], row["cwd"], config),
    )
    workspace = Workspace(home, rows, gen)
    owner = None
    try:
        owner = store.claim(
            "consolidate",
            workspace.input_hash,
            now=time.time(),
            lease=gen.lease_seconds,
            attempts=gen.max_extraction_attempts,
            cooldown=gen.consolidation_cooldown_seconds,
            repeat=True,
        )
        if owner is None:
            return "cooldown"
        if workspace.unchanged():
            store.finish_noop(owner, workspace.input_hash, time.time())
            return "unchanged"
        with keep_lease(
            store, "consolidate", owner, interval=gen.heartbeat_seconds, lease=gen.lease_seconds
        ):
            workspace.prepare()
            meaningful_inputs = rows or any(
                name != "extensions/ad_hoc/instructions.md" for name in workspace.files
            )
            if not meaningful_inputs:
                workspace.execute("read_file", {"path": "phase2_workspace_diff.md"})
                workspace.execute("write_summary", {"content": MINIMAL_SUMMARY})
            else:
                model.ready()
                consolidate_agent(workspace, model)
        if can_publish is not None and not can_publish():
            raise ResyncRequired(
                "New hook events arrived during consolidation; published memory was preserved"
            )
        generation = workspace.publish(store, owner)
        prune_generations(home, gen.retained_generations)
        return generation
    except Exception as exc:
        if owner:
            store.fail(
                "consolidate",
                owner,
                now=time.time(),
                delay=0 if isinstance(exc, ResyncRequired) else gen.retry_delay_seconds,
                code=exc.code if isinstance(exc, MemoryErrorBase) else "consolidation_failed",
            )
        raise
    finally:
        workspace.close()


def run_pass(
    home: Path,
    config: WorkerConfig,
    events: list[dict],
    *,
    client=None,
    models=None,
    initial_queue: set[Path] | None = None,
) -> dict:
    if not config.generation.enabled:
        return {"state": "disabled", "reader_available": True}
    ensure_layout(home)
    store = Store(home / "state.sqlite")
    try:
        recover_publication(home, store)
        effective = None
        if client is None:
            manager = ServerManager(config.api)
            with manager as api:
                inputs, citations = collect_inputs(api, store, config, home, events, time.time())
                version = api.server_version
                if models is None:
                    effective = api.get("/api/v1/config")
        else:
            inputs, citations = collect_inputs(client, store, config, home, events, time.time())
            version = getattr(client, "server_version", "test")
            if models is None:
                effective = client.get("/api/v1/config")
        budget = CallBudget(
            store,
            daily=config.generation.max_daily_model_calls,
            per_run=config.generation.max_run_model_calls,
        )
        extraction, consolidation = models or (
            Model(
                config.extraction,
                budget=budget,
                input_limit=config.generation.max_input_tokens,
                effective=effective,
                kimi_command=config.api.kimi_command,
            ),
            Model(
                config.consolidation,
                budget=budget,
                input_limit=config.generation.max_input_tokens,
                effective=effective,
                kimi_command=config.api.kimi_command,
            ),
        )
        results = []
        if inputs:
            extraction.ready()
            with ThreadPoolExecutor(max_workers=config.generation.extraction_concurrency) as pool:
                futures = [
                    pool.submit(extract_one, t, store, config, extraction, home) for t in inputs
                ]
                for future in futures:
                    results.append(future.result())
        if initial_queue is not None and set(queue_entries(home)) - initial_queue:
            return {
                "state": "pending_citations",
                "reader_available": True,
                "extractions": results,
                "reason": "New hook events arrived; retention waits for their next sync",
            }
        pruned = store.prune(
            cutoff=time.time() - config.generation.retention_days * 86400,
            limit=config.generation.prune_batch_size,
        )
        publication = phase_two(
            store,
            config,
            home,
            consolidation,
            can_publish=lambda: (
                initial_queue is None or not (set(queue_entries(home)) - initial_queue)
            ),
        )
        return {
            "state": "ready",
            "reader_available": True,
            "server_version": version,
            "extractions": results,
            "citations_counted": citations,
            "pruned": pruned,
            "publication": publication,
            "model_calls": budget.calls,
            **store.stats(),
        }
    finally:
        store.close()


def run(home: Path | None = None, *, drain: bool = False) -> dict:
    home = home or memory_home()
    try:
        with file_lock(home / "worker.lock"):
            for _ in range(4 if drain else 1):
                config = None
                files = queue_entries(home)
                events = []
                for path in files:
                    try:
                        event = read_json(path, 4096)
                        if isinstance(event, dict):
                            events.append(event)
                    except (OSError, ValueError):
                        continue
                try:
                    config = load_worker_config(home)
                    result = run_pass(home, config, events, initial_queue=set(files))
                except Exception as exc:
                    result = {
                        "state": "pending_citations"
                        if isinstance(exc, ResyncRequired)
                        else "paused",
                        "reader_available": True,
                        "error_code": exc.code
                        if isinstance(exc, MemoryErrorBase)
                        else "internal_error",
                        "message": str(exc)
                        if isinstance(exc, MemoryErrorBase)
                        else "Worker failed; inspect local configuration and rerun doctor",
                    }
                result["updated_at"] = time.time()
                if result["state"] == "paused":
                    result["retry_at"] = time.time() + (
                        config.generation.retry_delay_seconds if config is not None else 60
                    )
                write_json(home / "worker-status.json", result)
                if result["state"] in {"ready", "disabled", "pending_citations"}:
                    for path in files:
                        path.unlink(missing_ok=True)
                if not drain or result["state"] == "paused" or not queue_entries(home):
                    return result
            return result
    except BusyError:
        return {"state": "already_running", "reader_available": True}

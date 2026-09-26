"""Generation orchestration. Importing/starting this is never necessary to read memory."""

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from .config import WorkerConfig, load_worker_config
from .errors import (
    BusyError,
    MemoryErrorBase,
    ModelError,
    ResyncRequired,
    UnsafePathError,
)
from .evidence import budget_evidence, normalize, redact
from .extraction_output import EXTRACTION_TOOL, extraction_tool, parse_extraction
from .files import file_lock, memory_home, read_json, utf8_middle, write_json
from .issues import Issues
from .kimi import Transcript
from .models import CallBudget, Model
from .scan import allowed, clean_events, collect_inputs
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


def queue_entries(home: Path) -> list[Path]:
    return sorted((home / "queue").glob("*.json"))


def extract_one(
    transcript: Transcript,
    store: Store,
    config: WorkerConfig,
    model,
    home: Path,
    *,
    allow_removal=None,
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
                "{{ session_id }}": transcript.source.id,
                "{{ session_cwd }}": transcript.source.cwd,
                "{{ session_git_branch }}": "unknown; rely only on conversation evidence",
                "{{ session_contents }}": contents,
            }
            for old, new in replacements.items():
                template = template.replace(old, new)
            response = model.complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": redact(template)},
                ],
                tools=[extraction_tool()],
                output_tool=EXTRACTION_TOOL,
            )
            output = parse_extraction(response)
            summary, slug = (
                redact(output["rollout_summary"].strip()),
                output["rollout_slug"].strip(),
            )
            summary = utf8_middle(summary, gen.max_rollout_summary_bytes)
            if len(slug.encode()) > 256:
                raise ModelError("Extracted slug exceeds its byte limit")
            if not summary and slug:
                raise ModelError("Empty extraction must also have an empty slug")
        if (
            not summary
            and store.has_summary(transcript.source.id)
            and allow_removal is not None
            and not allow_removal()
        ):
            raise ResyncRequired(
                "An empty replacement waits for a complete citation synchronization"
            )
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


def phase_two(
    store: Store,
    config: WorkerConfig,
    home: Path,
    model,
    *,
    can_publish=None,
    preserve_sources: bool = False,
    issues: Issues | None = None,
) -> str:
    gen = config.generation
    issues = issues if issues is not None else Issues()
    rows = store.selected(
        cutoff=time.time() - gen.retention_days * 86400,
        limit=gen.max_consolidation_sources,
        accept=lambda row: allowed(row["source_id"], row["cwd"], config),
        preserve=preserve_sources,
    )
    workspace = Workspace(home, rows, gen, issues=issues)
    owner = None
    try:
        meaningful_inputs = rows or any(
            name != "extensions/ad_hoc/instructions.md" for name in workspace.files
        )
        if (preserve_sources or issues.count) and not meaningful_inputs:
            return "preserved"
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
            if not meaningful_inputs:
                workspace.execute("read_file", {"path": "phase2_workspace_diff.md"})
                workspace.execute("write_summary", {"content": MINIMAL_SUMMARY})
            else:
                model.ready()
                consolidate_agent(workspace, model)
        if workspace.removes_sources and can_publish is not None and not can_publish():
            raise ResyncRequired(
                "New activity arrived before source removal; retained memory waits for synchronization"
            )
        generation = workspace.publish(store, owner)
        try:
            prune_generations(home, gen.retained_generations, issues=issues)
        except OSError as exc:
            issues.add("generation_cleanup", exc)
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
    acknowledged: set[str] | None = None,
) -> dict:
    if not config.generation.enabled:
        return {"state": "disabled", "reader_available": True}
    ensure_layout(home)
    store = Store(home / "state.sqlite")
    issues = Issues()

    def pending():
        return initial_queue is not None and bool(set(queue_entries(home)) - initial_queue)

    try:
        recover_publication(home, store)
        store.prepare_extraction_requester(__version__, config.generation.max_extraction_attempts)
        effective = None
        if client is None:
            manager = ServerManager(config.api)
            with manager as api:
                scan = collect_inputs(api, store, config, home, events, time.time(), issues)
                version = api.server_version
                if models is None:
                    try:
                        effective = api.get("/api/v1/config")
                    except MemoryErrorBase as exc:
                        # The local Kimi config remains the default resolver; never
                        # switch providers merely because the read-only server exited.
                        issues.add("model_config", exc)
            if manager.cleanup_error:
                issues.add("helper_cleanup", manager.cleanup_error)
        else:
            scan = collect_inputs(client, store, config, home, events, time.time(), issues)
            version = getattr(client, "server_version", "test")
            if models is None:
                try:
                    effective = client.get("/api/v1/config")
                except MemoryErrorBase as exc:
                    issues.add("model_config", exc)
        if acknowledged is not None:
            acknowledged.update(scan.acknowledged)
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
        if scan.inputs:
            try:
                extraction.ready()
            except (MemoryErrorBase, OSError, ValueError) as exc:
                issues.add("extraction_config", exc)
                results.extend("failed" for _ in scan.inputs)
            else:
                with ThreadPoolExecutor(
                    max_workers=config.generation.extraction_concurrency
                ) as pool:
                    futures = [
                        (
                            t.source.id,
                            pool.submit(
                                extract_one,
                                t,
                                store,
                                config,
                                extraction,
                                home,
                                allow_removal=lambda: scan.complete and not pending(),
                            ),
                        )
                        for t in scan.inputs
                    ]
                    for source_id, future in futures:
                        try:
                            results.append(future.result())
                        except sqlite3.Error:
                            raise  # Global storage failure is not a bad session.
                        except Exception as exc:
                            issues.add("extraction", exc, source_id)
                            results.append("failed")
        preserve = not scan.complete or pending()
        publication = phase_two(
            store,
            config,
            home,
            consolidation,
            can_publish=lambda: scan.complete and not pending(),
            preserve_sources=preserve,
            issues=issues,
        )
        retention_deferred = preserve or pending()
        pruned = 0
        if not retention_deferred:
            pruned = store.prune(
                cutoff=time.time() - config.generation.retention_days * 86400,
                limit=config.generation.prune_batch_size,
            )
        return {
            "state": "degraded" if issues.count else "ready",
            "reader_available": True,
            "server_version": version,
            "extractions": results,
            "citations_counted": scan.citations,
            "missing_sessions": scan.missing,
            "retention_deferred": bool(retention_deferred),
            "issues": issues.summary(),
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
                events_by_path = {}
                for path in files:
                    try:
                        events = clean_events([read_json(path, 4096)], time.time())
                        if events:
                            events_by_path[path] = events[0]
                    except (OSError, ValueError):
                        continue
                try:
                    acknowledged: set[str] = set()
                    config = load_worker_config(home)
                    result = run_pass(
                        home,
                        config,
                        list(events_by_path.values()),
                        initial_queue=set(files),
                        acknowledged=acknowledged,
                    )
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
                result["worker_version"] = __version__
                if result["state"] == "paused":
                    result["retry_at"] = time.time() + (
                        config.generation.retry_delay_seconds if config is not None else 60
                    )
                write_json(home / "worker-status.json", result)
                if result["state"] in {"ready", "degraded", "disabled", "pending_citations"}:
                    for path in files:
                        event = events_by_path.get(path)
                        if (
                            event is not None
                            and result["state"] != "disabled"
                            and event["session_id"] not in acknowledged
                        ):
                            continue
                        try:
                            path.unlink(missing_ok=True)
                        except OSError:
                            pass  # A locked notification is safely replayable.
                if (
                    not drain
                    or result["state"] == "paused"
                    or not (set(queue_entries(home)) - set(files))
                ):
                    return result
            return result
    except BusyError:
        return {"state": "already_running", "reader_available": True}

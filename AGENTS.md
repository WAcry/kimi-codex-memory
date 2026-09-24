# Project rules

Read all accepted documents under `docs/adr/` before changing behavior. Read the
relevant `docs/design/` document before changing a subsystem. ADRs capture user
decisions, not implementation guesses: do not reverse them as an incidental refactor.

Documentation has four audiences. Keep README.md strictly user-facing: onboarding,
configuration, everyday recipes, and troubleshooting. Put mandatory agent rules here;
non-inferable user decisions in numbered ADRs; architecture and tradeoffs in DESIGN
documents. Do not turn README into an implementation inventory.

- Reader/hooks must remain usable when worker configuration, SQLite, API, credentials, or model generation fail. Never import worker/model/API modules on the reader hot path.
- Only memory v2 and the current Kimi transcript contract are supported. Try new host versions against the actual contract; never require exact version equality. Do not add legacy JSONL readers or v1 fallbacks.
- Never read or change real user sessions/credentials in tests. Use temporary homes and local fake HTTP servers. Never call paid models in tests.
- Do not change the sibling Kimi Code or Codex repositories. Vendor original prompt files unchanged; record their source commit and hashes. Adapt at runtime with documented replacements.
- Keep source history out of durable state. Persist only summaries, metadata, jobs, citation receipts, and bounded operational state.
- Default to Kimi's effective default model/authentication. Support Chat Completions, Anthropic and Responses, not Gemini. Honor configured context caps; unknown windows fall back to 256,000 tokens.
- Do not reintroduce inject_every_prompt or refresh_on_change. The reader injects a session snapshot, independent of generation health.
- Match Codex full-context boundaries: an absent summary still completes the initial check; first publication and ordinary resume do not trigger reinjection. Compaction does. See ADR 0006 for the Kimi timing limitation.
- Do not probe Kimi with --version before launching a helper or reject a running helper because the installed product version changed. Reuse healthy connections and release owned helpers after the batch. Set the auto-update opt-out before background Kimi process entry, never in user configuration.
- Ship self-contained native-plugin artifacts for Windows, macOS and Linux. Python/Node build tools are developer dependencies, not end-user prerequisites. No PyPI publishing.
- Never update Kimi itself. Plugin upgrades are owned by Kimi's plugin manager. Persist user data outside the installed plugin; preserve old published files during migration/failure.
- Version 1.0.0 is the first public compatibility baseline. Do not add pre-1.0 product-name, directory, configuration, database, publication-pointer or injection-receipt migrations. Defaults use only `.kimi-codex-memory`; no automatic adoption of development data.
- Preserve 1.0.0+ user data and documented configuration across compatible releases. Keep schema/file-format versions independent of product versions; future schema changes require tested, backed-up migrations from published baselines, never silent reset/downgrade. Keep the release-v1 fixture immutable and test it against future changes.
- Never treat incomplete/unrecognized history as empty history. Failed citation synchronization prohibits destructive retention/publication.
- Only manage child servers started by this worker. Preserve user-owned servers and token files; use authenticated loopback HTTP without redirects.
- Use `uv sync --locked --group dev --default-index https://pypi.org/simple`, then `.venv/bin/python -m pytest`, `.venv/bin/ruff check .`, and `.venv/bin/ruff format --check .` before committing. Use focused conventional commits and no co-author trailers.
- The optional native-server tests require `KIMI_MEMORY_NATIVE_KIMI=/absolute/path/to/kimi`. They must run in test-owned temporary Kimi homes with credentials removed and must never send a prompt to a paid model. A mock-server pass is not proof of native integration.
- Do not assume the native instance-registry ID equals `/meta.server_id`: the pinned Kimi build generates these independently. Preserve this regression coverage.

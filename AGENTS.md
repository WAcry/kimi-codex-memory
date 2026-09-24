# Project rules

- Reader/hooks must remain usable when worker configuration, SQLite, API, credentials, or model generation fail. Never import worker/model/API modules on the reader hot path.
- Only memory v2 and the pinned current Kimi transcript contract are supported. Do not add legacy JSONL readers or v1 fallbacks.
- Never read or change real user sessions/credentials in tests. Use temporary homes and local fake HTTP servers. Never call paid models in tests.
- Do not change the sibling Kimi Code or Codex repositories. Vendor original prompt files unchanged; record their source commit and hashes. Adapt at runtime with documented replacements.
- Keep source history out of durable state. Persist only summaries, metadata, jobs, citation receipts, and bounded operational state.
- Never treat incomplete/unrecognized history as empty history. Failed citation synchronization prohibits destructive retention/publication.
- Only manage child servers started by this worker. Preserve user-owned servers and token files; use authenticated loopback HTTP without redirects.
- Run `python3 -m pytest`, `ruff check .`, and `ruff format --check .` before committing. Use focused conventional commits and no co-author trailers.

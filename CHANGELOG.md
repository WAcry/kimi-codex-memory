# 1.0.5

- Accept the last valid submit_memory_extraction call instead of rejecting an
  otherwise usable response with multiple calls. Invalid or unrelated later
  calls cannot hide an earlier valid submission.
- When no valid submission exists, select the largest complete, schema-valid
  JSON object from final answer text. Measure the original object's UTF-8 bytes;
  prefer the later object on a size tie. Never use reasoning or repair JSON.
- Apply the same schema, Unicode, slug and empty-result checks before selection.
  Truncated responses and invalid results still preserve existing memories and
  use per-source retries. No schema, configuration or reader migration required.
- Add three-protocol streaming and frozen-package tests for corrected tool calls,
  final-output fallback, channel isolation and unchanged batch progress.

# 1.0.4

- Submit extraction results through one terminal submit_memory_extraction tool,
  using Codex v2's two required string fields. Never parse answer prose or
  reasoning as the extraction result; valid tool arguments finish the job without
  a follow-up model call.
- Keep native Kimi streaming/tool/thinking handling for all three protocols.
  Default to auto for gateway compatibility; direct official OpenAI endpoints
  additionally enforce strict arguments, required tool use and no parallel calls.
- Validate complete tool calls, field types, duplicate keys and completion state.
  Bad submissions retain old memories, use existing bounded retries, and do not
  block other sources. No configuration or stored-data migration is needed.
- Add split-argument stream, strict wire-format, reasoning separation and
  frozen-package regressions across Chat, Responses and Anthropic.

# 1.0.3

- Keep SDK debug logging disabled inside the private native-request pipe. User
  OPENAI_LOG/ANTHROPIC_LOG settings must not contaminate replies or emit request
  bodies. Includes all session-isolation and native-requester changes in 1.0.2.

# 1.0.2

- Isolate missing, archived, malformed or concurrently changed sessions at every
  history-read boundary, including native HTTP-200 not-found envelopes. Keep
  useful work when one source, citation timestamp, extraction or note fails.
- Preserve the prior selected memories and defer expiration when citation
  coverage is incomplete; healthy sources and explicit notes can still merge.
  New activity no longer blocks non-evicting publication.
- Use validated snapshots during model work, acknowledge queue items per source,
  and make cleanup failures non-fatal after a successful publication.
- Reuse pinned native Kimi Chat/Responses/Anthropic streaming requesters, thinking
  configuration and message codecs instead of separate Python wire adapters.
  Final extraction accepts exact JSON or one complete JSON fence, never thoughts.
- New requester versions rearm failed extraction budgets once without regenerating
  successful memories. Existing configuration, database and published data remain
  compatible; failures never disable the offline reader.

# 1.0.1

- Before the first usable memory summary, inject only short explicit-note
  guidance at the normal initial input boundary. Existing summaries still use
  the unchanged full prompt; no duplicate static instructions or late injection.
- Verify the actual system/instructions and user-hook roles for Chat
  Completions, Responses and Anthropic using native Kimi and local test models.
- Skip queued events whose session has been deleted, instead of crashing the
  worker into a retrying pause that stalls the whole batch.

# 1.0.0

First public release of Kimi Codex Memory.

- Self-contained Kimi plugin for Windows, macOS and Linux, on x64 and ARM64.
- Uses Kimi's effective default model and credentials: subscription OAuth or
  third-party providers with Chat Completions, Responses or Anthropic Messages.
- Codex memory-v2 extraction, consolidation, citation accounting and retention,
  with pristine upstream prompts pinned and minimal Kimi-specific templates.
- Offline memory remains readable when generation, authentication or the host
  history API fails. Injection follows initial-context and compaction boundaries.
- One self-contained hook prompt, without duplicate plugin system instructions.
  Custom SYSTEM.md templates do not need to include plugin sections. Silent
  no-op hooks add no empty JSON messages to the model's conversation.
- Source summaries and indexes use session_id consistently; the citation prompt
  explicitly maps that header value to the source-ID field.
- Tries new Kimi releases against the actual API without a product-version
  whitelist, and never upgrades Kimi on the user's behalf.

Version 1.0.0 establishes the public configuration and data-compatibility
baseline. Development-only rename, configuration, database and publication
migrations have been removed. Future compatible releases preserve 1.0.0+ user
data; necessary schema changes will include tested migration and recovery.

This is an independent project, not an official Moonshot or OpenAI product.
Generation uses the selected provider's quota.

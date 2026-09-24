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

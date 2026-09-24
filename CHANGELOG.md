# 1.0.0

First public release of Kimi Codex Memory.

- Self-contained Kimi plugin for Windows, macOS and Linux, on x64 and ARM64.
- Uses Kimi's effective default model and credentials: subscription OAuth or
  third-party providers with Chat Completions, Responses or Anthropic Messages.
- Codex memory-v2 extraction, consolidation, citation accounting and retention,
  with the original prompts pinned and verified.
- Offline memory remains readable when generation, authentication or the host
  history API fails. Injection follows initial-context and compaction boundaries.
- Tries new Kimi releases against the actual API without a product-version
  whitelist, and never upgrades Kimi on the user's behalf.

Version 1.0.0 establishes the public configuration and data-compatibility
baseline. Development-only rename, configuration, database and publication
migrations have been removed. Future compatible releases preserve 1.0.0+ user
data; necessary schema changes will include tested migration and recovery.

This is an independent project, not an official Moonshot or OpenAI product.
Generation uses the selected provider's quota.

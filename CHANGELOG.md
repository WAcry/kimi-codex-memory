# 0.2.1

Memory injection now follows the verified Codex v2 context boundaries. First
publication no longer inserts memory into an ongoing conversation; ordinary
resume keeps the existing context. Compaction still restores memory at Kimi's
next supported input boundary. Empty initial memory does not inject an empty
memory prompt, and regular turns do not reload the summary.

Kimi upgrades no longer trigger a preliminary version probe or a false
startup-version mismatch. Healthy helpers finish their current batch, missing
launcher hints fall back to PATH, and owned process trees are cleaned up.
Background hook launches set the auto-update opt-out before Kimi starts, without
changing the user's update settings.

# 0.2.0

Kimi Codex Memory installs as a self-contained Kimi plugin on Windows, macOS and
Linux. It inherits the current Kimi default model and authentication, including
subscription OAuth, third-party providers, and OpenAI Responses. No Python, Node
installation, separate API key or memory configuration is required.

Memory v2 prompts remain pinned to the upstream originals. Model budgets honor
the user's configured context window; an unknown window falls back to 256,000
tokens. Repeated per-prompt and change-triggered injection options are removed.

New Kimi versions are tried against the actual API contract, not rejected by a
version whitelist. Quota, authentication and generation failures remain quiet
and never disable existing memory. Failed work is retained with bounded backoff.

Updates use Kimi's plugin manager and never update Kimi itself. User data remains
outside the plugin; database upgrades are backed up and published snapshots stay
readable without the worker. The old development data directory is preserved.

This is an independent integration, not an official Moonshot or OpenAI product.
Generation uses the configured provider's quota.

# Public 1.0.0 compatibility baseline

Synthetic data produced by 1.0.0, never copied from a user. `state.sql` is a
portable SQLite dump with schema version 1. `home/` contains a published memory
snapshot, one explicit note, configuration overrides and an injection receipt.

After release, do not regenerate this fixture to make an incompatible change
pass. Future releases must read/migrate a copy while preserving the supported
configuration, memory, note and receipt semantics. Add separate fixtures when
a new public data format is deliberately released.

ADR 0008 records the owner's explicit one-time authorization to replace the
unused 1.0.0 release before adoption. This final fixture uses session_id in
source headers and memory indexes; it is the baseline frozen by that release.

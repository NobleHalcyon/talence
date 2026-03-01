# User Settings Subsystem (Planned)

Settings are stored in the database and are loaded by authenticated user context.

Settings must not violate determinism:
- Settings may influence *future* runs.
- Once a run begins, any run-scoped snapshots (operator config, bin config, pricing snapshot) must be treated as immutable for the duration of that run.

---

## Scope

- Settings are user-scoped by default.
- Some settings may later support collection-level overrides (policy-oriented features), but user defaults remain authoritative unless explicitly overridden.

---

## Examples (non-exhaustive)

- run_history_retention_count (default 5, max 100)

Purge / policy defaults:
- purge_enabled (default false)
- purge_copy_threshold (default 4)

Value tier thresholds (example):
- value_tier_thresholds (e.g. 4000, 2000 cents)

Future:
- protected_card_list
- pinned_bin_profiles
- collection_overrides

---

END OF USER SETTINGS SPEC
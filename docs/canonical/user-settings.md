# User Settings Subsystem (Planned)

Settings are user-scoped and stored in DB.

Examples:

- run_history_retention_count (default 5, max 100)
- purge_enabled
- purge_copy_threshold (default 4)
- value_tier_thresholds (e.g. 4000, 2000 cents)
- protected_card_list (future)

Settings must not affect deterministic guarantees.
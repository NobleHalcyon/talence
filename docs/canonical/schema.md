# Talence Schema Contract

SQLite is authoritative persistence layer.

Required Tables (M0 baseline):

- users
- refresh_tokens
- runs
- run_cards
- movement_plans
- planned_moves

Pricing Additions (M2+):

- printings
- run_price_snapshot

Rules:

- foreign_keys = ON (application connection)
- journal_mode = WAL
- No feature may rely on in-memory operational state.
- Schema changes require Canonical version bump.
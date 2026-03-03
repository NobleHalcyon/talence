# Talence Schema Contract

SQLite is the authoritative persistence layer.

This document defines required schema surfaces through M2.

---

## M0/M1 Required Tables

Authentication:
- `users`
- `auth_sessions`

Collections:
- `games`
- `collections`

Robot runtime:
- `runs`
- `run_cards`
- `movement_plans`
- `planned_moves`
- `move_events`

---

## M2 Catalog Tables

- `catalog_sets`
  - `set_code` PK
  - Scryfall set metadata
  - `raw_json` retained

- `catalog_prints`
  - `print_id` PK
  - print-level metadata and image URLs
  - `raw_json` retained

- `sync_state`
  - one row per sync source
  - cursor/status/row counts/error tracking

- `catalog_audit_log`
  - append-only sync/bootstrap audit events

---

## M2 Pricing Tables

- `prices_current`
  - mutable latest known price by `print_id`
  - overwritten by subsequent refresh/fetch

- `run_price_snapshots`
  - immutable run-scoped price snapshot
  - PK `(run_id, print_id)`
  - source/fetched timestamp captured per print

Snapshot invariants:
- Snapshot capture occurs as run enters `PLANNED`.
- Snapshot insert uses `ON CONFLICT DO NOTHING`.
- Planning must fail if snapshot is incomplete for run print_ids.
- After capture, run behavior must not depend on later changes in `prices_current`.

---

## M2 Image Cache Table

- `print_face_images`
  - metadata for cached print face images
  - content-addressed path uses sha256 shard model
  - `phash` is nullable and remains `NULL` in M2

Path invariant:
- `data/images/{sha256[0:2]}/{sha256[2:4]}/{sha256}.jpg`

---

## M2 Collection Consolidation Tables

- `collection_cards`
  - quantity by `(collection_id, print_id)`

- `collection_consolidations`
  - ledger row per consolidated `run_id`
  - enforces idempotent consolidation

Consolidation invariant:
- A run can be consolidated at most once.
- Repeated consolidation calls are no-op.

---

## Global DB Rules (Binding)

- `PRAGMA foreign_keys = ON` at connection setup.
- `PRAGMA journal_mode = WAL`.
- No replacement of sqlite3 runtime.
- No hidden in-memory operational dependencies for lifecycle state.

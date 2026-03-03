# TALENCE ARCHITECTURE SPEC

Version: v0.8.0
Last Updated: 2026-03-03
Impact Level: Minor
Change Summary:
- Added M2 Catalog subsystem architecture
- Added deterministic run pricing snapshot model
- Added hash-sharded image cache model
- Added collection consolidation ledger model

---

## 1. System Identity

Talence is a deterministic collection intelligence system with optional robotic execution.

Core flow:
- Scan -> Plan -> Execute

Talence is:
- Deterministic
- LIFO-aware
- Restart-safe
- SQLite authoritative

Talence is not:
- Streaming sort into final bins
- Probabilistic planning
- Hidden in-memory operational state

---

## 2. Non-Negotiable Invariants

- SQLite runtime only, WAL enabled, foreign keys enforced.
- Runs use explicit lifecycle states and persisted transitions.
- Bins are LIFO stacks.
- Unrecognized bin is never used for staging.
- Sorting uses aggregate composite key across enabled operators in order.
- Alphabetical deep sort uses full-string ordering.
- Run snapshots are immutable once captured.

---

## 3. Governance Authority

This document is canonical architecture authority.
Architectural changes require a version increment.

---

## 4. Milestones

Milestones are authoritative in `docs/canonical/milestones.json`.

- M0: Deterministic Core (Ratified)
- M1: Deterministic Robot Runtime (Ratified)
- M2: Collection Intelligence Interface (In Progress)

---

## 5. M2 Catalog Subsystem

The Catalog subsystem is independent from run lifecycle mutation and includes:

- Bulk bootstrap ingest from Scryfall bulk data
- Startup set delta check (best-effort, non-blocking)
- Upsert-based catalog persistence with raw payload retention
- Sync state and audit log tracking

Primary tables:
- `catalog_sets`
- `catalog_prints`
- `sync_state`
- `catalog_audit_log`

Rules:
- Ingest uses explicit transactions.
- Upserts use `INSERT ... ON CONFLICT DO UPDATE`.
- Bootstrap ingest is idempotent.
- Network failures in startup set-check must not block app boot.

---

## 6. Pricing Determinism Model

During SCANNING:
- Maintain in-memory cache keyed by `(run_id, print_id)`.
- Pull/fetch price once per print per run.
- Upsert latest value into `prices_current`.

At transition to PLANNED:
- Auto-capture `run_price_snapshots` for all run print_ids.
- Snapshot uses `ON CONFLICT DO NOTHING`.
- Planning is blocked if snapshot is incomplete.

After snapshot exists:
- Planner/execution must read snapshot state, not mutable current-price state.
- `prices_current` changes do not alter captured run snapshot.

---

## 7. Image Caching System

Image cache is content-addressed and hash-sharded:

- Path: `data/images/{sha256[0:2]}/{sha256[2:4]}/{sha256}.jpg`
- Metadata persisted in `print_face_images`
- `phash` remains `NULL` in M2

Rules:
- Cache writes are idempotent for the same `(print_id, face_key)`.
- Directory creation is automatic.

---

## 8. Collection Consolidation Ledger

Consolidation persists run cards into collection inventory with idempotency.

Tables:
- `collection_cards` (authoritative quantity by collection/print)
- `collection_consolidations` (ledger; one row per consolidated run)

Rules:
- If a run already exists in ledger, consolidation is a no-op.
- First consolidation folds run card quantities into collection quantities.
- Double-consolidation must not double-add.

---

## 9. Run Lifecycle States

Allowed states:
- `IDLE`
- `SCANNING`
- `HOLDING_READY`
- `PLANNED`
- `EXECUTING`
- `COMPLETE`
- `FAILED`

M2 does not alter lifecycle statuses or transition semantics.

---

## 10. Amendments Ledger

- v0.3.0 - Milestone realignment
- v0.4.0 - Sort operator contract and virtual bins
- v0.5.0 - Pricing and tier boundary preservation
- v0.6.0 - Run-scoped price snapshot persistence
- v0.7.0 - Identity taxonomy and collection-aware purge scope
- v0.8.0 - M2 catalog, deterministic snapshot flow, image cache, consolidation ledger

---

END OF ARCHITECTURE SPEC

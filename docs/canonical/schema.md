# Talence Schema Contract

SQLite is the authoritative persistence layer.

This document defines the minimum required schema surfaces by milestone.
If a table or contract is not defined here (or in Canonical with a version bump),
it must not be assumed.

---

## Required Tables (M0 baseline)

Authentication / identity:
- users
- auth_sessions

Collections:
- games
- collections

Robot runtime:
- runs
- run_cards
- movement_plans
- planned_moves
- move_events

Notes:
- `runs` is the operational unit of work and references a `collection_id`.
- `run_cards` are cards observed during a run and are identified by:
  - oracle_id (card identity)
  - print_id (printing identity)
  - instance_id (physical copy UUID)

---

## Collection Inventory (M2+)

To support multi-run sorting correctness (including purge evaluation, deck availability,
and analytics), Talence introduces a collection-level inventory substrate.

Required:
- collection_inventory

Suggested shape:
- collection_inventory
  - collection_id TEXT NOT NULL
  - print_id TEXT NOT NULL
  - finish TEXT NOT NULL            -- e.g. "nonfoil" | "foil"
  - count INTEGER NOT NULL
  - updated_at TEXT NOT NULL
  - UNIQUE(collection_id, print_id, finish)

Optional acceleration table (not required):
- collection_oracle_inventory
  - collection_id TEXT NOT NULL
  - oracle_id TEXT NOT NULL
  - count INTEGER NOT NULL
  - updated_at TEXT NOT NULL
  - UNIQUE(collection_id, oracle_id)

---

## Pricing Tables (M2+)

- printings
  - print_id
  - oracle_id
  - finish availability and metadata
  - price_usd_cents
  - price_usd_foil_cents
  - price_updated_at
  - price_source

- run_price_snapshot
  - run_id
  - print_id
  - price_usd_cents
  - price_usd_foil_cents
  - source
  - fetched_at
  - UNIQUE(run_id, print_id)

Rules:
- The printings table represents "current truth" and may be overwritten by refresh.
- The run_price_snapshot is immutable during the run once persisted.

---

## Global Rules (Binding)

- PRAGMA foreign_keys = ON (application connection).
- PRAGMA journal_mode = WAL.
- No feature may rely on hidden in-memory operational state.
- Schema changes require Canonical version bump + migration.
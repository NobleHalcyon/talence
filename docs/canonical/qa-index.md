# Talence QA Index

This file is the canonical QA gate index for ratification.

---

## M0

- Script: `scripts/qa/m0.ps1`
- Coverage:
  - Auth issuance and refresh rotation
  - Run -> Plan -> Persist baseline
  - FK enforcement
  - WAL mode

---

## M1

- Automated:
  - `python -m pytest -q`
- Coverage:
  - Run lifecycle FSM constraints
  - Startup resume detection with no mutation
  - Planner determinism and operator semantics
  - Execution persistence and stop/resume behavior

---

## M2

- Automated:
  - `python -m pytest -q`
- Additional coverage expected:
  - Bulk bootstrap ingest is idempotent and auditable
  - Startup set check is non-blocking and fail-safe
  - Hash-sharded image caching correctness and idempotency
  - Run-scoped pricing snapshot determinism and immutability
  - Consolidation ledger idempotency and quantity correctness
  - No M0/M1 regressions

Ratification gate:
- CI must be green with all tests offline.

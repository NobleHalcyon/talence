# TALENCE ARCHITECTURE SPEC

Version: v0.6.0  
Last Updated: 2026-02-28  
Impact Level: Minor  
Change Summary:
- Milestone realignment
- Sort operator contract
- Virtual bin semantics
- Pricing provider abstraction
- Overwrite price storage
- Run-scoped price snapshot persistence

---

# 1. System Identity

Talence is a deterministic, value-aware collection intelligence platform
with an optional robotics execution layer.

Talence is not:
- A streaming sorter
- A probabilistic planner
- A non-deterministic execution system

Talence is:
- Scan → Snapshot → Plan → Execute
- Deterministic
- LIFO-aware
- Value-preserving

---

# 2. Non-Negotiable Invariants

- SQLite persistence with WAL enabled.
- Foreign keys enforced via application connection.
- No hidden in-memory operational dependencies.
- All runs must be restart-safe.
- Pricing used in a run must be immutable during execution.
- All physical bins are LIFO stacks.
- Unrecognized bin excluded from provisioning.

---

# 3. Governance Authority

This document is the sole architectural authority.

No version bump = no architectural change.

---

# 4. Milestone Ladder

## M0 — Deterministic Core (Ratified)

Includes:
- SQLite persistence foundation
- WAL mode
- FK enforcement
- Argon2 password hashing
- JWT (HS256) requiring TALENCE_JWT_SECRET
- Rotating refresh tokens
- Run persistence
- Plan persistence
- No hidden in-memory state
- CI passing

---

## M1 — Deterministic Robot Runtime

Objective:
Scan → Snapshot → Plan → Execute with value-aware routing.

Includes:
- Mandatory consolidation phase
- Run lifecycle state machine
- Physical execution loop
- Step reconciliation
- Safe stop
- Capacity-aware provisioning
- Hard pinned-bin constraints
- Oracle-based purge logic
- Per-print pricing snapshot
- Planner respects split + pinned + virtual bins
- Deterministic move minimization
- No remote start

---

## M2 — Collection Intelligence Layer

- Collection UI
- Daily pricing refresh
- Live fallback pricing
- CSV import
- Metrics
- Price timestamp tracking

---

## M3 — User Rule Engine

- Multi-tier thresholds
- Exemption lists
- Rule precedence
- Profile overrides
- Conflict resolution

---

## M4 — Vision Pipeline

- Image capture
- Hash comparison
- OCR fallback
- Confidence thresholds
- Retry loop
- Unrecognized routing

---

## M5 — Cloud Partitioning

- Strict user partitioning
- Remote robot handshake
- API deployment
- Auth hardening

---

# 5. Sort Operator Contract

Operator config fields:
- op
- enabled
- order
- deep
- split_into_bins

Precedence:
Enabled operators applied in ascending order.

Deep semantics:
- Alphabetical: full-string compare.
- Color / Color Identity: deterministic ordering.

Tie-breaker:
name → print_id → instance_id

Split rules:
- Alphabetical cannot split.
- Split operators must form prefix.
- Correctness overrides split.

---

# 6. Virtual Bin Semantics

If insufficient physical bins exist:

- Maintain logical virtual bins.
- Co-locate virtual bins into physical bins.
- Preserve contiguous tier segments.
- Higher priority segments stacked on top.
- No interleaving permitted.

---

# 7. Pricing & Identity Contract

Provider:
- Abstract interface
- Scryfall initial implementation

Price storage:
- Overwrite current price on printings table
- price_usd_cents
- price_usd_foil_cents
- price_updated_at
- price_source

Daily refresh:
- Bulk update of relevant printings

Live refresh:
- On-demand update
- Must not alter active run snapshot

---

# 8. Run Price Snapshot Contract

Each run must persist:

run_price_snapshot:
- run_id
- print_id
- price_usd_cents
- price_usd_foil_cents
- source
- fetched_at

UNIQUE(run_id, print_id)

Lookup order:
1. run snapshot
2. in-memory cache (priceDict)
3. live fetch

Once snapshot exists, it cannot change during run.

Restart must rehydrate from snapshot.

---

# 9. Run Lifecycle States

IDLE
SCANNING
HOLDING_READY
PLANNED
EXECUTING
COMPLETE
FAILED

Transitions must be explicit and persisted.

---

# 10. Bin Model

- 35 physical bins
- LIFO stacks
- Input bin (configurable)
- Unrecognized bin (excluded from provisioning)
- Holding bins dynamically assigned during consolidation
- Virtual bins supported via segment stacking

---

# 11. Security Model

- JWT access tokens
- Rotating refresh tokens
- Secret required in all environments
- FK enforcement mandatory
- WAL enabled

---

# 12. Amendments Ledger

v0.3.0 — Milestone Realignment  
v0.4.0 — Sort Operator Contract + Virtual Bins  
v0.5.0 — Pricing & Tier Boundary Preservation  
v0.6.0 — Run-Scoped Price Snapshot Persistence

---

END OF ARCHITECTURE SPEC
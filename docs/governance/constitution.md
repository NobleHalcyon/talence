# Talence Constitution

Talence development follows a structured governance model.

This document defines how architectural authority operates.

---

## 1. Canonical Authority

The file:

    /docs/canonical/architecture.md

is the sole source of architectural truth.

It defines:
- System identity
- Domain boundaries
- Persistence contracts
- Auth model
- Planner invariants
- Milestone definitions
- Architectural constraints

If a decision is not recorded there with a version increment,
it is not architecture.

---

## 2. Versioning Rules

Talence uses semantic versioning for architecture:

Major:
- Hosting model change
- Core data model restructuring
- Planner invariant shift
- Auth model change
- Offline/online contract change

Minor:
- New subsystem
- New persistence boundary
- Expanded architectural contract

Patch:
- Clarifications
- Constraint tightening
- Non-structural renames

No version bump = no architectural change.

---

## 3. Thread Taxonomy

CANONICAL
- Defines truth.
- Ratifies decisions.

DEV
- Implements against current Canonical version.

STRATEGY
- Proposes roadmap direction.
- Cannot ratify.

LAB
- Experimental.
- Nothing leaves Lab without explicit promotion.

SYNC
- Operational awareness only.
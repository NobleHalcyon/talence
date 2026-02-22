# TALENCE Governance Protocol

Talence is developed using a structured thread model to prevent architectural drift,
control scope, and maintain high velocity without bureaucratic overhead.

This document defines:
- Thread roles
- Ratification process
- Versioning rules
- Dev completion requirements
- Codex usage rules

---

# Thread Taxonomy

## TALENCE / CANONICAL

Role: Constitution / Project Authority  
Purpose: Holds all architectural decisions and non-negotiables.

Every message in Canonical must begin with:

Talence Architecture Spec  
Version: X.Y.Z  
Last Updated: YYYY-MM-DD  
Impact Level: Major | Minor | Patch | None  

Change Summary:
- ...

### Version Rules

Major:
- Hosting model changes
- Core data model restructuring
- Planner invariants change
- Auth model shift
- Offline/online contract changes

Minor:
- New subsystem added
- New persistence boundary
- Runtime topology adjusted
- Architectural extension

Patch:
- Clarifications
- Renames
- Constraint tightening
- No structural shift

None:
- Discussion only

Ratification = Version increment.
No version bump → no decision.

---

## TALENCE / SYNC

Role: State alignment / operational awareness  
No architectural decisions allowed.

Daily Sync Template:

Sync Against Canonical: vX.Y.Z  
Active Branches:  
Merged Since Last Sync:  
Server Running: Y/N  
DB State:  
CI State:  
Blockers:  
Today’s Goal:  

---

## TALENCE / DEV / TAL-XXX-<slug>

Role: Branch-scoped implementer  
1 thread = 1 branch = 1 feature

Required Initialization:

Branch:
Goal:
Definition of Done:
Touches Architecture? (Y/N)

Environment:
Repo root:
Python version:
Run command:
DB path:
PYTHONPATH set? (Y/N)

Scope Guard:
Any idea outside Goal must be labeled:
- Future Enhancement
- Canonical Impact
- Strategy Idea

Assumptions:
- ...

Blockers:
- None / ...

---

Dev Completion Protocol (required before merge)

DEV SUMMARY REPORT

Branch:
Commits:
Files Changed:
Dependencies Added:
Schema Changes:
Endpoints Added/Modified:
Migration Required? (Y/N)
Touches Architecture? (Y/N)

Manual Test Steps:
Result:

If Touches Architecture = Y → Canonical version bump required.

---

## TALENCE / STRATEGY

Role: Long-term product thinking

Template:

Hypothesis:
Expected ROI:
Dependencies:
Risks:
Proposed Canonical Change? (Y/N)

If Y → move to Canonical.

---

## TALENCE / LAB

Role: Experimental sandbox

Template:

Hypothesis:
Method:
Result:
Keep / Kill:
Promote to Canonical? (Y/N)

Nothing leaves Lab without promotion.

---

# Archival Policy

Dev threads are not deleted.
Mark completed ones:

[ARCHIVED] TALENCE / DEV / TAL-XXX-<slug>

Dev summary markdown file must be committed under:

/docs/dev-logs/TAL-XXX-<slug>.md

Full transcripts optional.

---

# Codex Usage Rules

Codex is senior implementer.

Dev thread must:
- Provide full context block
- Provide constraints
- Request full-file outputs
- Require dependency updates if imports change
- Avoid micro-step prompting

Atomic implementation passes preferred.
# Talence Thread Bootstrap Context

Talence is governed by `/docs/canonical/architecture.md`.

Canonical is binding.
No version bump = no architectural decision.

Thread Roles:

- CANONICAL
  Authority. Architecture only. Must follow versioning protocol.

- STRATEGY
  Roadmap and sequencing only. Cannot mutate architecture.

- DEV / TAL-XXX
  Branch-scoped implementation only. One thread = one feature branch.

- LAB
  Experimental sandbox. Nothing leaves Lab without explicit Canonical ratification.

- SYNC
  Operational reporting only.

Core Architectural Invariants:

- SQLite persistence (WAL, foreign_keys=ON via app connection)
- Deterministic planning
- No hidden in-memory operational state
- Auth required for all state mutations
- Rotating refresh tokens with reuse rejection
- Operator semantics defined in `/docs/canonical/operators.md`

When uncertain:
- Ask for clarification.
- Do not infer architectural intent.
- Do not expand scope.

Milestones are defined in `/docs/canonical/milestones.json`.

END BOOTSTRAP
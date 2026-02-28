# Talence Documentation

This directory contains the governing documents for Talence.

Talence operates under a structured governance model to prevent architectural drift,
preserve determinism, and maintain disciplined iteration.

## Binding Authority

The single source of architectural truth is:

    /docs/canonical/architecture.md

If a decision is not recorded there with a version increment,
it is not architecture.

## Folder Structure

/governance
    Constitution and ratification mechanics.

/canonical
    Binding architectural truth (monolithic).

/runbooks
    QA and operational procedures (non-architectural).

/roadmap
    Strategy and ordering (non-binding).

/context
    Bootstrapping context and glossary.

---

When starting a new GPT thread, provide:

    Operate strictly within /docs/canonical/architecture.md
    and /docs/governance.

Structure holds.
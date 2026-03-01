# Talence Sort Operators

Version: v0.6.0 (inherits Canonical)  
Last Updated: 2026-02-28  
Status: Binding (operator definitions and constraints)

This document defines the runtime-configurable sorting operators used to build the composite sort key for Talence runs.

---

## 1. Operator Model (Binding)

Each operator is configured at runtime as:

- `op` (enum/string)
- `enabled` (bool)
- `order` (int; lower executes earlier / higher precedence)
- `deep` (bool; operator-specific meaning)
- `split_into_bins` (bool; operator-specific eligibility)

### 1.1 Precedence
Enabled operators are applied in ascending `order` to build a composite sort key.

### 1.2 Deep Semantics (Binding)
Deep is supported for:
- Alphabetical
- Color
- Color Identity

Deep meanings:
- Alphabetical deep = full string ordering (not “first letter only”).
- Color / Color Identity deep = deterministic ordering inside buckets for multicolor / combinations.

### 1.3 Split Into Bins (Binding)
- `split_into_bins` **cannot** be applied to Alphabetical.
- `split_into_bins` may only be true as a **prefix** of enabled operators (no gaps).
  - Example valid: split on Color Identity + Set; not valid: split on Set but not on Color Identity if Color Identity precedes Set.
- `split_into_bins` is **not a hard requirement**. Correctness can override it if bins/capacity are insufficient.

---

## 2. Operator Set (Binding)

Canonical operator set for V1 planning:

1) `color_identity`
2) `color`
3) `alphabetical`
4) `rarity`
5) `set`
6) `value_tier`
7) `mana_value`

This list is the authoritative set unless Canonical is updated via version bump.

---

## 3. Operator Definitions

### 3.1 color_identity
**Purpose:** Groups by MTG color identity (Commander identity style).  
**Inputs:** card’s color identity flags (e.g., W/U/B/R/G).  
**Deep:** Yes  
- Deep ordering must deterministically order multi-color identities within the bucket space (e.g., stable ranking of combinations).  
**Split into bins:** Yes (eligible)

**Key segment output:** a stable, deterministic identity key.

---

### 3.2 color
**Purpose:** Groups by card color (mana symbol color, not identity).  
**Inputs:** card color flags (W/U/B/R/G / colorless).  
**Deep:** Yes  
- Deep ordering must deterministically order multi-color cases in a stable manner.  
**Split into bins:** Yes (eligible)

**Key segment output:** a stable, deterministic color key.

---

### 3.3 alphabetical
**Purpose:** Lexicographic ordering by name.  
**Inputs:** card name (canonical name string).  
**Deep:** Yes  
- Deep alphabetical = full-string ordering.  
**Split into bins:** **No** (ineligible; forbidden)

**Key segment output:** normalized name string key.

---

### 3.4 rarity
**Purpose:** Groups/sorts by rarity.  
**Inputs:** rarity enum (common/uncommon/rare/mythic/… as applicable).  
**Deep:** Not applicable (ignored if provided)  
**Split into bins:** Yes (eligible)

**Key segment output:** stable rarity rank.

---

### 3.5 set
**Purpose:** Groups/sorts by set / printing set family.  
**Inputs:** set code or set identifier from printing.  
**Deep:** Not applicable (ignored if provided)  
**Split into bins:** Yes (eligible)

**Key segment output:** stable set rank (or code ordering, deterministic).

---

### 3.6 value_tier
**Purpose:** Routes/sorts based on value thresholds (e.g., ≥$40, ≥$20, ≥$2), per printing and finish.  
**Inputs:**  
- `print_id`  
- finish (foil vs non-foil)  
- run price snapshot: `run_price_snapshot(run_id, print_id, price_usd_cents, price_usd_foil_cents, ...)`

**Deep:** Not applicable (ignored if provided)  
**Split into bins:** Yes (eligible)

**Tier boundary rule (Binding):**
When multiple tiers must co-locate into a physical bin, each tier must remain a contiguous segment (no interleaving). Higher tiers stack on top by default.

**Key segment output:** tier rank (e.g., 0 = highest tier).

---

### 3.7 mana_value
**Purpose:** Groups/sorts by mana value (CMC).  
**Inputs:** numeric mana value.  
**Deep:** Not applicable (ignored if provided)  
**Split into bins:** Yes (eligible)

**Key segment output:** integer MV.

---

## 4. Deterministic Tie-Breaker (Binding)

If all enabled operator segments tie, apply:

`name` → `print_id` → `instance_id`

This ensures stable sorting even for identical printings and repeated physical copies.

---

## 5. Notes on Future Extensions (Non-binding)

Additional operators (e.g., type, subtype, format legality, tags) may be added only via Canonical version bump.

END OF OPERATORS SPEC
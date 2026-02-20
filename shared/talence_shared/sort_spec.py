from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

class Operator(str, Enum):
    COLOR_IDENTITY = "color_identity"
    COLOR = "color"
    ALPHABETICAL = "alphabetical"
    RARITY = "rarity"
    SET = "set"
    MANA_VALUE = "mana_value"
    USER_VALUE_TIER = "user_value_tier"

@dataclass(frozen=True)
class OperatorConfig:
    op: Operator
    enabled: bool = True
    order: int = 0
    deep: bool = False
    split_into_bins: bool = False

@dataclass(frozen=True)
class SortSpec:
    operators: List[OperatorConfig]

    def enabled_in_order(self) -> List[OperatorConfig]:
        ops = [o for o in self.operators if o.enabled]
        return sorted(ops, key=lambda x: x.order)

def normalize_name(name: str) -> str:
    # Deterministic "deep" alpha: casefold + basic punctuation normalization.
    # Keep it simple v1; can improve later.
    return "".join(ch for ch in name.casefold().strip())

COLOR_BITS: Dict[str, int] = {"W": 1, "U": 2, "B": 4, "R": 8, "G": 16}

def color_key(colors: List[str], deep: bool) -> Tuple[int, int]:
    """
    Returns (bucket, deep_value)
    bucket: 0=land, 1=colorless, 2=mono, 3=multi
    deep_value: for multi, sum of bits; else 0 or bit.
    """
    if not colors:
        return (1, 0)  # colorless
    if len(colors) == 1:
        bit = COLOR_BITS.get(colors[0], 0)
        return (2, bit)
    # multicolor
    if deep:
        s = sum(COLOR_BITS.get(c, 0) for c in colors)
        return (3, s)
    return (3, 0)

def build_composite_key(card: Dict[str, Any], spec: SortSpec) -> Tuple:
    """
    card is a dict containing:
      name, rarity, set_code, mana_value, colors, color_identity, user_value_tier, is_land
    """
    key_parts: List[Any] = []
    for cfg in spec.enabled_in_order():
        if cfg.op == Operator.ALPHABETICAL:
            if cfg.deep:
                key_parts.append(normalize_name(card["name"]))
            else:
                # first-letter bucket (A-Z -> 0-25), non-letter -> 26
                n = normalize_name(card["name"])
                c = n[0] if n else ""
                if "a" <= c <= "z":
                    key_parts.append((ord(c) - ord("a")))
                else:
                    key_parts.append(26)
                # deterministic tie-breaker to keep stable ordering
                key_parts.append(normalize_name(card["name"]))
        elif cfg.op == Operator.COLOR:
            if card.get("is_land"):
                key_parts.append((0, 0))
            else:
                key_parts.append(color_key(card.get("colors", []), cfg.deep))
        elif cfg.op == Operator.COLOR_IDENTITY:
            if card.get("is_land"):
                key_parts.append((0, 0))
            else:
                key_parts.append(color_key(card.get("color_identity", []), cfg.deep))
        elif cfg.op == Operator.RARITY:
            # Define rarity order explicitly
            order = {"common": 0, "uncommon": 1, "rare": 2, "mythic": 3}
            key_parts.append(order.get(card.get("rarity", ""), 99))
        elif cfg.op == Operator.SET:
            key_parts.append(card.get("set_code", ""))
        elif cfg.op == Operator.MANA_VALUE:
            key_parts.append(float(card.get("mana_value", 0)))
        elif cfg.op == Operator.USER_VALUE_TIER:
            # Tier ordering: A < B < C ... configurable later
            tier = card.get("user_value_tier") or "Z"
            key_parts.append(tier)
        else:
            key_parts.append(None)
    # Final stable tiebreakers (important!)
    key_parts.append(card.get("oracle_id", ""))
    key_parts.append(card.get("print_id", ""))
    key_parts.append(card.get("instance_id", ""))
    return tuple(key_parts)

def validate_split_prefix_rule(spec: SortSpec) -> None:
    enabled = spec.enabled_in_order()
    seen_false = False
    for cfg in enabled:
        if cfg.op == Operator.ALPHABETICAL and cfg.split_into_bins:
            raise ValueError("split_into_bins cannot be enabled for alphabetical.")
        if seen_false and cfg.split_into_bins:
            raise ValueError("split_into_bins may only be true for a prefix of enabled operators (no gaps).")
        if not cfg.split_into_bins:
            seen_false = True

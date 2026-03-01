from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from talence_shared.sort_spec import SortSpec, build_composite_key, validate_split_prefix_rule


@dataclass
class SystemBins:
    input_bin: int
    unrecognized_bin: int


@dataclass
class BinCapacity:
    capacity_by_bin: Dict[int, int]  # e.g. {1:200, 2:200, ...}


@dataclass
class CardInstance:
    instance_id: str
    name: str
    oracle_id: str
    print_id: str
    identified: bool
    current_bin: int
    attrs: Dict[str, Any]  # colors, color_identity, rarity, set_code, mana_value, user_value_tier, is_land


@dataclass
class BinAssignment:
    instance_id: str
    dest_bin: int
    index_in_bin: int  # 0=top in final stack


@dataclass
class Move:
    seq: int
    from_bin: int
    to_bin: int
    instance_id: str


@dataclass
class MovementPlan:
    dest_sequences: Dict[int, List[str]]  # bin -> instance_ids in final top->bottom order
    moves: List[Move]
    notes: Dict[str, Any]


def _card_key(ci: CardInstance, sort_spec: SortSpec) -> Tuple:
    d = dict(ci.attrs)
    d.update(
        {
            "name": ci.name,
            "oracle_id": ci.oracle_id,
            "print_id": ci.print_id,
            "instance_id": ci.instance_id,
        }
    )
    return build_composite_key(d, sort_spec)


def _split_prefix_len(sort_spec: SortSpec) -> int:
    n = 0
    for cfg in sort_spec.enabled_in_order():
        if cfg.split_into_bins:
            n += 1
            continue
        break
    return n


def _group_segments(
    ordered_with_keys: List[Tuple[CardInstance, Tuple]],
    split_prefix_len: int,
) -> List[Tuple[Tuple[Any, ...], List[CardInstance]]]:
    if not ordered_with_keys:
        return []
    if split_prefix_len <= 0:
        return [(("__ALL__",), [ci for ci, _ in ordered_with_keys])]

    out: List[Tuple[Tuple[Any, ...], List[CardInstance]]] = []
    current_key: Tuple[Any, ...] | None = None
    current_cards: List[CardInstance] = []
    for ci, composite_key in ordered_with_keys:
        key = tuple(composite_key[:split_prefix_len])
        if current_key is None:
            current_key = key
            current_cards = [ci]
            continue
        if key == current_key:
            current_cards.append(ci)
            continue
        out.append((current_key, current_cards))
        current_key = key
        current_cards = [ci]
    if current_key is not None:
        out.append((current_key, current_cards))
    return out


def _coerce_pinned_bin(ci: CardInstance) -> int | None:
    pinned = ci.attrs.get("pinned_bin")
    if pinned is None:
        return None
    if isinstance(pinned, bool):
        raise RuntimeError(f"Invalid pinned_bin for card {ci.instance_id}: {pinned!r}")
    try:
        return int(pinned)
    except (TypeError, ValueError):
        raise RuntimeError(f"Invalid pinned_bin for card {ci.instance_id}: {pinned!r}")


def provision_bins(
    ordered_with_keys: List[Tuple[CardInstance, Tuple]],
    sort_spec: SortSpec,
    available_bins: List[int],
    capacities: BinCapacity,
) -> Tuple[Dict[int, List[str]], Dict[str, Any]]:
    """
    Deterministic provisioning with:
    - split-prefix logical segments
    - virtual segment co-location without interleaving
    - hard pinned-bin constraints
    - split override when pin constraints are present
    """
    bins = [b for b in available_bins if capacities.capacity_by_bin.get(b, 0) > 0]
    if not bins and ordered_with_keys:
        raise RuntimeError("Not enough bin capacity to provision all recognized cards.")

    cap_by_bin = {b: int(capacities.capacity_by_bin.get(b, 0)) for b in bins}
    if sum(cap_by_bin.values()) < len(ordered_with_keys):
        raise RuntimeError("Not enough bin capacity to provision all recognized cards.")

    pinned_by_instance: Dict[str, int] = {}
    pinned_totals = {b: 0 for b in bins}
    has_pinned = False
    for ci, _ in ordered_with_keys:
        pinned_bin = _coerce_pinned_bin(ci)
        if pinned_bin is None:
            continue
        if pinned_bin not in cap_by_bin:
            raise RuntimeError(
                f"Pinned bin {pinned_bin} for {ci.instance_id} is not provisionable."
            )
        has_pinned = True
        pinned_by_instance[ci.instance_id] = pinned_bin
        pinned_totals[pinned_bin] += 1

    for b, pinned_count in pinned_totals.items():
        if pinned_count > cap_by_bin[b]:
            raise RuntimeError(
                f"Pinned constraints exceed capacity for bin {b}: "
                f"required={pinned_count}, capacity={cap_by_bin[b]}"
            )

    requested_split = _split_prefix_len(sort_spec)
    effective_split = requested_split
    split_overridden = False
    split_override_reason = None
    if has_pinned and requested_split > 0:
        # Correctness may override split when hard pin constraints are present.
        effective_split = 0
        split_overridden = True
        split_override_reason = "pinned_constraints"

    segments = _group_segments(ordered_with_keys, effective_split)
    dest_sequences: Dict[int, List[str]] = {b: [] for b in bins}
    fill = {b: 0 for b in bins}

    if effective_split > 0:
        bin_idx = 0
        for _, segment_cards in segments:
            segment_pos = 0
            while segment_pos < len(segment_cards):
                while bin_idx < len(bins) and fill[bins[bin_idx]] >= cap_by_bin[bins[bin_idx]]:
                    bin_idx += 1
                if bin_idx >= len(bins):
                    raise RuntimeError("Not enough bin capacity to provision all recognized cards.")

                b = bins[bin_idx]
                room = cap_by_bin[b] - fill[b]
                take = min(room, len(segment_cards) - segment_pos)
                chunk = segment_cards[segment_pos : segment_pos + take]
                dest_sequences[b].extend(ci.instance_id for ci in chunk)
                fill[b] += take
                segment_pos += take
    else:
        future_pinned = dict(pinned_totals)
        for ci, _ in ordered_with_keys:
            pinned_bin = pinned_by_instance.get(ci.instance_id)
            if pinned_bin is not None:
                if fill[pinned_bin] >= cap_by_bin[pinned_bin]:
                    raise RuntimeError(f"Pinned bin {pinned_bin} overflow for {ci.instance_id}")
                dest_sequences[pinned_bin].append(ci.instance_id)
                fill[pinned_bin] += 1
                future_pinned[pinned_bin] -= 1
                continue

            placed = False
            for b in bins:
                free = cap_by_bin[b] - fill[b]
                if free <= 0:
                    continue
                # Preserve room for future pinned cards in each bin.
                if free - 1 < future_pinned.get(b, 0):
                    continue
                dest_sequences[b].append(ci.instance_id)
                fill[b] += 1
                placed = True
                break
            if not placed:
                raise RuntimeError(
                    "Unable to place unpinned cards while preserving pinned-bin constraints."
                )

    cleaned = {b: seq for b, seq in dest_sequences.items() if seq}
    notes = {
        "requested_split_prefix_len": requested_split,
        "effective_split_prefix_len": effective_split,
        "split_overridden": split_overridden,
        "split_override_reason": split_override_reason,
        "segments_count": len(segments),
        "pinned_cards_count": len(pinned_by_instance),
    }
    return cleaned, notes


def plan_moves_correctness_first(
    instances_by_bin: Dict[int, List[str]],
    dest_sequences: Dict[int, List[str]],
    staging_bins: List[int],
) -> List[Move]:
    """
    V1 execution plan (correctness-first, not optimal):
    For each destination bin:
      - Build a staging stack S by extracting each required instance in final order and pushing onto S.
      - Dump S to destination to achieve correct top->bottom (reversal).
    This requires a helper to 'extract' a specific instance from a stack via temporary moves.
    Here we output an abstract move list; robot-service will implement extraction.
    """
    moves: List[Move] = []
    seq = 1
    stage_pool = staging_bins[:]

    for dest_bin, final_list in dest_sequences.items():
        if not stage_pool:
            raise RuntimeError("No staging bins available for planning.")
        stage = stage_pool[0]
        for instance_id in final_list:
            moves.append(Move(seq=seq, from_bin=-1, to_bin=stage, instance_id=instance_id))
            seq += 1
        for instance_id in reversed(final_list):
            moves.append(Move(seq=seq, from_bin=stage, to_bin=dest_bin, instance_id=instance_id))
            seq += 1
    return moves


def generate_plan(
    cards: List[CardInstance],
    sort_spec: SortSpec,
    system_bins: SystemBins,
    capacities: BinCapacity,
    all_bins: List[int],
) -> MovementPlan:
    validate_split_prefix_rule(sort_spec)

    recognized = [c for c in cards if c.identified]
    ordered_with_keys = sorted(
        ((c, _card_key(c, sort_spec)) for c in recognized),
        key=lambda pair: pair[1],
    )

    # Unrecognized bin is never used for provisioning/staging.
    available = [b for b in all_bins if b != system_bins.unrecognized_bin]
    dest_sequences, provisioning_notes = provision_bins(
        ordered_with_keys,
        sort_spec,
        available,
        capacities,
    )

    used_dest = set(dest_sequences.keys())
    staging_bins = [b for b in available if b not in used_dest]
    if not staging_bins and system_bins.input_bin != system_bins.unrecognized_bin:
        staging_bins = [system_bins.input_bin]

    instances_by_bin: Dict[int, List[str]] = {}
    for c, _ in ordered_with_keys:
        instances_by_bin.setdefault(c.current_bin, []).append(c.instance_id)

    moves = plan_moves_correctness_first(instances_by_bin, dest_sequences, staging_bins)

    return MovementPlan(
        dest_sequences=dest_sequences,
        moves=moves,
        notes={
            "planner": "v1_correctness_first",
            "staging_bins": staging_bins,
            "dest_bins": list(dest_sequences.keys()),
            **provisioning_notes,
        },
    )

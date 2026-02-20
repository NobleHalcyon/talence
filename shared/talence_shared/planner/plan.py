from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any, Optional

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

def provision_bins_simple(
    ordered_instances: List[CardInstance],
    available_bins: List[int],
    capacities: BinCapacity,
) -> Dict[int, List[str]]:
    """
    V1 provisioning: fill bins sequentially with contiguous chunks of the global order.
    This prioritizes correctness and simplicity. Later we add pinned bins + split preferences.
    """
    dest_sequences: Dict[int, List[str]] = {}
    idx = 0
    for b in available_bins:
        cap = capacities.capacity_by_bin.get(b, 0)
        if cap <= 0:
            continue
        if idx >= len(ordered_instances):
            break
        chunk = ordered_instances[idx: idx + cap]
        if chunk:
            dest_sequences[b] = [c.instance_id for c in chunk]  # top->bottom
            idx += len(chunk)
    if idx < len(ordered_instances):
        raise RuntimeError("Not enough bin capacity to provision all recognized cards.")
    return dest_sequences

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
    # Reserve one staging bin per destination if possible, else reuse.
    stage_pool = staging_bins[:]

    for dest_bin, final_list in dest_sequences.items():
        if not stage_pool:
            raise RuntimeError("No staging bins available for planning.")
        stage = stage_pool[0]  # reuse first staging bin
        # 1) ensure staging is empty (in v1 we assume it is; later we add clearing steps)
        # 2) push onto staging in final order (c0 then c1 ...)
        for instance_id in final_list:
            # abstract extraction: move that instance to staging
            # placeholder move: FROM=? TO=stage; will be expanded at execution time
            moves.append(Move(seq=seq, from_bin=-1, to_bin=stage, instance_id=instance_id))
            seq += 1
        # 3) dump staging to destination (pop stage -> dest)
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
    # Unrecognized should already be in unrecognized bin; planner ignores them.

    # Build global order
    def key_fn(ci: CardInstance) -> Tuple:
        d = dict(ci.attrs)
        d.update({
            "name": ci.name,
            "oracle_id": ci.oracle_id,
            "print_id": ci.print_id,
            "instance_id": ci.instance_id,
        })
        return build_composite_key(d, sort_spec)

    ordered = sorted(recognized, key=key_fn)

    # Determine available bins excluding system unrecognized (and optionally input if you want to keep as staging)
    excluded = {system_bins.unrecognized_bin}
    available = [b for b in all_bins if b not in excluded]

    # For v1 simple provisioning, we treat ALL non-unrecognized bins as possible destinations.
    dest_sequences = provision_bins_simple(ordered, available, capacities)

    # Determine staging bins: any empty bins not used as destinations could be staging. V1: pick a few highest-numbered bins.
    used_dest = set(dest_sequences.keys())
    staging_bins = [b for b in available if b not in used_dest]
    if not staging_bins:
        # fallback: allow using input bin as staging if it’s not unrecognized
        if system_bins.input_bin != system_bins.unrecognized_bin:
            staging_bins = [system_bins.input_bin]

    # Current stacks by bin (instance ids top->bottom)
    instances_by_bin: Dict[int, List[str]] = {}
    for c in recognized:
        instances_by_bin.setdefault(c.current_bin, []).append(c.instance_id)

    moves = plan_moves_correctness_first(instances_by_bin, dest_sequences, staging_bins)

    return MovementPlan(
        dest_sequences=dest_sequences,
        moves=moves,
        notes={
            "planner": "v1_correctness_first",
            "staging_bins": staging_bins,
            "dest_bins": list(dest_sequences.keys()),
        },
    )

from __future__ import annotations

import pytest

from talence_shared.planner.plan import BinCapacity, CardInstance, SystemBins, generate_plan
from talence_shared.sort_spec import Operator, OperatorConfig, SortSpec


def _card(
    instance_id: str,
    name: str,
    *,
    color_identity: list[str] | None = None,
    pinned_bin: int | None = None,
) -> CardInstance:
    attrs: dict[str, object] = {
        "color_identity": color_identity or [],
        "colors": color_identity or [],
        "is_land": False,
    }
    if pinned_bin is not None:
        attrs["pinned_bin"] = pinned_bin
    return CardInstance(
        instance_id=instance_id,
        name=name,
        oracle_id=f"o-{instance_id}",
        print_id=f"p-{instance_id}",
        identified=True,
        current_bin=1,
        attrs=attrs,
    )


def _labels_for_bin(dest_sequences: dict[int, list[str]], label_by_instance: dict[str, str], bin_id: int) -> list[str]:
    return [label_by_instance[i] for i in dest_sequences.get(bin_id, [])]


def _no_interleaving(labels: list[str]) -> bool:
    last_seen_at: dict[str, int] = {}
    for idx, label in enumerate(labels):
        if label in last_seen_at and idx - last_seen_at[label] > 1:
            return False
        last_seen_at[label] = idx
    return True


def test_split_segments_colocate_without_interleaving_and_exclude_unrecognized_bin() -> None:
    cards = [
        _card("W1", "Alpha W1", color_identity=["W"]),
        _card("W2", "Beta W2", color_identity=["W"]),
        _card("U1", "Alpha U1", color_identity=["U"]),
        _card("U2", "Beta U2", color_identity=["U"]),
        _card("B1", "Alpha B1", color_identity=["B"]),
        _card("B2", "Beta B2", color_identity=["B"]),
    ]
    sort_spec = SortSpec(
        operators=[
            OperatorConfig(op=Operator.COLOR_IDENTITY, enabled=True, order=0, split_into_bins=True),
            OperatorConfig(op=Operator.ALPHABETICAL, enabled=True, order=1, deep=True, split_into_bins=False),
        ]
    )
    plan = generate_plan(
        cards=cards,
        sort_spec=sort_spec,
        system_bins=SystemBins(input_bin=1, unrecognized_bin=35),
        capacities=BinCapacity(capacity_by_bin={1: 3, 2: 3, 35: 100}),
        all_bins=[1, 2, 35],
    )

    assert 35 not in plan.dest_sequences
    assert plan.notes["split_overridden"] is False
    assert plan.notes["effective_split_prefix_len"] == 1

    labels = {
        "W1": "W",
        "W2": "W",
        "U1": "U",
        "U2": "U",
        "B1": "B",
        "B2": "B",
    }
    b1_labels = _labels_for_bin(plan.dest_sequences, labels, 1)
    b2_labels = _labels_for_bin(plan.dest_sequences, labels, 2)
    assert b1_labels == ["W", "W", "U"]
    assert b2_labels == ["U", "B", "B"]
    assert _no_interleaving(b1_labels)
    assert _no_interleaving(b2_labels)


def test_hard_pinned_bin_constraint_enforced() -> None:
    cards = [
        _card("A", "Alpha"),
        _card("B", "Beta", pinned_bin=2),
        _card("C", "Gamma"),
    ]
    sort_spec = SortSpec(
        operators=[OperatorConfig(op=Operator.ALPHABETICAL, enabled=True, order=0, deep=True)]
    )
    plan = generate_plan(
        cards=cards,
        sort_spec=sort_spec,
        system_bins=SystemBins(input_bin=1, unrecognized_bin=35),
        capacities=BinCapacity(capacity_by_bin={1: 2, 2: 2}),
        all_bins=[1, 2],
    )

    assert "B" in plan.dest_sequences[2]


def test_pinned_bin_must_be_provisionable() -> None:
    cards = [_card("A", "Alpha", pinned_bin=35)]
    sort_spec = SortSpec(
        operators=[OperatorConfig(op=Operator.ALPHABETICAL, enabled=True, order=0, deep=True)]
    )
    with pytest.raises(RuntimeError, match="not provisionable"):
        generate_plan(
            cards=cards,
            sort_spec=sort_spec,
            system_bins=SystemBins(input_bin=1, unrecognized_bin=35),
            capacities=BinCapacity(capacity_by_bin={1: 1, 35: 100}),
            all_bins=[1, 35],
        )


def test_split_is_overridden_when_pinned_constraints_present() -> None:
    cards = [
        _card("W1", "Alpha W1", color_identity=["W"], pinned_bin=2),
        _card("U1", "Alpha U1", color_identity=["U"]),
    ]
    sort_spec = SortSpec(
        operators=[
            OperatorConfig(op=Operator.COLOR_IDENTITY, enabled=True, order=0, split_into_bins=True),
            OperatorConfig(op=Operator.ALPHABETICAL, enabled=True, order=1, deep=True, split_into_bins=False),
        ]
    )
    plan = generate_plan(
        cards=cards,
        sort_spec=sort_spec,
        system_bins=SystemBins(input_bin=1, unrecognized_bin=35),
        capacities=BinCapacity(capacity_by_bin={1: 1, 2: 1}),
        all_bins=[1, 2],
    )
    assert plan.notes["requested_split_prefix_len"] == 1
    assert plan.notes["effective_split_prefix_len"] == 0
    assert plan.notes["split_overridden"] is True
    assert plan.notes["split_override_reason"] == "pinned_constraints"


def test_planner_is_deterministic_for_same_inputs() -> None:
    cards = [
        _card("1", "A", color_identity=["W"]),
        _card("2", "B", color_identity=["U"]),
        _card("3", "C", color_identity=["B"]),
        _card("4", "D", color_identity=["W"]),
    ]
    sort_spec = SortSpec(
        operators=[
            OperatorConfig(op=Operator.COLOR_IDENTITY, enabled=True, order=0, split_into_bins=True),
            OperatorConfig(op=Operator.ALPHABETICAL, enabled=True, order=1, deep=True),
        ]
    )
    caps = BinCapacity(capacity_by_bin={1: 2, 2: 2, 3: 2})
    bins = [1, 2, 3]
    sys_bins = SystemBins(input_bin=1, unrecognized_bin=35)

    plan_a = generate_plan(cards, sort_spec, sys_bins, caps, bins)
    plan_b = generate_plan(cards, sort_spec, sys_bins, caps, bins)

    assert plan_a.dest_sequences == plan_b.dest_sequences
    assert [(m.seq, m.from_bin, m.to_bin, m.instance_id) for m in plan_a.moves] == [
        (m.seq, m.from_bin, m.to_bin, m.instance_id) for m in plan_b.moves
    ]
    assert plan_a.notes == plan_b.notes

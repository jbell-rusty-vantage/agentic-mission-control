"""Lane compile conformance: the same checks for every registered lane (design §10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mission_control.domain.resolution.configuration import VENDORS, Vendor
from mission_control.domain.resolution.resolved import LaneCompileRefused, SealedLaneBinding
from tests.conformance.lanes.compile.contract import CompileCheck, CompileConformance
from tests.conformance.lanes.compile.fixtures import CANONICAL_ITEMS, canonical_agent
from tests.conformance.lanes.compile.registry import COMPILE_LANES, SUITE_PROBES, compile_lanes
from tests.conformance.lanes.contract import DeclaredException

ROOT = Path(__file__).resolve().parents[4]


def _agent(lane: CompileConformance, *, required: frozenset[str] = frozenset()) -> Any:
    """The canonical agent on the first vendor the lane routes (a lane routes at least one)."""

    declaration = lane.declaration()
    vendor = next(
        vendor
        for vendor in VENDORS
        if (route := declaration.route(vendor)) is not None and route.verdict != "unsupported"
    )
    return canonical_agent(lane.profile, vendor=vendor, required=required)


@pytest.mark.parametrize("lane", compile_lanes(CompileCheck.DESCRIBE_HONESTY))
def test_receipt_verdicts_equal_the_declared_cells(lane: CompileConformance) -> None:
    declaration = lane.declaration()
    _, receipt = lane.adapter().compile(_agent(lane), lane.options())

    rows = {(row.kind, row.name): row for row in receipt.items}
    for item in CANONICAL_ITEMS:
        row = rows[(item.receipt_kind, item.name)]
        cell = declaration.items[item.kind]
        assert row.verdict == cell or (row.verdict == "degraded" and cell != "unsupported"), (
            f"{lane.profile} compiled {item.kind} {item.name} as {row.verdict}, describes {cell}"
        )
    assert receipt.lane_profile == lane.profile


@pytest.mark.parametrize("lane", compile_lanes(CompileCheck.RECEIPT_ITEM_DIGESTS))
def test_receipt_rows_carry_the_item_pin_digest(lane: CompileConformance) -> None:
    _, receipt = lane.adapter().compile(_agent(lane), lane.options())

    rows = {(row.kind, row.name): row for row in receipt.items}
    for item in CANONICAL_ITEMS:
        row = rows[(item.receipt_kind, item.name)]
        if row.digest is not None:
            assert row.digest == item.digest


@pytest.mark.parametrize("lane", compile_lanes(CompileCheck.REQUIRED_REFUSAL))
def test_a_required_unsupported_item_refuses_with_a_pointer(lane: CompileConformance) -> None:
    declaration = lane.declaration()
    unsupported = [
        item for item in CANONICAL_ITEMS if declaration.items[item.kind] == "unsupported"
    ]
    if not unsupported:
        pytest.skip(f"{lane.profile} supports every canonical item kind")
    target = unsupported[0]
    agent = _agent(lane, required=frozenset({target.name}))

    with pytest.raises(LaneCompileRefused) as refused:
        lane.adapter().compile(agent, lane.options())

    refusal = refused.value.refusal
    assert refusal.code == "ITEM_UNSUPPORTED_ON_LANE"
    assert refusal.lane_profile == lane.profile
    index = [item.name for item in agent.items].index(target.name)
    assert refusal.pointer == f"/items/{index}"


@pytest.mark.parametrize("lane", compile_lanes(CompileCheck.IDEMPOTENT))
def test_compile_is_pure_and_idempotent(lane: CompileConformance) -> None:
    agent = _agent(lane)
    first = lane.adapter().compile(agent, lane.options())
    second = lane.adapter().compile(agent, lane.options())

    assert first[0].digest == second[0].digest
    assert first[1].receipt_digest == second[1].receipt_digest


@pytest.mark.parametrize("lane", compile_lanes(CompileCheck.VENDOR_ROUTES))
@pytest.mark.parametrize("vendor", VENDORS)
def test_each_routed_vendor_compiles_and_others_refuse(
    lane: CompileConformance, vendor: Vendor
) -> None:
    route = lane.declaration().route(vendor)
    agent = canonical_agent(lane.profile, vendor=vendor)

    if route is None or route.verdict == "unsupported":
        with pytest.raises(LaneCompileRefused) as refused:
            lane.adapter().compile(agent, lane.options())
        assert refused.value.refusal.code == "MODEL_ROUTE_UNSUPPORTED"
        return
    _, receipt = lane.adapter().compile(agent, lane.options())
    model_rows = [row for row in receipt.items if row.kind == "model"]
    assert [row.verdict for row in model_rows] == [route.verdict]


@pytest.mark.parametrize("lane", compile_lanes(CompileCheck.OPAQUE_PORT))
def test_only_sealed_bytes_and_a_receipt_cross_the_port(lane: CompileConformance) -> None:
    binding, _ = lane.adapter().compile(_agent(lane), lane.options())

    assert isinstance(binding, SealedLaneBinding)
    assert binding.lane_profile == lane.profile
    assert isinstance(binding.payload, bytes)
    json.loads(binding.payload)  # canonical JSON, never a pickled native object


def test_the_suite_exercises_refusals_and_degradations() -> None:
    """Every branch above runs for at least one registered lane (no vacuous suite)."""

    entries = (*COMPILE_LANES, *SUITE_PROBES)
    declarations = [lane.declaration() for lane in entries]
    assert any(route.verdict == "unsupported" for d in declarations for route in d.model_routes)
    assert any("unsupported" in d.items.values() for d in declarations)
    receipts = [lane.adapter().compile(_agent(lane), lane.options())[1] for lane in entries]
    assert any(receipt.with_verdict("degraded") for receipt in receipts)


def test_every_registered_lane_declares_honest_exceptions() -> None:
    profiles = [lane.profile for lane in COMPILE_LANES]
    assert len(profiles) == len(set(profiles))
    for lane in (*COMPILE_LANES, *SUITE_PROBES):
        assert lane.adapter().profile == lane.profile == lane.declaration().lane_profile
        for check, exception in lane.exceptions.items():
            assert isinstance(check, CompileCheck)
            assert isinstance(exception, DeclaredException)
            assert exception.reason.strip() and exception.evidence, check
            missing = [path for path in exception.evidence if not (ROOT / path).is_file()]
            assert not missing, f"{lane.profile} {check} cites missing evidence {missing}"

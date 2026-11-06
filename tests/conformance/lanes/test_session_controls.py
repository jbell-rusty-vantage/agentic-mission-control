"""Control scenarios beside the turn for every lane that claims them (SPEC-06 section 3).

A provider permission round-trips through MP-11's broker and a Human Task; a fork is emulated
from a mid-run snapshot into a fresh derived session; and a continuation sealed while a turn
runs hands the next turn to a hydrated session at the turn boundary (ADR-0039).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mission_control.application.context.continuation import TransferStatus
from mission_control.domain.execution.lanes import SnapshotRequest
from mission_control.domain.frames.contracts import FrameKind
from tests.conformance.lanes.contract import LaneAdapter, Scenario, Script
from tests.conformance.lanes.drive import (
    approval_rig,
    binding_digest,
    finish,
    harness_fields,
    held_turn,
    lane_state,
    live_session,
    run_turn,
    seal_and_transfer,
    settled,
)
from tests.conformance.lanes.registry import lanes_for

MARKER_PATH = "src/forked.py"
MARKER = b"FORKED = True\n"


@pytest.mark.parametrize("lane", lanes_for(Scenario.APPROVAL_ROUND_TRIP))
async def test_a_provider_permission_round_trips_through_a_human_task(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    rig = approval_rig()
    fake = await lane.open(tmp_path, Script.APPROVAL, broker=rig.broker)
    rig.bind(fake)
    running = asyncio.create_task(run_turn(fake))
    task = await rig.open_task()
    binding = task.packet.binding
    assert task.packet.origin == "provider_permission"
    assert (binding.lane_profile, binding.generation) == (lane.profile, 1)
    assert binding.harness_execution_id == str(fake.identity.harness_execution_id)
    assert binding.policy_digest == binding_digest(fake.operation)
    assert fake.approval_answers() == [], "the provider waits for the human decision"
    await rig.approve(task)
    assert settled(await finish(running)).status == "completed"
    assert fake.approval_answers() == [True]
    (resolved,) = await rig.store.list_tasks(rig.request_scope)
    assert resolved.lifecycle == "resolved"
    kinds = [frame.kind for frame in fake.frames()]
    assert FrameKind.APPROVAL_REQUESTED in kinds and FrameKind.APPROVAL_RESOLVED in kinds


@pytest.mark.parametrize("lane", lanes_for(Scenario.FORK_EMULATION))
async def test_a_fork_is_emulated_from_a_mid_run_snapshot(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    fake = await lane.open(tmp_path / "source", Script.HELD_TURN)
    task = await held_turn(fake)
    await lane.write_workspace(fake, MARKER_PATH, MARKER)
    source = await live_session(fake)
    snapshot = await fake.harness.snapshot(
        SnapshotRequest(**harness_fields(fake, "snapshot"), session=source, reason="fork")
    )
    fake.release()
    assert settled(await finish(task)).status == "completed"
    assert snapshot.emulated is (fake.describe.controls["snapshot"] == "emulated")
    forked = await lane.fork(fake, snapshot, tmp_path / "fork", MARKER_PATH)
    assert forked.native_session_ref != source.native_session_ref, "a fresh derived session"
    assert forked.restored == MARKER, "the derived workspace starts at the snapshot"


@pytest.mark.parametrize("lane", lanes_for(Scenario.CONTINUATION_HANDOVER))
async def test_a_continuation_hands_the_next_turn_to_a_hydrated_session(
    lane: LaneAdapter, tmp_path: Path
) -> None:
    fake = await lane.open(tmp_path, Script.CONTINUATION)
    task = await held_turn(fake)
    source = (await live_session(fake)).native_session_ref
    outcome = await seal_and_transfer(fake, lane.continuation_ports(fake))
    assert outcome.transfer.status == TransferStatus.TRANSFERRED, outcome.transfer
    assert outcome.receipt is not None
    target = outcome.receipt.target_session_ref
    assert target != source, "a fresh session, never the source resumed"
    fake.release()
    result = await finish(task)
    assert settled(result).status == "completed"
    sends = fake.sends()
    assert [session for session, _text in sends] == [source, target]
    assert "purpose: continuation" in sends[1][1], "the sealed packet rides the handover turn"
    state = await lane_state(fake)
    assert state is not None and state.native_session_ref == target
    assert any(
        frame.kind is FrameKind.SESSION_INIT and frame.native_session_ref == target
        for frame in fake.frames()
    ), "the target's session_init frame confirms the handover"

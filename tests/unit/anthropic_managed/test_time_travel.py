"""`claude_managed` time travel at R1: reads and seeds reconstructed from persisted frames,
the seed honored by `prepare`/`start`/`send_turn`, and the harness steer against the fake.

No Anthropic API is called; the Managed Agents fake proves what the provider surface allows
(a session is created idle; a `user.message` during a held turn is consumed by that turn).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mission_control.adapters.anthropic_managed.time_travel import ClaudeManagedTimeTravel
from mission_control.adapters.remote_session.time_travel import (
    SEED_HEAD,
    SEED_HEAD_INJECTED,
    SEED_PROMPT,
    seed_turn_text,
)
from mission_control.application.execution.harness.dispatch import SteeringLane
from mission_control.application.execution.harness.time_travel import (
    SEED_HEAD_MESSAGE_COUNT,
    ForkSeedRequest,
    TimeTravelLane,
    TimeTravelUnsupported,
)
from mission_control.domain.execution.cognition_points import SessionCursorPoint
from mission_control.domain.execution.lanes import (
    LaneSeedHead,
    ObserveRequest,
    PrepareRequest,
    SendTurnRequest,
    StartRequest,
)
from tests.fixtures.managed_agents import MODEL_USAGE, TURN_LIST_COST
from tests.fixtures.managed_lane import PROFILE, managed_stack
from tests.unit.remote_session.hosted_support import (
    InMemoryFramesOf,
    harness_fields,
    record_for,
    settle_turn,
)

INJECTED = "Redirect: build on release/2.3."


async def _points(tmp_path: Path):  # type: ignore[no-untyped-def]
    stack = managed_stack(tmp_path)
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    points = stack.harness.turn_points(settled.points_request())
    lane = ClaudeManagedTimeTravel(InMemoryFramesOf(settled.lanes.frames))
    records = [
        record_for(
            point,
            run_id=stack.operation.identity.run_id,
            lane_profile=PROFILE,
            harness_execution_id=settled.harness_execution_id,
        )
        for point in points
    ]
    return stack, settled, lane, records


async def test_read_as_of_reconstructs_the_transcript_to_the_point(tmp_path: Path) -> None:
    stack, settled, lane, records = await _points(tmp_path)
    assert isinstance(lane, TimeTravelLane) and lane.lane_profile == PROFILE
    at_message = await lane.read_as_of(records[1])
    assert at_message.restore_level == "R1" and at_message.history == "reconstructed"
    roles = [(message.role, message.text) for message in at_message.state.messages]
    assert roles == [("user", stack.api.messages()[0][1]), ("assistant", "Done: report.md")]
    assert at_message.state.files == ()
    native = at_message.state.channels["native"]
    assert native["session_ref"] == settled.session_ref
    assert native["turn_ref"] == settled.turn_ref
    assert native["point_locator"] == records[1].coordinate.locator
    assert at_message.state.step == 1
    assert at_message.usage_to_point == {}  # the model request closes after this step
    assert any("workspace_files_not_captured" in item for item in at_message.state.withheld)
    at_result = await lane.read_as_of(records[2])
    assert len(at_result.state.messages) == 2
    assert at_result.usage_to_point == {
        **{f"tokens.{name}": amount for name, amount in MODEL_USAGE.items()},
        "cost.list_cost_minor_units": TURN_LIST_COST,
    }


async def test_read_as_of_refuses_other_point_kinds_and_unknown_points(tmp_path: Path) -> None:
    _stack, _settled, lane, records = await _points(tmp_path)
    foreign = records[0].model_copy(
        update={
            "coordinate": records[0].coordinate.model_copy(
                update={"point": SessionCursorPoint(session_ref="x", turn_ref="y", step_ref="z")}
            )
        }
    )
    with pytest.raises(TimeTravelUnsupported, match="point_frame_missing"):
        await lane.read_as_of(foreign)
    with pytest.raises(TimeTravelUnsupported, match="frames_missing"):
        await lane.collect_points(
            namespace=str(records[0].coordinate.harness_execution_id),
            checkpointer_ref_digest="7",
            source_locator=None,
            result_locator="any",
        )


async def test_seed_fork_stages_a_hydration_prompt_and_writes_nothing(tmp_path: Path) -> None:
    stack, _settled, lane, records = await _points(tmp_path)
    requests_before = len(stack.api.requests)
    request = ForkSeedRequest(
        source=records[2],
        derived_run_id="run-derived",
        derived_unit_key=records[2].coordinate.unit_key,
        derived_namespace="heid-derived",
        derived_invocation_id="inv-derived",
        fork_request_id="fork-1",
        message=INJECTED,
    )
    receipt = await lane.seed_fork(request)
    assert receipt.restore_level == "R1" and receipt.history == "reconstructed"
    assert receipt.derived.run_id == "run-derived" and receipt.derived.execution_generation == 1
    assert receipt.derived.point == SessionCursorPoint(
        session_ref="heid-derived", turn_ref="fork-seed:fork-1"
    )
    assert receipt.copied_checkpoints == 2
    artifacts = receipt.native_artifacts
    prompt = artifacts[SEED_PROMPT]
    assert "Done: report.md" in prompt and prompt.rstrip().endswith(INJECTED)
    assert artifacts[SEED_HEAD] == SEED_HEAD_INJECTED
    assert artifacts[SEED_HEAD_MESSAGE_COUNT] == "3"
    assert artifacts["source_point_locator"] == records[2].coordinate.locator
    assert "fake-anthropic-key" not in prompt
    # Idempotent and side-effect free: the same receipt, no provider call, no new session.
    assert await lane.seed_fork(request) == receipt
    assert len(stack.api.requests) == requests_before
    assert len(stack.api.sessions) == 1
    without = await lane.seed_fork(request.model_copy(update={"message": None}))
    assert without.native_artifacts[SEED_HEAD] == "transcript"
    assert (
        without.native_artifacts[SEED_PROMPT]
        .rstrip()
        .endswith("Continue the work from this point.")
    )


async def test_a_seeded_unit_starts_a_new_session_and_sends_the_prompt_first(
    tmp_path: Path,
) -> None:
    _stack, _settled, lane, records = await _points(tmp_path)
    receipt = await lane.seed_fork(
        ForkSeedRequest(
            source=records[2],
            derived_run_id="run-derived",
            derived_unit_key=records[2].coordinate.unit_key,
            derived_namespace="heid-derived",
            derived_invocation_id="inv-derived",
            fork_request_id="fork-1",
            message=INJECTED,
        )
    )
    seed = LaneSeedHead(
        source_run_id=records[2].coordinate.run_id,
        source_unit_key=records[2].coordinate.unit_key,
        source_execution_generation=1,
        point_kind=records[2].coordinate.kind,
        point_locator=records[2].coordinate.locator,
        point=records[2].coordinate.point.model_dump(mode="json"),
        restore_level=receipt.restore_level,
        history="reconstructed",
        native_artifacts=receipt.native_artifacts,
        message=INJECTED,
        fork_request_id="fork-1",
    )
    derived = managed_stack(tmp_path / "derived")
    operation = derived.operation
    fields = harness_fields(operation, PROFILE, "turn:1")
    derived.harness.stage(fields["harness_execution_id"], operation)
    prepared = await derived.harness.prepare(
        PrepareRequest(
            **fields,
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
            seed=seed,
        )
    )
    session = await derived.harness.start(StartRequest(**fields, prepared=prepared, seed=seed))
    created = derived.api.sessions[session.native_session_ref or ""]
    assert created["metadata"]["mc_fork_request"] == "fork-1"
    assert created["metadata"]["mc_fork_point"] == records[2].coordinate.locator
    assert created["status"] == "idle" and not derived.api.messages()
    turn = await derived.harness.send_turn(
        SendTurnRequest(**fields, session=session, turn_no=1, instruction_ref="operation:x:turn:1")
    )
    assert turn.native_turn_ref is not None
    (sent,) = derived.api.messages()
    assert sent[1] == seed_turn_text(seed)
    assert "Done: report.md" in sent[1] and sent[1].rstrip().endswith(INJECTED)


async def test_steer_sends_into_the_running_turn_and_is_stale_otherwise(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path, scripts=("held",))
    operation = stack.operation
    fields = harness_fields(operation, PROFILE, "turn:1")
    heid = fields["harness_execution_id"]
    stack.harness.stage(heid, operation)
    prepared = await stack.harness.prepare(
        PrepareRequest(
            **fields,
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
        )
    )
    session = await stack.harness.start(StartRequest(**fields, prepared=prepared))
    turn = await stack.harness.send_turn(
        SendTurnRequest(**fields, session=session, turn_no=1, instruction_ref="operation:x:turn:1")
    )
    await asyncio.wait_for(stack.api.held.wait(), 5)
    assert isinstance(stack.harness, SteeringLane)
    unstaged = await stack.harness.steer(turn, instruction_ref="inject:1")
    assert unstaged.outcome == "stale_target" and "not staged" in unstaged.detail
    stack.harness.stage_turn(heid, "inject:1", INJECTED)
    steered = await stack.harness.steer(turn, instruction_ref="inject:1")
    assert steered.outcome == "applied" and steered.target_turn_ref == turn.native_turn_ref
    messages = stack.api.messages()
    assert len(messages) == 2 and messages[1][1] == INJECTED
    assert stack.api.sessions[session.native_session_ref or ""]["status"] == "running"
    stack.api.release()
    frames = [
        frame
        async for frame in stack.harness.observe(ObserveRequest(**fields, turn=turn, after=None))
    ]
    assert frames[-1].terminal
    assert stack.harness.closing_facts(turn, frames[-1]).native_status == "finished"
    steer_frames = [
        frame for frame in frames if frame.raw_kind == "user.message" and frame.native_turn_ref
    ]
    assert len(steer_frames) == 2, "the steer is a user.message frame of the same turn"
    assert {frame.native_turn_ref for frame in steer_frames} == {turn.native_turn_ref}
    # Once the turn closed, the same steer no longer lands anywhere.
    after = await stack.harness.steer(turn, instruction_ref="inject:1")
    assert after.outcome == "stale_target" and "not running" in after.detail

"""`codex_agents` time travel at R1: reads and seeds reconstructed from persisted items,
the seed honored by `prepare`/`start`/`send_turn`, and the harness steer against the fake.

No OpenAI API is called; the Agents API fake proves what the surface allows (input during a
held turn lands as a `message:user` item of that turn; idle input starts a turn).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mission_control.adapters.openai_agents.time_travel import CodexAgentsTimeTravel
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
from mission_control.domain.execution.cognition_points import ThreadItemPoint
from mission_control.domain.execution.lanes import (
    LaneSeedHead,
    PrepareRequest,
    SendTurnRequest,
    StartRequest,
)
from tests.fixtures.agents_lane import agents_stack
from tests.unit.remote_session.hosted_support import (
    InMemoryFramesOf,
    harness_fields,
    record_for,
    settle_turn,
)

PROFILE = "codex_agents"
INJECTED = "Redirect: build on release/2.3."


async def _points(tmp_path: Path):  # type: ignore[no-untyped-def]
    stack = agents_stack(tmp_path)
    settled = await settle_turn(stack.harness, stack.operation, PROFILE)
    points = stack.harness.turn_points(settled.points_request())
    lane = CodexAgentsTimeTravel(InMemoryFramesOf(settled.lanes.frames))
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
    _stack, settled, lane, records = await _points(tmp_path)
    assert isinstance(lane, TimeTravelLane) and lane.lane_profile == PROFILE
    at_first_command = await lane.read_as_of(records[0])
    assert at_first_command.restore_level == "R1" and at_first_command.history == "reconstructed"
    messages = at_first_command.state.messages
    assert [message.role for message in messages] == ["assistant", "tool"]
    (call,) = messages[0].tool_calls
    assert call.name == "command_execution" and call.arguments == {"command": "echo evidence"}
    assert messages[1].tool_call_id == call.id and '"exit_code": 0' in (messages[1].text or "")
    assert at_first_command.usage_to_point == {} and at_first_command.state.step == 0
    at_result = await lane.read_as_of(records[-1])
    roles = [message.role for message in at_result.state.messages]
    assert roles == ["assistant", "tool"] * 3 + ["assistant"]
    assert at_result.state.messages[-1].text == "Completed answer."
    assert at_result.state.messages[-1].name == "final_answer"
    assert at_result.usage_to_point == {
        "tokens.input_tokens": 7,
        "tokens.output_tokens": 3,
        "tokens.total_tokens": 10,
    }
    native = at_result.state.channels["native"]
    assert native["session_ref"] == settled.session_ref
    assert native["turn_ref"] == settled.turn_ref
    assert at_result.state.files == ()
    assert any("workspace_files_not_captured" in item for item in at_result.state.withheld)


async def test_read_as_of_refuses_a_session_cursor_point(tmp_path: Path) -> None:
    from mission_control.domain.execution.cognition_points import SessionCursorPoint

    _stack, _settled, lane, records = await _points(tmp_path)
    foreign = records[0].model_copy(
        update={
            "coordinate": records[0].coordinate.model_copy(
                update={"point": SessionCursorPoint(session_ref="x", turn_ref="y")}
            )
        }
    )
    with pytest.raises(TimeTravelUnsupported, match="point_kind_not_thread_item"):
        await lane.read_as_of(foreign)


async def test_seed_fork_stages_a_hydration_prompt_and_writes_nothing(tmp_path: Path) -> None:
    stack, _settled, lane, records = await _points(tmp_path)
    requests_before = len(stack.api.requests)
    request = ForkSeedRequest(
        source=records[-1],
        derived_run_id="run-derived",
        derived_unit_key=records[-1].coordinate.unit_key,
        derived_namespace="heid-derived",
        derived_invocation_id="inv-derived",
        fork_request_id="fork-1",
        message=INJECTED,
    )
    receipt = await lane.seed_fork(request)
    assert receipt.restore_level == "R1" and receipt.history == "reconstructed"
    assert receipt.derived.point == ThreadItemPoint(
        thread_ref="heid-derived", item_ref="fork-seed#fork-1"
    )
    assert receipt.copied_checkpoints == 7
    artifacts = receipt.native_artifacts
    prompt = artifacts[SEED_PROMPT]
    assert "Completed answer." in prompt and "echo evidence" in prompt
    assert prompt.rstrip().endswith(INJECTED)
    assert artifacts[SEED_HEAD] == SEED_HEAD_INJECTED
    assert artifacts[SEED_HEAD_MESSAGE_COUNT] == "8"
    assert "sk-test" not in prompt
    assert await lane.seed_fork(request) == receipt
    assert len(stack.api.requests) == requests_before
    assert len(stack.api.sessions_store) == 1


async def test_a_seeded_unit_starts_a_new_session_and_sends_the_prompt_first(
    tmp_path: Path,
) -> None:
    _stack, _settled, lane, records = await _points(tmp_path)
    receipt = await lane.seed_fork(
        ForkSeedRequest(
            source=records[-1],
            derived_run_id="run-derived",
            derived_unit_key=records[-1].coordinate.unit_key,
            derived_namespace="heid-derived",
            derived_invocation_id="inv-derived",
            fork_request_id="fork-1",
            message=INJECTED,
        )
    )
    seed = LaneSeedHead(
        source_run_id=records[-1].coordinate.run_id,
        source_unit_key=records[-1].coordinate.unit_key,
        source_execution_generation=1,
        point_kind=records[-1].coordinate.kind,
        point_locator=records[-1].coordinate.locator,
        point=records[-1].coordinate.point.model_dump(mode="json"),
        restore_level=receipt.restore_level,
        history="reconstructed",
        native_artifacts=receipt.native_artifacts,
        message=INJECTED,
        fork_request_id="fork-1",
    )
    derived = agents_stack(tmp_path / "derived")
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
    created = derived.api.sessions_store[session.native_session_ref or ""]
    assert created["metadata"]["mc_fork_request"] == "fork-1"
    assert created["metadata"]["mc_fork_point"] == records[-1].coordinate.locator
    assert not derived.api.sends
    turn = await derived.harness.send_turn(
        SendTurnRequest(**fields, session=session, turn_no=1, instruction_ref="operation:x:turn:1")
    )
    assert turn.native_turn_ref is not None
    (sent,) = derived.api.sends
    (message,) = json.loads(sent[1])
    text = message["content"][0]["text"]
    assert text == seed_turn_text(seed)
    assert "Completed answer." in text and text.rstrip().endswith(INJECTED)


async def test_steer_sends_into_the_active_turn_and_is_stale_otherwise(tmp_path: Path) -> None:
    stack = agents_stack(tmp_path, ("held",))
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
    assert stack.api.steers == [turn.native_turn_ref]
    assert len(stack.api.sends) == 2 and INJECTED in stack.api.sends[1][1]
    assert len(stack.api.turn_store) == 1, "no new turn: the input steered the active one"
    user_items = [
        item
        for item in stack.api.item_store[turn.native_turn_ref or ""]
        if item["type"] == "message" and item["role"] == "user"
    ]
    assert len(user_items) == 1
    stack.api.release()
    after = await stack.harness.steer(turn, instruction_ref="inject:1")
    assert after.outcome == "stale_target" and "not in progress" in after.detail

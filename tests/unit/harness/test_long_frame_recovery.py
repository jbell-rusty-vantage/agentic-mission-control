"""Recovery must reconcile tool effects beyond the first frame-reader page."""

import pytest

from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import FrameKind, LaneProfile
from tests.fixtures.lane_turns import SCOPE, cursor_operation, lane_stack
from tests.fixtures.provider_frames import harness_start, observation


@pytest.mark.asyncio
async def test_recomposed_lane_reconciles_tool_effects_after_ten_thousand_frames() -> None:
    operation = cursor_operation()
    stack = lane_stack(operation=operation)
    start = harness_start(
        request_scope=SCOPE,
        run_key=operation.identity.run_id,
        activation_key=operation.identity.operation_id,
        lane=LaneProfile.CURSOR_LOCAL,
    )
    handle = await stack.frames.open_execution(start)
    writer = FrameWriter(stack.frames, handle)
    events = [observation("early", FrameKind.TOOL_CALL_STARTED, {}, tool_call_ref="early")]
    events.extend(observation(str(index), FrameKind.MESSAGE_DELTA, {}) for index in range(9999))
    events.extend(
        [
            observation("late", FrameKind.TOOL_CALL_STARTED, {}, tool_call_ref="late"),
            observation(
                "early-completed", FrameKind.TOOL_CALL_COMPLETED, {}, tool_call_ref="early"
            ),
        ]
    )
    await writer.write(events)
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
    recomposed = lane_stack(frames=stack.frames, operation=operation)
    assert await recomposed.service._open_effects(identity, 1, "turn-1") == ("late",)
    await FrameWriter(stack.frames, await stack.frames.open_execution(start)).write(
        [observation("late-completed", FrameKind.TOOL_CALL_COMPLETED, {}, tool_call_ref="late")]
    )
    restarted = lane_stack(frames=stack.frames, operation=operation)
    assert await restarted.service._open_effects(identity, 1, "turn-1") == ()

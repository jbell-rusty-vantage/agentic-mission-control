"""Regression coverage for delayed provider observations and long-lived projections."""

import pytest

from mission_control.application.frames.reducer import (
    DeriveContext,
    FrameFactProjector,
    FrameFactTarget,
    derive,
)
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import FrameKind as K
from mission_control.domain.frames.contracts import LaneProfile
from mission_control.domain.frames.facts import (
    ExecutionOutcomeFact,
    ToolEffectFact,
    TurnCompletedFact,
    TurnStartedFact,
    UsageSettledFact,
)
from mission_control.domain.policies.contracts import StartAction
from tests.fixtures.provider_frames import (
    SCOPE,
    harness_start,
    in_memory_store,
    observation,
    provider_frame,
)
from tests.unit.frames.test_frame_facts import _RunControl
from tests.unit.run_control.test_run_control import ALL_PERMISSIONS, actor, command, request
from tests.unit.run_control.test_run_control import service as run_control_service


def test_later_turn_failure_is_not_hidden_by_an_earlier_success() -> None:
    facts = derive(
        [
            provider_frame(1, K.RUN_RESULT, {"status": "finished"}, turn="first"),
            provider_frame(2, K.RUN_RESULT, {"status": "error"}, turn="second"),
            provider_frame(3, K.RUN_RESULT, {"status": "error"}, turn="second"),
        ],
        DeriveContext(
            lane=LaneProfile.CURSOR_CLOUD, current_generation=1, completion_policy="deferred"
        ),
    )
    outcomes = [fact for fact in facts if isinstance(fact, ExecutionOutcomeFact)]
    assert len(outcomes) == 1
    assert outcomes[0].native_turn_ref == "second"
    assert outcomes[0].outcome == "failed"


def test_unknown_result_does_not_suppress_authoritative_terminal_observation() -> None:
    facts = derive(
        [
            provider_frame(1, K.RUN_RESULT, {"status": "unknown"}),
            provider_frame(2, K.RUN_RESULT, {"status": "error"}),
        ],
        DeriveContext(lane=LaneProfile.CURSOR_CLOUD, current_generation=1),
    )
    assert any(isinstance(fact, ExecutionOutcomeFact) for fact in facts)


def test_delayed_tools_and_usage_keep_the_original_turn_without_reopening_it() -> None:
    facts = derive(
        [
            provider_frame(1, K.TURN_ENDED, {}, turn="first"),
            provider_frame(2, K.TOOL_CALL_COMPLETED, {}, turn="first", tool_call_ref="late"),
            provider_frame(3, K.TOOL_CALL_COMPLETED, {}, turn="second", tool_call_ref="next"),
            provider_frame(4, K.USAGE, {"input_tokens": 7}, turn="first"),
            provider_frame(5, K.TURN_ENDED, {}, turn="second"),
        ],
        DeriveContext(lane=LaneProfile.DEEP_AGENTS, current_generation=1),
    )
    starts = [fact for fact in facts if isinstance(fact, TurnStartedFact)]
    assert [(fact.native_turn_ref, fact.turn_ordinal) for fact in starts] == [
        ("first", 1),
        ("second", 2),
    ]
    tool = next(fact for fact in facts if isinstance(fact, ToolEffectFact))
    usage = next(fact for fact in facts if isinstance(fact, UsageSettledFact))
    assert tool.turn_ordinal == usage.turn_ordinal == 1


def test_delayed_approval_cannot_put_a_completed_turn_back_into_waiting() -> None:
    facts = derive(
        [
            provider_frame(1, K.TURN_ENDED, {}),
            provider_frame(2, K.SESSION_STATE, {"state": "awaiting_human"}),
        ],
        DeriveContext(lane=LaneProfile.CURSOR_CLOUD, current_generation=1),
    )
    assert [fact.fact for fact in facts] == ["session_started", "turn_started", "turn_completed"]


def test_usage_with_a_new_native_turn_starts_that_turn() -> None:
    facts = derive(
        [
            provider_frame(1, K.TURN_ENDED, {}, turn="first"),
            provider_frame(2, K.USAGE, {"input_tokens": 7}, turn="second"),
            provider_frame(3, K.TURN_ENDED, {}, turn="second"),
        ],
        DeriveContext(lane=LaneProfile.DEEP_AGENTS, current_generation=1),
    )
    turns = [fact for fact in facts if isinstance(fact, TurnCompletedFact)]
    assert turns[1].native_turn_ref == "second" and turns[1].turn_ordinal == 2
    assert turns[1].usage.value("input_tokens") == 7
    assert not any(isinstance(fact, UsageSettledFact) for fact in facts)


@pytest.mark.asyncio
@pytest.mark.parametrize(("page_size", "batch_size"), [(2, 64), (100, 2)])
async def test_projection_reads_all_pages_and_does_not_count_success_as_contention(
    page_size: int, batch_size: int
) -> None:
    service, _repository = run_control_service()
    admitted = await service.admit(request(request_scope=SCOPE))
    assert admitted.run_id is not None
    run_id = admitted.run_id
    await service.execute(
        command(run_id, 1, "start", StartAction()).model_copy(update={"request_scope": SCOPE})
    )
    store, _ = in_memory_store(run_key=run_id)
    handle = await store.open_execution(harness_start(run_key=run_id))
    writer = FrameWriter(store, handle)
    await writer.write(
        [
            observation(str(index), K.TOOL_CALL_COMPLETED, {}, tool_call_ref=f"tool-{index}")
            for index in range(40)
        ]
    )
    permitted = actor().model_copy(
        update={"permissions": ALL_PERMISSIONS | {"workflow_run.apply_frame_facts"}}
    )
    control = _RunControl(service)
    projector = FrameFactProjector(
        store, control, actor=permitted, max_frames=page_size, batch_size=batch_size
    )
    target = FrameFactTarget.from_handle(handle, run_key=run_id)
    projected = await projector.project(target, completion_policy="deferred")
    assert projected.through_ordinal == 40
    assert projected.applied == projected.derived == 42
    # A new projector/process derives the same history and emits no duplicate facts.
    restarted = FrameFactProjector(store, control, actor=permitted, max_frames=page_size)
    assert (await restarted.project(target, completion_policy="deferred")).applied == 0

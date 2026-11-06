"""MO-16: `lane.turn` records each prepared attempt's environment readiness and starts the
session only at the launch policy's minimum.

A prepare that proves no projection or workspace leaves the environment `declared`: the session
never starts, nothing is sent, and the unit settles `failed(environment_not_ready)` with the
policy's reason. A prepared environment starts, and a hook frame raises it to `exercised`. A
worker that restarts before the native session is recorded prepares the same generation again
with another receipt; the recorded receipt stands and the session starts.

MO-34: a lane that reads back what its provider loaded (`DiscoveringLane`) does so once its new
native session exists; the report is persisted as a frame and raises the environment to
`discovered`. A read-back that fails is lost evidence: the turn still completes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from mission_control.application.environments import (
    EnvironmentPreparationService,
    InMemoryEnvironmentPreparationRepository,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.contracts import OperationExecutionResult
from mission_control.domain.execution.discovery import (
    DiscoveryExpectation,
    DiscoveryItem,
    DiscoveryReport,
)
from mission_control.domain.execution.environment_preparation import (
    ENVIRONMENT_NOT_READY,
    LaunchReadinessPolicy,
    ReadinessLevel,
    preparation_id,
)
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.execution.lanes import (
    PreparedSession,
    PrepareRequest,
    SessionHandle,
    StartRequest,
)
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.lane_turns import (
    DIGEST,
    PreparingLane,
    RecordingSignals,
    ScriptedSessionLane,
    SimulatedWorkerLoss,
    cursor_operation,
    lane_stack,
    scripted_frames,
)


class LostBeforeStart(PreparingLane):
    """A worker that dies after the gate admitted its environment and before the native
    session was recorded."""

    async def start(self, request: StartRequest) -> SessionHandle:
        self.calls.append("start")
        raise SimulatedWorkerLoss


SKILL = DiscoveryItem(kind="skill", name="agent-browser")


@dataclass
class ReadingBackLane(PreparingLane):
    """A preparing lane whose provider reads back the skill it placed (or fails to)."""

    fail: bool = False

    async def prepare(self, request: PrepareRequest) -> PreparedSession:
        prepared = await super().prepare(request)
        expectation = DiscoveryExpectation(mechanism="setting_readback", items=(SKILL,))
        return prepared.model_copy(update={"discovery": expectation})

    async def discover(self, session: SessionHandle) -> DiscoveryReport | None:
        self.calls.append("discover")
        if self.fail:
            raise ConnectionError("the provider read-back failed")
        return DiscoveryReport(
            lane_profile=LaneProfile.CURSOR_LOCAL,
            mechanism="setting_readback",
            items=(SKILL,),
            source=f"sdk:get_agent:{session.native_session_ref}",
        )


def _turn() -> LaneTurnRequest:
    return LaneTurnRequest(operation=cursor_operation(), lane_profile="cursor_local", generation=1)


def _identity() -> LaneExecutionIdentity:
    return LaneExecutionIdentity.of(cursor_operation(), "cursor_local", 1)


def _stack(
    lane: Any,
    policy: LaunchReadinessPolicy | None = None,
    repository: InMemoryEnvironmentPreparationRepository | None = None,
) -> Any:
    repository = repository or InMemoryEnvironmentPreparationRepository()
    service = EnvironmentPreparationService(repository, policy=policy)
    return lane_stack(lane, preparations=service), repository


async def _stored(repository: InMemoryEnvironmentPreparationRepository) -> Any:
    identity = _identity()
    return await repository.get(
        identity.request_scope,
        preparation_id(identity.request_scope, identity.harness_execution_id, 1),
    )


async def test_an_unprepared_environment_never_starts_its_session() -> None:
    lane = ScriptedSessionLane(frames=scripted_frames())
    stack, repository = _stack(lane)
    result = await stack.service.turn(_turn(), RecordingSignals(stack.frames))

    assert result.done and result.closing_facts is not None
    assert result.closing_facts.error_code == ENVIRONMENT_NOT_READY
    settled = OperationExecutionResult.model_validate(result.operation_result)
    assert settled.status == "failed" and settled.failure_code == ENVIRONMENT_NOT_READY
    assert settled.failure_message is not None and "needs prepared" in settled.failure_message
    assert lane.calls == ["prepare"], "no start, no send: nothing reached the provider"
    stored = await _stored(repository)
    assert stored is not None and stored.readiness is ReadinessLevel.DECLARED
    assert stored.omissions and stored.omissions[0].startswith("rendered:")


async def test_a_prepared_environment_starts_and_a_hook_frame_exercises_it() -> None:
    frames = scripted_frames()
    frames.insert(1, ("hook.invoked", {"hook": "mc.stop_fence", "event": "before_tool"}))
    lane = PreparingLane(frames=frames)
    stack, repository = _stack(lane)
    result = await stack.service.turn(_turn(), RecordingSignals(stack.frames))

    settled = OperationExecutionResult.model_validate(result.operation_result)
    assert settled.status == "completed"
    assert lane.calls.index("prepare") < lane.calls.index("start")
    stored = await _stored(repository)
    assert stored is not None and stored.receipt_digest == DIGEST
    assert [mark.level for mark in stored.marks] == [
        ReadinessLevel.DECLARED,
        ReadinessLevel.RENDERED,
        ReadinessLevel.DELIVERED,
        ReadinessLevel.PREPARED,
        ReadinessLevel.EXERCISED,
    ]
    exercised = stored.mark(ReadinessLevel.EXERCISED)
    assert exercised is not None and exercised.evidence_ref.startswith("frame:fake:run-fake-1:")


async def test_a_restarted_worker_prepares_again_and_the_recorded_receipt_stands() -> None:
    lost = LostBeforeStart(frames=scripted_frames(), materialization_ref=DIGEST)
    stack, repository = _stack(lost)
    with pytest.raises(SimulatedWorkerLoss):
        await stack.service.turn(_turn(), RecordingSignals(stack.frames))
    admitted = await _stored(repository)
    assert admitted is not None and admitted.receipt_digest == DIGEST

    # The reused lease lists the files already written as unchanged: another receipt digest.
    again = PreparingLane(frames=scripted_frames(), materialization_ref="sha256:" + "9" * 64)
    stack, repository = _stack(again, repository=repository)
    result = await stack.service.turn(_turn(), RecordingSignals(stack.frames))

    assert OperationExecutionResult.model_validate(result.operation_result).status == "completed"
    assert again.calls.index("prepare") < again.calls.index("start")
    stored = await _stored(repository)
    assert stored is not None and stored.receipt_digest == DIGEST
    assert stored.mark(ReadinessLevel.PREPARED) == admitted.mark(ReadinessLevel.PREPARED)


async def test_the_launch_policy_sets_the_minimum() -> None:
    strict = LaunchReadinessPolicy(worker_hosted=ReadinessLevel.DISCOVERED)
    lane = PreparingLane(frames=scripted_frames())
    stack, repository = _stack(lane, strict)
    result = await stack.service.turn(_turn(), RecordingSignals(stack.frames))

    settled = OperationExecutionResult.model_validate(result.operation_result)
    assert settled.failure_code == ENVIRONMENT_NOT_READY
    assert "start" not in lane.calls
    stored = await _stored(repository)
    assert stored is not None and stored.readiness is ReadinessLevel.PREPARED


async def test_without_a_composed_gate_nothing_is_recorded_or_refused() -> None:
    lane = ScriptedSessionLane(frames=scripted_frames())
    stack = lane_stack(lane)
    result = await stack.service.turn(_turn(), RecordingSignals(stack.frames))
    assert OperationExecutionResult.model_validate(result.operation_result).status == "completed"


async def test_a_lane_reads_back_once_its_session_exists_and_is_discovered() -> None:
    lane = ReadingBackLane(frames=scripted_frames())
    stack, repository = _stack(lane)
    result = await stack.service.turn(_turn(), RecordingSignals(stack.frames))

    assert result.done
    assert lane.calls.index("discover") > lane.calls.index("start")
    stored = await _stored(repository)
    assert stored is not None and stored.mark(ReadinessLevel.DISCOVERED) is not None
    frames = stack.frames._executions[_identity().harness_execution_id].frames.values()
    (frame,) = [item for item in frames if item.raw_kind == "materialization.discovered"]
    assert frame.kind is FrameKind.STATUS


async def test_a_failed_read_back_is_lost_evidence_and_the_turn_completes() -> None:
    lane = ReadingBackLane(frames=scripted_frames(), fail=True)
    stack, repository = _stack(lane)
    result = await stack.service.turn(_turn(), RecordingSignals(stack.frames))

    settled = OperationExecutionResult.model_validate(result.operation_result)
    assert settled.status == "completed"
    stored = await _stored(repository)
    assert stored is not None and stored.readiness is ReadinessLevel.PREPARED

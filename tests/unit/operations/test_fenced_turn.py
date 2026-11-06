"""Tracing Stage 3: a turn that finishes under a persisted Stop Fence (F-S2-9 follow-up).

An immediate cancel persists its Stop Fence before run control records the cancel (ADR-0008).
A turn that finishes after the fence settles `cancelled` with what it spent once the cancel
is journaled (R1-F4: with its cognition points), and is never settled `completed` while the
cancel is not journaled (R1-F1). The fence is the run's: it covers every unit of the run
whatever the unit's own execution generation (R1-F5). A failing fence read is not a fence
and never turns a finished turn into a zero-usage failure (R1-F2). A Temporal cancel that
reaches the fenced settlement through the heartbeat does not cut it off (R1-F8).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mission_control.application.execution.operations.operation_execution import (
    OperationStopFencePending,
    bind_operation_execution_request,
    settlement_budget_snapshot,
)
from mission_control.application.execution.operations.operation_progress import CURRENT_CANCEL_PROBE
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    OperationSettlement,
    RuntimeUsage,
)
from mission_control.domain.policies.contracts import ExecutionTarget, RunProjection
from mission_control.domain.policies.stop_fence import StopFence
from tests.fixtures.checkpoint_recovery import (
    TOKENS_PER_CALL,
    AcceptingAuthority,
    RecoveryHarness,
    recovery_harness,
    stage_recovery_unit,
)
from tests.fixtures.lane_bindings import lane_fields
from tests.unit.operations.test_rrm_008_cancellation import _liability, _settlements

SCOPE = "tenant-1"


class CancelNotJournaled(AcceptingAuthority):
    """Run control holds no accepted cancel (in transit, or rejected by the reducer)."""

    async def verify_cancellation(self, request: Any, binding: Any) -> None:
        del request, binding
        raise ValueError("run control journaled no cancel for a active Workflow Run")


class ProjectingAuthority(AcceptingAuthority):
    """An authority that exposes the run projection at a chosen execution-target generation."""

    def __init__(self, harness: RecoveryHarness, generation: int) -> None:
        self._harness = harness
        self._generation = generation

    async def run_projection(self, request_scope: str, run_id: str) -> RunProjection:
        run = await self._harness.run_control.get_run(request_scope, run_id)
        return run.model_copy(
            update={
                "execution_target": ExecutionTarget(
                    family="GoalDirected",
                    family_workflow_id=f"goal/{run_id}",
                    execution_generation=self._generation,
                )
            }
        )


class FailingFences(InMemoryStopFenceRepository):
    async def get(self, request_scope: str, run_id: str) -> StopFence | None:
        raise ConnectionError("stop fence store unavailable")


def _fence(run_id: str, generation: int = 1) -> StopFence:
    from datetime import UTC, datetime

    return StopFence(
        request_scope=SCOPE,
        run_id=run_id,
        generation=generation,
        command_id="immediate-cancel-1",
        reason="operator stop",
        requested_at=datetime.now(UTC),
    )


async def _harness(fences: InMemoryStopFenceRepository | None = None) -> RecoveryHarness:
    harness = await recovery_harness()
    harness.service._stop_fences = fences or InMemoryStopFenceRepository()
    return harness


def _fence_mid_turn(harness: RecoveryHarness, generation: int = 1) -> None:
    """The immediate cancel lands while the turn runs: its fence is persisted before the
    second (final) model call, which the scripted model still answers."""

    async def persist() -> None:
        fences = harness.service._stop_fences
        assert isinstance(fences, InMemoryStopFenceRepository)
        await fences.persist(_fence(harness.run_id, generation))

    harness.model.before_call(2, persist)


def _capture_settlement_points(harness: RecoveryHarness) -> list[tuple[Any, ...]]:
    captured: list[tuple[Any, ...]] = []
    original = harness.service._settle

    async def settle(*args: Any, **kwargs: Any) -> Any:
        captured.append(tuple(kwargs.get("points", ())))
        return await original(*args, **kwargs)

    harness.service._settle = settle  # type: ignore[method-assign]
    return captured


@pytest.mark.asyncio
async def test_a_turn_finished_under_a_journaled_fence_settles_cancelled_with_its_points() -> None:
    """R1-F4: fenced and journaled -> `cancelled`, with the usage of both completed calls,
    both Delivery Report milestones and the finished turn's cognition points."""

    harness = await _harness()
    request = await harness.request(stage_recovery_unit(harness.run_id))
    _fence_mid_turn(harness)
    points = _capture_settlement_points(harness)

    result = await harness.run(request)

    assert (result.status, result.failure_code) == ("cancelled", "cancelled")
    assert result.usage.amounts == {"tokens.total": 2 * TOKENS_PER_CALL}
    assert result.result_checkpoint is not None
    [settlement] = _settlements(harness, request)
    assert settlement.status == "cancelled"
    assert (await _liability(harness, request))["effect"] == "cancelled"
    [settled_points] = points
    assert settled_points, "the finished turn's cognition points reach the settlement"
    fences = harness.service._stop_fences
    assert isinstance(fences, InMemoryStopFenceRepository)
    report = await fences.report(SCOPE, harness.run_id)
    assert report is not None and report.state == "settled"
    assert report.provider_acknowledged_at is not None


@pytest.mark.asyncio
async def test_a_turn_fenced_without_a_journaled_cancel_is_never_completed() -> None:
    """R1-F1: the fence is persisted but the cancel is not journaled (in transit, or rejected
    by the reducer). The turn's output is not settled `completed` (it may be the fence's
    stop text); the attempt raises a retryable error and settles nothing."""

    harness = await _harness()
    harness.service._authority = CancelNotJournaled()
    request = await harness.request(stage_recovery_unit(harness.run_id))
    _fence_mid_turn(harness)

    with pytest.raises(OperationStopFencePending):
        await harness.run(request)

    assert _settlements(harness, request) == []
    assert (await _liability(harness, request))["effect_settled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fence_generation", "run_generation", "unit_generation", "expected"),
    [
        # The fence is the run's: a unit of any generation of a fenced run is fenced.
        (1, 1, 1, "journaled"),
        (1, 1, 2, "journaled"),
        # It covers its own run generation and every earlier one ...
        (2, 1, 1, "journaled"),
        # ... and never a later run generation.
        (1, 2, 1, None),
    ],
)
async def test_the_fence_is_matched_against_the_run_generation_not_the_unit_generation(
    fence_generation: int, run_generation: int, unit_generation: int, expected: str | None
) -> None:
    """R1-F5: `StopFence.covers` over the run's execution-target generation, the generation
    the writer stores; a unit's own `execution_generation` (advanced by
    `start_new_generation`) is not compared with it."""

    harness = await _harness()
    harness.service._authority = ProjectingAuthority(harness, run_generation)
    request = await harness.request(stage_recovery_unit(harness.run_id))
    fences = harness.service._stop_fences
    assert isinstance(fences, InMemoryStopFenceRepository)
    await fences.persist(_fence(harness.run_id, fence_generation))
    binding = bind_operation_execution_request(request)
    assert DeepAgentExecutionBinding.carried_by(binding) is not None
    binding = binding.model_copy(
        update={
            **lane_fields(
                DeepAgentExecutionBinding.carried_by(binding).model_copy(
                    update={"execution_generation": unit_generation}
                )
            )
        }
    )

    assert await harness.service._turn_fence(request, binding) == expected


@pytest.mark.asyncio
async def test_a_failing_fence_read_is_not_a_fence_and_keeps_the_turn() -> None:
    """R1-F2: the fence check runs after the turn; a transient error there used to settle
    `failed/runtime_failed` with zero usage and no capture. It is logged and the finished
    turn settles as it would without the check."""

    harness = await _harness(FailingFences())
    request = await harness.request(stage_recovery_unit(harness.run_id))

    result = await harness.run(request)

    assert result.status == "completed", result
    assert result.usage.amounts == {"tokens.total": 2 * TOKENS_PER_CALL}
    assert result.result_checkpoint is not None


@pytest.mark.asyncio
async def test_a_heartbeat_cancel_during_the_fenced_settlement_does_not_cut_it_off() -> None:
    """R1-F8: the fenced path runs exactly while the immediate cancel is in flight; a
    requested Temporal cancel delivered into the settlement's awaits is swallowed and the
    settlement completes once."""

    harness = await _harness()
    request = await harness.request(stage_recovery_unit(harness.run_id))
    _fence_mid_turn(harness)
    task: asyncio.Task[Any] | None = None
    original = harness.service._fence_milestone

    async def milestone(binding: Any, name: Any) -> None:
        if name == "provider_acknowledged":
            assert task is not None
            task.cancel()  # the heartbeat delivers Temporal's cancel here
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        await original(binding, name)

    harness.service._fence_milestone = milestone  # type: ignore[method-assign, assignment]
    token = CURRENT_CANCEL_PROBE.set(lambda: True)
    try:
        task = asyncio.create_task(harness.service.execute(request, harness.attempt(request)))
    finally:
        CURRENT_CANCEL_PROBE.reset(token)

    result = await task

    assert (result.status, result.failure_code) == ("cancelled", "cancelled")
    [settlement] = _settlements(harness, request)
    assert settlement.status == "cancelled"
    assert (await _liability(harness, request))["effect_settled"] is True


@pytest.mark.asyncio
async def test_a_unit_that_spends_exactly_its_limit_exhausted_nothing() -> None:
    """R1-F12: `exhausted` uses the stop rule's `>` over amounts plus pending external."""

    harness = await recovery_harness()
    request = await harness.request(stage_recovery_unit(harness.run_id))
    binding = bind_operation_execution_request(request)
    assert binding.budget_limits == {"tokens.total": 10}

    def snapshot(usage: RuntimeUsage) -> Any:
        settlement = OperationSettlement.model_validate(
            {
                "settlement_id": "settlement:budget",
                "binding_id": binding.binding_id,
                "status": "completed",
                "usage": usage,
                "settled_at": "2026-10-22T00:00:00+00:00",
            }
        )
        return settlement_budget_snapshot(binding, settlement)["exhausted"]

    assert snapshot(RuntimeUsage(amounts={"tokens.total": 10})) == []
    assert snapshot(RuntimeUsage(amounts={"tokens.total": 11})) == ["tokens.total"]
    assert snapshot(
        RuntimeUsage(amounts={"tokens.total": 6}, pending_external_amounts={"tokens.total": 5})
    ) == ["tokens.total"]

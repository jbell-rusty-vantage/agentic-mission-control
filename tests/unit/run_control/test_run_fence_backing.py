"""Tracing Stage 3: which Stop Fence ends a Deep Agents turn, and launch identity replays.

R1-F1: the fence of an immediate cancel is written before run control records the cancel
(ADR-0008); a cancel the reducer rejects leaves the fence behind (insert-only). The model-call
check (`KernelHookFenceGate.run_fence`) therefore ends the turn only on a fence backed by a
journaled cancel. R1-F5: the fence is the run's and is matched against the run's
execution-target generation, never a unit's generation. R1-F14 (an idempotent re-launch that
offers no Temporal run id is not an identity conflict) runs on the disposable database in
tests/integration/postgres/test_run_temporal_identity_postgres.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from mission_control.application.execution.boundary_interventions import (
    BoundaryInterventionService,
)
from mission_control.application.execution.stop_fence import (
    InMemoryStopFenceRepository,
    KernelHookFenceGate,
)
from mission_control.application.missions.service import MissionControlService
from mission_control.domain.policies.contracts import ExecutionTarget, RunProjection
from mission_control.domain.policies.stop_fence import (
    StopFence,
    run_fence_generation,
)
from tests.support.boundary_commands import TARGET, started
from tests.support.run_control import service
from tests.support.unit.run_control.stop_fence import _cancel, admin

SCOPE = "tenant-1"


def _fence(run_id: str, generation: int = 1) -> StopFence:
    return StopFence(
        request_scope=SCOPE,
        run_id=run_id,
        generation=generation,
        command_id="immediate-cancel-1",
        reason="operator stop",
        requested_at=datetime.now(UTC),
    )


class TargetRuns:
    """Run control's projection with a chosen execution-target generation."""

    def __init__(self, runs: Any, generation: int) -> None:
        self._runs = runs
        self._generation = generation

    async def get_run(self, request_scope: str, run_id: str) -> RunProjection:
        run = await self._runs.get_run(request_scope, run_id)
        return run.model_copy(
            update={
                "execution_target": ExecutionTarget(
                    family="StageGraph",
                    family_workflow_id=f"stagegraph/{run_id}",
                    execution_generation=self._generation,
                )
            }
        )


class FailingRuns:
    async def get_run(self, request_scope: str, run_id: str) -> RunProjection:
        raise ConnectionError("run control unavailable")


@pytest.mark.asyncio
async def test_an_orphaned_fence_does_not_end_the_turn_until_the_cancel_is_journaled() -> None:
    authority, _ = service()
    run_id = await started(authority, "mission-orphan-fence", TARGET)
    fences = InMemoryStopFenceRepository()
    # The fence of a cancel the reducer did not accept: written, never backed.
    await fences.persist(_fence(run_id))
    gate = KernelHookFenceGate(fences, runs=authority)
    assert await gate.run_fence(SCOPE, run_id) is None
    # Without the run-control read (a composition that does not wire it) the fence decides.
    assert await KernelHookFenceGate(fences).run_fence(SCOPE, run_id) is not None

    # The operator's immediate cancel is journaled: the run is cancelling, the turn ends.
    facade = MissionControlService(
        authority, BoundaryInterventionService(authority), request_scope=SCOPE, stop_fences=fences
    )
    version = (await facade.inspect(run_id, admin())).version
    receipt = await facade.command(run_id, _cancel(run_id, version, "immediate"), admin())
    assert receipt.admission.status == "accepted"
    reason = await gate.run_fence(SCOPE, run_id)
    assert reason is not None and "immediate cancel" in reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fence_generation", "run_generation", "fenced"),
    [(1, 1, True), (2, 1, True), (1, 2, False)],
)
async def test_run_fence_covers_the_run_generation(
    fence_generation: int, run_generation: int, fenced: bool
) -> None:
    authority, _ = service()
    run_id = await started(authority, f"mission-fence-gen-{fence_generation}", TARGET)
    fences = InMemoryStopFenceRepository()
    facade = MissionControlService(
        authority, BoundaryInterventionService(authority), request_scope=SCOPE, stop_fences=fences
    )
    version = (await facade.inspect(run_id, admin())).version
    receipt = await facade.command(run_id, _cancel(run_id, version, "immediate"), admin())
    assert receipt.admission.status == "accepted"
    # The writer stores the run's execution-target generation (1 without a target).
    stored = await fences.get(SCOPE, run_id)
    assert stored is not None
    assert stored.generation == run_fence_generation(await authority.get_run(SCOPE, run_id)) == 1
    if fence_generation != 1:
        await fences.persist(_fence(run_id, fence_generation))
    gate = KernelHookFenceGate(fences, runs=TargetRuns(authority, run_generation))
    assert (await gate.run_fence(SCOPE, run_id) is not None) is fenced


@pytest.mark.asyncio
async def test_a_failing_run_read_is_not_a_fence() -> None:
    fences = InMemoryStopFenceRepository()
    await fences.persist(_fence("run-1"))
    assert await KernelHookFenceGate(fences, runs=FailingRuns()).run_fence(SCOPE, "run-1") is None

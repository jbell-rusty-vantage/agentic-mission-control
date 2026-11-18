"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_goal_iteration_packet.py.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.context.pack_service import (
    ContextPackService,
    StaticModelBudgetProfiles,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.execution.operations.operation_execution import (
    InMemoryOperationBindingRepository,
)
from mission_control.domain.context.packet import ModelBudgetProfile
from mission_control.domain.policies.contracts import CommandStatus
from tests.support.journal import MemoryOperationJournal
from tests.support.journaled_goal_loop import (
    GoalComposition,
    admit_goal_run,
    compose_goal_directed,
    goal_blueprint,
    goal_model,
    goal_run_control,
    goal_start_action,
)
from tests.support.knowledge.stores import InMemoryStaging
from tests.support.run_control import command
from tests.support.unit.operations.ft_b2_stage_handoff import FakeArtifacts, FakeSelections


async def _composition(
    profile: ModelBudgetProfile | None = None,
) -> tuple[GoalComposition, str, FakeSelections]:
    run_control = goal_run_control()
    selections = FakeSelections()
    staging = InMemoryStaging()
    packs = ContextPackService(
        artifacts=FakeArtifacts({}, scope=None),
        selections=selections,
        staging=staging,
        profiles=StaticModelBudgetProfiles(default=profile) if profile else None,
    )
    composition = await compose_goal_directed(
        run_control=run_control,
        journal=MemoryOperationJournal(),
        lineage=CheckpointLineageService(InMemoryCheckpointLineageRepository()),
        results=InMemoryArtifactPayloadStore(),
        bindings=InMemoryOperationBindingRepository(),
        saver=InMemorySaver(),
        model=goal_model(),
        blueprint=goal_blueprint(),
        context_packs=packs,
        context_inputs=staging,
    )
    run_id = await admit_goal_run(run_control, "ft-b3-goal-packet")
    started = await run_control.execute(
        command(run_id, 1, "ft-b3-start", goal_start_action(run_id))
    )
    assert started.status == CommandStatus.ACCEPTED
    return composition, run_id, selections


def _executor_result(claim: Any, run_id: str) -> Any:
    from mission_control.domain.programs.contracts import GoalExecutionResult

    return GoalExecutionResult(
        identity=claim.identity,
        disposition="completed",
        operation_identity=f"{claim.identity.semantic_key}:executor",
        operation_binding_ref="binding:executor",
        session_id=claim.session_id,
        workspace_id=claim.workspace_namespace,
        writable_paths=("/goal/1/executor/work",),
        output_refs=("artifact:rrm016:record",),
    )

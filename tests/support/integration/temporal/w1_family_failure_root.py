"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_w1_family_failure_root.py.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ApplicationError

from mission_control.adapters.temporal.workflows.belllabs_run import BellLabsRunWorkflow
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.programs.contracts import (
    BellLabsRunInput,
    GoalDirectedRunInput,
    StageGraphRunInput,
)
from tests.support.integration.temporal.chain_start_idempotent import revision
from tests.support.integration.temporal.wp_bp_010_temporal import _blueprint
from tests.support.integration.temporal.wp_bp_010_temporal import _run_input as stage_run_input
from tests.support.unit.coordinator.root_result_materialization import SCOPE

QUEUE = "w1-family-failure-root"


@workflow.defn(name="belllabs.stagegraph", sandboxed=False)
class FailingFamily:
    """Fails at once with a typed application error."""

    @workflow.run
    async def run(self, run_input: StageGraphRunInput) -> None:
        raise ApplicationError("unit failed", type="goal_operation_unreported", non_retryable=True)


def _root(run_id: str) -> BellLabsRunInput:
    family_input = asdict(
        replace(stage_run_input(_blueprint()), run_id=run_id, request_scope=SCOPE)
    )
    return BellLabsRunInput(
        schema_version="mc.mission_run.v1",
        run_id=run_id,
        request_scope=SCOPE,
        effective_configuration_digest=family_input["effective_configuration_digest"],
        workflow_type_digest=family_input["workflow_type_digest"],
        family="StageGraph",
        family_task_queue=QUEUE,
        family_input=family_input,
    )


def goal_root(run_id: str) -> BellLabsRunInput:
    staged = _root(run_id)
    goal = revision(run_id)
    family_input = asdict(
        GoalDirectedRunInput(
            run_id=run_id,
            request_scope=SCOPE,
            effective_configuration_digest=staged.effective_configuration_digest,
            blueprint_digest=sha256_digest(GENERIC_GOAL_DIRECTED),
            blueprint=GENERIC_GOAL_DIRECTED.model_dump(mode="json"),
            envelope_digest=goal.envelope_digest,
            initial_revision=goal,
            workflow_type_digest=staged.workflow_type_digest,
        )
    )
    return replace(staged, family="GoalDirected", family_input=family_input)


def admitted_root(family: str, run_id: str) -> BellLabsRunInput:
    return _root(run_id) if family == "StageGraph" else goal_root(run_id)


@workflow.defn(name="mc.mission_run.v1", sandboxed=False)
class PrePatchMissionRun(BellLabsRunWorkflow):
    """The root as recorded before its patches (W1 D15 family-failure terminalization and the
    terminal-result materialization): it returned or raised its family's outcome directly."""

    @workflow.run
    async def run(self, run_input: BellLabsRunInput) -> Any:
        return await super().run(run_input)

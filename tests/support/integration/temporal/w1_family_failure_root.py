"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_w1_family_failure_root.py.
"""

from __future__ import annotations

from dataclasses import asdict, replace

from temporalio import workflow
from temporalio.exceptions import ApplicationError

from mission_control.domain.programs.contracts import BellLabsRunInput, StageGraphRunInput
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

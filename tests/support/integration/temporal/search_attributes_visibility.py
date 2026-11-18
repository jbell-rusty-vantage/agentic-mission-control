"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_search_attributes_visibility.py.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment

from mission_control.adapters.temporal.search_attributes import BELLLABS_SEARCH_ATTRIBUTE_KEYS
from mission_control.domain.execution.contracts import OperationWorkflowRequest
from mission_control.domain.graph_runtime.identities import RuntimeUnitIdentity
from mission_control.domain.programs.contracts import (
    StageGraphAdmissionActivityRequest,
    StageGraphAdmissionActivityResult,
)
from mission_control.domain.programs.runtime_units import stage_runtime_unit
from tests.support.integration.temporal.stage_graph_workflow_temporal import (
    FakeStageGraphActivities,
)


async def _start_local() -> WorkflowEnvironment:
    try:
        return await WorkflowEnvironment.start_local(
            search_attributes=BELLLABS_SEARCH_ATTRIBUTE_KEYS, dev_server_log_level="error"
        )
    except RuntimeError as error:
        pytest.skip(f"Temporal dev server is unavailable: {error}")


class UnitBoundStageGraphActivities(FakeStageGraphActivities):
    """The BP-010 fixture with each operation bound to its `CON-CP-RUNTIME-UNIT-V1`."""

    def __init__(self) -> None:
        super().__init__()
        self.operations: list[tuple[RuntimeUnitIdentity, OperationWorkflowRequest]] = []

    @activity.defn(name="stagegraph.admit_operation")
    async def admit(
        self, request: StageGraphAdmissionActivityRequest
    ) -> StageGraphAdmissionActivityResult:
        admitted = await FakeStageGraphActivities.admit(self, request)
        assert admitted.operation is not None
        unit = stage_runtime_unit(request.request_scope, request.proposal.identity)
        bound = OperationWorkflowRequest.model_validate(
            {
                **admitted.operation.model_dump(mode="python"),
                "operation": {
                    **admitted.operation.operation.model_dump(mode="python"),
                    "runtime_unit": unit,
                },
            }
        )
        self.operations.append((unit, bound))
        return replace(admitted, operation=bound)

    @property
    def functions(self) -> list[object]:
        return [
            self.initialize,
            self.admit,
            self.decide,
            self.apply_cycle,
            self.complete,
            self.execute_operation,
        ]

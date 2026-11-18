"""Builders, constants and fakes that other test files import.

Moved from tests/unit/run_control/test_run_launch.py.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.coordinator.launch import BlueprintFamily, WorkflowSubmission
from mission_control.domain.programs.contracts import StageGraphRunInput
from tests.fixtures.rrm009_production_stack import stage_blueprint
from tests.support.run_control import DIGEST, WORKFLOW_DIGEST

SCOPE = "tenant-1"


class RecordingSubmitter:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, BlueprintFamily, str | None]] = []

    async def submit(
        self,
        workflow_input: object,
        *,
        workflow_id: str,
        blueprint_family: BlueprintFamily,
        parent_run_id: str | None = None,
    ) -> WorkflowSubmission:
        self.submissions.append((workflow_id, blueprint_family, parent_run_id))
        return WorkflowSubmission(workflow_id=workflow_id, temporal_run_id="temporal-run-1")


def _input(run_id: str, *, version: int = 1, **overrides: Any) -> dict[str, Any]:
    graph = stage_blueprint()
    values = asdict(
        StageGraphRunInput(
            run_id=run_id,
            request_scope=SCOPE,
            effective_configuration_digest=DIGEST,
            workflow_type_digest=WORKFLOW_DIGEST,
            blueprint_digest=sha256_digest(graph),
            blueprint=graph.model_dump(mode="json"),
            initial_run_version=version,
            semantic_input_binding_ref="semantic-input:launch",
            # `request()` admits this baseline reservation.
            baseline_reservation={"tokens.total": 20},
        )
    )
    values.update(overrides)
    return values

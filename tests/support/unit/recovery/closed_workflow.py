"""Builders, constants and fakes that other test files import.

Moved from tests/unit/recovery/test_closed_workflow.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from mission_control.application.recovery.closed_workflow import (
    ClosedExecution,
    ClosedWorkflowEvidence,
    ClosedWorkflowRecovery,
    ProducerAuthority,
)
from mission_control.contracts.runtime_contracts import ClosedWorkflowRecoveryRequest
from mission_control.domain.policies.contracts import CancelAction, ExecutionTarget, StartAction
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    ProducerLiability,
    ResultDecision,
    StageGraphAcceptedProjection,
)
from tests.support.run_control import NOW, command, request, service


async def setup_recovery():
    controls, repository = service()
    admitted = await controls.admit(
        request().model_copy(
            update={
                "budget_envelope": request().budget_envelope.model_copy(
                    update={"baseline_reservations": {}}
                )
            }
        )
    )
    run_id = admitted.run_id
    assert run_id is not None
    target = ExecutionTarget(
        family="StageGraph", family_workflow_id="family", root_workflow_id="root"
    )
    await controls.execute(command(run_id, 1, "start", StartAction(execution_target=target)))
    await controls.execute(command(run_id, 2, "cancel", CancelAction()))
    family = StageGraphAcceptedProjection(
        ExecutionIdentity(run_id),
        1,
        3,
        producer_liabilities={
            "attempt": ProducerLiability(
                "attempt",
                "reservation",
                child_closed_or_quiesced=True,
                reservations_and_usage_settled=True,
                effects_settled=True,
                cancellation_reconciled=True,
                result_decision=ResultDecision.ADMIT,
            )
        },
    )
    authority = AsyncMock()
    authority.read.return_value = ProducerAuthority(
        family, "actual-admitted-request", ("producer",), "sha256:" + "e" * 64
    )
    observer = AsyncMock()
    observer.observe.return_value = ClosedWorkflowEvidence(
        "tenant-1",
        run_id,
        1,
        1,
        NOW,
        tuple(
            ClosedExecution(w, str(uuid4()), "FAILED", 16, "sha256:" + "f" * 64, True)
            for w in (target.root_workflow_id, "family", "producer")
        ),
    )
    recovery = ClosedWorkflowRecovery(controls, authority, observer, clock=lambda: NOW)
    body = ClosedWorkflowRecoveryRequest(request_id=uuid4(), expected_version=3)
    return recovery, controls, repository, authority, observer, body, run_id

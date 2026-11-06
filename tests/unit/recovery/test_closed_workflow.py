from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.unit.run_control.test_run_control import NOW, actor, command, request, service

from mission_control.application.recovery.closed_workflow import (
    ClosedExecution,
    ClosedWorkflowEvidence,
    ClosedWorkflowRecovery,
    ProducerAuthority,
)
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.runtime_contracts import ClosedWorkflowRecoveryRequest
from mission_control.domain.policies.contracts import (
    ActorContext,
    CancelAction,
    CommandStatus,
    ExecutionTarget,
    RunOutcome,
    StartAction,
)
from mission_control.domain.policies.errors import IdempotencyConflict
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    ProducerLiability,
    ResultDecision,
    StageGraphAcceptedProjection,
)


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


@pytest.mark.asyncio
async def test_real_reducer_cancelled_and_recoverable_evidence_idempotent():
    recovery, controls, _, authority, observer, body, run_id = await setup_recovery()
    result = await recovery.recover("tenant-1", run_id, body, actor())
    assert result.status == CommandStatus.ACCEPTED
    assert result.terminal_outcome == RunOutcome.CANCELLED
    transitions = await controls.list_transitions("tenant-1", run_id)
    retained = next(
        ref
        for ref in transitions[-1].evidence_refs
        if ref.startswith("closed-workflow-evidence:v1:")
    )
    envelope = json.loads(retained.removeprefix("closed-workflow-evidence:v1:"))
    assert envelope["run_id"] == run_id
    assert len(envelope["executions"]) == 3
    assert all(row["temporal_run_id"] and row["history_digest"] for row in envelope["executions"])
    assert await recovery.recover("tenant-1", run_id, body, actor()) == result
    assert observer.observe.await_count == 1
    assert authority.read.await_count == 2
    assert await recovery.result("tenant-1", run_id, str(body.request_id), actor()) == result
    with pytest.raises(IdempotencyConflict):
        await recovery.recover(
            "tenant-1", run_id, body.model_copy(update={"expected_version": 4}), actor()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stale", "foreign", "missing", "active", "no_latest"])
async def test_rejects_untrusted_or_incomplete_closed_evidence(change):
    recovery, controls, _, _, observer, body, run_id = await setup_recovery()
    evidence = observer.observe.return_value
    if change == "stale":
        evidence = replace(evidence, observed_at=NOW - timedelta(seconds=21))
    if change == "foreign":
        evidence = replace(evidence, run_id="other")
    if change == "missing":
        evidence = replace(evidence, executions=evidence.executions[:-1])
    if change == "active":
        evidence = replace(
            evidence,
            executions=(
                replace(evidence.executions[0], status="RUNNING"),
                *evidence.executions[1:],
            ),
        )
    if change == "no_latest":
        evidence = replace(
            evidence, executions=tuple(replace(item, latest=False) for item in evidence.executions)
        )
    observer.observe.return_value = evidence
    with pytest.raises(MissionControlRejected):
        await recovery.recover("tenant-1", run_id, body, actor())
    assert (await controls.get_run("tenant-1", run_id)).version == 3


@pytest.mark.asyncio
async def test_authority_drift_refuses_without_terminal_write():
    recovery, controls, _, authority, _, body, run_id = await setup_recovery()
    before = authority.read.return_value
    authority.read.side_effect = [before, replace(before, fingerprint="changed")]
    with pytest.raises(MissionControlRejected, match="producer authority changed"):
        await recovery.recover("tenant-1", run_id, body, actor())
    assert (await controls.get_run("tenant-1", run_id)).version == 3


@pytest.mark.asyncio
async def test_permission_before_observer_and_strict_request():
    recovery, _, _, authority, observer, body, run_id = await setup_recovery()
    with pytest.raises(MissionControlRejected, match="required"):
        await recovery.recover(
            "tenant-1", run_id, body, ActorContext(actor_id="unprivileged", permissions=frozenset())
        )
    authority.read.assert_not_awaited()
    observer.observe.assert_not_awaited()
    with pytest.raises(ValidationError):
        ClosedWorkflowRecoveryRequest.model_validate(
            {**body.model_dump(), "cancellation_settled": True}
        )


@pytest.mark.asyncio
async def test_run_head_mutation_after_observer_is_refused_by_existing_cas():
    recovery, controls, _, _, observer, body, run_id = await setup_recovery()

    async def concurrent_cancel(_evidence):
        await controls.execute(command(run_id, 3, "concurrent", CancelAction()))

    observer.recheck.side_effect = concurrent_cancel
    result = await recovery.recover("tenant-1", run_id, body, actor())
    assert result.status != CommandStatus.ACCEPTED
    assert (await controls.get_run("tenant-1", run_id)).terminal_outcome is None

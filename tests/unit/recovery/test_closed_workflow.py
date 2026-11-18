from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError
from tests.support.run_control import NOW, actor, command
from tests.support.unit.recovery.closed_workflow import setup_recovery

from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.runtime_contracts import ClosedWorkflowRecoveryRequest
from mission_control.domain.policies.contracts import (
    ActorContext,
    CancelAction,
    CommandStatus,
    RunOutcome,
)
from mission_control.domain.policies.errors import IdempotencyConflict


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

"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_workflow_system_cancellation.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from temporalio import activity
from temporalio.client import WorkflowHandle

from mission_control.application.programs.service import orchestration_lifecycle_actor
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    LifecycleCommand,
    RecordUsageAction,
    RunPhase,
    TerminalizationProposal,
    TerminalizeAction,
)
from mission_control.domain.programs.contracts import (
    StageGraphCompletionActivityRequest,
    StageGraphCompletionActivityResult,
)
from tests.support.integration.temporal.rrm_007_boundary_interventions import (
    Authority,
    GovernedStageGraphActivities,
    until,
)
from tests.support.journaled_goal_loop import SCOPE
from tests.support.temporal import cancelled_operation_result, wait_heartbeating

BASELINE = {"tokens.total": 20}
# The fixture families' operation heartbeat timeout: a cancel reaches the running fake
# `operation.execute` on its next heartbeat (it heartbeats while it waits).
CANCEL_HEARTBEAT_SECONDS = 5


class CancellableStageGraphActivities(GovernedStageGraphActivities):
    """The RRM-007 StageGraph harness plus the fixture `operation.cancel` of a cancelled unit."""

    def __init__(self, authority: Authority) -> None:
        super().__init__(authority, gate_fast_on_slow=False)
        self.operation_heartbeat_timeout_seconds = CANCEL_HEARTBEAT_SECONDS
        self.cancel_settlements: list[str] = []
        self.fast_release = asyncio.Event()
        self.fast_cancelled = asyncio.Event()
        # Re-review edge case: the number of `operation.cancel` calls per stage that report the
        # unit's generation superseded (`in_doubt`, no settlement) before it settles.
        self.superseded_reports: dict[str, int] = {}

    @activity.defn(name="operation.execute")
    async def execute_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        operation_id = str(request["identity"]["operation_id"])
        if ":stage:fast:" in operation_id:
            # Held by the test so that the join never releases before the cancel lands.
            try:
                await wait_heartbeating(self.fast_release)
            except asyncio.CancelledError:
                self.fast_cancelled.set()
                raise
            return {"output_refs": ["artifact:fast"]}
        if ":stage:slow:" in operation_id:
            self.slow_started.set()
            try:
                await wait_heartbeating(self.slow_release)
            except asyncio.CancelledError:
                # The cancel reached the running Activity (heartbeat or worker shutdown).
                self.slow_cancelled.set()
                raise
            self.slow_completed.set()
            return {"output_refs": ["artifact:slow"]}
        return await super().execute_operation(request)

    @activity.defn(name="operation.cancel")
    async def cancel_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        operation_id = str(request["identity"]["operation_id"])
        self.cancel_settlements.append(operation_id)
        for stage, remaining in self.superseded_reports.items():
            if f":stage:{stage}:" in operation_id and remaining > 0:
                self.superseded_reports[stage] = remaining - 1
                return {
                    "binding_id": f"binding:{operation_id}",
                    "semantic_attempt_key": str(request["identity"]),
                    "status": "in_doubt",
                    "failure_code": "generation_superseded",
                    "failure_message": "an accepted generation boundary superseded it",
                    "reconciliation_incident_id": "incident:fixture:superseded",
                }
        return cancelled_operation_result(request)

    @activity.defn(name="stagegraph.complete")
    async def complete(
        self, request: StageGraphCompletionActivityRequest
    ) -> StageGraphCompletionActivityResult:
        """The terminal proposal through the real run control (the fixture operations hold
        no reservations; the fixture admission's baseline is released here first)."""

        return await terminalize_through_run_control(self.authority.run_control, request)


async def terminalize_through_run_control(
    run_control: Any, request: StageGraphCompletionActivityRequest
) -> StageGraphCompletionActivityResult:
    scope, run_id = request.request_scope, request.run_id
    run = await run_control.get_run(scope, run_id)
    budget = await run_control.get_budget(scope, run_id)
    if "baseline" in budget.reservations:
        released = await run_control.execute(
            LifecycleCommand(
                command_id=f"stagegraph:{run_id}:release-baseline",
                idempotency_issuer=request.idempotency_issuer,
                request_scope=scope,
                run_id=run_id,
                expected_run_version=run.version,
                actor=orchestration_lifecycle_actor(),
                action=RecordUsageAction(
                    usage_id="stagegraph-usage:baseline",
                    reservation_id="baseline",
                    actual_amounts={},
                    release_amounts=dict(budget.reservations["baseline"]),
                ),
                reason="Release the fixture baseline before the terminal proposal",
                occurred_at=request.occurred_at,
                correlation_id=request.correlation_id,
            )
        )
        assert released.status == CommandStatus.ACCEPTED, released.reason_code
        run = await run_control.get_run(scope, run_id)
        budget = await run_control.get_budget(scope, run_id)
    effects = await run_control.get_effects(scope, run_id)
    evidence_payload = [
        item.model_dump(mode="json")
        for item in sorted(run.accepted_obligation_evidence, key=lambda item: item.obligation_ref)
    ]
    accepted_refs = {item.obligation_ref for item in run.accepted_obligation_evidence}
    proposal = TerminalizationProposal(
        proposal_id=f"stagegraph-fixture:{run_id}:v{run.version}",
        expected_run_version=run.version,
        workflow_type_digest=run.workflow_type_ref.digest,
        obligation_revision=run.obligation_revision,
        evidence_frontier_digest=run.evidence_frontier_digest,
        accepted_obligation_evidence_digest=sha256_digest(evidence_payload),
        proposing_execution_binding_ref="stagegraph-fixture",
        required_obligations_accepted=run.required_obligation_refs <= accepted_refs,
        valid_output_refs=request.proposal.valid_output_refs,
        cancellation_settled=request.proposal.cancelled,
        budget_settled=(
            not any(budget.reserved.values()) and not any(budget.pending_settlement.values())
        ),
        effects_settled=all(claim.settlement is not None for claim in effects.claims.values()),
        pending_wait_or_link_ids=(),
        proposed_at=request.occurred_at,
        finalization_plan=run.finalization_plan,
        output_omission_reason=run.finalization_omission_reason,
    )
    result = await run_control.execute(
        LifecycleCommand(
            command_id=f"stagegraph:{run_id}:terminalize:v{run.version}",
            idempotency_issuer=request.idempotency_issuer,
            request_scope=scope,
            run_id=run_id,
            expected_run_version=run.version,
            actor=orchestration_lifecycle_actor(),
            action=TerminalizeAction(proposal=proposal),
            reason="Fixture StageGraph terminal proposal through run control",
            occurred_at=request.occurred_at,
            correlation_id=request.correlation_id,
        )
    )
    return StageGraphCompletionActivityResult(
        accepted=result.status == CommandStatus.ACCEPTED,
        terminal_outcome=result.terminal_outcome,
        resulting_run_version=result.resulting_run_version,
        reason_code=result.reason_code,
    )


async def _cancel(authority: Authority, run_id: str, command_id: str = "cancel") -> Any:
    accepted = await authority.intervene(run_id, command_id, CancelAction())
    assert accepted.phase == RunPhase.CANCELLING
    status = await authority.run_control.get_boundary_command(SCOPE, run_id, "operator", command_id)
    assert status is not None
    if status.command.target.kind != "run_control":
        assert status.command.target.sequence_space == "cancel"
    return status


async def _await_completion(handle: WorkflowHandle[Any, Any], *, seconds: float) -> Any:
    """Wait for the execution to close, then read its result (the time-skipping server's
    long poll can return without a close event while a workflow is still running)."""

    async def closed() -> bool:
        description = await handle.describe()
        return description.status is not None and description.status.name != "RUNNING"

    await until(closed, seconds=seconds)
    return await handle.result()

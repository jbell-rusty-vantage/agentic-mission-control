"""Close a governed cancellation that has never admitted a family execution target."""

from typing import Literal

from mission_control.application.execution.service import RunControlService
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import (
    ActorContext,
    CommandStatus,
    LifecycleCommand,
    RecordUsageAction,
    RunPhase,
    TerminalizationProposal,
    TerminalizeAction,
)


class UnstartedRunCancellation:
    """Only release an unused admission baseline; all other liabilities retain their owner."""

    def __init__(self, run_control: RunControlService, actor: ActorContext) -> None:
        self._control, self._actor = run_control, actor

    async def close(self, scope: str, run_id: str) -> Literal["closed", "execution_owned"]:
        base = f"unstarted-cancellation:{run_id}"
        for _ in range(8):
            run = await self._control.get_run(scope, run_id)
            if run.phase == RunPhase.TERMINAL:
                if run.terminal_outcome != "cancelled":
                    raise ValueError("unstarted cancellation found another terminal outcome")
                return "closed"
            if run.execution_target is not None:
                return "execution_owned"
            if run.phase != RunPhase.CANCELLING:
                raise ValueError("unstarted cancellation requires accepted cancellation")
            transitions = await self._control.list_transitions(scope, run_id)
            if not transitions or transitions[-1].resulting_version != run.version:
                continue
            if any(
                row.resulting_phase not in {RunPhase.PENDING, RunPhase.CANCELLING}
                for row in transitions
            ):
                return "execution_owned"  # historical target-less executions also own their saga
            budget = await self._control.get_budget(scope, run_id)
            effects = await self._control.get_effects(scope, run_id)
            if (
                effects.claims
                or any(budget.consumed.values())
                or any(budget.pending_settlement.values())
                or budget.outstanding_usage_ids
                or any(
                    name != "baseline" and any(amounts.values())
                    for name, amounts in budget.reservations.items()
                )
                or run.accepted_operation_settlement_evidence
                or run.async_children
                or run.accepted_output_evidence
                or run.finalization_plan is not None
            ):
                raise ValueError("unstarted cancellation has execution liabilities; owner required")
            remaining = {
                key: value
                for key, value in budget.reservations.get("baseline", {}).items()
                if value > 0
            }
            action: RecordUsageAction | TerminalizeAction
            if remaining:
                action = RecordUsageAction(
                    usage_id=f"{base}:baseline",
                    actual_amounts={},
                    reservation_id="baseline",
                    release_amounts=remaining,
                )
                suffix = "release-baseline"
            else:
                if any(budget.reserved.values()):
                    raise ValueError("unstarted cancellation has unattributed reserved budget")
                action = TerminalizeAction(
                    proposal=TerminalizationProposal(
                        proposal_id=f"{base}:v{run.version}",
                        expected_run_version=run.version,
                        workflow_type_digest=run.workflow_type_ref.digest,
                        obligation_revision=run.obligation_revision,
                        evidence_frontier_digest=run.evidence_frontier_digest,
                        accepted_obligation_evidence_digest=sha256_digest(
                            [
                                item.model_dump(mode="json")
                                for item in sorted(
                                    run.accepted_obligation_evidence,
                                    key=lambda item: item.obligation_ref,
                                )
                            ]
                        ),
                        proposing_execution_binding_ref=f"unstarted-run:{run_id}",
                        required_obligations_accepted=run.required_obligation_refs
                        <= {item.obligation_ref for item in run.accepted_obligation_evidence},
                        cancellation_settled=True,
                        budget_settled=True,
                        effects_settled=True,
                        proposed_at=run.updated_at,
                    )
                )
                suffix = "terminalize"
            result = await self._control.execute(
                LifecycleCommand(
                    command_id=f"{base}:{suffix}:v{run.version}",
                    idempotency_issuer="chain-unstarted-cancellation",
                    request_scope=scope,
                    run_id=run_id,
                    expected_run_version=run.version,
                    actor=self._actor,
                    action=action,
                    reason="Settle governed cancellation of an admitted run with no execution",
                    evidence_refs=(f"unstarted-run:{run_id}",),
                    occurred_at=run.updated_at,
                    correlation_id=base,
                )
            )
            if result.status == CommandStatus.STALE:
                continue
            if result.status != CommandStatus.ACCEPTED:
                raise RuntimeError(f"unstarted cancellation refused: {result.reason_code}")
            if suffix == "terminalize":
                return "closed"
        raise RuntimeError("unstarted cancellation remained concurrently changing")

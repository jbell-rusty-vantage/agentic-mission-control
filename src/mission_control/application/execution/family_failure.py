"""Terminalize a run whose family workflow ended without terminalizing it (W1 D15).

The Mission Control root calls this (activity `coordinator.terminalize_failed_family`) when
its family workflow failed, timed out, was cancelled or was terminated. It never infers a
success: it releases the run's unused admission-time `baseline` reservation (the family that
would have released it is gone) and proposes terminalization with the typed cause as the
execution failure, so an active run ends `failed` and a cancelling one `cancelled`. The
reducer decides from its own authoritative facts; a unit still settling keeps the run open
(`FamilyFailureLiabilityPending`, retried by the activity), any other refusal is returned
typed for the operator.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import (
    ActorContext,
    BudgetState,
    CommandResult,
    CommandStatus,
    EffectLedgerState,
    LifecycleCommand,
    RecordUsageAction,
    RunPhase,
    RunProjection,
    TerminalizationProposal,
    TerminalizeAction,
    outstanding_liabilities,
)
from mission_control.domain.programs.family_failure import (
    BUDGET_UNSETTLED_AT_FAILURE,
    FAMILY_FAILURE_LIABILITY_REJECTIONS,
    FAMILY_FAILURE_STALE_REJECTIONS,
    LIABILITY_TERMINALIZATION_ATTEMPT,
    LIABILITY_TERMINALIZED_REJECTIONS,
    FamilyFailureTerminalizationRequest,
    FamilyFailureTerminalizationResult,
)

_LOG = logging.getLogger(__name__)
ISSUER = "mc.family_failure.v1"
STALE_ATTEMPTS = 4
# The liability names and reservation records a terminal command's evidence carries.
MAX_LIABILITY_EVIDENCE = 64


class FamilyFailureRunControl(Protocol):
    async def get_run(self, request_scope: str, run_id: str) -> RunProjection: ...

    async def get_budget(self, request_scope: str, run_id: str) -> BudgetState: ...

    async def get_effects(self, request_scope: str, run_id: str) -> EffectLedgerState: ...

    async def get_command_result(
        self, request_scope: str, run_id: str, idempotency_issuer: str, command_id: str
    ) -> CommandResult | None: ...

    async def execute(self, command: LifecycleCommand) -> CommandResult: ...


class FamilyFailureLiabilityPending(RuntimeError):
    """A liability another owner settles remains (retryable): the run stays open meanwhile."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(f"family failure terminalization waits for: {reason_code}")
        self.reason_code = reason_code


class FamilyFailureTerminalization:
    def __init__(self, run_control: FamilyFailureRunControl, actor: ActorContext) -> None:
        self._run_control = run_control
        self._actor = actor

    async def terminalize(
        self, request: FamilyFailureTerminalizationRequest, *, attempt: int = 1
    ) -> FamilyFailureTerminalizationResult:
        """Idempotent per (run version, activity attempt): a retried attempt replays the same
        command identity with the same payload."""

        issuer = json.dumps([ISSUER, request.run_id], separators=(",", ":"))
        base = f"family-failure:{request.run_id}:epoch:{request.execution_epoch}"
        reason_code = "stale_run_version"
        for _ in range(STALE_ATTEMPTS):
            run = await self._run_control.get_run(request.request_scope, request.run_id)
            if run.phase == RunPhase.TERMINAL:
                return FamilyFailureTerminalizationResult(
                    accepted=True,
                    resulting_run_version=run.version,
                    terminal_outcome=run.terminal_outcome.value if run.terminal_outcome else "",
                    reason_code="already_terminal",
                )
            target = run.execution_target
            if target is not None and target.execution_epoch != request.execution_epoch:
                return FamilyFailureTerminalizationResult(
                    accepted=False,
                    resulting_run_version=run.version,
                    reason_code="stale_execution_epoch",
                )
            released = await self._release_baseline(request, run, issuer, base)
            if released is not None:
                if released.status == CommandStatus.STALE:
                    continue
                if released.status != CommandStatus.ACCEPTED:
                    return FamilyFailureTerminalizationResult(
                        accepted=False,
                        resulting_run_version=released.resulting_run_version,
                        reason_code=f"baseline_release_{released.reason_code}",
                    )
                run = await self._run_control.get_run(request.request_scope, request.run_id)
            result = await self._run_control.execute(
                LifecycleCommand(
                    command_id=f"{base}:terminalize:v{run.version}:a{attempt}",
                    idempotency_issuer=issuer,
                    request_scope=request.request_scope,
                    run_id=request.run_id,
                    expected_run_version=run.version,
                    actor=self._actor,
                    action=TerminalizeAction(proposal=_proposal(run, request, attempt)),
                    reason=(
                        f"The {request.family} family workflow ended without terminalizing "
                        f"the run ({request.cause})"
                    ),
                    evidence_refs=(
                        f"family-workflow:{request.family_workflow_id}",
                        f"family-failure-cause:{request.cause}",
                        f"family-failure-message:{request.cause_digest}",
                    ),
                    occurred_at=request.occurred_at,
                    correlation_id=base,
                )
            )
            if result.status == CommandStatus.ACCEPTED:
                return FamilyFailureTerminalizationResult(
                    accepted=True,
                    resulting_run_version=result.resulting_run_version,
                    terminal_outcome=(
                        result.terminal_outcome.value if result.terminal_outcome else ""
                    ),
                )
            reason_code = result.reason_code
            stale = result.status == CommandStatus.STALE
            if stale or reason_code in FAMILY_FAILURE_STALE_REJECTIONS:
                continue
            if (
                reason_code in LIABILITY_TERMINALIZED_REJECTIONS
                and attempt >= LIABILITY_TERMINALIZATION_ATTEMPT
                and await self._unchanged_since_previous_attempt(
                    request, run, issuer, base, attempt
                )
            ):
                closed = await self._terminalize_with_liabilities(
                    request, run, issuer, base, attempt
                )
                if closed is not None:
                    if closed.status == CommandStatus.ACCEPTED:
                        return FamilyFailureTerminalizationResult(
                            accepted=True,
                            resulting_run_version=closed.resulting_run_version,
                            terminal_outcome=(
                                closed.terminal_outcome.value if closed.terminal_outcome else ""
                            ),
                            reason_code=BUDGET_UNSETTLED_AT_FAILURE,
                        )
                    reason_code = closed.reason_code
                    if closed.status == CommandStatus.STALE or (
                        reason_code in FAMILY_FAILURE_STALE_REJECTIONS
                    ):
                        continue
            if reason_code in FAMILY_FAILURE_LIABILITY_REJECTIONS:
                raise FamilyFailureLiabilityPending(reason_code)
            return FamilyFailureTerminalizationResult(
                accepted=False,
                resulting_run_version=result.resulting_run_version,
                reason_code=reason_code,
            )
        raise FamilyFailureLiabilityPending(reason_code)

    async def _unchanged_since_previous_attempt(
        self,
        request: FamilyFailureTerminalizationRequest,
        run: RunProjection,
        issuer: str,
        base: str,
        attempt: int,
    ) -> bool:
        """W1 D26 review S2: escalate only when the previous attempt was refused for a
        liability at this same run version. Every budget and effect change is a lifecycle
        command that moves the version, so a slow but progressing settlement keeps waiting
        (within the root's retry bound) instead of being closed early."""

        previous = await self._run_control.get_command_result(
            request.request_scope,
            request.run_id,
            issuer,
            f"{base}:terminalize:v{run.version}:a{attempt - 1}",
        )
        return (
            previous is not None
            and previous.status == CommandStatus.REJECTED
            and previous.reason_code in LIABILITY_TERMINALIZED_REJECTIONS
        )

    async def _terminalize_with_liabilities(
        self,
        request: FamilyFailureTerminalizationRequest,
        run: RunProjection,
        issuer: str,
        base: str,
        attempt: int,
    ) -> CommandResult | None:
        """W1 D26: close the run naming every unsettled reservation and effect as a terminal
        liability; nothing is settled or released on the unit's behalf. The evidence records
        each outstanding reservation's amounts for operator reconciliation."""

        budget = await self._run_control.get_budget(request.request_scope, request.run_id)
        effects = await self._run_control.get_effects(request.request_scope, request.run_id)
        liabilities = outstanding_liabilities(budget, effects)
        if not liabilities:
            return None
        records = _liability_records(budget, effects)
        recorded = records[:MAX_LIABILITY_EVIDENCE]
        named = tuple(f"terminal-liability:{name}" for name in liabilities)
        truncated = max(len(records) - len(recorded), 0) + max(
            len(named) - MAX_LIABILITY_EVIDENCE, 0
        )
        if truncated:
            _LOG.warning(
                "terminal liability evidence of run %s truncated by %d records; the run's "
                "operator_reconciliation waits name every liability",
                request.run_id,
                truncated,
            )
        proposal = _proposal(run, request, attempt).model_copy(
            update={
                "proposal_id": f"{base}:liability:v{run.version}:a{attempt}",
                "unsettled_liabilities": liabilities,
                "budget_settled": False,
                "effects_settled": False,
            }
        )
        if run.phase != RunPhase.CANCELLING:
            proposal = proposal.model_copy(
                update={
                    "execution_failure_refs": (
                        *proposal.execution_failure_refs,
                        BUDGET_UNSETTLED_AT_FAILURE,
                    )
                }
            )
        return await self._run_control.execute(
            LifecycleCommand(
                command_id=f"{base}:terminalize-liability:v{run.version}:a{attempt}",
                idempotency_issuer=issuer,
                request_scope=request.request_scope,
                run_id=request.run_id,
                expected_run_version=run.version,
                actor=self._actor,
                action=TerminalizeAction(
                    proposal=TerminalizationProposal.model_validate(proposal.model_dump())
                ),
                reason=(
                    f"The {request.family} family workflow ended without terminalizing the run "
                    f"({request.cause}); its unsettled budget and effects stay liabilities for "
                    "operator reconciliation"
                ),
                evidence_refs=(
                    f"family-workflow:{request.family_workflow_id}",
                    f"family-failure-cause:{request.cause}",
                    f"family-failure-message:{request.cause_digest}",
                    *named[:MAX_LIABILITY_EVIDENCE],
                    *recorded,
                    *((f"terminal-liability-evidence-truncated:{truncated}",) if truncated else ()),
                ),
                occurred_at=request.occurred_at,
                correlation_id=base,
            )
        )

    async def _release_baseline(
        self,
        request: FamilyFailureTerminalizationRequest,
        run: RunProjection,
        issuer: str,
        base: str,
    ) -> CommandResult | None:
        """Release what remains of the admission-time baseline (the family's own release
        never ran); None when nothing remains (released earlier, or never held)."""

        budget = await self._run_control.get_budget(request.request_scope, request.run_id)
        remaining = {
            dimension: amount
            for dimension, amount in budget.reservations.get("baseline", {}).items()
            if amount > 0
        }
        if not remaining:
            return None
        return await self._run_control.execute(
            LifecycleCommand(
                command_id=f"{base}:baseline:v{run.version}",
                idempotency_issuer=issuer,
                request_scope=request.request_scope,
                run_id=request.run_id,
                expected_run_version=run.version,
                actor=self._actor,
                action=RecordUsageAction(
                    usage_id=f"family-failure-usage:{request.run_id}:baseline",
                    actual_amounts={},
                    reservation_id="baseline",
                    release_amounts=remaining,
                ),
                reason="Release the baseline reservation of a family that ended unterminalized",
                evidence_refs=(f"family-workflow:{request.family_workflow_id}",),
                occurred_at=request.occurred_at,
                correlation_id=base,
            )
        )


def _liability_records(budget: BudgetState, effects: EffectLedgerState) -> tuple[str, ...]:
    """The amounts and identities each terminal liability is recorded with (review S1)."""

    def dump(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    records = [
        f"{BUDGET_UNSETTLED_AT_FAILURE}:reservation:{reservation_id}:{dump(amounts)}"
        for reservation_id, amounts in sorted(budget.reservations.items())
        if any(amount > 0 for amount in amounts.values())
    ]
    pending = {key: value for key, value in budget.pending_settlement.items() if value > 0}
    if pending:
        records.append(f"{BUDGET_UNSETTLED_AT_FAILURE}:pending_settlement:{dump(pending)}")
    records.extend(
        f"{BUDGET_UNSETTLED_AT_FAILURE}:effect:{effect_id}:"
        + dump(
            {
                "operation_ref": claim.operation_ref,
                "reservation_id": claim.reservation_id,
                "disposition": claim.disposition.value,
            }
        )
        for effect_id, claim in sorted(effects.claims.items())
        if claim.settlement is None
    )
    return tuple(records)


def _proposal(
    run: RunProjection, request: FamilyFailureTerminalizationRequest, attempt: int
) -> TerminalizationProposal:
    cancelling = run.phase == RunPhase.CANCELLING
    return TerminalizationProposal(
        proposal_id=(
            f"family-failure:{request.run_id}:epoch:{request.execution_epoch}:"
            f"v{run.version}:a{attempt}"
        ),
        expected_run_version=run.version,
        workflow_type_digest=run.workflow_type_ref.digest,
        obligation_revision=run.obligation_revision,
        evidence_frontier_digest=run.evidence_frontier_digest,
        accepted_obligation_evidence_digest=sha256_digest(
            [
                item.model_dump(mode="json")
                for item in sorted(
                    run.accepted_obligation_evidence, key=lambda item: item.obligation_ref
                )
            ]
        ),
        proposing_execution_binding_ref=f"family-workflow:{request.family_workflow_id}",
        required_obligations_accepted=run.required_obligation_refs
        <= {item.obligation_ref for item in run.accepted_obligation_evidence},
        # A cancelling run ends `cancelled` (the reducer's rule); any other run fails with the
        # typed cause, never completes: the family that would have proved completion is gone.
        execution_failure_refs=() if cancelling else (f"family_workflow_failed:{request.cause}",),
        valid_output_refs=tuple(
            sorted(
                {item.output_ref for item in run.accepted_output_evidence}
                | set(run.finalization_output_refs)
            )
        ),
        cancellation_settled=cancelling,
        budget_settled=True,
        effects_settled=True,
        proposed_at=request.occurred_at,
        finalization_plan=run.finalization_plan,
        output_omission_reason=run.finalization_omission_reason,
    )


__all__ = [
    "FamilyFailureLiabilityPending",
    "FamilyFailureRunControl",
    "FamilyFailureTerminalization",
]

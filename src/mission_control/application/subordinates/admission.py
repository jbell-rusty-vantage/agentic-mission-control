"""Governed check-time admission of async child results (OVE-184; OUTPUT-CONTRACTS §§10-11).

The parent's ``check_async_task`` path calls :meth:`CheckTimeAdmission.admit` for a child it
reconciled. Admission is the same governed decision the parent boundary makes
(:mod:`parent_completion`), moved to the moment the parent asks, so usable output reaches the
parent's cognition while it still runs:

1. **Audience**: the asking parent must be the child's spawning parent (run, binding) and the
   child must run under the exact contract digest the parent sealed. Anything else refuses;
   a foreign or superseded child's text never reaches this parent.
2. **Completion is not admission**: an active or in-doubt child stays pending.
3. **One decision per child**: a link already decided is read back (no second decision, no
   second index entry); an undecided completed child is decided through the contract's
   registered admission policy with the parent's live generation, so a late or superseded
   result is refused by the service's own fence. A policy the deployment does not register
   decides nothing (the child stays pending, exactly as at the parent boundary).
4. An admitted result yields the exact text and its ``child_result_index`` entry. Admission
   never submits, assesses or fulfills anything: the parent's obligations are its own, and
   only an explicit exact adoption (``adoption.py``) offers the output to one of them.

Settlement stays at the parent boundary, after cognition: a child admitted here is settled
there exactly once (``AsyncChildCompletion`` skips the decision it finds).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from mission_control.application.subordinates.parent_completion import AdmissionRule
from mission_control.application.subordinates.service import (
    AsyncSubagentError,
    AsyncSubagentService,
)
from mission_control.domain.execution.async_child_admission import (
    ADMITTED_DECISIONS,
    ChildAdmission,
    PendingReason,
    RefusedReason,
    child_result_index_entry,
)
from mission_control.domain.execution.contracts import (
    AsyncSubagentContract,
    AsyncSubagentExecution,
    AsyncSubagentLifecycle,
    OperationExecutionBinding,
    ParentAsyncSubagentLink,
)

_ENDED_WITHOUT_RESULT = frozenset(
    {
        AsyncSubagentLifecycle.FAILED,
        AsyncSubagentLifecycle.CANCELLED,
        AsyncSubagentLifecycle.ORPHANED,
    }
)


class CheckTimeAdmission:
    """The parent's governed check-time admission (see the module doc)."""

    def __init__(
        self,
        service: AsyncSubagentService,
        *,
        policies: Mapping[str, AdmissionRule],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._policies = dict(policies)
        self._clock = clock or (lambda: datetime.now(UTC))

    async def admit(
        self,
        parent: OperationExecutionBinding,
        contract: AsyncSubagentContract,
        execution: AsyncSubagentExecution,
        *,
        current_generation: int,
    ) -> ChildAdmission:
        scope = parent.request_scope
        child_id = execution.child_execution_id
        if execution.parent_run_id != parent.run_id or (
            execution.parent_binding_id != parent.binding_id
        ):
            return self._refused(execution, "audience_mismatch")
        if execution.contract_digest != contract.contract_digest:
            return self._refused(execution, "contract_digest_mismatch")
        if execution.lifecycle == AsyncSubagentLifecycle.IN_DOUBT:
            return self._pending(execution, "child_in_doubt")
        if execution.lifecycle in _ENDED_WITHOUT_RESULT:
            return self._refused(execution, "no_result")
        if execution.lifecycle != AsyncSubagentLifecycle.COMPLETED:
            return self._pending(execution, "child_active")
        link = await self._service.link(scope, child_id)
        newly_decided = False
        if link.result_decision is None:
            # Exactly once under concurrent checks (review B2): only the writer that moves the
            # link from undecided to decided reports `newly_decided`.
            rule = self._policies.get(link.result_admission_policy_ref)
            if rule is None:
                return self._pending(execution, "admission_policy_not_registered")
            try:
                link, newly_decided = await self._service.decide_result_once(
                    scope,
                    child_id,
                    rule(execution),
                    parent_open=True,
                    current_generation=current_generation,
                    decided_at=self._clock(),
                )
            except AsyncSubagentError:
                # The service's own fence: a late or superseded result never mutates the parent.
                return self._refused(execution, "late_result")
        return self._from_link(execution, link, contract, newly_decided=newly_decided)

    def _from_link(
        self,
        execution: AsyncSubagentExecution,
        link: ParentAsyncSubagentLink,
        contract: AsyncSubagentContract,
        *,
        newly_decided: bool,
    ) -> ChildAdmission:
        decision = link.result_decision
        if decision not in ADMITTED_DECISIONS:
            return self._refused(
                execution,
                "decision_deferred" if decision == "defer" else "decision_rejected",
                decision=decision,
                newly_decided=newly_decided,
            )
        try:
            entry = child_result_index_entry(
                execution,
                link,
                child_name=contract.name,
                admitted_by="check_time",
            )
        except ValueError:
            return self._refused(execution, "manifest_mismatch", decision=decision)
        return ChildAdmission(
            status="admitted",
            child_execution_id=execution.child_execution_id,
            lifecycle=execution.lifecycle.value,
            decision=decision,
            newly_decided=newly_decided,
            entry=entry,
            output_text=execution.result_output_text,
            decided_at=link.updated_at,
        )

    @staticmethod
    def _pending(execution: AsyncSubagentExecution, reason: PendingReason) -> ChildAdmission:
        return ChildAdmission(
            status="pending",
            child_execution_id=execution.child_execution_id,
            lifecycle=execution.lifecycle.value,
            reason=reason,
        )

    @staticmethod
    def _refused(
        execution: AsyncSubagentExecution,
        reason: RefusedReason,
        *,
        decision: str | None = None,
        newly_decided: bool = False,
    ) -> ChildAdmission:
        return ChildAdmission.model_validate(
            {
                "status": "refused",
                "child_execution_id": execution.child_execution_id,
                "lifecycle": execution.lifecycle.value,
                "reason": reason,
                "decision": decision,
                "newly_decided": newly_decided,
            }
        )


__all__ = ["CheckTimeAdmission"]

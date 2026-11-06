"""Reducer-governed cancellation recovery after the exact Temporal family closed.

No restart, new cancel, native dispatch, usage attribution or provider acknowledgement.
The caller supplies identity/version only; trusted readers derive every settlement fact.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from mission_control.application.execution.service import RunControlService
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.runtime_contracts import ClosedWorkflowRecoveryRequest
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import (
    ActorContext,
    CommandResult,
    CommandStatus,
    LifecycleCommand,
    RunPhase,
    RunProjection,
    TerminalizationProposal,
    TerminalizeAction,
)
from mission_control.domain.policies.errors import IdempotencyConflict
from mission_control.domain.programs.contracts import StageGraphAcceptedProjection

PERMISSION = "workflow_run.terminalize"


@dataclass(frozen=True)
class ProducerAuthority:
    family: StageGraphAcceptedProjection
    producer_request_ref: str
    producer_workflow_ids: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class ClosedExecution:
    workflow_id: str
    temporal_run_id: str
    status: str
    last_event_id: int
    history_digest: str
    latest: bool = False


@dataclass(frozen=True)
class ClosedWorkflowEvidence:
    request_scope: str
    run_id: str
    execution_epoch: int
    execution_generation: int
    observed_at: datetime
    executions: tuple[ClosedExecution, ...]


class ClosedWorkflowAuthority(Protocol):
    async def read(self, run: RunProjection) -> ProducerAuthority:
        """Fail closed on any unsettled claim, native dispatch/session or unknown producer."""
        ...


class ClosedWorkflowObserver(Protocol):
    async def observe(
        self, run: RunProjection, producers: tuple[str, ...]
    ) -> ClosedWorkflowEvidence: ...

    async def recheck(self, evidence: ClosedWorkflowEvidence) -> None:
        """Verify latest exact execution IDs remain the same and terminal, no mutations."""
        ...


class ClosedWorkflowRecovery:
    def __init__(
        self,
        controls: RunControlService,
        authority: ClosedWorkflowAuthority,
        observer: ClosedWorkflowObserver,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._controls, self._authority, self._observer, self._clock = (
            controls,
            authority,
            observer,
            clock,
        )

    @staticmethod
    def issuer(actor: ActorContext) -> str:
        return json.dumps(["mc.closed_workflow_recovery.v1", actor.actor_id], separators=(",", ":"))

    @staticmethod
    def authorize(actor: ActorContext) -> None:
        if PERMISSION not in actor.permissions:
            raise MissionControlRejected("unauthorized", "workflow_run.terminalize is required")

    async def result(
        self, scope: str, run_id: str, request_id: str, actor: ActorContext
    ) -> CommandResult | None:
        self.authorize(actor)
        return await self._controls.get_command_result(
            scope, run_id, self.issuer(actor), request_id
        )

    async def recover(
        self, scope: str, run_id: str, request: ClosedWorkflowRecoveryRequest, actor: ActorContext
    ) -> CommandResult:
        try:
            async with asyncio.timeout(30):
                return await self._recover(scope, run_id, request, actor)
        except TimeoutError:
            raise MissionControlRejected(
                "unavailable",
                "closed workflow recovery deadline elapsed; "
                "read retained request result before any retry",
            ) from None

    async def _recover(
        self, scope: str, run_id: str, request: ClosedWorkflowRecoveryRequest, actor: ActorContext
    ) -> CommandResult:
        self.authorize(actor)
        request = ClosedWorkflowRecoveryRequest.model_validate(request.model_dump(mode="python"))
        command_id = str(request.request_id)
        marker = "closed-workflow-request:" + sha256_digest(
            {
                "scope": scope,
                "run_id": run_id,
                "actor_id": actor.actor_id,
                "request": request.model_dump(mode="json"),
            }
        )
        prior = await self.result(scope, run_id, command_id, actor)
        if prior is not None:
            # An accepted replay needs no fresh observer or write. Its immutable
            # transition binds the original caller payload, even after terminalization.
            transitions = await self._controls.list_transitions(scope, run_id)
            if prior.status == CommandStatus.ACCEPTED and any(
                item.command_id == command_id
                and item.actor.actor_id == actor.actor_id
                and item.prior_version == request.expected_version
                and marker in item.evidence_refs
                for item in transitions
            ):
                return prior
            raise IdempotencyConflict(
                "recovery request identity is already used; read its retained result"
            )
        run = await self._controls.get_run(scope, run_id)
        if run.request_scope != scope or run.run_id != run_id:
            raise MissionControlRejected("unauthorized", "recovery scope differs from the run")
        if run.version != request.expected_version:
            raise MissionControlRejected(
                "stale_version", "recovery requires the current run version"
            )
        target = run.execution_target
        if (
            run.phase != RunPhase.CANCELLING
            or target is None
            or target.family != "StageGraph"
            or not target.root_workflow_id
        ):
            raise MissionControlRejected(
                "unsupported_control",
                "recovery requires an existing cancelling StageGraph execution",
            )
        # This deliberately does not reinterpret adopted/provider async child IDs
        # as Temporal workflow IDs. Their separate reconciliation must finish first.
        if (
            run.active_waits
            or run.active_pauses
            or run.pending_continuation_proposals
            or run.async_children
        ):
            raise MissionControlRejected(
                "recovery_liability",
                "waits, continuation or external-child authority requires reconciliation",
            )
        before = await self._authority.read(run)
        family = before.family
        if (
            family.identity.run_id != run_id
            or family.identity.execution_epoch != target.execution_epoch
        ):
            raise MissionControlRejected(
                "recovery_identity", "family authority differs from the execution"
            )
        if not family.producer_liabilities or not all(
            item.closed for item in family.producer_liabilities.values()
        ):
            raise MissionControlRejected(
                "recovery_liability", "family producers are not conclusively settled"
            )
        if any(
            item.status in {"reserved", "running", "waiting", "paused"}
            for item in family.stages.values()
        ):
            raise MissionControlRejected("recovery_liability", "an active family stage remains")
        budget = await self._controls.get_budget(scope, run_id)
        effects = await self._controls.get_effects(scope, run_id)
        if (
            budget.reservations
            or any(budget.reserved.values())
            or any(budget.pending_settlement.values())
            or budget.outstanding_usage_ids
        ):
            raise MissionControlRejected("recovery_liability", "budget or usage remains unsettled")
        if any(item.settlement is None for item in effects.claims.values()):
            raise MissionControlRejected("recovery_liability", "an effect remains unsettled")
        async with asyncio.timeout(30):
            evidence = await self._observer.observe(run, before.producer_workflow_ids)
            if (
                evidence.request_scope,
                evidence.run_id,
                evidence.execution_epoch,
                evidence.execution_generation,
            ) != (scope, run_id, target.execution_epoch, target.execution_generation):
                raise MissionControlRejected(
                    "recovery_identity", "closed workflow evidence names another execution"
                )
            required_ids = {
                target.root_workflow_id,
                target.family_workflow_id,
                *before.producer_workflow_ids,
            }
            if not required_ids <= {item.workflow_id for item in evidence.executions} or any(
                not item.temporal_run_id
                or item.last_event_id < 1
                or item.status
                not in {
                    "COMPLETED",
                    "FAILED",
                    "CANCELED",
                    "TERMINATED",
                    "TIMED_OUT",
                    "CONTINUED_AS_NEW",
                }
                for item in evidence.executions
            ):
                raise MissionControlRejected(
                    "recovery_identity", "closed workflow evidence is incomplete"
                )
            latest_records = [item for item in evidence.executions if item.latest]
            if (
                len({item.workflow_id for item in latest_records}) != len(latest_records)
                or {item.workflow_id for item in latest_records}
                != {item.workflow_id for item in evidence.executions}
                or any(item.status == "CONTINUED_AS_NEW" for item in latest_records)
            ):
                raise MissionControlRejected(
                    "recovery_identity", "latest closed workflow evidence is incomplete"
                )
            if not timedelta(0) <= self._clock() - evidence.observed_at <= timedelta(seconds=20):
                raise MissionControlRejected(
                    "recovery_stale_evidence", "closed workflow evidence is stale"
                )
            await self._observer.recheck(evidence)
            after = await self._authority.read(run)
        if after.fingerprint != before.fingerprint:
            raise MissionControlRejected(
                "stale_version", "producer authority changed during recovery inspection"
            )
        now = self._clock()
        if now - evidence.observed_at > timedelta(seconds=20):
            raise MissionControlRejected(
                "recovery_stale_evidence", "closed workflow evidence expired"
            )
        # The reducer rechecks current run version and all budget/effect/obligation
        # authority under its existing transactional CAS; no caller booleans enter.
        proposal = TerminalizationProposal(
            proposal_id="closed-workflow:" + command_id,
            expected_run_version=request.expected_version,
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
            proposing_execution_binding_ref=before.producer_request_ref,
            required_obligations_accepted=run.required_obligation_refs
            <= {item.obligation_ref for item in run.accepted_obligation_evidence},
            valid_output_refs=tuple(
                sorted(
                    {item.output_ref for item in run.accepted_output_evidence}
                    | set(run.finalization_output_refs)
                )
            ),
            cancellation_settled=True,
            budget_settled=True,
            effects_settled=True,
            proposed_at=now,
            finalization_plan=run.finalization_plan,
            output_omission_reason=run.finalization_omission_reason,
        )
        envelope = {"schema_version": "mc.closed_workflow_evidence.v1", **asdict(evidence)}
        envelope["observed_at"] = evidence.observed_at.isoformat()
        retained_evidence = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        if len(retained_evidence.encode()) > 24_000:
            raise MissionControlRejected(
                "recovery_evidence_limit",
                "closed workflow evidence exceeds the durable envelope bound",
            )
        return await self._controls.execute(
            LifecycleCommand(
                command_id=command_id,
                idempotency_issuer=self.issuer(actor),
                request_scope=scope,
                run_id=run_id,
                expected_run_version=request.expected_version,
                actor=actor,
                action=TerminalizeAction(proposal=proposal),
                reason=(
                    "Reconcile existing cancellation after exact workflows closed; "
                    "no provider acknowledgement or human acceptance"
                ),
                evidence_refs=(
                    marker,
                    "producer-authority:" + before.fingerprint,
                    "closed-workflow-evidence:v1:" + retained_evidence,
                ),
                occurred_at=now,
                correlation_id=command_id,
            )
        )

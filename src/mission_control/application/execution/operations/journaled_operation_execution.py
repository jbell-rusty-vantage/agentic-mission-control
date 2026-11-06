from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.execution.operations.operation_execution import (
    ResultManifestObserver,
    operation_settlement_id,
    settlement_result_manifest,
)
from mission_control.application.execution.operations.operation_journal import (
    OperationJournalMutation,
    OperationJournalService,
)
from mission_control.application.execution.service import OperationAuthorityValidator
from mission_control.domain.authoring.canonical import contract_fingerprint, sha256_digest
from mission_control.domain.execution.checkpoint_lineage import UnitReconciliationIncident
from mission_control.domain.execution.contracts import (
    OperationExecutionBinding,
    OperationSettlement,
)
from mission_control.domain.execution.journal import (
    OperationClaimResult,
    OperationEffectClaim,
    OperationJournalSettlement,
    OperationTechnicalAttempt,
)
from mission_control.domain.policies.boundary_commands import receipt as boundary_receipt
from mission_control.domain.policies.contracts import (
    AcceptedOperationSettlementEvidence,
    ActorContext,
    ApplyAuthorityBatchAction,
    BudgetState,
    ClaimEffectAction,
    CommandResult,
    CommandStatus,
    EffectDisposition,
    EffectLedgerState,
    EffectSettlementOutcome,
    LifecycleCommand,
    LifecycleTransitionRecord,
    ObserveEffectAction,
    ReceiptState,
    RecordOperationSettlementEvidenceAction,
    RecordUsageAction,
    RunPhase,
    RunProjection,
    SettleEffectAction,
    SettlePendingUsageAction,
    SetWaitAction,
    UnitReconciliationDecision,
    WaitCondition,
    operator_reconciliation_condition_id,
)

OUTPUT_PAYLOAD_MEDIA_TYPE = "application/vnd.belllabs.operation-output+json"
SETTLEMENT_MEDIA_TYPE = "application/vnd.belllabs.operation-settlement+json"


OPERATION_BOUNDARY_RECORDER = "operation-boundary"


class JournalRunControlReader(Protocol):
    async def get_run(self, request_scope: str, run_id: str) -> RunProjection: ...

    async def get_budget(self, request_scope: str, run_id: str) -> BudgetState: ...

    async def get_effects(self, request_scope: str, run_id: str) -> EffectLedgerState: ...

    async def execute(self, command: LifecycleCommand) -> CommandResult: ...

    async def execute_operation_authority(
        self,
        command: LifecycleCommand,
        *,
        validate_authority: OperationAuthorityValidator,
    ) -> tuple[LifecycleCommand, CommandResult]: ...

    async def list_transitions(
        self,
        request_scope: str,
        run_id: str,
    ) -> tuple[LifecycleTransitionRecord, ...]: ...

    async def get_command_result(
        self,
        request_scope: str,
        run_id: str,
        idempotency_issuer: str,
        command_id: str,
    ) -> CommandResult | None: ...


class ResultPayloadStore(Protocol):
    async def stage(
        self,
        *,
        artifact_id: str,
        content: bytes,
        content_digest: str,
        media_type: str,
    ) -> ArtifactPayloadAddress: ...

    async def retrieve(self, address: ArtifactPayloadAddress) -> bytes: ...


class JournaledOperationExecutionCoordinator:
    """Coordinates immutable operation-binding authority with the PostgreSQL effect journal."""

    def __init__(
        self,
        *,
        journal: OperationJournalService,
        run_control: JournalRunControlReader,
        results: ResultPayloadStore,
        actor: ActorContext,
    ) -> None:
        self._journal = journal
        self._run_control = run_control
        self._results = results
        self._actor = actor

    async def acquire(
        self,
        binding: OperationExecutionBinding,
        *,
        claimed_by: str,
        at_current_version: bool = False,
    ) -> OperationClaimResult:
        """Claim the unit's consequential effect in run control, then in the journal.

        The claim binds the operation's accepted run-control revision. `at_current_version`
        (RRM-008) claims at the run's current version instead: the cancellation saga settles
        a unit whose run moved past the bound revision through the accepted cancel itself,
        and the claim exists only to be settled `cancelled` without provider work.
        """

        claim = _claim_for(binding, claimed_by=claimed_by)
        expected_run_version = binding.run_control_revision
        if at_current_version:
            current = await self._run_control.get_run(binding.request_scope, binding.run_id)
            expected_run_version = current.version
        authority_command, claimed = await self._execute_replayable(
            LifecycleCommand(
                command_id=_claim_authority_command_id(claim),
                idempotency_issuer="operation-journal",
                request_scope=binding.request_scope,
                run_id=binding.run_id,
                expected_run_version=expected_run_version,
                actor=self._actor,
                action=ClaimEffectAction(
                    effect_id=claim.effect_claim_id,
                    effect_kind="operation.runtime",
                    operation_ref=binding.binding_id,
                    provider_idempotency_key=binding.side_effect_key,
                    reservation_id=binding.budget_reservation_id,
                    claim_payload_digest=sha256_digest(claim.model_dump(mode="json")),
                ),
                reason="Claim consequential operation effect before provider dispatch",
                evidence_refs=(binding.binding_id,),
                occurred_at=claim.claimed_at,
                correlation_id=f"operation:{binding.semantic_attempt_key}",
                causation_id=binding.binding_id,
            ),
            binding=binding,
            cancellation_claim=at_current_version,
        )
        if claimed.status != CommandStatus.ACCEPTED:
            return OperationClaimResult(
                status="shadow_denied",
                reason=f"run-control effect claim rejected: {claimed.reason_code}",
            )
        return await self._journal.commit(
            OperationJournalMutation(
                request_scope=binding.request_scope,
                belllabs_run_id=binding.run_id,
                expected_run_version=claimed.resulting_run_version,
                claim=claim,
                authority_command=authority_command,
                authority_result=claimed,
            )
        )

    async def existing_lane_claim(
        self, binding: OperationExecutionBinding, expected_claim_id: str
    ) -> OperationEffectClaim:
        """Read the existing consequential claim; never rebuild its old claimant.

        Recovery adopts terminal evidence, not a new claim-authority command.
        Both the immutable journal and run-control effect must identify this binding.
        """
        if expected_claim_id != _effect_claim_id(binding):
            raise ValueError("terminal evidence names another effect claim")
        claim = await self._journal.get_claim(binding.request_scope, expected_claim_id)
        if (
            claim is None
            or claim.claim_mode != "active"
            or claim.status.value not in {"claimed", "executing"}
        ):
            raise ValueError("an active existing lane claim is required")
        expected = _claim_for(binding, claimed_by=claim.claimed_by)
        mutable = {"status", "claimed_at", "heartbeat_at", "lease_expires_at"}
        if claim.model_dump(exclude=mutable) != expected.model_dump(exclude=mutable):
            raise ValueError("existing lane claim differs from admitted binding")
        effects = await self._run_control.get_effects(binding.request_scope, binding.run_id)
        effect = effects.claims.get(expected_claim_id)
        if (
            effect is None
            or (
                effect.settlement is not None
                and effect.settlement.settlement_id != operation_settlement_id(binding.binding_id)
            )
            or (
                effect.operation_ref != binding.binding_id
                or effect.provider_idempotency_key != binding.side_effect_key
                or effect.reservation_id != binding.budget_reservation_id
            )
        ):
            raise ValueError("existing lane effect authority differs")
        return claim

    async def get_settlement(
        self,
        binding: OperationExecutionBinding,
    ) -> OperationSettlement | None:
        claim_id = _effect_claim_id(binding)
        settlement = await self._journal.get_settlement(
            binding.request_scope,
            claim_id,
        )
        if settlement is None or settlement.result_manifest_ref is None:
            return None
        assert settlement.result_manifest_digest is not None
        assert settlement.result_manifest_size_bytes is not None
        content = await self._results.retrieve(
            ArtifactPayloadAddress(
                object_ref=settlement.result_manifest_ref,
                content_digest=settlement.result_manifest_digest,
                size_bytes=settlement.result_manifest_size_bytes,
            )
        )
        return await self._restore(binding, OperationSettlement.model_validate_json(content))

    async def acquire_lane_admission_rejection(
        self,
        binding: OperationExecutionBinding,
        *,
        claimed_by: str,
        verify_authority: Callable[[], Awaitable[None]],
    ) -> OperationClaimResult:
        """Fence out normal dispatch before settling a proven absent lane execution.

        A different command purpose claims the same effect identity. Consequently
        either normal dispatch or rejection wins the reducer CAS; neither can replay
        the other's accepted command, even after an authority-before-journal crash.
        Only this exact rejection's accepted authority may resume its own saga.
        """

        claim = _claim_for(binding, claimed_by=claimed_by).model_copy(
            update={"claimed_at": datetime.now(UTC)}
        )
        command_id = f"lane-admission-rejection:{_claim_authority_command_id(claim)}"
        issuer = "operation-lane-admission-rejection"
        prior = await self._run_control.get_command_result(
            binding.request_scope, binding.run_id, issuer, command_id
        )
        current = await self._run_control.get_run(binding.request_scope, binding.run_id)
        if (
            current.phase not in {RunPhase.ACTIVE, RunPhase.WAITING}
            or current.version < binding.run_control_revision
            or current.effective_configuration_digest != binding.effective_configuration_digest
        ):
            return OperationClaimResult(status="conflict", reason="operation authority changed")
        budget = await self._run_control.get_budget(binding.request_scope, binding.run_id)
        effects = await self._run_control.get_effects(binding.request_scope, binding.run_id)
        own_replay = prior is not None and prior.status == CommandStatus.ACCEPTED
        settlement_id = operation_settlement_id(binding.binding_id)
        related = tuple(
            item
            for item in effects.claims.values()
            if item.operation_ref == binding.binding_id
            or item.reservation_id == binding.budget_reservation_id
            or item.provider_idempotency_key == binding.side_effect_key
        )
        if own_replay and len(related) != 1:
            return OperationClaimResult(status="conflict", reason="rejection effect proof missing")
        if own_replay:
            # The first rejection's actual time belongs to its authoritative effect.
            # Rebuild the exact claim digest after an authority-before-journal crash.
            claim = claim.model_copy(update={"claimed_at": related[0].claimed_at})
        for effect in related:
            if (
                not own_replay
                or effect.effect_id != claim.effect_claim_id
                or effect.operation_ref != binding.binding_id
                or effect.reservation_id != binding.budget_reservation_id
                or effect.provider_idempotency_key != binding.side_effect_key
                or any(
                    item.observation_id != f"observation:{settlement_id}"
                    or item.disposition != EffectDisposition.FAILED
                    or item.provider_effect_ref is not None
                    for item in effect.observations
                )
                or (
                    effect.settlement is not None
                    and (
                        effect.settlement.settlement_id != settlement_id
                        or effect.settlement.outcome != EffectSettlementOutcome.FAILED
                        or effect.settlement.usage_settlement_ref != settlement_id
                    )
                )
            ):
                return OperationClaimResult(status="conflict", reason="prior operation effect")
        usages = tuple(
            item
            for item in budget.usage_records.values()
            if item.reservation_id == binding.budget_reservation_id
            or item.authority_ref == binding.binding_id
        )
        for usage in usages:
            if (
                not own_replay
                or usage.usage_id != settlement_id
                or usage.authority_ref != binding.binding_id
                or usage.reservation_id != binding.budget_reservation_id
                or usage.actual_amounts
                or usage.pending_external_amounts
                or usage.release_amounts
                != {
                    dimension: amount
                    for dimension, amount in binding.budget_limits.items()
                    if amount
                }
            ):
                return OperationClaimResult(status="conflict", reason="prior operation usage")
        if not usages and budget.reservations.get(binding.budget_reservation_id) != dict(
            binding.budget_limits
        ):
            return OperationClaimResult(status="conflict", reason="reservation changed")
        if not own_replay:
            # Fresh rejection needs current admission. Exact own accepted authority
            # resumes its saga even if its usage batch already released reservation
            # before a crash; the checks above admit only that exact empty usage.
            await verify_authority()
        checked = await self._run_control.get_run(binding.request_scope, binding.run_id)
        if checked.version != current.version:
            return OperationClaimResult(status="conflict", reason="operation authority changed")
        authority_command, result = await self._execute_replayable(
            LifecycleCommand(
                command_id=command_id,
                idempotency_issuer=issuer,
                request_scope=binding.request_scope,
                run_id=binding.run_id,
                expected_run_version=current.version,
                actor=self._actor,
                action=ClaimEffectAction(
                    effect_id=claim.effect_claim_id,
                    effect_kind="operation.runtime",
                    operation_ref=binding.binding_id,
                    provider_idempotency_key=binding.side_effect_key,
                    reservation_id=binding.budget_reservation_id,
                    claim_payload_digest=sha256_digest(claim.model_dump(mode="json")),
                ),
                reason="Fence never-started lane admission rejection before settlement",
                evidence_refs=(binding.binding_id,),
                occurred_at=claim.claimed_at,
                correlation_id=f"operation:{binding.semantic_attempt_key}",
                causation_id=binding.binding_id,
            )
        )
        if result.status != CommandStatus.ACCEPTED:
            return OperationClaimResult(
                status="conflict", reason=f"rejection claim refused: {result.reason_code}"
            )
        return await self._journal.commit(
            OperationJournalMutation(
                request_scope=binding.request_scope,
                belllabs_run_id=binding.run_id,
                expected_run_version=result.resulting_run_version,
                claim=claim,
                authority_command=authority_command,
                authority_result=result,
            )
        )

    async def load_result_manifest(
        self,
        binding: OperationExecutionBinding,
        *,
        manifest_ref: str,
        manifest_digest: str,
        manifest_size_bytes: int,
    ) -> OperationSettlement:
        """The exact settlement a fenced result observation recorded (`observed_unsettled`)."""

        content = await self._results.retrieve(
            ArtifactPayloadAddress(
                object_ref=manifest_ref,
                content_digest=manifest_digest,
                size_bytes=manifest_size_bytes,
            )
        )
        return await self._restore(binding, OperationSettlement.model_validate_json(content))

    async def _restore(
        self, binding: OperationExecutionBinding, replay: OperationSettlement
    ) -> OperationSettlement:
        """Re-attach the digest-bound output payload the manifest commits to."""

        if replay.binding_id != binding.binding_id:
            raise ValueError("result manifest belongs to another operation binding")
        if replay.output_payload_ref is None:
            return replay
        assert replay.output_payload_digest is not None
        assert replay.output_payload_size_bytes is not None
        payload = json.loads(
            await self._results.retrieve(
                ArtifactPayloadAddress(
                    object_ref=replay.output_payload_ref,
                    content_digest=replay.output_payload_digest,
                    size_bytes=replay.output_payload_size_bytes,
                )
            )
        )
        return replay.model_copy(
            update={
                "output_text": payload["output_text"],
                "structured_output": payload["structured_output"],
                "event_payloads": tuple(payload.get("event_payloads", ())),
            }
        )

    async def settle(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim,
        settlement: OperationSettlement,
        *,
        started_at: datetime,
        technical_attempt: int = 1,
        before_authority: ResultManifestObserver | None = None,
        expected_run_version: int | None = None,
    ) -> OperationSettlement:
        expected_claim_id = _effect_claim_id(binding)
        if (
            claim.effect_claim_id != expected_claim_id
            or claim.request_scope != binding.request_scope
            or claim.semantic_binding_id != binding.binding_id
            or claim.semantic_binding_digest != sha256_digest(binding)
            or settlement.binding_id != binding.binding_id
        ):
            raise ValueError("claim, binding, and settlement authority do not match")
        output = output_payload(settlement)
        output_address = await self._results.stage(
            artifact_id=f"{settlement.settlement_id}:output",
            content=output,
            content_digest=f"sha256:{hashlib.sha256(output).hexdigest()}",
            media_type=OUTPUT_PAYLOAD_MEDIA_TYPE,
        )
        settlement = settlement.model_copy(
            update={
                "output_payload_ref": output_address.object_ref,
                "output_payload_digest": output_address.content_digest,
                "output_payload_size_bytes": output_address.size_bytes,
            }
        )
        content = settlement_result_manifest(settlement)
        content_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
        address = await self._results.stage(
            artifact_id=settlement.settlement_id,
            content=content,
            content_digest=content_digest,
            media_type=SETTLEMENT_MEDIA_TYPE,
        )
        if before_authority is not None:
            # REQ-CP-EXEC-014 / REQ-CP-DA-017: the fenced result observation (and, for
            # cognition, the checkpoint transition) fixes this exact immutable manifest by
            # compare-and-set before authority settlement.
            await before_authority(address.object_ref, address.content_digest, address.size_bytes)
        current_run = await self._run_control.get_run(binding.request_scope, binding.run_id)
        release_amounts = {
            dimension: limit
            - min(
                limit,
                settlement.usage.amounts.get(dimension, 0)
                + settlement.usage.pending_external_amounts.get(dimension, 0),
            )
            for dimension, limit in binding.budget_limits.items()
            if limit
            > settlement.usage.amounts.get(dimension, 0)
            + settlement.usage.pending_external_amounts.get(dimension, 0)
        }
        disposition = (
            EffectDisposition.SUCCEEDED
            if settlement.status == "completed"
            else EffectDisposition.CANCELLED
            if settlement.status == "cancelled"
            else EffectDisposition.FAILED
        )
        _observation_command, observation = await self._execute_replayable(
            LifecycleCommand(
                command_id=f"operation-effect-observation:{settlement.settlement_id}",
                idempotency_issuer="operation-journal",
                request_scope=binding.request_scope,
                run_id=binding.run_id,
                expected_run_version=(
                    expected_run_version
                    if expected_run_version is not None
                    else current_run.version
                ),
                actor=self._actor,
                action=ObserveEffectAction(
                    effect_id=claim.effect_claim_id,
                    observation_id=f"observation:{settlement.settlement_id}",
                    disposition=disposition,
                    provider_effect_ref=settlement.provider_run_id,
                    evidence_refs=(address.object_ref,),
                ),
                reason="Reconcile provider completion as an observed effect fact",
                evidence_refs=(binding.binding_id, address.object_ref),
                occurred_at=settlement.settled_at,
                correlation_id=f"operation:{binding.semantic_attempt_key}",
                causation_id=claim.effect_claim_id,
            ),
            pinned_version=expected_run_version is not None,
            binding=binding,
        )
        _require_accepted(observation, "effect observation")
        pending_external = any(settlement.usage.pending_external_amounts.values())
        authority_actor = self._actor.model_copy(
            update={"authority_refs": self._actor.authority_refs | {binding.binding_id}}
        )
        journal_settlement = OperationJournalSettlement.create(
            settlement_id=settlement.settlement_id,
            request_scope=binding.request_scope,
            effect_claim_id=claim.effect_claim_id,
            settlement_revision=1,
            status=("reconciliation_required" if pending_external else settlement.status),
            usage=settlement.usage.amounts,
            released_usage=release_amounts,
            pending_external_usage=settlement.usage.pending_external_amounts,
            result_manifest_ref=address.object_ref,
            result_manifest_digest=address.content_digest,
            result_manifest_size_bytes=address.size_bytes,
            failure_code=settlement.failure_code,
            detail={"schema_version": "1"},
            settled_at=settlement.settled_at,
        )
        usage_action = RecordUsageAction(
            usage_id=settlement.settlement_id,
            authority_ref=binding.binding_id,
            actual_amounts=settlement.usage.amounts,
            reservation_id=binding.budget_reservation_id,
            release_amounts=release_amounts,
            pending_external_amounts=settlement.usage.pending_external_amounts,
        )
        settlement_evidence = RecordOperationSettlementEvidenceAction(
            evidence=AcceptedOperationSettlementEvidence(
                settlement_id=journal_settlement.settlement_id,
                settlement_payload_digest=journal_settlement.settlement_digest,
                accepted_by_authority_ref=binding.binding_id,
            )
        )
        authority_action = (
            ApplyAuthorityBatchAction(actions=(usage_action, settlement_evidence))
            if pending_external
            else ApplyAuthorityBatchAction(
                actions=(
                    usage_action,
                    SettleEffectAction(
                        effect_id=claim.effect_claim_id,
                        settlement_id=settlement.settlement_id,
                        observation_id=f"observation:{settlement.settlement_id}",
                        outcome=EffectSettlementOutcome(disposition.value),
                        usage_settlement_ref=settlement.settlement_id,
                        evidence_refs=(address.object_ref,),
                    ),
                    settlement_evidence,
                )
            )
        )
        authority_command, usage_result = await self._execute_replayable(
            LifecycleCommand(
                command_id=(
                    f"operation-authority-settlement:{settlement.settlement_id}:revision:1"
                ),
                idempotency_issuer="operation-journal",
                request_scope=binding.request_scope,
                run_id=binding.run_id,
                expected_run_version=observation.resulting_run_version,
                actor=authority_actor,
                action=authority_action,
                reason=(
                    "Record pending operation usage before later reconciliation"
                    if pending_external
                    else "Atomically settle operation usage and consequential effect"
                ),
                evidence_refs=(binding.binding_id, address.object_ref),
                occurred_at=settlement.settled_at,
                correlation_id=f"operation:{binding.semantic_attempt_key}",
                causation_id=claim.effect_claim_id,
            ),
            pinned_version=expected_run_version is not None,
            binding=binding,
        )
        _require_accepted(usage_result, "operation authority settlement")
        technical_attempt_record = OperationTechnicalAttempt(
            operation_attempt_id=str(
                uuid5(NAMESPACE_URL, f"operation-technical:{settlement.settlement_id}")
            ),
            request_scope=binding.request_scope,
            effect_claim_id=claim.effect_claim_id,
            technical_attempt=technical_attempt,
            provider="runtime_adapter",
            provider_attempt_id=settlement.provider_run_id,
            disposition=(
                "succeeded"
                if settlement.status == "completed"
                else "cancelled"
                if settlement.status == "cancelled"
                else "failed"
            ),
            idempotency_supported=True,
            retry_class="claim_then_reconcile",
            usage=settlement.usage.amounts,
            started_at=started_at,
            finished_at=settlement.settled_at,
            failure_code=settlement.failure_code,
        )
        await self._journal.commit(
            OperationJournalMutation(
                request_scope=binding.request_scope,
                belllabs_run_id=binding.run_id,
                expected_run_version=usage_result.resulting_run_version,
                claim=claim,
                attempt=technical_attempt_record,
                settlement=journal_settlement,
                authority_command=authority_command,
                authority_result=usage_result,
            )
        )
        return settlement

    async def record_in_doubt(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim,
        incident: UnitReconciliationIncident,
    ) -> None:
        """REQ-CP-RUN-007: preserve the ambiguous disposition and park on the operator.

        The unit's effect claim stays unsettled with an `ambiguous` observation, and the run
        declares an `operator_reconciliation` wait without changing its phase. Both writes
        are idempotent by command identity, so a repeated in_doubt attempt is a no-op.
        """

        correlation = f"operation:{binding.semantic_attempt_key}"
        await self._execute_tolerating(
            binding,
            lambda version: LifecycleCommand(
                command_id=f"operation-effect-in-doubt:{incident.incident_id}",
                idempotency_issuer="operation-journal",
                request_scope=binding.request_scope,
                run_id=binding.run_id,
                expected_run_version=version,
                actor=self._actor,
                action=ObserveEffectAction(
                    effect_id=claim.effect_claim_id,
                    observation_id=f"in-doubt:{incident.incident_id}",
                    disposition=EffectDisposition.AMBIGUOUS,
                    evidence_refs=(incident.incident_id,),
                ),
                reason=f"Runtime unit is in_doubt: {incident.reason}",
                evidence_refs=(binding.binding_id, incident.incident_id),
                occurred_at=incident.recorded_at,
                correlation_id=correlation,
                causation_id=claim.effect_claim_id,
            ),
            tolerated={"effect_observation_exists", "effect_already_settled", "run_is_terminal"},
        )
        await self._execute_tolerating(
            binding,
            lambda version: LifecycleCommand(
                command_id=f"operation-reconciliation-wait:{incident.incident_id}",
                idempotency_issuer="operation-journal",
                request_scope=binding.request_scope,
                run_id=binding.run_id,
                expected_run_version=version,
                actor=self._actor,
                action=SetWaitAction(
                    condition=WaitCondition(
                        condition_id=operator_reconciliation_condition_id(
                            incident.unit_key, incident.execution_generation, incident.revision
                        ),
                        kind="operator_reconciliation",
                        scope=frozenset({incident.unit_key}),
                        verification_ref=incident.incident_id,
                        timeout_policy_ref="operator-reconciliation:no-timeout",
                    ),
                    runnable_work_remains=True,
                ),
                reason="Park the in_doubt unit on operator reconciliation",
                evidence_refs=(binding.binding_id, incident.incident_id),
                occurred_at=incident.recorded_at,
                correlation_id=correlation,
                causation_id=claim.effect_claim_id,
            ),
            tolerated={"wait_exists", "invalid_phase", "run_is_terminal"},
        )

    async def get_unit_reconciliation(
        self,
        binding: OperationExecutionBinding,
        *,
        unit_key: str,
        execution_generation: int,
        incident_id: str,
    ) -> UnitReconciliationDecision | None:
        """The accepted `reconcile_unit` decision for this incident revision, if any."""

        run = await self._run_control.get_run(binding.request_scope, binding.run_id)
        return next(
            (
                item
                for item in run.unit_reconciliations
                if item.unit_key == unit_key
                and item.execution_generation == execution_generation
                and item.incident_id == incident_id
            ),
            None,
        )

    async def record_reconciliation_applied(
        self,
        binding: OperationExecutionBinding,
        decision: UnitReconciliationDecision,
    ) -> None:
        """RRM-007: the operation boundary applied the accepted `reconcile_unit` decision.

        Recorded through run control's receipt ledger when the composed run control keeps
        one; a duplicate application is a no-op there (the receipt never transitions twice).
        """

        recorder = getattr(self._run_control, "record_boundary_receipt", None)
        lookup = getattr(self._run_control, "list_boundary_commands", None)
        if recorder is None or lookup is None:
            return
        # The decision records the command ID; the issuer is found on the run's ledger.
        status = next(
            (
                item
                for item in await lookup(binding.request_scope, binding.run_id)
                if item.command.kind == "reconcile_unit"
                and item.command.command_id == decision.decision_id
                and item.command.target.target_ref
                == f"{decision.unit_key}:gen:{decision.execution_generation}"
            ),
            None,
        )
        if status is None or status.state in {ReceiptState.APPLIED, ReceiptState.REJECTED}:
            return
        now = datetime.now(UTC)
        if status.state == ReceiptState.ACCEPTED:
            await recorder(
                binding.request_scope,
                boundary_receipt(
                    status.command,
                    ordinal=1,
                    state=ReceiptState.DELIVERED,
                    recorded_by=OPERATION_BOUNDARY_RECORDER,
                    detail="decision read from authority by the operation boundary",
                    transport_ref=binding.binding_id,
                    recorded_at=now,
                ),
            )
        await recorder(
            binding.request_scope,
            boundary_receipt(
                status.command,
                ordinal=1,
                state=ReceiptState.APPLIED,
                recorded_by=OPERATION_BOUNDARY_RECORDER,
                detail=f"decision {decision.decision} applied by the operation boundary",
                transport_ref=binding.binding_id,
                recorded_at=now,
            ),
        )

    async def unsettled_effect_ids(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim,
    ) -> tuple[str, ...]:
        """Consequential effects the unit claimed, besides its own, that remain unsettled."""

        effects = await self._run_control.get_effects(binding.request_scope, binding.run_id)
        return tuple(
            sorted(
                effect_id
                for effect_id, item in effects.claims.items()
                if item.operation_ref == binding.binding_id
                and effect_id != claim.effect_claim_id
                and item.settlement is None
            )
        )

    async def _execute_tolerating(
        self,
        binding: OperationExecutionBinding,
        build: Callable[[int], LifecycleCommand],
        *,
        tolerated: set[str],
    ) -> None:
        for _attempt in range(8):
            run = await self._run_control.get_run(binding.request_scope, binding.run_id)
            command = build(run.version)
            prior = await self._run_control.get_command_result(
                command.request_scope,
                command.run_id,
                command.idempotency_issuer,
                command.command_id,
            )
            result = prior or await self._run_control.execute(command)
            if result.status == CommandStatus.ACCEPTED or result.reason_code in tolerated:
                return
            if result.status == CommandStatus.STALE and prior is None:
                continue
            raise RuntimeError(
                f"in_doubt authority record rejected by run control: {result.reason_code}"
            )
        raise RuntimeError("in_doubt authority record remained stale after retries")

    async def settle_pending_usage(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim,
        settlement: OperationSettlement,
        *,
        actual_amounts: dict[str, int],
        release_amounts: dict[str, int],
        reconciled_at: datetime,
    ) -> OperationSettlement:
        if (
            claim.effect_claim_id != _effect_claim_id(binding)
            or claim.semantic_binding_id != binding.binding_id
            or settlement.binding_id != binding.binding_id
        ):
            raise ValueError("pending settlement authority does not match operation binding")
        prior = await self._journal.get_settlement(
            binding.request_scope,
            claim.effect_claim_id,
        )
        if (
            prior is None
            or prior.settlement_id != settlement.settlement_id
            or prior.status != "reconciliation_required"
            or not prior.pending_external_usage
        ):
            raise ValueError("operation has no matching pending usage settlement")
        if prior.result_manifest_ref is None:
            raise ValueError("pending operation settlement has no result manifest")
        final_settlement = OperationJournalSettlement.create(
            settlement_id=settlement.settlement_id,
            request_scope=binding.request_scope,
            effect_claim_id=claim.effect_claim_id,
            settlement_revision=2,
            status=settlement.status,
            usage={
                dimension: prior.usage.get(dimension, 0) + actual_amounts.get(dimension, 0)
                for dimension in prior.usage.keys() | actual_amounts.keys()
            },
            released_usage={
                dimension: prior.released_usage.get(dimension, 0)
                + release_amounts.get(dimension, 0)
                for dimension in prior.released_usage.keys() | release_amounts.keys()
            },
            pending_external_usage={},
            result_manifest_ref=prior.result_manifest_ref,
            result_manifest_digest=prior.result_manifest_digest,
            result_manifest_size_bytes=prior.result_manifest_size_bytes,
            failure_code=settlement.failure_code,
            detail={"schema_version": "1"},
            settled_at=reconciled_at,
        )
        current_run = await self._run_control.get_run(binding.request_scope, binding.run_id)
        pending_settlement_id = f"pending:{settlement.settlement_id}"
        authority_command, authority_result = await self._execute_replayable(
            LifecycleCommand(
                command_id=(
                    f"operation-authority-settlement:{settlement.settlement_id}:revision:2"
                ),
                idempotency_issuer="operation-journal",
                request_scope=binding.request_scope,
                run_id=binding.run_id,
                expected_run_version=current_run.version,
                actor=self._actor.model_copy(
                    update={"authority_refs": self._actor.authority_refs | {binding.binding_id}}
                ),
                action=ApplyAuthorityBatchAction(
                    actions=(
                        SettlePendingUsageAction(
                            settlement_id=pending_settlement_id,
                            usage_id=settlement.settlement_id,
                            actual_amounts=actual_amounts,
                            pending_release_amounts=release_amounts,
                        ),
                        SettleEffectAction(
                            effect_id=claim.effect_claim_id,
                            settlement_id=settlement.settlement_id,
                            observation_id=f"observation:{settlement.settlement_id}",
                            outcome=EffectSettlementOutcome(
                                (
                                    EffectDisposition.SUCCEEDED
                                    if settlement.status == "completed"
                                    else EffectDisposition.CANCELLED
                                    if settlement.status == "cancelled"
                                    else EffectDisposition.FAILED
                                ).value
                            ),
                            usage_settlement_ref=pending_settlement_id,
                            evidence_refs=(prior.result_manifest_ref,),
                        ),
                        RecordOperationSettlementEvidenceAction(
                            evidence=AcceptedOperationSettlementEvidence(
                                settlement_id=final_settlement.settlement_id,
                                settlement_payload_digest=(final_settlement.settlement_digest),
                                accepted_by_authority_ref=binding.binding_id,
                            )
                        ),
                    )
                ),
                reason="Atomically reconcile pending operation usage and effect",
                evidence_refs=(
                    binding.binding_id,
                    prior.result_manifest_ref,
                ),
                occurred_at=reconciled_at,
                correlation_id=f"operation:{binding.semantic_attempt_key}",
                causation_id=claim.effect_claim_id,
            ),
            binding=binding,
        )
        _require_accepted(authority_result, "pending operation authority settlement")
        await self._journal.commit(
            OperationJournalMutation(
                request_scope=binding.request_scope,
                belllabs_run_id=binding.run_id,
                expected_run_version=authority_result.resulting_run_version,
                claim=claim,
                settlement=final_settlement,
                prior_settlement=prior,
                authority_command=authority_command,
                authority_result=authority_result,
            )
        )
        return settlement

    async def _execute_replayable(
        self,
        command: LifecycleCommand,
        *,
        pinned_version: bool = False,
        binding: OperationExecutionBinding | None = None,
        cancellation_claim: bool = False,
    ) -> tuple[LifecycleCommand, CommandResult]:
        prior = await self._run_control.get_command_result(
            command.request_scope,
            command.run_id,
            command.idempotency_issuer,
            command.command_id,
        )
        if prior is not None:
            if pinned_version and prior.resulting_run_version != command.expected_run_version + 1:
                raise RuntimeError("retained settlement authority differs from its pinned version")
            command = command.model_copy(
                update={"expected_run_version": prior.resulting_run_version - 1}
            )
            fingerprint = contract_fingerprint(command, exclude={"occurred_at"})
            if prior.status != CommandStatus.ACCEPTED or prior.command_fingerprint != fingerprint:
                raise RuntimeError(
                    "stored operation authority result conflicts with exact replay command: "
                    f"stored={prior.command_fingerprint}, rebuilt={fingerprint}"
                )
            return command, prior
        if not pinned_version and binding is not None:
            validator = await self._authority_validator(
                binding,
                claiming=isinstance(command.action, ClaimEffectAction),
                cancellation_claim=cancellation_claim,
            )
            return await self._run_control.execute_operation_authority(
                command, validate_authority=validator
            )
        result = await self._run_control.execute(command)
        return command, result

    async def _authority_validator(
        self,
        binding: OperationExecutionBinding,
        *,
        claiming: bool,
        cancellation_claim: bool,
    ) -> OperationAuthorityValidator:
        admission_target = None
        unit = binding.runtime_unit
        if unit is not None:
            transitions = await self._run_control.list_transitions(
                binding.request_scope, binding.run_id
            )
            admission = next(
                (
                    item
                    for item in transitions
                    if item.resulting_version == binding.run_control_revision
                ),
                None,
            )
            if admission is None:
                raise ValueError("operation binding has no retained admission transition")
            admission_target = admission.resulting_projection.execution_target

        def validate(run: RunProjection, budget: BudgetState, effects: EffectLedgerState) -> None:
            if (
                run.request_scope != binding.request_scope
                or run.run_id != binding.run_id
                or run.version < binding.run_control_revision
                or run.effective_configuration_digest != binding.effective_configuration_digest
                or (unit is not None and run.execution_target != admission_target)
            ):
                raise ValueError("operation journal authority no longer matches its binding")
            if (
                unit is not None
                and admission_target is not None
                and admission_target.execution_epoch != unit.execution_epoch
            ):
                raise ValueError("operation journal execution epoch changed")
            if claiming:
                if _effect_claim_id(binding) in effects.claims:
                    # This cannot authorize fresh dispatch: the reducer must retain the
                    # exact existing-effect rejection, including rejection-saga claims.
                    return
                required_phase = RunPhase.CANCELLING if cancellation_claim else RunPhase.ACTIVE
                if run.phase != required_phase:
                    raise ValueError("operation effect claim requires its current authority phase")
                reservation = budget.reservations.get(binding.budget_reservation_id)
                if reservation is None or any(
                    dimension not in reservation or amount > reservation[dimension]
                    for dimension, amount in binding.budget_limits.items()
                ):
                    raise ValueError("operation effect claim reservation changed")

        return validate


def output_payload(settlement: OperationSettlement) -> bytes:
    """Canonical output payload bytes; the manifest commits to their digest.

    RRM-009: the runtime's event payloads (the materialization inspection and the
    sanitized capability lineage) travel in the same digest-bound payload, so the journaled
    path keeps them durably. A settlement without them keeps the earlier byte layout.
    """

    payload: dict[str, object] = {
        "output_text": settlement.output_text,
        "structured_output": settlement.structured_output,
    }
    if settlement.event_payloads:
        payload["event_payloads"] = list(settlement.event_payloads)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def _effect_claim_id(binding: OperationExecutionBinding) -> str:
    return operation_effect_claim_id(binding.request_scope, binding.binding_id)


def operation_effect_claim_id(request_scope: str, binding_id: str) -> str:
    """The run-control effect identity of a bound operation's consequential runtime effect."""

    identity = f"operation-effect:{request_scope}:{binding_id}"
    return str(uuid5(NAMESPACE_URL, identity))


def _claim_authority_command_id(claim: OperationEffectClaim) -> str:
    identity = (
        f"operation-claim-authority:{claim.request_scope}:"
        f"{claim.operation_contract_digest}:{claim.idempotency_key}"
    )
    return f"operation-effect-claim:{uuid5(NAMESPACE_URL, identity)}"


def _require_accepted(result: CommandResult, subject: str) -> None:
    if result.status != CommandStatus.ACCEPTED:
        raise RuntimeError(f"{subject} rejected by run control: {result.reason_code}")


def _claim_for(
    binding: OperationExecutionBinding,
    *,
    claimed_by: str,
) -> OperationEffectClaim:
    return OperationEffectClaim(
        effect_claim_id=_effect_claim_id(binding),
        request_scope=binding.request_scope,
        belllabs_run_id=binding.run_id,
        operation_contract_digest=sha256_digest(binding.operation_contract_ref),
        idempotency_key=binding.side_effect_key,
        request_digest=binding.request_fingerprint,
        semantic_binding_id=binding.binding_id,
        semantic_binding_digest=sha256_digest(binding),
        semantic_attempt_key=binding.semantic_attempt_key,
        unit_key=binding.runtime_unit.unit_key if binding.runtime_unit is not None else None,
        claimed_by=claimed_by,
        claimed_at=binding.bound_at,
    )

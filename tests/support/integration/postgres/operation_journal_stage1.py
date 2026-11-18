"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_operation_journal_stage1.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.domain.authoring.canonical import contract_fingerprint, sha256_digest
from mission_control.domain.execution.journal import (
    OperationEffectClaim,
    OperationJournalSettlement,
    OperationTechnicalAttempt,
)
from mission_control.domain.policies.contracts import (
    AcceptedOperationSettlementEvidence,
    ActorContext,
    ApplyAuthorityBatchAction,
    CommandResult,
    CommandStatus,
    DomainEventEnvelope,
    EffectSettlementOutcome,
    LifecycleCommand,
    RecordOperationSettlementEvidenceAction,
    RecordUsageAction,
    RunPhase,
    SettleEffectAction,
)
from tests.support.run_control import command as unit_command

NOW = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
# In-memory tests run in the literal "tenant-1" scope; the PostgreSQL test binds the
# canonical scope of its disposable common database for its duration.
_SCOPE = ["tenant-1"]


def command(run_id: str, version: int, command_id: str, action: object) -> LifecycleCommand:
    return unit_command(run_id, version, command_id, action).model_copy(
        update={"request_scope": _SCOPE[0]}
    )


def claim(*, run_id: str = "run-1", request_digest: str = DIGEST) -> OperationEffectClaim:
    return OperationEffectClaim(
        effect_claim_id="claim-1",
        request_scope=_SCOPE[0],
        belllabs_run_id=run_id,
        operation_contract_digest=DIGEST,
        idempotency_key="effect-key-1",
        request_digest=request_digest,
        semantic_binding_id="immutable-binding-1",
        semantic_binding_digest=DIGEST,
        semantic_attempt_key=f"{run_id}:operation:search:semantic-attempt:1",
        claimed_by="operation-worker",
        claimed_at=NOW,
    )


def attempt() -> OperationTechnicalAttempt:
    return OperationTechnicalAttempt(
        operation_attempt_id="technical-attempt-1",
        request_scope=_SCOPE[0],
        effect_claim_id="claim-1",
        technical_attempt=1,
        provider="fixture-provider",
        disposition="failed",
        idempotency_supported=True,
        retry_class="safe",
        usage={"tokens.total": 7},
        started_at=NOW,
        finished_at=NOW,
        failure_code="fixture_failure",
    )


def settlement() -> OperationJournalSettlement:
    values = {
        "settlement_id": "settlement-1",
        "request_scope": _SCOPE[0],
        "effect_claim_id": "claim-1",
        "settlement_revision": 1,
        "status": "failed",
        "usage": {"tokens.total": 7},
        "result_manifest_ref": "artifact:settlement-1",
        "result_manifest_digest": DIGEST,
        "result_manifest_size_bytes": 7,
        "failure_code": "fixture_failure",
        "detail": {"schema_version": "1"},
        "settled_at": NOW,
    }
    return OperationJournalSettlement.create(**values)


def authority_result(
    *,
    run_id: str,
    settlement_id: str = "settlement-1",
    revision: int = 1,
    version: int = 2,
    fingerprint: str | None = None,
) -> CommandResult:
    command = authority_command(
        run_id=run_id,
        settlement_id=settlement_id,
        revision=revision,
        resulting_version=version,
    )
    return CommandResult(
        command_id=(f"operation-authority-settlement:{settlement_id}:revision:{revision}"),
        idempotency_issuer="operation-journal",
        run_id=run_id,
        command_fingerprint=fingerprint or contract_fingerprint(command, exclude={"occurred_at"}),
        status=CommandStatus.ACCEPTED,
        resulting_run_version=version,
        phase=RunPhase.ACTIVE,
        reason_code="accepted",
        reason="operation authority accepted",
        recorded_at=NOW,
    )


def authority_command(
    *,
    run_id: str,
    settlement_id: str = "settlement-1",
    revision: int = 1,
    resulting_version: int = 2,
) -> LifecycleCommand:
    return LifecycleCommand(
        command_id=(f"operation-authority-settlement:{settlement_id}:revision:{revision}"),
        idempotency_issuer="operation-journal",
        request_scope=_SCOPE[0],
        run_id=run_id,
        expected_run_version=resulting_version - 1,
        actor=ActorContext(
            actor_id="operation-journal",
            authority_refs=frozenset(),
            permissions=frozenset(),
        ),
        action=ApplyAuthorityBatchAction(
            actions=(
                RecordUsageAction(
                    usage_id=settlement_id,
                    authority_ref="immutable-binding-1",
                    reservation_id="reservation-1",
                    actual_amounts={"tokens.total": 7},
                ),
                SettleEffectAction(
                    effect_id="claim-1",
                    settlement_id=settlement_id,
                    observation_id=f"observation:{settlement_id}",
                    outcome=EffectSettlementOutcome.FAILED,
                    usage_settlement_ref=settlement_id,
                    evidence_refs=("artifact:settlement-1",),
                ),
                RecordOperationSettlementEvidenceAction(
                    evidence=AcceptedOperationSettlementEvidence(
                        settlement_id=settlement_id,
                        settlement_payload_digest=settlement().settlement_digest,
                        accepted_by_authority_ref="immutable-binding-1",
                    )
                ),
            )
        ),
        reason="test authority settlement",
        evidence_refs=("immutable-binding-1", "artifact:settlement-1"),
        occurred_at=NOW,
        correlation_id="operation:test",
        causation_id="claim-1",
    )


def authority_event(
    command: LifecycleCommand,
    result: CommandResult,
) -> DomainEventEnvelope:
    action = command.action
    is_batch = isinstance(action, ApplyAuthorityBatchAction)
    payload = {"command_id": command.command_id}
    if is_batch:
        payload["authority_batch_digest"] = sha256_digest(action)
    return DomainEventEnvelope(
        event_id=f"event:{command.command_id}",
        event_type=(
            "workflow_run.apply_authority_batch"
            if is_batch
            else "workflow_run.record_usage"
            if isinstance(action, RecordUsageAction)
            else "workflow_run.claim_effect"
        ),
        aggregate_id=command.run_id,
        aggregate_version=result.resulting_run_version,
        sequence=1,
        occurred_at=NOW,
        recorded_at=NOW,
        actor=command.actor,
        correlation_id=command.correlation_id,
        causation_id=command.causation_id,
        payload=payload,
    )

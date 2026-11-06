"""B4a: durable, bounded receipt references without retaining arbitrary settlement detail."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from mission_control.domain.execution.contracts import RuntimeResult
from mission_control.domain.execution.invocation_settlement import (
    InvocationSettlement,
    SettlementOutcome,
    WaitReason,
)

AT = datetime(2026, 10, 29, tzinfo=UTC)
DECISION = "kh:aiengineer-postgres/decision/opaque-native@use-decision.v1"
SUBJECT = "kh:aiengineer-postgres/report/r1@research-report.v2#sha256:" + "a" * 64
EFFECT = "ek1:" + "b" * 64
RECEIPT = "aiengineer-postgres/native_receipt/r1@receipt.v1"
REFERENCES = {
    "decision": DECISION,
    "subject_ref": SUBJECT,
    "state": "applied",
    "effect_key": EFFECT,
    "receipt_ref": RECEIPT,
    "receipt_digest": "sha256:" + "c" * 64,
    "journal_state": "applied",
    "refusal_code": None,
}


def saved():
    return InvocationSettlement.save(
        request_scope="scope",
        run_id="run",
        binding_id="binding",
        operation_ref="op",
        operation_attempt=1,
        unit_key="unit",
        execution_generation=1,
        result=RuntimeResult(output_text="PRIVATE_MODEL_BODY"),
        recovery_owner="workflow",
        claim_fence=2,
        at=AT,
    )


def test_reference_metadata_survives_advance_json_and_public_evidence():
    original = saved()
    complete = original.advanced(
        SettlementOutcome.done(
            detail={
                "provider_output": "PRIVATE_DETAIL_BODY",
                "authorization": "PRIVATE_SECRET",
                "native_effects": [
                    REFERENCES
                    | {"raw_receipt": "PRIVATE_RECEIPT_BODY", "credential": "PRIVATE_KEY"}
                ],
            }
        ),
        claim_fence=2,
        at=AT + timedelta(seconds=1),
    )
    restarted = InvocationSettlement.model_validate_json(complete.model_dump_json())
    evidence = restarted.evidence()["invocation_settlement"]
    assert evidence["native_effects"] == [
        {key: value for key, value in REFERENCES.items() if value is not None}
    ]
    assert "PRIVATE_" not in json.dumps(evidence)
    assert "PRIVATE_DETAIL" not in complete.model_dump_json()
    assert complete.saved_result == original.saved_result
    assert complete.saved_result_digest == original.saved_result_digest


def test_unavailable_pass_preserves_latest_reference_evidence_until_explicit_refresh():
    first = saved().advanced(
        SettlementOutcome(
            state="waiting",
            reason=WaitReason.REVIEW_PENDING,
            pending_reviews=("review:1",),
            detail={
                "native_effects": [
                    REFERENCES
                    | {
                        "state": "pending_review",
                        "receipt_ref": None,
                        "receipt_digest": None,
                        "journal_state": None,
                    }
                ]
            },
        ),
        claim_fence=2,
        at=AT,
    )
    unavailable = first.advanced(
        SettlementOutcome.unavailable(ConnectionError("PRIVATE_NETWORK")),
        claim_fence=3,
        at=AT + timedelta(seconds=1),
    )
    assert (
        unavailable.evidence()["invocation_settlement"]["native_effects"]
        == first.evidence()["invocation_settlement"]["native_effects"]
    )
    refreshed = unavailable.advanced(
        SettlementOutcome.done(detail={"native_effects": [REFERENCES]}),
        claim_fence=3,
        at=AT + timedelta(seconds=2),
    )
    assert (
        refreshed.evidence()["invocation_settlement"]["native_effects"][0]["receipt_ref"] == RECEIPT
    )
    assert (
        first.evidence()["invocation_settlement"]["native_effects"][0]["state"] == "pending_review"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"state": "PRIVATE_RAW_BODY"},
        {"receipt_ref": "secret text"},
        {"effect_key": "a" * 513},
        {"receipt_digest": "not-a-digest"},
    ],
)
def test_invalid_reference_metadata_is_rejected(updates):
    with pytest.raises(ValueError):
        saved().advanced(
            SettlementOutcome.done(detail={"native_effects": [REFERENCES | updates]}),
            claim_fence=2,
            at=AT,
        )


def test_reference_list_is_bounded_and_legacy_records_default_empty():
    with pytest.raises(ValueError):
        saved().advanced(
            SettlementOutcome.done(detail={"native_effects": [REFERENCES] * 257}),
            claim_fence=2,
            at=AT,
        )
    legacy = saved().model_dump(mode="json")
    legacy.pop("native_effects", None)
    restored = InvocationSettlement.model_validate(legacy)
    assert restored.evidence()["invocation_settlement"].get("native_effects", []) == []


def test_explicit_snapshot_replaces_or_clears_without_mutating_the_source_outcome():
    from copy import deepcopy

    source = {"native_effects": [REFERENCES | {"raw": {"body": "PRIVATE_PAYLOAD"}}]}
    original_source = deepcopy(source)
    first = saved().advanced(
        SettlementOutcome(
            state="waiting",
            reason=WaitReason.EFFECT_PENDING,
            pending_effects=(EFFECT,),
            detail=source,
        ),
        claim_fence=2,
        at=AT,
    )
    replacement = REFERENCES | {
        "effect_key": "ek1:" + "d" * 64,
        "state": "refused",
        "receipt_ref": None,
        "receipt_digest": None,
        "journal_state": "rejected",
        "refusal_code": "STALE_DECISION",
    }
    second = first.advanced(
        SettlementOutcome(
            state="waiting",
            reason=WaitReason.REVIEW_PENDING,
            pending_reviews=("review:1",),
            detail={"native_effects": [replacement]},
        ),
        claim_fence=2,
        at=AT + timedelta(seconds=1),
    )
    projection = second.evidence()["invocation_settlement"]["native_effects"]
    assert projection[0]["effect_key"] != EFFECT
    assert "receipt_ref" not in projection[0]
    assert first.evidence()["invocation_settlement"]["native_effects"][0]["receipt_ref"] == RECEIPT
    cleared = second.advanced(
        SettlementOutcome.done(detail={"native_effects": []}),
        claim_fence=2,
        at=AT + timedelta(seconds=2),
    )
    assert cleared.evidence()["invocation_settlement"].get("native_effects", []) == []
    assert source == original_source


@pytest.mark.asyncio
async def test_actual_native_outcome_accepts_canonical_opaque_receipt_identifiers():
    from dataclasses import replace

    from mission_control.application.knowledge.native_write import NativeWriteOutcome
    from mission_control.application.ports.knowledge import RecordedUseDecision
    from mission_control.contracts.knowledge_protocol import digest_canonical
    from mission_control.contracts.knowledge_protocol_results import OperationReceipt
    from tests.unit.knowledge.test_gateway import call, harness

    h = harness()
    result = await h.gateway.invoke(call(), h.access())
    assert result.receipt is not None and result.journal is not None
    document = result.receipt.model_dump(mode="json")
    document.pop("digest")
    document["nativeReceiptRef"]["id"] = "native/opaque@1"
    receipt = OperationReceipt(**document, digest=digest_canonical(document))
    actual = replace(
        result,
        receipt=receipt,
        journal=replace(
            result.journal,
            terminal_receipt_ref=receipt.receipt_ref(),
            receipt_digest=receipt.digest,
        ),
    )
    decision = RecordedUseDecision(
        handle=DECISION.replace("opaque-native", "opaque/native@1"),
        binding_id=receipt.nativeReceiptRef.binding,
        tenant_id=receipt.nativeReceiptRef.tenant,
        use_decision_id="opaque/native@1",
        bound_effect_digest=result.journal.bound_effect_digest,
        processed_epoch=1,
        plan={},
        subject_ref=SUBJECT.replace("/r1@", "/report/opaque@1@"),
    )
    native = NativeWriteOutcome("applied", decision, result=actual)
    projected = (
        saved()
        .advanced(
            SettlementOutcome.done(detail={"native_effects": [native.document()]}),
            claim_fence=2,
            at=AT,
        )
        .evidence()["invocation_settlement"]["native_effects"][0]
    )
    assert projected["receipt_ref"] == receipt.receipt_ref()
    assert "native/opaque@1@" in projected["receipt_ref"]
    assert projected["decision"] == decision.handle
    assert projected["subject_ref"] == decision.subject_ref


def test_existing_reference_count_bound_accepts_more_than_sixty_four():
    complete = saved().advanced(
        SettlementOutcome.done(detail={"native_effects": [REFERENCES] * 65}), claim_fence=2, at=AT
    )
    assert len(complete.evidence()["invocation_settlement"]["native_effects"]) == 65

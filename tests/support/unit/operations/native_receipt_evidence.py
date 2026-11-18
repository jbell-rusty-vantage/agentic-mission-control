"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_native_receipt_evidence.py.
"""

from datetime import UTC, datetime

from mission_control.domain.execution.contracts import RuntimeResult
from mission_control.domain.execution.invocation_settlement import InvocationSettlement

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

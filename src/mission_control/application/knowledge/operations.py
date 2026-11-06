"""Knowledge calls, results and settlement rules of the gateway (M02).

A :class:`KnowledgeCall` is what a tool projection asks for: an operation, a capability pin
and a JSON payload. It carries no origin, tenant or credential: those are host-derived from
the live :class:`~mission_control.application.knowledge.access.InvocationAccess`, so an
agent-supplied ``origin`` field is refused by the model itself.

The native bytes of a payload are its ``kop-canonical-json.v1`` UTF-8 text, so the envelope's
inline payload, ``payloadDigest`` and the bound effect agree byte for byte on every retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.application.ports.knowledge import HandleRecord, JournalRecord, Settlement
from mission_control.contracts.knowledge_protocol import (
    ASSESSMENT_OPERATIONS,
    EFFECTFUL_OPERATIONS,
    HANDLE_OPERATIONS,
    Governors,
    JsonDocument,
    NativeContract,
    OperationHandle,
    OperationName,
    PinnedSchemaRef,
    Ref,
    canonical_json,
)
from mission_control.contracts.knowledge_protocol_results import (
    OperationReceipt,
    OperationStatus,
    ProtocolError,
    ProtocolErrorCode,
    ReceiptDelivery,
    ReceiptFound,
    ReceiptNotFound,
    ReceiptUnresolved,
)
from mission_control.domain.knowledge.effects import JournalState

LookupResult = ReceiptFound | ReceiptNotFound | ReceiptUnresolved
# Non-effect operations that answer with a durable remote handle (release 1.6.0 table).
NON_EFFECT_HANDLE_OPERATIONS: frozenset[str] = frozenset(
    (HANDLE_OPERATIONS - EFFECTFUL_OPERATIONS) | {"knowledge.read"}
)
# W1 D22: every operation whose K01 handle the gateway records in `knowledge_operation_handle`:
# an effect that answers a handle (`_effect`), the non-effect handle operations
# (`_handle_operation`) and the trusted path's evaluation context and assessment operations
# (`trusted`, whose set is `ASSESSMENT_OPERATIONS` plus `knowledge.read`). Release 1.9.0's 0067
# makes the table's operation check exactly this set.
RECORDED_HANDLE_OPERATIONS: frozenset[str] = (
    EFFECTFUL_OPERATIONS | NON_EFFECT_HANDLE_OPERATIONS | ASSESSMENT_OPERATIONS | {"knowledge.read"}
)


class KnowledgeCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: OperationName
    capability_pin: str = Field(min_length=1)
    native_contract: NativeContract
    payload: JsonDocument
    governors: Governors
    required_capabilities: tuple[str, ...] = ()
    pinned_schema: PinnedSchemaRef | None = None
    upstream: tuple[Ref, ...] = ()
    # A host-supplied stable logical key (e.g. the tool-call idempotency key). When absent the
    # gateway mints one from the origin scope, operation, capability pin and payload digest.
    effect_key: str | None = Field(default=None, min_length=1, max_length=200)
    # For a non-effect handle operation: the stable request key the binding deduplicates
    # starts by (a retry after transport loss is the same request). Absent: a fresh id.
    request_key: str | None = Field(default=None, min_length=1, max_length=200)
    # What the operation is about (a submission id, a report handle), recorded with the handle.
    subject_ref: str | None = Field(default=None, min_length=1, max_length=2048)
    # `knowledge.apply` only (K01 round 2): the plan-level part of the payload (e.g. the native
    # intent) that the binding's use decision binds. The bound effect digest is then over its
    # canonical bytes and the originating origin; the semantic payload digest stays over the
    # whole payload. Absent: the bound digest is over the whole payload.
    plan: JsonDocument | None = None
    # `knowledge.apply` only: the plan-level bound digest a recorded use decision binds when the
    # host cannot recompute it from bytes it holds (the AI Engineer ingestion planner computes
    # it over planned proposal bytes); the binding recomputes and refuses a mismatch.
    bound_effect_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    # K01 round 4: the declared exact use of an effectful operation (both or neither), from
    # the recorded use decision (apply) or the registered task (register).
    use: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.-]{0,119}$")
    audience: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.-]{0,119}$")

    @model_validator(mode="after")
    def _plan_only_for_apply(self) -> KnowledgeCall:
        if (
            self.plan is not None or self.bound_effect_digest is not None
        ) and self.operation != "knowledge.apply":
            raise ValueError("a plan-level digest applies to knowledge.apply only")
        if self.plan is not None and self.bound_effect_digest is not None:
            raise ValueError("name the plan or its bound digest, not both")
        if (self.use is None) != (self.audience is None):
            raise ValueError("use and audience are declared together")
        if self.use is not None and self.operation not in EFFECTFUL_OPERATIONS:
            raise ValueError("a declared use belongs to an effectful operation only")
        return self

    @property
    def effectful(self) -> bool:
        return self.operation in EFFECTFUL_OPERATIONS

    @property
    def handle_operation(self) -> bool:
        return self.operation in NON_EFFECT_HANDLE_OPERATIONS

    def native_bytes(self) -> bytes:
        return canonical_json(self.payload).encode("utf-8")

    def plan_bytes(self) -> bytes | None:
        return None if self.plan is None else canonical_json(self.plan).encode("utf-8")


class KnowledgeRefused(RuntimeError):
    """A host-side refusal before or instead of transmission (typed K01 error code)."""

    def __init__(self, code: ProtocolErrorCode, message: str, *, effect_key: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code: ProtocolErrorCode = code
        self.effect_key = effect_key


@dataclass(frozen=True)
class KnowledgeResult:
    operation: str
    effect_key: str | None = None
    journal: JournalRecord | None = None
    handle: OperationHandle | None = None
    handle_record: HandleRecord | None = None
    receipt: OperationReceipt | None = None
    status: OperationStatus | None = None
    lookup: LookupResult | None = None
    refusal_code: str | None = None
    # W1 D11: the typed KS refusal behind `refusal_code` (message, details), when one answered.
    refusal: ProtocolError | None = None
    # W1 D12: the outcome was replayed from the journal of an identical earlier call.
    replayed: bool = False

    @property
    def state(self) -> JournalState | None:
        return None if self.journal is None else self.journal.state

    def document(self) -> dict[str, Any]:
        """Structured, credential-free tool output (never provider text as control)."""

        return {
            "operation": self.operation,
            "effect_key": self.effect_key,
            "journal_state": None if self.journal is None else self.journal.state.value,
            "receipt_ref": None if self.journal is None else self.journal.terminal_receipt_ref,
            "receipt_digest": None if self.receipt is None else self.receipt.digest,
            "handle": None if self.handle is None else self.handle.model_dump(mode="json"),
            "status": None if self.status is None else self.status.state,
            "result_ref": None
            if self.status is None or self.status.resultRef is None
            else self.status.resultRef.model_dump(mode="json"),
            "refusal_code": self.refusal_code,
            "receipt_outcome": None if self.receipt is None else self.receipt.outcome,
            # Admitted and queued for delivery: not applied yet, not a refusal; the host settles
            # it from a later receipt lookup (reconcile) before the run can finalize.
            "pending_delivery": pending_delivery(self.receipt, self.lookup),
            # What the receipt says the effect produced, as exact handles the agent can
            # select (``submit_output``) or read back (``knowledge_read``).
            "affected": []
            if self.receipt is None
            else [
                {
                    "handle": f"kh:{ref.binding}/{ref.kind}/{ref.id}@{ref.version}",
                    "digest": ref.digest,
                }
                for ref in self.receipt.affectedRefs
            ],
        }


def pending_delivery(receipt: OperationReceipt | None, lookup: object | None = None) -> bool:
    """The effect was admitted and queued for delivery (`pending_dispatch`), not yet applied.

    Such a receipt is not a settlement: the journal stays ``uncertain`` (blocking finalization
    and any redispatch) until a later ``receipt.get`` reports the delivered outcome.
    """

    found = receipt if receipt is not None else getattr(lookup, "receipt", None)
    if not isinstance(found, OperationReceipt) or found.outcome != "pending_dispatch":
        return False
    delivery = getattr(lookup, "delivery", None)
    # No composed delivery yet, or still queued/in flight: pending. `failed` is not pending any
    # more and proves nothing about the target either; it stays an unresolved effect.
    return delivery is None or delivery.state in {"pending", "dispatched"}


def settlement_from_delivery(
    receipt: OperationReceipt, delivery: ReceiptDelivery | None
) -> Settlement | None:
    """A `pending_dispatch` receipt settles only from a later lookup's composed delivery.

    `applied` settles applied (the target acknowledged); `revoked` settles rejected (the queued
    effect was withdrawn before it reached the target). `pending`, `dispatched` and `failed`
    leave the effect unresolved.
    """

    if receipt.outcome != "pending_dispatch" or delivery is None:
        return None
    states = {"applied": JournalState.APPLIED, "revoked": JournalState.REJECTED}
    state = states.get(delivery.state)
    if state is None:
        return None
    return Settlement(
        state=state,
        terminal_receipt_ref=receipt.receipt_ref(),
        receipt_digest=receipt.digest,
        reconciled=True,
    )


def settlement_from_receipt(receipt: OperationReceipt, *, reconciled: bool) -> Settlement:
    if receipt.outcome == "pending_dispatch":
        raise ValueError("a pending_dispatch receipt is not a settlement")
    return Settlement(
        state=JournalState(receipt.outcome),
        terminal_receipt_ref=receipt.receipt_ref(),
        receipt_digest=receipt.digest,
        reconciled=reconciled,
    )


def settlement_without_receipt(status: OperationStatus) -> Settlement | None:
    """A terminal status that proves no effect happened settles ``rejected``; else ``None``.

    Only refused, failed or cancelled computations with no unresolved effects qualify; a
    success, partial or hold without a receipt stays unresolved until the receipt is found.
    """

    if status.state not in {"rejected", "failed", "cancelled"} or status.unresolvedEffects:
        return None
    if status.error is not None:
        code = status.error.code
    else:
        code = "CANCELLED" if status.state == "cancelled" else "INTERNAL"
    return Settlement(state=JournalState.REJECTED, refusal_code=code)


__all__ = [
    "NON_EFFECT_HANDLE_OPERATIONS",
    "RECORDED_HANDLE_OPERATIONS",
    "KnowledgeCall",
    "KnowledgeRefused",
    "KnowledgeResult",
    "LookupResult",
    "pending_delivery",
    "settlement_from_delivery",
    "settlement_from_receipt",
    "settlement_without_receipt",
]

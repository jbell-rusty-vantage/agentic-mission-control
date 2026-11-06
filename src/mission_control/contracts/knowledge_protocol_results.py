"""Knowledge Operation Protocol (K01) result, descriptor and credential wire models.

Companions to :mod:`mission_control.contracts.knowledge_protocol` for the shapes a binding
returns (``operation-status.v2``, ``operation-receipt.v2``, ``receipt-lookup.v2``,
``protocol-error.v2``, ``binding-descriptor.v2``) and the claims Mission Control mints for one
dispatch (``credential-claims.v2``). The JSON Schemas under
``tests/fixtures/knowledge_protocol`` are the authority; these models never relax them, and
they add the K01 ``superRefine`` rules the schemas cannot express: the fixed
retryable/domain-outcome class of every error code, a terminal status without a retry hint
(and a live one with it), ``failed`` with a typed error, ``waiting_review`` with its review,
cancellation with its request id, and the credential lifetime/scope/recovery rules.

**Effect-scoped recovery (Checkpoint A decision, SPRINT-V-DESIGN §10.1).** ``recovery`` is
``{scope, authorityRef, effectKey, boundEffectDigest}``. ``read_only`` is the receipt-lookup
authority after an invocation ended: a ``recovery`` origin, ``receipt.get``/``operation.get``
only. ``effect`` lets a *new attempt* re-dispatch one exact uncertain effect: the new attempt
is the credential origin (``current_caller_origin``), the envelope keeps the unchanged
``originating_origin`` and identical bound bytes, and the grant names that exact effect key and
bound digest, which must equal the credential ``effect``. This is the agreed K01 shape helper
E-KS is adding to ``credential-claims.v2``; until its schema and vectors land in
``tests/fixtures/knowledge_protocol`` the conformance tests mark the dependency explicitly.

Credential claims never carry the signed token itself; the token bytes stay opaque to every
model here so nothing can serialize them into a journal, log or artifact.
"""

# ruff: noqa: N815

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    TypeAdapter,
    model_serializer,
    model_validator,
)

from mission_control.contracts.knowledge_assessment import OBSERVER_ROLES, CredentialEvaluation
from mission_control.contracts.knowledge_protocol import (
    EFFECTFUL_OPERATIONS,
    EVALUATOR_OPERATIONS,
    TERMINAL_STATES,
    Digest,
    Id,
    Instant,
    JsonDocument,
    Name,
    OperationHandle,
    OperationName,
    OperationState,
    Origin,
    Ref,
    SafeInt,
    SchemaVersion,
    ScopeId,
)

CREDENTIAL_TOKEN_TYPE = "ks-knowledge-operation+jwt"  # noqa: S105 - a JWT `typ`, not a secret
CREDENTIAL_MAX_LIFETIME_SECONDS = 300
DEFAULT_CLOCK_SKEW_SECONDS = 30


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


ProtocolErrorCode = Literal[
    "ORIGIN_MISMATCH",
    "SCOPE_DENIED",
    "EFFECT_CONFLICT",
    "SCHEMA_UNSUPPORTED",
    "EXACT_REVISION_UNAVAILABLE",
    "REVIEW_REQUIRED",
    "BUDGET_EXHAUSTED",
    "UNSUPPORTED_MEDIA",
    "STALE_DECISION",
    "UNRESOLVED_EFFECT",
    "INDEPENDENCE_UNPROVEN",
    "INVALID_ENVELOPE",
    "CAPABILITY_UNAVAILABLE",
    "NOT_FOUND",
    "CANCELLED",
    "INTERNAL",
]

# K01 `ERROR_CLASSES`: (retryable, domainOutcome) per code. A binding that answers another
# class for a code is answering outside the protocol, and the document is refused.
ERROR_CLASSES: Final[dict[str, tuple[bool, bool]]] = {
    "ORIGIN_MISMATCH": (False, False),
    "SCOPE_DENIED": (False, False),
    "EFFECT_CONFLICT": (False, False),
    "SCHEMA_UNSUPPORTED": (False, False),
    "EXACT_REVISION_UNAVAILABLE": (False, True),
    "REVIEW_REQUIRED": (False, True),
    "BUDGET_EXHAUSTED": (False, True),
    "UNSUPPORTED_MEDIA": (False, True),
    "STALE_DECISION": (False, True),
    "UNRESOLVED_EFFECT": (False, False),
    "INDEPENDENCE_UNPROVEN": (False, True),
    "INVALID_ENVELOPE": (False, False),
    "CAPABILITY_UNAVAILABLE": (True, False),
    "NOT_FOUND": (False, False),
    "CANCELLED": (False, False),
    "INTERNAL": (True, False),
}


class ErrorCorrelation(_Strict):
    dispatchId: Id | None
    operationId: Id | None
    effectKey: Id | None


class ProtocolError(_Strict):
    protocolVersion: Literal["ks.knowledge_operation.v2"]
    code: ProtocolErrorCode
    message: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    retryable: bool
    domainOutcome: bool
    correlation: ErrorCorrelation
    details: JsonDocument | None
    occurredAt: Instant

    @model_validator(mode="after")
    def _classified(self) -> ProtocolError:
        retryable, domain = ERROR_CLASSES[self.code]
        if self.retryable != retryable or self.domainOutcome != domain:
            raise ValueError(
                f"{self.code} is classified retryable={retryable} domainOutcome={domain}"
            )
        return self


def protocol_error(
    code: ProtocolErrorCode,
    message: str,
    *,
    occurred_at: str,
    dispatch_id: str | None = None,
    operation_id: str | None = None,
    effect_key: str | None = None,
    details: JsonDocument | None = None,
) -> ProtocolError:
    """A typed error with the protocol's fixed classification (K01 ``protocolError``)."""

    retryable, domain = ERROR_CLASSES[code]
    return ProtocolError(
        protocolVersion="ks.knowledge_operation.v2",
        code=code,
        message=message,
        retryable=retryable,
        domainOutcome=domain,
        correlation=ErrorCorrelation(
            dispatchId=dispatch_id, operationId=operation_id, effectKey=effect_key
        ),
        details=details,
        occurredAt=occurred_at,
    )


class UnresolvedEffect(_Strict):
    effectKey: Id
    boundEffectDigest: Digest
    dispatchId: Id
    reconciliation: Literal["pending", "lookup_negative", "lookup_failed", "resolved"]
    lastCheckedAt: Instant | None


class ArtifactRef(Ref):
    kind: Literal["artifact"]


class AdjudicationRef(Ref):
    kind: Literal["adjudication"]


class OperationStatus(_Strict):
    handle: OperationHandle
    state: OperationState
    revision: Annotated[int, Field(ge=1, le=2**53 - 1)]
    createdAt: Instant
    updatedAt: Instant
    progressRef: ArtifactRef | None
    pendingReviewRef: AdjudicationRef | None
    resultRef: Ref | None
    error: ProtocolError | None
    unresolvedEffects: list[UnresolvedEffect]
    retryAfterMs: Annotated[int, Field(ge=100, le=300_000)] | None
    cancelRequestId: Id | None

    @model_validator(mode="after")
    def _rules(self) -> OperationStatus:
        terminal = self.state in TERMINAL_STATES
        if terminal and self.retryAfterMs is not None:
            raise ValueError("terminal status carries no retry hint")
        if not terminal and self.retryAfterMs is None:
            raise ValueError("non-terminal status needs a retry hint")
        if self.state == "failed" and self.error is None:
            raise ValueError("failed requires a typed error")
        if self.state == "waiting_review" and self.pendingReviewRef is None:
            raise ValueError("waiting_review names its review")
        if self.state in {"cancelling", "cancelled"} and self.cancelRequestId is None:
            raise ValueError("cancellation names its request id")
        return self


class ReceiptEffect(_Strict):
    effectKey: Id
    semanticPayloadDigest: Digest
    originatingOrigin: Origin
    boundEffectDigest: Digest
    canonicalization: Literal["kop-canonical-json.v1"]
    currentCallerOrigin: Origin
    dispatchId: Id
    envelopeDigest: Digest
    dispatchSequence: Annotated[int, Field(ge=1, le=2**53 - 1)]


class ConcurrencyToken(_Strict):
    before: Annotated[str, StringConstraints(max_length=400)] | None
    after: Annotated[str, StringConstraints(max_length=400)] | None


class ItemOutcome(_Strict):
    itemId: Id
    outcome: Literal["admitted", "held", "rejected", "superseded", "duplicate"]
    reason: Annotated[str, StringConstraints(max_length=400)] | None
    ref: Ref | None


# `pending_dispatch` (K01 round 2): admitted and queued for delivery (Biotech outbox), never
# `applied`; the host keeps the effect unresolved until `receipt.get` reports the delivery.
ReceiptOutcome = Literal["applied", "noop", "partial", "rejected", "pending_dispatch"]
SETTLED_RECEIPT_OUTCOMES: Final = frozenset({"applied", "noop", "partial", "rejected"})


class OperationReceipt(_Strict):
    handle: OperationHandle
    effect: ReceiptEffect
    outcome: ReceiptOutcome
    nativeReceiptRef: Ref
    affectedRefs: list[Ref]
    concurrencyToken: ConcurrencyToken
    processedRevocationEpoch: SafeInt
    itemOutcomes: list[ItemOutcome]
    appliedAt: Instant
    details: JsonDocument | None
    digest: Digest

    def receipt_ref(self) -> str:
        """Stable text reference to the native receipt (journal ``terminal_receipt_ref``)."""

        ref = self.nativeReceiptRef
        return f"{ref.binding}/{ref.kind}/{ref.id}@{ref.version}"


DeliveryState = Literal["pending", "dispatched", "applied", "revoked", "failed"]


class ReceiptDelivery(_Strict):
    """Delivery state composed into a lookup of a `pending_dispatch` receipt (K01 round 2).

    The receipt itself stays immutable; the binding reads the outbox acknowledgment at lookup
    time. Only `applied` proves the queued effect reached its target.
    """

    state: DeliveryState
    dispatchId: Id
    targetBinding: ScopeId
    nativeState: Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,40}$")]
    ackDigest: Digest | None
    ackedAt: Instant | None
    graphTxRef: Annotated[str, StringConstraints(min_length=1, max_length=400)] | None
    checkedAt: Instant


class ReceiptFound(_Strict):
    disposition: Literal["found"]
    receipt: OperationReceipt
    delivery: ReceiptDelivery | None = None


class ReceiptNotFound(_Strict):
    disposition: Literal["not_found"]
    checkedAt: Instant


class ReceiptUnresolved(_Strict):
    disposition: Literal["unresolved"]
    error: ProtocolError


ReceiptLookup = Annotated[
    ReceiptFound | ReceiptNotFound | ReceiptUnresolved, Field(discriminator="disposition")
]
RECEIPT_LOOKUP: TypeAdapter[ReceiptFound | ReceiptNotFound | ReceiptUnresolved] = TypeAdapter(
    ReceiptLookup
)


class BindingGuarantees(_Strict):
    exactRead: Literal["exact_revision", "latest_only"]
    receiptLookup: Literal["by_effect_key", "unsupported"]
    nativeCancellation: Literal["native", "stop_dispatch_and_reconcile"]
    admission: Literal["exact_use_decision", "unsupported"]
    revocation: Literal["epoch_checked", "unsupported"]
    writeAtomicity: Literal["single_transaction", "marker_plus_outbox"]


class PinnedSchema(_Strict):
    name: Name
    version: SchemaVersion
    digest: Digest


class Qualification(_Strict):
    capability: Name
    receiptRef: Id
    tier: Literal["T0", "T1-KS", "T1-MC", "T2-control", "Q"]
    recordedAt: Instant
    digest: Digest


class BindingDescriptor(_Strict):
    protocolVersions: Annotated[list[Literal["ks.knowledge_operation.v2"]], Field(min_length=1)]
    binding: Name
    application: Name
    coreSchemas: list[SchemaVersion]
    operations: list[OperationName]
    # WI-03 S7: what runs `report.assess`'s census (a scripted double only on a disposable host).
    auditorKind: Literal["scripted", "independent", "none"]
    reportKinds: list[Name]
    media: list[Name]
    guarantees: BindingGuarantees
    signingIssuer: Name
    pinnedSchema: PinnedSchema
    qualification: list[Qualification]
    describedAt: Instant


class CredentialEffect(_Strict):
    effectKey: Id
    boundEffectDigest: Digest


RecoveryScope = Literal["read_only", "effect"]
READ_ONLY_RECOVERY_OPERATIONS: Final = frozenset({"receipt.get", "operation.get"})
EFFECT_RECOVERY_OPERATIONS: Final = frozenset(
    EFFECTFUL_OPERATIONS | {"receipt.get", "operation.get"}
)


class CredentialRecovery(_Strict):
    """Explicit host recovery authority (agreed K01 effect-scoped shape, see module doc)."""

    scope: RecoveryScope
    authorityRef: Id
    effectKey: Id | None
    boundEffectDigest: Digest | None

    @model_validator(mode="after")
    def _scoped(self) -> CredentialRecovery:
        if self.scope == "effect" and (self.effectKey is None or self.boundEffectDigest is None):
            raise ValueError("an effect-scoped recovery names its exact effect key and digest")
        if (self.effectKey is None) != (self.boundEffectDigest is None):
            raise ValueError("a recovery grant names both its effect key and bound digest")
        return self

    @property
    def read_only(self) -> bool:
        return self.scope == "read_only"


class CredentialClaims(_Strict):
    typ: Literal["ks-knowledge-operation+jwt"]
    iss: Name
    aud: Name
    sub: Id
    jti: Id
    iat: SafeInt
    nbf: SafeInt
    exp: SafeInt
    tenant: ScopeId
    application: Name
    binding: Name
    origin: Origin
    operations: Annotated[list[OperationName], Field(min_length=1)]
    effect: CredentialEffect | None
    dispatchId: Id
    recovery: CredentialRecovery | None
    # WI-03: the host's evaluator grant for a separate judge/auditor/reviewer invocation. Absent
    # on the wire when None (the KS claim is optional, not nullable).
    evaluation: CredentialEvaluation | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_evaluation(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        if data.get("evaluation") is None:
            data.pop("evaluation", None)
        return data

    @model_validator(mode="after")
    def _rules(self) -> CredentialClaims:
        if not self.nbf <= self.exp or not self.iat < self.exp:
            raise ValueError("a credential expires after it is issued and becomes valid")
        if self.exp - self.iat > CREDENTIAL_MAX_LIFETIME_SECONDS:
            raise ValueError("a knowledge operation credential lives at most 300 seconds")
        if self.tenant != self.origin.tenantId or self.application != self.origin.applicationId:
            raise ValueError("credential tenant and application are the origin's")
        if self.sub != self.origin.subject:
            raise ValueError("credential subject is the origin subject")
        operations = set(self.operations)
        if operations & EFFECTFUL_OPERATIONS and self.effect is None:
            raise ValueError("effectful grants bind one exact effect")
        evaluation = self.evaluation
        if evaluation is not None:
            if not operations <= EVALUATOR_OPERATIONS:
                raise ValueError(
                    "an evaluator credential grants assessment and read operations only"
                )
            if self.recovery is not None:
                raise ValueError("an evaluator credential carries no recovery")
            if "report.observe" in operations and evaluation.role not in OBSERVER_ROLES:
                raise ValueError("report.observe needs an observer role")
            if "report.review" in operations and evaluation.role != "human_reviewer":
                raise ValueError("report.review needs a reviewer")
        elif operations & {"report.observe", "report.review"}:
            raise ValueError("report.observe and report.review need the host's evaluator grant")
        recovery = self.recovery
        if self.origin.kind == "recovery" and (recovery is None or not recovery.read_only):
            raise ValueError("a recovery origin carries read-only recovery authority")
        if recovery is None:
            return self
        if recovery.read_only:
            if self.origin.kind != "recovery":
                raise ValueError("read-only recovery claims need a recovery origin")
            if recovery.authorityRef != self.origin.recoveryAuthorityRef:
                raise ValueError("recovery authority differs from the origin's")
            if not operations <= READ_ONLY_RECOVERY_OPERATIONS:
                raise ValueError("read-only recovery permits receipt and status lookups only")
            return self
        # Effect-scoped: the new attempt itself is the caller; the grant is not an origin.
        if self.origin.kind not in {"mission_invocation", "durable_worker"}:
            raise ValueError("effect-scoped recovery is presented by a live invocation")
        if not operations <= EFFECT_RECOVERY_OPERATIONS:
            raise ValueError("effect-scoped recovery grants the bound effect only")
        if self.effect is None or (
            self.effect.effectKey != recovery.effectKey
            or self.effect.boundEffectDigest != recovery.boundEffectDigest
        ):
            raise ValueError("effect-scoped recovery covers exactly the credential's effect")
        return self


__all__ = [
    "CREDENTIAL_MAX_LIFETIME_SECONDS",
    "CREDENTIAL_TOKEN_TYPE",
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "EFFECT_RECOVERY_OPERATIONS",
    "ERROR_CLASSES",
    "READ_ONLY_RECOVERY_OPERATIONS",
    "RECEIPT_LOOKUP",
    "SETTLED_RECEIPT_OUTCOMES",
    "AdjudicationRef",
    "ArtifactRef",
    "BindingDescriptor",
    "BindingGuarantees",
    "ConcurrencyToken",
    "CredentialClaims",
    "CredentialEffect",
    "CredentialRecovery",
    "DeliveryState",
    "ErrorCorrelation",
    "ItemOutcome",
    "OperationReceipt",
    "OperationStatus",
    "PinnedSchema",
    "ProtocolError",
    "ProtocolErrorCode",
    "Qualification",
    "ReceiptDelivery",
    "ReceiptEffect",
    "ReceiptFound",
    "ReceiptLookup",
    "ReceiptNotFound",
    "ReceiptOutcome",
    "ReceiptUnresolved",
    "RecoveryScope",
    "UnresolvedEffect",
    "protocol_error",
]

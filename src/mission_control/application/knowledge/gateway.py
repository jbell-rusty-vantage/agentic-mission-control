"""The knowledge gateway (Sprint V M02, design §4/§5): journal first, receipt first.

For an effectful operation (``knowledge.apply``, ``report.register``) the gateway:

1. binds the native bytes to the originating origin (K01 ``bind_effect``) under a host-minted
   or host-supplied effect key, refusing ``EFFECT_CONFLICT`` (same key, other bytes) and
   ``ORIGIN_MISMATCH`` (a caller other than the originating one without an explicit
   :class:`~mission_control.application.knowledge.access.RecoveryGrant` for that exact key
   and digest) before anything leaves the process;
2. journals ``prepared`` (race-safe admission), then mints a fresh 300 s credential and
   verifies its claims (issuer, audience, binding, scope, origin, operations, effect, dispatch
   and recovery authority), then journals ``dispatched`` (compare-and-set: one dispatcher
   wins), then transmits;
3. settles from the receipt (``applied``/``noop``/``partial``/``rejected``), or polls a handle
   with bounded retry-after, or on transport failure journals ``uncertain`` and tries one
   receipt lookup. A negative lookup leaves the effect ``uncertain``; it is never retried
   automatically, only by a later attempt carrying explicit recovery authority. That retry
   presents the new attempt as the credential origin (``current_caller_origin``) with an
   **effect-scoped** recovery claim for the exact key and bound digest, while the envelope
   keeps the unchanged ``originating_origin`` and identical native bytes, a new dispatch id
   and a new credential (Checkpoint A decision, SPRINT-V-DESIGN §10.1).

Non-effect handle operations (``report.assess``, ``report.derive``, ``verify.claims``,
``knowledge.read``) are recorded in the durable handle store (release 1.6.0) with the caller,
invocation and request key, polled with bounded retry-after, and every observed status is kept
monotonically. A transport failure on them raises the retryable typed refusal
``CAPABILITY_UNAVAILABLE``; a retry with the same request key is the same request.

``trusted`` dispatches one trusted assessment operation (WI-03: ``report.observe``,
``report.seal``, ``report.decide``, ``report.review``, ``decision.resolve``) under a credential that
carries the host's evaluator grant when a separate judge, auditor or reviewer invocation acts, and
answers the exact result document (re-verified by digest) or the typed KS refusal with its reason.

``reconcile`` is receipt-first recovery under a separate read-only recovery credential.
``cancel`` stops new calls for the invocation, sends an idempotent ``operation.cancel`` for
every open durable handle of the invocation (found after a restart too), stores the first
cancel request id, and reconciles the attempt's open journal rows by receipt lookup.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from mission_control.application.knowledge.access import (
    CredentialMismatch,
    InvocationAccess,
    RecoveryAccess,
    instant,
    verify_credential_claims,
)
from mission_control.application.knowledge.apply_payload import apply_payload
from mission_control.application.knowledge.operations import (
    KnowledgeCall,
    KnowledgeRefused,
    KnowledgeResult,
    LookupResult,
    pending_delivery,
    settlement_from_delivery,
    settlement_from_receipt,
    settlement_without_receipt,
)
from mission_control.application.ports.knowledge import (
    CredentialMinter,
    CredentialRequest,
    ExactContentReader,
    HandleCandidate,
    HandleRecord,
    JournalRecord,
    JournalVersionConflict,
    KnowledgeBindingClient,
    KnowledgeHandleStore,
    KnowledgeJournal,
    KnowledgeProtocolRefusal,
    KnowledgeTransportError,
    MintedCredential,
    PrepareRequest,
    RecordedUseDecision,
    ReportPackage,
    RetainedReadStore,
    Settlement,
    UseDecisionStore,
)
from mission_control.contracts.knowledge_assessment import (
    ASSESSMENT_CONTRACTS,
    EVALUATION_CONTEXT_CONTRACT,
    EVALUATION_CONTEXT_VERSION,
    RESULT_VERSIONS,
    CredentialEvaluation,
)
from mission_control.contracts.knowledge_protocol import (
    PROTOCOL_VERSION,
    READ_INTENT_CONTRACT,
    TERMINAL_STATES,
    EffectBinding,
    EnvelopeTarget,
    Governors,
    KnowledgePlanPreview,
    KnowledgeReadIntentRequest,
    KnowledgeReadIntentResult,
    NativeInput,
    OperationEnvelope,
    OperationHandle,
    OperationName,
    Origin,
    Ref,
    bind_effect,
    bound_effect_digest,
    digest_bytes,
    digest_canonical,
    read_intent_snapshot_digest,
    trusted_operation_id,
)
from mission_control.contracts.knowledge_protocol_results import (
    SETTLED_RECEIPT_OUTCOMES,
    BindingDescriptor,
    CredentialRecovery,
    OperationReceipt,
    OperationStatus,
    ProtocolError,
    ReceiptDelivery,
    ReceiptFound,
    ReceiptNotFound,
)
from mission_control.domain.knowledge.effects import (
    TERMINAL_STATES as JOURNAL_TERMINAL,
)
from mission_control.domain.knowledge.effects import (
    EffectConflict,
    JournalState,
    mint_effect_key,
)
from mission_control.domain.resolution.resolved import KnowledgePortBinding


def _decision_effect_key(
    decision: RecordedUseDecision, access: InvocationAccess, capability_pin: str
) -> str:
    """One canonical key for planning, actual apply, and receipt recovery."""
    return mint_effect_key(
        access.origin,
        capability_pin,
        digest_canonical(
            {
                "useDecisionId": decision.use_decision_id,
                "boundEffectDigest": decision.bound_effect_digest,
            }
        ),
    )


Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]
MIN_POLL_SECONDS = 0.1
MAX_POLL_SECONDS = 300.0
# K01 refusals of a dispatched effect after which the native write may have committed (WI-05,
# OUTPUT-CONTRACTS §5): `UNRESOLVED_EFFECT` (native receipt without protocol receipt) and
# `INTERNAL` (e.g. the protocol receipt write failed after the native commit). Without a
# `details.dispatch` state they leave the effect uncertain for receipt-first recovery; every
# other refusal without one is a definitive rollback.
EFFECT_MAY_HAVE_COMMITTED: frozenset[str] = frozenset({"UNRESOLVED_EFFECT", "INTERNAL"})
# What Knowledge Services (component 2.5.0) says the refused dispatch did natively.
DISPATCH_STATES: frozenset[str] = frozenset(
    {"not_journaled", "journaled_uncommitted", "committed", "unknown"}
)


def dispatch_state(error: ProtocolError) -> str | None:
    """The refusal's ``details.dispatch`` (WI-05), when the binding states one it knows.

    ``journaled_uncommitted`` counts only with ``details.fenced: true``: KS abandoned the
    dispatch under the commit lock, so its native commit can never land later. Unfenced, a
    commit may still be in flight and the state is ``unknown``.
    """

    details = error.details
    state = details.get("dispatch") if isinstance(details, dict) else None
    if not isinstance(state, str) or state not in DISPATCH_STATES:
        return None
    if state == "journaled_uncommitted" and not (
        isinstance(details, dict) and details.get("fenced") is True
    ):
        return "unknown"
    return state


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class TrustedAnswer:
    """One trusted assessment operation's answer: the exact result document, or the typed KS
    refusal (``refusal.details.reason`` names the cause), with the durable handle record."""

    operation: str
    document: dict[str, Any] | None = None
    refusal: ProtocolError | None = None
    status: OperationStatus | None = None
    handle_record: HandleRecord | None = None

    @property
    def reason(self) -> str | None:
        details = None if self.refusal is None else self.refusal.details
        reason = details.get("reason") if isinstance(details, dict) else None
        return reason if isinstance(reason, str) else None

    @property
    def issues(self) -> tuple[str, ...]:
        """W1 D20: KS's validation issues (``details.issues``: ``path: message``), bounded."""

        return refusal_issues(None if self.refusal is None else self.refusal.details)


MAX_ISSUES = 20
MAX_ISSUE_CHARS = 300


def refusal_issues(details: Any) -> tuple[str, ...]:
    """The bounded validation issues a KS refusal carries (``issues`` or ``violations``): at most
    :data:`MAX_ISSUES`, each redacted (the toolset's credential and path patterns) and cut to
    :data:`MAX_ISSUE_CHARS`. KS writes them as ``path: message`` (zod paths and messages)."""

    if not isinstance(details, dict):
        return ()
    raw = details.get("issues") or details.get("violations") or ()
    if not isinstance(raw, list):
        return ()
    from mission_control.application.knowledge.redaction import redacted

    return tuple(redacted(str(item), MAX_ISSUE_CHARS) for item in raw[:MAX_ISSUES])


def _check_read_intent(result: KnowledgeReadIntentResult) -> None:
    """The answer is internally consistent: its snapshot digest is over its operations and
    every body it returned digests to that operation's ``contentDigest``."""

    if read_intent_snapshot_digest(result.atKnowledgeSeq, result.operations) != (
        result.snapshotDigest
    ):
        raise KnowledgeRefused("INVALID_ENVELOPE", "read-intent snapshot digest does not recompute")
    for operation in result.operations:
        returned = operation.rows is not None or operation.value is not None
        if returned and digest_canonical(operation.body) != operation.contentDigest:
            raise KnowledgeRefused(
                "INVALID_ENVELOPE", f"read-intent body {operation.opId} differs from its digest"
            )


def _poll_delay(status: OperationStatus) -> float:
    hint = (status.retryAfterMs or 1000) / 1000
    return min(max(hint, MIN_POLL_SECONDS), MAX_POLL_SECONDS)


def _replayed(operation: str, record: JournalRecord) -> KnowledgeResult:
    """W1 D12: the recorded outcome of an identical, already settled effect (nothing is sent).

    The effect key is over the exact payload, so only identical bytes reach here: a corrected
    payload is a new key and dispatches. A settled refusal replays as the same refusal (its
    journaled code), never as a success without a handle; a success replays idempotently.
    """

    refusal_code = None
    if record.state is JournalState.REJECTED:
        refusal_code = record.refusal_code or "REJECTED"
    return KnowledgeResult(
        operation=operation,
        effect_key=record.effect_key,
        journal=record,
        refusal_code=refusal_code,
        replayed=True,
    )


class KnowledgeGateway:
    """One gateway per application binding; the host refreshes access at every tool call.

    ``knowledge`` is the application's :class:`KnowledgePortBinding` (its Application Profile,
    OC-R4): the binding id every credential names, and the apply contract and payload layout
    `apply_decision` builds the native intent from. No application is named here.
    """

    def __init__(
        self,
        *,
        client: KnowledgeBindingClient,
        journal: KnowledgeJournal,
        handles: KnowledgeHandleStore,
        minter: CredentialMinter,
        content: ExactContentReader | None = None,
        decisions: UseDecisionStore | None = None,
        knowledge: KnowledgePortBinding,
        audience: str,
        actor_ref: str = "mission-control:knowledge-gateway",
        max_polls: int = 10,
        clock: Clock = _utcnow,
        sleep: Sleep = asyncio.sleep,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        if max_polls < 0:
            raise ValueError("max_polls cannot be negative")
        self._client = client
        self._journal = journal
        self._handles = handles
        self._minter = minter
        self._content = content
        self._decisions = decisions
        self._knowledge = knowledge
        self._binding = knowledge.binding_id
        self._audience = audience
        self._actor_ref = actor_ref
        self._max_polls = max_polls
        self._clock = clock
        self._sleep = sleep
        self._new_id = new_id
        self._cancelled: set[str] = set()

    @property
    def binding(self) -> str:
        return self._binding

    @property
    def knowledge(self) -> KnowledgePortBinding:
        return self._knowledge

    @property
    def audience(self) -> str:
        return self._audience

    @property
    def decisions(self) -> UseDecisionStore | None:
        return self._decisions

    # ------------------------------------------------------------ public surface

    async def originating_origin(self, scope: str, effect_key: str) -> Origin | None:
        """The originating origin an earlier dispatch of ``effect_key`` sealed (None: new).

        A host that seals the originating origin inside native bytes (the report producer,
        W1 D1) reuses it, so a retried effect carries the same bytes and the same key."""

        existing = await self._journal.lookup(scope, effect_key)
        return None if existing is None else existing.originating_origin

    async def invoke(self, call: KnowledgeCall, access: InvocationAccess) -> KnowledgeResult:
        if access.invocation_ref in self._cancelled:
            raise KnowledgeRefused("CANCELLED", "the invocation was cancelled; no new calls")
        if call.effectful:
            return await self._effect(call, access)
        if call.handle_operation:
            return await self._handle_operation(call, access)
        if call.operation == "knowledge.describe":
            raise KnowledgeRefused(
                "INVALID_ENVELOPE", "describe is a host preflight, not an agent call"
            )
        raise KnowledgeRefused("INVALID_ENVELOPE", f"{call.operation} is a host operation")

    async def describe(self, origin: Origin) -> BindingDescriptor:
        """The binding descriptor under a service (standalone) credential: startup preflight."""

        credential = self._mint(
            CredentialRequest(
                audience=self._audience,
                binding=self._binding,
                origin=origin,
                operations=("knowledge.describe",),
                dispatch_id=self._new_id(),
            )
        )
        try:
            return await self._client.describe(credential.token)
        except KnowledgeProtocolRefusal as refusal:
            raise KnowledgeRefused(refusal.error.code, refusal.error.message) from None
        except KnowledgeTransportError as error:
            raise KnowledgeRefused("CAPABILITY_UNAVAILABLE", str(error)) from None

    async def poll(self, record: HandleRecord, caller: Origin, *, scope: str) -> HandleRecord:
        """Poll one durable handle until terminal or the poll bound; returns the stored view."""

        status = await self._poll(record.handle, caller, invocation_ref=record.invocation_ref)
        if status is None:
            return record
        return await self._handles.observe(scope, self._binding, status, at=self._clock())

    async def trusted(
        self,
        operation: OperationName,
        request: BaseModel,
        access: InvocationAccess,
        *,
        evaluation: CredentialEvaluation | None,
        request_key: str,
        governors: Governors,
        capability_pin: str,
        subject_ref: str | None = None,
    ) -> TrustedAnswer:
        """Dispatch one trusted assessment operation and answer its exact result document.

        The caller is ``access``'s own invocation; ``evaluation`` is the host's attestation of a
        separate evaluator invocation (never set for the producer). A transport failure raises
        the retryable ``CAPABILITY_UNAVAILABLE`` (the evaluator or KS is unavailable); a KS
        refusal is answered, typed, so the bridge can hold, wait or refuse.
        """

        contract = (
            EVALUATION_CONTEXT_CONTRACT
            if operation == "knowledge.read"
            else ASSESSMENT_CONTRACTS.get(operation)
        )
        if contract is None:
            raise KnowledgeRefused(
                "INVALID_ENVELOPE", f"{operation} is not an assessment operation"
            )
        if access.invocation_ref in self._cancelled:
            raise KnowledgeRefused("CANCELLED", "the invocation was cancelled; no new calls")
        caller = access.wire_origin()
        dispatch_id = self._new_id()
        credential = self._mint(
            CredentialRequest(
                audience=self._audience,
                binding=self._binding,
                origin=caller,
                operations=(operation,),
                dispatch_id=dispatch_id,
                evaluation=evaluation,
            )
        )
        call = KnowledgeCall(
            operation=operation,
            capability_pin=capability_pin,
            native_contract=contract,
            payload=request.model_dump(mode="json", by_alias=True),
            governors=governors,
            request_key=request_key,
            subject_ref=subject_ref,
        )
        envelope = self._envelope(call, caller, dispatch_id, request_id=request_key)
        try:
            answer = await self._client.invoke(envelope, credential.token)
        except KnowledgeProtocolRefusal as refusal:
            return TrustedAnswer(operation=operation, refusal=refusal.error)
        except KnowledgeTransportError as error:
            raise KnowledgeRefused(
                "CAPABILITY_UNAVAILABLE", f"binding unreachable: {error}"
            ) from None
        if isinstance(answer, OperationReceipt | KnowledgePlanPreview | KnowledgeReadIntentResult):
            raise KnowledgeRefused("INVALID_ENVELOPE", f"{operation} answered no handle")
        record = await self._handles.record(
            HandleCandidate(
                scope=access.scope,
                binding_id=self._binding,
                operation=operation,
                request_id=request_key,
                handle=answer,
                coordinates=access.coordinates(),
                invocation_ref=access.invocation_ref,
                caller_origin=caller,
                actor_ref=self._actor_ref,
                at=self._clock(),
                subject_ref=subject_ref,
            )
        )
        status = await self._poll(answer, caller, invocation_ref=access.invocation_ref)
        if status is not None:
            record = await self._handles.observe(
                access.scope, self._binding, status, at=self._clock()
            )
        if status is None or status.state != "succeeded" or status.resultRef is None:
            return TrustedAnswer(
                operation=operation,
                refusal=None if status is None else status.error,
                status=status,
                handle_record=record,
            )
        document = await self._result_document(status.resultRef, caller, operation)
        return TrustedAnswer(
            operation=operation, document=document, status=status, handle_record=record
        )

    async def plan_preview(
        self,
        payload: Mapping[str, Any],
        access: InvocationAccess,
        *,
        capability_pin: str,
        governors: Governors,
        request_key: str,
    ) -> KnowledgePlanPreview:
        """The read-only ``knowledge.plan_preview`` of a native apply payload (W1 native write).

        The envelope is the one ``knowledge.apply`` sends (the binding's apply contract, the
        inline payload) with ``effect: null``, under a NON-effect credential granting only
        ``knowledge.plan_preview``. Every call mints a fresh credential (its own ``jti`` and
        dispatch id), so a replay after a crash consumes a new nonce. Nothing is recorded: KS
        binds, journals and admits nothing, and the answer comes in the same call.
        """

        if access.invocation_ref in self._cancelled:
            raise KnowledgeRefused("CANCELLED", "the invocation was cancelled; no new calls")
        port = self._knowledge
        caller = access.wire_origin()
        dispatch_id = self._new_id()
        credential = self._mint(
            CredentialRequest(
                audience=self._audience,
                binding=self._binding,
                origin=caller,
                operations=("knowledge.plan_preview",),
                dispatch_id=dispatch_id,
            )
        )
        call = KnowledgeCall(
            operation="knowledge.plan_preview",
            capability_pin=capability_pin,
            native_contract={
                "name": port.apply_contract_name,
                "version": port.apply_contract_version,
            },
            payload=dict(payload),
            governors=governors,
            request_key=request_key,
        )
        envelope = self._envelope(call, caller, dispatch_id, request_id=request_key)
        try:
            answer = await self._client.invoke(envelope, credential.token)
        except KnowledgeProtocolRefusal as refusal:
            raise KnowledgeRefused(refusal.error.code, refusal.error.message) from None
        except KnowledgeTransportError as error:
            raise KnowledgeRefused(
                "CAPABILITY_UNAVAILABLE", f"binding unreachable: {error}"
            ) from None
        if not isinstance(answer, KnowledgePlanPreview):
            raise KnowledgeRefused(
                "INVALID_ENVELOPE", "knowledge.plan_preview answered no plan preview"
            )
        return answer

    async def read_intent(
        self,
        request: KnowledgeReadIntentRequest,
        access: InvocationAccess,
        *,
        observations: RetainedReadStore,
        capability_pin: str,
        governors: Governors,
        request_key: str,
    ) -> KnowledgeReadIntentResult:
        """One recorded ``knowledge.read_intent`` (OVE-204 slice 4), answered in the same call.

        The envelope carries the request inline under ``knowledge-read-intent/v1`` with
        ``effect: null`` and no declared use, under a fresh NON-effect credential granting only
        ``knowledge.read_intent``. KS records the read as one operation row and answers the
        same operation for a replay of ``request_key``. The answer is checked (snapshot digest
        and every returned body against its content digest) and every result operation is then
        recorded as one ``retained_read_observation`` before the result is returned: a read
        that could not be recorded is refused (``CAPABILITY_UNAVAILABLE``, retry the same call).
        """

        from mission_control.application.knowledge.read_intent import read_observations

        if access.invocation_ref in self._cancelled:
            raise KnowledgeRefused("CANCELLED", "the invocation was cancelled; no new calls")
        caller = access.wire_origin()
        dispatch_id = self._new_id()
        credential = self._mint(
            CredentialRequest(
                audience=self._audience,
                binding=self._binding,
                origin=caller,
                operations=("knowledge.read_intent",),
                dispatch_id=dispatch_id,
            )
        )
        call = KnowledgeCall(
            operation="knowledge.read_intent",
            capability_pin=capability_pin,
            native_contract=dict(READ_INTENT_CONTRACT),
            payload=request.payload(),
            governors=governors,
            request_key=request_key,
        )
        envelope = self._envelope(call, caller, dispatch_id, request_id=request_key)
        try:
            answer = await self._client.invoke(envelope, credential.token)
        except KnowledgeProtocolRefusal as refusal:
            raise KnowledgeRefused(refusal.error.code, refusal.error.message) from None
        except KnowledgeTransportError as error:
            raise KnowledgeRefused(
                "CAPABILITY_UNAVAILABLE", f"binding unreachable: {error}"
            ) from None
        if not isinstance(answer, KnowledgeReadIntentResult):
            raise KnowledgeRefused(
                "INVALID_ENVELOPE", "knowledge.read_intent answered no read-intent result"
            )
        _check_read_intent(answer)
        rows = read_observations(
            request,
            answer,
            binding=self._binding,
            run_id=access.origin.run_id,
            invocation_ref=access.invocation_ref,
        )
        try:
            await observations.record(
                access.scope, rows, actor_ref=self._actor_ref, at=self._clock()
            )
        except Exception as error:
            raise KnowledgeRefused(
                "CAPABILITY_UNAVAILABLE",
                f"the read was served but not recorded ({type(error).__name__}); retry the same "
                "call",
            ) from None
        return answer

    async def recover_trusted(
        self,
        operation: OperationName,
        access: InvocationAccess,
        *,
        request_key: str,
        subject_ref: str | None = None,
    ) -> TrustedAnswer | None:
        """Read (``operation.get``) and record the trusted operation KS holds for exactly this
        request id, without sending the request again (W1: KS accepted it, the host lost the
        handle). ``None`` when KS holds no such operation (the dispatch never landed)."""

        caller = access.wire_origin()
        handle = OperationHandle(
            protocolVersion="ks.knowledge_operation.v2",
            tenant=caller.tenantId,
            application=caller.applicationId,
            binding=self._binding,
            operationId=trusted_operation_id(caller.tenantId, operation, request_key),
        )
        credential = self._fresh(
            CredentialRequest(
                audience=self._audience,
                binding=self._binding,
                origin=caller,
                operations=("operation.get",),
                dispatch_id=self._new_id(),
            )
        )
        try:
            status: OperationStatus | None = await self._client.operation_get(handle, credential)
        except KnowledgeProtocolRefusal as refusal:
            if refusal.error.code == "NOT_FOUND":
                return None  # KS holds no operation for this request id
            raise KnowledgeRefused(refusal.error.code, refusal.error.message) from None
        except KnowledgeTransportError as error:
            # Unknown whether KS holds it: never treated as "not held" (that would re-run).
            raise KnowledgeRefused(
                "CAPABILITY_UNAVAILABLE", f"binding unreachable: {error}"
            ) from None
        assert status is not None
        if status.handle.operationId != handle.operationId:
            # The derivation mirrors KS (golden vectors: ks-operation-id-parity.json); another id
            # is a protocol fault, never adopted as this request's operation.
            raise KnowledgeRefused(
                "INVALID_ENVELOPE",
                f"operation.get answered {status.handle.operationId} for {handle.operationId}",
            )
        if status.state not in TERMINAL_STATES:
            status = (
                await self._poll(handle, caller, invocation_ref=access.invocation_ref) or status
            )
        record = await self._handles.record(
            HandleCandidate(
                scope=access.scope,
                binding_id=self._binding,
                operation=operation,
                request_id=request_key,
                handle=status.handle,
                coordinates=access.coordinates(),
                invocation_ref=access.invocation_ref,
                caller_origin=caller,
                actor_ref=self._actor_ref,
                at=self._clock(),
                subject_ref=subject_ref,
            )
        )
        record = await self._handles.observe(access.scope, self._binding, status, at=self._clock())
        return TrustedAnswer(
            operation=operation,
            refusal=None if status.state == "succeeded" else status.error,
            status=status,
            handle_record=record,
        )

    async def _result_document(
        self, result_ref: Ref, caller: Origin, operation: str
    ) -> dict[str, Any]:
        """The exact result document named by ``result_ref``, re-verified by digest."""

        expected = (
            EVALUATION_CONTEXT_VERSION
            if operation == "knowledge.read"
            else RESULT_VERSIONS.get(operation)
        )
        if result_ref.version != expected:
            raise KnowledgeRefused(
                "SCHEMA_UNSUPPORTED", f"{operation} answered a {result_ref.version} document"
            )
        artifact = getattr(self._client, "artifact", None)
        if artifact is None:
            raise KnowledgeRefused("CAPABILITY_UNAVAILABLE", "the binding client reads no bytes")
        credential = self._mint(
            CredentialRequest(
                audience=self._audience,
                binding=self._binding,
                origin=caller,
                operations=("knowledge.read",),
                dispatch_id=self._new_id(),
            )
        )
        try:
            data = await artifact(result_ref.id, result_ref.digest, credential.token)
        except KnowledgeProtocolRefusal as refusal:
            raise KnowledgeRefused(refusal.error.code, refusal.error.message) from None
        except KnowledgeTransportError as error:
            raise KnowledgeRefused("CAPABILITY_UNAVAILABLE", str(error)) from None
        if digest_bytes(data) != result_ref.digest:
            raise KnowledgeRefused(
                "EXACT_REVISION_UNAVAILABLE", "the result bytes differ from their digest"
            )
        document = json.loads(data.decode("utf-8"))
        if not isinstance(document, dict):
            raise KnowledgeRefused("SCHEMA_UNSUPPORTED", "the result document is not an object")
        return document

    async def read_content(self, result_ref: Ref, access: InvocationAccess) -> ReportPackage:
        """The frozen package of exactly ``result_ref`` under a fresh ``knowledge.read`` grant."""

        if self._content is None:
            raise KnowledgeRefused("CAPABILITY_UNAVAILABLE", "no exact content reader is bound")
        if access.invocation_ref in self._cancelled:
            raise KnowledgeRefused("CANCELLED", "the invocation was cancelled; no new calls")

        def credential() -> str:
            return self._mint(
                CredentialRequest(
                    audience=self._audience,
                    binding=self._binding,
                    origin=access.wire_origin(),
                    operations=("knowledge.read",),
                    dispatch_id=self._new_id(),
                )
            ).token

        try:
            return await self._content.fetch(result_ref, credential)
        except KnowledgeProtocolRefusal as refusal:
            raise KnowledgeRefused(refusal.error.code, refusal.error.message) from None
        except KnowledgeTransportError as error:
            raise KnowledgeRefused("CAPABILITY_UNAVAILABLE", str(error)) from None

    async def open_effects_for_operation(
        self, scope: str, *, run_id: str, operation_ref: str
    ) -> list[JournalRecord]:
        """Unsettled rows of every attempt of one operation (host recovery grants)."""

        return await self._journal.open_for_operation(
            scope, run_id=run_id, operation_ref=operation_ref
        )

    async def open_effects(
        self, scope: str, *, run_id: str, operation_ref: str, operation_attempt: int
    ) -> list[JournalRecord]:
        """The attempt's unsettled journal rows (prepared, dispatched, uncertain)."""

        return await self._journal.open_for_attempt(
            scope, run_id=run_id, operation_ref=operation_ref, operation_attempt=operation_attempt
        )

    async def apply_decision(
        self,
        handle: str,
        access: InvocationAccess,
        *,
        capability_pin: str,
        governors: Governors,
    ) -> KnowledgeResult:
        """`knowledge.apply` of one host-recorded use decision (integrator decision 2026-10-25).

        The agent names only the decision handle. The host resolves the recorded decision
        (id, plan-level bound digest, normalized-values digest, processed epoch), takes the
        native contract and payload layout from the application's knowledge port and composes
        the exact use (`apply_payload`); the agent never types digests.
        """

        return await self._apply_decision(
            handle, access, capability_pin=capability_pin, governors=governors
        )

    async def apply_native_decision(
        self,
        handle: str,
        access: InvocationAccess,
        *,
        admission: Ref,
        capability_pin: str,
        governors: Governors,
    ) -> KnowledgeResult:
        """Trusted service-only successor authority; never an agent argument.

        The service verified the fresh exact root chain and report/use/run context. The
        native executor still compares this admission's bound digest and normalized values
        against the immutable original plan. A journaled root is never re-authorized.
        """
        return await self._apply_decision(
            handle,
            access,
            capability_pin=capability_pin,
            governors=governors,
            admission=admission,
        )

    async def _apply_decision(
        self,
        handle: str,
        access: InvocationAccess,
        *,
        capability_pin: str,
        governors: Governors,
        admission: Ref | None = None,
    ) -> KnowledgeResult:
        decision = await self._recorded_apply_decision(handle, access)
        if admission is not None:
            self._check_apply_decision(decision, access, native=True)
            if (
                admission.kind != "use_decision"
                or admission.binding != decision.binding_id
                or admission.tenant != decision.tenant_id
            ):
                raise KnowledgeRefused("SCOPE_DENIED", "native admission differs in scope")
        port = self._knowledge
        contract = {"name": port.apply_contract_name, "version": port.apply_contract_version}
        effect_key = _decision_effect_key(decision, access, capability_pin)
        existing = await self._journal.lookup(access.scope, effect_key)
        if admission is not None and existing is not None:
            return _replayed("knowledge.apply", existing)
        originating = existing.originating_origin if existing is not None else access.wire_origin()
        payload_decision = (
            decision if admission is None else replace(decision, use_decision_id=admission.id)
        )
        built = apply_payload(
            port, payload_decision, effect_key=effect_key, originating=originating
        )
        call = KnowledgeCall(
            operation="knowledge.apply",
            capability_pin=capability_pin,
            native_contract=contract,
            payload=built.payload,
            governors=governors,
            effect_key=effect_key,
            plan=built.plan,
            bound_effect_digest=built.bound_effect_digest,
            subject_ref=handle,
            use=decision.use,
            audience=decision.audience,
        )
        if admission is not None:
            if access.invocation_ref in self._cancelled:
                raise KnowledgeRefused("CANCELLED", "the invocation was cancelled; no new calls")
            return await self._effect(call, access, fresh_admission=True)
        return await self.invoke(call, access)

    def _check_apply_decision(
        self, decision: RecordedUseDecision, access: InvocationAccess, *, native: bool = False
    ) -> None:
        if decision.binding_id != self._binding or decision.tenant_id != access.origin.tenant_id:
            raise KnowledgeRefused("SCOPE_DENIED", "the decision names another binding or tenant")
        if (
            native or decision.invocation_ref is not None
        ) and decision.invocation_ref != access.invocation_ref:
            raise KnowledgeRefused(
                "ORIGIN_MISMATCH", "this plan decision binds another invocation's origin"
            )

    async def _recorded_apply_decision(
        self, handle: str, access: InvocationAccess
    ) -> RecordedUseDecision:
        decision = (
            None if self._decisions is None else await self._decisions.get(access.scope, handle)
        )
        if decision is None:
            raise KnowledgeRefused("NOT_FOUND", f"no recorded use decision {handle!r}")
        self._check_apply_decision(decision, access)
        return decision

    async def decision_effect_key(
        self, handle: str, access: InvocationAccess, *, capability_pin: str
    ) -> str:
        """Read the stable identity of this invocation's recorded native-plan decision.

        This prepares no journal row, mints no credential, and grants no apply authority.
        A producer may explicitly submit this pending identity; fulfillment still requires
        the journal's same-run APPLIED receipt after ordinary native admission.
        """
        decision = await self._recorded_apply_decision(handle, access)
        self._check_apply_decision(decision, access, native=True)
        return _decision_effect_key(decision, access, capability_pin)

    async def existing_decision_effect(
        self, handle: str, access: InvocationAccess, *, capability_pin: str
    ) -> KnowledgeResult | None:
        decision = (
            None if self._decisions is None else await self._decisions.get(access.scope, handle)
        )
        if decision is None:
            return None
        self._check_apply_decision(decision, access, native=True)
        key = _decision_effect_key(decision, access, capability_pin)
        row = await self._journal.lookup(access.scope, key)
        if row is None:
            return None
        return KnowledgeResult(
            operation="knowledge.apply",
            effect_key=key,
            journal=row,
            replayed=True,
            refusal_code=row.refusal_code,
        )

    async def receipt(self, effect_key: str, access: RecoveryAccess) -> LookupResult | None:
        """Receipt-first audit lookup under read-only recovery authority; settles nothing that
        is already terminal (an uncertain effect settles as in ``reconcile``)."""

        record = await self._journal.lookup(access.scope, effect_key)
        if record is None:
            raise KnowledgeRefused("NOT_FOUND", "no journalled effect", effect_key=effect_key)
        if not access.in_scope_of(record.originating_origin):
            raise KnowledgeRefused("SCOPE_DENIED", "recovery scope differs", effect_key=effect_key)
        _, lookup = await self._lookup_and_settle(
            access.scope,
            record,
            access.wire_origin(),
            recovery=access.claim(record.effect_key, record.bound_effect_digest),
        )
        return lookup

    async def stored_handle(self, scope: str, operation_id: str) -> HandleRecord | None:
        """The durable handle of a remote operation of this binding (survives restarts)."""

        return await self._handles.get(scope, self._binding, operation_id)

    async def reconcile(self, effect_key: str, access: RecoveryAccess) -> KnowledgeResult:
        """Receipt-first recovery under a read-only recovery credential."""

        record = await self._journal.lookup(access.scope, effect_key)
        if record is None:
            raise KnowledgeRefused("NOT_FOUND", "no journalled effect", effect_key=effect_key)
        if not access.in_scope_of(record.originating_origin):
            raise KnowledgeRefused("SCOPE_DENIED", "recovery scope differs", effect_key=effect_key)
        if record.state not in {JournalState.DISPATCHED, JournalState.UNCERTAIN}:
            return KnowledgeResult(operation="receipt.get", effect_key=effect_key, journal=record)
        record, lookup = await self._lookup_and_settle(
            access.scope,
            record,
            access.wire_origin(),
            recovery=access.claim(record.effect_key, record.bound_effect_digest),
        )
        return KnowledgeResult(
            operation="receipt.get", effect_key=effect_key, journal=record, lookup=lookup
        )

    async def cancel(self, access: InvocationAccess, cancel_request_id: str) -> list[JournalRecord]:
        """Stop new calls for this invocation, cancel its open handles, reconcile its effects."""

        self._cancelled.add(access.invocation_ref)
        caller = access.wire_origin()
        cancelled: dict[str, OperationStatus | None] = {}
        for handle in await self._handles.open_for_invocation(access.scope, access.invocation_ref):
            cancelled[handle.handle.operationId] = await self._cancel_handle(
                access.scope, handle, caller, cancel_request_id
            )
        settled: list[JournalRecord] = []
        coordinates = access.coordinates()
        open_rows = await self._journal.open_for_attempt(
            access.scope,
            run_id=coordinates.run_id,
            operation_ref=coordinates.operation_ref,
            operation_attempt=coordinates.operation_attempt,
        )
        for record in sorted(open_rows, key=lambda item: item.effect_key):
            if record.state is JournalState.PREPARED:
                record = await self._settle(
                    access.scope,
                    record,
                    Settlement(state=JournalState.REJECTED, refusal_code="CANCELLED"),
                )
                settled.append(record)
                continue
            status = None
            if record.operation_id in cancelled:
                status = cancelled[record.operation_id]
            elif record.operation_id is not None:
                status = await self._send_cancel(self._handle_of(record), caller, cancel_request_id)
            record, _lookup = await self._lookup_and_settle(access.scope, record, caller)
            if record.state not in JOURNAL_TERMINAL:
                record = await self._settle_or_uncertain(access.scope, record, status)
            settled.append(record)
        return settled

    async def cancel_run(
        self, request_scope: str, run_id: str, *, cancel_request_id: str
    ) -> list[HandleRecord]:
        """Run-level stop: cancel every open handle of the run, including assessments still
        open after their node completed (an accepted cancel, after its Stop Fence).

        Each cancel is sent under a fresh credential for the handle's own recorded caller
        (re-authenticated now), idempotent by the first stored cancel request id; new tool
        calls of the fenced run are already denied by the Kernel Hook fence gate.
        """

        cancelled: list[HandleRecord] = []
        for record in await self._handles.open_for_run(request_scope, run_id):
            caller = record.caller_origin.model_copy(
                update={
                    "invocationId": f"stop-{self._new_id()}",
                    "authenticatedAt": instant(self._clock()),
                }
            )
            await self._cancel_handle(request_scope, record, caller, cancel_request_id)
            stored = await self._handles.get(
                request_scope, record.binding_id, record.handle.operationId
            )
            cancelled.append(stored or record)
        return cancelled

    # ------------------------------------------------------------ non-effect handles

    async def _handle_operation(
        self, call: KnowledgeCall, access: InvocationAccess
    ) -> KnowledgeResult:
        caller = access.wire_origin()
        dispatch_id = self._new_id()
        credential = self._mint(
            CredentialRequest(
                audience=self._audience,
                binding=self._binding,
                origin=caller,
                operations=(call.operation,),
                dispatch_id=dispatch_id,
            )
        )
        request_id = call.request_key or self._new_id()
        envelope = self._envelope(call, caller, dispatch_id, request_id=request_id)
        try:
            answer = await self._client.invoke(envelope, credential.token)
        except KnowledgeProtocolRefusal as refusal:
            return KnowledgeResult(
                operation=call.operation, refusal_code=refusal.error.code, refusal=refusal.error
            )
        except KnowledgeTransportError as error:
            raise KnowledgeRefused(
                "CAPABILITY_UNAVAILABLE", f"binding unreachable: {error}"
            ) from None
        if isinstance(answer, OperationReceipt | KnowledgePlanPreview | KnowledgeReadIntentResult):
            raise KnowledgeRefused(
                "INVALID_ENVELOPE", f"{call.operation} answered no handle for no effect"
            )
        record = await self._handles.record(
            HandleCandidate(
                scope=access.scope,
                binding_id=self._binding,
                operation=call.operation,
                request_id=request_id,
                handle=answer,
                coordinates=access.coordinates(),
                invocation_ref=access.invocation_ref,
                caller_origin=caller,
                actor_ref=self._actor_ref,
                at=self._clock(),
                subject_ref=call.subject_ref,
            )
        )
        status = await self._poll(answer, caller, invocation_ref=access.invocation_ref)
        if status is not None:
            record = await self._handles.observe(
                access.scope, self._binding, status, at=self._clock()
            )
        return KnowledgeResult(
            operation=call.operation,
            handle=answer,
            handle_record=record,
            status=status,
            refusal_code=None if status is None or status.error is None else status.error.code,
            refusal=None if status is None else status.error,
        )

    async def _cancel_handle(
        self, scope: str, record: HandleRecord, caller: Origin, cancel_request_id: str
    ) -> OperationStatus | None:
        record = await self._handles.request_cancel(
            scope,
            record.binding_id,
            record.handle.operationId,
            cancel_request_id,
            at=self._clock(),
        )
        # The first stored request id is the idempotency key, also after a restart.
        status = await self._send_cancel(
            record.handle, caller, record.cancel_request_id or cancel_request_id
        )
        if status is not None:
            await self._handles.observe(scope, record.binding_id, status, at=self._clock())
        return status

    # ------------------------------------------------------------ effects

    async def _effect(
        self, call: KnowledgeCall, access: InvocationAccess, *, fresh_admission: bool = False
    ) -> KnowledgeResult:
        native = call.native_bytes()
        caller = access.wire_origin()
        scope = access.scope
        effect_key = call.effect_key or mint_effect_key(
            access.origin, call.capability_pin, digest_bytes(native)
        )
        existing = await self._journal.lookup(scope, effect_key)
        if fresh_admission and existing is not None:
            return _replayed(call.operation, existing)
        originating = existing.originating_origin if existing is not None else caller
        binding = bind_effect(effect_key, native, originating)
        plan = call.plan_bytes()
        if plan is not None:
            # Apply: bind the plan-level bytes the use decision binds (K01 round 2).
            binding = binding.model_copy(
                update={"boundEffectDigest": bound_effect_digest(plan, originating)}
            )
        elif call.bound_effect_digest is not None:
            binding = binding.model_copy(update={"boundEffectDigest": call.bound_effect_digest})
        if existing is not None and existing.bound_effect_digest != binding.boundEffectDigest:
            raise KnowledgeRefused(
                "EFFECT_CONFLICT", "same effect key, different bytes", effect_key=effect_key
            )
        if existing is not None and existing.state in JOURNAL_TERMINAL:
            # Settled already: the same bytes return the recorded outcome, nothing is sent. W1
            # D12: a recorded refusal replays as the same refusal, never as a success.
            return _replayed(call.operation, existing)
        recovery = self._recovery_for(access, originating, caller, binding)
        try:
            record = await self._journal.prepare(
                PrepareRequest(
                    scope=scope,
                    effect_key=effect_key,
                    semantic_payload_digest=binding.semanticPayloadDigest,
                    bound_effect_digest=binding.boundEffectDigest,
                    originating_origin=originating,
                    current_caller_origin=caller,
                    coordinates=access.coordinates(),
                    capability_pin=call.capability_pin,
                    binding_id=self._binding,
                    actor_ref=self._actor_ref,
                )
            )
        except EffectConflict:
            raise KnowledgeRefused(
                "EFFECT_CONFLICT", "same effect key, different bound effect", effect_key=effect_key
            ) from None

        result = KnowledgeResult(operation=call.operation, effect_key=effect_key, journal=record)
        # A competing prepare may have frozen an earlier admission after our lookups.
        # Never dispatch revised authority under that row's immutable semantic digest.
        if fresh_admission and record.semantic_payload_digest != binding.semanticPayloadDigest:
            return _replayed(call.operation, record)
        if record.state in JOURNAL_TERMINAL:
            return _replayed(call.operation, record)  # settled already (idempotent)
        if record.state is JournalState.DISPATCHED:
            return result  # in flight under another dispatcher
        if record.state is JournalState.UNCERTAIN:
            record, lookup = await self._lookup_and_settle(scope, record, caller, recovery=recovery)
            pending = pending_delivery(None, lookup)
            if record.state is not JournalState.UNCERTAIN or recovery is None or pending:
                # Settled, not recoverable, or admitted and still queued for delivery: never
                # redispatch a `pending_dispatch` effect; it settles on a later receipt lookup.
                return KnowledgeResult(
                    operation=call.operation,
                    effect_key=effect_key,
                    journal=record,
                    lookup=lookup,
                    receipt=lookup.receipt if isinstance(lookup, ReceiptFound) else None,
                    refusal_code=None
                    if record.state is not JournalState.UNCERTAIN or pending
                    else "UNRESOLVED_EFFECT",
                )
        return await self._dispatch(call, access, record, binding, caller, recovery)

    async def _refused_after_dispatch(
        self,
        call: KnowledgeCall,
        scope: str,
        record: JournalRecord,
        caller: Origin,
        recovery: CredentialRecovery | None,
        error: ProtocolError,
    ) -> KnowledgeResult:
        """WI-05: settle a refused dispatch rejected only when nothing of it can have committed.

        ``details.dispatch`` (KS 2.5.0) says what the refused dispatch did natively. Only the first
        dispatch of an effect (no recovery grant: no earlier dispatch can be in flight or
        committed) is settled rejected: at once for ``not_journaled``, and for a fenced
        ``journaled_uncommitted`` (KS abandoned it under the commit lock, so no late commit can
        land) only once ``receipt.get`` proves no commit exists. Everything
        else (``committed``, ``unknown``, a retry's refusal, or a binding without the field that
        answers ``EFFECT_MAY_HAVE_COMMITTED``) stays uncertain and settles receipt-first while the
        WI-04 settlement waits on it.
        """

        code = error.code
        state = dispatch_state(error)
        first = recovery is None
        reject = Settlement(state=JournalState.REJECTED, refusal_code=code)
        if first and state == "not_journaled":
            record = await self._settle(scope, record, reject)
            return self._finish(call.operation, record, refusal_code=code, refusal=error)
        if first and state == "journaled_uncommitted":
            record, lookup = await self._lookup_and_settle(scope, record, caller, recovery=recovery)
            if record.state is JournalState.DISPATCHED and isinstance(lookup, ReceiptNotFound):
                record = await self._settle(scope, record, reject)
                return self._finish(
                    call.operation, record, lookup=lookup, refusal_code=code, refusal=error
                )
            if record.state is JournalState.DISPATCHED:
                record = await self._mark_uncertain(scope, record)
            return self._finish(call.operation, record, lookup=lookup)
        if state is None and code not in EFFECT_MAY_HAVE_COMMITTED:
            record = await self._settle(scope, record, reject)
            return self._finish(call.operation, record, refusal_code=code, refusal=error)
        record = await self._mark_uncertain(scope, record)
        record, lookup = await self._lookup_and_settle(scope, record, caller, recovery=recovery)
        return self._finish(call.operation, record, lookup=lookup)

    def _recovery_for(
        self,
        access: InvocationAccess,
        originating: Origin,
        caller: Origin,
        binding: EffectBinding,
    ) -> CredentialRecovery | None:
        """``None`` for the originator; an effect-scoped claim for an authorized new attempt."""

        if originating.identity() == caller.identity():
            return None
        grant = access.grant_for(binding.effectKey, binding.boundEffectDigest)
        if grant is None:
            raise KnowledgeRefused(
                "ORIGIN_MISMATCH",
                "caller is not the originating invocation and holds no recovery authority",
                effect_key=binding.effectKey,
            )
        return grant.claim()

    async def _dispatch(
        self,
        call: KnowledgeCall,
        access: InvocationAccess,
        record: JournalRecord,
        binding: EffectBinding,
        caller: Origin,
        recovery: CredentialRecovery | None,
    ) -> KnowledgeResult:
        scope = access.scope
        effect_key = binding.effectKey
        dispatch_id = self._new_id()
        try:
            credential = self._mint(
                CredentialRequest(
                    audience=self._audience,
                    binding=self._binding,
                    origin=caller,
                    operations=(call.operation,),
                    dispatch_id=dispatch_id,
                    effect_key=effect_key,
                    bound_effect_digest=binding.boundEffectDigest,
                    recovery=recovery,
                )
            )
        except KnowledgeRefused:
            if record.state is JournalState.PREPARED:
                await self._settle(
                    scope,
                    record,
                    Settlement(state=JournalState.REJECTED, refusal_code="SCOPE_DENIED"),
                )
            raise
        envelope = self._envelope(
            call, caller, dispatch_id, request_id=record.knowledge_operation_id, effect=binding
        )
        try:
            record = await self._journal.dispatch(
                scope,
                effect_key,
                expected_version=record.version,
                dispatch_id=dispatch_id,
                envelope_digest=envelope.digest(),
                protocol_version=PROTOCOL_VERSION,
                caller=caller,
                at=self._clock(),
                # The host grant a later attempt re-dispatches under, recorded with the dispatch.
                recovery_authority_ref=None
                if recovery is None or recovery.scope != "effect"
                else recovery.authorityRef,
            )
        except JournalVersionConflict:
            current = await self._journal.lookup(scope, effect_key)
            if current is not None and current.state in JOURNAL_TERMINAL:
                return _replayed(call.operation, current)
            return KnowledgeResult(operation=call.operation, effect_key=effect_key, journal=current)

        try:
            answer = await self._client.invoke(envelope, credential.token)
        except KnowledgeTransportError:
            record = await self._mark_uncertain(scope, record)
            record, lookup = await self._lookup_and_settle(scope, record, caller, recovery=recovery)
            return self._finish(call.operation, record, lookup=lookup)
        except KnowledgeProtocolRefusal as refusal:
            return await self._refused_after_dispatch(
                call, scope, record, caller, recovery, refusal.error
            )

        if isinstance(answer, OperationReceipt):
            record = await self._accept_receipt(scope, record, answer, reconciled=False)
            return self._finish(call.operation, record, receipt=answer)
        if isinstance(answer, KnowledgePlanPreview | KnowledgeReadIntentResult):
            raise KnowledgeRefused(
                "INVALID_ENVELOPE", f"{call.operation} answered a result document"
            )

        record = await self._journal.record_handle(
            scope,
            effect_key,
            expected_version=record.version,
            operation_id=answer.operationId,
            at=self._clock(),
        )
        await self._handles.record(
            HandleCandidate(
                scope=scope,
                binding_id=self._binding,
                operation=call.operation,
                request_id=record.knowledge_operation_id,
                handle=answer,
                coordinates=access.coordinates(),
                invocation_ref=access.invocation_ref,
                caller_origin=caller,
                actor_ref=self._actor_ref,
                at=self._clock(),
                effect_key=effect_key,
            )
        )
        status = await self._poll(answer, caller, invocation_ref=access.invocation_ref)
        if status is not None:
            await self._handles.observe(scope, self._binding, status, at=self._clock())
        if status is None or status.state not in TERMINAL_STATES:
            return KnowledgeResult(
                operation=call.operation,
                effect_key=effect_key,
                journal=record,
                handle=answer,
                status=status,
            )
        record, lookup = await self._lookup_and_settle(scope, record, caller, recovery=recovery)
        if record.state not in JOURNAL_TERMINAL:
            record = await self._settle_or_uncertain(scope, record, status)
        return self._finish(call.operation, record, lookup=lookup, status=status, handle=answer)

    async def _poll(
        self, handle: OperationHandle, caller: Origin, *, invocation_ref: str
    ) -> OperationStatus | None:
        status: OperationStatus | None = None
        for index in range(self._max_polls):
            if invocation_ref in self._cancelled:
                break
            credential = self._fresh(
                CredentialRequest(
                    audience=self._audience,
                    binding=self._binding,
                    origin=caller,
                    operations=("operation.get",),
                    dispatch_id=self._new_id(),
                )
            )
            try:
                status = await self._client.operation_get(handle, credential)
            except (KnowledgeTransportError, KnowledgeProtocolRefusal):
                break
            if status.state in TERMINAL_STATES or index == self._max_polls - 1:
                break
            await self._sleep(_poll_delay(status))
        return status

    async def _send_cancel(
        self, handle: OperationHandle, caller: Origin, cancel_request_id: str
    ) -> OperationStatus | None:
        credential = self._fresh(
            CredentialRequest(
                audience=self._audience,
                binding=self._binding,
                origin=caller,
                operations=("operation.cancel",),
                dispatch_id=self._new_id(),
            )
        )
        try:
            return await self._client.operation_cancel(handle, cancel_request_id, credential)
        except (KnowledgeTransportError, KnowledgeProtocolRefusal):
            return None

    def _handle_of(self, record: JournalRecord) -> OperationHandle:
        origin = record.originating_origin
        assert record.operation_id is not None
        return OperationHandle(
            protocolVersion="ks.knowledge_operation.v2",
            tenant=origin.tenantId,
            application=origin.applicationId,
            binding=self._binding,
            operationId=record.operation_id,
        )

    # ------------------------------------------------------------ settlement

    async def _lookup_and_settle(
        self,
        scope: str,
        record: JournalRecord,
        origin: Origin,
        *,
        recovery: CredentialRecovery | None = None,
    ) -> tuple[JournalRecord, LookupResult | None]:
        operations: tuple[OperationName, ...] = ("receipt.get",)
        credential = self._fresh(
            CredentialRequest(
                audience=self._audience,
                binding=self._binding,
                origin=origin,
                operations=operations,
                dispatch_id=self._new_id(),
                effect_key=record.effect_key,
                bound_effect_digest=record.bound_effect_digest,
                recovery=recovery,
            )
        )
        try:
            lookup = await self._client.receipt(record.effect_key, credential)
        except (KnowledgeTransportError, KnowledgeProtocolRefusal):
            return record, None
        if isinstance(lookup, ReceiptFound):
            record = await self._accept_receipt(
                scope, record, lookup.receipt, reconciled=True, delivery=lookup.delivery
            )
        return record, lookup

    async def _accept_receipt(
        self,
        scope: str,
        record: JournalRecord,
        receipt: OperationReceipt,
        *,
        reconciled: bool,
        delivery: ReceiptDelivery | None = None,
    ) -> JournalRecord:
        effect = receipt.effect
        if (
            effect.effectKey != record.effect_key
            or effect.boundEffectDigest != record.bound_effect_digest
            or receipt.handle.tenant != record.originating_origin.tenantId
        ):
            # Not proof of this effect: never settle from it.
            if record.state is JournalState.DISPATCHED:
                return await self._mark_uncertain(scope, record)
            return record
        if receipt.outcome not in SETTLED_RECEIPT_OUTCOMES:
            # `pending_dispatch`: admitted and queued, not yet delivered. The effect stays
            # unresolved (blocks finalization) until a later receipt lookup reports delivery.
            delivered = settlement_from_delivery(receipt, delivery)
            if delivered is not None:
                return await self._settle(scope, record, delivered)
            if record.state is JournalState.DISPATCHED:
                return await self._mark_uncertain(scope, record)
            return record
        return await self._settle(
            scope, record, settlement_from_receipt(receipt, reconciled=reconciled)
        )

    async def _settle_or_uncertain(
        self, scope: str, record: JournalRecord, status: OperationStatus | None
    ) -> JournalRecord:
        settlement = None if status is None else settlement_without_receipt(status)
        if settlement is not None:
            return await self._settle(scope, record, settlement)
        if record.state is JournalState.DISPATCHED:
            return await self._mark_uncertain(scope, record)
        return record

    async def _settle(
        self, scope: str, record: JournalRecord, settlement: Settlement
    ) -> JournalRecord:
        if record.state in JOURNAL_TERMINAL:
            return record  # late settlement is idempotent
        try:
            return await self._journal.settle(
                scope,
                record.effect_key,
                expected_version=record.version,
                settlement=settlement,
                at=self._clock(),
            )
        except JournalVersionConflict:
            current = await self._journal.lookup(scope, record.effect_key)
            return current if current is not None else record

    async def _mark_uncertain(self, scope: str, record: JournalRecord) -> JournalRecord:
        try:
            return await self._journal.mark_uncertain(
                scope, record.effect_key, expected_version=record.version, at=self._clock()
            )
        except JournalVersionConflict:
            current = await self._journal.lookup(scope, record.effect_key)
            return current if current is not None else record

    def _finish(
        self,
        operation: str,
        record: JournalRecord,
        *,
        receipt: OperationReceipt | None = None,
        lookup: LookupResult | None = None,
        status: OperationStatus | None = None,
        handle: OperationHandle | None = None,
        refusal_code: str | None = None,
        refusal: ProtocolError | None = None,
    ) -> KnowledgeResult:
        if refusal is None and status is not None and status.error is not None:
            refusal = status.error
        if (
            record.state is JournalState.UNCERTAIN
            and refusal_code is None
            and not pending_delivery(receipt, lookup)
        ):
            refusal_code = "UNRESOLVED_EFFECT"
        return KnowledgeResult(
            operation=operation,
            effect_key=record.effect_key,
            journal=record,
            receipt=receipt,
            lookup=lookup,
            status=status,
            handle=handle,
            refusal_code=refusal_code,
            refusal=refusal if refusal_code is not None else None,
        )

    # ------------------------------------------------------------ helpers

    def _fresh(self, request: CredentialRequest) -> Callable[[], str]:
        """A credential source for an idempotent route: every transmission (including a client
        retry after 429/503 or a transport loss) presents a freshly minted single-use token
        with its own `jti` AND its own dispatch id, so the binding's credential-use registry
        (unique per tenant, issuer and dispatch id) never sees a replay or a reused dispatch
        (R2-MC O5, R3 O5)."""

        def token() -> str:
            return self._mint(replace(request, dispatch_id=self._new_id())).token

        return token

    def _mint(self, request: CredentialRequest) -> MintedCredential:
        minted = self._minter.mint(request)
        try:
            verify_credential_claims(minted.claims, request, now=self._clock())
        except CredentialMismatch as error:
            raise KnowledgeRefused(
                "SCOPE_DENIED", str(error), effect_key=request.effect_key
            ) from None
        return minted

    def _envelope(
        self,
        call: KnowledgeCall,
        caller: Origin,
        dispatch_id: str,
        *,
        request_id: str,
        effect: EffectBinding | None = None,
    ) -> OperationEnvelope:
        native = call.native_bytes()
        return OperationEnvelope(
            protocolVersion="ks.knowledge_operation.v2",
            requestId=request_id,
            dispatchId=dispatch_id,
            tenant=caller.tenantId,
            application=caller.applicationId,
            binding=self._binding,
            operation=call.operation,
            effect=effect,
            target=EnvelopeTarget(handle=None, effectKey=None),
            cancelRequestId=None,
            input=NativeInput(
                nativeContract=call.native_contract,
                payloadDigest=digest_bytes(native),
                payloadBytes=len(native),
                payloadRef=None,
                inlinePayload=call.payload,
                upstream=list(call.upstream),
            ),
            governors=call.governors,
            requiredCapabilities=list(call.required_capabilities),
            pinnedSchema=call.pinned_schema,
            issuedAt=instant(self._clock()),
            use=call.use,
            audience=call.audience,
        )


__all__ = ["KnowledgeGateway", "TrustedAnswer"]

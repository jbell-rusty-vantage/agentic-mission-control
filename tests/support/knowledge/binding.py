"""The one Knowledge Services fake: `FakeKnowledgeBinding`, served over HTTP, and its parity target.

* :class:`FakeKnowledgeBinding` is the K01 semantic fake. Every call is authorized by a real
  :class:`~mission_control.adapters.knowledge.credentials.CredentialVerifier` (pinned issuer
  and JWKS, ``EdDSA`` only, exact audience, window, single-use ``jti``: the K07 stand-in) and
  then checked as K01 ``admitDispatch`` would: the credential grants the operation, its scope
  is the envelope's, its effect is the envelope's, the caller is the originating origin or
  presents an *effect-scoped* recovery claim for that exact key and bound digest, and the same
  key never binds other bytes. Effects commit once per key (native durable deduplication).
  Scripts per ``invoke``: ``"receipt"`` (commit and answer the receipt), ``"handle"`` (answer a
  handle; commits when a scripted status is terminal ``succeeded``/``partial``), ``"lost"``
  (commit, then fail the transport), ``"drop"`` (fail without committing), ``"refuse:CODE"`` and
  ``"commit_refuse:CODE"`` (commit natively, then refuse: the protocol receipt was lost after the
  native commit, WI-05); ``CODE@STATE`` adds the KS 2.5.0 ``details.dispatch`` state
  (``not_journaled``, ``journaled_uncommitted``, ...). Non-effect handle operations
  (``report.assess``, ``knowledge.read``, ...) answer a handle whose statuses are scripted per
  operation name; ``knowledge.read`` resolves the exact revision of a registered report package or
  ends ``rejected`` with ``EXACT_REVISION_UNAVAILABLE``. The trusted assessment operations
  (``report.observe``, ``report.seal``, ``report.decide``, ``report.review``,
  ``decision.resolve``) are served by the operation module in ``trusted.py`` when the fake is
  built with a ``TrustedKnowledgeState``.
* :func:`knowledge_http_app` serves the five K01 routes over a fake binding (Starlette), so
  :class:`~mission_control.adapters.knowledge.http_client.HttpKnowledgeBindingClient` runs
  the same scenarios in process through ``httpx.ASGITransport``.
* :func:`parity_target` selects the binding for a parity scenario: the in-process fake over
  HTTP by default; the real executor when ``KNOWLEDGE_BINDING_URL``, ``KNOWLEDGE_ISSUER``,
  ``KNOWLEDGE_ISSUER_KEY_FILE`` and ``KNOWLEDGE_BINDING_AUDIENCE`` are all set (names only;
  scripted scenarios stay fake-only).
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mission_control.adapters.knowledge.credentials import (
    CredentialRejected,
    CredentialVerifier,
    Ed25519CredentialMinter,
    load_signing_key,
)
from mission_control.adapters.knowledge.http_client import HttpKnowledgeBindingClient
from mission_control.application.ports.knowledge import (
    KnowledgeProtocolRefusal,
    KnowledgeTransportError,
    ReportPackage,
)
from mission_control.contracts.knowledge_protocol import (
    TERMINAL_STATES,
    MembersSelection,
    OperationEnvelope,
    OperationHandle,
    Ref,
    SelectedReportRead,
    can_transition,
    canonical_json,
    digest_bytes,
    digest_canonical,
)
from mission_control.contracts.knowledge_protocol_results import (
    BindingDescriptor,
    ConcurrencyToken,
    CredentialClaims,
    OperationReceipt,
    OperationStatus,
    ProtocolError,
    ProtocolErrorCode,
    ReceiptDelivery,
    ReceiptEffect,
    ReceiptFound,
    ReceiptNotFound,
    ReceiptUnresolved,
    protocol_error,
)
from tests.support.knowledge.content import (
    StoredPackage,
    describe_document,
    package_ref,
    report_package,
)
from tests.support.knowledge.credentials import AUDIENCE, BINDING, Issuer, RecordingMinter, stamp
from tests.support.knowledge.trusted import (
    TRUSTED_OPERATIONS,
    TrustedAssessments,
    TrustedKnowledgeState,
)

HTTP_STATUS: dict[str, int] = {
    "ORIGIN_MISMATCH": 403,
    "SCOPE_DENIED": 401,
    "EFFECT_CONFLICT": 409,
    "SCHEMA_UNSUPPORTED": 422,
    "EXACT_REVISION_UNAVAILABLE": 409,
    "REVIEW_REQUIRED": 409,
    "BUDGET_EXHAUSTED": 429,
    "UNSUPPORTED_MEDIA": 415,
    "STALE_DECISION": 409,
    "UNRESOLVED_EFFECT": 409,
    "INDEPENDENCE_UNPROVEN": 409,
    "INVALID_ENVELOPE": 400,
    "CAPABILITY_UNAVAILABLE": 503,
    "NOT_FOUND": 404,
    "CANCELLED": 409,
    "INTERNAL": 500,
}


@dataclass
class Call:
    kind: str
    claims: CredentialClaims
    envelope: OperationEnvelope | None = None
    effect_key: str | None = None


@dataclass
class FakeOperation:
    handle: OperationHandle
    operation: str
    envelope: OperationEnvelope
    claims: CredentialClaims
    status: OperationStatus


class FakeKnowledgeBinding:
    """The K01 semantic fake (see the module doc); implements ``KnowledgeBindingClient``."""

    def __init__(
        self,
        *,
        verifier: CredentialVerifier,
        clock: Callable[[], datetime],
        binding: str = BINDING,
        application: str = "biotech",
        installation_id: str | None = None,
        trusted: TrustedKnowledgeState | None = None,
    ) -> None:
        self.verifier = verifier
        self.clock = clock
        self.binding = binding
        self.application = application
        # KS `authorize` (W1 D6): when set, the origin must name the installation this binding
        # installs (the component installation), as the real executor checks.
        self.installation_id = installation_id
        self.invoke_script: deque[str] = deque()
        # W1 native write: the read-only `knowledge.plan_preview` answer (None: refused as an
        # unsupported operation, like a binding that previews nothing).
        self.previewer: Callable[[OperationEnvelope], Any] | None = None
        # OVE-204 slice 4: the `knowledge.read_intent` answer (None: refused as an operation the
        # binding does not serve). `read_intent_answer` builds a consistent one.
        self.reader: Callable[[OperationEnvelope], Any] | None = None
        # Whether `knowledge.describe` lists `knowledge.read_intent` (KS serves it only with the
        # host-injected read intent port).
        self.serves_read_intent = True
        self.statuses: deque[str] = deque()
        self.operation_statuses: dict[str, deque[str]] = {}
        self.lookups: deque[str] = deque()
        self.calls: list[Call] = []
        self.committed: dict[str, OperationReceipt] = {}
        self.bound: dict[str, str] = {}
        self.operations: dict[str, FakeOperation] = {}
        self.requests: dict[tuple[str, str], str] = {}
        self.packages: dict[tuple[str, str], StoredPackage] = {}
        # Answered reads: package ref (id, digest) -> (manifest, stored package).
        self.answers: dict[tuple[str, str], tuple[dict[str, Any], StoredPackage]] = {}
        # Purposes the binding admits for knowledge.read (readSelected `purpose_undeclared`).
        self.read_purposes: frozenset[str] | None = None
        self.dispatches: dict[str, int] = {}
        # WI-03 S7: what the binding says runs its census (`describe`).
        self.auditor_kind = "independent"
        # Details a scripted ``refuse:CODE`` carries (None: no details).
        self.refusal_details: dict[str, Any] | None = None
        # WI-03: the trusted assessment operations, served over `trusted` (the durable KS state
        # a "restart" keeps). Without it they are not served, and the binding reads no result
        # bytes (`artifact` is None, as the gateway checks).
        self.trusted = (
            None
            if trusted is None
            else TrustedAssessments(trusted, verify=verifier.verify, clock=clock, binding=binding)
        )
        self.artifact: Callable[[str, str, Any], Awaitable[bytes]] | None = (
            None if self.trusted is None else self.trusted.artifact
        )

    # ---------------------------------------------------------------- authorization

    def error(self, code: ProtocolErrorCode, message: str, **correlation: Any) -> ProtocolError:
        names = {
            "effectKey": "effect_key",
            "operationId": "operation_id",
            "dispatchId": "dispatch_id",
        }
        return protocol_error(
            code,
            message,
            occurred_at=stamp(self.clock()),
            **{names[key]: value for key, value in correlation.items()},
        )

    def refuse(self, code: ProtocolErrorCode, message: str, **correlation: Any) -> None:
        raise KnowledgeProtocolRefusal(self.error(code, message, **correlation))

    def _refuse_with_state(self, spec: str, message: str, effect_key: str | None) -> None:
        """``CODE`` or ``CODE@STATE``: STATE is the KS 2.5.0 ``details.dispatch`` (WI-05)."""

        code, _, state = spec.partition("@")
        error = self.error(code, message, effectKey=effect_key)  # type: ignore[arg-type]
        if self.refusal_details:
            # A scripted refusal's own details (W1 D19: KS names a colliding record).
            error = error.model_copy(update={"details": dict(self.refusal_details)})
        if state:
            # KS 2.5.0 fences a journaled_uncommitted dispatch; a trailing ``!`` omits the fence.
            unfenced = state.endswith("!")
            state = state.rstrip("!")
            fence = {"fenced": True} if state == "journaled_uncommitted" and not unfenced else {}
            error = error.model_copy(update={"details": {"dispatch": state, **fence}})
        raise KnowledgeProtocolRefusal(error)

    def authorize(self, token: str | Callable[[], str], operation: str) -> CredentialClaims:
        if callable(token):
            token = token()  # a fresh single-use credential per transmission
        try:
            claims = self.verifier.verify(token)
        except CredentialRejected as rejected:
            raise KnowledgeProtocolRefusal(self.error("SCOPE_DENIED", rejected.reason)) from None
        if operation not in claims.operations:
            self.refuse("SCOPE_DENIED", "operation not granted")
        if claims.binding != self.binding:
            self.refuse("SCOPE_DENIED", "credential names another binding")
        if (
            self.installation_id is not None
            and claims.origin.installationId != self.installation_id
        ):
            self.refuse("SCOPE_DENIED", "the credential origin names another installation")
        return claims

    def _admit_effect(self, envelope: OperationEnvelope, claims: CredentialClaims) -> None:
        effect = envelope.effect
        assert effect is not None
        if (envelope.tenant, envelope.application) != (claims.tenant, claims.application):
            self.refuse("SCOPE_DENIED", "envelope scope differs from the credential")
        if claims.effect is None or (
            claims.effect.effectKey != effect.effectKey
            or claims.effect.boundEffectDigest != effect.boundEffectDigest
        ):
            self.refuse("SCOPE_DENIED", "credential effect differs from the envelope effect")
        bound = self.bound.get(effect.effectKey)
        if bound is not None and bound != effect.boundEffectDigest:
            self.refuse("EFFECT_CONFLICT", "same key, other bytes", effectKey=effect.effectKey)
        caller = claims.origin
        if caller.digest() != effect.originatingOrigin.digest():
            recovery = claims.recovery
            if (
                recovery is None
                or recovery.scope != "effect"
                or recovery.effectKey != effect.effectKey
                or recovery.boundEffectDigest != effect.boundEffectDigest
            ):
                self.refuse(
                    "ORIGIN_MISMATCH",
                    "a different caller needs effect-scoped recovery authority",
                    effectKey=effect.effectKey,
                )
        self.bound.setdefault(effect.effectKey, effect.boundEffectDigest)

    # ---------------------------------------------------------------- protocol

    async def invoke(
        self, envelope: OperationEnvelope, credential: str
    ) -> OperationHandle | OperationReceipt:
        if self.trusted is not None and envelope.operation in TRUSTED_OPERATIONS:
            return await self.trusted.invoke(envelope, credential)
        claims = self.authorize(credential, envelope.operation)
        key = envelope.effect.effectKey if envelope.effect is not None else None
        self.calls.append(Call("invoke", claims, envelope, key))
        if envelope.operation == "knowledge.plan_preview":
            # A non-effect credential (no effect claim) and nothing bound, journaled or admitted.
            if claims.effect is not None or self.previewer is None:
                self.refuse("SCHEMA_UNSUPPORTED", "this binding previews no native plan")
            assert self.previewer is not None
            return self.previewer(envelope)
        if envelope.operation == "knowledge.read_intent":
            # A non-effect credential granting exactly `knowledge.read_intent`; KS records it.
            if claims.effect is not None or self.reader is None:
                self.refuse("SCHEMA_UNSUPPORTED", "this binding serves no read intent")
            assert self.reader is not None
            return self.reader(envelope)
        if envelope.effect is None:
            return self._start(envelope, claims)
        self._admit_effect(envelope, claims)
        step = self.invoke_script.popleft() if self.invoke_script else "receipt"
        assert key is not None
        self.dispatches[key] = self.dispatches.get(key, 0) + 1
        if step.startswith("refuse:"):
            self._refuse_with_state(step.split(":", 1)[1], "refused", key)
        if step.startswith("commit_refuse:"):
            self._commit(envelope, claims)
            self._refuse_with_state(step.split(":", 1)[1], "protocol receipt lost", key)
        if step == "drop":
            raise KnowledgeTransportError("connection reset before commit")
        if step == "lost":
            self._commit(envelope, claims)
            raise KnowledgeTransportError("connection reset after commit")
        if step == "handle":
            return self._open(envelope, claims, envelope.operation).handle
        if step in {"noop", "partial"}:
            return self._commit(envelope, claims, outcome=step)
        if step == "pending":  # admitted and queued for delivery (Biotech outbox)
            return self._commit(envelope, claims, outcome="pending_dispatch")
        return self._commit(envelope, claims)

    async def operation_get(self, handle: OperationHandle, credential: str) -> OperationStatus:
        if self.trusted is not None and handle.operationId not in self.operations:
            return await self.trusted.operation_get(handle, credential)
        claims = self.authorize(credential, "operation.get")
        self.calls.append(Call("operation.get", claims))
        operation = self.operations.get(handle.operationId)
        if operation is None:
            self.refuse("NOT_FOUND", "unknown handle", operationId=handle.operationId)
        assert operation is not None
        if operation.status.state in TERMINAL_STATES:
            return operation.status
        script = self.operation_statuses.get(operation.operation) or self.statuses
        state = script.popleft() if script else "running"
        return self._advance(operation, state)

    async def operation_cancel(
        self, handle: OperationHandle, cancel_request_id: str, credential: str
    ) -> OperationStatus:
        claims = self.authorize(credential, "operation.cancel")
        self.calls.append(Call("operation.cancel", claims))
        operation = self.operations.get(handle.operationId)
        if operation is None:
            self.refuse("NOT_FOUND", "unknown handle", operationId=handle.operationId)
        assert operation is not None
        status = operation.status
        if status.state in TERMINAL_STATES:
            return status
        first = status.cancelRequestId or cancel_request_id
        if status.state != "queued":
            # Native cancellation: the computation stops at its next boundary (K01 edge
            # running|waiting_review -> cancelling -> cancelled).
            self._transition(operation, "cancelling", cancelRequestId=first)
        return self._transition(operation, "cancelled", cancelRequestId=first)

    async def receipt(
        self, effect_key: str, credential: str
    ) -> ReceiptFound | ReceiptNotFound | ReceiptUnresolved:
        claims = self.authorize(credential, "receipt.get")
        self.calls.append(Call("receipt.get", claims, effect_key=effect_key))
        step = self.lookups.popleft() if self.lookups else "auto"
        if step == "drop":
            raise KnowledgeTransportError("lookup timed out")
        if step == "unresolved":
            return ReceiptUnresolved(
                disposition="unresolved", error=self.error("UNRESOLVED_EFFECT", "unknown")
            )
        if step.startswith("delivery:") and effect_key in self.committed:
            # The binding composes the outbox acknowledgment into the lookup (K01 round 3).
            state = step.split(":", 1)[1]
            acked = state == "applied"
            at = stamp(self.clock())
            delivery = ReceiptDelivery(
                state=state,  # type: ignore[arg-type]
                dispatchId=f"dsp-{effect_key[-12:]}",
                targetBinding=self.binding,
                nativeState="acknowledged" if acked else state,
                ackDigest=digest_canonical({"ack": effect_key}) if acked else None,
                ackedAt=at if acked else None,
                graphTxRef="graph-tx-1" if acked else None,
                checkedAt=at,
            )
            return ReceiptFound(
                disposition="found", receipt=self.committed[effect_key], delivery=delivery
            )
        if step == "auto" and effect_key in self.committed:
            return ReceiptFound(disposition="found", receipt=self.committed[effect_key])
        return ReceiptNotFound(disposition="not_found", checkedAt=stamp(self.clock()))

    async def describe(self, credential: str) -> BindingDescriptor:
        claims = self.authorize(credential, "knowledge.describe")
        self.calls.append(Call("knowledge.describe", claims))
        return BindingDescriptor.model_validate(
            describe_document(
                self.binding,
                self.application,
                self.auditor_kind,
                read_intent=self.serves_read_intent,
            )
        )

    # ---------------------------------------------------------------- exact content

    def register_package(self, package: StoredPackage) -> StoredPackage:
        self.packages[(package.report.id, package.report.digest)] = package
        return package

    def artifact_bytes(
        self, artifact_id: str, digest: str, credential: str | Callable[[], str]
    ) -> bytes:
        """The executor's ``artifacts/{id}?digest=`` extension over the stored packages."""

        self.authorize(credential, "knowledge.read")
        for (answer_id, answer_digest), (manifest, package) in self.answers.items():
            candidates = {
                (answer_id, answer_digest): canonical_json(manifest).encode("utf-8"),
                (f"{package.report.id}.body", digest_bytes(package.body)): package.body,
                (f"{package.report.id}.ledger", digest_bytes(package.ledger)): package.ledger,
            }
            if (artifact_id, digest) in candidates:
                return candidates[(artifact_id, digest)]
        self.refuse("EXACT_REVISION_UNAVAILABLE", "no artifact with that id and digest")
        raise AssertionError  # pragma: no cover

    async def fetch(self, result_ref: Ref, credentials: Callable[[], str]) -> ReportPackage:
        self.authorize(credentials(), "knowledge.read")
        answered = self.answers.get((result_ref.id, result_ref.digest))
        if answered is not None:
            manifest, package = answered
            whole = manifest["body"] is not None
            served = package.body if package.served_body is None else package.served_body
            return ReportPackage(
                result_ref=result_ref,
                manifest=manifest,
                body=served if whole else b"",
                ledger=package.ledger if whole else b"",
            )
        self.refuse("EXACT_REVISION_UNAVAILABLE", "no package for that exact ref")
        raise AssertionError  # pragma: no cover

    # ---------------------------------------------------------------- builders

    def calls_of(self, kind: str) -> list[Call]:
        return [call for call in self.calls if call.kind == kind]

    def _handle(self, envelope: OperationEnvelope, operation_id: str) -> OperationHandle:
        return OperationHandle(
            protocolVersion="ks.knowledge_operation.v2",
            tenant=envelope.tenant,
            application=envelope.application,
            binding=self.binding,
            operationId=operation_id,
        )

    def _open(
        self, envelope: OperationEnvelope, claims: CredentialClaims, operation: str
    ) -> FakeOperation:
        existing = self.requests.get((operation, envelope.requestId))
        if existing is not None:  # idempotent start by request id
            return self.operations[existing]
        operation_id = f"op-{len(self.operations) + 1}"
        at = stamp(self.clock())
        status = OperationStatus(
            handle=self._handle(envelope, operation_id),
            state="queued",
            revision=1,
            createdAt=at,
            updatedAt=at,
            progressRef=None,
            pendingReviewRef=None,
            resultRef=None,
            error=None,
            unresolvedEffects=[],
            retryAfterMs=100,
            cancelRequestId=None,
        )
        record = FakeOperation(status.handle, operation, envelope, claims, status)
        self.operations[operation_id] = record
        self.requests[(operation, envelope.requestId)] = operation_id
        return record

    def _start(self, envelope: OperationEnvelope, claims: CredentialClaims) -> OperationHandle:
        if envelope.operation not in {
            "report.assess",
            "report.derive",
            "verify.claims",
            "knowledge.read",
        }:
            self.refuse("INVALID_ENVELOPE", f"{envelope.operation} is not served here")
        if (envelope.tenant, envelope.application) != (claims.tenant, claims.application):
            self.refuse("SCOPE_DENIED", "envelope scope differs from the credential")
        return self._open(envelope, claims, envelope.operation).handle

    def _transition(self, operation: FakeOperation, state: str, **changes: Any) -> OperationStatus:
        current = operation.status
        if state == current.state:
            return current
        if not can_transition(current.state, state):
            if can_transition(current.state, "running") and can_transition("running", state):
                current = self._transition(operation, "running")
            else:
                raise AssertionError(f"scripted illegal transition {current.state} -> {state}")
        terminal = state in TERMINAL_STATES
        values = current.model_dump(mode="json") | {
            "state": state,
            "revision": current.revision + 1,
            "updatedAt": stamp(self.clock()),
            "retryAfterMs": None if terminal else (current.retryAfterMs or 100),
            **changes,
        }
        operation.status = OperationStatus.model_validate(values)
        return operation.status

    def _advance(self, operation: FakeOperation, state: str) -> OperationStatus:
        changes: dict[str, Any] = {}
        if state == "waiting_review":
            changes["pendingReviewRef"] = Ref(
                kind="adjudication",
                id=f"review-{operation.handle.operationId}",
                version="research-core.adjudication.v1",
                digest=digest_canonical({"review": operation.handle.operationId}),
                tenant=operation.handle.tenant,
                binding=self.binding,
            ).model_dump(mode="json")
        if state == "failed":
            changes["error"] = self.error("INTERNAL", "scripted failure").model_dump(mode="json")
        if state in {"succeeded", "partial", "held", "rejected"}:
            changes |= self._result(operation, state)
            state = changes.pop("state", state)
        if state in {"succeeded", "partial"} and operation.envelope.effect is not None:
            self._commit(
                operation.envelope,
                operation.claims,
                "partial" if state == "partial" else "applied",
            )
        return self._transition(operation, state, **changes)

    def _result(self, operation: FakeOperation, state: str) -> dict[str, Any]:
        if operation.operation == "knowledge.read":
            return self._read(operation.envelope)
        if operation.operation in {"report.assess", "report.derive", "verify.claims"}:
            result = Ref(
                kind="artifact",
                id=f"{operation.operation}-{operation.handle.operationId}",
                version="research-core.report_assessment.v1",
                digest=digest_canonical({"op": operation.handle.operationId, "state": state}),
                tenant=operation.handle.tenant,
                binding=self.binding,
            )
            return {"resultRef": result.model_dump(mode="json")}
        return {}

    def _read(self, envelope: OperationEnvelope) -> dict[str, Any]:
        """readSelected: the exact v2 package for this request, or a typed rejection."""

        def rejected(code: ProtocolErrorCode, message: str) -> dict[str, Any]:
            return {"state": "rejected", "error": self.error(code, message).model_dump(mode="json")}

        contract = envelope.input.nativeContract if envelope.input else None
        if contract is None or (contract.name, contract.version) != (
            "selected-report-read",
            "v2",
        ):
            return rejected("SCHEMA_UNSUPPORTED", "knowledge.read takes selected-report-read/v2")
        try:
            read = SelectedReportRead.model_validate(
                envelope.input.inlinePayload if envelope.input else None
            )
        except ValueError:
            return rejected("INVALID_ENVELOPE", "selection_invalid")
        upstream = (envelope.input.upstream if envelope.input else [])[:1]
        if upstream and upstream[0] != read.report:
            return rejected("INVALID_ENVELOPE", "report_upstream_mismatch")
        if self.read_purposes is not None and read.purpose not in self.read_purposes:
            return rejected("INVALID_ENVELOPE", "purpose_undeclared")
        package = self.packages.get((read.report.id, read.report.digest))
        if package is None:
            return rejected("EXACT_REVISION_UNAVAILABLE", "revision_unavailable")
        if isinstance(read.selection, MembersSelection):
            known = {
                **{h.id: h for h, _ in package.member_handles("assertion")},
                **{h.id: h for h, _ in package.member_handles("fragment")},
            }
            for handle in (*read.selection.assertions, *read.selection.evidence):
                if handle.id not in known:
                    return rejected("INVALID_ENVELOPE", "member_unknown")
                if known[handle.id] != handle:
                    return rejected("EXACT_REVISION_UNAVAILABLE", "member_revision_mismatch")
        manifest = package.answer(read)
        ref = package_ref(read.report, manifest)
        self.answers[(ref.id, ref.digest)] = (manifest, package)
        return {"resultRef": ref.model_dump(mode="json")}

    def _commit(
        self, envelope: OperationEnvelope, claims: CredentialClaims, outcome: str = "applied"
    ) -> OperationReceipt:
        effect = envelope.effect
        assert effect is not None
        if effect.effectKey in self.committed:  # native durable deduplication
            return self.committed[effect.effectKey]
        tenant = envelope.tenant
        handle = self._handle(envelope, f"op-{effect.effectKey[-12:]}")
        affected: list[Ref] = []
        if envelope.operation == "report.register" and isinstance(
            envelope.input.inlinePayload if envelope.input else None, dict
        ):
            payload = envelope.input.inlinePayload if envelope.input else {}
            assert isinstance(payload, dict)
            # W1 D1: the host-canonicalized `research-report/v2` payload names its report.
            named = payload.get("report")
            named = named if isinstance(named, dict) else {}
            report_id = str(named.get("reportId", "report-1"))
            package = self.register_package(
                report_package(report_id, str(named.get("revision", 1)), tenant=tenant)
            )
            affected.append(package.report)
        body: dict[str, Any] = {
            "handle": handle,
            "effect": ReceiptEffect(
                effectKey=effect.effectKey,
                semanticPayloadDigest=effect.semanticPayloadDigest,
                originatingOrigin=effect.originatingOrigin,
                boundEffectDigest=effect.boundEffectDigest,
                canonicalization="kop-canonical-json.v1",
                currentCallerOrigin=claims.origin,
                dispatchId=envelope.dispatchId,
                envelopeDigest=envelope.digest(),
                dispatchSequence=self.dispatches.get(effect.effectKey, 1),
            ),
            "outcome": outcome,
            "nativeReceiptRef": Ref(
                kind="receipt",
                id=f"rcpt-{len(self.committed) + 1}",
                version="receipt.v1",
                digest=effect.boundEffectDigest,
                tenant=tenant,
                binding=self.binding,
            ),
            "affectedRefs": affected,
            "concurrencyToken": ConcurrencyToken(before=None, after="1"),
            "processedRevocationEpoch": 0,
            "itemOutcomes": [],
            "appliedAt": stamp(self.clock()),
            "details": None,
        }
        receipt = OperationReceipt(**body, digest=digest_canonical(dict(body)))
        self.committed[effect.effectKey] = receipt
        return receipt


def knowledge_http_app(binding: FakeKnowledgeBinding) -> Starlette:
    """The five K01 routes over ``binding`` (the shape the KS executor exposes)."""

    def bearer(request: Request) -> str:
        header = request.headers.get("authorization", "")
        return header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""

    def refusal(error: ProtocolError) -> JSONResponse:
        return JSONResponse(error.model_dump(mode="json"), status_code=HTTP_STATUS[error.code])

    async def guarded(call: Callable[[], Any]) -> JSONResponse:
        try:
            result = await call()
        except KnowledgeProtocolRefusal as refused:
            return refusal(refused.error)
        except KnowledgeTransportError:
            return JSONResponse({"detail": "upstream reset"}, status_code=502)
        return JSONResponse(result.model_dump(mode="json"))

    async def invoke(request: Request) -> JSONResponse:
        try:
            envelope = OperationEnvelope.model_validate_json(await request.body())
        except ValueError:
            return refusal(binding.error("INVALID_ENVELOPE", "envelope is not K01"))
        return await guarded(lambda: binding.invoke(envelope, bearer(request)))

    def handle_of(request: Request) -> OperationHandle:
        operation = binding.operations.get(request.path_params["operation_id"])
        if operation is None:
            raise KnowledgeProtocolRefusal(binding.error("NOT_FOUND", "unknown handle"))
        return operation.handle

    async def get_operation(request: Request) -> JSONResponse:
        async def run() -> OperationStatus:
            return await binding.operation_get(handle_of(request), bearer(request))

        return await guarded(run)

    async def cancel(request: Request) -> JSONResponse:
        body = await request.json()

        async def run() -> OperationStatus:
            return await binding.operation_cancel(
                handle_of(request), str(body["cancelRequestId"]), bearer(request)
            )

        return await guarded(run)

    async def receipt(request: Request) -> JSONResponse:
        return await guarded(
            lambda: binding.receipt(request.path_params["effect_key"], bearer(request))
        )

    async def describe(request: Request) -> JSONResponse:
        return await guarded(lambda: binding.describe(bearer(request)))

    async def artifact(request: Request) -> Response:
        try:
            content = binding.artifact_bytes(
                request.path_params["artifact_id"],
                request.query_params.get("digest", ""),
                bearer(request),
            )
        except KnowledgeProtocolRefusal as refused:
            return refusal(refused.error)
        return Response(content, media_type="application/octet-stream")

    prefix = "/knowledge-operation/v2"
    return Starlette(
        routes=[
            Route(f"{prefix}/invoke", invoke, methods=["POST"]),
            Route(f"{prefix}/operations/{{operation_id:str}}", get_operation, methods=["GET"]),
            Route(f"{prefix}/operations/{{operation_id:str}}/cancel", cancel, methods=["POST"]),
            Route(f"{prefix}/receipts/{{effect_key:str}}", receipt, methods=["GET"]),
            Route(f"{prefix}/describe", describe, methods=["GET"]),
            Route(f"{prefix}/artifacts/{{artifact_id:str}}", artifact, methods=["GET"]),
        ]
    )


def http_client_over(binding: FakeKnowledgeBinding, **options: Any) -> HttpKnowledgeBindingClient:
    transport = httpx.ASGITransport(app=knowledge_http_app(binding))
    return HttpKnowledgeBindingClient("http://ks-executor.test", transport=transport, **options)


REAL_BINDING_ENV = (
    "KNOWLEDGE_BINDING_URL",
    "KNOWLEDGE_ISSUER",
    "KNOWLEDGE_ISSUER_KEY_FILE",
    "KNOWLEDGE_BINDING_AUDIENCE",
)


@dataclass
class ParityTarget:
    name: str
    client: Any
    minter: Any
    audience: str
    binding: str
    fake: FakeKnowledgeBinding | None = None


def real_binding_configured(environ: Mapping[str, str] = os.environ) -> bool:
    return all(environ.get(name) for name in REAL_BINDING_ENV)


def parity_target(
    kind: str, *, clock: Callable[[], datetime], environ: Mapping[str, str] = os.environ
) -> ParityTarget:
    """``"fake"``: the fake over the in-process HTTP surface; ``"real"``: the KS executor."""

    if kind == "real":
        from pathlib import Path

        key = load_signing_key(Path(environ["KNOWLEDGE_ISSUER_KEY_FILE"]))
        minter = Ed25519CredentialMinter(issuer=environ["KNOWLEDGE_ISSUER"], active=key)
        return ParityTarget(
            name="real",
            client=HttpKnowledgeBindingClient(environ["KNOWLEDGE_BINDING_URL"]),
            minter=RecordingMinter(minter),
            audience=environ["KNOWLEDGE_BINDING_AUDIENCE"],
            binding=environ.get("KNOWLEDGE_BINDING_ID", BINDING),
        )
    issuer = Issuer(clock=clock)
    fake = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    return ParityTarget(
        name="fake",
        client=http_client_over(fake),
        minter=RecordingMinter(issuer.minter()),
        audience=AUDIENCE,
        binding=BINDING,
        fake=fake,
    )


__all__ = [
    "HTTP_STATUS",
    "REAL_BINDING_ENV",
    "Call",
    "FakeKnowledgeBinding",
    "FakeOperation",
    "ParityTarget",
    "http_client_over",
    "knowledge_http_app",
    "parity_target",
    "real_binding_configured",
]

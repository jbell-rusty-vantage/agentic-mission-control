"""Knowledge binding parity harness for the gateway, tools and M03/M04 seams (Sprint V SV-16).

Pieces:

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
  ends ``rejected`` with ``EXACT_REVISION_UNAVAILABLE``.
* :func:`knowledge_http_app` serves the five K01 routes over a fake binding (Starlette), so
  :class:`~mission_control.adapters.knowledge.http_client.HttpKnowledgeBindingClient` runs
  the same scenarios in process through ``httpx.ASGITransport``.
* :func:`parity_target` selects the binding for a parity scenario: the in-process fake over
  HTTP by default; the real executor when ``KNOWLEDGE_BINDING_URL``, ``KNOWLEDGE_ISSUER``,
  ``KNOWLEDGE_ISSUER_KEY_FILE`` and ``KNOWLEDGE_BINDING_AUDIENCE`` are all set (names only;
  scripted scenarios stay fake-only).
* In-memory journal, handle, submission and transfer stores with the release 1.5.0/1.6.0
  legality rules, a content-addressed staging store and a stepping clock.
"""

from __future__ import annotations

import hashlib
import os
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mission_control.adapters.knowledge.credentials import (
    CredentialRejected,
    CredentialVerifier,
    Ed25519CredentialMinter,
    SigningKey,
    generate_signing_key,
    load_signing_key,
)
from mission_control.adapters.knowledge.http_client import HttpKnowledgeBindingClient
from mission_control.application.context.materialization import TransferPlanConflict
from mission_control.application.ports.knowledge import (
    CredentialRequest,
    FinalizationCandidate,
    FinalizationRecord,
    HandleCandidate,
    HandleRecord,
    JournalRecord,
    JournalVersionConflict,
    KnowledgeProtocolRefusal,
    KnowledgeTransportError,
    LineageEntry,
    MintedCredential,
    PrepareRequest,
    ReportPackage,
    RetainedReadObservation,
    Settlement,
    SubmissionCandidate,
    SubmissionClosed,
    SubmissionConflict,
    SubmissionRecord,
)
from mission_control.bootstrap.application_profiles import load_application_file
from mission_control.contracts.knowledge_protocol import (
    PROTOCOL_VERSION,
    TERMINAL_STATES,
    KnowledgeReadIntentRequest,
    KnowledgeReadIntentResult,
    MembersSelection,
    OperationEnvelope,
    OperationHandle,
    Ref,
    RevisionSelection,
    SelectedReportRead,
    can_reach,
    can_transition,
    canonical_json,
    digest_bytes,
    digest_canonical,
    read_intent_snapshot_digest,
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
from mission_control.domain.context.transfer import DeliveryReceipt, SealedTransferPlan
from mission_control.domain.knowledge.effects import (
    EffectConflict,
    JournalState,
    require_transition,
)
from mission_control.domain.resolution.resolved import KnowledgePortBinding

ISSUER = "mission-control"
AUDIENCE = "ks-executor"
BINDING = "aiengineer-postgres"
DEPLOYMENTS = Path(__file__).resolve().parents[2] / "deployments"


def knowledge_port(binding: str = BINDING) -> KnowledgePortBinding:
    """The checked-in Application Profile's knowledge port for ``binding`` (OC-R4)."""

    for path in sorted(DEPLOYMENTS.glob("*/application.toml")):
        port = load_application_file(path).profile.knowledge
        if port.binding_id == binding:
            return port
    raise LookupError(f"no deployments/*/application.toml names binding {binding}")


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


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class SteppingClock:
    """A fixed-start clock that advances by ``step`` on every read."""

    def __init__(self, start: datetime | None = None, step: timedelta = timedelta(0)) -> None:
        self.now = start or datetime(2026, 10, 24, 20, 0, tzinfo=UTC)
        self.step = step

    def __call__(self) -> datetime:
        current = self.now
        self.now = current + self.step
        return current

    def advance(self, delta: timedelta) -> None:
        self.now += delta


# ---------------------------------------------------------------- credentials


@dataclass
class Issuer:
    """A disposable issuer: active and retiring Ed25519 keys, the minter and the JWKS."""

    clock: Callable[[], datetime]
    active: SigningKey = field(default_factory=lambda: generate_signing_key("mc-k2"))
    retiring: SigningKey | None = field(default_factory=lambda: generate_signing_key("mc-k1"))
    issuer: str = ISSUER
    lifetime: int = 300

    def minter(self) -> Ed25519CredentialMinter:
        return Ed25519CredentialMinter(
            issuer=self.issuer,
            active=self.active,
            retiring=self.retiring,
            lifetime_seconds=self.lifetime,
            clock=self.clock,
        )

    def verifier(
        self, *, audience: str = AUDIENCE, issuer: str | None = None
    ) -> CredentialVerifier:
        return CredentialVerifier(
            issuer=issuer or self.issuer,
            audience=audience,
            jwks=self.minter().jwks(),
            clock=self.clock,
        )


@dataclass
class RecordingMinter:
    """Wraps the real minter: records claims and optionally re-signs drifted claims."""

    inner: Ed25519CredentialMinter
    drift: dict[str, Any] = field(default_factory=dict)
    minted: list[CredentialClaims] = field(default_factory=list)

    @property
    def issuer(self) -> str:
        return self.inner.issuer

    def mint(self, request: CredentialRequest) -> MintedCredential:
        minted = self.inner.mint(request)
        if self.drift:
            claims = CredentialClaims.model_validate(
                minted.claims.model_dump(mode="json") | self.drift
            )
            minted = MintedCredential(claims=claims, token=self.inner.sign_claims(claims))
        self.minted.append(minted.claims)
        return minted


# ---------------------------------------------------------------- the fake binding


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


@dataclass
class StoredPackage:
    """One exact report revision the fake serves: its body, ledger and member records."""

    report: Ref
    kind: Ref
    body: bytes
    ledger: bytes
    assertions: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...] = ()
    # The bytes the binding actually serves (a truncated or corrupt custody copy), when they
    # differ from what the package manifest declares.
    served_body: bytes | None = None

    def member_handles(self, kind: str) -> tuple[tuple[Ref, dict[str, Any]], ...]:
        records = self.assertions if kind == "assertion" else self.evidence
        version = (
            "research-core.assertion.v2" if kind == "assertion" else "research-core.fragment.v2"
        )
        return tuple(
            (
                Ref(
                    kind=kind,  # type: ignore[arg-type]
                    id=record["id"],
                    version=version,
                    digest=digest_canonical(record),
                    tenant=self.report.tenant,
                    binding=self.report.binding,
                ),
                record,
            )
            for record in records
        )

    def artifact(self, suffix: str, content: bytes) -> dict[str, str]:
        return {
            "kind": "artifact",
            "id": f"{self.report.id}.{suffix}",
            "version": "research-core.artifact.v1",
            "digest": digest_bytes(content),
            "tenant": self.report.tenant,
            "binding": self.report.binding,
        }

    def answer(self, read: SelectedReportRead) -> dict[str, Any]:
        """``research-report-package.v2`` for exactly this read (KS readSelected semantics)."""

        whole = isinstance(read.selection, RevisionSelection)
        assertions = self.member_handles("assertion")
        evidence = self.member_handles("fragment")
        if not whole:
            assert isinstance(read.selection, MembersSelection)
            wanted_a = {h.id: h for h in read.selection.assertions}
            wanted_e = {h.id: h for h in read.selection.evidence}
            assertions = tuple(item for item in assertions if item[0].id in wanted_a)
            evidence = tuple(item for item in evidence if item[0].id in wanted_e)
        return {
            "schema": "research-report-package.v2",
            "report": self.report.model_dump(mode="json"),
            "revision": self.report.id,
            "kind": self.kind.model_dump(mode="json"),
            "purpose": read.purpose,
            "request": read.digest(),
            "selection": read.selection.model_dump(mode="json"),
            "body": {
                "path": "body.md",
                "digest": digest_bytes(self.body),
                "bytes": len(self.body),
                "artifact": self.artifact("body", self.body),
            }
            if whole
            else None,
            "ledger": {
                "path": "ledger.json",
                "digest": digest_bytes(self.ledger),
                "bytes": len(self.ledger),
                "artifact": self.artifact("ledger", self.ledger),
            }
            if whole
            else None,
            "assertions": [
                {"handle": h.model_dump(mode="json"), "record": r} for h, r in assertions
            ],
            "evidence": [{"handle": h.model_dump(mode="json"), "record": r} for h, r in evidence],
        }

    @property
    def result_ref(self) -> Ref:
        """The package of a whole-revision read under the dependent-input purpose."""

        read = SelectedReportRead(
            report=self.report, exact=True, purpose="dependent_input", selection=RevisionSelection()
        )
        return package_ref(self.report, self.answer(read))


def package_ref(report: Ref, manifest: dict[str, Any]) -> Ref:
    digest = digest_canonical(manifest)
    return Ref(
        kind="artifact",
        id=f"{report.id}.package.{digest[7:19]}",
        version="research-report-package.v2",
        digest=digest,
        tenant=report.tenant,
        binding=report.binding,
    )


def report_package(
    report_id: str,
    version: str,
    *,
    tenant: str,
    binding: str = BINDING,
    body: bytes = b"# Findings\n\nThe exact body.\n",
    ledger: bytes = b'{"assertions":["a-1"]}',
    assertions: tuple[str, ...] = ("a-1",),
    evidence: tuple[str, ...] = (),
) -> StoredPackage:
    report = Ref(
        kind="report",
        id=report_id,
        version="research-report.v2",
        digest=digest_canonical({"id": report_id, "version": version, "body": digest_bytes(body)}),
        tenant=tenant,
        binding=binding,
    )
    kind = Ref(
        kind="report_kind",
        id="evidence_report",
        version="research-report-kind.v1",
        digest=digest_canonical({"kind": "evidence_report"}),
        tenant=tenant,
        binding=binding,
    )

    def record(schema: str, item_id: str, text: str) -> dict[str, Any]:
        return {
            "schemaVersion": schema,
            "id": item_id,
            "tenant": tenant,
            "binding": binding,
            "proposition" if "assertion" in schema else "text": text,
        }

    return StoredPackage(
        report=report,
        kind=kind,
        body=body,
        ledger=ledger,
        assertions=tuple(
            record("research-core.assertion.v2", item, f"claim {item}") for item in assertions
        ),
        evidence=tuple(
            record("research-core.fragment.v2", item, f"fragment {item}") for item in evidence
        ),
    )


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


def describe_document(
    binding: str, application: str, auditor_kind: str = "independent", *, read_intent: bool = True
) -> dict[str, Any]:
    document = {
        "protocolVersions": [PROTOCOL_VERSION],
        "binding": binding,
        "application": application,
        "coreSchemas": ["research-report.v2"],
        "operations": [
            "knowledge.describe",
            "knowledge.read",
            "knowledge.apply",
            "report.register",
            "report.assess",
            "report.derive",
            "verify.claims",
            "operation.get",
            "operation.cancel",
            "receipt.get",
        ],
        "auditorKind": auditor_kind,
        "reportKinds": ["evidence_report", "study_appraisal"],
        "media": ["text.markdown"],
        "guarantees": {
            "exactRead": "exact_revision",
            "receiptLookup": "by_effect_key",
            "nativeCancellation": "native",
            "admission": "exact_use_decision",
            "revocation": "epoch_checked",
            "writeAtomicity": "single_transaction",
        },
        "signingIssuer": "knowledge-services",  # the binding's seal signer, not MC's issuer
        "pinnedSchema": {
            "name": "knowledge-verification-2.5.0",
            "version": "knowledge-verification.v2",
            "digest": "sha256:" + "1" * 64,
        },
        "qualification": [],
        "describedAt": "2026-10-25T00:00:00Z",
    }
    if read_intent:
        # OVE-204 slice 4: a binding with the host-injected read intent port serves it.
        document["operations"].insert(3, "knowledge.read_intent")  # type: ignore[attr-defined]
    return document


# ---------------------------------------------------------------- HTTP surface over the fake


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


# ---------------------------------------------------------------- in-memory stores


class InMemoryKnowledgeJournal:
    """The journal port with the 1.5.0 legality rules, for unit tests."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], JournalRecord] = {}
        self.coordinates: dict[tuple[str, str], tuple[str, str, int]] = {}
        self.history: dict[tuple[str, str], list[tuple[JournalState | None, JournalState]]] = {}

    async def prepare(self, request: PrepareRequest) -> JournalRecord:
        key = (request.scope, request.effect_key)
        existing = self.rows.get(key)
        if existing is not None:
            if existing.bound_effect_digest != request.bound_effect_digest:
                raise EffectConflict(f"EFFECT_CONFLICT {request.effect_key}")
            return existing
        record = JournalRecord(
            knowledge_operation_id=str(uuid4()),
            effect_key=request.effect_key,
            semantic_payload_digest=request.semantic_payload_digest,
            bound_effect_digest=request.bound_effect_digest,
            originating_origin=request.originating_origin,
            current_caller_origin=request.current_caller_origin,
            capability_pin=request.capability_pin,
            binding_id=request.binding_id,
            state=JournalState.PREPARED,
            version=1,
            operation_ref=request.coordinates.operation_ref,
            operation_attempt=request.coordinates.operation_attempt,
        )
        self.rows[key] = record
        coordinates = request.coordinates
        self.coordinates[key] = (
            coordinates.run_id,
            coordinates.operation_ref,
            coordinates.operation_attempt,
        )
        self.history[key] = [(None, JournalState.PREPARED)]
        return record

    async def lookup(self, scope: str, effect_key: str) -> JournalRecord | None:
        return self.rows.get((scope, effect_key))

    async def open_for_attempt(
        self, scope: str, *, run_id: str, operation_ref: str, operation_attempt: int
    ) -> list[JournalRecord]:
        wanted = (run_id, operation_ref, operation_attempt)
        return [
            record
            for key, record in self.rows.items()
            if key[0] == scope
            and self.coordinates[key] == wanted
            and record.state
            in {JournalState.PREPARED, JournalState.DISPATCHED, JournalState.UNCERTAIN}
        ]

    async def open_for_operation(
        self, scope: str, *, run_id: str, operation_ref: str
    ) -> list[JournalRecord]:
        return [
            record
            for key, record in self.rows.items()
            if key[0] == scope
            and self.coordinates[key][:2] == (run_id, operation_ref)
            and record.state
            in {JournalState.PREPARED, JournalState.DISPATCHED, JournalState.UNCERTAIN}
        ]

    def _advance(self, scope: str, effect_key: str, expected: int, **changes: Any) -> JournalRecord:
        key = (scope, effect_key)
        current = self.rows[key]
        if current.version != expected:
            raise JournalVersionConflict(effect_key)
        state = changes.get("state", current.state)
        if state != current.state:
            require_transition(current.state, state)
        record = replace(current, version=current.version + 1, **changes)
        self.rows[key] = record
        self.history[key].append((current.state, record.state))
        return record

    async def dispatch(
        self,
        scope: str,
        effect_key: str,
        *,
        expected_version: int,
        dispatch_id: str,
        envelope_digest: str,
        protocol_version: str,
        caller: Any,
        at: datetime,
        recovery_authority_ref: str | None = None,
    ) -> JournalRecord:
        return self._advance(
            scope,
            effect_key,
            expected_version,
            state=JournalState.DISPATCHED,
            dispatch_id=dispatch_id,
            envelope_digest=envelope_digest,
            protocol_version=protocol_version,
            current_caller_origin=caller,
            recovery_authority_ref=recovery_authority_ref,
        )

    async def record_handle(
        self, scope: str, effect_key: str, *, expected_version: int, operation_id: str, at: datetime
    ) -> JournalRecord:
        return self._advance(scope, effect_key, expected_version, operation_id=operation_id)

    async def settle(
        self,
        scope: str,
        effect_key: str,
        *,
        expected_version: int,
        settlement: Settlement,
        at: datetime,
    ) -> JournalRecord:
        return self._advance(
            scope,
            effect_key,
            expected_version,
            state=settlement.state,
            terminal_receipt_ref=settlement.terminal_receipt_ref,
            receipt_digest=settlement.receipt_digest,
            refusal_code=settlement.refusal_code,
            reconciled=settlement.reconciled,
        )

    async def mark_uncertain(
        self, scope: str, effect_key: str, *, expected_version: int, at: datetime
    ) -> JournalRecord:
        return self._advance(scope, effect_key, expected_version, state=JournalState.UNCERTAIN)

    async def transitions(
        self, scope: str, effect_key: str
    ) -> list[tuple[JournalState | None, JournalState]]:
        return list(self.history.get((scope, effect_key), []))


class InMemoryKnowledgeHandleStore:
    """``KnowledgeHandleStore`` with the 1.6.0 rules (monotonic revision, first cancel id)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], HandleRecord] = {}
        self.runs: dict[tuple[str, str, str], str] = {}

    async def record(self, candidate: HandleCandidate) -> HandleRecord:
        key = (candidate.scope, candidate.binding_id, candidate.handle.operationId)
        if key in self.rows:
            return self.rows[key]
        self.runs[key] = candidate.coordinates.run_id
        record = HandleRecord(
            handle_id=str(uuid4()),
            binding_id=candidate.binding_id,
            operation=candidate.operation,
            request_id=candidate.request_id,
            handle=candidate.handle,
            invocation_ref=candidate.invocation_ref,
            caller_origin=candidate.caller_origin,
            state="queued",
            remote_revision=0,
            version=1,
            effect_key=candidate.effect_key,
            subject_ref=candidate.subject_ref,
        )
        self.rows[key] = record
        return record

    async def get(self, scope: str, binding_id: str, operation_id: str) -> HandleRecord | None:
        return self.rows.get((scope, binding_id, operation_id))

    async def observe(
        self, scope: str, binding_id: str, status: OperationStatus, *, at: datetime
    ) -> HandleRecord:
        key = (scope, binding_id, status.handle.operationId)
        current = self.rows[key]
        if status.revision <= current.remote_revision or current.terminal:
            return current
        if status.state != current.state and not can_reach(current.state, status.state):
            return current  # stale or illegal: a poll never regresses a handle
        record = replace(
            current,
            state=status.state,
            remote_revision=status.revision,
            version=current.version + 1,
            cancel_request_id=current.cancel_request_id or status.cancelRequestId,
            pending_review_ref=None
            if status.pendingReviewRef is None
            else status.pendingReviewRef.id,
            result_ref=status.resultRef,
            error_code=None if status.error is None else status.error.code,
            unresolved_effects=tuple(
                effect.model_dump(mode="json") for effect in status.unresolvedEffects
            ),
        )
        self.rows[key] = record
        return record

    async def request_cancel(
        self,
        scope: str,
        binding_id: str,
        operation_id: str,
        cancel_request_id: str,
        *,
        at: datetime,
    ) -> HandleRecord:
        key = (scope, binding_id, operation_id)
        current = self.rows[key]
        if current.cancel_request_id is not None or current.terminal:
            return current
        record = replace(current, cancel_request_id=cancel_request_id, version=current.version + 1)
        self.rows[key] = record
        return record

    async def open_for_run(self, scope: str, run_id: str) -> list[HandleRecord]:
        return [
            record
            for key, record in self.rows.items()
            if key[0] == scope and self.runs.get(key) == run_id and not record.terminal
        ]

    async def open_for_invocation(self, scope: str, invocation_ref: str) -> list[HandleRecord]:
        return [
            record
            for key, record in self.rows.items()
            if key[0] == scope and record.invocation_ref == invocation_ref and not record.terminal
        ]


class InMemorySubmissionStore:
    """``OutputSubmissionStore`` with the 1.5.0 + 1.6.0 rules."""

    def __init__(self) -> None:
        self.rows: dict[str, SubmissionRecord] = {}
        self.scopes: dict[str, str] = {}
        self.finalizations: dict[tuple[str, str], FinalizationRecord] = {}
        self.meta: dict[str, tuple[str, str, int]] = {}  # submission -> run, operation, attempt
        self.finalized: list[tuple[str, FinalizationCandidate]] = []

    async def record_selection(self, candidate: SubmissionCandidate) -> SubmissionRecord:
        if (candidate.scope, candidate.invocation_ref) in self.finalizations:
            raise SubmissionClosed(candidate.invocation_ref)
        mine = [
            row
            for sid, row in self.rows.items()
            if self.scopes[sid] == candidate.scope
            and row.invocation_ref == candidate.invocation_ref
            and row.obligation_id == candidate.obligation_id
        ]
        for row in mine:
            if row.submission_key == candidate.submission_key:
                if row.selection_digest != candidate.selection_digest:
                    raise SubmissionConflict(candidate.submission_key)
                return row
        record = SubmissionRecord(
            submission_id=str(uuid4()),
            invocation_ref=candidate.invocation_ref,
            obligation_id=candidate.obligation_id,
            submission_key=candidate.submission_key,
            revision=len(mine) + 1,
            selection_digest=candidate.selection_digest,
            assessment_state="pending",
            selection=candidate.selection,
        )
        self.rows[record.submission_id] = record
        self.scopes[record.submission_id] = candidate.scope
        self.meta[record.submission_id] = (
            candidate.run_id,
            candidate.operation_ref,
            candidate.operation_attempt,
        )
        return record

    async def list_for_invocation(self, scope: str, invocation_ref: str) -> list[SubmissionRecord]:
        return sorted(
            (
                row
                for sid, row in self.rows.items()
                if self.scopes[sid] == scope and row.invocation_ref == invocation_ref
            ),
            key=lambda row: (row.obligation_id, row.revision),
        )

    def _cas(self, submission_id: str, expected: int, **changes: Any) -> SubmissionRecord:
        current = self.rows[submission_id]
        if current.version != expected:
            raise JournalVersionConflict(submission_id)
        record = replace(current, version=current.version + 1, **changes)
        self.rows[submission_id] = record
        return record

    async def start_assessment(
        self,
        scope: str,
        submission_id: str,
        *,
        expected_version: int,
        operation_id: str,
        binding_id: str,
        actor_ref: str,
        at: datetime,
    ) -> SubmissionRecord:
        if self.rows[submission_id].assessment_state != "pending":
            raise ValueError("only a pending submission starts its assessment")
        return self._cas(
            submission_id,
            expected_version,
            assessment_state="assessing",
            assessment_operation_id=operation_id,
            assessment_binding=binding_id,
        )

    async def record_assessment(
        self,
        scope: str,
        submission_id: str,
        *,
        expected_version: int,
        state: str,
        assessment_ref: str,
        assessment_digest: str | None,
        actor_ref: str,
        at: datetime,
    ) -> SubmissionRecord:
        if self.rows[submission_id].assessment_state != "assessing":
            raise ValueError("only an assessing submission records its assessment")
        return self._cas(
            submission_id,
            expected_version,
            assessment_state=state,
            assessment_ref=assessment_ref,
            assessment_digest=assessment_digest,
        )

    async def finalize(self, candidate: FinalizationCandidate) -> FinalizationRecord:
        key = (candidate.scope, candidate.invocation_ref)
        if key not in self.finalizations:
            self.finalized.append((candidate.scope, candidate))
            self.finalizations[key] = FinalizationRecord(
                finalization_id=str(uuid4()),
                invocation_ref=candidate.invocation_ref,
                outcome=candidate.outcome,
                submission_ids=candidate.submission_ids,
                report=candidate.report,
                report_digest=candidate.report_digest,
                outcome_basis=candidate.outcome_basis,
            )
        return self.finalizations[key]


class InMemoryTransferPlanStore:
    """``TransferPlanStore``: one immutable plan per receiver key, appended receipts (0057)."""

    def __init__(self) -> None:
        self.plans: dict[tuple[str, str], SealedTransferPlan] = {}
        self.receipt_rows: list[tuple[str, DeliveryReceipt]] = []

    async def seal(self, plan: SealedTransferPlan) -> SealedTransferPlan:
        key = (plan.receiver.scope, plan.receiver_key)
        stored = self.plans.setdefault(key, plan)
        if stored.digest != plan.digest:
            raise TransferPlanConflict(f"receiver {plan.receiver_key} has another sealed plan")
        return stored

    async def plan_for(self, scope: str, receiver_key: str) -> SealedTransferPlan | None:
        return self.plans.get((scope, receiver_key))

    async def get(self, scope: str, plan_id: str) -> SealedTransferPlan | None:
        return next(
            (p for (s, _k), p in self.plans.items() if s == scope and p.plan_id == plan_id),
            None,
        )

    async def append_receipt(self, scope: str, receipt: DeliveryReceipt) -> DeliveryReceipt:
        sequence = 1 + sum(1 for s, r in self.receipt_rows if r.plan_id == receipt.plan_id)
        stored = receipt.model_copy(update={"sequence": sequence})
        self.receipt_rows.append((scope, stored))
        return stored

    async def receipts(self, scope: str, plan_id: str) -> tuple[DeliveryReceipt, ...]:
        return tuple(r for s, r in self.receipt_rows if s == scope and r.plan_id == plan_id)

    async def file_realizations(self, scope: str, source_refs: Sequence[str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for s, receipt in self.receipt_rows:
            plan = await self.get(s, receipt.plan_id)
            if s != scope or plan is None:
                continue
            for item in receipt.delivered:
                source = plan.member(item.member_key).source_ref
                if (
                    source in source_refs
                    and item.placement == "file"
                    and item.ok
                    and source not in found
                ):
                    found[source] = f"transfer-receipt:{receipt.receipt_id}#{item.path_or_handle}"
        return found


class InMemoryLineageStore:
    """``ContentLineageStore`` with the 0051 rules (one producer per subject, replay-safe)."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, LineageEntry]] = []
        self._ids: set[str] = set()

    async def record(self, scope: str, entries: Any, *, actor_ref: str, at: datetime) -> int:
        from mission_control.adapters.postgres.knowledge.lineage import lineage_id

        written = 0
        for entry in entries:
            key = lineage_id(entry)
            if key in self._ids:
                continue
            if entry.fact.role.value == "producer" and any(
                stored.fact.role.value == "producer"
                and stored.fact.subject_handle == entry.fact.subject_handle
                and stored_scope == scope
                for stored_scope, stored in self.entries
            ):
                raise ValueError("a subject has at most one producer")
            self._ids.add(key)
            self.entries.append((scope, entry))
            written += 1
        return written

    async def record_registration(
        self, scope: str, entries: Any, *, actor_ref: str, at: datetime
    ) -> int:
        # No await between validation and commit: matches the atomic registration transaction.
        from mission_control.adapters.postgres.knowledge.lineage import lineage_id

        pending = list(entries)
        handles = {entry.fact.subject_handle for entry in pending}
        producers = {
            entry.fact.subject_handle
            for saved_scope, entry in self.entries
            if saved_scope == scope and entry.fact.role.value == "producer"
        }
        for handle in handles:
            incoming = [entry for entry in pending if entry.fact.subject_handle == handle]
            identities = {(entry.subject_kind, entry.subject_digest) for entry in incoming}
            if len(identities) != 1 or any(entry.subject_digest is None for entry in incoming):
                raise ValueError("registration lineage requires one exact kind and digest")
            if any(
                entry.fact.role.value not in {"producer", "caller", "receipt"} for entry in incoming
            ):
                raise ValueError("registration lineage cannot assert other provenance roles")
            if any(
                (entry.subject_kind, entry.subject_digest) not in identities
                for saved_scope, entry in self.entries
                if saved_scope == scope and entry.fact.subject_handle == handle
            ):
                raise ValueError("registration lineage differs from immutable subject identity")
        written = 0
        for entry in pending:
            if entry.fact.role.value == "producer":
                if entry.fact.subject_handle in producers:
                    continue
                producers.add(entry.fact.subject_handle)
            key = lineage_id(entry)
            if key not in self._ids:
                self._ids.add(key)
                self.entries.append((scope, entry))
                written += 1
        return written

    async def facts(self, scope: str, subject_handle: str) -> list[Any]:
        return [
            entry.fact
            for stored_scope, entry in self.entries
            if stored_scope == scope and entry.fact.subject_handle == subject_handle
        ]


def read_intent_answer(
    envelope: OperationEnvelope,
    *,
    rows: Mapping[str, list[dict[str, Any]]] | None = None,
    errors: Mapping[str, str] | None = None,
    withheld: frozenset[str] = frozenset(),
    retained: Ref | None = None,
    knowledge_seq: int = 12,
    updated_at: str = "2026-10-31T10:00:00Z",
) -> KnowledgeReadIntentResult:
    """A consistent `knowledge-read-intent-result.v1` for the envelope's inline request: the KS
    operation id is a function of the request id (a replay answers the same id), each operation
    answers ``rows[opId]`` (default: one row naming the op), ``errors[opId]`` fails it, and an op
    in ``withheld`` keeps its digest but returns no body."""

    assert envelope.input is not None
    request = KnowledgeReadIntentRequest.model_validate(envelope.input.inlinePayload)
    operation_id = (
        "op-read_intent-"
        + digest_canonical(
            {
                "tenant": envelope.tenant,
                "operation": envelope.operation,
                "requestId": envelope.requestId,
            }
        )[7:39]
    )
    results = []
    for item in request.operations:
        query = getattr(item, "query", None) or getattr(item, "id", None)
        if errors and item.opId in errors:
            results.append(
                {
                    "opId": item.opId,
                    "kind": item.kind,
                    "query": query,
                    "status": "error",
                    "rowCount": 0,
                    "truncated": False,
                    "contentDigest": digest_canonical(None),
                    "bodyWithheld": False,
                    "error": {"code": errors[item.opId], "message": f"{item.opId} failed"},
                }
            )
            continue
        body = (rows or {}).get(item.opId, [{"op": item.opId, "n": 1}])
        document: dict[str, Any] = {
            "opId": item.opId,
            "kind": item.kind,
            "query": query,
            "status": "ok" if body else "empty",
            "rowCount": len(body),
            "truncated": False,
            "contentDigest": digest_canonical(body),
            "bodyWithheld": item.opId in withheld,
        }
        if item.opId not in withheld:
            document["columns"] = sorted({key for row in body for key in row})
            document["rows"] = body
        results.append(document)
    from mission_control.contracts.knowledge_protocol import ReadIntentOperationResult

    parsed = [ReadIntentOperationResult.model_validate(item) for item in results]
    at = request.atKnowledgeSeq if request.atKnowledgeSeq is not None else knowledge_seq
    return KnowledgeReadIntentResult.model_validate(
        {
            "schemaVersion": "knowledge-read-intent-result.v1",
            "operationId": operation_id,
            "snapshotId": "snap-" + operation_id[-12:],
            "snapshotDigest": read_intent_snapshot_digest(at, parsed),
            "knowledgeHead": {"knowledgeSeq": knowledge_seq, "updatedAt": updated_at},
            "atKnowledgeSeq": at,
            "contract": {"migrationHead": "20261031000000", "catalogVersion": "1.0.0"},
            "operations": results,
            "retainedRef": None if retained is None else retained.model_dump(mode="json"),
        }
    )


class InMemoryRetainedReadStore:
    """``RetainedReadStore`` with the 0052 rules: unique (scope, invocation, read ref), the
    readable-needs-digest CHECK (the dataclass), append-only."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], RetainedReadObservation] = {}
        self.actors: list[str] = []
        self.fail: Exception | None = None

    async def record(self, scope: str, rows: Any, *, actor_ref: str, at: datetime) -> int:
        if self.fail is not None:
            raise self.fail
        written = 0
        for row in rows:
            key = (scope, row.invocation_ref, row.read_observation_ref)
            if key in self.rows:
                continue
            self.rows[key] = row
            self.actors.append(actor_ref)
            written += 1
        return written

    async def observations(self, scope: str, invocation_ref: str) -> list[RetainedReadObservation]:
        return [
            row
            for (stored, invocation, _), row in self.rows.items()
            if stored == scope and invocation == invocation_ref
        ]


class InMemoryStaging:
    """``MissionFileStagingPort`` + durable reader over a dict (content addressed)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.corrupt_next: int = 0
        self.unreadable_next: int = 0
        # Item name suffix -> how many of its next reads fail (per item, not global).
        self.unreadable_items: dict[str, int] = {}
        self.staged: list[str] = []

    async def stage(self, *, request_scope: str, name: str, content: bytes, media_type: str) -> str:
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        stored = content
        if self.corrupt_next:
            self.corrupt_next -= 1
            stored = content + b"\x00corrupted"
        locator = f"mem://{request_scope}/{name}#{digest}:{len(content)}"
        self.objects[locator] = stored
        self.staged.append(locator)
        return locator

    async def retrieve(self, durable_ref: str) -> bytes:
        name = durable_ref.split("#", 1)[0].rsplit("/", 1)[-1]
        if self.unreadable_items.get(name):
            self.unreadable_items[name] -= 1
            raise OSError("object store unavailable")
        if self.unreadable_next:
            self.unreadable_next -= 1
            raise OSError("object store unavailable")
        return self.objects[durable_ref]


__all__ = [
    "AUDIENCE",
    "BINDING",
    "ISSUER",
    "REAL_BINDING_ENV",
    "Call",
    "FakeKnowledgeBinding",
    "InMemoryKnowledgeHandleStore",
    "InMemoryKnowledgeJournal",
    "InMemoryLineageStore",
    "InMemoryRetainedReadStore",
    "InMemoryStaging",
    "InMemorySubmissionStore",
    "InMemoryTransferPlanStore",
    "Issuer",
    "ParityTarget",
    "RecordingMinter",
    "SteppingClock",
    "StoredPackage",
    "describe_document",
    "http_client_over",
    "knowledge_http_app",
    "model_content",
    "model_report",
    "parity_target",
    "read_intent_answer",
    "real_binding_configured",
    "report_package",
    "stamp",
]


RECORD_KINDS = {"fragments": "fragment", "assertions": "assertion", "supportSets": "support_set"}


def fresh_registration(template: Mapping[str, Any], suffix: str) -> dict[str, Any]:
    """A `research-report/v2` registration with every record id made unique by ``suffix``.

    Records refer to each other by K01 `Ref` (id + canonical record digest, research-core
    `recordRef`), so after renaming the task, fragment, assertion and support-set ids each
    dependent `Ref` is recomputed until the document is stable. Artifact refs (content
    digests) and template ids (obligations, sections, premises) are unchanged. An empty
    ``suffix`` reproduces the template byte for byte.
    """

    import copy

    document = copy.deepcopy(dict(template))
    records: dict[tuple[str, str], dict[str, Any]] = {}
    renamed: dict[str, str] = {}
    task = document["task"]
    for key, kind in (("task", "task"), *RECORD_KINDS.items()):
        for record in [task] if key == "task" else document[key]:
            new = f"{record['id']}-{suffix}" if suffix else record["id"]
            renamed[record["id"]] = new
            record["id"] = new
            records[(kind, new)] = record
    document["report"]["reportId"] = (
        f"report-mc-{suffix}" if suffix else document["report"]["reportId"]
    )

    def visit(node: Any) -> bool:
        changed = False
        if isinstance(node, dict):
            if {"kind", "id", "version", "digest", "tenant", "binding"} <= set(node):
                ident = renamed.get(node["id"], node["id"])
                target = records.get((str(node["kind"]), str(ident)))
                if target is not None and target is not node:
                    digest = digest_canonical(target)
                    if node["id"] != ident or node["digest"] != digest:
                        node["id"], node["digest"] = ident, digest
                        changed = True
            for value in node.values():
                changed |= visit(value)
        elif isinstance(node, list):
            for value in node:
                changed |= visit(value)
        return changed

    for _ in range(16):
        if not visit(document):
            return document
    raise AssertionError("registration references did not converge")


def model_content(registration: Mapping[str, Any]) -> dict[str, Any]:
    """W1 D1: the model-shaped content of a complete registration (what a producer submits).

    The host binds the producer and computes every in-registration digest, so assertions lose
    their ``producer``, support sets their ``qualifiersDigest``, text-quote fragments their
    selected digest and size, and every reference to a record of the same registration becomes
    its id; references outside it (artifacts, rubric, policy) stay complete.
    """

    import copy

    document = copy.deepcopy(dict(registration))
    local = {
        (kind, str(record["id"]))
        for key, kind in RECORD_KINDS.items()
        for record in document.get(key, [])
    }
    for assertion in document.get("assertions", []):
        assertion.pop("producer", None)
    for support in document.get("supportSets", []):
        target = support.get("assertion")
        if isinstance(target, dict) and ("assertion", str(target.get("id"))) in local:
            support.pop("qualifiersDigest", None)  # an external assertion keeps its own
    for fragment in document.get("fragments", []):
        if fragment.get("selector", {}).get("kind") == "text_quote":
            fragment.pop("selectedDigest", None)
            fragment.pop("selectedSize", None)

    def visit(node: Any) -> Any:
        if isinstance(node, dict):
            if {"kind", "id", "version", "digest", "tenant", "binding"} <= set(node) and (
                str(node["kind"]),
                str(node["id"]),
            ) in local:
                return str(node["id"])
            return {key: visit(value) for key, value in node.items()}
        if isinstance(node, list):
            return [visit(value) for value in node]
        return node

    return {key: visit(value) for key, value in document.items()}


def _artifact(name: str, kind: str = "artifact") -> dict[str, str]:
    return {
        "kind": kind,
        "id": name,
        "version": "artifact.v1",
        "digest": digest_bytes(name.encode("utf-8")),
    }


def model_report(
    report_id: str,
    revision: int = 1,
    *,
    use: str | None = None,
    audience: str | None = None,
    quote: str = "Mistral 7B is a 7-billion-parameter language model.",
) -> dict[str, Any]:
    """A minimal model-shaped `research-report/v2` content (W1 D1): ids, no digests, no origin.

    External references (the task's original artifact, rubric and policy; the fragment's capture
    and representation) are complete, as the host handed them to the producer.
    """

    task: dict[str, Any] = {
        "id": f"task-{report_id}",
        "domain": "engineering",
        "originalTask": _artifact(f"task-input-{report_id}"),
        "obligations": [
            {
                "id": "finding.size",
                "description": "State the size.",
                "weight": 10000,
                "required": True,
            }
        ],
        "asOf": "2026-10-28T00:00:00Z",
        "permittedMedia": ["text_markdown"],
        "rubric": _artifact("rubric-engineering", "rubric"),
        "policy": _artifact("policy-ai-engineer", "policy"),
        "minimumRisk": "medium",
        "limits": {
            "calls": 20,
            "tokens": 300000,
            "costUsd": "1",
            "deadline": "2026-11-30T00:00:00Z",
        },
    }
    if use is not None:
        task["use"] = use
    if audience is not None:
        task["audience"] = audience
    fragment = f"frag-{report_id}"
    assertion = f"asr-{report_id}"
    claim = {
        "type": "claim",
        "occurrenceId": f"occ-{report_id}",
        "assertion": assertion,
        "text": "Mistral 7B has 7 billion parameters",
        "obligations": ["finding.size"],
        "attribution": None,
    }
    paragraph = {
        "type": "paragraph",
        "id": "p1",
        "inlines": [claim, {"type": "citation", "label": "c1", "fragment": fragment}],
        "excludedReason": None,
    }
    return {
        "task": task,
        "fragments": [
            {
                "id": fragment,
                "sourceVersion": "arxiv-2310.06825@2026-10-28",
                "capture": _artifact("capture-arxiv-2310.06825"),
                "representation": _artifact("representation-arxiv-2310.06825"),
                "selector": {
                    "kind": "text_quote",
                    "value": quote,
                    "resolverVersion": "text-quote.v3",
                    "normalizationVersion": "text-norm.v1",
                },
                "context": {
                    "header": "Mistral 7B, abstract",
                    "footnotes": [],
                    "surroundingDigest": None,
                },
                "parserLineage": ["frozen-quote.v1"],
                "captureCompleteness": "complete",
                "access": {"rights": "public", "limits": []},
                "originFamily": None,
            }
        ],
        "assertions": [
            {
                "id": assertion,
                "logicalId": "mistral-7b-size",
                "proposition": "Mistral 7B has 7 billion parameters.",
                "kind": "source_report",
                "value": {"type": "quantity", "amount": "7000000000", "unit": "parameters"},
                "subject": "mistral-7b",
                "object": None,
                "qualifiers": {
                    "profile": "engineering.v2",
                    "entity": "mistral-7b",
                    "unit": "parameters",
                },
                "riskReasons": [],
            }
        ],
        "supportSets": [
            {
                "id": f"ss-{report_id}",
                "assertion": assertion,
                "provenance": "declared_citation",
                "required": [{"premise": "size", "evidence": [fragment], "derivedFrom": []}],
                "contrary": [],
            }
        ],
        "report": {
            "reportId": report_id,
            "revision": revision,
            "kind": "evidence_report",
            "structuredBody": {
                "sections": [
                    {
                        "id": "findings",
                        "heading": [{"type": "text", "text": "Findings"}],
                        "headingExcludedReason": None,
                        "blocks": [paragraph],
                    }
                ]
            },
        },
    }

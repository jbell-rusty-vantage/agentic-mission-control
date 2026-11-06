"""Ports of the knowledge gateway, submission, assessment and delivery seams (Sprint V M02-M05).

``KnowledgeBindingClient`` is the out-of-process application binding (Knowledge Services
executor, or a domain BFF speaking the same protocol). It speaks K01
``ks.knowledge_operation.v2`` only; no SDK types cross it. The executor contract, by K01
operation name (HTTP routes in ``adapters/knowledge/http_client.py``):

* ``knowledge.apply`` / ``report.register`` / ``knowledge.read`` / ``report.*`` /
  ``verify.claims``: ``invoke(envelope, credential)``; an effectful operation returns its
  ``operation-receipt.v2`` synchronously or an ``operation-handle.v2`` to poll; the
  non-effect handle operations (``report.assess``, ``report.derive``, ``verify.claims``,
  ``knowledge.read``) return a handle.
* ``operation.get``: ``operation_get(handle, credential)`` -> ``operation-status.v2``
  (bounded ``retryAfterMs``).
* ``operation.cancel``: ``operation_cancel(handle, cancel_request_id, credential)``,
  idempotent by request id; stops new work, never invents a rollback.
* ``receipt.get``: ``receipt(effect_key, credential)`` -> ``receipt-lookup.v2``
  (``found`` / ``not_found`` / ``unresolved``).
* ``knowledge.describe``: ``describe(credential)`` -> ``binding-descriptor.v2``.

A typed refusal from the binding raises :class:`KnowledgeProtocolRefusal`; a transport failure
(no answer, connection loss, timeout, or a 5xx without a protocol body) raises
:class:`KnowledgeTransportError`, after which the host cannot know whether a dispatched effect
happened.

The credential is an opaque bearer string minted by :class:`CredentialMinter` per dispatch.
Ports never log, persist or embed it; :class:`MintedCredential` hides it from ``repr``.

K01 has no byte route for an exact read: ``knowledge.read`` resolves an exact revision to a
``resultRef`` and :class:`ExactContentReader` fetches the frozen report package bytes for that
exact ref (M04). The Knowledge Services executor serves them through its extension route
``GET /knowledge-operation/v2/artifacts/{id}?digest=`` (one credential per request).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from mission_control.contracts.knowledge_assessment import CredentialEvaluation
from mission_control.contracts.knowledge_protocol import (
    KnowledgePlanPreview,
    KnowledgeReadIntentResult,
    OperationEnvelope,
    OperationHandle,
    OperationName,
    Origin,
    Ref,
)
from mission_control.contracts.knowledge_protocol_results import (
    BindingDescriptor,
    CredentialClaims,
    CredentialRecovery,
    OperationReceipt,
    OperationStatus,
    ProtocolError,
    ReceiptFound,
    ReceiptNotFound,
    ReceiptUnresolved,
)
from mission_control.domain.knowledge.effects import JournalState
from mission_control.domain.knowledge.lineage import LineageFact
from mission_control.domain.knowledge.reads import RetainedReadObservation

# A bearer token, or a source that mints a fresh single-use one per transmission (K07 `jti`).
type Credential = str | Callable[[], str]

# ---------------------------------------------------------------- binding


class KnowledgeTransportError(RuntimeError):
    """The binding did not answer; a dispatched effect may or may not have happened."""


class KnowledgeProtocolRefusal(RuntimeError):
    """The binding answered with a typed ``protocol-error.v2``."""

    def __init__(self, error: ProtocolError) -> None:
        super().__init__(f"{error.code}: {error.message}")
        self.error = error


class KnowledgeBindingClient(Protocol):
    async def invoke(
        self, envelope: OperationEnvelope, credential: str
    ) -> OperationHandle | OperationReceipt | KnowledgePlanPreview | KnowledgeReadIntentResult: ...

    async def operation_get(
        self, handle: OperationHandle, credential: Credential
    ) -> OperationStatus: ...

    async def operation_cancel(
        self, handle: OperationHandle, cancel_request_id: str, credential: Credential
    ) -> OperationStatus: ...

    async def receipt(
        self, effect_key: str, credential: Credential
    ) -> ReceiptFound | ReceiptNotFound | ReceiptUnresolved: ...

    async def describe(self, credential: Credential) -> BindingDescriptor: ...


@dataclass(frozen=True)
class ReportPackage:
    """The frozen export of one exact report revision (design §8 "report export").

    ``manifest`` is the index document whose canonical digest is the read's ``resultRef``
    digest: it names the report ref, the body and ledger digests and byte counts, and the
    selected assertion/evidence handles. ``body`` and ``ledger`` are the exact bytes.
    """

    result_ref: Ref
    manifest: Mapping[str, Any]
    body: bytes
    ledger: bytes


class ExactContentReader(Protocol):
    async def fetch(self, result_ref: Ref, credentials: Callable[[], str]) -> ReportPackage:
        """The package for exactly ``result_ref``; never a newer or older revision.

        ``credentials`` mints a fresh single-use ``knowledge.read`` credential per request.
        """
        ...


# ---------------------------------------------------------------- credentials


@dataclass(frozen=True)
class CredentialRequest:
    """Everything one dispatch credential is bound to (K01 ``credential-claims.v2``).

    ``recovery`` is the explicit host recovery authority the dispatch presents: read-only for a
    receipt lookup after the invocation ended (``recovery`` origin), effect-scoped for a new
    attempt re-dispatching one exact uncertain effect (the new attempt is ``origin``).
    """

    audience: str
    binding: str
    origin: Origin
    operations: tuple[OperationName, ...]
    dispatch_id: str
    effect_key: str | None = None
    bound_effect_digest: str | None = None
    recovery: CredentialRecovery | None = None
    # WI-03: the evaluator grant of a separate judge, auditor or reviewer invocation.
    evaluation: CredentialEvaluation | None = None


@dataclass(frozen=True)
class MintedCredential:
    claims: CredentialClaims
    token: str = field(repr=False)


class CredentialMinter(Protocol):
    """Mints one short-lived (300 s) credential per dispatch, immediately before it.

    Claims carry the issuer, exact audience, tenant, application, current origin, operations,
    effect key/digest (effectful calls), dispatch id, a unique ``jti`` and the requested
    recovery authority. A minted credential is never reused for another dispatch.
    """

    @property
    def issuer(self) -> str: ...

    def mint(self, request: CredentialRequest) -> MintedCredential: ...


# ---------------------------------------------------------------- invocation identity


class InvocationLocator(Protocol):
    """The ledger identity of one live attempt (provenance slice 1, OVE-204).

    ``run_key`` is the run's public id (``mission_run.run_key``, the binding's ``run_id``);
    ``unit_key`` is the attempt's runtime unit key (``activation.activation_key``). Returns
    ``(mission_id, activation_id)``: the run's ledger ``mission_run.mission_id`` and the
    ``activation.activation_id`` attempt admission recorded for that unit (``None`` without a
    unit key or without that row). A run absent from the request scope raises
    :class:`~mission_control.domain.knowledge.origin.MissionIdentityUnavailable`: no origin is
    ever built from a stand-in mission id.
    """

    async def locate(
        self, request_scope: str, run_key: str, unit_key: str | None
    ) -> tuple[str, str | None]: ...


# ---------------------------------------------------------------- journal


@dataclass(frozen=True)
class JournalCoordinates:
    """The invoking attempt's Mission Control coordinates (never the remote handle)."""

    mission_id: str
    run_id: str
    activation_id: str | None
    operation_ref: str
    operation_attempt: int
    execution_generation: int
    lane_profile: str | None = None
    unit_key: str | None = None


@dataclass(frozen=True)
class PrepareRequest:
    scope: str
    effect_key: str
    semantic_payload_digest: str
    bound_effect_digest: str
    originating_origin: Origin
    current_caller_origin: Origin
    coordinates: JournalCoordinates
    capability_pin: str
    binding_id: str
    actor_ref: str


@dataclass(frozen=True)
class JournalRecord:
    knowledge_operation_id: str
    effect_key: str
    semantic_payload_digest: str
    bound_effect_digest: str
    originating_origin: Origin
    current_caller_origin: Origin
    capability_pin: str
    binding_id: str
    state: JournalState
    version: int
    reconciled: bool = False
    dispatch_id: str | None = None
    envelope_digest: str | None = None
    protocol_version: str | None = None
    operation_id: str | None = None
    terminal_receipt_ref: str | None = None
    receipt_digest: str | None = None
    refusal_code: str | None = None
    # The host recovery grant the latest dispatch was sent under (a later attempt), if any.
    recovery_authority_ref: str | None = None
    # The attempt that prepared the row (for host recovery grants of later attempts).
    operation_ref: str | None = None
    operation_attempt: int | None = None


@dataclass(frozen=True)
class Settlement:
    state: JournalState
    terminal_receipt_ref: str | None = None
    receipt_digest: str | None = None
    refusal_code: str | None = None
    reconciled: bool = False


class JournalVersionConflict(RuntimeError):
    """Another writer advanced the journal row first (compare-and-set lost)."""


class KnowledgeJournal(Protocol):
    """Host journal of one logical knowledge effect per scoped effect key.

    ``prepare`` is race-safe admission: it returns the existing row for the key or inserts a
    ``prepared`` one, and raises :class:`~mission_control.domain.knowledge.effects.EffectConflict`
    for the same key with a different bound effect. Every other write is a compare-and-set on
    ``expected_version``; the store appends one transition per version.
    """

    async def prepare(self, request: PrepareRequest) -> JournalRecord: ...

    async def lookup(self, scope: str, effect_key: str) -> JournalRecord | None: ...

    async def open_for_attempt(
        self, scope: str, *, run_id: str, operation_ref: str, operation_attempt: int
    ) -> list[JournalRecord]:
        """Unsettled rows (prepared, dispatched, uncertain) one attempt prepared."""
        ...

    async def open_for_operation(
        self, scope: str, *, run_id: str, operation_ref: str
    ) -> list[JournalRecord]:
        """Unsettled rows of every attempt of one operation of one run."""
        ...

    async def dispatch(
        self,
        scope: str,
        effect_key: str,
        *,
        expected_version: int,
        dispatch_id: str,
        envelope_digest: str,
        protocol_version: str,
        caller: Origin,
        at: datetime,
        recovery_authority_ref: str | None = None,
    ) -> JournalRecord: ...

    async def record_handle(
        self, scope: str, effect_key: str, *, expected_version: int, operation_id: str, at: datetime
    ) -> JournalRecord: ...

    async def settle(
        self,
        scope: str,
        effect_key: str,
        *,
        expected_version: int,
        settlement: Settlement,
        at: datetime,
    ) -> JournalRecord: ...

    async def mark_uncertain(
        self, scope: str, effect_key: str, *, expected_version: int, at: datetime
    ) -> JournalRecord: ...

    async def transitions(
        self, scope: str, effect_key: str
    ) -> list[tuple[JournalState | None, JournalState]]: ...


# ---------------------------------------------------------------- durable handles (1.6.0)


@dataclass(frozen=True)
class HandleCandidate:
    """A remote handle the host received (``knowledge_operation_handle``, release 1.6.0)."""

    scope: str
    binding_id: str
    operation: OperationName
    request_id: str
    handle: OperationHandle
    coordinates: JournalCoordinates
    invocation_ref: str
    caller_origin: Origin
    actor_ref: str
    at: datetime
    effect_key: str | None = None
    subject_ref: str | None = None


@dataclass(frozen=True)
class HandleRecord:
    handle_id: str
    binding_id: str
    operation: str
    request_id: str
    handle: OperationHandle
    invocation_ref: str
    caller_origin: Origin
    state: str
    remote_revision: int
    version: int
    effect_key: str | None = None
    subject_ref: str | None = None
    cancel_request_id: str | None = None
    pending_review_ref: str | None = None
    result_ref: Ref | None = None
    error_code: str | None = None
    unresolved_effects: tuple[Mapping[str, Any], ...] = ()

    @property
    def terminal(self) -> bool:
        return self.state in {"succeeded", "partial", "held", "rejected", "failed", "cancelled"}


class KnowledgeHandleStore(Protocol):
    """Durable remote handles of non-effect (and effect) handle operations.

    ``record`` is idempotent per (scope, binding, remote operation id). ``observe`` applies a
    remote status only when its revision is newer (a stale poll never regresses a handle) and
    the K01 edge is legal. ``request_cancel`` stores the first cancel request id; a later one
    is a no-op returning the stored record.
    """

    async def record(self, candidate: HandleCandidate) -> HandleRecord: ...

    async def get(self, scope: str, binding_id: str, operation_id: str) -> HandleRecord | None: ...

    async def observe(
        self, scope: str, binding_id: str, status: OperationStatus, *, at: datetime
    ) -> HandleRecord: ...

    async def request_cancel(
        self,
        scope: str,
        binding_id: str,
        operation_id: str,
        cancel_request_id: str,
        *,
        at: datetime,
    ) -> HandleRecord: ...

    async def open_for_invocation(self, scope: str, invocation_ref: str) -> list[HandleRecord]: ...

    async def open_for_run(self, scope: str, run_id: str) -> list[HandleRecord]:
        """Every open handle of a run, whichever attempt started it (run-level stop)."""
        ...


# ---------------------------------------------------------------- submissions


class SubmissionConflict(RuntimeError):
    """Same invocation, obligation and submission key with a different selection (MCE02)."""


class SubmissionClosed(RuntimeError):
    """The invocation is already finalized; no further submission is accepted."""


@dataclass(frozen=True)
class SubmissionCandidate:
    scope: str
    run_id: str
    operation_ref: str
    operation_attempt: int
    execution_generation: int
    invocation_ref: str
    obligation_id: str
    submission_key: str
    selection: dict[str, Any]
    selection_digest: str
    actor_ref: str
    at: datetime
    unit_key: str | None = None


@dataclass(frozen=True)
class SubmissionRecord:
    submission_id: str
    invocation_ref: str
    obligation_id: str
    submission_key: str
    revision: int
    selection_digest: str
    assessment_state: str
    selection: Mapping[str, Any] = field(default_factory=dict)
    version: int = 1
    assessment_operation_id: str | None = None
    assessment_binding: str | None = None
    assessment_ref: str | None = None
    assessment_digest: str | None = None


@dataclass(frozen=True)
class FinalizationCandidate:
    scope: str
    run_id: str
    operation_ref: str
    operation_attempt: int
    execution_generation: int
    invocation_ref: str
    outcome: str
    submission_ids: tuple[str, ...]
    report: dict[str, Any]
    report_digest: str
    actor_ref: str
    at: datetime
    outcome_basis: str = "submission_coverage"


@dataclass(frozen=True)
class FinalizationRecord:
    finalization_id: str
    invocation_ref: str
    outcome: str
    submission_ids: tuple[str, ...]
    report: dict[str, Any]
    report_digest: str
    outcome_basis: str = "submission_coverage"


class OutputSubmissionStore(Protocol):
    async def record_selection(self, candidate: SubmissionCandidate) -> SubmissionRecord:
        """Legacy report selection of a run without registered promises (M04 delivery reads
        it); idempotent per (invocation, obligation, key); next revision for a new key."""
        ...

    async def list_for_invocation(
        self, scope: str, invocation_ref: str
    ) -> list[SubmissionRecord]: ...

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
        """``pending -> assessing`` naming the independent ``report.assess`` handle (1.6.0)."""
        ...

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
        """``assessing -> assessed | held | rejected`` from the service's terminal status."""
        ...

    async def finalize(self, candidate: FinalizationCandidate) -> FinalizationRecord:
        """The one finalization per invocation; a repeat returns the recorded one."""
        ...


# ---------------------------------------------------------------- lineage (0051)


@dataclass(frozen=True)
class LineageEntry:
    """One provenance fact to persist, with what joins it to the journal and stores."""

    fact: LineageFact
    subject_kind: str  # artifact | output | report | assertion
    subject_digest: str | None = None
    run_id: str | None = None
    knowledge_operation_id: str | None = None
    effect_key: str | None = None


class ContentLineageStore(Protocol):
    """Append-only content lineage; a replayed fact is the same row."""

    async def record(
        self, scope: str, entries: Sequence[LineageEntry], *, actor_ref: str, at: datetime
    ) -> int: ...

    async def record_registration(
        self, scope: str, entries: Sequence[LineageEntry], *, actor_ref: str, at: datetime
    ) -> int:
        """Atomically retain the first producer of identical immutable registered content.

        Verify subject kind/digest before preserving its producer; append caller and receipt
        facts. Conflicting content refuses the entire write. Ordinary record remains strict.
        """
        ...

    async def facts(self, scope: str, subject_handle: str) -> list[LineageFact]: ...


# ---------------------------------------------------------------- retained reads (read_intent)


class RetainedReadStore(Protocol):
    """Append-only ``retained_read_observation`` rows (release 1.5.0, 0052; OVE-204 slice 4).

    ``record`` writes each observation once: a replayed observation (same invocation and
    read observation ref) is the same row and is not written again. Returns the rows written.
    """

    async def record(
        self,
        scope: str,
        rows: Sequence[RetainedReadObservation],
        *,
        actor_ref: str,
        at: datetime,
    ) -> int: ...

    async def observations(
        self, scope: str, invocation_ref: str
    ) -> list[RetainedReadObservation]: ...


# ---------------------------------------------------------------- use decisions (apply)


@dataclass(frozen=True)
class RecordedUseDecision:
    """An exact use decision the host recorded for one native plan (integrator decision
    2026-10-25): the agent names only its handle; the host supplies the exact use.

    ``plan`` is the native intent the decision binds (an AI Engineer ingestion intent or a
    Biotech knowledge intent); ``bound_effect_digest`` is the plan-level digest the decision
    binds; ``proposals_ref`` the derived proposals document handle it decided over, if any.
    """

    handle: str
    binding_id: str
    tenant_id: str
    use_decision_id: str
    bound_effect_digest: str
    processed_epoch: int
    plan: Mapping[str, Any]
    normalized_values_digest: str | None = None
    proposals_ref: str | None = None
    # The exact use and audience the decision admits (declared on the apply envelope).
    use: str | None = None
    audience: str | None = None
    # Native write (0072): the exact report revision decided over (`<report handle>#<digest>`)
    # and the invocation whose origin the bound digest binds (the only one that may apply it).
    subject_ref: str | None = None
    invocation_ref: str | None = None
    # The exact KS decision record digest (the resolution names the decision exactly).
    decision_digest: str | None = None


class UseDecisionStore(Protocol):
    """Host-recorded use decisions by handle, scoped by request scope."""

    async def get(self, scope: str, handle: str) -> RecordedUseDecision | None: ...

    async def for_invocation(
        self, scope: str, invocation_ref: str
    ) -> tuple[RecordedUseDecision, ...]:
        """The plan-level decisions recorded for exactly this invocation (0072), by handle."""
        ...


class UseDecisionRecorder(UseDecisionStore, Protocol):
    """The durable store the trusted bridge records decisions into (release 1.7.0, 0059)."""

    async def record(
        self, scope: str, decision: RecordedUseDecision, *, actor_ref: str, at: datetime
    ) -> RecordedUseDecision: ...


__all__ = [
    "ContentLineageStore",
    "CredentialMinter",
    "CredentialRequest",
    "ExactContentReader",
    "FinalizationCandidate",
    "FinalizationRecord",
    "HandleCandidate",
    "HandleRecord",
    "InvocationLocator",
    "JournalCoordinates",
    "JournalRecord",
    "JournalVersionConflict",
    "KnowledgeBindingClient",
    "KnowledgeHandleStore",
    "KnowledgeJournal",
    "KnowledgeProtocolRefusal",
    "KnowledgeTransportError",
    "LineageEntry",
    "MintedCredential",
    "OutputSubmissionStore",
    "PrepareRequest",
    "RecordedUseDecision",
    "ReportPackage",
    "RetainedReadObservation",
    "RetainedReadStore",
    "Settlement",
    "SubmissionCandidate",
    "SubmissionClosed",
    "SubmissionConflict",
    "SubmissionRecord",
    "UseDecisionRecorder",
    "UseDecisionStore",
]

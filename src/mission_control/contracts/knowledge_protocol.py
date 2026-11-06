"""Knowledge Operation Protocol (K01) wire models and digests for the Mission Control side.

The authority is Knowledge Services' ``@aiengineer/knowledge-operation-protocol``
(``ks.knowledge_operation.v2``); its JSON Schemas and golden vectors are mirrored under
``tests/fixtures/knowledge_protocol``. These are the Python validation models the design asks
the consumer to own (SPRINT-V-DESIGN §2.1, §9 "K01 golden contracts"). They never import
TypeScript and never relax a rule: unknown fields are refused, versions are literal, origins
with template coordinates are refused, and canonical bytes follow ``kop-canonical-json.v1``.
Every TypeScript ``superRefine`` rule of K01 is reproduced as a model validator and every
pattern the published JSON Schemas carry is a constrained type here: no ``Any`` crosses the
wire (inline payloads and details are :data:`JsonDocument`, integers only).
``tests/conformance/test_knowledge_protocol_negative.py`` feeds TS-invalid documents to these
models and compares each model's field set with its published schema.

``kop-canonical-json.v1`` differs from :mod:`mission_control.contracts.canonical`: no NFC
normalization, integers only, no datetime/Decimal coercion, lone surrogates refused. The two
never share a digest space.

Field names are the wire names (camelCase) on purpose: no handwritten semantic renaming.
"""

# ruff: noqa: N815

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PROTOCOL_VERSION = "ks.knowledge_operation.v2"
CANONICALIZATION = "kop-canonical-json.v1"

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$")]
ScopeId = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,119}$")]
SchemaVersion = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]*\.v[0-9]+$")]
Instant = Annotated[
    str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d*[1-9])?Z$")
]
SafeInt = Annotated[int, Field(ge=0, le=2**53 - 1)]
PositiveInt = Annotated[int, Field(ge=1, le=2**53 - 1)]
NativeVersion = Annotated[str, StringConstraints(pattern=r"^v[0-9]+$")]
UsdAmount = Annotated[str, StringConstraints(pattern=r"^(0|[1-9]\d*)(\.\d{1,6})?$")]
# An operation name, `report_kind:<kind>`, `media:<type>` or `<guarantee>:<value>`.
CapabilityName = Annotated[
    str,
    StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{0,79}(:[a-zA-Z0-9_./+-]{1,80})?$"),
]
# Protocol-carried JSON (K01 `JsonDocumentSchema`): strings, integers, booleans, null, arrays
# and string-keyed objects; never a float, because canonical bytes carry no floats.
type JsonDocument = str | int | bool | None | list[JsonDocument] | dict[str, JsonDocument]
# The kinds a qualified handle can name (K01 `REF_KINDS`).
RefKind = Literal[
    "task",
    "artifact",
    "assertion",
    "occurrence",
    "fragment",
    "support_set",
    "observation",
    "report",
    "report_kind",
    "rubric",
    "policy",
    "method",
    "mapping",
    "verification_run",
    "run_manifest",
    "use_decision",
    "adjudication",
    "receipt",
    "effect",
    "operation",
]


class CanonicalizationError(ValueError):
    """A value outside the canonical value space (float, lone surrogate, undefined member)."""


def _refuse_lone_surrogate(value: str, path: str) -> None:
    # A Python str holds a surrogate code point only when it is unpaired: a JSON escaped pair
    # decodes to one astral character. K01 refuses it (TS `CANONICAL_VALUE_UNSUPPORTED`): such
    # a string has no UTF-8 bytes, so it can have no canonical digest.
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise CanonicalizationError(f"lone surrogate is not canonical at {path}")


def _canonicalize(value: Any, path: str) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if not -(2**53 - 1) <= value <= 2**53 - 1:
            raise CanonicalizationError(f"only safe integers are canonical at {path}")
        return str(value)
    if isinstance(value, float):
        raise CanonicalizationError(f"only safe integers are canonical; got float at {path}")
    if isinstance(value, str):
        return _json_string(value, path)
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="json"), path)
    if isinstance(value, list | tuple):
        items = (_canonicalize(item, f"{path}[{index}]") for index, item in enumerate(value))
        return "[" + ",".join(items) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalizationError(f"object keys must be strings at {path}")
        for key in value:
            _refuse_lone_surrogate(key, f"{path}.<key>")
        # JavaScript sorts keys by UTF-16 code units; the UTF-16-BE encoding sorts the same way
        # (an astral key, encoded as a surrogate pair 0xD800.., sorts before U+E000..U+FFFF).
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        parts = [
            f"{_json_string(key, path)}:{_canonicalize(value[key], f'{path}.{key}')}"
            for key in keys
        ]
        return "{" + ",".join(parts) + "}"
    raise CanonicalizationError(f"unsupported {type(value).__name__} at {path}")


def _json_string(value: str, path: str = "$") -> str:
    # Exactly what JSON.stringify writes: non-ASCII unescaped, \b \f \n \r \t short escapes,
    # other control characters as \u00XX lowercase. Python's json module agrees on all of these.
    _refuse_lone_surrogate(value, path)
    return json.dumps(value, ensure_ascii=False)


def canonical_json(value: Any) -> str:
    """Canonical ``kop-canonical-json.v1`` text: UTF-16-sorted keys, compact, integers only."""

    return _canonicalize(value, "$")


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_canonical(value: Any) -> str:
    return digest_bytes(canonical_json(value).encode("utf-8"))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MissionCoordinates(_Strict):
    missionId: Id
    runId: Id
    activationId: Id | None
    operationId: Id
    operationAttempt: SafeInt
    executionGeneration: SafeInt
    lane: Name


OriginKind = Literal["mission_invocation", "standalone", "recovery", "durable_worker"]


class Origin(_Strict):
    kind: OriginKind
    installationId: ScopeId
    applicationId: Name
    tenantId: ScopeId
    issuer: Name
    subject: Id
    mission: MissionCoordinates | None
    recoveryAuthorityRef: Id | None
    invocationId: Id
    authenticatedAt: Instant

    @model_validator(mode="after")
    def _rules(self) -> Origin:
        if self.kind == "mission_invocation" and self.mission is None:
            raise ValueError("mission_invocation requires mission coordinates")
        if (self.kind == "recovery") != (self.recoveryAuthorityRef is not None):
            raise ValueError("only a recovery origin carries recovery authority, and it must")
        if self.mission is not None and self.mission.operationId.startswith("manifest-template/"):
            raise ValueError("template coordinates are not a live invocation (E01)")
        return self

    def identity(self) -> dict[str, Any]:
        """Everything except the per-authentication fields (matches ``originIdentity`` in K01)."""

        data = self.model_dump(mode="json")
        data.pop("authenticatedAt")
        data.pop("invocationId")
        return data

    def digest(self) -> str:
        return digest_canonical(self.identity())


class EffectBinding(_Strict):
    effectKey: Id
    semanticPayloadDigest: Digest
    originatingOrigin: Origin
    boundEffectDigest: Digest
    canonicalization: Literal["kop-canonical-json.v1"]


def bound_effect_digest(native_payload: bytes, originating_origin: Origin) -> str:
    return digest_canonical(
        {
            "canonicalization": CANONICALIZATION,
            "payloadDigest": digest_bytes(native_payload),
            "originatingOrigin": originating_origin.identity(),
        }
    )


def bind_effect(
    effect_key: str, native_payload: bytes, originating_origin: Origin
) -> EffectBinding:
    return EffectBinding(
        effectKey=effect_key,
        semanticPayloadDigest=digest_bytes(native_payload),
        originatingOrigin=originating_origin,
        boundEffectDigest=bound_effect_digest(native_payload, originating_origin),
        canonicalization="kop-canonical-json.v1",
    )


class OperationHandle(_Strict):
    protocolVersion: Literal["ks.knowledge_operation.v2"]
    tenant: ScopeId
    application: Name
    binding: Name
    operationId: Id


OperationState = Literal[
    "queued",
    "running",
    "waiting_review",
    "cancelling",
    "succeeded",
    "partial",
    "held",
    "rejected",
    "failed",
    "cancelled",
]
TERMINAL_STATES: frozenset[str] = frozenset(
    {"succeeded", "partial", "held", "rejected", "failed", "cancelled"}
)
DOMAIN_TERMINAL_STATES: frozenset[str] = frozenset({"succeeded", "partial", "held", "rejected"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelling", "cancelled", "failed", "rejected"}),
    "running": frozenset(
        {"waiting_review", "cancelling", "succeeded", "partial", "held", "rejected", "failed"}
    ),
    "waiting_review": frozenset(
        {"running", "cancelling", "held", "rejected", "succeeded", "partial", "failed"}
    ),
    "cancelling": frozenset({"cancelled", "succeeded", "partial", "held", "rejected", "failed"}),
}


def can_transition(current: str, nxt: str) -> bool:
    return nxt in _TRANSITIONS.get(current, frozenset())


def can_reach(current: str, target: str) -> bool:
    """A forward path of legal K01 edges leads from ``current`` to ``target``.

    A poller sees remote statuses, not every edge: ``waiting_review`` observed, then
    ``cancelled`` (through the unobserved ``cancelling``) is a legal forward observation.
    """

    seen = {current}
    frontier = [current]
    while frontier:
        state = frontier.pop()
        for nxt in _TRANSITIONS.get(state, frozenset()):
            if nxt == target:
                return True
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    return False


class Ref(_Strict):
    kind: RefKind
    id: Id
    version: SchemaVersion
    digest: Digest
    tenant: ScopeId
    binding: Name


SELECTED_READ_CONTRACT: Final = {"name": "selected-report-read", "version": "v2"}
REPORT_PACKAGE_SCHEMA: Final = "research-report-package.v2"
READ_PURPOSE_PATTERN: Final = r"^[a-z][a-z0-9_]{0,63}$"
MAX_SELECTED_MEMBERS: Final = 512


class _Wire(BaseModel):
    """Closed wire model validated from JSON documents (lists accepted for tuples)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RevisionSelection(_Wire):
    mode: Literal["revision"] = "revision"


class MembersSelection(_Wire):
    mode: Literal["members"] = "members"
    assertions: tuple[Ref, ...] = ()
    evidence: tuple[Ref, ...] = ()

    @model_validator(mode="after")
    def _exact_handles(self) -> MembersSelection:
        for kind, handles in (("assertion", self.assertions), ("fragment", self.evidence)):
            if any(handle.kind != kind for handle in handles):
                raise ValueError(f"selected {kind} handles name {kind} refs only")
            ids = [handle.id for handle in handles]
            if ids != sorted(set(ids)):
                raise ValueError("selected handles are sorted by id, one per id")
            if len(ids) > MAX_SELECTED_MEMBERS:
                raise ValueError("at most 512 selected handles per kind")
        if not self.assertions and not self.evidence:
            raise ValueError("a members selection names at least one handle")
        return self


class SelectedReportRead(_Wire):
    """``selected-report-read.v2`` (KS ``readSelected``, WI-02): the inline payload of an exact
    ``knowledge.read``: the exact report, the receiver's admitted purpose and the selection
    (the whole revision, or exact assertion/fragment handles). Never widened to another revision."""

    report: Ref
    exact: Literal[True]
    purpose: Annotated[str, StringConstraints(pattern=READ_PURPOSE_PATTERN)]
    selection: RevisionSelection | MembersSelection = Field(discriminator="mode")

    @model_validator(mode="after")
    def _a_report(self) -> SelectedReportRead:
        if self.report.kind != "report":
            raise ValueError("a selected read names an exact report ref")
        return self

    def digest(self) -> str:
        """``selectedReadDigest``: the digest a package's ``request`` must repeat."""

        return digest_canonical(self.model_dump(mode="json"))


class PackagePart(_Wire):
    path: Literal["body.md", "ledger.json"]
    digest: Digest
    bytes: Annotated[int, Field(ge=0)]
    artifact: Ref


class PackageMember(_Wire):
    handle: Ref
    record: dict[str, Any]

    @model_validator(mode="after")
    def _record_is_the_handle(self) -> PackageMember:
        if digest_canonical(self.record) != self.handle.digest:
            raise ValueError("a package member record does not digest to its handle")
        return self


class ResearchReportPackage(_Wire):
    """``research-report-package.v2``: the exact answer to one ``SelectedReportRead``."""

    schema_: Literal["research-report-package.v2"] = Field(alias="schema")
    report: Ref
    revision: Id
    kind: Ref
    purpose: Annotated[str, StringConstraints(pattern=READ_PURPOSE_PATTERN)]
    request: Digest
    selection: RevisionSelection | MembersSelection = Field(discriminator="mode")
    body: PackagePart | None
    ledger: PackagePart | None
    assertions: tuple[PackageMember, ...]
    evidence: tuple[PackageMember, ...]

    @model_validator(mode="after")
    def _parts_follow_the_mode(self) -> ResearchReportPackage:
        whole = isinstance(self.selection, RevisionSelection)
        if whole != (self.body is not None and self.ledger is not None) or (
            not whole and (self.body is not None or self.ledger is not None)
        ):
            raise ValueError("a revision read carries body and ledger, a members read neither")
        return self


class NativeContract(_Strict):
    """Native contract name and version (``knowledge-ingestion-intent`` / ``v1``)."""

    name: Name
    version: NativeVersion


class PinnedSchemaRef(_Strict):
    name: Name
    version: SchemaVersion
    digest: Digest


class NativeInput(_Strict):
    nativeContract: NativeContract
    payloadDigest: Digest
    payloadBytes: SafeInt
    payloadRef: Ref | None
    inlinePayload: JsonDocument | None
    upstream: list[Ref]

    @model_validator(mode="after")
    def _inline(self) -> NativeInput:
        inline = self.inlinePayload
        if inline is not None and digest_canonical(inline) != self.payloadDigest:
            raise ValueError("inline payload canonical digest differs from payloadDigest")
        return self


class Budget(_Strict):
    calls: SafeInt
    tokens: SafeInt
    costUsd: UsdAmount


class Governors(_Strict):
    deadline: Instant
    maxItems: PositiveInt
    partialResults: Literal["forbid", "allow"]
    budget: Budget


class EnvelopeTarget(_Strict):
    handle: OperationHandle | None
    effectKey: Id | None


OperationName = Literal[
    "knowledge.describe",
    "knowledge.read",
    "knowledge.apply",
    "report.register",
    "report.assess",
    "report.derive",
    "verify.claims",
    "report.observe",
    "report.seal",
    "report.decide",
    "report.review",
    "decision.resolve",
    "knowledge.plan_preview",
    "knowledge.read_intent",
    "operation.get",
    "operation.cancel",
    "receipt.get",
]
EFFECTFUL_OPERATIONS: frozenset[str] = frozenset({"knowledge.apply", "report.register"})
# The trusted assessment operations (WI-03): handles whose result document names the outcome.
ASSESSMENT_OPERATIONS: frozenset[str] = frozenset(
    {"report.observe", "report.seal", "report.decide", "report.review", "decision.resolve"}
)
# Operations whose invoke answers their result document in the same call: no handle, no
# receipt (K01 `RESULT_OPERATIONS`): the read-only W1 native plan preview (nothing recorded) and
# the recorded read `knowledge.read_intent` (KS records one operation row; OVE-204 slice 4).
RESULT_OPERATIONS: frozenset[str] = frozenset({"knowledge.plan_preview", "knowledge.read_intent"})


class KnowledgePlanPreview(_Strict):
    """``knowledge-plan-preview.v1``: what ``knowledge.apply``'s own planning computes for the
    same request now (KS ``plan-preview.ts``). Nothing is bound, journaled or admitted."""

    planId: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    semanticPayloadDigest: Digest
    boundEffectDigest: Digest
    normalizedValuesDigest: Digest
    processedEpoch: SafeInt
    migrationHead: Annotated[str, StringConstraints(min_length=1, max_length=200)]


# ---------------------------------------------------------------- knowledge.read_intent
# KS `packages/knowledge-operation-protocol/src/read-intent.ts` (OVE-204 slice 4): a bounded,
# recorded read of a binding's knowledge store, answered synchronously. Every digest is
# `digest_canonical` (one scheme); a native number that is not a safe integer travels as its
# decimal string (KS `toWireJson`), so rows and values are always `JsonDocument`.

READ_INTENT_CONTRACT: Final = {"name": "knowledge-read-intent", "version": "v1"}
READ_INTENT_REQUEST_VERSION: Final = "knowledge-read-intent-request.v1"
READ_INTENT_RESULT_VERSION: Final = "knowledge-read-intent-result.v1"
READ_INTENT_MAX_OPERATIONS: Final = 32
READ_INTENT_INLINE_MAX_BYTES: Final = 262_144
ReadIntentNamedQuery = Literal[
    "knowledge.head",
    "entity.resolve",
    "entity.by_identifier",
    "entity.card",
    "entity.relationships",
    "evidence.claims_for_entity",
    "relationships.current_by_kind",
    "vocab.relationship_kind",
]
ReadIntentOpId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
ReadIntentKind = Literal["named_query", "schema_search", "schema_get"]
ReadIntentStatus = Literal["ok", "empty", "skipped", "error", "truncated"]
# Statuses whose content was actually read (a `retained_read_observation` is `readable`).
READ_INTENT_READABLE: frozenset[str] = frozenset({"ok", "empty", "truncated"})


def _absent(value: object) -> bool:
    return value is None


class ReadIntentNamedQueryOperation(_Strict):
    opId: ReadIntentOpId
    kind: Literal["named_query"]
    query: ReadIntentNamedQuery
    params: dict[str, JsonDocument] = Field(default_factory=dict)
    limit: Annotated[int, Field(ge=1, le=2000)] | None = Field(default=None, exclude_if=_absent)


class ReadIntentSchemaSearchOperation(_Strict):
    opId: ReadIntentOpId
    kind: Literal["schema_search"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    kinds: (
        Annotated[
            list[Annotated[str, StringConstraints(min_length=1, max_length=80)]],
            Field(max_length=16),
        ]
        | None
    ) = Field(default=None, exclude_if=_absent)
    limit: Annotated[int, Field(ge=1, le=50)] | None = Field(default=None, exclude_if=_absent)


class ReadIntentSchemaGetOperation(_Strict):
    opId: ReadIntentOpId
    kind: Literal["schema_get"]
    id: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    maxBytes: Annotated[int, Field(ge=256, le=256_000)] | None = Field(
        default=None, exclude_if=_absent
    )


ReadIntentOperation = Annotated[
    ReadIntentNamedQueryOperation | ReadIntentSchemaSearchOperation | ReadIntentSchemaGetOperation,
    Field(discriminator="kind"),
]


class KnowledgeReadIntentRequest(_Strict):
    """``knowledge-read-intent-request.v1``: the inline payload of ``knowledge.read_intent``."""

    schemaVersion: Literal["knowledge-read-intent-request.v1"]
    # The declared purpose; recorded with the operation, never a use decision.
    purpose: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    # Freeze the result document into custody (`retainedRef`) and retain the native snapshot.
    persist: bool = False
    # Read as of this knowledge sequence; None: the current head.
    atKnowledgeSeq: SafeInt | None = None
    operations: Annotated[list[ReadIntentOperation], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _unique_op_ids(self) -> KnowledgeReadIntentRequest:
        ids = [operation.opId for operation in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate opId")
        return self

    def payload(self) -> dict[str, JsonDocument]:
        """The inline wire payload (defaults written, absent optionals omitted)."""

        return self.model_dump(mode="json")


class ReadIntentError(_Strict):
    code: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    message: Annotated[str, StringConstraints(max_length=2000)]


class ReadIntentOperationResult(_Strict):
    opId: ReadIntentOpId
    kind: ReadIntentKind
    # The named query, the search text, or the page id.
    query: Annotated[str, StringConstraints(min_length=1, max_length=300)] | None = Field(
        default=None, exclude_if=_absent
    )
    status: ReadIntentStatus
    rowCount: SafeInt
    truncated: bool
    # `digest_canonical` of the full body (rows, value or null), also when it is withheld.
    contentDigest: Digest
    # The body was not returned inline: the result's 256 KiB inline budget was spent.
    bodyWithheld: bool
    columns: list[str] | None = Field(default=None, exclude_if=_absent)
    rows: list[dict[str, JsonDocument]] | None = Field(default=None, exclude_if=_absent)
    value: JsonDocument = Field(default=None, exclude_if=_absent)
    error: ReadIntentError | None = Field(default=None, exclude_if=_absent)

    @property
    def body(self) -> JsonDocument:
        """The returned body: rows for a row set, the value otherwise (None when absent)."""

        if self.rows is not None:
            return list(self.rows)
        return self.value


class ReadIntentKnowledgeHead(_Strict):
    knowledgeSeq: SafeInt
    updatedAt: Instant


class ReadIntentContract(_Strict):
    migrationHead: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    workspaceFingerprint: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = (
        Field(default=None, exclude_if=_absent)
    )
    catalogVersion: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = Field(
        default=None, exclude_if=_absent
    )


class KnowledgeReadIntentResult(_Strict):
    """``knowledge-read-intent-result.v1``: the synchronous answer of ``knowledge.read_intent``."""

    schemaVersion: Literal["knowledge-read-intent-result.v1"]
    # The recorded KS operation id (`op-read_intent-...`); a replay answers the same id.
    operationId: Id
    snapshotId: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    snapshotDigest: Digest
    knowledgeHead: ReadIntentKnowledgeHead
    atKnowledgeSeq: SafeInt
    contract: ReadIntentContract
    operations: Annotated[list[ReadIntentOperationResult], Field(min_length=1, max_length=32)]
    # The frozen result document in custody when `persist`; otherwise null.
    retainedRef: Ref | None


def read_intent_snapshot_digest(
    at_knowledge_seq: int, operations: list[ReadIntentOperationResult]
) -> str:
    """KS ``readIntentSnapshotDigest``: the digest of the per-operation summaries (bodies enter
    only through their content digests, so withholding a body never changes it)."""

    return digest_canonical(
        {
            "atKnowledgeSeq": at_knowledge_seq,
            "operations": [
                {
                    "opId": operation.opId,
                    "kind": operation.kind,
                    "query": operation.query,
                    "status": operation.status,
                    "rowCount": operation.rowCount,
                    "truncated": operation.truncated,
                    "contentDigest": operation.contentDigest,
                }
                for operation in operations
            ],
        }
    )


# Operations that answer with a handle to poll rather than a terminal result (K01).
HANDLE_OPERATIONS: frozenset[str] = frozenset(
    {"knowledge.apply", "report.assess", "report.derive", "verify.claims"} | ASSESSMENT_OPERATIONS
)
# What an evaluator credential (`evaluation` grant) may be granted: assessment, resolution and
# reads only; never an effect or a producer operation.
EVALUATOR_OPERATIONS: frozenset[str] = frozenset(
    {"report.observe", "report.review", "decision.resolve", "knowledge.read", "operation.get"}
)


def trusted_operation_id(tenant: str, operation: str, request_id: str) -> str:
    """The id Knowledge Services gives a trusted operation (an assessment operation or the
    evaluation-context ``knowledge.read``): ``op-<operation, first "." as "-">-`` plus 32 hex of the
    kop-canonical sha256 of ``{tenant, operation, requestId}`` (knowledge-services
    ``packages/host/src/knowledge-operation/service.ts``, the trusted operation path and
    ``shortDigest``). KS answers a replay of the same request id with that operation, so a host
    that persisted its request id can read the operation (``operation.get``) without re-sending
    (W1: recovering a KS-accepted observation whose handle the host failed to record)."""

    digest = digest_canonical({"tenant": tenant, "operation": operation, "requestId": request_id})
    return f"op-{operation.replace('.', '-', 1)}-{digest[7:39]}"


class OperationEnvelope(_Strict):
    protocolVersion: Literal["ks.knowledge_operation.v2"]
    requestId: Id
    dispatchId: Id
    tenant: ScopeId
    application: Name
    binding: Name
    operation: OperationName
    effect: EffectBinding | None
    target: EnvelopeTarget
    cancelRequestId: Id | None
    input: NativeInput | None
    governors: Governors
    requiredCapabilities: list[CapabilityName]
    pinnedSchema: PinnedSchemaRef | None
    issuedAt: Instant
    # K01 round 4: the declared exact use of an effectful operation (both or neither); absent
    # keys stay absent on the wire and in the envelope digest.
    use: Name | None = Field(default=None, exclude_if=lambda value: value is None)
    audience: Name | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def _rules(self) -> OperationEnvelope:
        effectful = self.operation in EFFECTFUL_OPERATIONS
        if effectful != (self.effect is not None):
            raise ValueError("effect binding present iff the operation is effectful")
        if (self.use is None) != (self.audience is None):
            raise ValueError("use and audience are declared together")
        if self.use is not None and not effectful:
            raise ValueError("a declared use belongs to an effectful operation only")
        if self.effect is not None:
            if self.effect.originatingOrigin.tenantId != self.tenant:
                raise ValueError("effect tenant differs from envelope tenant")
            if self.input is None or self.input.payloadDigest != self.effect.semanticPayloadDigest:
                raise ValueError("payload digest differs from the bound effect")
        if self.operation in {"operation.get", "operation.cancel"} and self.target.handle is None:
            raise ValueError(f"{self.operation} needs a handle")
        if self.operation == "receipt.get" and self.target.effectKey is None:
            raise ValueError("receipt.get needs the effect key")
        if (self.operation == "operation.cancel") != (self.cancelRequestId is not None):
            raise ValueError("cancel request id present iff the operation is cancel")
        return self

    def digest(self) -> str:
        envelope = self.model_dump(mode="json")
        return digest_canonical({"canonicalization": CANONICALIZATION, "envelope": envelope})

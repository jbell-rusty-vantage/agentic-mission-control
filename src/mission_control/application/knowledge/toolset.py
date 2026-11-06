"""The knowledge toolset: lane-neutral agent tools over the gateway and submissions (M02/M03).

Seven tools (design §8): ``knowledge_read``, ``knowledge_apply``, ``report_register``,
``report_derive``, ``verify_claims``, ``submit_output`` and (OVE-204 slice 4)
``knowledge_read_intent``, the recorded discovery read of the binding's knowledge store. A lane
adapter projects them into its native tool form (Deep Agents:
``adapters/deep_agents/knowledge_tools.py``) and calls :meth:`KnowledgeToolset.dispatch` with
the arguments the model supplied and the *current* invocation:
:meth:`KnowledgeToolset.access` builds a fresh
:class:`~mission_control.application.knowledge.access.InvocationAccess` from the live attempt
at every dispatch (M02 "current invocation refreshed at every tool dispatch"), with a new
invocation id and authentication instant, so a retried attempt presents its own origin and a
stale one cannot be reused. Arguments never carry an origin, tenant or credential.

Every effectful call is journaled by the gateway before dispatch; the result is a structured
document (journal state, receipt reference and digest, handle, status, result reference, typed
refusal code). Provider text is never a control channel: a refusal is a ``code``, never prose
the model must interpret. ``submit_output`` submits under the stable tool-call id as the
submission key, so a replayed tool call is the same submission. :meth:`finalize` is called by
the lane when the node's attempt completes; it hands selected reports to the independent
assessment (M03).

The live-to-wire identity mapping (provenance slice 1, OVE-204): the binding carries the run
key and the runtime unit key only, so :meth:`KnowledgeToolset.locate` resolves the ledger ids
once per attempt through the :class:`~mission_control.application.ports.knowledge.
InvocationLocator` port: ``mission_id`` is ``mission_run.mission_id`` and ``activation_id`` the
``activation.activation_id`` attempt admission recorded for the unit key (``None`` without a
runtime unit). :meth:`KnowledgeToolset.access` refuses an unresolved live attempt
(``MissionIdentityUnavailable``); no origin carries a stand-in id. The unit key rides on the
access (journal, handle and submission rows), never on the origin or the K01 wire.
"""

from __future__ import annotations

import asyncio
import json
import types
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, Union, get_args, get_origin
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mission_control.application.context.resolution import (
    ContentResolutionService,
    ResolutionRefused,
    selected_read_payload,
)
from mission_control.application.knowledge.access import (
    InvocationAccess,
    RecoveryAccess,
    RecoveryGrant,
)
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.operations import (
    KnowledgeCall,
    KnowledgeRefused,
    KnowledgeResult,
)
from mission_control.application.knowledge.redaction import redacted as _redacted
from mission_control.application.knowledge.report_registration import (
    RegistrationRefused,
    canonical_registration,
)
from mission_control.application.knowledge.roles import (
    PRODUCER_TOOL_CAPABILITIES,
    PRODUCER_TOOLS,
)
from mission_control.application.knowledge.trusted_settlement import (
    TrustedSettlement,
    UncomposedTrustedSettlement,
    pending_or_raise,
)
from mission_control.application.outputs.submission_service import (
    AmbiguousHandle,
    FinalizationReport,
    OutputSelection,
    SelectedItem,
    SubmissionService,
    UnsupportedReportSelection,
    report_ref,
)
from mission_control.application.ports.knowledge import (
    ContentLineageStore,
    InvocationLocator,
    JournalRecord,
    KnowledgeTransportError,
    LineageEntry,
    RetainedReadStore,
    SubmissionClosed,
    SubmissionConflict,
)
from mission_control.contracts.identities import parse_request_scope
from mission_control.contracts.knowledge_protocol import (
    READ_INTENT_CONTRACT,
    SELECTED_READ_CONTRACT,
    Governors,
    JsonDocument,
    KnowledgeReadIntentRequest,
    OperationName,
    ReadIntentOperation,
    Ref,
    SelectedReportRead,
    digest_canonical,
)
from mission_control.contracts.knowledge_protocol_results import (
    ProtocolError,
    ReceiptFound,
    ReceiptNotFound,
)
from mission_control.domain.knowledge.effects import TERMINAL_STATES as JOURNAL_TERMINAL
from mission_control.domain.knowledge.effects import JournalState, mint_effect_key
from mission_control.domain.knowledge.lineage import (
    ADOPTION_ACT,
    ActorKind,
    LineageFact,
    ProvenanceRole,
)
from mission_control.domain.knowledge.origin import InvocationOrigin, MissionIdentityUnavailable
from mission_control.domain.outputs.contracts import (
    CandidateRef,
    OutputObligation,
    SubmissionAck,
    SubmitOutput,
)
from mission_control.domain.outputs.rules import code_change_digest, text_digest, value_digest

if TYPE_CHECKING:
    from mission_control.application.knowledge.native_write import NativeWriteService

TOOL_NAMES: Final = (
    "knowledge_read",
    "knowledge_apply",
    "report_register",
    "report_derive",
    "verify_claims",
    "submit_output",
    "knowledge_read_intent",
)
TOOL_OPERATIONS: Final[Mapping[str, OperationName]] = {
    "knowledge_read": "knowledge.read",
    "knowledge_apply": "knowledge.apply",
    "report_register": "report.register",
    "report_derive": "report.derive",
    "verify_claims": "verify.claims",
    "knowledge_read_intent": "knowledge.read_intent",
}
NATIVE_CONTRACTS: Final[Mapping[str, dict[str, str]]] = {
    "knowledge_read": dict(SELECTED_READ_CONTRACT),
    "report_register": {"name": "research-report", "version": "v2"},
    "report_derive": {"name": "research-report-derive", "version": "v1"},
    "verify_claims": {"name": "research-claims", "version": "v1"},
    "knowledge_read_intent": dict(READ_INTENT_CONTRACT),
}


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MemberArg(_Args):
    kind: Literal["assertion", "fragment"]
    id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=128)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReadArgs(_Args):
    handle: str = Field(min_length=1, max_length=2048, description="Exact report handle kh:...")
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$", description="The handle's digest")
    members: list[MemberArg] = Field(
        default_factory=list,
        max_length=512,
        description=(
            "Exact assertion/fragment handles of that report to read (members mode); empty: "
            "the whole revision"
        ),
    )


class ReadIntentArgs(_Args):
    """OVE-204 slice 4: a bounded discovery read of the binding's knowledge store (allowlisted
    named queries, schema search and schema page reads). Every read is recorded."""

    purpose: str = Field(
        min_length=1, max_length=200, description="Why you read (recorded with the read)"
    )
    operations: list[ReadIntentOperation] = Field(
        min_length=1,
        max_length=32,
        description=(
            "1..32 reads, each with a unique opId: {kind: named_query, query, params, limit?}, "
            "{kind: schema_search, query, kinds?, limit?} or {kind: schema_get, id, maxBytes?}"
        ),
    )
    persist: bool = Field(
        default=False, description="Freeze the result into custody (returns retainedRef)"
    )
    at_knowledge_seq: int | None = Field(
        default=None,
        ge=0,
        le=2**53 - 1,
        description="Read as of this knowledge sequence; omit for the current head",
    )

    def request(self) -> KnowledgeReadIntentRequest:
        return KnowledgeReadIntentRequest(
            schemaVersion="knowledge-read-intent-request.v1",
            purpose=self.purpose,
            persist=self.persist,
            atKnowledgeSeq=self.at_knowledge_seq,
            operations=list(self.operations),
        )


@dataclass(frozen=True)
class ReadScope:
    """What the receiver's sealed transfer plan lets ``knowledge_read`` reach (WI-02 B1): its
    purpose, and for an independent evaluator only the plan's exact report handles."""

    purpose: str
    isolated: bool
    reports: Mapping[str, str] = field(default_factory=dict)

    def allows(self, handle: str, digest: str) -> bool:
        return not self.isolated or self.reports.get(handle) == digest


class ReadOutOfScope(RuntimeError):
    """An isolated receiver named a report its sealed plan does not hold."""


class ApplyArgs(_Args):
    decision: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="The exact handle of an already-recorded use decision to apply (from the host)",
    )
    # W1 native write: an accepted report member of this invocation's sealed plan; the host
    # derives the native intent, decides it officially and applies it in this invocation.
    report: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="The exact handle of an accepted report member of your sealed plan to write",
    )
    digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _one_subject(self) -> ApplyArgs:
        if (self.decision is None) == (self.report is None):
            raise ValueError("name exactly one: a recorded decision handle or a report member")
        if (self.report is None) != (self.digest is None):
            raise ValueError("a report member names its exact digest")
        return self


class RegisterArgs(_Args):
    report: dict[str, JsonDocument] = Field(
        description=(
            "The research report content: task, fragments, assertions, supportSets and report. "
            "Records name each other by id; the host completes tenant, binding, producer and "
            "every digest (a digest you give is checked)"
        )
    )


class DeriveArgs(_Args):
    handle: str = Field(min_length=1, max_length=2048)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    mapping: dict[str, JsonDocument] = Field(default_factory=dict)


class VerifyArgs(_Args):
    claims: list[dict[str, JsonDocument]] = Field(min_length=1)
    handle: str | None = Field(default=None, min_length=1, max_length=2048)
    digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class InlineItem(_Args):
    """WI-04: an inline candidate of a named promise (text or a structured value).

    The host computes the digest of the exact bytes or canonical value when the model gives
    none (a given digest is checked); a structured value defaults to the promise's pinned
    schema. Only a run with registered promises accepts inline candidates."""

    kind: Literal["inline"]
    text: str | None = Field(default=None, max_length=1_000_000)
    value: JsonDocument | None = None
    effect_key: str | None = Field(default=None, min_length=1, max_length=512)
    receipt_ref: str | None = Field(default=None, min_length=1, max_length=2048)
    schema_ref: str | None = Field(default=None, min_length=1, max_length=512)
    media_type: str | None = Field(default=None, min_length=1, max_length=255)
    digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class CodeChangeItem(_Args):
    """WI-04: a proposed code change of a named promise (repository, base, head or patch)."""

    kind: Literal["code_change"]
    repository: str = Field(min_length=1, max_length=512)
    base: str = Field(pattern=r"^[0-9a-f]{40}$")
    head: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    patch_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    changed_paths: list[str] = Field(min_length=1, max_length=4096)
    digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


SubmitItem = Annotated[SelectedItem | InlineItem | CodeChangeItem, Field(discriminator="kind")]


class LegacySubmitArgs(_Args):
    obligation: str = Field(min_length=1, max_length=200)
    # Named promises (WI-01): the deliverable this act offers a revision of; defaults to the
    # promise's output name. Ignored for a run without registered promises.
    deliverable: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,199}$")
    items: list[SubmitItem] = Field(
        min_length=1,
        description="One report alone, or non-report handles/paths; for a named promise also "
        "an inline text or structured value, or a code change. Report collections and mixed "
        "report selections are unsupported; duplicates are refused too.",
    )


class SubmitArgs(_Args):
    action: Literal["submit", "inspect"] = "submit"
    obligation: str | None = Field(default=None, min_length=1, max_length=200)
    mode: Literal["progressive", "final"] = "final"
    expected_head: str | None = Field(default=None, min_length=1, max_length=64)
    # Named promises (WI-01): the deliverable this act offers a revision of; defaults to the
    # promise's output name. Ignored for a run without registered promises.
    deliverable: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,199}$")
    items: list[SubmitItem] = Field(
        default_factory=list,
        max_length=64,
        description="One report alone, or non-report handles/paths; for a named promise also "
        "an inline text or structured value, or a code change. Report collections and mixed "
        "report selections are unsupported; duplicates are refused too.",
    )

    @model_validator(mode="after")
    def _action(self) -> SubmitArgs:
        if self.action == "submit" and (self.obligation is None or not self.items):
            raise ValueError(
                "submit requires obligation and nonempty items; inspect discovers pins"
            )
        if self.action == "inspect" and (
            self.items
            or self.deliverable is not None
            or self.expected_head is not None
            or self.mode != "final"
        ):
            raise ValueError("inspect accepts only an optional obligation")
        return self


TOOL_ARGUMENTS: Final[Mapping[str, type[_Args]]] = {
    "knowledge_read": ReadArgs,
    "knowledge_apply": ApplyArgs,
    "report_register": RegisterArgs,
    "report_derive": DeriveArgs,
    "verify_claims": VerifyArgs,
    "submit_output": SubmitArgs,
    "knowledge_read_intent": ReadIntentArgs,
}
TOOL_DESCRIPTIONS: Final[Mapping[str, str]] = {
    "knowledge_read": (
        "Read one exact report revision (handle + digest) or selected members; "
        "returns verified content and references (256 KiB maximum)."
    ),
    "knowledge_apply": (
        "Apply one host-recorded use decision exactly once (name its handle; the host supplies "
        "the exact use); journaled; returns its receipt, or pending_delivery while queued."
    ),
    "report_register": (
        "Register a research report from its content (the host computes every digest and "
        "binds the producer); returns the receipt and report ref."
    ),
    "report_derive": "Derive exact domain proposals from a registered report (async handle).",
    "verify_claims": "Verify claims (async handle with progress and findings).",
    "knowledge_read_intent": (
        "Read the knowledge store for discovery: allowlisted named queries (knowledge.head, "
        "entity.resolve, entity.by_identifier, entity.card, entity.relationships, "
        "evidence.claims_for_entity, relationships.current_by_kind, vocab.relationship_kind), "
        "schema_search and schema_get, up to 32 per call from one consistent snapshot. Returns "
        "rows/values with a content digest per read (bodies past 256 KiB are withheld, digest "
        "kept). Every read is recorded; it is never a use decision or verified evidence."
    ),
    "submit_output": (
        "Inspect your pinned contracts and submission status with {action: inspect}; optionally "
        "name a full obligation key <owner position>.<promise name>, e.g. root.report. "
        "Submit using that key and items: for a report_register "
        "receipt copy its affected report handle and digest into {kind: handle, ref, digest}. "
        "mode defaults to final; progressive records a draft. expected_head is the accepted "
        "revision ID returned by inspect, checked atomically. An accepted acknowledgement only "
        "records a draft: it is not promotion, verified acceptance, fulfillment or completion. "
        "The host independently assesses and promotes. Report collections and mixed report "
        "selections are unsupported. Repair findings with a new tool call; retry identical "
        "arguments under the same call ID for replay. Lineage and actor identity are host-owned."
    ),
}


# W1 D17: models (Claude Haiku 5.5 in 9 of 10 W1 calls) send an object argument as a JSON string.
# The tool boundary parses such a string exactly once, strictly (one JSON object, no duplicate
# keys, no NaN/Infinity), size bounded, then validates the object as usual. Only a field whose
# schema admits nothing but an object (or a list whose items are objects) is coerced, so a
# string is never reinterpreted where a string is valid (an inline `value`, a handle).
MAX_COERCED_ARGUMENT_BYTES: Final = 2_097_152
ArgumentShape = Literal["object", "object_items"]


@dataclass(frozen=True)
class ArgumentCoercion:
    """One argument the boundary parsed from a JSON-object string (recorded in the result)."""

    field: str
    bytes: int
    to: Literal["object", "array"] = "object"

    def document(self) -> dict[str, Any]:
        return {"field": self.field, "from": "json_string", "to": self.to, "bytes": self.bytes}


class ArgumentCoercionRefused(ValueError):
    """An object argument arrived as a string that is not exactly one bounded JSON object."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


def _is_object(annotation: Any) -> bool:
    if get_origin(annotation) is Annotated:
        return _is_object(get_args(annotation)[0])
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        members = [item for item in get_args(annotation) if item is not type(None)]
        return bool(members) and all(_is_object(item) for item in members)
    if origin is dict or annotation is dict:
        return True
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _shape(annotation: Any) -> ArgumentShape | None:
    if get_origin(annotation) is Annotated:
        return _shape(get_args(annotation)[0])
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        members = [item for item in get_args(annotation) if item is not type(None)]
        shapes = {_shape(item) for item in members}
        return shapes.pop() if len(shapes) == 1 else None
    if _is_object(annotation):
        return "object"
    if origin in (list, tuple) and get_args(annotation):
        return "object_items" if _is_object(get_args(annotation)[0]) else None
    return None


def model_argument_shapes(arguments: type[BaseModel]) -> dict[str, ArgumentShape]:
    """The fields of an argument model whose schema admits only an object (or a list of
    objects): the ones a JSON string may stand in for (W1 D17; D18 the response tool)."""

    shapes = {name: _shape(info.annotation) for name, info in arguments.model_fields.items()}
    return {name: shape for name, shape in shapes.items() if shape is not None}


def object_argument_shapes(tool: str) -> dict[str, ArgumentShape]:
    """The arguments of ``tool`` whose schema admits only an object (or a list of objects)."""

    arguments = TOOL_ARGUMENTS.get(tool)
    return {} if arguments is None else model_argument_shapes(arguments)


def _reject_constant(value: str) -> Any:
    raise ValueError(f"{value} is not strict JSON")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    duplicate = next((key for key in keys if keys.count(key) > 1), None)
    if duplicate is not None:
        raise ValueError(f"duplicate key {duplicate!r}")
    return dict(pairs)


def _parse_strict(field: str, text: str) -> tuple[Any, int]:
    size = len(text.encode("utf-8"))
    if size > MAX_COERCED_ARGUMENT_BYTES:
        raise ArgumentCoercionRefused(
            field, f"the JSON string is {size} bytes (limit {MAX_COERCED_ARGUMENT_BYTES})"
        )
    try:
        value = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_unique_pairs)
    except (ValueError, RecursionError) as error:
        raise ArgumentCoercionRefused(
            field, f"a string was given, but it is not strict JSON: {str(error)[:200]}"
        ) from None
    return value, size


def _parse_object(field: str, text: str) -> tuple[dict[str, Any], ArgumentCoercion]:
    value, size = _parse_strict(field, text)
    if not isinstance(value, dict):
        raise ArgumentCoercionRefused(
            field, f"a string was given, but its JSON is a {type(value).__name__}, not an object"
        )
    return value, ArgumentCoercion(field=field, bytes=size)


def _parse_object_list(field: str, text: str) -> tuple[list[Any], ArgumentCoercion]:
    """A list-of-objects argument sent whole as a JSON string (W1 review N3)."""

    value, size = _parse_strict(field, text)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ArgumentCoercionRefused(
            field, "a string was given, but its JSON is not an array of objects"
        )
    return value, ArgumentCoercion(field=field, bytes=size, to="array")


def coerce_object_arguments(
    tool: str, arguments: Mapping[str, Any]
) -> tuple[dict[str, Any], tuple[ArgumentCoercion, ...]]:
    """The arguments with every JSON-object string of an object-typed argument parsed once.

    Already-parsed values pass unchanged (a second call coerces nothing), so the canonical
    bytes and digests the host computes are those of the parsed object (W1 D1 stays exact).
    Raises :class:`ArgumentCoercionRefused` for a string that is not one bounded JSON object.
    """

    return coerce_with_shapes(object_argument_shapes(tool), arguments)


def coerce_with_shapes(
    shapes: Mapping[str, ArgumentShape], arguments: Mapping[str, Any]
) -> tuple[dict[str, Any], tuple[ArgumentCoercion, ...]]:
    """:func:`coerce_object_arguments` over explicit shapes (any argument model)."""

    coerced = dict(arguments)
    records: list[ArgumentCoercion] = []
    for name, shape in shapes.items():
        value = coerced.get(name)
        if shape == "object" and isinstance(value, str):
            coerced[name], record = _parse_object(name, value)
            records.append(record)
        elif shape == "object_items" and isinstance(value, str):
            coerced[name], record = _parse_object_list(name, value)
            records.append(record)
        elif shape == "object_items" and isinstance(value, list):
            items = list(value)
            for index, item in enumerate(items):
                if isinstance(item, str):
                    items[index], record = _parse_object(f"{name}[{index}]", item)
                    records.append(record)
            coerced[name] = items
    return coerced, tuple(records)


def coercion_refusal(tool: str, error: ArgumentCoercionRefused) -> dict[str, Any]:
    """The typed refusal of an object argument the boundary could not parse."""

    document = _refusal(
        tool, "INVALID_ENVELOPE", f"argument {error.field}: {error.reason}; send a JSON object"
    )
    document["refusal"]["field_paths"] = [error.field]
    return document


# W1 D11: the KS refusal the model sees (code, message, field paths), bounded and redacted.
_REFUSAL_MESSAGE_LIMIT: Final = 500
_REFUSAL_ENTRY_LIMIT: Final = 300
_REFUSAL_ENTRIES: Final = 10


def _bounded_entries(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        _redacted(
            item if isinstance(item, str) else json.dumps(item, sort_keys=True),
            _REFUSAL_ENTRY_LIMIT,
        )
        for item in value[:_REFUSAL_ENTRIES]
    ]


def refusal_view(code: str, error: ProtocolError | None) -> dict[str, Any]:
    """The refusal document a tool result carries for a KS refusal (W1 D11).

    The typed code, the KS message and, where KS names them, the offending field paths and its
    bounded ``issues``/``violations`` so the model can correct the payload. Bounded (message
    500 chars, at most 10 entries of 300 chars) and redacted of credential-shaped strings.
    """

    if error is None:
        return {"code": code, "message": None}
    view: dict[str, Any] = {
        "code": code,
        "message": _redacted(error.message, _REFUSAL_MESSAGE_LIMIT),
    }
    details = error.details if isinstance(error.details, dict) else {}
    issues = _bounded_entries(details.get("issues"))
    violations = _bounded_entries(details.get("violations"))
    paths = [item.split(": ", 1)[0] for item in issues if ": " in item]
    for key in ("path", "field", "pointer"):
        value = details.get(key)
        if isinstance(value, str):
            paths.append(_redacted(value, _REFUSAL_ENTRY_LIMIT))
    if paths:
        view["field_paths"] = list(dict.fromkeys(paths))[:_REFUSAL_ENTRIES]
    if issues:
        view["issues"] = issues
    if violations:
        view["violations"] = violations
    reason = details.get("reason")
    if isinstance(reason, str):
        view["reason"] = _redacted(reason, _REFUSAL_ENTRY_LIMIT)
    if reason in RECORD_COLLISIONS:
        # W1 D19: KS names the colliding record; the producer re-registers under new ids.
        for key in ("record", "id"):
            value = details.get(key)
            if isinstance(value, str):
                view[key] = _redacted(value, _REFUSAL_ENTRY_LIMIT)
        view["next_action"] = RECORD_COLLISIONS[str(reason)]
    return view


# W1 D19: KS `report.register` record collisions (typed EFFECT_CONFLICT, never INTERNAL) and what
# the producer does about each.
RECORD_COLLISIONS: Final[Mapping[str, str]] = {
    "record_id_conflict": (
        "another registration holds this record id with other content: give this record (and "
        "every reference to it) a new id, then call report_register again"
    ),
    "record_digest_exists": (
        "this exact record is already registered under the named id: reference that id instead"
    ),
}


@dataclass(frozen=True)
class LiveInvocation:
    """The live attempt a tool call belongs to, as the lane knows it at dispatch time."""

    request_scope: str
    run_id: str
    operation_id: str
    operation_attempt: int
    execution_generation: int
    lane: str
    obligations: tuple[str, ...] = ()
    # The owner position the host bound to this invocation (named promises, WI-01).
    position: str | None = None
    recovery_grant: RecoveryGrant | None = None
    # Host-minted at attempt start (R2-MC D2): one effect-scoped grant per effect an earlier
    # attempt of this operation left dispatched or uncertain.
    recovery_grants: tuple[RecoveryGrant, ...] = ()
    # WI-02: the read scope of the receiver's sealed transfer plan (absent: no plan).
    read_scope: ReadScope | None = None
    # W1 D27: the host bound this invocation as an independent evaluator (its sealed transfer
    # plan's isolation); it may not use the producer's tools (`PRODUCER_TOOLS`).
    evaluator: bool = False
    # Provenance slice 1 (OVE-204): the ledger identity of this attempt, resolved once by
    # `KnowledgeToolset.locate` (``mission_run.mission_id``; the ``activation.activation_id``
    # attempt admission recorded for ``unit_key``). ``unit_key`` is the binding's runtime unit
    # key (``None``: no runtime unit, so no activation). `KnowledgeToolset.access` refuses a
    # live attempt whose mission id is unresolved.
    mission_id: str | None = None
    activation_id: str | None = None
    unit_key: str | None = None


def _declared_use(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """The registered task's exact use and audience (K01 round 4: declared on the envelope)."""

    task = payload.get("task")
    if not isinstance(task, Mapping):
        return None, None
    use, audience = task.get("use"), task.get("audience")
    if isinstance(use, str) and isinstance(audience, str):
        return use, audience
    return None, None


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class KnowledgeToolset:
    gateway: KnowledgeGateway
    submissions: SubmissionService
    issuer: str
    subject: str = "mission-control-runtime"
    capability_pins: Mapping[str, str] = field(default_factory=dict)
    # Sprint V SV-16: content lineage (0051): producer/receipt facts for a registered report,
    # adopter facts for a selected report this invocation did not produce.
    lineage: ContentLineageStore | None = None
    # WI-03: the trusted KS assessment pass of a saved result's settlement (composed when the
    # admitted run configuration supplies separate evaluators; W1 composes the Deep Agents
    # judge/auditor runner). Absent: the settlement keeps the report.assess handoff only.
    trusted: TrustedSettlement | None = None
    native: NativeWriteService | None = None
    # W1 D30: without a trusted settlement, the pass that keeps a trusted-pinned revision waiting
    # (actionable cause) instead of finalizing it unjudged.
    uncomposed_trusted: UncomposedTrustedSettlement | None = None
    deadline: timedelta = timedelta(minutes=30)
    max_items: int = 64
    clock: Callable[[], datetime] = _utcnow
    # Node-end reconciliation (integrator decision 2026-10-25): a bounded receipt-first poll of
    # the open effects of the attempt (the HTTP client honours a bounded Retry-After per
    # lookup); what stays unresolved blocks the settlement of the invocation.
    reconcile_attempts: int = 5
    reconcile_initial_delay: float = 0.5
    reconcile_max_delay: float = 5.0
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    # W1 D6: the KS component installation every wire origin names (None: the MC installation,
    # one shared id). The request scope keeps the MC installation.
    knowledge_installation_id: str | None = None
    # Provenance slice 1 (OVE-204): resolves a live attempt's ledger mission and activation
    # ids. Absent, no unresolved live attempt can build an origin (fail closed).
    locator: InvocationLocator | None = None
    # OVE-204 slice 4: where every `knowledge_read_intent` read is recorded (one
    # `retained_read_observation` per result operation). Absent: the tool is refused.
    retained_reads: RetainedReadStore | None = None

    async def locate(self, live: LiveInvocation) -> LiveInvocation:
        """The live attempt with its ledger mission and activation ids (once per attempt).

        A live attempt that already carries its mission id is returned unchanged; otherwise
        the locator reads ``mission_run.mission_id`` by the run key and the activation row
        attempt admission recorded for the unit key. Both are stable per attempt, so begin,
        dispatch, settlement and a settlement after a worker restart build the same origin."""

        if live.mission_id is not None:
            return live
        if self.locator is None:
            raise MissionIdentityUnavailable(
                f"no invocation locator is composed: run {live.run_id} has no ledger mission id"
            )
        mission_id, activation_id = await self.locator.locate(
            live.request_scope, live.run_id, live.unit_key
        )
        return replace(live, mission_id=mission_id, activation_id=activation_id)

    def access(self, live: LiveInvocation) -> InvocationAccess:
        """A fresh host-built access for this dispatch (new invocation id, now).

        The origin names the ledger mission and activation (`locate`); an unresolved live
        attempt raises `MissionIdentityUnavailable` (no stand-in mission id)."""

        if live.mission_id is None:
            raise MissionIdentityUnavailable(
                f"run {live.run_id} operation {live.operation_id}: the live attempt carries no "
                "ledger mission id (resolve it with KnowledgeToolset.locate)"
            )
        scope = parse_request_scope(live.request_scope)
        origin = InvocationOrigin(
            issuer=self.issuer,
            installation_id=str(scope.installation_id),
            application_id=scope.application_id,
            tenant_id=str(scope.tenant_id),
            mission_id=live.mission_id,
            run_id=live.run_id,
            activation_id=live.activation_id,
            operation_id=live.operation_id,
            attempt=live.operation_attempt,
            generation=live.execution_generation,
            lane=live.lane,
        )
        return InvocationAccess(
            origin=origin,
            subject=self.subject,
            invocation_id=f"inv-{uuid4()}",
            authenticated_at=self.clock(),
            recovery_grant=live.recovery_grant,
            recovery_grants=live.recovery_grants,
            knowledge_installation_id=self.knowledge_installation_id,
            unit_key=live.unit_key,
        )

    async def dispatch(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        live: LiveInvocation,
        *,
        tool_call_id: str,
        coercions: tuple[ArgumentCoercion, ...] = (),
    ) -> dict[str, Any]:
        """One tool call. ``coercions`` are the object arguments the lane's tool boundary
        already parsed from JSON strings (W1 D17); the result records every coercion."""

        if tool not in TOOL_ARGUMENTS:
            return _refusal(tool, "INVALID_ENVELOPE", f"unknown knowledge tool {tool}")
        if live.evaluator and tool in PRODUCER_TOOLS:
            return _refusal(
                tool,
                "ROLE_SEPARATION",
                f"an independent evaluator may not call {tool}: it never registers, applies or "
                "submits for the promises it evaluates; return the verdict as the structured "
                "observation",
            )
        if tool == "knowledge_read_intent" and (
            live.evaluator or (live.read_scope is not None and live.read_scope.isolated)
        ):
            return _refusal(
                tool,
                "SCOPE_DENIED",
                "an independent evaluator reads only its sealed plan's exact reports; "
                "knowledge_read_intent is not available to it",
            )
        try:
            values, parsed_here = coerce_object_arguments(tool, arguments)
        except ArgumentCoercionRefused as error:
            return coercion_refusal(tool, error)
        document = await self._dispatch_parsed(tool, values, live, tool_call_id=tool_call_id)
        coerced = (*coercions, *parsed_here)
        if coerced:
            document["argument_coercions"] = [item.document() for item in coerced]
        return document

    async def _dispatch_parsed(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        live: LiveInvocation,
        *,
        tool_call_id: str,
    ) -> dict[str, Any]:
        try:
            parsed = TOOL_ARGUMENTS[tool].model_validate(dict(arguments))
        except ValidationError as error:
            return validation_refusal(tool, error)
        live = await self.locate(live)
        access = self.access(live)  # refreshed at every dispatch
        if isinstance(parsed, SubmitArgs):
            return await self._submit(parsed, access, tool_call_id, live.position)
        if isinstance(parsed, ReadIntentArgs):
            return await self._read_intent(parsed, access, tool_call_id)
        try:
            if isinstance(parsed, ApplyArgs) and parsed.report is not None:
                native = await self._native_write(parsed, access, live)
                if isinstance(native, dict):
                    return native
                result = native
            elif isinstance(parsed, ApplyArgs):
                # The host resolves the recorded use decision; the agent named its handle only.
                assert parsed.decision is not None
                result = await self.gateway.apply_decision(
                    parsed.decision,
                    access,
                    capability_pin=self.capability_pins.get(tool, f"knowledge.{tool}@1"),
                    governors=self._governors(),
                )
            elif isinstance(parsed, RegisterArgs):
                result = await self.gateway.invoke(
                    await self._register_call(parsed, access), access
                )
            else:
                call = self._call(tool, parsed, access, live.read_scope)
                result = await self.gateway.invoke(call, access)
        except RegistrationRefused as error:
            return _refusal(tool, error.code, str(error))
        except ReadOutOfScope as error:
            return _refusal(tool, "SCOPE_DENIED", str(error))
        except AmbiguousHandle as error:
            return _refusal(tool, "SCHEMA_UNSUPPORTED", str(error))
        except KnowledgeRefused as refused:
            return _refusal(tool, refused.code, str(refused), effect_key=refused.effect_key)
        if result.replayed and result.refusal_code is None and result.receipt is None:
            # W1 review S1: a settled success replays with its handles, never an empty result.
            loaded = await self._with_stored_receipt(tool, result, live)
            if isinstance(loaded, dict):
                return loaded
            result = loaded
        document = result.document()
        if isinstance(parsed, ReadArgs) and result.refusal_code is None:
            try:
                resolved = await ContentResolutionService(self.gateway).resolve_result(
                    SelectedItem(kind="handle", ref=parsed.handle, digest=parsed.digest),
                    access,
                    SelectedReportRead.model_validate(call.payload),
                    result,
                )
            except ResolutionRefused as error:
                return _refusal(tool, error.cause or error.code, str(error))
            try:
                content = {
                    "manifest": resolved.manifest,
                    "body": resolved.body.decode("utf-8"),
                    "ledger": resolved.ledger.decode("utf-8"),
                }
            except UnicodeDecodeError:
                return _refusal(tool, "SCHEMA_UNSUPPORTED", "Report text is not valid UTF-8.")
            # Retrieval is bounded and never silently truncates exact evidence. Large
            # revisions can be requested as explicitly selected assertion/fragment members.
            if len(json.dumps(content, ensure_ascii=False).encode("utf-8")) > 262_144:
                return _refusal(
                    tool,
                    "CONTENT_LIMIT_EXCEEDED",
                    "Verified content exceeds 256 KiB; request selected members.",
                )
            document["content"] = content
        if tool == "report_register" and result.receipt is not None and result.journal is not None:
            await self._record_production(access, result, replayed=result.replayed)
        refusal: dict[str, Any] | None = None
        if result.refusal_code is not None:
            refusal = refusal_view(result.refusal_code, result.refusal)
            if result.replayed:
                # W1 D12: an identical retry of a refused effect replays the same refusal.
                refusal["message"] = (
                    "this exact content was already refused with "
                    f"{result.refusal_code}; nothing was sent again. Correct the content and "
                    "call again (a changed payload is a new effect)"
                )
                refusal["replayed"] = True
        return {
            "tool": tool,
            "ok": result.refusal_code is None,
            "result": document,
            "refusal": refusal,
        }

    async def _read_intent(
        self, parsed: ReadIntentArgs, access: InvocationAccess, tool_call_id: str
    ) -> dict[str, Any]:
        """One recorded ``knowledge.read_intent``: the result document, or a typed refusal."""

        tool = "knowledge_read_intent"
        if self.retained_reads is None:
            return _refusal(
                tool,
                "CAPABILITY_UNAVAILABLE",
                "no retained read store is composed; reads are recorded or refused",
            )
        try:
            request = parsed.request()
        except ValidationError as error:
            return validation_refusal(tool, error)
        from mission_control.application.knowledge.read_intent import read_intent_request_key

        try:
            result = await self.gateway.read_intent(
                request,
                access,
                observations=self.retained_reads,
                capability_pin=self.capability_pins.get(tool, f"knowledge.{tool}@1"),
                governors=self._governors(),
                request_key=read_intent_request_key(
                    access.invocation_ref, tool_call_id, digest_canonical(request.payload())
                ),
            )
        except KnowledgeRefused as refused:
            return _refusal(tool, refused.code, str(refused))
        return {
            "tool": tool,
            "ok": True,
            "result": result.model_dump(mode="json"),
            "refusal": None,
        }

    async def finalize(self, live: LiveInvocation) -> FinalizationReport:
        """Settle the invocation: blocked while any of its effects is unresolved."""

        live = await self.locate(live)
        access = self.access(live)
        unresolved = tuple(row.effect_key for row in await self._open_effects(live))
        return await self.submissions.finalize(
            access.identity(live.obligations),
            access,
            unresolved_effects=unresolved,
            owes_nothing=live.evaluator,
        )

    async def begin(self, live: LiveInvocation) -> LiveInvocation:
        """Before the agent of a retry attempt starts: one effect-scoped recovery grant per
        effect an earlier attempt of this operation left dispatched or uncertain (exact key
        and bound digest; R2-MC D2). The dispatch it authorizes records its authority ref.
        The returned live attempt carries its ledger identity (`locate`)."""

        live = await self.locate(live)
        access = self.access(live)
        if await self.submissions.promises_registered(access.scope, live.run_id):
            # Named promises: pin their active revisions at invocation start, so a successor
            # activated later never changes this invocation's contract.
            await self.submissions.pin_invocation(access, actor_ref="mission-control:toolset")
            # WI-04: the finalization iterates the pinned promises this position owns.
            live = await self.with_declared_obligations(live)
        if live.operation_attempt <= 1:
            return live
        rows = await self.gateway.open_effects_for_operation(
            access.scope, run_id=live.run_id, operation_ref=live.operation_id
        )
        grants = tuple(
            RecoveryGrant(
                authority_ref="host-retry:"
                + sha256(
                    f"{live.run_id}/{live.operation_id}/{live.operation_attempt}/"
                    f"{row.effect_key}".encode()
                ).hexdigest()[:40],
                effect_key=row.effect_key,
                bound_effect_digest=row.bound_effect_digest,
            )
            for row in rows
            if row.state in {JournalState.DISPATCHED, JournalState.UNCERTAIN}
            and (row.operation_attempt or 0) < live.operation_attempt
        )
        return replace(live, recovery_grants=grants) if grants else live

    async def fail(self, live: LiveInvocation) -> FinalizationReport:
        """A failed attempt (R2-MC O1): reconcile its outstanding effects, then record its
        finalization with basis ``attempt_failed`` (the effects still unresolved are named)."""

        live = await self.locate(live)
        await self.reconcile(live)
        access = self.access(live)
        unresolved = tuple(row.effect_key for row in await self._open_effects(live))
        return await self.submissions.finalize(
            access.identity(live.obligations),
            access,
            unresolved_effects=unresolved,
            attempt_failed=True,
        )

    async def settle(self, live: LiveInvocation) -> FinalizationReport:
        """Node end (and the recovery path after the run): reconcile, then finalize."""

        live = await self.locate(live)
        await self.reconcile(live)
        return await self.finalize(live)

    async def with_declared_obligations(self, live: LiveInvocation) -> LiveInvocation:
        """The live invocation with the promises its position owns (WI-04).

        A run with registered promises declares, for this invocation, every pinned promise
        whose owner position is the host-bound position; the finalization then iterates them
        (omitted submissions included). A run without promises, or an invocation without a
        bound position, keeps the obligations the caller gave."""

        live = await self.locate(live)
        access = self.access(live)
        if live.evaluator:
            # W1 D27: an independent evaluator owes none of the promises it evaluates; it
            # finalizes with no declared obligations (not as an unfulfilled producer).
            return live
        if live.position is None or not await self.submissions.promises_registered(
            access.scope, live.run_id
        ):
            return live
        pins = await self.submissions.pin_invocation(access, actor_ref="mission-control:toolset")
        owned = []
        for key in sorted(pins):
            obligation = await self.submissions.pinned_obligation(access, key)
            if obligation is not None and obligation.owner_position == live.position:
                owned.append(key)
        return replace(live, obligations=tuple(dict.fromkeys((*live.obligations, *owned))))

    def _applier(self, access: InvocationAccess) -> Callable[..., Awaitable[KnowledgeResult]]:
        async def apply(handle: str, *, admission: Ref | None = None) -> KnowledgeResult:
            if admission is not None:
                return await self.gateway.apply_native_decision(
                    handle,
                    access,
                    admission=admission,
                    capability_pin=self.capability_pins.get(
                        "knowledge_apply", "knowledge.knowledge_apply@1"
                    ),
                    governors=self._governors(),
                )
            return await self.gateway.apply_decision(
                handle,
                access,
                capability_pin=self.capability_pins.get(
                    "knowledge_apply", "knowledge.knowledge_apply@1"
                ),
                governors=self._governors(),
            )

        return apply

    async def _native_write(
        self, parsed: ApplyArgs, access: InvocationAccess, live: LiveInvocation
    ) -> KnowledgeResult | dict[str, Any]:
        """W1 native write of an accepted report member, inside this invocation."""

        if self.native is None:
            raise KnowledgeRefused(
                "SCHEMA_UNSUPPORTED", "this host composes no native write for the application"
            )
        assert parsed.report is not None and parsed.digest is not None
        outcome = await self.native.write(
            access,
            parsed.report,
            parsed.digest,
            plan_reports={} if live.read_scope is None else live.read_scope.reports,
            attempt=int(self.clock().timestamp() * 1000),
            apply=self._applier(access),
        )
        if outcome.state in {"applied", "noop", "partial", "pending_effect"}:
            return outcome.result
        if outcome.state == "refused":
            return _refusal(
                "knowledge_apply",
                outcome.refusal_code or "STALE_DECISION",
                "the native effect was refused",
            )
        return {
            "tool": "knowledge_apply",
            "ok": True,
            "result": {
                "state": "pending_review",
                "decision": outcome.decision.handle,
                "effect_key": await self.gateway.decision_effect_key(
                    outcome.decision.handle,
                    access,
                    capability_pin=self.capability_pins.get(
                        "knowledge_apply", "knowledge.knowledge_apply@1"
                    ),
                ),
                "pending_reviews": list(outcome.pending_reviews),
                "next": (
                    "a qualified reviewer must approve the plan decision; this invocation's "
                    "settlement applies it then. You may explicitly submit its effect_key "
                    "for your declared effect_receipt promise now; it is not an applied receipt. "
                    "Do not call knowledge_apply again for it"
                ),
            },
            "refusal": None,
        }

    async def settle_saved(
        self, live: LiveInvocation, *, fenced: bool = False
    ) -> tuple[FinalizationReport, tuple[str, ...]]:
        """WI-04: one settlement pass over a saved provider result (no model call, no write).

        Reconciles the attempt's open effects (receipt-first, read-only recovery authority),
        then finalizes once; while an effect stays unresolved nothing is recorded and the
        report is ``blocked``. Not fenced, open assessments are polled and late verdicts are
        recorded; the second element names the assessments still without a verdict. Fenced
        (a cancellation): open handles are cancelled, no assessment starts or is polled, and
        only an unresolved effect can hold the result.
        """

        live = await self.locate(live)
        live = await self.with_declared_obligations(live)
        if fenced:
            await self.cancel(live)
        await self.reconcile(live)
        access = self.access(live)
        native_pending: tuple[str, ...] = ()
        native_effects: tuple[dict[str, Any], ...] = ()
        if self.native is not None and not fenced:
            # W1 native write (provisional, ESCALATION H12): a plan decision that waited on a
            # qualified review is applied here, by this same invocation's origin, once usable.
            settled_native = await self.native.settle(
                access,
                attempt=int(self.clock().timestamp() * 1000),
                apply=self._applier(access),
            )
            native_pending = settled_native.pending_reviews
            native_effects = tuple(row.document() for row in settled_native.outcomes)
            await self.reconcile(live)
        identity = access.identity(live.obligations)
        unresolved = tuple(row.effect_key for row in await self._open_effects(live))
        report = await self.submissions.finalize(
            identity,
            None if fenced else access,
            unresolved_effects=unresolved,
            owes_nothing=live.evaluator,
        )
        report = replace(report, native_effects=native_effects)
        if report.blocked or fenced:
            return report, native_pending
        trusted: tuple[str, ...] = ()
        if self.trusted is not None:
            # WI-03: the exact KS reviews this saved result waits on (an evaluator still
            # unavailable raises; the settlement boundary records the wait and retries).
            passed = await self.trusted.settle(access, attempt=int(self.clock().timestamp() * 1000))
            trusted = tuple(pending_or_raise(passed))
        elif self.uncomposed_trusted is not None:
            # W1 D30: an evaluator credential is unset in this worker; a trusted-pinned revision
            # waits with the actionable cause (the boundary records the wait and retries).
            pending_or_raise(await self.uncomposed_trusted.settle(access, attempt=0))
        trusted = trusted + native_pending
        if not report.open_assessments:
            return report, trusted
        current = await self.submissions.refresh_assessments(identity, access)
        return report, trusted + tuple(
            summary.assessment.operation_id
            for summary in current
            if summary.assessment is not None
            and summary.assessment.state == "assessing"
            and summary.assessment.operation_id is not None
        )

    async def cancel(self, live: LiveInvocation) -> list[JournalRecord]:
        """Stop: no new calls, cancel open handles (incl. under review), reconcile effects.

        The cancel request id is derived from the attempt, so a repeated stop (or a stop
        after a restart) is the same idempotent cancellation.
        """

        live = await self.locate(live)
        access = self.access(live)
        request_id = f"stop:{live.run_id}:{live.operation_id}:{live.operation_attempt}"
        return await self.gateway.cancel(access, request_id)

    async def reconcile(self, live: LiveInvocation) -> list[KnowledgeResult]:
        """After the invocation ended: receipt-first lookup of its uncertain effects under a
        separate read-only recovery authority (design §5)."""

        live = await self.locate(live)
        results: dict[str, KnowledgeResult] = {}
        delay = self.reconcile_initial_delay
        for attempt in range(max(1, self.reconcile_attempts)):
            rows = await self._open_effects(live)
            if not rows:
                break
            recovery = self._recovery(live)
            for row in rows:
                results[row.effect_key] = await self.gateway.reconcile(row.effect_key, recovery)
            if all(results[row.effect_key].state in JOURNAL_TERMINAL for row in rows):
                break
            if attempt + 1 < self.reconcile_attempts:
                await self.sleep(delay)
                delay = min(delay * 2, self.reconcile_max_delay)
        return list(results.values())

    async def _open_effects(self, live: LiveInvocation) -> list[JournalRecord]:
        access = self.access(live)
        coordinates = access.coordinates()
        rows = await self.gateway.open_effects(
            access.scope,
            run_id=coordinates.run_id,
            operation_ref=coordinates.operation_ref,
            operation_attempt=coordinates.operation_attempt,
        )
        return [
            row for row in rows if row.state in {JournalState.DISPATCHED, JournalState.UNCERTAIN}
        ]

    def _recovery(self, live: LiveInvocation) -> RecoveryAccess:
        origin = self.access(live).origin
        return RecoveryAccess(
            installation_id=origin.installation_id,
            application_id=origin.application_id,
            tenant_id=origin.tenant_id,
            issuer=self.issuer,
            subject=f"{self.subject}:reconciler",
            authority_ref=f"recovery:{live.run_id}:{live.operation_attempt}",
            invocation_id=f"inv-{uuid4()}",
            authenticated_at=self.clock(),
            knowledge_installation_id=self.knowledge_installation_id,
        )

    # ------------------------------------------------------------------ helpers

    def _governors(self) -> Governors:
        deadline = (self.clock() + self.deadline).astimezone(UTC)
        return Governors(
            deadline=deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
            maxItems=self.max_items,
            partialResults="forbid",
            budget={"calls": 0, "tokens": 0, "costUsd": "0"},  # type: ignore[arg-type]
        )

    def _call(
        self,
        tool: str,
        parsed: _Args,
        access: InvocationAccess,
        scope: ReadScope | None = None,
    ) -> KnowledgeCall:
        operation = TOOL_OPERATIONS[tool]
        tenant = access.origin.tenant_id
        upstream: tuple[Any, ...] = ()
        payload: dict[str, JsonDocument]
        if isinstance(parsed, ReadArgs | DeriveArgs) or (
            isinstance(parsed, VerifyArgs) and parsed.handle is not None
        ):
            handle = getattr(parsed, "handle", None)
            digest = getattr(parsed, "digest", None)
            report = report_ref(
                SelectedItem(kind="handle", ref=str(handle), digest=str(digest)), tenant=tenant
            )
            if report is None:
                raise AmbiguousHandle(f"{handle} is not a report handle")
            if scope is not None and not scope.allows(str(handle), str(digest)):
                # An isolated receiver reaches only its sealed plan's reports, by any tool.
                raise ReadOutOfScope(f"{handle} is not in this receiver's sealed plan")
            upstream = (report,)
        if isinstance(parsed, ReadArgs):
            # readSelected (selected-report-read/v2) under the receiver plan's purpose; an
            # independent evaluator reaches only the reports its sealed plan holds.
            report = upstream[0]

            def member(item: MemberArg) -> Ref:
                return Ref(
                    kind=item.kind,
                    id=item.id,
                    version=item.version,
                    digest=item.digest,
                    tenant=report.tenant,
                    binding=report.binding,
                )

            assertions = tuple(member(m) for m in parsed.members if m.kind == "assertion")
            evidence = tuple(member(m) for m in parsed.members if m.kind == "fragment")
            payload = selected_read_payload(
                report,
                purpose="dependent_input" if scope is None else scope.purpose,
                assertions=assertions if parsed.members else None,
                evidence=evidence if parsed.members else None,
            )
        elif isinstance(parsed, DeriveArgs):
            payload = {"report": upstream[0].model_dump(mode="json"), "mapping": parsed.mapping}
        else:
            assert isinstance(parsed, VerifyArgs)
            payload = {"claims": list(parsed.claims)}
        # `report_register` never passes here: its content is host-canonicalized (W1 D1).
        return KnowledgeCall(
            operation=operation,
            capability_pin=self.capability_pins.get(tool, f"knowledge.{tool}@1"),
            native_contract=NATIVE_CONTRACTS[tool],
            payload=payload,
            governors=self._governors(),
            upstream=upstream,
        )

    async def _register_call(self, parsed: RegisterArgs, access: InvocationAccess) -> KnowledgeCall:
        """W1 D1: the model submitted report content only; the host computes every digest.

        The effect key is over the model's exact content, and the assertions' producer is the
        effect's originating origin (an earlier dispatch's, sealed in its bytes, else this
        attempt's), so a retried registration of the same content is the same bytes and key.
        """

        content = dict(parsed.report)
        pin = self.capability_pins.get("report_register", "knowledge.report_register@1")
        try:
            content_digest = digest_canonical(content)
        except ValueError as error:
            raise RegistrationRefused(
                "REGISTRATION_MALFORMED", f"the content is not canonical JSON: {error}"
            ) from None
        effect_key = mint_effect_key(access.origin, pin, content_digest)
        producer = await self.gateway.originating_origin(access.scope, effect_key)
        payload = canonical_registration(
            content,
            tenant=access.origin.tenant_id,
            binding=self.gateway.binding,
            producer=producer or access.wire_origin(),
        )
        use, audience = _declared_use(payload)
        return KnowledgeCall(
            operation="report.register",
            capability_pin=pin,
            native_contract=NATIVE_CONTRACTS["report_register"],
            payload=payload,
            governors=self._governors(),
            effect_key=effect_key,
            use=use,
            audience=audience,
        )

    async def _with_stored_receipt(
        self, tool: str, result: KnowledgeResult, live: LiveInvocation
    ) -> KnowledgeResult | dict[str, Any]:
        """W1 review S1: the settled receipt of a replayed success, loaded read-only.

        The journal keeps only the receipt's ref and digest, so the replay reads the receipt
        back (``receipt.get`` under the run's read-only recovery authority, nothing re-sent)
        and keeps it only when it is the journal's exact receipt; then the result carries the
        same affected handles and receipt digest as the original call (a fresh attempt or a
        compacted context gets usable handles). When the receipt cannot be proven, the replay
        is a typed refusal, never ``ok: true`` without handles: ``RECEIPT_UNAVAILABLE``
        (refused, not found, unresolved or unreachable; ``retryable`` says whether a later call
        may succeed), ``RECEIPT_DIGEST_MISSING`` (the journal holds no digest to check against)
        or ``RECEIPT_DIGEST_MISMATCH``. A settlement that recorded no receipt at all (a status
        settlement) replays as before.
        """

        journal = result.journal
        if journal is None or journal.terminal_receipt_ref is None:
            return result
        key = journal.effect_key

        def refused(code: str, message: str, *, retryable: bool) -> dict[str, Any]:
            document = _refusal(tool, code, message, effect_key=key)
            document["refusal"]["retryable"] = retryable
            document["refusal"]["replayed"] = True
            return document

        if journal.receipt_digest is None:
            return refused(
                "RECEIPT_DIGEST_MISSING",
                "the settled effect's journal holds no receipt digest, so its receipt cannot be "
                "proven; its handles are not returned",
                retryable=False,
            )
        try:
            lookup = await self.gateway.receipt(key, self._recovery(live))
        except KnowledgeRefused as error:
            return refused(
                "RECEIPT_UNAVAILABLE",
                f"the settled receipt could not be read back: {error.code}",
                retryable=error.code in {"CAPABILITY_UNAVAILABLE", "UNRESOLVED_EFFECT"},
            )
        except (KnowledgeTransportError, OSError, TimeoutError):
            return refused(
                "RECEIPT_UNAVAILABLE",
                "the binding is unreachable; the settled receipt could not be read back",
                retryable=True,
            )
        if not isinstance(lookup, ReceiptFound):
            # None (transport error or protocol refusal inside the lookup) and `unresolved`
            # may clear later; `not_found` for a settled effect will not.
            return refused(
                "RECEIPT_UNAVAILABLE",
                "the settled receipt was not found"
                if isinstance(lookup, ReceiptNotFound)
                else "the settled receipt could not be read back now",
                retryable=not isinstance(lookup, ReceiptNotFound),
            )
        receipt = lookup.receipt
        if receipt.digest != journal.receipt_digest:
            return refused(
                "RECEIPT_DIGEST_MISMATCH",
                "the binding's receipt is not the settled receipt the journal recorded; its "
                "handles are not returned",
                retryable=False,
            )
        return replace(result, receipt=receipt, lookup=lookup)

    async def _record_production(
        self, access: InvocationAccess, result: KnowledgeResult, *, replayed: bool = False
    ) -> None:
        """Preserve the immutable first creator; this registration is a caller and receipt.

        A distinct report may reuse content-addressed body bytes. Registration-specific storage
        checks exact kind/digest under a subject lock rather than racing a read then insert.
        """

        del replayed  # Effect replay and distinct registration both preserve existing producers.
        if self.lineage is None or result.receipt is None or result.journal is None:
            return
        original = result.journal.originating_origin
        coordinates = original.mission
        if (
            coordinates is None
            or original.issuer != access.origin.issuer
            or original.applicationId != access.origin.application_id
            or str(original.tenantId) != access.origin.tenant_id
            or str(original.installationId)
            != (self.knowledge_installation_id or access.origin.installation_id)
        ):
            raise ValueError("registration producer journal origin is outside the invocation scope")
        # The wire origin names the KS installation; lineage uses the verified MC scope.
        # Toolset origins carry no parent_invocation_id. Every creator coordinate comes from
        # the durable originating call, never the recovery caller's attempt or operation.
        producer = InvocationOrigin(
            issuer=original.issuer,
            installation_id=access.origin.installation_id,
            application_id=original.applicationId,
            tenant_id=str(original.tenantId),
            mission_id=coordinates.missionId,
            run_id=coordinates.runId,
            activation_id=coordinates.activationId,
            operation_id=coordinates.operationId,
            attempt=coordinates.operationAttempt,
            generation=coordinates.executionGeneration,
            lane=coordinates.lane,
        )
        receipt = result.receipt
        refs = list(receipt.affectedRefs)
        if receipt.nativeReceiptRef.kind == "report" and receipt.nativeReceiptRef not in refs:
            refs.append(receipt.nativeReceiptRef)
        receipt_ref = result.journal.terminal_receipt_ref or receipt.receipt_ref()
        entries: list[LineageEntry] = []
        for ref in refs:
            handle = f"kh:{ref.binding}/{ref.kind}/{ref.id}@{ref.version}"
            common = {
                "subject_kind": _subject_kind(ref.kind),
                "subject_digest": ref.digest,
                "run_id": access.origin.run_id,
                "knowledge_operation_id": result.journal.knowledge_operation_id,
                "effect_key": result.journal.effect_key,
            }
            entries.append(
                LineageEntry(
                    fact=LineageFact(
                        subject_handle=handle,
                        role=ProvenanceRole.PRODUCER,
                        actor_kind=ActorKind.ORIGIN,
                        actor_ref="mc-inv:" + producer.digest(),
                        actor_origin=producer,
                        fact={"act": "production", "receipt": receipt_ref},
                    ),
                    **(common | {"run_id": producer.run_id}),
                )
            )
            entries.append(
                LineageEntry(
                    fact=LineageFact(
                        subject_handle=handle,
                        role=ProvenanceRole.CALLER,
                        actor_kind=ActorKind.ORIGIN,
                        actor_ref=access.invocation_ref,
                        actor_origin=access.origin,
                        fact={"act": "registration", "receipt": receipt_ref},
                    ),
                    **common,
                )
            )
            entries.append(
                LineageEntry(
                    fact=LineageFact(
                        subject_handle=handle,
                        role=ProvenanceRole.RECEIPT,
                        actor_kind=ActorKind.RECEIPT,
                        actor_ref=receipt_ref,
                        fact={"receipt_digest": receipt.digest},
                    ),
                    **common,
                )
            )
        await self.lineage.record_registration(
            access.scope, entries, actor_ref="mission-control:knowledge-lineage", at=self.clock()
        )

    async def _submit_named(
        self,
        parsed: SubmitArgs,
        access: InvocationAccess,
        tool_call_id: str,
        position: str | None,
    ) -> dict[str, Any]:
        """A run with registered promises: the lane tool enters ``submit_output`` itself."""

        assert parsed.obligation is not None
        obligation = await self.submissions.pinned_obligation(access, parsed.obligation)
        if obligation is None:
            valid = await self._submittable_keys(access, position)
            document = _refusal(
                "submit_output",
                "OBLIGATION_UNDECLARED",
                f"no admitted promise {parsed.obligation} is pinned for this invocation; "
                "obligation is the full promise key <owner position>.<promise name>, one of: "
                + (", ".join(valid) or "none"),
            )
            document["refusal"]["valid_obligations"] = list(valid)
            return document
        reports = [
            item
            for item in parsed.items
            if isinstance(item, SelectedItem) and item.kind == "handle" and "/report/" in item.ref
        ]
        if reports and len(parsed.items) != 1:
            return _refusal(
                "submit_output",
                "SCHEMA_UNSUPPORTED",
                "a report must be the only selected item; collections are unsupported",
            )
        name = parsed.deliverable or obligation.key.rsplit(".", 1)[-1]
        try:
            request = SubmitOutput(
                submission_key=tool_call_id,
                obligation_key=parsed.obligation,
                mode=parsed.mode,
                expected_head=parsed.expected_head,
                items=tuple(
                    _candidate(
                        item,
                        obligation,
                        name if len(parsed.items) == 1 else f"{name}-{index + 1}",
                    )
                    for index, item in enumerate(parsed.items)
                ),
            )
        except ValueError as error:
            return _refusal("submit_output", "SCHEMA_UNSUPPORTED", str(error))
        ack = await self.submissions.submit_output(access, request, position=position)
        if ack.status != "accepted":
            return _named_refusal(ack)
        if ack.submission_id is not None:
            # Selecting a report another invocation produced is an adoption (lineage 0051).
            await self._record_adoption(access, parsed, ack.submission_id)
        return {
            "tool": "submit_output",
            "ok": True,
            "result": {
                "submission_id": ack.submission_id,
                "obligation": parsed.obligation,
                "revisions": [item.model_dump(mode="json") for item in ack.revisions],
                "next_actions": list(ack.next_actions),
                "status": ack.status,
                "meaning": "recorded_draft",
                "mode": parsed.mode,
                "findings": [item.model_dump(mode="json") for item in ack.findings],
            },
            "refusal": None,
        }

    async def _submittable_keys(
        self, access: InvocationAccess, position: str | None
    ) -> tuple[str, ...]:
        """W1 D13: the promise keys this invocation may submit (pinned; owned by its position
        when the host bound one), for the refusal of an undeclared key."""

        view = await self.submissions.inspect_invocation(access, position=position)
        if not view["ok"]:
            return ()
        return tuple(item["obligation"]["key"] for item in view["result"]["obligations"])

    async def _record_adoption(
        self, access: InvocationAccess, parsed: SubmitArgs, submission_id: str
    ) -> None:
        """Selecting a report another invocation produced is an adoption, never production."""

        if self.lineage is None:
            return
        entries: list[LineageEntry] = []
        for item in parsed.items:
            if item.kind != "handle":
                continue
            facts = await self.lineage.facts(access.scope, item.ref)
            produced_here = any(
                fact.role is ProvenanceRole.PRODUCER and fact.actor_ref == access.invocation_ref
                for fact in facts
            )
            if produced_here:
                continue
            entries.append(
                LineageEntry(
                    fact=LineageFact(
                        subject_handle=item.ref,
                        role=ProvenanceRole.ADOPTER,
                        actor_kind=ActorKind.OBLIGATION,
                        actor_ref=f"{access.invocation_ref}:{parsed.obligation}",
                        fact={"act": ADOPTION_ACT, "submission": submission_id},
                    ),
                    subject_kind=_subject_kind(
                        item.ref.split("/", 2)[1] if "/" in item.ref else ""
                    ),
                    subject_digest=item.digest,
                    run_id=access.origin.run_id,
                )
            )
        if entries:
            await self.lineage.record(
                access.scope,
                entries,
                actor_ref="mission-control:knowledge-lineage",
                at=self.clock(),
            )

    async def _submit(
        self,
        parsed: SubmitArgs,
        access: InvocationAccess,
        tool_call_id: str,
        position: str | None = None,
    ) -> dict[str, Any]:
        if parsed.action == "inspect":
            return await self.submissions.inspect_invocation(
                access, position=position, obligation_key=parsed.obligation
            )
        assert parsed.obligation is not None
        if await self.submissions.promises_registered(access.scope, access.origin.run_id):
            return await self._submit_named(parsed, access, tool_call_id, position)
        if parsed.mode != "final" or parsed.expected_head is not None:
            return _refusal(
                "submit_output",
                "SCHEMA_UNSUPPORTED",
                "progressive and expected_head require registered named promises",
            )
        selected = tuple(item for item in parsed.items if isinstance(item, SelectedItem))
        if len(selected) != len(parsed.items):
            return _refusal(
                "submit_output",
                "SCHEMA_UNSUPPORTED",
                "inline and code-change candidates need the run's registered promises",
            )
        try:
            record = await self.submissions.submit(
                access,
                parsed.obligation,
                OutputSelection(items=selected),
                tool_call_id,
            )
        except (AmbiguousHandle, UnsupportedReportSelection) as error:
            return _refusal("submit_output", "SCHEMA_UNSUPPORTED", str(error))
        except SubmissionConflict:
            return _refusal("submit_output", "EFFECT_CONFLICT", "same tool call, other selection")
        except SubmissionClosed:
            return _refusal("submit_output", "CANCELLED", "the invocation is already finalized")
        await self._record_adoption(access, parsed, record.submission_id)
        return {
            "tool": "submit_output",
            "ok": True,
            "result": {
                "submission_id": record.submission_id,
                "obligation": record.obligation_id,
                "revision": record.revision,
                "selection_digest": record.selection_digest,
                "assessment_state": record.assessment_state,
            },
            "refusal": None,
        }


def _candidate(
    item: SelectedItem | InlineItem | CodeChangeItem, obligation: OutputObligation, name: str
) -> CandidateRef:
    """The exact candidate a tool item offers; the host fills digests the model left out."""

    if isinstance(item, SelectedItem):
        return CandidateRef(
            deliverable_id=name,
            form=obligation.form,
            kind=item.kind,
            ref=item.ref,
            digest=item.digest,
        )
    if isinstance(item, InlineItem):
        schema = obligation.contract.schema_pin
        schema_ref = item.schema_ref or (
            schema.ref if schema is not None and item.value is not None else None
        )
        digest = item.digest or (
            text_digest(item.text) if item.text is not None else value_digest(item.value)
        )
        return CandidateRef(
            deliverable_id=name,
            form=obligation.form,
            kind="inline",
            digest=digest,
            text=item.text,
            value=item.value,
            schema_ref=schema_ref,
            media_type=item.media_type,
            effect_key=item.effect_key,
            receipt_ref=item.receipt_ref,
        )
    draft = CandidateRef(
        deliverable_id=name,
        form=obligation.form,
        kind="inline",
        digest="sha256:" + "0" * 64,
        repository=item.repository,
        base=item.base,
        head=item.head,
        patch_digest=item.patch_digest,
        changed_paths=tuple(item.changed_paths),
    )
    return draft.model_copy(update={"digest": item.digest or code_change_digest(draft)})


def _named_refusal(ack: SubmissionAck) -> dict[str, Any]:
    error = ack.error
    assert error is not None
    document = _refusal("submit_output", error.code.value, error.safe_message)
    document["refusal"].update(error.model_dump(mode="json", exclude={"code", "safe_message"}))
    document["refusal"]["findings"] = [item.model_dump(mode="json") for item in ack.findings]
    document["refusal"]["next_actions"] = list(ack.next_actions)
    return document


def validation_refusal(tool: str, error: ValidationError) -> dict[str, Any]:
    """Safe argument locations and reachable producer repair; never echo model values."""
    paths = tuple(".".join(str(part) for part in item["loc"]) for item in error.errors())
    if tool == "submit_output" and any(not path for path in paths):
        paths = (*(path for path in paths if path), "action", "obligation", "items")
    document = _refusal(
        tool,
        "INVALID_ENVELOPE",
        "repair the indicated arguments",
        field_paths=paths,
    )
    document["refusal"].update(
        {
            "retry_state": "repairable",
            "recovery_owner": "producer",
            "available_actions": [tool],
        }
    )
    return document


def _subject_kind(kind: str) -> str:
    return kind if kind in {"artifact", "report", "assertion"} else "output"


def _refusal(
    tool: str,
    code: str,
    message: str,
    *,
    effect_key: str | None = None,
    field_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    refusal: dict[str, Any] = {"code": code, "message": _redacted(message, 500)}
    if field_paths:
        refusal["field_paths"] = list(dict.fromkeys(field_paths))[:_REFUSAL_ENTRIES]
    return {
        "tool": tool,
        "ok": False,
        "result": None if effect_key is None else {"effect_key": effect_key},
        "refusal": refusal,
    }


__all__ = [
    "NATIVE_CONTRACTS",
    "PRODUCER_TOOLS",
    "PRODUCER_TOOL_CAPABILITIES",
    "TOOL_ARGUMENTS",
    "TOOL_DESCRIPTIONS",
    "TOOL_NAMES",
    "TOOL_OPERATIONS",
    "ArgumentCoercion",
    "ArgumentCoercionRefused",
    "KnowledgeToolset",
    "LiveInvocation",
    "coerce_object_arguments",
    "coerce_with_shapes",
    "coercion_refusal",
    "model_argument_shapes",
    "object_argument_shapes",
    "refusal_view",
    "validation_refusal",
]

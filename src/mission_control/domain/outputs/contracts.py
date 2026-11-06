"""Closed typed output-contract model (OUTPUT-CONTRACTS §2; ADR-0058, ADR-0010).

Every type here is closed (``extra=forbid``) and frozen. Digests use the canonical JSON of
``domain.authoring.canonical`` with a domain-separation tag, never include their own digest,
later assessments or mutable status. The eight general forms are representation categories;
domain meaning (a report, a judgment, an index) is a substantive contract over them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from mission_control.domain.authoring.canonical import sha256_digest, stable_json_dump

DIGEST_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
KEY_PATTERN: Final = r"^[a-z0-9][a-z0-9._:-]{0,199}$"
# OUTPUT-CONTRACTS §2: the installation warning default and the maximum distinct cardinality.
CARDINALITY_WARNING: Final = 8
CARDINALITY_MAXIMUM: Final = 64
PROMISE_SET_SCHEMA: Final = "mc.output_promises.v1"
IDENTITY_RULE_DELIVERABLE_ID: Final = "mc.identity.deliverable-id@1"


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def tagged_digest(tag: str, value: Any) -> str:
    """Domain-separated canonical digest: ``sha256(canonical({"tag", "value"}))``."""

    return sha256_digest({"tag": tag, "value": value})


class OutputForm(StrEnum):
    TEXT = "text"
    STRUCTURED = "structured"
    FILE = "file"
    COLLECTION = "collection"
    REFERENCE = "reference"
    CODE_CHANGE = "code_change"
    EFFECT_RECEIPT = "effect_receipt"
    CONTROL_RECORD = "control_record"


# Forms whose full fulfillment proof belongs to later work items. Their contract shape compiles
# and submissions are checked, but fulfillment truthfully reports "not yet fulfillable".
# WI-02 fulfills `file` through custody plus an actual receiving-backend read and resolves the
# exact issuer/scope/revision of `reference`; WI-03 fulfills `reference` through the current
# official use of that exact revision (`reference_uses`); WI-05 fulfills `effect_receipt` through
# the settled native effect (`effect_receipts`); WI-07 fulfills `collection` through independent
# per-member assessments under the authored aggregate rule (`domain.outputs.collections`). Every
# form now has its proof; the map stays the one place a future deferral is declared.
DEFERRED_FORMS: Final[dict[OutputForm, str]] = {}
# WI-07: the aggregate rule a collection's member requirement declares in its ``parameters``
# (``{"aggregate": "all"}``, the default, or ``{"aggregate": "at_least", "minimum": k}``).
AGGREGATE_RULES: Final = ("all", "at_least")
# WI-07 review B2/N1: the validators of the application's trusted-judgment pin
# (`deployments/<app>/application.toml` `assessment_pin`). A collection member requirement under
# one of them is proven only by a standing member assessment the trusted bridge recorded citing an
# exact KS decision that the host verified standing for that member's exact ref and digest. There
# is no default pin: ``None`` treats every validator as trusted (fail closed).
TrustedValidators = frozenset[str] | None
# Per exact member (ref, digest): the KS decision ids verified standing for it now.
MemberDecisions = Mapping[tuple[str, str], frozenset[str]]


class Enforcement(StrEnum):
    """Required unmet blocks; expected unmet is a visible shortfall; optional absence is silent."""

    REQUIRED = "required"
    EXPECTED = "expected"
    OPTIONAL = "optional"

    @property
    def strength(self) -> int:
        return {"required": 2, "expected": 1, "optional": 0}[self.value]


class EvaluationScope(StrEnum):
    INVOCATION = "invocation"
    CYCLE = "cycle"
    ITERATION = "iteration"
    ACTIVATION = "activation"
    ACCUMULATED_STAGE = "accumulated_stage"
    GOAL = "goal"
    MISSION = "mission"


class Pin(_Closed):
    id: str = Field(min_length=1, max_length=512)
    version: int = Field(ge=1)
    digest: str = Field(pattern=DIGEST_PATTERN)


class SchemaPin(_Closed):
    """An exact schema: its ref (name@version) and, when bound, its body and digest."""

    ref: str = Field(min_length=1, max_length=512)
    digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    body: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def _exact(self) -> SchemaPin:
        if (self.digest is None) != (self.body is None):
            raise ValueError("a bound schema carries both its body and its digest")
        if self.body is not None and sha256_digest(self.body) != self.digest:
            raise ValueError("schema body differs from its pinned digest")
        return self

    @property
    def bound(self) -> bool:
        return self.body is not None


class Cardinality(_Closed):
    min: int = Field(default=1, ge=0)
    max: int = Field(default=1, ge=1, le=CARDINALITY_MAXIMUM)

    @model_validator(mode="after")
    def _ordered(self) -> Cardinality:
        if self.min > self.max:
            raise ValueError("cardinality min must not exceed max")
        return self


class Requirement(_Closed):
    """One promised guarantee, proven by an independent assessment of the exact subject."""

    key: str = Field(pattern=KEY_PATTERN)
    validator: str = Field(min_length=1, max_length=512)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    required: bool = True
    # ``member``: a nested guarantee every exact member an index lists must pass.
    subject: Literal["deliverable", "set", "member"] = "deliverable"


def aggregate_rule(requirement: Requirement) -> tuple[str, int | None]:
    """The authored aggregate rule of a collection member requirement (WI-07, §§2, 4).

    ``("all", None)``: every exact member must pass (the default: one held or rejected member
    keeps the collection unfulfilled). ``("at_least", k)``: at least ``k`` distinct members must
    pass; the others stay visible per member and never count. Anything else refuses.
    """

    rule = requirement.parameters.get("aggregate", "all")
    if rule not in AGGREGATE_RULES:
        raise ValueError(f"member requirement {requirement.key} names no aggregate rule: {rule!r}")
    minimum = requirement.parameters.get("minimum")
    if rule == "all":
        if minimum is not None:
            raise ValueError("an `all` aggregate rule takes no minimum")
        return "all", None
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise ValueError("an `at_least` aggregate rule names a positive integer minimum")
    return "at_least", minimum


def collection_document(members: Sequence[Any], value: Any = None) -> dict[str, Any]:
    """The canonical manifest document of an inline collection (WI-07): its member *set*
    (order-free, so a reordered manifest is the same content) and its optional value. Members
    are ``MemberRef`` objects or their ``{"ref", "digest"}`` dumps."""

    pairs = sorted(
        [item["ref"], item["digest"]] if isinstance(item, dict) else [item.ref, item.digest]
        for item in members
    )
    return {"tag": "mc.collection.v1", "value": {"members": pairs, "value": value}}


def collection_digest(members: Sequence[Any], value: Any = None) -> str:
    """The exact digest of an inline collection manifest (``collection_document``)."""

    return sha256_digest(collection_document(members, value))


class CoverageContract(_Closed):
    """The promised subject population of a structured output (exact closure, never a count)."""

    subjects: tuple[str, ...] = Field(min_length=1)
    pointer: str = Field(pattern=r"^(/[^/]+)+$")
    key: str | None = Field(default=None, min_length=1)

    @field_validator("subjects")
    @classmethod
    def _canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("coverage subjects are distinct")
        return tuple(sorted(value))


class MemberGuarantee(_Closed):
    """Nested guarantees of an index: each exact member it references must pass these keys
    (the contract's ``member`` requirements)."""

    pointer: str = Field(pattern=r"^(/[^/]+)+$")
    requirement_keys: tuple[str, ...] = Field(min_length=1)


class OutputContract(_Closed):
    form: OutputForm
    template_pins: tuple[Pin, ...] = ()
    media_type: str | None = Field(default=None, min_length=1, max_length=255)
    encoding: Literal["utf-8"] | None = None
    max_bytes: int | None = Field(default=None, ge=1)
    schema_pin: SchemaPin | None = None
    requirements: tuple[Requirement, ...] = ()
    coverage: CoverageContract | None = None
    member_contract: MemberGuarantee | None = None
    repository: str | None = Field(default=None, min_length=1)
    # Named capabilities whose exact receipts may be associated with a missing submission.
    receipt_capabilities: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _form_shape(self) -> OutputContract:
        keys = [item.key for item in self.requirements]
        if len(keys) != len(set(keys)):
            raise ValueError("requirement keys are unique within a contract")
        needs_schema = {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD}
        if self.form in needs_schema and self.schema_pin is None:
            raise ValueError(f"a {self.form} contract pins its schema")
        valued = {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD}
        if self.form not in valued and self.member_contract is not None:
            raise ValueError("nested member guarantees apply to structured values")
        if self.form not in valued | {OutputForm.COLLECTION} and self.coverage is not None:
            raise ValueError("coverage applies to structured values and collections")
        if self.form is OutputForm.TEXT and self.schema_pin is not None:
            raise ValueError("a text contract checks bytes, not a schema")
        if self.form is not OutputForm.TEXT and (
            self.encoding is not None or self.max_bytes is not None
        ):
            raise ValueError("encoding and max_bytes are text checks")
        if self.form is not OutputForm.CODE_CHANGE and self.repository is not None:
            raise ValueError("repository identity belongs to a code_change contract")
        if self.extensions:
            raise ValueError("unknown executable contract extensions are rejected")
        member_keys = {item.key for item in self.requirements if item.subject == "member"}
        if self.form is OutputForm.COLLECTION:
            # A collection's members are its exact manifest entries (``CandidateRef.members``);
            # each member requirement names its aggregate rule (WI-07).
            for item in self.requirements:
                if item.subject == "member":
                    aggregate_rule(item)
            return self
        if self.member_contract is None and member_keys:
            raise ValueError("member requirements need a nested member contract")
        if self.member_contract is not None and (
            set(self.member_contract.requirement_keys) != member_keys
        ):
            raise ValueError(
                "nested member guarantees name exactly the contract's member requirements"
            )
        return self

    @property
    def digest(self) -> str:
        return tagged_digest("mc.output_contract.v1", stable_json_dump(self))


class OutputObligation(_Closed):
    """``OutputObligation@2``: one named, pinned promise of an owner position."""

    key: str = Field(pattern=KEY_PATTERN)
    revision: int = Field(default=1, ge=1)
    owner_position: str = Field(min_length=1, max_length=512)
    evaluation_scope: EvaluationScope = EvaluationScope.INVOCATION
    contract: OutputContract
    enforcement: Enforcement = Enforcement.REQUIRED
    cardinality: Cardinality = Field(default_factory=Cardinality)
    identity_rule_pin: str = IDENTITY_RULE_DELIVERABLE_ID
    applicability: Literal["always"] = "always"

    @property
    def form(self) -> OutputForm:
        return self.contract.form

    @property
    def contract_digest(self) -> str:
        return self.contract.digest

    @property
    def digest(self) -> str:
        return tagged_digest("mc.output_obligation.v2", stable_json_dump(self))

    def document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ---------------------------------------------------------------- completion (closed AST)


class AllOf(_Closed):
    op: Literal["all"] = "all"
    items: tuple[CompletionExpr, ...] = Field(min_length=1)


class AnyOf(_Closed):
    op: Literal["any"] = "any"
    items: tuple[CompletionExpr, ...] = Field(min_length=1)


class ObligationLeaf(_Closed):
    op: Literal["obligation"] = "obligation"
    obligation: str = Field(pattern=KEY_PATTERN)


class AssessmentLeaf(_Closed):
    op: Literal["assessment"] = "assessment"
    obligation: str = Field(pattern=KEY_PATTERN)
    requirement: str = Field(pattern=KEY_PATTERN)
    allowed: tuple[Literal["pass", "review"], ...] = ("pass",)


class IntegrityLeaf(_Closed):
    op: Literal["integrity"] = "integrity"
    check: str = Field(min_length=1, max_length=512)


class HumanResolutionLeaf(_Closed):
    op: Literal["human_resolution"] = "human_resolution"
    task: str = Field(min_length=1, max_length=512)


class CriterionLeaf(_Closed):
    op: Literal["criterion"] = "criterion"
    criterion: str = Field(min_length=1, max_length=512)


CompletionExpr = Annotated[
    AllOf
    | AnyOf
    | ObligationLeaf
    | AssessmentLeaf
    | IntegrityLeaf
    | HumanResolutionLeaf
    | CriterionLeaf,
    Field(discriminator="op"),
]
AllOf.model_rebuild()
AnyOf.model_rebuild()


def referenced_obligations(expression: BaseModel) -> frozenset[str]:
    if isinstance(expression, AllOf | AnyOf):
        return frozenset().union(*(referenced_obligations(item) for item in expression.items))
    if isinstance(expression, ObligationLeaf | AssessmentLeaf):
        return frozenset({expression.obligation})
    return frozenset()


class OutputPromiseSet(_Closed):
    """The compiled, inspectable promises of one admitted configuration.

    The completion expression is closed over declared vocabularies: obligation leaves name
    declared promises, assessment leaves declared requirements, and integrity, human and
    criterion leaves the declared check, task and criterion names. Every *required* promise is a
    conjunct of the expression (reachable from its root through ``all`` only), so a required
    promise that is unmet can never coexist with a satisfied completion.
    """

    schema_version: Literal["mc.output_promises.v1"] = PROMISE_SET_SCHEMA
    obligations: tuple[OutputObligation, ...]
    completion: CompletionExpr
    integrity_checks: tuple[str, ...] = ()
    human_tasks: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _closed(self) -> OutputPromiseSet:
        keys = [item.key for item in self.obligations]
        if len(keys) != len(set(keys)):
            raise ValueError("obligation keys are unique within a promise set")
        unknown = referenced_obligations(self.completion) - set(keys)
        if unknown:
            raise ValueError(f"completion names undeclared obligations: {sorted(unknown)}")
        for leaf in _leaves(self.completion, AssessmentLeaf):
            obligation = next(item for item in self.obligations if item.key == leaf.obligation)
            requirement = next(
                (r for r in obligation.contract.requirements if r.key == leaf.requirement), None
            )
            if requirement is None:
                raise ValueError(
                    f"completion names requirement {leaf.requirement!r} that obligation "
                    f"{leaf.obligation!r} does not declare"
                )
            if "review" in leaf.allowed and requirement.required:
                # Fulfillment decides a required requirement by ``pass``; admitting a review
                # disposition is an authored choice over a non-required requirement only.
                raise ValueError(
                    f"requirement {leaf.requirement!r} is required (decided by pass); only a "
                    "non-required requirement may admit a review disposition"
                )
        vocabularies = (
            (IntegrityLeaf, "check", self.integrity_checks, "integrity check"),
            (HumanResolutionLeaf, "task", self.human_tasks, "human task"),
            (CriterionLeaf, "criterion", self.criteria, "criterion"),
        )
        for kind, attribute, declared, label in vocabularies:
            for leaf in _leaves(self.completion, kind):
                if getattr(leaf, attribute) not in declared:
                    raise ValueError(
                        f"completion names undeclared {label} {getattr(leaf, attribute)!r}"
                    )
        conjuncts = _conjunct_obligations(self.completion)
        uncovered = sorted(
            item.key
            for item in self.obligations
            if item.enforcement is Enforcement.REQUIRED and item.key not in conjuncts
        )
        if uncovered:
            raise ValueError(
                f"required promises {uncovered} must be conjuncts of the completion expression"
            )
        return self

    def obligation(self, key: str) -> OutputObligation | None:
        return next((item for item in self.obligations if item.key == key), None)

    @property
    def digest(self) -> str:
        return tagged_digest(PROMISE_SET_SCHEMA, stable_json_dump(self))


def _leaves(expression: BaseModel, kind: type[Any]) -> tuple[Any, ...]:
    if isinstance(expression, AllOf | AnyOf):
        return tuple(leaf for item in expression.items for leaf in _leaves(item, kind))
    return (expression,) if isinstance(expression, kind) else ()


def _conjunct_obligations(expression: BaseModel) -> frozenset[str]:
    """Obligation leaves reachable from the root through ``all`` nodes only."""

    if isinstance(expression, AllOf):
        return frozenset().union(*(_conjunct_obligations(item) for item in expression.items))
    if isinstance(expression, ObligationLeaf):
        return frozenset({expression.obligation})
    return frozenset()


# ---------------------------------------------------------------- candidates and submission


class MemberRef(_Closed):
    """An exact member an index or collection references (handle or revision + digest)."""

    ref: str = Field(min_length=1, max_length=2048)
    digest: str = Field(pattern=DIGEST_PATTERN)


class CandidateRef(_Closed):
    """One exact candidate a producer offers (``SubmitOutput.items[]``).

    ``kind`` says how the bytes are reached: ``inline`` (text or a JSON value carried here),
    ``handle`` (an exact ``kh:`` knowledge handle), ``path`` (a declared workspace path) or
    ``native_id`` (a bare native id, resolved only through one exact admitted binding). The
    host injects attribution; a candidate carries no actor, authority or merge/push field.
    """

    deliverable_id: str = Field(pattern=KEY_PATTERN)
    form: OutputForm
    kind: Literal["inline", "handle", "path", "native_id"]
    digest: str = Field(pattern=DIGEST_PATTERN)
    ref: str | None = Field(default=None, min_length=1, max_length=2048)
    media_type: str | None = Field(default=None, min_length=1, max_length=255)
    encoding: Literal["utf-8"] | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    text: str | None = None
    value: JsonValue | None = None
    schema_ref: str | None = Field(default=None, min_length=1, max_length=512)
    # reference
    issuer: str | None = Field(default=None, min_length=1, max_length=255)
    native_kind: str | None = Field(default=None, pattern=r"^[a-z_]{1,64}$")
    native_revision: str | None = Field(default=None, min_length=1, max_length=255)
    # code_change
    repository: str | None = Field(default=None, min_length=1, max_length=512)
    base: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    head: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    patch_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    changed_paths: tuple[str, ...] = ()
    # collection / effect_receipt
    members: tuple[MemberRef, ...] = ()
    effect_key: str | None = Field(default=None, min_length=1, max_length=512)
    receipt_ref: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def _addressed(self) -> CandidateRef:
        if (self.kind == "inline") == (self.ref is not None):
            raise ValueError("an inline candidate carries content, any other names its ref")
        if self.kind != "inline" and (self.text is not None or self.value is not None):
            raise ValueError("only an inline candidate carries its content")
        return self

    def document(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True, exclude_defaults=True) | {
            "deliverable_id": self.deliverable_id,
            "form": self.form.value,
            "kind": self.kind,
            "digest": self.digest,
        }


class SubmitOutput(_Closed):
    """``SubmitOutput@2``: the single authoritative progressive/final submission act."""

    submission_key: str = Field(min_length=1, max_length=512)
    obligation_key: str = Field(pattern=KEY_PATTERN)
    mode: Literal["progressive", "final"] = "final"
    expected_head: str | None = Field(default=None, min_length=1, max_length=64)
    items: tuple[CandidateRef, ...] = Field(min_length=1)
    derivation_refs: tuple[str, ...] = ()

    def document(self) -> dict[str, Any]:
        """The canonical payload the submission key binds (same key + other bytes refuses)."""

        return {
            "obligation_key": self.obligation_key,
            "mode": self.mode,
            "expected_head": self.expected_head,
            "items": [item.document() for item in self.items],
            "derivation_refs": list(self.derivation_refs),
        }


class AdmittedBinding(_Closed):
    """One admitted invocation binding a bare native id may resolve through."""

    binding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,119}$")
    issuer: str = Field(min_length=1)
    native_kinds: tuple[str, ...] = Field(min_length=1)
    revision: str = Field(pattern=r"^[a-z][a-z0-9_.-]*\.v[0-9]+$")


class OutputErrorCode(StrEnum):
    OBLIGATION_UNDECLARED = "OBLIGATION_UNDECLARED"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    POSITION_UNBOUND = "POSITION_UNBOUND"
    INVOCATION_UNPINNED = "INVOCATION_UNPINNED"
    SCHEMA_UNVALIDATED = "SCHEMA_UNVALIDATED"
    RUN_MISMATCH = "RUN_MISMATCH"
    OLDER_REVISION = "OLDER_REVISION"
    ASSESSOR_UNAUTHORIZED = "ASSESSOR_UNAUTHORIZED"
    MEMBER_NOT_LISTED = "MEMBER_NOT_LISTED"
    DELEGATION_REQUIRED = "DELEGATION_REQUIRED"
    NO_PENDING_SUCCESSOR = "NO_PENDING_SUCCESSOR"
    SUCCESSOR_BREAKS_COMPLETION = "SUCCESSOR_BREAKS_COMPLETION"
    HOST_REQUIRED = "HOST_REQUIRED"
    FORM_MISMATCH = "FORM_MISMATCH"
    MISSING_FIELD = "MISSING_FIELD"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    ENCODING_INVALID = "ENCODING_INVALID"
    MEDIA_TYPE_MISMATCH = "MEDIA_TYPE_MISMATCH"
    SIZE_EXCEEDED = "SIZE_EXCEEDED"
    SCHEMA_PIN_MISMATCH = "SCHEMA_PIN_MISMATCH"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    SCHEMA_UNBOUND = "SCHEMA_UNBOUND"
    MEMBER_REF_NOT_EXACT = "MEMBER_REF_NOT_EXACT"
    REPOSITORY_MISMATCH = "REPOSITORY_MISMATCH"
    SELF_GRANTED_AUTHORITY = "SELF_GRANTED_AUTHORITY"
    AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE"
    UNRESOLVED_REFERENCE = "UNRESOLVED_REFERENCE"
    CARDINALITY_EXCEEDED = "CARDINALITY_EXCEEDED"
    DUPLICATE_DELIVERABLE = "DUPLICATE_DELIVERABLE"
    SUBMISSION_CONFLICT = "SUBMISSION_CONFLICT"
    STALE_HEAD = "STALE_HEAD"
    STALE_GENERATION = "STALE_GENERATION"
    INVOCATION_FINALIZED = "INVOCATION_FINALIZED"
    NOT_PROMOTABLE = "NOT_PROMOTABLE"
    SELF_ASSESSMENT = "SELF_ASSESSMENT"
    SUBJECT_UNKNOWN = "SUBJECT_UNKNOWN"
    PROMISES_CONFLICT = "PROMISES_CONFLICT"
    STALE_REVISION = "STALE_REVISION"
    SUCCESSOR_INVALID = "SUCCESSOR_INVALID"
    WEAKENING_UNAUTHORIZED = "WEAKENING_UNAUTHORIZED"
    SELF_WAIVER = "SELF_WAIVER"
    UNSAFE_BOUNDARY = "UNSAFE_BOUNDARY"
    TRANSFER_SUCCESSOR_UNSUPPORTED = "TRANSFER_SUCCESSOR_UNSUPPORTED"
    # WI-03 supersession authority: only the trusted bridge, same exact subject, KS lineage.
    SUPERSESSION_UNAUTHORIZED = "SUPERSESSION_UNAUTHORIZED"
    SUPERSESSION_SUBJECT_MISMATCH = "SUPERSESSION_SUBJECT_MISMATCH"
    SUPERSESSION_NOT_A_SUCCESSOR = "SUPERSESSION_NOT_A_SUCCESSOR"


RecoveryOwner = Literal["producer", "host", "knowledge_service", "native_service", "reviewer"]


class OutputError(_Closed):
    """``OutputError@1``: a typed refusal with its recovery owner and available actions."""

    code: OutputErrorCode
    position: str | None = None
    field_pointer: str | None = None
    safe_message: str = Field(max_length=500)
    retry_state: Literal["retryable", "repairable", "terminal"] = "repairable"
    recovery_owner: RecoveryOwner = "producer"
    available_actions: tuple[str, ...] = ()
    correlation_id: str | None = None


class Finding(_Closed):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(max_length=500)
    pointer: str | None = None


class SubmittedRevision(_Closed):
    revision_id: str
    deliverable_id: str
    revision: int
    content_digest: str


class SubmissionAck(_Closed):
    """``SubmissionAck@1``. ``accepted`` records drafts; it never promotes or fulfills."""

    submission_id: str | None = None
    status: Literal["accepted", "refused"]
    revisions: tuple[SubmittedRevision, ...] = ()
    findings: tuple[Finding, ...] = ()
    next_actions: tuple[str, ...] = ()
    error: OutputError | None = None


# ---------------------------------------------------------------- exact outputs, sets, assessments


class ExactOutput(_Closed):
    """One immutable output revision as fulfillment reads it (content digest is the identity)."""

    revision_id: str
    run_id: str
    obligation_key: str
    obligation_revision: int
    deliverable_id: str
    revision: int
    form: OutputForm
    content_digest: str = Field(pattern=DIGEST_PATTERN)
    candidate: dict[str, JsonValue]
    producer_origin_ref: str


class OutputSet(_Closed):
    """``OutputSet@1``: the pinned frontier members; its digest excludes assessments."""

    set_id: str
    revision: int = Field(ge=1)
    obligation_refs: tuple[tuple[str, int], ...]
    members: tuple[ExactOutput, ...]
    membership_digest: str = Field(pattern=DIGEST_PATTERN)
    prior_set_id: str | None = None


def membership_digest(
    obligation_refs: tuple[tuple[str, int], ...], members: tuple[ExactOutput, ...]
) -> str:
    return tagged_digest(
        "mc.output_set.v1",
        {
            "obligations": sorted([key, revision] for key, revision in obligation_refs),
            "members": sorted(
                [
                    m.obligation_key,
                    m.obligation_revision,
                    m.deliverable_id,
                    m.revision_id,
                    m.content_digest,
                ]
                for m in members
            ),
        },
    )


AssessmentResult = Literal["pass", "fail", "review", "unavailable"]


class Assessment(_Closed):
    """``Assessment@1``: an independent typed judgment of one exact subject.

    ``member`` subjects are the exact nested members an index references (``subject_id`` is
    the member ref, ``subject_digest`` its digest); adding an assessment never changes the
    subject or set it assessed.
    """

    assessment_id: str
    subject_kind: Literal["output_revision", "output_set", "member"]
    subject_id: str
    subject_digest: str = Field(pattern=DIGEST_PATTERN)
    requirement_results: dict[str, AssessmentResult]
    result: AssessmentResult
    assessor_origin_ref: str
    method_pin: str
    policy_pin: str
    evidence_refs: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    # ``member`` subjects name the exact index revision that lists them.
    index_revision_id: str | None = None
    # A later judgment replaces an earlier one only by naming it; otherwise both stand.
    supersedes: str | None = None


class Unmet(_Closed):
    code: str
    message: str = Field(max_length=500)
    waiting: bool = True
    owner: RecoveryOwner = "producer"


class Fulfillment(_Closed):
    """``Fulfillment@1``: the decision for one declared obligation at a pinned frontier."""

    obligation_key: str
    obligation_revision: int
    enforcement: Enforcement
    disposition: Literal["fulfilled", "unfulfilled", "blocked", "not_applicable"]
    eligible_members: tuple[str, ...] = ()
    assessment_refs: tuple[str, ...] = ()
    distinct_count: int = 0
    unmet: tuple[Unmet, ...] = ()
    submitted: bool = False

    @property
    def digest(self) -> str:
        return tagged_digest("mc.obligation_fulfillment.v1", stable_json_dump(self))


CompletionState = Literal["satisfied", "waiting", "blocked"]


class FulfillmentResult(_Closed):
    set_id: str
    membership_digest: str
    fulfillments: tuple[Fulfillment, ...]
    completion: CompletionState
    blocking: tuple[str, ...] = ()
    shortfalls: tuple[str, ...] = ()
    waiting_on: tuple[str, ...] = ()


__all__ = [
    "AGGREGATE_RULES",
    "CARDINALITY_MAXIMUM",
    "CARDINALITY_WARNING",
    "DEFERRED_FORMS",
    "AdmittedBinding",
    "AllOf",
    "AnyOf",
    "Assessment",
    "AssessmentLeaf",
    "CandidateRef",
    "Cardinality",
    "CompletionExpr",
    "CompletionState",
    "CoverageContract",
    "CriterionLeaf",
    "Enforcement",
    "EvaluationScope",
    "ExactOutput",
    "Finding",
    "Fulfillment",
    "FulfillmentResult",
    "HumanResolutionLeaf",
    "IntegrityLeaf",
    "MemberDecisions",
    "MemberGuarantee",
    "MemberRef",
    "ObligationLeaf",
    "OutputContract",
    "OutputError",
    "OutputErrorCode",
    "OutputForm",
    "OutputObligation",
    "OutputPromiseSet",
    "OutputSet",
    "Pin",
    "Requirement",
    "SchemaPin",
    "SubmissionAck",
    "SubmitOutput",
    "SubmittedRevision",
    "TrustedValidators",
    "Unmet",
    "aggregate_rule",
    "collection_digest",
    "collection_document",
    "membership_digest",
    "referenced_obligations",
    "tagged_digest",
]

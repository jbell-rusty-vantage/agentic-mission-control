"""Mission Manifest v1 (``mc.mission_manifest.v1``): the YAML authoring surface.

A ``mission.yml`` file is parsed (YAML 1.2 core scalars, duplicate keys rejected, no floats),
shape-validated into :class:`MissionManifest` with unknown keys rejected everywhere, and every
failure is reported as a ``(code, pointer, message)`` triple whose pointer is a JSON pointer
into the manifest. :func:`resolve_environments` computes each node's effective Environment by
the inheritance rules of SPEC-05 (mappings deep-merge, lists replace, scalars replace,
narrowing only) and records the provenance of every field.

This module is pure: no catalog access, no compile, no persistence. Capability ``search``
entries stay unresolved here; resolving them to exact pins is the compile service's job.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

import yaml
import yaml.constructor
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from mission_control.domain.authoring.provider_options import (
    normalize_provider_options,
    provider_options_lane_mismatch,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.outputs.contracts import Enforcement, EvaluationScope, OutputForm

MANIFEST_SCHEMA_ID = "mc.mission_manifest.v1"
MANIFEST_LITERAL = "mission/v1"
MANIFEST_SCHEMA_FILENAME = f"{MANIFEST_SCHEMA_ID}.json"

# ---------------------------------------------------------------------------
# Error vocabulary
# ---------------------------------------------------------------------------


class ManifestErrorCode(StrEnum):
    INVALID_DEFINITION = "INVALID_DEFINITION"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    CAPABILITY_DRIFT = "CAPABILITY_DRIFT"
    UNSUPPORTED_BEHAVIOR = "UNSUPPORTED_BEHAVIOR"
    AUTHORITY_DENIED = "AUTHORITY_DENIED"
    APPLICATION_FORBIDDEN = "APPLICATION_FORBIDDEN"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


class ManifestIssue(BaseModel):
    """One blocker or warning; ``pointer`` is a JSON pointer into the manifest document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ManifestErrorCode
    pointer: str
    message: str = Field(min_length=1)
    reason: str | None = None


class ManifestRejected(ValueError):
    """The manifest cannot be parsed into a valid :class:`MissionManifest`."""

    def __init__(self, issues: Sequence[ManifestIssue]) -> None:
        if not issues:
            raise ValueError("a rejection must carry at least one issue")
        self.issues: tuple[ManifestIssue, ...] = tuple(issues)
        first = self.issues[0]
        super().__init__(f"{first.code}: {first.pointer or '/'}: {first.message}")


def json_pointer(parts: Iterable[str | int]) -> str:
    """RFC 6901 pointer for a path (``~`` and ``/`` escaped)."""

    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


# ---------------------------------------------------------------------------
# YAML 1.2 core-schema loader (no YAML 1.1 ``on``/``yes`` booleans, no floats, no dates)
# ---------------------------------------------------------------------------

_BOOL_TAG = "tag:yaml.org,2002:bool"
_INT_TAG = "tag:yaml.org,2002:int"
_FLOAT_TAG = "tag:yaml.org,2002:float"
_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"
_REPLACED_TAGS = {_BOOL_TAG, _INT_TAG, _FLOAT_TAG, _TIMESTAMP_TAG}
_YAML12_BOOL = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")
_YAML12_INT = re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$")
_YAML12_FLOAT = re.compile(
    r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?"
    r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"
)


class _ManifestLoader(yaml.SafeLoader):
    """SafeLoader restricted to the YAML 1.2 core schema with exact decimals."""


_ManifestLoader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag not in _REPLACED_TAGS]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_ManifestLoader.add_implicit_resolver(_BOOL_TAG, _YAML12_BOOL, list("tTfF"))
_ManifestLoader.add_implicit_resolver(_INT_TAG, _YAML12_INT, list("-+0123456789"))
_ManifestLoader.add_implicit_resolver(_FLOAT_TAG, _YAML12_FLOAT, list("-+0123456789."))


def _construct_int(loader: _ManifestLoader, node: yaml.ScalarNode) -> int:
    text = str(loader.construct_scalar(node))
    if text.startswith(("0o", "0x")):
        return int(text, 0)
    return int(text, 10)


def _construct_decimal(loader: _ManifestLoader, node: yaml.ScalarNode) -> Decimal:
    text = str(loader.construct_scalar(node))
    try:
        value = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - the resolver regex guards this
        raise yaml.constructor.ConstructorError(
            None, None, f"invalid number {text!r}", node.start_mark
        ) from exc
    if not value.is_finite():
        raise yaml.constructor.ConstructorError(
            None, None, "non-finite numbers are not allowed in a manifest", node.start_mark
        )
    return value


def _construct_mapping(loader: _ManifestLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(
                None, None, f"mapping keys must be strings, found {key!r}", key_node.start_mark
            )
        if key in result:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_ManifestLoader.add_constructor(_INT_TAG, _construct_int)
_ManifestLoader.add_constructor(_FLOAT_TAG, _construct_decimal)
_ManifestLoader.add_constructor("tag:yaml.org,2002:map", _construct_mapping)


def load_manifest_yaml(text: str) -> dict[str, Any]:
    """Parse manifest YAML text into a JSON-like document; never executes tags."""

    loader = _ManifestLoader(text)
    try:
        document = loader.get_single_data()
    except yaml.YAMLError as exc:
        raise ManifestRejected(
            [
                ManifestIssue(
                    code=ManifestErrorCode.INVALID_DEFINITION,
                    pointer="",
                    message=f"manifest is not valid YAML: {exc}",
                    reason="yaml_syntax",
                )
            ]
        ) from exc
    finally:
        loader.dispose()
    if not isinstance(document, dict):
        raise ManifestRejected(
            [
                ManifestIssue(
                    code=ManifestErrorCode.INVALID_DEFINITION,
                    pointer="",
                    message="a manifest must be a YAML mapping at the top level",
                    reason="not_a_mapping",
                )
            ]
        )
    return document


class _CanonicalDumper(yaml.SafeDumper):
    """Dumps documents produced by :func:`load_manifest_yaml` back to canonical YAML."""


def _represent_decimal(dumper: _CanonicalDumper, value: Decimal) -> yaml.ScalarNode:
    return dumper.represent_scalar(_FLOAT_TAG, _decimal_text(value))


_CanonicalDumper.add_representer(Decimal, _represent_decimal)


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if value.is_zero() else text


def canonical_manifest_bytes(document: Mapping[str, Any]) -> bytes:
    """Canonical YAML bytes: sorted keys, block style, no comments, UTF-8."""

    rendered: str = yaml.dump(
        dict(document),
        Dumper=_CanonicalDumper,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
        width=1_000_000,
    )
    return rendered.encode("utf-8")


def manifest_digest(document: Mapping[str, Any]) -> str:
    """``sha256:`` digest of the canonical YAML of a parsed manifest document."""

    return "sha256:" + hashlib.sha256(canonical_manifest_bytes(document)).hexdigest()


# ---------------------------------------------------------------------------
# Scalar vocabularies
# ---------------------------------------------------------------------------

SLUG_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,127}$"
PROFILE_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,191}$"
SCHEMA_REF_PATTERN = r"^[a-z][a-z0-9_.-]*@[0-9]+$"
OUTPUT_REF_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,127}\.[a-z0-9][a-z0-9_-]{0,127}$"
EVENT_TYPE_PATTERN = r"^[a-z][a-z0-9_]*(?:\.(?:[a-z][a-z0-9_]*|\*))*$"
PIN_PATTERN = (
    r"^(?P<capability_id>[a-z0-9][a-z0-9._:-]*)"
    r"@(?P<version>latest|[0-9A-Za-z][0-9A-Za-z.+_-]*)"
    r"(?:#(?P<digest>sha256:[0-9a-f]{64}))?$"
)
_PIN = re.compile(PIN_PATTERN)
DURATION_PATTERN = r"^(?=[0-9])(?:[0-9]+d)?(?:[0-9]+h)?(?:[0-9]+m)?(?:[0-9]+s)?$"
_DURATION = re.compile(r"^(?:([0-9]+)d)?(?:([0-9]+)h)?(?:([0-9]+)m)?(?:([0-9]+)s)?$")

# An Application id (`ApplicationProfile.application_id`, OC-R4). Which ids exist is the
# installation's Application Registry, checked at compile; the manifest names no closed set.
APPLICATION_ID_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"

Slug = Annotated[str, StringConstraints(pattern=SLUG_PATTERN)]
ApplicationId = Annotated[str, StringConstraints(pattern=APPLICATION_ID_PATTERN)]
ProfileId = Annotated[str, StringConstraints(pattern=PROFILE_PATTERN)]
SchemaRef = Annotated[str, StringConstraints(pattern=SCHEMA_REF_PATTERN)]
OutputRef = Annotated[str, StringConstraints(pattern=OUTPUT_REF_PATTERN)]
EventType = Annotated[str, StringConstraints(pattern=EVENT_TYPE_PATTERN)]
NonEmptyText = Annotated[str, StringConstraints(min_length=1)]


def parse_duration(value: object) -> int:
    """Duration grammar: integer seconds, or ``[Nd][Nh][Nm][Ns]`` (``4h``, ``1h30m``)."""

    if isinstance(value, bool):
        raise ValueError("a duration is seconds or a string such as 4h or 1h30m")
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, Decimal) and value == value.to_integral_value():
        seconds = int(value)
    elif isinstance(value, str) and (match := _DURATION.fullmatch(value)) and value:
        days, hours, minutes, secs = (int(group or 0) for group in match.groups())
        seconds = ((days * 24 + hours) * 60 + minutes) * 60 + secs
    else:
        raise ValueError("a duration is seconds or a string such as 4h or 1h30m")
    if seconds <= 0:
        raise ValueError("a duration must be positive")
    return seconds


Duration = Annotated[
    int,
    BeforeValidator(parse_duration),
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "integer", "minimum": 1},
                {"type": "string", "pattern": DURATION_PATTERN, "minLength": 2},
            ],
            "description": "Seconds, or [Nd][Nh][Nm][Ns] such as 4h or 1h30m.",
        }
    ),
]


# The manifest `lane` vocabulary is the one Lane Profile enum (MP-01); mission/v1 accepts
# every name in the schema and rejects the non-Cursor provider lanes in validation
# (ADR-0018). mission/v2 (`manifest_v2.py`) admits them.
Lane = LaneProfile

RESERVED_LANES = frozenset(
    {
        Lane.CLAUDE_AGENT_SDK,
        Lane.CODEX,
        Lane.CLAUDE_CLOUD,
        Lane.CODEX_CLOUD,
        Lane.CLAUDE_MANAGED,
        Lane.CODEX_AGENTS,
    }
)
CURSOR_LANES = frozenset({Lane.CURSOR_LOCAL, Lane.CURSOR_CLOUD})
HOSTED_LANES = frozenset(
    {
        Lane.CURSOR_CLOUD,
        Lane.CLAUDE_CLOUD,
        Lane.CODEX_CLOUD,
        Lane.CLAUDE_MANAGED,
        Lane.CODEX_AGENTS,
    }
)


class CapabilityKind(StrEnum):
    """Catalog Capability Kinds a manifest entry may name (ADR-0020, ADR-0023)."""

    MCP_SERVER = "mcp_server"
    MCP_TOOL = "mcp_tool"
    SKILL_BUNDLE = "skill_bundle"
    HOOK_SCRIPT = "hook_script"
    SUBAGENT_PROFILE = "subagent_profile"
    PLUGIN = "plugin"
    DETERMINISTIC_EXECUTOR = "deterministic_executor"
    ASSESSMENT = "assessment"
    MODEL_PROFILE = "model_profile"
    SANDBOX_PROFILE = "sandbox_profile"
    CONTEXT_BUNDLE = "context_bundle"
    # Sprint V SV-16: a host tool capability (catalog `tool` row), e.g. a knowledge tool.
    TOOL = "tool"


class SideEffect(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE_REVERSIBLE = "external_write_reversible"
    EXTERNAL_WRITE_IRREVERSIBLE = "external_write_irreversible"
    SPEND = "spend"


DEFAULT_SIDE_EFFECTS: tuple[SideEffect, ...] = (SideEffect.READ_ONLY, SideEffect.WORKSPACE_WRITE)


class HookEvent(StrEnum):
    """``mc.hook_event`` values (ADR-0026)."""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    BEFORE_PROMPT = "before_prompt"
    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    AFTER_TOOL_FAILURE = "after_tool_failure"
    BEFORE_SHELL = "before_shell"
    AFTER_SHELL = "after_shell"
    AFTER_FILE_EDIT = "after_file_edit"
    BEFORE_COMPACTION = "before_compaction"
    AFTER_COMPACTION = "after_compaction"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_STOP = "subagent_stop"
    STOP = "stop"


class ExpansionTier(StrEnum):
    INLINE = "inline"
    REFERENCE = "reference"
    MATERIALIZE = "materialize"
    AUTO = "auto"


class CommandKind(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    SATISFY_WAIT = "satisfy_wait"
    CANCEL = "cancel"
    QUEUE_INSTRUCTION = "queue_instruction"
    ADD_CONTEXT = "add_context"
    INTERRUPT_AND_INJECT = "interrupt_and_inject"
    FORK = "fork"
    REQUEST_CONTINUATION = "request_continuation"


class Behavior(StrEnum):
    STAGE_GRAPH = "stage_graph"
    GOAL_LOOP = "goal_loop"
    PARALLEL_SWARM = "parallel_swarm"
    EVALUATOR_OPTIMIZER = "evaluator_optimizer"
    AGENT_EXECUTOR = "agent_executor"
    DETERMINISTIC_EXECUTOR = "deterministic_executor"
    EVENT_WAIT = "event_wait"
    TIMER = "timer"
    HUMAN_GATE = "human_gate"
    PROOF_GATE = "proof_gate"
    CHILD_MISSION_INVOCATION = "child_mission_invocation"


# ---------------------------------------------------------------------------
# Shape models
# ---------------------------------------------------------------------------


class ManifestModel(BaseModel):
    """Strict, immutable manifest shape: unknown keys are rejected everywhere."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        allow_inf_nan=False,
        ser_json_inf_nan="strings",
    )

    def authored(self) -> dict[str, Any]:
        """The fields the author wrote, by alias, in Python mode (decimals stay exact)."""

        return self.model_dump(mode="python", by_alias=True, exclude_unset=True)


def _exactly_one(model: BaseModel, names: Sequence[str], what: str) -> None:
    present = [name for name in names if getattr(model, name) is not None]
    if len(present) != 1:
        aliases = " | ".join((type(model).model_fields[name].alias or name) for name in names)
        raise ValueError(f"{what} needs exactly one of {aliases}")


_PIN_OR_SEARCH_SCHEMA: dict[str, Any] = {
    "oneOf": [{"required": ["pin"]}, {"required": ["search"]}],
}


class CapabilityEntryBase(ManifestModel):
    """``{pin: id@version#sha256:…}`` or ``{search: "...", kind: ..., as: alias}``.

    Never used as a field type: fields declare one of the concrete leaf entries below, so a
    declared model is never filled by a subclass that adds fields."""

    model_config = ConfigDict(json_schema_extra=_PIN_OR_SEARCH_SCHEMA)

    pin: str | None = Field(default=None, pattern=PIN_PATTERN)
    search: str | None = Field(default=None, min_length=1, max_length=512)
    kind: CapabilityKind | None = None
    as_: Slug | None = Field(default=None, alias="as")
    require: tuple[Lane, ...] | None = None

    @model_validator(mode="after")
    def _pin_or_search(self) -> CapabilityEntryBase:
        _exactly_one(self, ("pin", "search"), "a capability entry")
        if self.search is not None:
            if self.kind is None:
                raise ValueError("a search entry needs kind")
            if self.as_ is None:
                raise ValueError("a search entry needs an alias (as)")
        if self.pin is not None:
            match = _PIN.fullmatch(self.pin)
            if match is not None and match["version"] != "latest" and not match["digest"]:
                raise ValueError(
                    "an exact pin needs #sha256:<digest>; only @latest may omit the digest"
                )
        return self

    @property
    def pin_parts(self) -> tuple[str, str, str | None] | None:
        if self.pin is None:
            return None
        match = _PIN.fullmatch(self.pin)
        if match is None:  # pragma: no cover - the field pattern guards this
            return None
        return match["capability_id"], match["version"], match["digest"]


class CapabilityReference(CapabilityEntryBase):
    """A pin-or-search entry with no kind-specific fields (skills, plugins, models)."""


class CapabilityEntry(CapabilityEntryBase):
    tools: tuple[Annotated[str, StringConstraints(min_length=1)], ...] | None = None

    @model_validator(mode="after")
    def _tools_only_for_servers(self) -> CapabilityEntry:
        if self.tools is not None and self.kind not in (None, CapabilityKind.MCP_SERVER):
            raise ValueError("tools narrows an mcp_server entry only")
        return self


class AgentOverlay(ManifestModel):
    readonly: bool | None = None
    is_background: bool | None = None
    model: Literal["inherit"] | ProfileId | None = None


class AgentEntry(CapabilityEntryBase):
    overlay: AgentOverlay | None = None


class HookEntry(CapabilityEntryBase):
    events: tuple[HookEvent, ...] = Field(min_length=1)
    matcher: str | None = Field(default=None, min_length=1)
    fail_closed: bool = False


class ContextEntry(ManifestModel):
    """A read-only context item: a catalog entry, an artifact, or a workspace path."""

    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {"required": ["pin"]},
                {"required": ["search"]},
                {"required": ["artifact"]},
                {"required": ["path"]},
            ]
        }
    )

    pin: str | None = Field(default=None, pattern=PIN_PATTERN)
    search: str | None = Field(default=None, min_length=1, max_length=512)
    artifact: str | None = Field(default=None, pattern=r"^artifact://\S+$")
    path: str | None = Field(default=None, min_length=1)
    kind: CapabilityKind | None = None
    as_: Slug | None = Field(default=None, alias="as")
    expand: ExpansionTier | None = None

    @model_validator(mode="after")
    def _one_source(self) -> ContextEntry:
        _exactly_one(self, ("pin", "search", "artifact", "path"), "a context entry")
        if self.search is not None and (self.kind is None or self.as_ is None):
            raise ValueError("a context search entry needs kind and an alias (as)")
        return self


class ModelSelection(ManifestModel):
    profile: ProfileId | CapabilityReference | None = None
    settings: dict[str, Any] | None = None


class SandboxSelection(ManifestModel):
    profile: ProfileId | None = None
    egress: tuple[Slug, ...] | None = None


class RepositoryWorkspace(ManifestModel):
    url: str | None = Field(default=None, pattern=r"^(?:https://|ssh://|git@)\S+$")
    ref: str | None = Field(default=None, min_length=1)
    path: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _url_or_path(self) -> RepositoryWorkspace:
        if self.url is None and self.path is None:
            raise ValueError("a repository needs url or path")
        return self


class WorkspaceSelection(ManifestModel):
    repo: RepositoryWorkspace | None = None
    context: tuple[ProfileId | ContextEntry, ...] | None = None
    skills: tuple[CapabilityReference, ...] | None = None


class Budget(ManifestModel):
    usd: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    tokens: int | None = Field(default=None, ge=0)
    wall_clock: Duration | None = None
    tool_calls: int | None = Field(default=None, ge=0)


class Governors(ManifestModel):
    depth: int | None = Field(default=None, ge=0)
    fan_out: int | None = Field(default=None, ge=1)
    iterations: int | None = Field(default=None, ge=1)
    rounds: int | None = Field(default=None, ge=1)
    patience: int | None = Field(default=None, ge=1)
    transfers: int | None = Field(default=None, ge=0)


class Environment(ManifestModel):
    """Lane, model, sandbox, workspace, capabilities and limits; every field is optional so a
    node can overlay any subset. A mission-level Environment must be complete (see
    :func:`resolve_environments`)."""

    lane: Lane | None = None
    model: ModelSelection | None = None
    sandbox: SandboxSelection | None = None
    workspace: WorkspaceSelection | None = None
    capabilities: tuple[CapabilityEntry, ...] | None = None
    agents: tuple[AgentEntry, ...] | None = None
    hooks: tuple[HookEntry, ...] | None = None
    plugins: tuple[CapabilityReference, ...] | None = None
    budget: Budget | None = None
    governors: Governors | None = None
    side_effects: tuple[SideEffect, ...] | None = None
    # P1-S2: provider-specific settings keyed by lane profile, each validated by that lane's
    # options model (`domain/authoring/provider_options.py`) and stored canonically. A key
    # for a lane the node does not run on is a compile blocker (`_lane_issues`).
    provider_options: dict[str, dict[str, Any]] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        # Additive: definitions compiled before this field keep their digests (ADR-0020).
        json_schema_extra={"digest_omit_default": True},
    )

    @field_validator("provider_options")
    @classmethod
    def provider_options_are_known(
        cls, value: dict[str, dict[str, Any]] | None
    ) -> dict[str, dict[str, Any]] | None:
        try:
            return normalize_provider_options(value)
        except ValueError as error:
            raise ValueError(f"provider_options: {error}") from error

    # Lanes this manifest version refuses in validation (v1: every non-Cursor provider
    # lane, ADR-0018). A later manifest version overrides these hooks; v1 behavior is fixed.
    reserved_lanes: ClassVar[frozenset[LaneProfile]] = RESERVED_LANES
    # Lanes whose environment must name workspace.repo (v1: the Cursor lanes).
    repository_lanes: ClassVar[frozenset[LaneProfile]] = CURSOR_LANES

    def version_lane_issues(
        self, env_pointer: str, *, mission_level: bool
    ) -> tuple[list[ManifestIssue], list[ManifestIssue]]:
        """Version-specific lane rules beyond the shared ones (none in mission/v1)."""

        return [], []

    def version_narrowing_issues(
        self, child: Environment, overlay: Environment, pointer: str
    ) -> list[ManifestIssue]:
        """Version-specific authority-narrowing rules (none in mission/v1)."""

        return []


# --- Goals and acceptance ---------------------------------------------------------------


class AssessmentAcceptance(ManifestModel):
    capability: CapabilityReference
    threshold: Decimal = Field(ge=0, le=1)


_ACCEPTANCE_KEYS = ("assessment", "human", "schema", "all", "any")


class Acceptance(ManifestModel):
    """The authoring form of the Completion Contract's closed typed AST (ADR-0010)."""

    model_config = ConfigDict(
        json_schema_extra={"oneOf": [{"required": [key]} for key in _ACCEPTANCE_KEYS]}
    )

    assessment: AssessmentAcceptance | None = None
    human: Literal["review_accept", "approved"] | None = None
    schema_: SchemaRef | None = Field(default=None, alias="schema")
    all_: tuple[Acceptance, ...] | None = Field(default=None, alias="all", min_length=1)
    any_: tuple[Acceptance, ...] | None = Field(default=None, alias="any", min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _reject_free_text(cls, value: object) -> object:
        if isinstance(value, str):
            raise ValueError(
                "acceptance must be a typed expression (assessment, human, schema, all, any); "
                "free-text, natural-language or code predicates are rejected"
            )
        return value

    @model_validator(mode="after")
    def _exactly_one_operator(self) -> Acceptance:
        _exactly_one(self, ("assessment", "human", "schema_", "all_", "any_"), "acceptance")
        return self


class Objective(ManifestModel):
    key: Slug
    description: NonEmptyText
    parent: Slug | None = None


class SuccessCriterion(ManifestModel):
    key: Slug
    description: NonEmptyText
    evidence: tuple[Annotated[str, StringConstraints(min_length=1)], ...] = Field(min_length=1)
    acceptance: Acceptance


class Goal(ManifestModel):
    key: Slug
    description: NonEmptyText
    importance: Literal["primary", "secondary", "optional"] = "primary"
    objectives: tuple[Objective, ...] = ()
    criteria: tuple[SuccessCriterion, ...] = Field(min_length=1)


# --- Program nodes ----------------------------------------------------------------------


class InputBinding(ManifestModel):
    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [{"required": ["from"]}, {"required": ["artifact"]}, {"required": ["value"]}]
        }
    )

    name: Slug
    from_: OutputRef | None = Field(default=None, alias="from")
    artifact: str | None = Field(default=None, pattern=r"^artifact://\S+$")
    value: Any = None
    schema_: SchemaRef | None = Field(default=None, alias="schema")
    expand: ExpansionTier = ExpansionTier.AUTO
    required: bool = True

    @model_validator(mode="after")
    def _one_source(self) -> InputBinding:
        sources = [
            name
            for name in ("from_", "artifact", "value")
            if name in self.model_fields_set and getattr(self, name) is not None
        ]
        if len(sources) != 1:
            raise ValueError("an input binding needs exactly one of from | artifact | value")
        return self


class OutputCardinality(ManifestModel):
    min: int = Field(default=1, ge=0)
    max: int = Field(default=1, ge=1, le=64)


class OutputCoverage(ManifestModel):
    """The exact promised subjects a structured output must cover (never a bare count)."""

    subjects: tuple[Annotated[str, StringConstraints(min_length=1)], ...] = Field(min_length=1)
    pointer: str = Field(pattern=r"^(/[^/]+)+$")
    key: str | None = Field(default=None, min_length=1)


class OutputRequirementDeclaration(ManifestModel):
    """A promised guarantee proven by an independent assessment (a declared check)."""

    key: Slug
    validator: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    parameters: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    # ``member``: a nested guarantee each exact member an index lists must pass.
    subject: Literal["deliverable", "set", "member"] = "deliverable"


class OutputMembers(ManifestModel):
    """Nested guarantees of an index: every exact member it lists must pass these checks."""

    pointer: str = Field(pattern=r"^(/[^/]+)+$")
    requirements: tuple[Slug, ...] = Field(min_length=1)


class OutputDeclaration(ManifestModel):
    """One exact named output promise (OUTPUT-CONTRACTS §2): form, enforcement, coverage."""

    name: Slug
    form: OutputForm = OutputForm.STRUCTURED
    schema_: SchemaRef | None = Field(default=None, alias="schema")
    enforcement: Enforcement = Enforcement.REQUIRED
    cardinality: OutputCardinality | None = None
    coverage: OutputCoverage | None = None
    requirements: tuple[OutputRequirementDeclaration, ...] = ()
    members: OutputMembers | None = None
    media_type: str | None = Field(default=None, min_length=1, max_length=255)
    repository: str | None = Field(default=None, min_length=1, max_length=512)
    # Named capabilities whose exact receipts may be associated with a missing submission.
    receipts: tuple[Annotated[str, StringConstraints(min_length=1)], ...] = ()
    scope: EvaluationScope = EvaluationScope.INVOCATION

    @model_validator(mode="after")
    def _form_shape(self) -> OutputDeclaration:
        if self.form in {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD} and not self.schema_:
            raise ValueError(f"a {self.form.value} output pins its schema")
        if self.form is OutputForm.TEXT and self.schema_:
            raise ValueError("a text output checks exact bytes, not a schema")
        if self.form not in {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD} and (
            self.coverage is not None or self.members is not None
        ):
            raise ValueError("coverage and nested members apply to structured outputs")
        if self.repository is not None and self.form is not OutputForm.CODE_CHANGE:
            raise ValueError("repository identity belongs to a code_change output")
        keys = {item.key for item in self.requirements}
        if len(keys) != len(self.requirements):
            raise ValueError("output requirement keys are unique")
        member_keys = {item.key for item in self.requirements if item.subject == "member"}
        if (self.members is None and member_keys) or (
            self.members is not None and set(self.members.requirements) != member_keys
        ):
            raise ValueError("members.requirements name exactly the member-subject requirements")
        return self

    @property
    def required(self) -> bool:
        """Read-only view: the promise blocks completion (enforcement ``required``)."""

        return self.enforcement is Enforcement.REQUIRED


class NodeCompletion(ManifestModel):
    acceptance: Acceptance


class QuorumJoin(ManifestModel):
    quorum: int = Field(ge=1)


# --- Explicit release groups, stage facts and routes (OVE-171, OUTPUT-CONTRACTS §7) ---------

FACT_REF_PATTERN = OUTPUT_REF_PATTERN
RouteScalar = StrictBool | StrictInt | Annotated[StrictStr, StringConstraints(max_length=256)]


class ReleaseGroupMember(ManifestModel):
    """One exact group member and the subjects its output covers (for coverage)."""

    stage: Slug
    covers: tuple[Slug, ...] = ()


class ReleaseGroupDeclaration(ManifestModel):
    """A named all/any/quorum release group of sibling producers (exact members in declared
    order). The selected set is the first qualifying distinct set in durable eligibility order;
    ``coverage`` subjects must be covered by that set together, which a quorum never waives."""

    key: Slug
    join: Literal["all", "any"] | QuorumJoin = "all"
    members: tuple[Slug | ReleaseGroupMember, ...] = Field(min_length=1)
    coverage: tuple[Slug, ...] = ()

    @property
    def member_keys(self) -> tuple[str, ...]:
        return tuple(item if isinstance(item, str) else item.stage for item in self.members)

    def covers(self) -> dict[str, tuple[str, ...]]:
        return {
            item.stage: item.covers
            for item in self.members
            if isinstance(item, ReleaseGroupMember) and item.covers
        }


class FactDeclaration(ManifestModel):
    """A typed fact the host reads at ``pointer`` of this node's accepted structured output."""

    name: Slug
    output: Slug
    pointer: str = Field(pattern=r"^(/[^/]+)+$", max_length=512)
    type: Literal["string", "integer", "boolean"]


class RoutePredicateDeclaration(ManifestModel):
    """``<stage>.<fact> <op> <value>``: a closed typed comparison over a pinned stage fact."""

    fact: str = Field(pattern=FACT_REF_PATTERN)
    op: Literal["eq", "ne", "lt", "le", "gt", "ge", "in", "not_in"]
    value: RouteScalar | tuple[RouteScalar, ...]


class RouteBranchDeclaration(ManifestModel):
    key: Slug
    when: tuple[RoutePredicateDeclaration, ...] = Field(min_length=1, max_length=8)
    release: tuple[Slug, ...] = Field(min_length=1)


class RouteDeclaration(ManifestModel):
    """An explicit conditional route: ``all_matching`` or ordered ``first_match`` (required; no
    silent universal choice). ``else`` releases only when every branch is conclusively false."""

    key: Slug
    mode: Literal["all_matching", "first_match"]
    branches: tuple[RouteBranchDeclaration, ...] = Field(min_length=1, max_length=16)
    else_: tuple[Slug, ...] = Field(default=(), alias="else")


class RevisitDeclaration(ManifestModel):
    """A bounded Revisit Region (01-STAGE_GRAPH §8): a known stage set with a declared entry
    and exit, a hard visit cap (counting the first visit) and a deterministic stop: ``until``
    facts when authored, else fulfillment of every required obligation the region owes. An
    integer ``progress`` fact with ``patience`` ends a region that stops improving. ``carry``
    names exit outputs the next visit's entry receives (the prior visit's accepted revision)."""

    key: Slug
    stages: tuple[Slug, ...] = Field(min_length=1)
    entry: Slug
    exit: Slug
    max_visits: int = Field(ge=2, le=16)
    until: tuple[RoutePredicateDeclaration, ...] = Field(default=(), max_length=8)
    progress: str | None = Field(default=None, pattern=FACT_REF_PATTERN)
    patience: int | None = Field(default=None, ge=1, le=16)
    carry: tuple[Slug, ...] = ()


class ProgramNodeBase(ManifestModel):
    key: Slug
    objectives: tuple[Slug, ...] = ()
    environment: Environment | None = None
    inputs: tuple[InputBinding, ...] = ()
    outputs: tuple[OutputDeclaration, ...] = ()
    completion: NodeCompletion | None = None
    depends_on: tuple[Slug, ...] = ()
    join: Literal["all", "any"] | QuorumJoin = "all"
    # OVE-171: named release groups of sibling producers and the typed facts routes read.
    release_groups: tuple[ReleaseGroupDeclaration, ...] = ()
    facts: tuple[FactDeclaration, ...] = ()

    requires_objectives: ClassVar[bool] = False

    @model_validator(mode="after")
    def _objectives_present(self) -> ProgramNodeBase:
        if self.requires_objectives and not self.objectives:
            raise ValueError(f"a {self.behavior_name()} node needs objectives")
        return self

    @classmethod
    def behavior_name(cls) -> str:
        return str(cls.model_fields["behavior"].default)


class ExportDeclaration(ManifestModel):
    """OVE-176 (OUTPUT-CONTRACTS §9): how a nested body exports one declared output of its node.

    Every declared output of a nested Goal Loop or Stage Graph is exported to the parent (final by
    default). ``from: <stage>.<output>`` names the inner producer of a Stage Graph body's output;
    ``timing: early`` lets an independently accepted output leave an incomplete composite without
    accepting it. Undeclared inner outputs never cross the boundary."""

    output: Slug
    from_: str | None = Field(default=None, alias="from", pattern=OUTPUT_REF_PATTERN)
    timing: Literal["final", "early"] = "final"


class StageGraphNode(ProgramNodeBase):
    behavior: Literal["stage_graph"] = "stage_graph"
    nodes: tuple[ProgramNode, ...] = Field(min_length=1)
    fail_fast: bool = False
    concurrency: int | None = Field(default=None, ge=1)
    # OVE-171: explicit conditional routes over the facts of this graph's stages.
    routes: tuple[RouteDeclaration, ...] = Field(default=(), max_length=32)
    # OVE-171 slice D: at most one bounded Revisit Region over this graph's stages.
    revisits: tuple[RevisitDeclaration, ...] = Field(default=(), max_length=1)
    # OVE-176: the exports of this graph when it is a nested body.
    exports: tuple[ExportDeclaration, ...] = Field(default=(), max_length=32)

    requires_objectives: ClassVar[bool] = True


class Verifier(ManifestModel):
    independent: bool = True
    environment: Environment | None = None


class GoalLoopNode(ProgramNodeBase):
    behavior: Literal["goal_loop"] = "goal_loop"
    objective: Slug
    action_space: tuple[Slug, ...] = Field(min_length=1)
    verifier: Verifier | None = None
    stop: Acceptance | None = None
    # OVE-176 (00-EXECUTION_PROGRAM_MODEL §5.1): the executor phase as one subprogram (a Stage
    # Graph or a Goal Loop) executed recursively each iteration; absent, an agent executes it.
    nodes: tuple[ProgramNode, ...] = Field(default=(), max_length=1)
    # OVE-176: the exports of this loop when it is a nested body.
    exports: tuple[ExportDeclaration, ...] = Field(default=(), max_length=32)


class ParallelSwarmNode(ProgramNodeBase):
    behavior: Literal["parallel_swarm"] = "parallel_swarm"
    objective: Slug | None = None
    action_space: tuple[Slug, ...] = ()
    params: dict[str, Any] = Field(default_factory=dict)


class EvaluatorOptimizerNode(ProgramNodeBase):
    behavior: Literal["evaluator_optimizer"] = "evaluator_optimizer"
    objective: Slug | None = None
    action_space: tuple[Slug, ...] = ()
    params: dict[str, Any] = Field(default_factory=dict)


class FollowUpTurn(ManifestModel):
    max_turns: int = Field(ge=1, le=10)


class FollowUpTurnPolicy(ManifestModel):
    follow_up_turn: FollowUpTurn


class AgentExecutorNode(ProgramNodeBase):
    behavior: Literal["agent_executor"] = "agent_executor"
    instruction: NonEmptyText
    operating_contract: str | None = Field(default=None, min_length=1)
    missing_output_policy: Literal["not_accepted"] | FollowUpTurnPolicy = "not_accepted"

    requires_objectives: ClassVar[bool] = True


class DeterministicExecutorKind(StrEnum):
    VERIFICATION_DISPATCH = "verification_dispatch"
    ARTIFACT_REGISTER = "artifact_register"
    GIT_SNAPSHOT = "git_snapshot"
    SCHEMA_VALIDATE = "schema_validate"
    TEST_RUN = "test_run"
    COALESCE = "coalesce"
    AGREEMENT_CHECK = "agreement_check"
    NOOP_ECHO = "noop_echo"


class DeterministicExecutorNode(ProgramNodeBase):
    behavior: Literal["deterministic_executor"] = "deterministic_executor"
    kind: DeterministicExecutorKind
    params: dict[str, Any] = Field(default_factory=dict)

    requires_objectives: ClassVar[bool] = True


class HumanTaskSpec(ManifestModel):
    kind: Literal["APPROVAL", "QUESTION", "SELECTION", "REVIEW", "POLICY_OVERRIDE"]
    prompt: NonEmptyText
    reviewers: tuple[Annotated[str, StringConstraints(min_length=1)], ...] = Field(min_length=1)
    packet: tuple[OutputRef, ...] = ()
    timeout: Duration | None = None
    on_timeout: Slug | None = None


class HumanGateNode(ProgramNodeBase):
    behavior: Literal["human_gate"] = "human_gate"
    task: HumanTaskSpec


class RearmMode(ManifestModel):
    rearm: dict[str, Any]


class EventWaitNode(ProgramNodeBase):
    behavior: Literal["event_wait"] = "event_wait"
    event_type: EventType
    match: dict[str, Any] = Field(default_factory=dict)
    timeout: Duration | None = None
    on_timeout: Slug | None = None
    mode: Literal["once"] | RearmMode = "once"


class TimerNode(ProgramNodeBase):
    behavior: Literal["timer"] = "timer"
    duration: Duration | None = None
    until: AwareDatetime | None = None

    @model_validator(mode="after")
    def _duration_or_until(self) -> TimerNode:
        _exactly_one(self, ("duration", "until"), "a timer")
        return self


class ProofGateNode(ProgramNodeBase):
    behavior: Literal["proof_gate"] = "proof_gate"
    evidence: OutputRef
    required_disposition: Slug
    on_reject: Slug | None = None


class ChildSource(ManifestModel):
    inline: MissionBlock | None = None
    template: str | None = Field(default=None, min_length=1)
    existing: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _one_source(self) -> ChildSource:
        _exactly_one(self, ("inline", "template", "existing"), "a child mission")
        return self


class ChildAwait(ManifestModel):
    until: Slug


class ChildMissionInvocationNode(ProgramNodeBase):
    behavior: Literal["child_mission_invocation"] = "child_mission_invocation"
    mode: Literal["spawn", "attach"]
    child: ChildSource
    await_: ChildAwait | None = Field(default=None, alias="await")
    on_parent_cancel: Slug | None = None
    portal: Literal["peek", "peek_and_command"] = "peek"


ProgramNode = Annotated[
    StageGraphNode
    | GoalLoopNode
    | ParallelSwarmNode
    | EvaluatorOptimizerNode
    | AgentExecutorNode
    | DeterministicExecutorNode
    | HumanGateNode
    | EventWaitNode
    | TimerNode
    | ProofGateNode
    | ChildMissionInvocationNode,
    Field(discriminator="behavior"),
]

AnyProgramNode = (
    StageGraphNode
    | GoalLoopNode
    | ParallelSwarmNode
    | EvaluatorOptimizerNode
    | AgentExecutorNode
    | DeterministicExecutorNode
    | HumanGateNode
    | EventWaitNode
    | TimerNode
    | ProofGateNode
    | ChildMissionInvocationNode
)


# --- Controls ---------------------------------------------------------------------------


class WebhookChannel(ManifestModel):
    webhook: NonEmptyText
    secret_ref: str | None = Field(default=None, min_length=1)


class SubscriptionDeclaration(ManifestModel):
    events: tuple[EventType, ...] = Field(min_length=1)
    channel: Literal["stream", "mcp"] | WebhookChannel
    node_keys: tuple[Slug, ...] = ()


class NotificationDeclaration(ManifestModel):
    on: tuple[Slug, ...] = Field(min_length=1)
    channel: Slug


class Controls(ManifestModel):
    commands_allowed: tuple[CommandKind, ...] | None = None
    subscriptions: tuple[SubscriptionDeclaration, ...] = ()
    notifications: NotificationDeclaration | None = None
    chain_autostart: bool | None = None


# --- Missions, links, manifest ----------------------------------------------------------


class MissionBlock(ManifestModel):
    key: Slug
    title: NonEmptyText
    application: ApplicationId
    domain_pack: ProfileId | None = None
    description: str | None = None
    goals: tuple[Goal, ...] = Field(min_length=1)
    environment: Environment
    program: ProgramNode
    controls: Controls | None = None


class GoalAcceptedSpec(ManifestModel):
    goal_key: Slug | None = None


class GoalAcceptedCondition(ManifestModel):
    goal_accepted: GoalAcceptedSpec


LinkCondition = (
    Literal["goal_accepted", "mission_accepted", "execution_complete"] | GoalAcceptedCondition
)


class ChainLinkDeclaration(ManifestModel):
    """Shape of one ``links`` entry; graph and binding semantics live in
    ``domain/composition/chain.py`` (SPEC-04)."""

    from_: Slug = Field(alias="from")
    to: Slug
    kind: Literal["supplies", "depends_on"]
    outputs: tuple[Slug, ...] = ()
    receiving_purpose: Literal["dependent_input", "repair"] = "dependent_input"
    placement: Literal["inline", "file", "handle"] = "file"
    alternatives: tuple[Literal["inline", "file", "handle"], ...] = ()
    evidence_required: bool = True
    selector: Literal["accepted_snapshot", "finalized_snapshot"] = "accepted_snapshot"
    on: LinkCondition = "goal_accepted"
    on_upstream_cancel: Literal["continue", "cancel_downstream", "detach"] = "continue"
    on_upstream_not_accepted: Literal["stop"] = "stop"

    @model_validator(mode="after")
    def _outputs_match_kind(self) -> ChainLinkDeclaration:
        if self.kind == "supplies" and not self.outputs:
            raise ValueError("a supplies link names at least one supplier output")
        if self.kind == "depends_on" and self.outputs:
            raise ValueError("a depends_on link carries no outputs")
        if self.kind == "supplies":
            if self.receiving_purpose == "repair":
                if self.selector != "finalized_snapshot" or self.on != "execution_complete":
                    raise ValueError(
                        "repair supply requires finalized_snapshot and execution_complete"
                    )
            elif self.selector != "accepted_snapshot" or self.on == "execution_complete":
                raise ValueError(
                    "ordinary supply requires accepted_snapshot and an acceptance gate"
                )
        return self


class MissionManifest(ManifestModel):
    """``mc.mission_manifest.v1``: one mission, or a Mission Chain of missions plus links."""

    model_config = ConfigDict(
        title="Mission Manifest v1",
        json_schema_extra={
            "oneOf": [
                {"required": ["mission"], "not": {"required": ["links"]}},
                {"required": ["missions", "links"]},
            ]
        },
    )

    manifest: Literal["mission/v1"]
    mission: MissionBlock | None = None
    missions: tuple[MissionBlock, ...] | None = Field(default=None, min_length=2)
    links: tuple[ChainLinkDeclaration, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _single_or_chain(self) -> MissionManifest:
        if (self.mission is None) == (self.missions is None):
            raise ValueError("a manifest declares exactly one of mission | missions")
        if self.mission is not None and self.links is not None:
            raise ValueError("links belong to the missions (chain) form only")
        if self.missions is not None and self.links is None:
            raise ValueError("the missions (chain) form requires links")
        return self

    @property
    def is_chain(self) -> bool:
        return self.missions is not None

    def mission_blocks(self) -> tuple[tuple[str, MissionBlock], ...]:
        """Each mission with its JSON pointer."""

        if self.mission is not None:
            return (("/mission", self.mission),)
        return tuple(
            (f"/missions/{index}", block) for index, block in enumerate(self.missions or ())
        )


for _model in (StageGraphNode, GoalLoopNode, ChildSource, ChildMissionInvocationNode, MissionBlock):
    _model.model_rebuild()


# ---------------------------------------------------------------------------
# Parsing with pointers
# ---------------------------------------------------------------------------

_BEHAVIOR_TAGS = frozenset(item.value for item in Behavior)
_UNION_NOISE = frozenset({"str", "int", "bool", "float", "decimal", "none", "list", "dict"})
_FIELD_PART = re.compile(r"^[a-z_][a-z0-9_]*$")


def _pointer_from_loc(loc: Sequence[str | int]) -> str:
    parts: list[str | int] = []
    for part in loc:
        if isinstance(part, int) or (
            _FIELD_PART.fullmatch(part) and part not in _BEHAVIOR_TAGS | _UNION_NOISE
        ):
            parts.append(part)
    return json_pointer(parts)


def issues_from_validation_error(
    error: ValidationError, *, prefix: str = ""
) -> tuple[ManifestIssue, ...]:
    details = [
        (prefix + _pointer_from_loc(detail["loc"]), detail)
        for detail in error.errors(include_url=False)
    ]
    issues: dict[tuple[str, str], ManifestIssue] = {}
    for pointer, detail in details:
        message = str(detail["msg"]).removeprefix("Value error, ")
        if detail["type"] == "too_short" and any(
            other.startswith(pointer + "/") for other, _ in details
        ):
            # A failed item also shortens its container; the item's own error is the cause.
            continue
        issues.setdefault(
            (pointer, message),
            ManifestIssue(
                code=ManifestErrorCode.INVALID_DEFINITION,
                pointer=pointer,
                message=message,
                reason=str(detail["type"]),
            ),
        )
    return tuple(issues.values())


def parse_manifest(document: Mapping[str, Any]) -> MissionManifest:
    """Shape-validate a parsed document; raises :class:`ManifestRejected` with pointers."""

    try:
        return MissionManifest.model_validate(dict(document))
    except ValidationError as error:
        raise ManifestRejected(issues_from_validation_error(error)) from error


def parse_manifest_yaml(text: str) -> tuple[MissionManifest, dict[str, Any]]:
    """Load and shape-validate manifest YAML; returns the model and the parsed document."""

    document = load_manifest_yaml(text)
    return parse_manifest(document), document


def manifest_json_schema() -> dict[str, Any]:
    """The JSON Schema exported to ``contracts/schemas/mc.mission_manifest.v1.json``."""

    schema = MissionManifest.model_json_schema(by_alias=True, mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://mission-control.belllabs/schemas/{MANIFEST_SCHEMA_FILENAME}",
        "x-mc-schema-id": MANIFEST_SCHEMA_ID,
        **schema,
    }


def manifest_json_schema_text() -> str:
    return json.dumps(manifest_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Program walking
# ---------------------------------------------------------------------------


class NodeVisit(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    node: AnyProgramNode
    pointer: str
    parent_key: str | None


def walk_program(root: AnyProgramNode, pointer: str) -> Iterator[NodeVisit]:
    """Depth-first, document-order walk of a program tree (the stages of a stage graph and the
    executor body of a goal loop; an inline child mission is a separate mission, not walked)."""

    stack: list[tuple[AnyProgramNode, str, str | None]] = [(root, pointer, None)]
    while stack:
        node, node_pointer, parent_key = stack.pop()
        yield NodeVisit(node=node, pointer=node_pointer, parent_key=parent_key)
        if isinstance(node, StageGraphNode | GoalLoopNode):
            for index in range(len(node.nodes) - 1, -1, -1):
                stack.append((node.nodes[index], f"{node_pointer}/nodes/{index}", node.key))


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------

_ENTRY_KEYS = frozenset({"pin", "search", "artifact", "path"})
PROVENANCE_PATTERN = r"^(?:inherited|overlay|plugin:[a-z0-9][a-z0-9_-]*)$"
Provenance = Annotated[str, StringConstraints(pattern=PROVENANCE_PATTERN)]


def _is_mapping_leaf(value: object) -> bool:
    """Capability-like mappings replace as a unit; merging pin into search would be nonsense."""

    return isinstance(value, dict) and bool(_ENTRY_KEYS & set(value))


# Discriminated environment selections (field -> discriminator) that never deep-merge
# across variants.
_DISCRIMINATED_SELECTIONS: Mapping[str, str] = {
    "execution_environment": "kind",
    "provider_environment": "strategy",
    "network": "mode",
    "write": "mode",
}


def merge_environment_documents(
    parent: Mapping[str, Any], overlay: Mapping[str, Any]
) -> dict[str, Any]:
    """Deep merge: mappings merge key by key, lists and scalars replace."""

    result = dict(parent)
    for key, value in overlay.items():
        current = result.get(key)
        discriminator = _DISCRIMINATED_SELECTIONS.get(key)
        if (
            discriminator is not None
            and isinstance(value, dict)
            and isinstance(current, dict)
            and value.get(discriminator, current.get(discriminator)) != current.get(discriminator)
        ):
            # mission/v2: a selection of another variant (hosted over local, sync over bind,
            # another network or git write mode) replaces the inherited one; merging the two
            # shapes is never a valid selection.
            result[key] = value
        elif (
            isinstance(value, dict)
            and isinstance(current, dict)
            and not _is_mapping_leaf(value)
            and not _is_mapping_leaf(current)
        ):
            result[key] = merge_environment_documents(current, value)
        else:
            result[key] = value
    return result


def _leaf_paths(
    document: Mapping[str, Any], prefix: tuple[str, ...] = ()
) -> Iterator[tuple[str, ...]]:
    for key, value in document.items():
        path = (*prefix, key)
        if isinstance(value, dict) and value and not _is_mapping_leaf(value):
            yield from _leaf_paths(value, path)
        else:
            yield path


def _set_by(overlay: Mapping[str, Any], path: tuple[str, ...]) -> bool:
    current: object = overlay
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
        if _is_mapping_leaf(current) or not isinstance(current, dict):
            return True
    return True


class NodeEnvironment(BaseModel):
    """One node's effective Environment and where each field came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_key: str
    role: Literal["node", "verifier"] = "node"
    pointer: str
    behavior: Behavior
    lane: Lane
    lane_changed_from: Lane | None = None
    effective_environment: Environment
    field_provenance: dict[str, Provenance]


class MissionEnvironments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mission_key: str
    pointer: str
    nodes: tuple[NodeEnvironment, ...]


class ManifestStructure(BaseModel):
    """Catalog-free structural validation result for one manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_digest: str
    missions: tuple[MissionEnvironments, ...]
    blockers: tuple[ManifestIssue, ...] = ()
    warnings: tuple[ManifestIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.blockers


def _issue(
    pointer: str,
    message: str,
    reason: str,
    code: ManifestErrorCode = ManifestErrorCode.INVALID_DEFINITION,
) -> ManifestIssue:
    return ManifestIssue(code=code, pointer=pointer, message=message, reason=reason)


def _narrowing_issues(
    parent: Environment, child: Environment, overlay: Environment, pointer: str
) -> list[ManifestIssue]:
    issues: list[ManifestIssue] = []
    limits: tuple[tuple[str, BaseModel | None, BaseModel | None, BaseModel | None], ...] = (
        ("budget", parent.budget, child.budget, overlay.budget),
        ("governors", parent.governors, child.governors, overlay.governors),
    )
    for block, parent_values, child_values, overlay_values in limits:
        if parent_values is None or child_values is None or overlay_values is None:
            continue
        for name in overlay_values.model_fields_set:
            inherited = getattr(parent_values, name)
            requested = getattr(child_values, name)
            if inherited is not None and requested is not None and requested > inherited:
                issues.append(
                    _issue(
                        f"{pointer}/{block}/{name}",
                        f"{block}.{name} {requested} widens the inherited limit {inherited}",
                        "widens_authority",
                    )
                )
    if overlay.side_effects is not None:
        allowed = set(parent.side_effects or DEFAULT_SIDE_EFFECTS)
        for index, effect in enumerate(overlay.side_effects):
            if effect not in allowed:
                issues.append(
                    _issue(
                        f"{pointer}/side_effects/{index}",
                        f"side effect {effect.value} is not allowed by the parent environment",
                        "widens_authority",
                    )
                )
    issues.extend(parent.version_narrowing_issues(child, overlay, pointer))
    return issues


def _overlay_environment(
    parent: Environment, overlay: Environment | None
) -> tuple[Environment, dict[str, str]]:
    parent_document = parent.authored()
    overlay_document = overlay.authored() if overlay is not None else {}
    merged = merge_environment_documents(parent_document, overlay_document)
    # The parent's class decides the manifest version (v1 Environment or a v2 subclass).
    effective = type(parent).model_validate(merged)
    provenance = {
        ".".join(path): ("overlay" if _set_by(overlay_document, path) else "inherited")
        for path in _leaf_paths(effective.authored())
    }
    return effective, dict(sorted(provenance.items()))


def _mission_environment_issues(environment: Environment, pointer: str) -> list[ManifestIssue]:
    issues: list[ManifestIssue] = []
    required = ("lane", "model", "budget", "governors")
    for name in required:
        if getattr(environment, name) is None:
            issues.append(
                _issue(
                    f"{pointer}/{name}",
                    f"the mission-level environment requires {name}",
                    "missing_field",
                )
            )
    if environment.model is not None and environment.model.profile is None:
        issues.append(
            _issue(f"{pointer}/model/profile", "the mission model needs a profile", "missing_field")
        )
    if environment.lane == Lane.DEEP_AGENTS and environment.sandbox is None:
        issues.append(
            _issue(
                f"{pointer}/sandbox",
                "a deep_agents mission environment requires a sandbox",
                "missing_field",
            )
        )
    return issues


def _lane_issues(
    environment: Environment, env_pointer: str, *, mission_level: bool
) -> tuple[list[ManifestIssue], list[ManifestIssue]]:
    blockers: list[ManifestIssue] = []
    warnings: list[ManifestIssue] = []
    lane = environment.lane
    if lane is not None and lane in environment.reserved_lanes:
        blockers.append(
            _issue(
                f"{env_pointer}/lane",
                f"lane {lane.value} is reserved and not supported in mission/v1",
                "reserved_lane",
                ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
            )
        )
    version_blockers, version_warnings = environment.version_lane_issues(
        env_pointer, mission_level=mission_level
    )
    blockers.extend(version_blockers)
    warnings.extend(version_warnings)
    if (
        lane in environment.repository_lanes
        and (environment.workspace is None or environment.workspace.repo is None)
        and not (
            lane == Lane.CURSOR_LOCAL
            and getattr(environment.workspace, "kind", "code") == "knowledge"
        )
    ):
        blockers.append(
            _issue(
                f"{env_pointer}/workspace/repo",
                f"lane {lane.value} requires workspace.repo",
                "missing_field",
            )
        )
    if (
        lane == Lane.CURSOR_LOCAL
        and environment.workspace is not None
        and environment.workspace.repo is not None
        and environment.workspace.repo.path is None
        and getattr(environment.workspace.repo, "use", None) is None
    ):
        blockers.append(
            _issue(
                f"{env_pointer}/workspace/repo/path",
                "lane cursor_local requires workspace.repo.path",
                "missing_field",
            )
        )
    if not mission_level and lane == Lane.DEEP_AGENTS and environment.sandbox is None:
        warnings.append(
            _issue(
                f"{env_pointer}/sandbox",
                "deep_agents node without a sandbox profile uses the deployment default",
                "sandbox_defaulted",
            )
        )
    candidates = tuple(item.value for item in getattr(environment, "lanes", ()) or ())
    for key in provider_options_lane_mismatch(
        environment.provider_options,
        lane=lane.value if lane is not None else None,
        candidate_lanes=candidates,
    ):
        blockers.append(
            _issue(
                f"{env_pointer}/provider_options/{key}",
                f"provider_options name lane {key}, but this environment runs on "
                f"{lane.value if lane is not None else 'an inherited lane'}",
                "provider_options_lane_mismatch",
            )
        )
    return blockers, warnings


def _goal_index(block: MissionBlock, pointer: str) -> tuple[set[str], list[ManifestIssue]]:
    issues: list[ManifestIssue] = []
    goal_keys: dict[str, int] = {}
    objective_keys: dict[str, str] = {}
    for goal_index, goal in enumerate(block.goals):
        goal_pointer = f"{pointer}/goals/{goal_index}"
        if goal.key in goal_keys:
            issues.append(
                _issue(f"{goal_pointer}/key", f"duplicate goal key {goal.key}", "duplicate_key")
            )
        goal_keys.setdefault(goal.key, goal_index)
        local_objectives = {objective.key for objective in goal.objectives}
        for objective_index, objective in enumerate(goal.objectives):
            objective_pointer = f"{goal_pointer}/objectives/{objective_index}"
            if objective.key in objective_keys or objective.key in goal_keys:
                issues.append(
                    _issue(
                        f"{objective_pointer}/key",
                        f"duplicate objective key {objective.key}",
                        "duplicate_key",
                    )
                )
            objective_keys.setdefault(objective.key, goal.key)
            if objective.parent is not None and objective.parent not in local_objectives:
                issues.append(
                    _issue(
                        f"{objective_pointer}/parent",
                        f"objective parent {objective.parent} is not an objective of goal "
                        f"{goal.key}",
                        "unknown_objective",
                    )
                )
        criteria_keys: set[str] = set()
        for criterion_index, criterion in enumerate(goal.criteria):
            if criterion.key in criteria_keys:
                issues.append(
                    _issue(
                        f"{goal_pointer}/criteria/{criterion_index}/key",
                        f"duplicate criterion key {criterion.key}",
                        "duplicate_key",
                    )
                )
            criteria_keys.add(criterion.key)
    return set(goal_keys) | set(objective_keys), issues


def _program_issues(
    block: MissionBlock, pointer: str, objective_refs: set[str]
) -> list[ManifestIssue]:
    issues: list[ManifestIssue] = []
    program_pointer = f"{pointer}/program"
    if block.program.depends_on:
        issues.append(
            _issue(
                f"{program_pointer}/depends_on",
                "the root node has no siblings to depend on",
                "unknown_dependency",
            )
        )
    seen: set[str] = set()
    for visit in walk_program(block.program, program_pointer):
        node = visit.node
        if node.key in seen:
            issues.append(
                _issue(f"{visit.pointer}/key", f"duplicate node key {node.key}", "duplicate_key")
            )
        seen.add(node.key)
        refs = list(node.objectives)
        if isinstance(node, GoalLoopNode | ParallelSwarmNode | EvaluatorOptimizerNode):
            if node.objective is not None:
                refs.append(node.objective)
        for ref in refs:
            if ref not in objective_refs:
                issues.append(
                    _issue(
                        f"{visit.pointer}/objectives"
                        if ref in node.objectives
                        else f"{visit.pointer}/objective",
                        f"{ref} is not a goal or objective of mission {block.key}",
                        "unknown_objective",
                    )
                )
        for kind, names in (
            ("input", [item.name for item in node.inputs]),
            ("output", [item.name for item in node.outputs]),
        ):
            duplicates = sorted({name for name in names if names.count(name) > 1})
            for name in duplicates:
                issues.append(
                    _issue(f"{visit.pointer}/{kind}s", f"duplicate {kind} {name}", "duplicate_key")
                )
        if isinstance(node, StageGraphNode):
            issues.extend(_stage_graph_issues(node, visit.pointer))
        issues.extend(_nested_body_issues(node, visit.pointer, root=node is block.program))
        # OVE-171: routes, groups and facts lower for the root Stage Graph and its stages only;
        # anywhere else they would be ignored, so they refuse instead.
        stage_of_root = visit.parent_key == block.program.key and isinstance(
            block.program, StageGraphNode
        )
        for field, present in (
            ("release_groups", bool(node.release_groups) and not stage_of_root),
            ("facts", bool(node.facts) and not stage_of_root),
            (
                "routes",
                isinstance(node, StageGraphNode)
                and bool(node.routes)
                and node is not block.program,
            ),
            (
                "revisits",
                isinstance(node, StageGraphNode)
                and bool(node.revisits)
                and node is not block.program,
            ),
        ):
            if present:
                issues.append(
                    _issue(
                        f"{visit.pointer}/{field}",
                        f"{field} apply to the root Stage Graph and its stages only",
                        "unsupported_graph_position",
                        ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                    )
                )
    return issues


def _subtree(node: AnyProgramNode) -> Iterator[AnyProgramNode]:
    yield node
    if isinstance(node, StageGraphNode | GoalLoopNode):
        for child in node.nodes:
            yield from _subtree(child)


def stage_graph_root_sources(node: StageGraphNode) -> dict[str, str | None]:
    """OVE-169 E4: the producer of each output of a Stage Graph program root.

    A Stage Graph root runs no cognition of its own, so it owes no promise of its own: each of
    its declared outputs is an export of one of its stages' promises (the same rule as a nested
    Stage Graph body), named by ``exports: [{output, from: <stage>.<output>}]`` or, when
    unambiguous, by the one stage that declares an output of the same name. The value is
    ``<stage>.<output>``, or ``None`` when no single stage produces it."""

    produced = {
        f"{child.key}.{output.name}": output.name
        for child in node.nodes
        for output in child.outputs
    }
    explicit = {item.output: item.from_ for item in node.exports if item.from_ is not None}
    sources: dict[str, str | None] = {}
    for output in node.outputs:
        source = explicit.get(output.name)
        if source is None:
            matches = [key for key, name in produced.items() if name == output.name]
            source = matches[0] if len(matches) == 1 else None
        sources[output.name] = source if source in produced else None
    return sources


def _root_export_issues(node: StageGraphNode, pointer: str) -> list[ManifestIssue]:
    """OVE-169 E4: every Stage Graph root output is produced by exactly one of its stages
    (a promise nobody can submit is refused here, not discovered live)."""

    issues: list[ManifestIssue] = []
    children = {child.key: child for child in node.nodes}
    sources = stage_graph_root_sources(node)
    produced_refs = {
        f"{child.key}.{output.name}" for child in node.nodes for output in child.outputs
    }
    for index, export in enumerate(node.exports):
        if export.timing != "final":
            issues.append(
                _issue(
                    f"{pointer}/exports/{index}/timing",
                    "a program root exports what its mission owes; early timing applies to a "
                    "nested body only (a link's release condition times a chain)",
                    "unsupported_graph_position",
                    ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                )
            )
        if [item.output for item in node.exports].count(export.output) > 1:
            issues.append(
                _issue(f"{pointer}/exports/{index}/output", "duplicate export", "duplicate_key")
            )
        if export.output not in sources:
            issues.append(
                _issue(
                    f"{pointer}/exports/{index}/output",
                    f"{export.output} is not a declared output of {node.key}",
                    "nested_export_unknown_output",
                )
            )
        if export.from_ is not None and export.from_ not in produced_refs:
            issues.append(
                _issue(
                    f"{pointer}/exports/{index}/from",
                    f"{export.from_} is not an output of a stage of {node.key}",
                    "nested_export_unknown_source",
                )
            )
    for index, output in enumerate(node.outputs):
        source = sources[output.name]
        if source is None:
            issues.append(
                _issue(
                    f"{pointer}/outputs/{index}",
                    f"output {output.name} of Stage Graph root {node.key} has no producing "
                    "stage: declare it on one stage and name it with "
                    f"`exports: [{{output: {output.name}, from: <stage>.<output>}}]`",
                    "root_output_unbound",
                )
            )
            continue
        stage, _, name = source.partition(".")
        produced = next(item for item in children[stage].outputs if item.name == name)
        if (produced.form, produced.schema_) != (output.form, output.schema_):
            issues.append(
                _issue(
                    f"{pointer}/outputs/{index}",
                    f"output {output.name} (form {output.form.value}, schema {output.schema_}) "
                    f"differs from its producer {source} (form {produced.form.value}, schema "
                    f"{produced.schema_})",
                    "root_export_contract_mismatch",
                )
            )
    return issues


def _nested_body_issues(node: AnyProgramNode, pointer: str, *, root: bool) -> list[ManifestIssue]:
    """OVE-176: a Goal Loop executor body is one Stage Graph or Goal Loop; exports belong to a
    nested body only and name its declared outputs and inner producers; a nested body reads no
    producer outside itself (its inputs are not yet delivered across the boundary). A Stage
    Graph program root exports its outputs from its stages (OVE-169, ``_root_export_issues``)."""

    issues: list[ManifestIssue] = []
    if isinstance(node, GoalLoopNode):
        for index, child in enumerate(node.nodes):
            if not isinstance(child, StageGraphNode | GoalLoopNode):
                issues.append(
                    _issue(
                        f"{pointer}/nodes/{index}/behavior",
                        "a goal loop executor body is a stage_graph or goal_loop, not "
                        f"{child.behavior}",
                        "unsupported_nested_body",
                        ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                    )
                )
    if not isinstance(node, StageGraphNode | GoalLoopNode):
        return issues
    if root and isinstance(node, StageGraphNode):
        return issues + _root_export_issues(node, pointer)
    if node.exports and root:
        issues.append(
            _issue(
                f"{pointer}/exports",
                "a goal_loop program root owes its own outputs; exports apply to a nested body "
                "or a stage_graph root",
                "unsupported_graph_position",
                ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
            )
        )
    declared = {item.name for item in node.outputs}
    inner = {
        f"{item.key}.{output.name}"
        for item in _subtree(node)
        if item is not node
        for output in item.outputs
    }
    seen: set[str] = set()
    for index, export in enumerate(node.exports):
        at = f"{pointer}/exports/{index}"
        if export.output in seen:
            issues.append(
                _issue(f"{at}/output", f"duplicate export {export.output}", "duplicate_key")
            )
        seen.add(export.output)
        if export.output not in declared:
            issues.append(
                _issue(
                    f"{at}/output",
                    f"{export.output} is not a declared output of {node.key}",
                    "nested_export_unknown_output",
                )
            )
        if export.from_ is not None and (
            isinstance(node, GoalLoopNode) or export.from_ not in inner
        ):
            issues.append(
                _issue(
                    f"{at}/from",
                    f"{export.from_} is not an inner stage output of stage graph {node.key}"
                    if isinstance(node, StageGraphNode)
                    else "a goal loop exports its own outputs; `from` names stage graph producers",
                    "nested_export_unknown_source",
                )
            )
    if not root:
        keys = {item.key for item in _subtree(node)}
        for item in _subtree(node):
            for binding_index, binding in enumerate(item.inputs):
                producer = (binding.from_ or "").partition(".")[0]
                if binding.from_ is not None and producer not in keys:
                    issues.append(
                        _issue(
                            f"{pointer}/inputs/{binding_index}" if item is node else pointer,
                            f"{item.key}.{binding.name} reads {binding.from_} from outside the "
                            f"nested body {node.key}",
                            "nested_inherited_input_unsupported",
                            ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                        )
                    )
    return issues


def bound_producers(child: ProgramNodeBase, siblings: Iterable[str]) -> tuple[str, ...]:
    """Sibling producers a node reads through explicit ``from: <producer>.<output>`` bindings.

    OVE-171 (01-STAGE_GRAPH §3): a required data binding creates its input prerequisite; it
    needs no duplicate ``depends_on`` edge. Document order, unique."""

    known = set(siblings)
    found: list[str] = []
    for item in child.inputs:
        producer = (item.from_ or "").partition(".")[0]
        if producer in known and producer != child.key and producer not in found:
            found.append(producer)
    return tuple(found)


def _route_issues(
    node: StageGraphNode, pointer: str, siblings: Mapping[str, int]
) -> tuple[list[ManifestIssue], dict[str, set[str]]]:
    """Routes name declared facts of sibling stages, release siblings, target a stage at most
    once and never release the stage whose facts decide them. Returns route ordering edges."""

    issues: list[ManifestIssue] = []
    facts: dict[tuple[str, str], str] = {}
    for index, child in enumerate(node.nodes):
        structured = {
            item.name: item for item in child.outputs if item.form is OutputForm.STRUCTURED
        }
        names: set[str] = set()
        for fact_index, fact in enumerate(child.facts):
            fact_pointer = f"{pointer}/nodes/{index}/facts/{fact_index}"
            if fact.name in names:
                issues.append(_issue(f"{fact_pointer}/name", "duplicate fact", "duplicate_key"))
            names.add(fact.name)
            if fact.output not in structured:
                issues.append(
                    _issue(
                        f"{fact_pointer}/output",
                        f"{fact.output} is not a structured output of {child.key} (facts are "
                        "read from schema-validated bytes)",
                        "unknown_output",
                    )
                )
            facts[(child.key, fact.name)] = fact.type
    edges: dict[str, set[str]] = {}
    targeted: dict[str, str] = {}
    keys: set[str] = set()
    for route_index, route in enumerate(node.routes):
        route_pointer = f"{pointer}/routes/{route_index}"
        if route.key in keys:
            issues.append(_issue(f"{route_pointer}/key", "duplicate route", "duplicate_key"))
        keys.add(route.key)
        branch_keys = [item.key for item in route.branches]
        if len(set(branch_keys)) != len(branch_keys) or "else" in branch_keys:
            issues.append(
                _issue(
                    f"{route_pointer}/branches",
                    "branch keys are unique and never else",
                    "duplicate_key",
                )
            )
        sources: set[str] = set()
        targets: list[tuple[str, str]] = []
        for branch_index, branch in enumerate(route.branches):
            branch_pointer = f"{route_pointer}/branches/{branch_index}"
            for when_index, predicate in enumerate(branch.when):
                stage, _, name = predicate.fact.partition(".")
                kind = facts.get((stage, name))
                when_pointer = f"{branch_pointer}/when/{when_index}"
                if kind is None:
                    issues.append(
                        _issue(
                            f"{when_pointer}/fact",
                            f"{predicate.fact} is not a declared fact of a sibling stage",
                            "unknown_fact",
                        )
                    )
                    continue
                sources.add(stage)
                problem = _predicate_problem(predicate, kind)
                if problem:
                    issues.append(_issue(f"{when_pointer}/value", problem, "invalid_predicate"))
            targets.extend(
                (f"{branch_pointer}/release/{index}", stage)
                for index, stage in enumerate(branch.release)
            )
        targets.extend(
            (f"{route_pointer}/else/{index}", stage) for index, stage in enumerate(route.else_)
        )
        for target_pointer, stage in targets:
            if stage not in siblings:
                issues.append(
                    _issue(target_pointer, f"{stage} is not a sibling stage", "unknown_dependency")
                )
                continue
            if targeted.get(stage, route.key) != route.key:
                issues.append(
                    _issue(target_pointer, f"{stage} is released by two routes", "duplicate_route")
                )
            targeted[stage] = route.key
            if stage in sources:
                issues.append(
                    _issue(
                        target_pointer,
                        f"route {route.key} cannot release {stage}, whose facts decide it",
                        "dependency_cycle",
                    )
                )
            edges.setdefault(stage, set()).update(sources - {stage})
    return issues, edges


def _revisit_issues(
    node: StageGraphNode,
    pointer: str,
    siblings: Mapping[str, int],
    route_edges: Mapping[str, set[str]],
) -> list[ManifestIssue]:
    """A Revisit Region is a closed, entry-rooted set of sibling stages with typed stop facts."""

    issues: list[ManifestIssue] = []
    by_key = {child.key: child for child in node.nodes}
    facts = {(child.key, fact.name): fact.type for child in node.nodes for fact in child.facts}
    targets = set(route_edges)
    for index, region in enumerate(node.revisits):
        at = f"{pointer}/revisits/{index}"
        members = set(region.stages)
        unknown = sorted(members - siblings.keys())
        if unknown:
            issues.append(
                _issue(
                    f"{at}/stages",
                    f"{', '.join(unknown)} are not sibling stages",
                    "unknown_dependency",
                )
            )
            continue
        for field, stage in (("entry", region.entry), ("exit", region.exit)):
            if stage not in members:
                issues.append(
                    _issue(f"{at}/{field}", f"{stage} is not a region stage", "invalid_region")
                )
        if members & targets:
            issues.append(
                _issue(f"{at}/stages", "a region stage cannot be a route target", "invalid_region")
            )
        edges = {
            key: {*by_key[key].depends_on, *bound_producers(by_key[key], siblings)}
            | {m for g in by_key[key].release_groups for m in g.member_keys}
            for key in members
        }
        if region.entry in members and edges[region.entry] & members:
            issues.append(
                _issue(
                    f"{at}/entry", "the entry depends on no other region stage", "invalid_region"
                )
            )
        for stage in sorted(members - {region.entry}):
            seen: set[str] = set()
            frontier = [stage]
            while frontier:
                for producer in edges.get(frontier.pop(), set()) & members:
                    if producer not in seen:
                        seen.add(producer)
                        frontier.append(producer)
            if region.entry not in seen:
                issues.append(
                    _issue(
                        f"{at}/stages",
                        f"{stage} is not reached from the entry {region.entry}",
                        "invalid_region",
                    )
                )
        for when_index, predicate in enumerate(region.until):
            stage, _, name = predicate.fact.partition(".")
            kind = facts.get((stage, name)) if stage in members else None
            if kind is None:
                issues.append(
                    _issue(
                        f"{at}/until/{when_index}/fact",
                        f"{predicate.fact} is not a declared fact of a region stage",
                        "unknown_fact",
                    )
                )
                continue
            problem = _predicate_problem(predicate, kind)
            if problem:
                issues.append(
                    _issue(f"{at}/until/{when_index}/value", problem, "invalid_predicate")
                )
        if (region.progress is None) != (region.patience is None):
            issues.append(
                _issue(
                    f"{at}/patience",
                    "progress and patience are declared together",
                    "invalid_region",
                )
            )
        if region.progress is not None:
            stage, _, name = region.progress.partition(".")
            if stage not in members or facts.get((stage, name)) != "integer":
                issues.append(
                    _issue(
                        f"{at}/progress",
                        f"{region.progress} is not a declared integer fact of a region stage",
                        "unknown_fact",
                    )
                )
        exit_node = by_key.get(region.exit)
        outputs = {item.name for item in exit_node.outputs} if exit_node is not None else set()
        for carry_index, name in enumerate(region.carry):
            if name not in outputs:
                issues.append(
                    _issue(
                        f"{at}/carry/{carry_index}",
                        f"{name} is not a declared output of the exit {region.exit}",
                        "unknown_output",
                    )
                )
    return issues


def _predicate_problem(predicate: RoutePredicateDeclaration, kind: str) -> str | None:
    values = predicate.value if isinstance(predicate.value, tuple) else (predicate.value,)
    if (predicate.op in {"in", "not_in"}) != isinstance(predicate.value, tuple):
        return "in/not_in compare with a list; every other operator a scalar"
    if not values or len(values) > 32:
        return "a predicate compares with 1..32 values"
    expected = {"string": str, "integer": int, "boolean": bool}[kind]
    if any(type(item) is not expected for item in values):
        return f"the fact is a {kind}; compare it with {kind} values"
    if predicate.op in {"lt", "le", "gt", "ge"} and kind != "integer":
        return "ordered comparisons apply to integer facts only"
    return None


def _group_issues(
    child: ProgramNodeBase, pointer: str, siblings: Mapping[str, int]
) -> list[ManifestIssue]:
    issues: list[ManifestIssue] = []
    seen: set[str] = set(child.depends_on)
    keys: set[str] = set()
    for group_index, group in enumerate(child.release_groups):
        group_pointer = f"{pointer}/release_groups/{group_index}"
        if group.key in keys or group.key == "inputs":
            issues.append(
                _issue(
                    f"{group_pointer}/key",
                    "group keys are unique and never inputs",
                    "duplicate_key",
                )
            )
        keys.add(group.key)
        members = group.member_keys
        for member_index, member in enumerate(members):
            member_pointer = f"{group_pointer}/members/{member_index}"
            if member not in siblings or member == child.key:
                issues.append(
                    _issue(member_pointer, f"{member} is not a sibling stage", "unknown_dependency")
                )
            elif member in seen:
                issues.append(
                    _issue(
                        member_pointer,
                        f"{member} is already a dependency or a member of another group",
                        "duplicate_dependency",
                    )
                )
            seen.add(member)
        if isinstance(group.join, QuorumJoin) and group.join.quorum > len(members):
            issues.append(
                _issue(
                    f"{group_pointer}/join/quorum",
                    "quorum exceeds the number of group members",
                    "invalid_join",
                )
            )
        reachable = {subject for subjects in group.covers().values() for subject in subjects}
        missing = sorted(set(group.coverage) - reachable)
        if missing:
            issues.append(
                _issue(
                    f"{group_pointer}/coverage",
                    f"no member covers {', '.join(missing)}",
                    "uncoverable_group",
                )
            )
        if any(
            item.required is False and (item.from_ or "").partition(".")[0] in members
            for item in child.inputs
        ):
            issues.append(
                _issue(
                    f"{group_pointer}/members",
                    "release group members are required inputs",
                    "invalid_join",
                )
            )
    return issues


def _stage_graph_issues(node: StageGraphNode, pointer: str) -> list[ManifestIssue]:
    issues: list[ManifestIssue] = []
    siblings: dict[str, int] = {}
    for index, child in enumerate(node.nodes):
        siblings.setdefault(child.key, index)
    route_issues, route_edges = _route_issues(node, pointer, siblings)
    issues.extend(route_issues)
    issues.extend(_revisit_issues(node, pointer, siblings, route_edges))
    edges: dict[str, tuple[str, ...]] = {}
    for index, child in enumerate(node.nodes):
        issues.extend(_group_issues(child, f"{pointer}/nodes/{index}", siblings))
        for dep_index, dependency in enumerate(child.depends_on):
            if dependency not in siblings or dependency == child.key:
                issues.append(
                    _issue(
                        f"{pointer}/nodes/{index}/depends_on/{dep_index}",
                        f"{dependency} is not a sibling stage of {child.key}",
                        "unknown_dependency",
                    )
                )
        if isinstance(child.join, QuorumJoin) and child.join.quorum > len(child.depends_on):
            issues.append(
                _issue(
                    f"{pointer}/nodes/{index}/join/quorum",
                    "quorum exceeds the number of dependencies",
                    "invalid_join",
                )
            )
        grouped = tuple(
            member
            for group in child.release_groups
            for member in group.member_keys
            if member in siblings
        )
        # OVE-171: bindings, group members and route facts order a stage as dependencies do.
        edges[child.key] = edges.get(child.key, ()) + tuple(
            dict.fromkeys(
                (
                    *(dep for dep in child.depends_on if dep in siblings),
                    *bound_producers(child, siblings),
                    *grouped,
                    *sorted(route_edges.get(child.key, ())),
                )
            )
        )
    cycle = find_cycle(edges)
    if cycle:
        issues.append(
            _issue(
                f"{pointer}/nodes/{siblings[cycle[0]]}/depends_on",
                "stage dependencies form a cycle: " + " -> ".join(cycle),
                "dependency_cycle",
            )
        )
    return issues


def find_cycle(edges: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """A cycle in a directed graph given as node -> successors, or ``()``; deterministic."""

    state: dict[str, int] = {}
    path: list[str] = []

    def visit(node: str) -> tuple[str, ...]:
        state[node] = 1
        path.append(node)
        for successor in sorted(edges.get(node, ())):
            if state.get(successor) == 1:
                return (*path[path.index(successor) :], successor)
            if successor not in state and (found := visit(successor)):
                return found
        path.pop()
        state[node] = 2
        return ()

    for node in sorted(edges):
        if node not in state and (found := visit(node)):
            return found
    return ()


def _node_environments(
    block: MissionBlock, pointer: str
) -> tuple[list[NodeEnvironment], list[ManifestIssue], list[ManifestIssue]]:
    blockers: list[ManifestIssue] = []
    warnings: list[ManifestIssue] = []
    resolved: list[NodeEnvironment] = []
    mission_environment = block.environment
    if mission_environment.side_effects is None:
        mission_environment = type(mission_environment).model_validate(
            {**mission_environment.authored(), "side_effects": list(DEFAULT_SIDE_EFFECTS)}
        )
    effective_by_key: dict[str, Environment] = {}
    program_pointer = f"{pointer}/program"
    for visit in walk_program(block.program, program_pointer):
        node = visit.node
        parent = (
            mission_environment if visit.parent_key is None else effective_by_key[visit.parent_key]
        )
        env_pointer = f"{visit.pointer}/environment"
        effective, provenance = _overlay_environment(parent, node.environment)
        if node.environment is not None:
            blockers.extend(_narrowing_issues(parent, effective, node.environment, env_pointer))
            node_blockers, node_warnings = _lane_issues(effective, env_pointer, mission_level=False)
            if node.environment.lane is not None:
                blockers.extend(node_blockers)
                warnings.extend(node_warnings)
        effective_by_key[node.key] = effective
        lane = effective.lane or Lane.DEEP_AGENTS
        resolved.append(
            NodeEnvironment(
                node_key=node.key,
                pointer=visit.pointer,
                behavior=Behavior(node.behavior),
                lane=lane,
                lane_changed_from=(
                    parent.lane if parent.lane is not None and parent.lane != lane else None
                ),
                effective_environment=effective,
                field_provenance=provenance,
            )
        )
        governors = effective.governors or Governors()
        if isinstance(node, GoalLoopNode):
            for name in ("iterations", "patience"):
                if getattr(governors, name) is None:
                    blockers.append(
                        _issue(
                            f"{env_pointer}/governors/{name}",
                            f"a goal_loop needs governors.{name} (inherited or overlay)",
                            "missing_governors",
                        )
                    )
            if node.verifier is not None and node.verifier.environment is not None:
                verifier_pointer = f"{visit.pointer}/verifier/environment"
                verifier_env, verifier_provenance = _overlay_environment(
                    effective, node.verifier.environment
                )
                blockers.extend(
                    _narrowing_issues(
                        effective, verifier_env, node.verifier.environment, verifier_pointer
                    )
                )
                verifier_blockers, verifier_warnings = _lane_issues(
                    verifier_env, verifier_pointer, mission_level=False
                )
                if node.verifier.environment.lane is not None:
                    blockers.extend(verifier_blockers)
                    warnings.extend(verifier_warnings)
                verifier_lane = verifier_env.lane or lane
                resolved.append(
                    NodeEnvironment(
                        node_key=node.key,
                        role="verifier",
                        pointer=f"{visit.pointer}/verifier",
                        behavior=Behavior(node.behavior),
                        lane=verifier_lane,
                        lane_changed_from=lane if verifier_lane != lane else None,
                        effective_environment=verifier_env,
                        field_provenance=verifier_provenance,
                    )
                )
        if isinstance(node, ChildMissionInvocationNode) and governors.depth is None:
            blockers.append(
                _issue(
                    f"{env_pointer}/governors/depth",
                    "a child_mission_invocation needs governors.depth",
                    "missing_governors",
                )
            )
    return resolved, blockers, warnings


def resolve_mission(
    block: MissionBlock, pointer: str
) -> tuple[MissionEnvironments, list[ManifestIssue], list[ManifestIssue]]:
    """Structural validation and effective environments for one mission block."""

    blockers: list[ManifestIssue] = []
    warnings: list[ManifestIssue] = []
    env_pointer = f"{pointer}/environment"
    blockers.extend(_mission_environment_issues(block.environment, env_pointer))
    lane_blockers, lane_warnings = _lane_issues(block.environment, env_pointer, mission_level=True)
    blockers.extend(lane_blockers)
    warnings.extend(lane_warnings)
    objective_refs, goal_issues = _goal_index(block, pointer)
    blockers.extend(goal_issues)
    blockers.extend(_program_issues(block, pointer, objective_refs))
    nodes, node_blockers, node_warnings = _node_environments(block, pointer)
    blockers.extend(node_blockers)
    warnings.extend(node_warnings)
    return (
        MissionEnvironments(mission_key=block.key, pointer=pointer, nodes=tuple(nodes)),
        blockers,
        warnings,
    )


def _dedupe(issues: Iterable[ManifestIssue]) -> tuple[ManifestIssue, ...]:
    seen: dict[tuple[str, str, str], ManifestIssue] = {}
    for issue in issues:
        seen.setdefault((issue.code.value, issue.pointer, issue.message), issue)
    return tuple(seen.values())


def resolve_environments(
    manifest: MissionManifest, document: Mapping[str, Any]
) -> ManifestStructure:
    """Validate structure (keys, references, lanes, governors, narrowing) and compute every
    node's effective Environment with field provenance. Link semantics are SPEC-04's."""

    blockers: list[ManifestIssue] = []
    warnings: list[ManifestIssue] = []
    missions: list[MissionEnvironments] = []
    keys: set[str] = set()
    for pointer, block in manifest.mission_blocks():
        if block.key in keys:
            blockers.append(
                _issue(f"{pointer}/key", f"duplicate mission key {block.key}", "duplicate_key")
            )
        keys.add(block.key)
        environments, mission_blockers, mission_warnings = resolve_mission(block, pointer)
        missions.append(environments)
        blockers.extend(mission_blockers)
        warnings.extend(mission_warnings)
    return ManifestStructure(
        manifest_digest=manifest_digest(document),
        missions=tuple(missions),
        blockers=_dedupe(blockers),
        warnings=_dedupe(warnings),
    )

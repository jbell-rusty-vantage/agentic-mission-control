"""The Mission Manifest reference, generated from the manifest models and their validators.

A Coordinator that has only the MCP server has no schema file and no example to copy, so the
server says what a manifest holds. Nothing here is a hand-copied field list:

- the fields, which are required, their allowed values and their defaults come from the JSON
  Schema of `MissionManifestV2` (`domain/authoring/manifest_v2.py`), the same schema
  `missionctl mission schema` prints;
- what a rule in a validator requires is found by asking the validator: each lane's required
  `environment` fields from `resolve_environments` over a manifest that leaves them out, and
  the output forms that need or refuse a `schema` from `OutputDeclaration`;
- which acceptance operator can start where is found by asking the check a start applies
  (`completion_support.launch_acceptance_issues`) for every operator at every location.

`REQUIRED_SHAPES`, `VALUE_FIELDS` and `SECTION_PLACES` only choose which models the short page
shows and where each sits in the YAML; `tests/unit/guide/test_manifest_reference.py` holds every
name in them to the schema.

Provider-neutral and application-neutral: every lane, value and field is read from a model.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Final, get_args

from pydantic import ValidationError

from mission_control.application.authoring.completion_support import launch_acceptance_issues
from mission_control.domain.authoring import manifest as manifest_v1
from mission_control.domain.authoring import manifest_v2
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.manifest import (
    APPLICATION_ID_PATTERN,
    DURATION_PATTERN,
    EVENT_TYPE_PATTERN,
    OUTPUT_REF_PATTERN,
    PIN_PATTERN,
    PROFILE_PATTERN,
    SCHEMA_REF_PATTERN,
    SLUG_PATTERN,
    HumanTaskSpec,
    ManifestRejected,
    OutputDeclaration,
    resolve_environments,
)
from mission_control.domain.authoring.manifest_lowering import lower_mission
from mission_control.domain.authoring.manifest_v2 import (
    MANIFEST_V2_LITERAL,
    MissionManifestV2,
    parse_manifest_any,
)
from mission_control.domain.authoring.mission_definition import manifest_to_definitions
from mission_control.domain.execution.lanes import DEFAULT_LANE_PROFILE
from mission_control.domain.outputs.contracts import OutputForm
from mission_control.domain.programs.completion import OutputSchemaBinding

MANIFEST_REF: Final = "manifest"
ROOT_SECTION: Final = "MissionManifest"
_V2: Final = "V2"
# The longest vocabulary a field's row writes out; a longer one is named and is a section.
_INLINE_VALUES: Final = 6
# What a string pattern of the schema means to an author.
_PATTERNS: Final[Mapping[str, str]] = {
    SLUG_PATTERN: "slug",
    APPLICATION_ID_PATTERN: "application id",
    PROFILE_PATTERN: "profile name",
    SCHEMA_REF_PATTERN: "`<schema>@<revision>`",
    OUTPUT_REF_PATTERN: "`<node key>.<output name>`",
    PIN_PATTERN: "`<id>@<version>#sha256:<digest>` or `<id>@latest`",
    EVENT_TYPE_PATTERN: "event type",
    DURATION_PATTERN: "duration",
    r"^artifact://\S+$": "`artifact://...`",
}
# Where each model sits in a manifest, in reading order: the sections of the full reference.
SECTION_PLACES: Final[Mapping[str, str]] = {
    ROOT_SECTION: "the document",
    "MissionBlock": "`mission`",
    "MissionBrief": "`mission.brief`, the interview's result in the user's words",
    "BriefAnswer": "`brief.answers[]`",
    "Goal": "`mission.goals[]`",
    "Objective": "`goals[].objectives[]`",
    "SuccessCriterion": "`goals[].criteria[]`",
    "Acceptance": "`criteria[].acceptance`, a node's `completion.acceptance`",
    "AssessmentAcceptance": "`acceptance.assessment`",
    "Environment": "`mission.environment`, a node's `environment` overlay",
    "ModelSelection": "`environment.model`",
    "SandboxSelection": "`environment.sandbox`",
    "Budget": "`environment.budget`",
    "Governors": "`environment.governors`",
    "CapabilityEntry": "`environment.capabilities[]`",
    "CapabilityReference": "`environment.plugins[]`, `workspace.skills[]`",
    "AgentEntry": "`environment.agents[]`",
    "HookEntry": "`environment.hooks[]`",
    "StageGraphNode": "`mission.program` or a stage",
    "GoalLoopNode": "`mission.program` or a stage",
    "Verifier": "a Goal Loop's `verifier`",
    "AgentExecutorNode": "a stage",
    "HumanGateNode": "a stage",
    "HumanTaskSpec": "a human gate's `task`",
    "InputBinding": "a node's `inputs[]`",
    "OutputDeclaration": "a node's `outputs[]`",
    "OutputRequirementDeclaration": "`outputs[].requirements[]`",
    "Controls": "`mission.controls`",
}
# The shapes whose required fields the short page lists, with where each sits.
REQUIRED_SHAPES: Final[tuple[tuple[str, str], ...]] = (
    ("the document", ROOT_SECTION),
    ("`mission`", "MissionBlock"),
    ("`brief`", "MissionBrief"),
    ("`goals[]`", "Goal"),
    ("`goals[].objectives[]`", "Objective"),
    ("`goals[].criteria[]`", "SuccessCriterion"),
    ("`behavior: stage_graph`", "StageGraphNode"),
    ("`behavior: goal_loop`", "GoalLoopNode"),
    ("`behavior: agent_executor`", "AgentExecutorNode"),
    ("`behavior: human_gate`", "HumanGateNode"),
    ("a gate's `task`", "HumanTaskSpec"),
    ("`inputs[]`", "InputBinding"),
    ("`outputs[]`", "OutputDeclaration"),
)
# The enumerated fields the short page lists: (label, section, field).
VALUE_FIELDS: Final[tuple[tuple[str, str, str], ...]] = (
    ("`brief.purpose`", "MissionBrief", "purpose"),
    ("`goals[].importance`", "Goal", "importance"),
    ("`task.kind`", "HumanTaskSpec", "kind"),
    ("`outputs[].form`", "OutputDeclaration", "form"),
    ("`outputs[].enforcement`", "OutputDeclaration", "enforcement"),
    ("`inputs[].expand`", "InputBinding", "expand"),
    ("`environment.side_effects[]`", "Environment", "side_effects"),
    ("a capability entry's `kind`", "CapabilityEntry", "kind"),
)
# The acceptance operators as authored, each with one probe expression.
_PROBE_SCHEMA: Final = "probe@1"
ACCEPTANCE_PROBES: Final[tuple[tuple[str, Mapping[str, Any]], ...]] = (
    ("`human: review_accept`", {"human": "review_accept"}),
    ("`human: approved`", {"human": "approved"}),
    ("`schema: <schema>@<revision>`", {"schema": _PROBE_SCHEMA}),
    (
        "`assessment`",
        {"assessment": {"capability": {"pin": "assessment.probe@latest"}, "threshold": 1}},
    ),
    ("`all`", {"all": [{"human": "review_accept"}]}),
    ("`any`", {"any": [{"human": "review_accept"}]}),
)


class UnknownSection(KeyError):
    """`manifest:<section>` names no model of the manifest."""


# -- the schema ----------------------------------------------------------------------------------


@cache
def _schema() -> dict[str, Any]:
    return MissionManifestV2.model_json_schema(by_alias=True, mode="validation")


@cache
def _sections() -> dict[str, dict[str, Any]]:
    """Every model of the manifest by its section name. A `mission/v2` model takes the name of
    the `mission/v1` model it extends (`Environment` is `EnvironmentV2`); a module-qualified
    name keeps its last part, the authoring module's first."""

    schema = _schema()
    definitions: dict[str, dict[str, Any]] = schema["$defs"]
    sections: dict[str, dict[str, Any]] = {
        ROOT_SECTION: {key: value for key, value in schema.items() if key != "$defs"}
    }
    for name in sorted(definitions, key=lambda item: ("authoring__manifest" not in item, item)):
        if f"{name}{_V2}" in definitions:
            continue
        sections.setdefault(_section_name(name), definitions[name])
    return sections


def _section_name(definition: str) -> str:
    return definition.rsplit("__", 1)[-1].removesuffix(_V2)


def section_names() -> tuple[str, ...]:
    """The reference's sections first, then every other model by name."""

    rest = sorted(name for name in _sections() if name not in SECTION_PLACES)
    return (*SECTION_PLACES, *rest)


def _model(section: str) -> type[Any] | None:
    for module in (manifest_v2, manifest_v1):
        for name in (f"{section}{_V2}", section):
            found = getattr(module, name, None)
            if isinstance(found, type):
                return found
    return None


def required_fields(section: str) -> tuple[str, ...]:
    """The fields a model requires, in its own order: the schema's `required`, plus
    `objectives` where the node's validator demands it."""

    node = _sections()[section]
    required = set(node.get("required", ()))
    if getattr(_model(section), "requires_objectives", False):
        required.add("objectives")
    return tuple(name for name in node.get("properties", {}) if name in required)


def one_of(section: str) -> tuple[str, ...]:
    """The fields of which a model takes exactly one (`pin` or `search`), where it says so."""

    variants = _sections()[section].get("oneOf", ())
    if not variants or any(
        set(variant) != {"required"} or len(variant["required"]) != 1 for variant in variants
    ):
        return ()
    return tuple(variant["required"][0] for variant in variants)


def allowed_values(section: str, field: str) -> tuple[tuple[str, ...], str | None]:
    """A field's enumerated values and its default (`None`: it has none)."""

    node = _sections()[section]["properties"][field]
    default = node.get("default")
    return _values(node), default if isinstance(default, str) else None


def _resolve(node: Mapping[str, Any]) -> Mapping[str, Any]:
    ref = node.get("$ref")
    if isinstance(ref, str):
        return _schema()["$defs"][ref.rsplit("/", 1)[-1]]
    return node


def _values(node: Mapping[str, Any]) -> tuple[str, ...]:
    """The closed set of strings a node admits, through references, lists and alternatives."""

    resolved = _resolve(node)
    if "const" in resolved:
        return (str(resolved["const"]),)
    if "enum" in resolved:
        return tuple(str(value) for value in resolved["enum"])
    if resolved.get("type") == "array" and "items" in resolved:
        return _values(resolved["items"])
    found: list[str] = []
    for variant in (*resolved.get("anyOf", ()), *resolved.get("oneOf", ())):
        found += [value for value in _values(variant) if value not in found]
    return tuple(found)


def _type(node: Mapping[str, Any]) -> str:
    """One field's value as an author writes it."""

    ref = node.get("$ref")
    if isinstance(ref, str):
        target = _resolve(node)
        name = _section_name(ref.rsplit("/", 1)[-1])
        if "enum" in target:
            # A short vocabulary is written out; a long one is its own section.
            values = target["enum"]
            return _spans(values) if len(values) <= _INLINE_VALUES else f"a `{name}` value"
        return f"`{name}`"
    if "const" in node:
        return f"`{node['const']}`"
    if "enum" in node:
        return _spans(node["enum"])
    variants = [item for item in node.get("anyOf", ()) if item.get("type") != "null"]
    if variants:
        if str(node.get("description", "")).startswith("Seconds"):
            return "duration (seconds, or `4h`, `1h30m`)"
        return " or ".join(dict.fromkeys(_type(item) for item in variants))
    kind = node.get("type")
    if kind == "array":
        return f"list of {_type(node.get('items', {}))}"
    if kind == "object":
        return "mapping"
    if kind == "string":
        return _PATTERNS.get(str(node.get("pattern")), "text")
    if isinstance(kind, str):
        return kind
    return "any value"


def section_markdown(section: str) -> str:
    """One model's fields as a table; `UnknownSection` for a name that is no model."""

    sections = _sections()
    if section not in sections:
        raise UnknownSection(section)
    node = sections[section]
    place = SECTION_PLACES.get(section)
    lines = [f"### `{section}`" + (f": {place}" if place else ""), ""]
    if "enum" in node:
        return "\n".join([*lines, f"One of {_spans(node['enum'])}."])
    required = set(required_fields(section))
    lines += ["| Field | Required | Value |", "| --- | --- | --- |"]
    for name, field in node.get("properties", {}).items():
        default = field.get("default")
        suffix = (
            f" (default `{default if isinstance(default, str) else json.dumps(default)}`)"
            if isinstance(default, str | bool | int) and "const" not in field
            else ""
        )
        value = _type(field).replace("|", "\\|")
        lines.append(f"| `{name}` | {'yes' if name in required else ''} | {value}{suffix} |")
    choice = one_of(section)
    if choice:
        lines += ["", f"Exactly one of {_spans(choice)}."]
    return "\n".join(lines)


# -- what the validators require -----------------------------------------------------------------


def _probe_document(
    program: Mapping[str, Any],
    *,
    environment: Mapping[str, Any],
    acceptance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The smallest whole manifest around one program and one environment."""

    criterion = {
        "key": "criterion",
        "description": "probe",
        "evidence": ["result"],
        "acceptance": acceptance or {"human": "review_accept"},
    }
    return {
        "manifest": MANIFEST_V2_LITERAL,
        "mission": {
            "key": "probe",
            "title": "probe",
            "application": "probe",
            "goals": [{"key": "goal", "description": "probe", "criteria": [criterion]}],
            "environment": dict(environment),
            "program": dict(program),
        },
    }


_STAGE: Final[Mapping[str, Any]] = {
    "key": "work",
    "behavior": "agent_executor",
    "objectives": ["goal"],
    "instruction": "probe",
    "outputs": [{"name": "result", "schema": _PROBE_SCHEMA}],
}


def _graph(*stages: Mapping[str, Any]) -> dict[str, Any]:
    return {"key": "root", "behavior": "stage_graph", "objectives": ["goal"], "nodes": list(stages)}


@cache
def lane_environment_requirements(lane: str) -> tuple[str, ...]:
    """What the mission-level `environment` of a `mission/v2` manifest must hold on one lane,
    as dotted paths: the fields the structural validation reports missing when the environment
    names the lane and nothing else, each replaced by the fields it reports missing inside it
    once the field is present and empty."""

    prefix = "/mission/environment/"

    def missing(environment: Mapping[str, Any]) -> tuple[str, ...]:
        document = _probe_document(_graph(_STAGE), environment=environment)
        try:
            structure = resolve_environments(parse_manifest_any(document), document)
        except ManifestRejected:
            # An empty mapping is not a valid value of this field: nothing deeper to report.
            return ()
        return tuple(
            dict.fromkeys(
                issue.pointer.removeprefix(prefix).replace("/", ".")
                for issue in structure.blockers
                if issue.reason == "missing_field" and issue.pointer.startswith(prefix)
            )
        )

    found: list[str] = []
    for name in missing({"lane": lane}):
        inside = missing({"lane": lane, name: {}}) if "." not in name else ()
        found += [item for item in inside if item.startswith(f"{name}.")] or [name]
    return tuple(dict.fromkeys(found))


@cache
def output_schema_rules() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The output forms that need a `schema` and the forms that refuse one."""

    def refused(document: dict[str, Any]) -> bool:
        try:
            OutputDeclaration.model_validate(document)
        except ValidationError:
            return True
        return False

    needs = tuple(
        form.value for form in OutputForm if refused({"name": "result", "form": form.value})
    )
    refuses = tuple(
        form.value
        for form in OutputForm
        if refused({"name": "result", "form": form.value, "schema": _PROBE_SCHEMA})
    )
    return needs, refuses


@dataclass(frozen=True, slots=True)
class AcceptanceLocation:
    """Where a criterion's acceptance is evaluated: what owns the goal."""

    label: str
    program: Mapping[str, Any]


def _gate(kind: str) -> dict[str, Any]:
    return {
        "key": "gate",
        "behavior": "human_gate",
        "objectives": ["goal"],
        "depends_on": ["work"],
        "task": {"kind": kind, "prompt": "probe", "reviewers": ["reviewer"]},
    }


def acceptance_locations() -> tuple[AcceptanceLocation, ...]:
    """A Goal Loop program root, an agent stage, and a human gate of each task kind."""

    loop = {
        "key": "root",
        "behavior": "goal_loop",
        "objective": "goal",
        "action_space": ["root"],
        "outputs": [{"name": "result", "schema": _PROBE_SCHEMA}],
    }
    kinds = get_args(HumanTaskSpec.model_fields["kind"].annotation)
    return (
        AcceptanceLocation("a `goal_loop` program root", loop),
        AcceptanceLocation("an `agent_executor` stage", _graph(_STAGE)),
        *(
            AcceptanceLocation(
                f"a `human_gate` stage, `task.kind: {kind}`", _graph(_STAGE, _gate(kind))
            )
            for kind in kinds
        ),
    )


def _starts(location: AcceptanceLocation, acceptance: Mapping[str, Any]) -> bool:
    """Whether a start accepts this operator at this location: the check a start applies,
    over a manifest whose only variable is the operator and the goal's owner."""

    environment = {
        "lane": DEFAULT_LANE_PROFILE,
        "model": {"profile": "probe"},
        "sandbox": {"profile": "probe"},
        "budget": {"usd": 1},
        "governors": {"depth": 1},
    }
    document = _probe_document(location.program, environment=environment, acceptance=acceptance)
    (definition,) = manifest_to_definitions(parse_manifest_any(document), document)
    body = {"type": "object"}
    schemas = {
        _PROBE_SCHEMA: OutputSchemaBinding(
            schema_ref=_PROBE_SCHEMA,
            source_digest=sha256_digest({"probe": _PROBE_SCHEMA}),
            schema_digest=sha256_digest(body),
            json_schema=body,
        )
    }
    blueprint = lower_mission(definition, output_schemas=schemas).blueprint
    return not launch_acceptance_issues(definition, blueprint, schemas)


@cache
def acceptance_support() -> tuple[tuple[str, tuple[tuple[str, bool], ...]], ...]:
    """Every acceptance operator with, per location, whether a start accepts it there."""

    locations = acceptance_locations()
    return tuple(
        (label, tuple((location.label, _starts(location, expression)) for location in locations))
        for label, expression in ACCEPTANCE_PROBES
    )


def acceptance_table() -> str:
    """The table of `acceptance_support`: one column per location, locations that decide
    alike sharing one, operators that decide alike sharing a row."""

    support = acceptance_support()
    columns: dict[tuple[bool, ...], list[str]] = {}
    for index, location in enumerate(acceptance_locations()):
        verdicts = tuple(row[index][1] for _label, row in support)
        columns.setdefault(verdicts, []).append(location.label)
    rows: dict[tuple[str, ...], list[str]] = {}
    for position, (label, _row) in enumerate(support):
        cells = tuple("starts" if verdicts[position] else "refused" for verdicts in columns)
        rows.setdefault(cells, []).append(label)
    return _table(
        ["`acceptance` on a goal owned by", *(_merged(labels) for labels in columns.values())],
        [[", ".join(labels), *cells] for cells, labels in rows.items()],
    )


def _merged(labels: Sequence[str]) -> str:
    """Location labels that differ only in their last value, as one label."""

    if len(labels) == 1:
        return labels[0]
    head, _, _ = labels[0].rpartition(": ")
    tails = [label.rpartition(": ")[2].rstrip("`") for label in labels]
    return f"{head}: {'`, `'.join(tails)}`"


# -- the pages -----------------------------------------------------------------------------------


def manifest_topic_section(
    *, lanes: Iterable[str], sandbox_profiles: Mapping[str, str] | None, application_id: str
) -> str:
    """The generated part of the `manifest` topic: required fields, allowed values, what each
    bound lane requires, which acceptance starts where and the sandbox profiles bound here,
    each with the one line that says what it suits (`sandbox_profiles`: name -> line)."""

    required = _table(
        ["Where", "Required"],
        [[label, _spans(required_fields(section))] for label, section in REQUIRED_SHAPES],
    )
    values = []
    for label, section, field in VALUE_FIELDS:
        allowed, default = allowed_values(section, field)
        values.append(
            f"- {label}: {_spans(allowed)}" + (f" (default `{default}`)" if default else "")
        )
    needs, refuses = output_schema_rules()
    values.append(
        f"- `outputs[].schema`: required for the forms {_spans(needs)}, refused for "
        f"{_spans(refuses)}"
    )
    values.append(f"- `acceptance`: exactly one of {_spans(one_of('Acceptance'))}")
    # Lanes that require the same share one row.
    by_requirement: dict[tuple[str, ...], list[str]] = {}
    for lane in lanes:
        by_requirement.setdefault(lane_environment_requirements(lane), []).append(lane)
    lane_rows = [[_spans(names), _spans(needed)] for needed, names in by_requirement.items()]
    sandboxes = (
        "This server does not launch, so it binds no sandbox profile."
        if sandbox_profiles is None
        else "\n".join(
            [
                "Sandbox profiles bound here (`environment.sandbox.profile`); read one in "
                "full with its `sandbox:<name>` ref:",
                *(f"- `{name}`: {line}" for name, line in sandbox_profiles.items()),
            ]
        )
        if sandbox_profiles
        else "No sandbox profile is bound here: a `deep_agents` node cannot start."
    )
    return "\n\n".join(
        [
            f"`manifest` is `{MANIFEST_V2_LITERAL}`; `mission.application` is `{application_id}`.",
            required,
            "\n".join(values),
            "The mission `environment` must hold, per lane:",
            _table(["Lane", "Required in `mission.environment`"], lane_rows),
            sandboxes,
            "## Which acceptance can start",
            acceptance_table(),
        ]
    )


def manifest_reference_markdown() -> str:
    """The full reference: every section of `SECTION_PLACES`, then the name of every other."""

    others = [name for name in section_names() if name not in SECTION_PLACES]
    needs, refuses = output_schema_rules()
    return "\n\n".join(
        [
            "# Mission Manifest reference",
            f"A manifest is YAML. Its first key is `manifest: {MANIFEST_V2_LITERAL}`. An unknown "
            "key is refused everywhere. Each table is one mapping: its fields, which are "
            "required and what each takes. A value named like `Goal` is the table of that name.",
            *(section_markdown(section) for section in SECTION_PLACES),
            "## Rules the tables do not show",
            f"- An output's `schema` is required for the forms {_spans(needs)} and refused for "
            f"{_spans(refuses)}.",
            "## Which acceptance can start",
            acceptance_table(),
            "## More sections",
            f"Read any of these with `{MANIFEST_REF}:<section>`: {_spans(others)}.",
        ]
    )


def manifest_reference_document() -> dict[str, Any]:
    """The reference as data: each core section's required fields, and the other sections."""

    return {
        "manifest": MANIFEST_V2_LITERAL,
        "sections": {
            section: {"place": place, "required": list(required_fields(section))}
            for section, place in SECTION_PLACES.items()
        },
        "more_sections": [name for name in section_names() if name not in SECTION_PLACES],
        "acceptance": {label.strip("`"): dict(row) for label, row in acceptance_support()},
    }


def _spans(names: Iterable[object]) -> str:
    return ", ".join(f"`{name}`" for name in names) or "none"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = [f"| {' | '.join(header)} |", f"|{' --- |' * len(header)}"]
    lines += [f"| {' | '.join(row)} |" for row in rows]
    return "\n".join(lines)


__all__ = [
    "ACCEPTANCE_PROBES",
    "MANIFEST_REF",
    "REQUIRED_SHAPES",
    "ROOT_SECTION",
    "SECTION_PLACES",
    "VALUE_FIELDS",
    "AcceptanceLocation",
    "UnknownSection",
    "acceptance_locations",
    "acceptance_support",
    "acceptance_table",
    "allowed_values",
    "lane_environment_requirements",
    "manifest_reference_document",
    "manifest_reference_markdown",
    "manifest_topic_section",
    "one_of",
    "output_schema_rules",
    "required_fields",
    "section_markdown",
    "section_names",
]

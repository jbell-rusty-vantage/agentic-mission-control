"""The manifest reference is generated from the manifest models, and what it says is true.

No name in it is hand-copied: every section, field and value comes from the schema of
`MissionManifestV2`. What a validator requires (a lane's `environment`, an output's `schema`,
which acceptance can start) is asked of the validator, and here the answers are held to the real
compiler over the seeded in-memory catalog: the acceptance table says what `startable` says.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from mission_control.application.guide import manifest_reference as reference
from mission_control.application.guide.service import GuideRefused
from mission_control.domain.authoring.manifest import (
    AgentExecutorNode,
    Behavior,
    CapabilityKind,
    Goal,
    HumanTaskSpec,
    SideEffect,
    canonical_manifest_bytes,
)
from mission_control.domain.authoring.manifest_v2 import MissionManifestV2
from mission_control.domain.execution.lanes import DEFAULT_LANE_PROFILE, LANE_PROFILES
from mission_control.domain.outputs.contracts import Enforcement, OutputForm
from tests.support.manifests.compile import scope, service
from tests.unit.guide.support import SANDBOXES, full_guide, stub_guide

# The owner's budget for the short page, in tokens (characters divided by four).
MANIFEST_TOPIC_TOKENS = 1_500
APPLICATION = "ai-engineer"


def test_every_named_section_and_field_is_in_the_manifest_schema() -> None:
    definitions = MissionManifestV2.model_json_schema(by_alias=True)["$defs"]
    sections = set(reference.section_names())

    assert set(reference.SECTION_PLACES) <= sections
    for _label, section in reference.REQUIRED_SHAPES:
        assert section in sections, section
    for _label, section, field in reference.VALUE_FIELDS:
        assert reference.allowed_values(section, field)[0], (section, field)
    # A `mission/v2` model answers under the name of the model it extends; every other model
    # of the schema is a section too.
    assert {"Environment", "MissionBlock", "StageGraphNode", "TimerNode", "HookEvent"} <= sections
    assert not [name for name in sections if name.endswith("V2")]
    assert len(sections) >= len({name.removesuffix("V2") for name in definitions}) - 1


def test_required_fields_and_values_are_the_models_own() -> None:
    assert reference.required_fields("MissionBlock") == (
        "key",
        "title",
        "application",
        "goals",
        "environment",
        "program",
    )
    assert reference.required_fields("Goal") == ("key", "description", "criteria")
    assert reference.required_fields("SuccessCriterion") == (
        "key",
        "description",
        "evidence",
        "acceptance",
    )
    # `objectives` is demanded by the node's validator, not by the schema.
    assert AgentExecutorNode.requires_objectives is True
    assert reference.required_fields("AgentExecutorNode") == ("key", "objectives", "instruction")
    assert reference.required_fields("StageGraphNode") == ("key", "objectives", "nodes")
    assert reference.required_fields("GoalLoopNode") == ("key", "objective", "action_space")
    assert reference.required_fields("HumanGateNode") == ("key", "task")
    assert reference.required_fields("HumanTaskSpec") == ("kind", "prompt", "reviewers")

    assert reference.allowed_values("Goal", "importance") == (
        get_args(Goal.model_fields["importance"].annotation),
        "primary",
    )
    assert reference.allowed_values("HumanTaskSpec", "kind")[0] == get_args(
        HumanTaskSpec.model_fields["kind"].annotation
    )
    assert reference.allowed_values("OutputDeclaration", "form") == (
        tuple(form.value for form in OutputForm),
        "structured",
    )
    assert reference.allowed_values("OutputDeclaration", "enforcement")[0] == tuple(
        item.value for item in Enforcement
    )
    assert reference.allowed_values("Environment", "side_effects")[0] == tuple(
        effect.value for effect in SideEffect
    )
    assert reference.allowed_values("CapabilityEntry", "kind")[0] == tuple(
        kind.value for kind in CapabilityKind
    )
    assert reference.one_of("Acceptance") == ("assessment", "human", "schema", "all", "any")
    assert reference.allowed_values("Acceptance", "human")[0] == ("review_accept", "approved")
    assert reference.one_of("CapabilityEntry") == ("pin", "search")
    assert reference.one_of("InputBinding") == ("from", "artifact", "value")
    assert reference.output_schema_rules() == (("structured", "control_record"), ("text",))


def test_each_lane_s_environment_requirements_are_what_validation_refuses() -> None:
    default = reference.lane_environment_requirements(DEFAULT_LANE_PROFILE)

    assert default == ("model.profile", "budget", "governors", "sandbox")
    for lane in LANE_PROFILES:
        needed = reference.lane_environment_requirements(lane)
        assert {"model.profile", "budget", "governors"} <= set(needed), lane
        # Only the default lane runs in a Mission Control sandbox; the others name where
        # they execute.
        assert ("sandbox" in needed) is (lane == DEFAULT_LANE_PROFILE), lane
        assert ("execution_environment" in needed) is (lane != DEFAULT_LANE_PROFILE), lane


def _mission(program: dict[str, Any], acceptance: dict[str, Any]) -> str:
    """A whole manifest for the seeded catalog: one goal, one text output, one acceptance."""

    document = {
        "manifest": "mission/v2",
        "mission": {
            "key": "acceptance-probe",
            "title": "Acceptance probe",
            "application": APPLICATION,
            "goals": [
                {
                    "key": "goal",
                    "description": "Probe one acceptance operator",
                    "criteria": [
                        {
                            "key": "criterion",
                            "description": "The operator is evaluated where the goal is owned",
                            "evidence": ["result"],
                            "acceptance": acceptance,
                        }
                    ],
                }
            ],
            "environment": {
                "lane": DEFAULT_LANE_PROFILE,
                "model": {"profile": "producer.default"},
                "sandbox": {"profile": next(iter(SANDBOXES))},
                "budget": {"usd": 1, "tokens": 100000, "wall_clock": "10m", "tool_calls": 10},
                "governors": {"depth": 1, "fan_out": 1, "iterations": 1, "patience": 1},
            },
            "program": program,
        },
    }
    return canonical_manifest_bytes(document).decode("utf-8")


_WORK = {
    "key": "work",
    "behavior": "agent_executor",
    "objectives": ["goal"],
    "instruction": "Write the result.",
    "outputs": [{"name": "result", "form": "text"}],
}


def _gate(kind: str) -> dict[str, Any]:
    return {
        "key": "gate",
        "behavior": "human_gate",
        "objectives": ["goal"],
        "depends_on": ["work"],
        "task": {"kind": kind, "prompt": "Decide.", "reviewers": ["owner"]},
    }


def _graph(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"key": "root", "behavior": "stage_graph", "objectives": ["goal"], "nodes": list(nodes)}


_LOOP = {
    "key": "root",
    "behavior": "goal_loop",
    "objective": "goal",
    "action_space": ["root"],
    "outputs": [{"name": "result", "form": "text"}],
}
# Each location of the table as a real program.
PROGRAMS = {
    "a `goal_loop` program root": _LOOP,
    "an `agent_executor` stage": _graph(_WORK),
    **{
        f"a `human_gate` stage, `task.kind: {kind}`": _graph(_WORK, _gate(kind))
        for kind in get_args(HumanTaskSpec.model_fields["kind"].annotation)
    },
}


def test_the_acceptance_table_covers_every_operator_and_location() -> None:
    support = reference.acceptance_support()

    assert [label for label, _row in support] == [
        label for label, _probe in reference.ACCEPTANCE_PROBES
    ]
    assert {location for _label, row in support for location, _starts in row} == set(PROGRAMS)
    by_operator = {label: dict(row) for label, row in support}
    # The four facts a first manifest trips over.
    assert by_operator["`human: review_accept`"]["an `agent_executor` stage"] is False
    assert by_operator["`human: review_accept`"]["a `goal_loop` program root"] is True
    assert by_operator["`human: review_accept`"]["a `human_gate` stage, `task.kind: REVIEW`"]
    assert by_operator["`human: approved`"]["a `human_gate` stage, `task.kind: APPROVAL`"]
    assert not by_operator["`human: approved`"]["a `human_gate` stage, `task.kind: REVIEW`"]
    # No evaluator is qualified for these anywhere.
    for operator in ("`assessment`", "`all`", "`any`"):
        assert not any(by_operator[operator].values()), operator


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["review_accept", "approved"])
@pytest.mark.parametrize("location", list(PROGRAMS))
async def test_the_table_says_what_the_real_compile_says_for_human_acceptance(
    location: str, decision: str
) -> None:
    """The table is computed by the check a start applies; the full compile service over the
    seeded catalog reports the same `startable` for the same operator at the same place."""

    compile_service, _, _ = await service()
    compilation = await compile_service.compile(
        _mission(PROGRAMS[location], {"human": decision}), scope(APPLICATION)
    )

    assert compilation.report.blockers == (), compilation.report.blockers
    table = dict(dict(reference.acceptance_support())[f"`human: {decision}`"])
    assert compilation.report.startable is table[location], compilation.report.start_blockers
    if not table[location]:
        assert {item.reason for item in compilation.report.start_blockers} == {
            "completion_evaluator_unavailable"
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "acceptance",
    [
        {
            "assessment": {
                "capability": {"pin": "assessment.evidence-coverage@latest"},
                "threshold": 1,
            }
        },
        {"all": [{"human": "review_accept"}]},
        {"any": [{"human": "review_accept"}]},
    ],
)
async def test_an_operator_without_an_evaluator_compiles_and_cannot_start(
    acceptance: dict[str, Any],
) -> None:
    compile_service, _, _ = await service()
    program = _graph(_WORK, _gate("REVIEW"))
    compilation = await compile_service.compile(_mission(program, acceptance), scope(APPLICATION))

    assert compilation.ok and compilation.report.startable is False
    assert {item.reason for item in compilation.report.start_blockers} == {
        "completion_evaluator_unavailable"
    }


async def test_the_manifest_topic_is_generated_and_stays_inside_its_budget() -> None:
    page = (await full_guide().topic("manifest", "mcp")).markdown

    assert len(page) // 4 <= MANIFEST_TOPIC_TOKENS, len(page) // 4
    assert "| `behavior: agent_executor` | `key`, `objectives`, `instruction` |" in page
    assert "| `behavior: goal_loop` | `key`, `objective`, `action_space` |" in page
    assert "| `goals[].criteria[]` | `key`, `description`, `evidence`, `acceptance` |" in page
    assert "`goals[].importance`: `primary`, `secondary`, `optional` (default `primary`)" in page
    assert (
        "`outputs[].schema`: required for the forms `structured`, `control_record`, refused "
        "for `text`" in page
    )
    # Every bound lane with what its environment must hold; lanes that need the same share
    # a row.
    assert "| `deep_agents` | `model.profile`, `budget`, `governors`, `sandbox` |" in page
    lane_rows = "\n".join(line for line in page.splitlines() if "`model.profile`" in line)
    assert all(f"`{lane}`" in lane_rows for lane in LANE_PROFILES)
    # The acceptance table, and the bound sandbox profiles.
    assert "| `human: review_accept` | starts | refused | refused | starts |" in page
    assert "| `assessment`, `all`, `any` | refused | refused | refused | refused |" in page
    assert "`task.kind: APPROVAL`, `QUESTION`, `SELECTION`, `POLICY_OVERRIDE`" in page
    # Each bound sandbox profile on its own line, with what it suits, and where to read more.
    assert (
        "Sandbox profiles bound here (`environment.sandbox.profile`); read one in full with "
        "its `sandbox:<name>` ref:\n- `research.standard`: docker sandbox bound by this "
        "deployment" in page
    )
    assert '`mission_describe("sandbox:<profile>")`' in page
    assert '`mission_describe("manifest")`' in page and "completion_evaluator_unavailable" in page

    unbound = (await stub_guide(sandboxes={}).topic("manifest")).markdown
    unknown = (await stub_guide(sandboxes=None).topic("manifest")).markdown
    assert "No sandbox profile is bound here" in unbound
    assert "This server does not launch, so it binds no sandbox profile." in unknown
    # Only the lanes this installation binds are listed.
    assert "cursor_local" not in unbound and "`claude_agent_sdk`" in unbound


async def test_describe_the_manifest_is_the_whole_reference_as_markdown() -> None:
    guide = stub_guide()
    whole = await guide.describe("manifest")
    section = await guide.describe("manifest:TimerNode")

    assert whole.kind == "manifest" and whole.markdown is not None
    assert whole.markdown.startswith("# Mission Manifest reference")
    for name, place in reference.SECTION_PLACES.items():
        assert f"### `{name}`: {place}" in whole.markdown
    assert "| `instruction` | yes | text |" in whole.markdown
    assert "| `importance` |  | `primary`, `secondary`, `optional` (default `primary`) |" in (
        whole.markdown
    )
    assert "| `evidence` | yes | list of text |" in whole.markdown
    assert "Exactly one of `assessment`, `human`, `schema`, `all`, `any`." in whole.markdown
    assert "## Which acceptance can start" in whole.markdown
    assert "`manifest:<section>`" in whole.markdown and "`TimerNode`" in whole.markdown
    assert whole.data["sections"]["AgentExecutorNode"]["required"] == [
        "key",
        "objectives",
        "instruction",
    ]
    assert "TimerNode" in whole.data["more_sections"]
    # Every behaviour a node can take is reachable as a section.
    reachable = " ".join(reference.section_markdown(name) for name in reference.section_names())
    assert all(f"`{behavior.value}`" in reachable for behavior in Behavior)

    assert section.markdown is not None and section.markdown.startswith("### `TimerNode`")
    assert "| `duration` |  | duration (seconds, or `4h`, `1h30m`) |" in section.markdown
    assert section.data == {"section": "TimerNode", "required": ["key"]}
    with pytest.raises(GuideRefused) as refused:
        await guide.describe("manifest:Nowhere")
    assert refused.value.code == "not_found" and "manifest:Goal" in refused.value.valid

"""OVE-176 / WI-13: nested family bodies compile recursively, positioned, sealed and bounded.

A Goal Loop in a Stage Graph stage and a Stage Graph as a Goal Loop's executor phase each lower
to one ``NestedBody`` (never a flattened stage); only the composite's declared outputs cross the
boundary; the body's own promises keep their absolute position; depth, inherited inputs,
unknown exports and unsupported bodies refuse typed and pointed.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from mission_control.domain.authoring.contracts import GoalDirectedBlueprint, StageGraphBlueprint
from mission_control.domain.authoring.manifest import (
    ManifestRejected,
    load_manifest_yaml,
    parse_manifest,
    resolve_environments,
)
from mission_control.domain.authoring.manifest_lowering import lower_mission, output_promises
from mission_control.domain.authoring.mission_definition import (
    MissionDefinition,
    manifest_to_definitions,
)
from mission_control.domain.authoring.nested_bodies import NestedBodyError
from mission_control.domain.authoring.nested_lowering import nested_definition
from mission_control.domain.programs.stagegraph_bounds import stagegraph_payload_problems

ROOT = Path(__file__).resolve().parents[3]
W5 = ROOT / "tests/fixtures/manifests/sprint-oc-w5"
PLACEHOLDERS = {"__PACK__": '{"task":"frozen"}', "__MODEL__": "frontier.default"}


def document(name: str) -> dict[str, Any]:
    text = (W5 / name).read_text(encoding="utf-8")
    for key, value in PLACEHOLDERS.items():
        text = text.replace(key, value)
    return load_manifest_yaml(text)


def definition(doc: dict[str, Any]) -> MissionDefinition:
    manifest = parse_manifest(doc)
    structure = resolve_environments(manifest, doc)
    assert not getattr(structure, "blockers", ())
    (only,) = manifest_to_definitions(manifest, doc)
    return only


def issues(doc: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(ManifestRejected) as caught:
        manifest = parse_manifest(doc)
        structure = resolve_environments(manifest, doc)
        blockers = getattr(structure, "blockers", ())
        if blockers:
            raise ManifestRejected(blockers)
    return [(item.pointer, item.reason or "") for item in caught.value.issues]


GOAL_IN_GRAPH = ("ai-engineer.goal-in-graph.mission.yml", "biotech.goal-in-graph.mission.yml")
GRAPH_IN_GOAL = ("ai-engineer.graph-in-goal.mission.yml", "biotech.graph-in-goal.mission.yml")


def test_the_w5_fixture_set_covers_both_nestings_for_both_applications() -> None:
    assert sorted(path.name for path in W5.glob("*.yml")) == sorted(GOAL_IN_GRAPH + GRAPH_IN_GOAL)


@pytest.mark.parametrize("name", GOAL_IN_GRAPH)
def test_a_goal_loop_stage_is_a_recursive_body_not_a_flattened_stage(name: str) -> None:
    resolved = definition(document(name))
    lowered = lower_mission(resolved)
    graph = lowered.blueprint
    assert isinstance(graph, StageGraphBlueprint)
    assert stagegraph_payload_problems(graph) == ()
    assert [item.reason for item in lowered.warnings] == []
    (body,) = graph.nested_bodies
    assert (body.host_id, body.node_key, body.position) == ("research", "research", "research")
    assert (body.behavior, body.family, body.depth, body.max_depth) == (
        "goal_loop",
        "GoalDirected",
        1,
        2,
    )
    exports = {item.output: (item.source, item.timing, item.required) for item in body.exports}
    assert exports == {
        "report": ("research.report", "final", True),
        "progress_note": ("research.progress_note", "early", True),
    }
    # The consumer binds the composite's export exactly (one dependency, no side path).
    (edge,) = [item for item in graph.dependencies if item.consumer_stage_id != "review"]
    assert (edge.producer_stage_id, edge.producer_output_slot_id, edge.consumer_stage_id) == (
        "research",
        "report",
        "compare",
    )
    # The body's sealed digests are its own derived definition and lowering.
    derived = nested_definition(resolved, resolved.program.nodes[0])
    assert body.definition_digest == derived.digest
    nested = lower_mission(derived, position=body.position, depth=body.depth)
    assert body.blueprint_digest == nested.blueprint_digest
    assert isinstance(nested.blueprint, GoalDirectedBlueprint)
    assert nested.blueprint.max_iterations == 2


@pytest.mark.parametrize("name", GRAPH_IN_GOAL)
def test_a_stage_graph_executor_body_runs_inside_its_goal_loop(name: str) -> None:
    resolved = definition(document(name))
    lowered = lower_mission(resolved)
    loop = lowered.blueprint
    assert lowered.family == "GoalDirected"
    assert isinstance(loop, GoalDirectedBlueprint)
    (body,) = loop.nested_bodies
    assert (body.host_id, body.position, body.family, body.depth) == (
        "executor",
        "refine/pass",
        "StageGraph",
        1,
    )
    (export,) = body.exports
    assert (export.output, export.source, export.timing) == ("report", "draft.report", "final")
    nested = lower_mission(
        nested_definition(resolved, resolved.program.nodes[0]),
        position=body.position,
        depth=body.depth,
    )
    graph = nested.blueprint
    assert isinstance(graph, StageGraphBlueprint)
    assert {stage.stage_id for stage in graph.stages} == {"draft", "check"}
    assert body.blueprint_digest == nested.blueprint_digest


@pytest.mark.parametrize("name", GOAL_IN_GRAPH + GRAPH_IN_GOAL)
def test_internal_outputs_stay_in_the_body_and_keep_their_nested_position(name: str) -> None:
    resolved = definition(document(name))
    parent = output_promises(resolved)
    assert parent is not None
    parent_keys = {item.key for item in parent.obligations}
    body_node = resolved.program.nodes[0]
    position = next(iter(lower_mission(resolved).blueprint.nested_bodies)).position
    promised = output_promises(nested_definition(resolved, body_node), position=position)
    assert promised is not None
    if name in GOAL_IN_GRAPH:
        # The composite's own outputs are owed by the parent at the stage position; the body
        # run owes the same promises at the same absolute position.
        assert {"research.report", "research.progress_note"} <= parent_keys
        assert {(item.key, item.owner_position) for item in promised.obligations} == {
            ("research.report", "research"),
            ("research.progress_note", "research"),
        }
    else:
        # The loop owes only its own output; the subgraph's stage outputs are the body's.
        assert parent_keys == {"refine.report"}
        assert {(item.key, item.owner_position) for item in promised.obligations} == {
            ("draft.report", "refine/pass/draft"),
            ("check.verdict", "refine/pass/check"),
        }


def test_lowering_nested_bodies_is_deterministic() -> None:
    for name in GOAL_IN_GRAPH + GRAPH_IN_GOAL:
        first = lower_mission(definition(document(name)))
        second = lower_mission(definition(document(name)))
        assert first.blueprint_digest == second.blueprint_digest


def test_a_program_without_nested_bodies_keeps_its_digest_neutral_shape() -> None:
    doc = document("ai-engineer.goal-in-graph.mission.yml")
    program = doc["mission"]["program"]
    research = program["nodes"][0]
    program["nodes"][0] = {
        "key": "research",
        "behavior": "agent_executor",
        "objectives": research["objectives"],
        "instruction": "Register the report.",
        "outputs": research["outputs"],
    }
    graph = lower_mission(definition(doc)).blueprint
    assert graph.nested_bodies == ()
    assert "nested_bodies" not in graph.model_dump(mode="json")


def test_the_depth_governor_refuses_a_body_deeper_than_it_allows() -> None:
    doc = document("ai-engineer.goal-in-graph.mission.yml")
    doc["mission"]["environment"]["governors"]["depth"] = 0
    with pytest.raises(NestedBodyError) as caught:
        lower_mission(definition(doc))
    assert caught.value.reason == "nested_depth_exceeded"
    assert caught.value.pointer.endswith("/program/nodes/0")


def test_a_body_reading_a_producer_outside_itself_refuses_typed() -> None:
    doc = document("ai-engineer.goal-in-graph.mission.yml")
    nodes = doc["mission"]["program"]["nodes"]
    nodes[0], nodes[1] = copy.deepcopy(nodes[1]), copy.deepcopy(nodes[0])
    nodes[0]["inputs"] = []
    nodes[1]["inputs"] = [{"name": "prior", "from": "compare.comparison", "expand": "inline"}]
    assert ("/mission/program/nodes/1/inputs/0", "nested_inherited_input_unsupported") in issues(
        doc
    )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda node: node.update(exports=[{"output": "missing", "timing": "early"}]),
            "nested_export_unknown_output",
        ),
        (
            lambda node: node.update(exports=[{"output": "report", "from": "x.report"}]),
            "nested_export_unknown_source",
        ),
    ],
)
def test_export_refusals_are_typed_and_pointed(mutate: Any, reason: str) -> None:
    doc = document("ai-engineer.goal-in-graph.mission.yml")
    mutate(doc["mission"]["program"]["nodes"][0])
    assert reason in {found for _, found in issues(doc)}


def test_a_stage_graph_body_export_names_an_inner_producer() -> None:
    doc = document("ai-engineer.graph-in-goal.mission.yml")
    body = doc["mission"]["program"]["nodes"][0]
    body["exports"] = [{"output": "report", "from": "check.unknown"}]
    assert ("/mission/program/nodes/0/exports/0/from", "nested_export_unknown_source") in issues(
        doc
    )


def test_a_goal_loop_executor_body_is_a_family_program() -> None:
    doc = document("ai-engineer.graph-in-goal.mission.yml")
    doc["mission"]["program"]["nodes"] = [
        {
            "key": "solo",
            "behavior": "agent_executor",
            "objectives": ["draft_report"],
            "instruction": "Draft.",
        }
    ]
    assert ("/mission/program/nodes/0/behavior", "unsupported_nested_body") in issues(doc)


def test_exports_on_the_program_root_refuse_instead_of_being_ignored() -> None:
    doc = document("ai-engineer.graph-in-goal.mission.yml")
    doc["mission"]["program"]["exports"] = [{"output": "report"}]
    assert ("/mission/program/exports", "unsupported_graph_position") in issues(doc)


def two_level_document() -> dict[str, Any]:
    """`outer` is a nested Stage Graph whose stage `research` is itself a Goal Loop body."""

    doc = document("ai-engineer.goal-in-graph.mission.yml")
    program = doc["mission"]["program"]
    research = program["nodes"][0]
    program["nodes"][0] = {
        "key": "outer",
        "behavior": "stage_graph",
        "objectives": research["objectives"],
        "outputs": copy.deepcopy(research["outputs"]),
        "exports": [{"output": "report", "from": "research.report"}],
        "nodes": [research],
    }
    program["nodes"][0]["outputs"] = [
        item for item in program["nodes"][0]["outputs"] if item["name"] == "report"
    ]
    research.pop("exports", None)
    doc["mission"]["program"]["nodes"][1]["inputs"] = [
        {"name": "report", "from": "outer.report", "expand": "reference"}
    ]
    return doc


def test_the_depth_governor_is_inherited_by_every_level() -> None:
    """N2: a body's own nested body is one level deeper under the same mission governor."""

    resolved = definition(two_level_document())
    (outer,) = lower_mission(resolved).blueprint.nested_bodies
    assert (outer.position, outer.depth, outer.max_depth) == ("outer", 1, 2)
    inner_lowered = lower_mission(
        nested_definition(resolved, resolved.program.nodes[0]), position="outer", depth=1
    )
    (inner,) = inner_lowered.blueprint.nested_bodies
    assert (inner.position, inner.depth, inner.max_depth) == ("outer/research", 2, 2)
    capped = two_level_document()
    capped["mission"]["environment"]["governors"]["depth"] = 1
    with pytest.raises(NestedBodyError) as caught:
        lower_mission(definition(capped))
    assert caught.value.reason == "nested_depth_exceeded"

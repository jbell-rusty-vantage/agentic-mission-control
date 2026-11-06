"""OVE-171 / WI-08: authoring and lowering of explicit routes, named release groups, typed facts
and optional bindings; the binding is its own dependency (no depends_on-only side path); the W2
fixtures compile offline; a graph whose family records would outgrow their bounds refuses at
compile, typed (W1 D10)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from mission_control.application.programs.stage_inputs import stagegraph_authored_inputs
from mission_control.domain.authoring.contracts import JoinKind, StageGraphBlueprint
from mission_control.domain.authoring.graph_routes import GRAPH_SEMANTICS_V1
from mission_control.domain.authoring.manifest import (
    ManifestRejected,
    load_manifest_yaml,
    parse_manifest,
    resolve_environments,
)
from mission_control.domain.authoring.manifest_lowering import lower_mission
from mission_control.domain.authoring.mission_definition import (
    MissionDefinition,
    manifest_to_definitions,
)
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.programs.stagegraph_bounds import stagegraph_payload_problems

ROOT = Path(__file__).resolve().parents[3]
W2 = ROOT / "tests/fixtures/manifests/sprint-oc-w2"
PLACEHOLDERS = {
    "__PACK__": '{"task":"frozen"}',
    "__PRODUCER__": "frontier.default",
    "__CONSUMER__": "frontier.default",
}


def document(name: str) -> dict[str, Any]:
    text = (W2 / name).read_text(encoding="utf-8")
    for key, value in PLACEHOLDERS.items():
        text = text.replace(key, value)
    return load_manifest_yaml(text)


def definition(doc: dict[str, Any]) -> MissionDefinition:
    manifest = parse_manifest(doc)
    structure = resolve_environments(manifest, doc)
    assert not getattr(structure, "blockers", ())
    (only,) = manifest_to_definitions(manifest, doc)
    return only


def blueprint(doc: dict[str, Any]) -> StageGraphBlueprint:
    lowered = lower_mission(definition(doc))
    assert isinstance(lowered.blueprint, StageGraphBlueprint)
    return lowered.blueprint


def issues(doc: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(ManifestRejected) as caught:
        manifest = parse_manifest(doc)
        structure = resolve_environments(manifest, doc)
        blockers = getattr(structure, "blockers", ())
        if blockers:
            raise ManifestRejected(blockers)
    return [(item.pointer, item.reason or "") for item in caught.value.issues]


def without_review(doc: dict[str, Any]) -> dict[str, Any]:
    """The graph without its final REVIEW gate (which owns every human-accepted goal, OVE-169)."""

    program = doc["mission"]["program"]
    program["nodes"] = [item for item in program["nodes"] if item["key"] != "review"]
    return doc


def node(doc: dict[str, Any], key: str) -> dict[str, Any]:
    return next(item for item in doc["mission"]["program"]["nodes"] if item["key"] == key)


# ---------------------------------------------------------------- the W2 fixtures


@pytest.mark.parametrize("name", sorted(path.name for path in W2.glob("*.yml")))
def test_every_w2_fixture_compiles_offline_within_its_family_bounds(name: str) -> None:
    graph = blueprint(document(name))
    assert stagegraph_payload_problems(graph) == ()


@pytest.mark.parametrize(
    "name", ["ai-engineer.producer-consumer.mission.yml", "biotech.producer-consumer.mission.yml"]
)
def test_the_consumer_binding_alone_is_its_dependency(name: str) -> None:
    doc = document(name)
    assert "depends_on" not in node(doc, "consume")
    graph = blueprint(doc)
    (edge,) = [item for item in graph.dependencies if item.consumer_stage_id != "review"]
    assert (edge.producer_stage_id, edge.producer_output_slot_id, edge.consumer_stage_id) == (
        "produce",
        "report",
        "consume",
    )
    assert edge.dependency_class.value == "required"
    (authored,) = stagegraph_authored_inputs(definition(doc))
    assert (authored.consumer_stage_id, authored.producer_stage_id, authored.name) == (
        "consume",
        "produce",
        "report",
    )
    assert authored.required
    # No route, group or optional binding: the earlier semantics (and digest) are kept.
    assert graph.graph_semantics is None


def test_routes_groups_facts_and_optional_bindings_lower_under_the_semantics() -> None:
    first = blueprint(document("graph.routes-first-match.mission.yml"))
    assert first.graph_semantics == GRAPH_SEMANTICS_V1
    (route,) = first.routes
    assert route.mode == "first_match"
    assert [branch.branch_id for branch in route.branches] == ["urgent", "broad"]
    assert route.else_stage_ids == ("archive",)
    triage = next(stage for stage in first.stages if stage.stage_id == "triage")
    assert {(fact.fact_id, fact.value_type) for fact in triage.facts} == {
        ("severity", "string"),
        ("source_count", "integer"),
    }
    # The three alternatives each owe `reviewed`: whichever the route selects proves it (the
    # fixture's final REVIEW gate owns the human-accepted goals, so this is the graph without it).
    ungated = blueprint(without_review(document("graph.routes-first-match.mission.yml")))
    owed = {
        stage.stage_id
        for stage in ungated.stages
        if any(slot.obligation_slot_id == "reviewed" for slot in stage.obligation_slots)
    }
    assert owed == {"deep_review", "light_review", "archive"}
    (review,) = [join for join in first.joins if join.consumer_stage_id == "report"]
    assert review.join_id == "report:group:review" and review.kind is JoinKind.ANY
    assert review.group is not None
    assert review.group.member_stage_ids == ("deep_review", "light_review", "archive")

    groups = blueprint(document("graph.groups-quorum-optional.mission.yml"))
    joins = {join.join_id: join for join in groups.joins}
    reviews = joins["synthesize:group:reviews"]
    assert reviews.kind is JoinKind.MINIMUM and reviews.minimum == 2
    assert reviews.group is not None and reviews.group.coverage_subjects == ("efficacy", "safety")
    assert reviews.group.covers("efficacy_c") == {"efficacy"}
    optional = joins["synthesize:optional"]
    (context,) = [
        edge for edge in groups.dependencies if edge.dependency_id in optional.dependency_ids
    ]
    assert context.dependency_class.value == "optional"


def test_lowering_is_deterministic() -> None:
    doc = document("graph.routes-all-matching.mission.yml")
    assert blueprint(doc).model_dump(mode="json") == blueprint(copy.deepcopy(doc)).model_dump(
        mode="json"
    )


# ---------------------------------------------------------------- typed authoring refusals


def test_route_mode_is_required_never_a_silent_default() -> None:
    doc = document("graph.routes-all-matching.mission.yml")
    del doc["mission"]["program"]["routes"][0]["mode"]
    assert any(pointer.endswith("/routes/0/mode") for pointer, _ in issues(doc))


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda r: r["branches"][0]["when"][0].update(fact="scan_a.missing"), "unknown_fact"),
        (lambda r: r["branches"][0]["when"][0].update(value="yes"), "invalid_predicate"),
        (lambda r: r["branches"][0]["when"][0].update(op="lt"), "invalid_predicate"),
        (lambda r: r["branches"][0].update(release=["scan_a"]), "dependency_cycle"),
        (lambda r: r["branches"][0].update(release=["ghost"]), "unknown_dependency"),
    ],
)
def test_route_refusals_are_typed_and_pointed(mutate: Any, reason: str) -> None:
    doc = document("graph.routes-all-matching.mission.yml")
    mutate(doc["mission"]["program"]["routes"][0])
    assert reason in {found for _, found in issues(doc)}


def test_a_stage_is_released_by_at_most_one_route() -> None:
    doc = document("graph.routes-all-matching.mission.yml")
    routes = doc["mission"]["program"]["routes"]
    routes.append({**copy.deepcopy(routes[0]), "key": "again"})
    assert "duplicate_route" in {reason for _, reason in issues(doc)}


def test_facts_come_from_a_structured_output() -> None:
    doc = document("graph.routes-all-matching.mission.yml")
    node(doc, "follow_a")["facts"] = [
        {"name": "x", "output": "note_a", "pointer": "/x", "type": "string"}
    ]
    assert "unknown_output" in {reason for _, reason in issues(doc)}


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda g: g.update(join={"quorum": 4}), "invalid_join"),
        (lambda g: g.update(coverage=["safety", "dosage"]), "uncoverable_group"),
        (lambda g: g["members"].append({"stage": "ghost"}), "unknown_dependency"),
    ],
)
def test_group_refusals_are_typed_and_pointed(mutate: Any, reason: str) -> None:
    doc = document("graph.groups-quorum-optional.mission.yml")
    mutate(node(doc, "synthesize")["release_groups"][0])
    assert reason in {found for _, found in issues(doc)}


def test_a_group_member_cannot_also_be_an_ordering_dependency() -> None:
    doc = document("graph.groups-quorum-optional.mission.yml")
    node(doc, "synthesize")["depends_on"] = ["safety_a"]
    assert "duplicate_dependency" in {reason for _, reason in issues(doc)}


def test_a_binding_cycle_is_refused_without_depends_on() -> None:
    doc = document("ai-engineer.producer-consumer.mission.yml")
    node(doc, "produce")["inputs"] = [{"name": "back", "from": "consume.comparison"}]
    assert "dependency_cycle" in {reason for _, reason in issues(doc)}


def test_groups_and_facts_outside_the_root_stage_graph_refuse_instead_of_being_ignored() -> None:
    doc = document("ai-engineer.producer-consumer.mission.yml")
    doc["mission"]["program"]["release_groups"] = [{"key": "g", "members": ["produce"]}]
    found = issues(doc)
    assert ("/mission/program/release_groups", "unsupported_graph_position") in found


def test_a_revisit_region_lowers_with_its_stop_rule_cap_progress_and_carry() -> None:
    graph = blueprint(document("graph.revisit-refine.mission.yml"))
    assert graph.graph_semantics == GRAPH_SEMANTICS_V1 and graph.workflow_cycle_policy is None
    (region,) = graph.revisit_regions
    assert (region.entry_stage_id, region.exit_stage_id, region.max_visits) == (
        "draft",
        "critique",
        3,
    )
    assert region.stage_ids == ("critique", "draft")
    assert [(p.stage_id, p.fact_id, p.value) for p in region.until] == [
        ("critique", "approved", True)
    ]
    assert region.progress is not None and region.progress.fact_id == "score"
    assert region.patience == 2
    assert [(c.stage_id, c.output_slot_id) for c in region.carry] == [("critique", "verdict")]


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda r: r.update(entry="publish"), "invalid_region"),
        (lambda r: r.update(entry="critique"), "invalid_region"),
        (lambda r: r["until"][0].update(fact="publish.approved"), "unknown_fact"),
        (lambda r: r["until"][0].update(value=1), "invalid_predicate"),
        (lambda r: r.update(carry=["text"]), "unknown_output"),
        (lambda r: r.pop("patience"), "invalid_region"),
        (lambda r: r.update(progress="critique.approved"), "unknown_fact"),
        (lambda r: r.update(stages=["draft", "critique", "ghost"]), "unknown_dependency"),
    ],
)
def test_revisit_refusals_are_typed_and_pointed(mutate: Any, reason: str) -> None:
    doc = document("graph.revisit-refine.mission.yml")
    mutate(doc["mission"]["program"]["revisits"][0])
    assert reason in {found for _, found in issues(doc)}


def test_a_revisit_cap_is_bounded() -> None:
    doc = document("graph.revisit-refine.mission.yml")
    doc["mission"]["program"]["revisits"][0]["max_visits"] = 1
    assert any(pointer.endswith("/max_visits") for pointer, _ in issues(doc))


# ---------------------------------------------------------------- compile-time family bounds


def test_a_graph_whose_family_records_outgrow_their_bound_refuses_typed() -> None:
    def chain(count: int) -> StageGraphBlueprint:
        return build_stagegraph_v2(
            logical_id="wi08.bounds",
            title="bounds",
            description="a long chain",
            stages=tuple(
                StageGraphStageSpec(
                    f"stage-{index:02d}",
                    depends_on=(f"stage-{index - 1:02d}",) if index else (),
                    output_slots=("out",),
                )
                for index in range(count)
            ),
        )

    assert stagegraph_payload_problems(chain(8)) == ()
    problems = stagegraph_payload_problems(chain(40))
    assert problems and problems[0].startswith("family_record_too_large:")

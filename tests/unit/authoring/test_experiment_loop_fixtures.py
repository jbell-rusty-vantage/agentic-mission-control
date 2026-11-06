"""OVE-169 experiment loop (EXPERIMENT-LOOP-2026-11 section 3): the five E1-E5 fixtures compile
offline with zero blockers through the full manifest compile service over the seeded catalog
(the owner-manifest path of ``test_manifest_compile.py``), and pass the fresh-launch acceptance
check (``completion_support_issues``) that start applies (compile reports it as ``start_blockers``).

Also pinned: the shapes each experiment relies on (parallel join with both expansion tiers,
route plus revisit, the chain link, the nested body), the exact knowledge-tools pins, and the
Stage Graph root export E4's chain reads (the root-promise gap fixed in iteration 0).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_control.application.authoring.completion_support import completion_support_issues
from mission_control.application.authoring.manifest_service import (
    ManifestCompilation,
    catalog_output_schemas,
)
from mission_control.domain.authoring.contracts import GoalDirectedBlueprint, StageGraphBlueprint
from mission_control.domain.authoring.manifest import load_manifest_yaml
from mission_control.domain.authoring.manifest_lowering import lower_mission, output_promises
from mission_control.domain.authoring.nested_lowering import nested_definition
from tests.unit.authoring.test_manifest_compile import scope, service

ROOT = Path(__file__).resolve().parents[3]
LOOP = ROOT / "tests/fixtures/manifests/experiment-loop"
SEEDS = ROOT / "packages/mission-control-db-contract/seeds"
SEED = SEEDS / "common/mc.catalog.knowledge-tools-1.2.0.json"
FIXTURES = (
    "e1-goal-loop-report.mission.yml",
    "e2-stagegraph-fanout-join.mission.yml",
    "e3-stagegraph-route-revisit.mission.yml",
    "e4-linked-chain.mission.yml",
    "e5-nested-goal-in-graph.mission.yml",
)
# What the driver substitutes; the pack shape matters only to the model, never to compile.
PLACEHOLDERS = {"__PACK__": '{"reportId":"fixture","task":{},"fragments":[]}'}
PRODUCERS = {"producer.default", "producer.fallback"}  # the rows sprint_oc_w1_bindings binds


def rendered(name: str, producer: str = "producer.fallback") -> str:
    text = (LOOP / name).read_text(encoding="utf-8")
    for key, value in PLACEHOLDERS.items():
        text = text.replace(key, value)
    return text.replace("__PRODUCER__", producer)


def missions(name: str) -> list[dict]:
    document = load_manifest_yaml(rendered(name))
    return document.get("missions") or [document["mission"]]


async def compiled(name: str, producer: str = "producer.fallback") -> ManifestCompilation:
    compile_service, _, _ = await service()
    return await compile_service.compile(rendered(name, producer), scope("ai-engineer"))


def test_the_fixture_set_is_exactly_e1_to_e5() -> None:
    assert sorted(path.name for path in LOOP.glob("*.yml")) == sorted(FIXTURES)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", FIXTURES)
async def test_each_fixture_compiles_with_zero_blockers_and_passes_launch_acceptance(
    name: str,
) -> None:
    compilation = await compiled(name)
    assert compilation.report.blockers == (), compilation.report.blockers
    assert compilation.ok and compilation.resolution is not None
    assert compilation.report.start_blockers == () and compilation.report.startable is True
    assert compilation.resolution.catalog_resolution == "resolved"
    assert all(item.result is not None for item in compilation.resolution.resolved)
    assert {program.mission_key for program in compilation.programs} == {
        definition.mission_key for definition in compilation.definitions
    }
    for definition in compilation.definitions:
        blueprint = compilation.program(definition.mission_key).lowered.blueprint
        # start refuses what compile accepts (manifest_launch_inputs.py, `_templates`).
        assert completion_support_issues(definition, blueprint) == ()
        if isinstance(blueprint, StageGraphBlueprint):
            for body in blueprint.nested_bodies:
                node = next(item for item in definition.program.nodes if item.key == body.node_key)
                derived = nested_definition(definition, node)
                nested = lower_mission(derived, position=body.position, depth=body.depth)
                assert completion_support_issues(derived, nested.blueprint) == ()


@pytest.mark.asyncio
async def test_e1_compiles_on_the_sonnet_row_it_alone_may_use() -> None:
    compilation = await compiled(FIXTURES[0], producer="producer.default")
    assert compilation.report.blockers == ()


@pytest.mark.parametrize("name", FIXTURES)
def test_models_are_bound_rows_and_tools_are_exact_seeded_pins(name: str) -> None:
    seeded = {}
    for record in json.loads(SEED.read_text(encoding="utf-8"))["records"]:
        ref = (record["fields"].get("manifest") or {}).get("ref") or {}
        if ref.get("kind") == "tool":
            seeded[ref["logical_id"]] = ref["digest"]
    text = rendered(name)
    assert "__" not in "".join(line for line in text.splitlines() if not line.startswith("#"))
    for mission in missions(name):
        environment = mission["environment"]
        assert environment["lane"] == "deep_agents"
        assert environment["model"]["profile"] in PRODUCERS
        for capability in environment["capabilities"]:
            logical_id, _, rest = capability["pin"].partition("@")
            assert capability["kind"] == "tool"
            assert seeded[logical_id] == rest.partition("#")[2]
        assert "skills" not in environment.get("workspace", {})  # no skill is launch-bound
        # Parallel Swarm and Evaluator Optimizer are refused at compile (OVE-215).
        assert "parallel_swarm" not in text and "evaluator_optimizer" not in text


@pytest.mark.asyncio
async def test_e1_is_a_two_iteration_goal_loop_with_a_held_review() -> None:
    (program,) = (await compiled(FIXTURES[0])).programs
    blueprint = program.lowered.blueprint
    assert isinstance(blueprint, GoalDirectedBlueprint)
    assert blueprint.max_iterations == 2
    (mission,) = missions(FIXTURES[0])
    assert mission["goals"][0]["criteria"][0]["acceptance"] == {"human": "review_accept"}
    assert mission["program"]["verifier"]["environment"]["model"]["profile"] == (
        "producer.fallback"
    )


@pytest.mark.asyncio
async def test_e2_joins_parallel_collectors_with_a_materialized_and_a_referenced_input() -> None:
    (program,) = (await compiled(FIXTURES[1])).programs
    blueprint = program.lowered.blueprint
    assert isinstance(blueprint, StageGraphBlueprint)
    edges = {
        (edge.producer_stage_id, edge.producer_output_slot_id, edge.consumer_stage_id)
        for edge in blueprint.dependencies
    }
    assert {
        ("collect_a", "notes_a", "synthesize"),
        ("collect_b", "notes_b", "synthesize"),
    } <= edges
    (mission,) = missions(FIXTURES[1])
    assert mission["program"]["concurrency"] == 2
    synthesize = next(node for node in mission["program"]["nodes"] if node["key"] == "synthesize")
    assert {item["name"]: item["expand"] for item in synthesize["inputs"]} == {
        "notes_a": "materialize",
        "notes_b": "reference",
    }


@pytest.mark.asyncio
async def test_e3_routes_typed_facts_into_one_bounded_revisit_region() -> None:
    compilation = await compiled(FIXTURES[2])
    (program,) = compilation.programs
    blueprint = program.lowered.blueprint
    assert isinstance(blueprint, StageGraphBlueprint)
    (route,) = blueprint.routes
    assert route.target_stage_ids >= {"outline", "skip"}
    (region,) = blueprint.revisit_regions
    assert (region.entry_stage_id, region.exit_stage_id, region.max_visits) == (
        "draft",
        "critique",
        3,
    )
    # A region stage is never a route target (compile rule); the route releases `outline`.
    assert not set(region.stage_ids) & set(route.target_stage_ids)
    # Both route-fact and stop-fact schemas resolve to their exact seeded authority.
    schemas = await catalog_output_schemas((await service())[1], compilation.definitions[0])
    assert set(schemas) == {"schema.w2-triage-verdict@1", "schema.w2-critique-verdict@1"}


@pytest.mark.asyncio
async def test_e4_links_a_stage_graph_supplier_to_a_goal_loop_consumer() -> None:
    compilation = await compiled(FIXTURES[3])
    families = {item.mission_key: item.lowered.family for item in compilation.programs}
    assert families == {"e4-evidence": "StageGraph", "e4-brief": "GoalDirected"}
    document = load_manifest_yaml(rendered(FIXTURES[3]))
    (link,) = document["links"]
    assert link["on"] == {"goal_accepted": {"goal_key": "evidence"}}
    assert link["on_upstream_cancel"] == "continue"


@pytest.mark.asyncio
async def test_e4_supplier_root_output_is_the_map_stage_promise() -> None:
    """The gap E4 would have hit live (OVE-169 iteration 0, now fixed): a Stage Graph root output
    was a promise owned by ``workflow``, which no stage can submit. The root now exports the
    ``map`` stage's promise; the submission proof is
    ``tests/unit/chains/test_stagegraph_chain_supply.py``."""

    compilation = await compiled(FIXTURES[3])
    supplier = next(item for item in compilation.definitions if item.mission_key == "e4-evidence")
    promises = output_promises(supplier)
    assert promises is not None
    owners = {item.key: item.owner_position for item in promises.obligations}
    assert owners == {"collect.notes": "collect", "map.evidence_map": "map"}
    blueprint = compilation.program("e4-evidence").lowered.blueprint
    assert isinstance(blueprint, StageGraphBlueprint)
    assert set(owners.values()) <= {stage.stage_id for stage in blueprint.stages}


@pytest.mark.asyncio
async def test_e4_supplier_still_runs_when_the_link_releases() -> None:
    """Loop iter-1 L1-05: the link releases on goal_accepted{evidence} (the review gate); the
    supplier must still be running then, or the cancel overlay (on_upstream_cancel: continue)
    lands on a terminal run (HTTP 422). A no-cost APPROVAL gate of a later goal holds it open."""

    (supplier, _consumer) = missions(FIXTURES[3])
    released_on = load_manifest_yaml(rendered(FIXTURES[3]))["links"][0]["on"]["goal_accepted"]
    goal = released_on["goal_key"]
    nodes = {node["key"]: node for node in supplier["program"]["nodes"]}
    after = [
        node
        for node in nodes.values()
        if "review" in node.get("depends_on", ()) and goal not in node["objectives"]
    ]
    assert [node["key"] for node in after] == ["hold"]
    (hold,) = after
    assert hold["behavior"] == "human_gate" and hold["task"]["kind"] == "APPROVAL"
    assert hold["task"]["reviewers"] == ["owner"]
    compilation = await compiled(FIXTURES[3])
    blueprint = compilation.program("e4-evidence").lowered.blueprint
    assert isinstance(blueprint, StageGraphBlueprint)
    assert ("review", "hold") in {
        (edge.producer_stage_id, edge.consumer_stage_id) for edge in blueprint.dependencies
    }


def test_e4_map_is_asked_for_its_contracted_media_type() -> None:
    """Loop iter-1 L1-05: `map` was told to submit "a Markdown table" against a `text/plain`
    contract; Haiku sent text/markdown and submit_output refused MEDIA_TYPE_MISMATCH."""

    (supplier, _consumer) = missions(FIXTURES[3])
    (node,) = (item for item in supplier["program"]["nodes"] if item["key"] == "map")
    (output,) = node["outputs"]
    assert f"media_type {output['media_type']}" in " ".join(node["instruction"].split())


@pytest.mark.asyncio
async def test_e5_nests_one_goal_loop_between_two_agent_stages() -> None:
    (program,) = (await compiled(FIXTURES[4])).programs
    blueprint = program.lowered.blueprint
    assert isinstance(blueprint, StageGraphBlueprint)
    (body,) = blueprint.nested_bodies
    assert (body.node_key, body.family, body.depth) == ("research", "GoalDirected", 1)
    exports = {item.output: item.timing for item in body.exports}
    assert exports == {"report": "final", "progress_note": "early"}
    assert "research" in {edge.producer_stage_id for edge in blueprint.dependencies}

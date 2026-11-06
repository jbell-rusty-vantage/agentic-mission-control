"""OVE-171 / WI-08 slice D (PROOFS §5 C04/C05): bounded Revisit Regions in the pure interpreter.

A declared region (entry -> exit) re-runs while its stop rule does not hold, within a hard visit
cap; the stop is the `until` facts when authored, otherwise fulfillment of the region's required
obligations; no progress over `patience` visits or the cap end it as governed outcomes (never
success); an unknown stop fact is exhaustion (actionable). The entry's revisit receives exactly
the prior visit's accepted exit output; consumers wait for the final outcome and read only the
final visit (no siblings, no older attempts); review fix B1 is covered for routes.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.authoring.graph_routes import (
    GRAPH_SEMANTICS_V1,
    CarriedOutput,
    FactPredicate,
    FactRef,
    RevisitRegion,
    RouteBranch,
    StageFact,
    StageRoute,
)
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from tests.unit.orchestration.test_wi08_graph_routes import Driver

FACTS = (
    StageFact(fact_id="approved", output_slot_id="out", pointer="/approved", value_type="boolean"),
    StageFact(fact_id="score", output_slot_id="out", pointer="/score", value_type="integer"),
)


def region_graph(*, until: bool = True, max_visits: int = 3, patience: int | None = None):
    base = build_stagegraph_v2(
        logical_id="wi08.revisit",
        title="revisit",
        description="draft -> critique region, publish downstream",
        stages=(
            StageGraphStageSpec("draft", output_slots=("out",), obligation_refs=("drafted",)),
            StageGraphStageSpec(
                "critique",
                depends_on=("draft",),
                output_slots=("out",),
                facts=FACTS,
                obligation_refs=("critiqued",),
            ),
            StageGraphStageSpec("publish", depends_on=("draft", "critique"), output_slots=("out",)),
            StageGraphStageSpec("side", output_slots=("out",)),
        ),
        max_concurrency=8,
        graph_semantics=GRAPH_SEMANTICS_V1,
    )
    region = RevisitRegion(
        region_id="refine",
        stage_ids=("draft", "critique"),
        entry_stage_id="draft",
        exit_stage_id="critique",
        max_visits=max_visits,
        until=(FactPredicate(stage_id="critique", fact_id="approved", op="eq", value=True),)
        if until
        else (),
        progress=FactRef(stage_id="critique", fact_id="score") if patience else None,
        patience=patience,
        carry=(CarriedOutput(stage_id="critique", output_slot_id="out"),),
    )
    return StageGraphBlueprint.model_validate(
        {**base.model_dump(mode="python"), "revisit_regions": (region,)}
    )


def visit(graph: Driver, cycle: int, *, approved: Any = False, score: int = 10, **extra: Any):
    graph.run("draft", ref=f"artifact://draft/v{cycle}", **extra.get("draft", {}))
    graph.run(
        "critique",
        ref=f"artifact://critique/v{cycle}",
        facts={"approved": approved, "score": score},
        **extra.get("critique", {}),
    )


def revisit(graph: Driver) -> None:
    proposal = graph.interpreter.revisit_invalidation(
        graph.projection, region_id="refine", next_objective="address the critique"
    )
    graph.projection = graph.interpreter.apply_workflow_invalidation(
        graph.projection,
        proposal,
        next_run_version=graph.projection.run_version + 1,
        next_family_version=graph.projection.family_version + 1,
    )


def test_a_failing_stop_rule_revisits_with_the_prior_exit_output_carried_exactly() -> None:
    graph = Driver(region_graph())
    graph.run("side")
    visit(graph, 1, approved=False)
    (decision,) = graph.interpreter.revisit_view(graph.projection)
    assert (decision.visit, decision.disposition) == (1, "revisit")
    assert graph.interpreter.revisit_due(graph.projection) == decision
    assert "publish" not in graph.ready()  # consumers wait for the region's final outcome
    assert "revisit:refine" in graph.interpreter.completion(graph.projection).pending_dependency_ids
    revisit(graph)
    assert graph.ready() == {"draft"}  # `side` is reused, never re-run
    entry = graph.admit("draft")
    carried = [
        b for b in entry.frozen_input_bindings if b.consumer_input_slot_id.startswith("carry:")
    ]
    assert [(b.producer_stage_key, b.artifact_ref) for b in carried] == [
        ("critique", "artifact://critique/v1")
    ]
    assert "artifact://critique/v1" in entry.frozen_input_refs
    (lineage,) = entry.revisit_decisions
    assert (lineage.region_id, lineage.visit) == ("refine", 2)
    assert entry.continues_from is not None
    assert entry.continues_from.prior_result_refs == ("artifact://draft/v1",)
    graph.finish("draft", ref="artifact://draft/v2")
    graph.run("critique", ref="artifact://critique/v2", facts={"approved": True, "score": 90})
    (final,) = graph.interpreter.revisit_view(graph.projection)
    assert (final.visit, final.disposition) == (2, "exit")
    release = graph.admit("publish")
    # Exactly the final visit's outputs: no older attempt, no sibling.
    assert set(release.frozen_input_refs) == {"artifact://draft/v2", "artifact://critique/v2"}
    graph.finish("publish")
    completion = graph.interpreter.completion(graph.projection)
    assert completion.pending_dependency_ids == () and completion.open_producer_liability_ids == ()
    assert completion.revisit_decisions[0].disposition == "exit"


def test_the_visit_cap_is_a_governed_outcome_and_consumers_continue_from_the_last_visit() -> None:
    graph = Driver(region_graph(max_visits=2))
    visit(graph, 1)
    revisit(graph)
    visit(graph, 2)
    (decision,) = graph.interpreter.revisit_view(graph.projection)
    assert decision.disposition == "cap_exhausted"
    assert graph.interpreter.revisit_due(graph.projection) is None
    with pytest.raises(ValueError, match="no revisit"):
        graph.interpreter.revisit_invalidation(
            graph.projection, region_id="refine", next_objective="again"
        )
    release = graph.admit("publish")
    assert set(release.frozen_input_refs) == {"artifact://draft/v2", "artifact://critique/v2"}


def test_no_progress_over_patience_ends_the_region() -> None:
    graph = Driver(region_graph(max_visits=5, patience=1))
    visit(graph, 1, score=50)
    revisit(graph)
    visit(graph, 2, score=40)
    (decision,) = graph.interpreter.revisit_view(graph.projection)
    assert decision.disposition == "no_progress" and decision.progress == (50, 40)


def test_without_until_the_stop_is_fulfillment_of_the_region_obligations() -> None:
    graph = Driver(region_graph(until=False))
    visit(graph, 1, draft={"obligations": ("drafted",)})
    assert graph.interpreter.revisit_view(graph.projection)[0].disposition == "revisit"
    revisit(graph)
    visit(graph, 2, critique={"obligations": ("critiqued",)})
    # `drafted` from visit 1 is retained (accumulated); `critiqued` arrives in visit 2.
    assert graph.interpreter.revisit_view(graph.projection)[0].disposition == "exit"


def test_an_unknown_stop_fact_is_exhaustion_never_false() -> None:
    graph = Driver(region_graph())
    visit(graph, 1, approved=None)
    (decision,) = graph.interpreter.revisit_view(graph.projection)
    assert decision.disposition == "exhausted"
    assert graph.interpreter.revisit_due(graph.projection) is None
    (held,) = graph.interpreter.exhaustion(graph.projection)
    assert held.condition_id == "revisit-exhausted:refine" and held.stage_ids == ("publish",)
    assert "publish" not in graph.ready()
    assert not graph.interpreter.completion(graph.projection).can_terminalize


def test_a_failed_exit_ends_the_region_and_skips_its_consumers() -> None:
    graph = Driver(region_graph())
    graph.run("side")
    graph.run("draft")
    graph.run("critique", outcome="failed")
    assert graph.interpreter.revisit_view(graph.projection)[0].disposition == "failed"
    concluded = graph.interpreter.failure_completion(graph.projection)
    assert concluded is not None and concluded.skipped_stage_ids == ("publish",)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"entry_stage_id": "critique"}, "entry depends on no other region stage"),
        ({"stage_ids": ("draft", "critique", "ghost")}, "unknown stage"),
        ({"carry": (CarriedOutput(stage_id="critique", output_slot_id="nope"),)}, "carries"),
    ],
)
def test_a_malformed_region_is_refused(change: dict[str, Any], message: str) -> None:
    graph = region_graph()
    region = graph.revisit_regions[0].model_copy(update=change)
    with pytest.raises(ValueError, match=message):
        StageGraphBlueprint.model_validate(
            {**graph.model_dump(mode="python"), "revisit_regions": (region,)}
        )


def test_a_region_owns_the_workflow_cycle_and_needs_the_semantics_marker() -> None:
    graph = region_graph()
    with pytest.raises(ValueError, match="graph routes semantics"):
        StageGraphBlueprint.model_validate(
            {**graph.model_dump(mode="python"), "graph_semantics": None}
        )


# ---------------------------------------------------------------- review fix B1


def test_a_branch_with_one_final_and_one_pending_unknown_is_not_exhausted() -> None:
    flag = (StageFact(fact_id="f", output_slot_id="out", pointer="/f", value_type="boolean"),)
    graph = build_stagegraph_v2(
        logical_id="wi08.b1",
        title="b1",
        description="a conjunction over two sources",
        stages=(
            StageGraphStageSpec("a", output_slots=("out",), facts=flag),
            StageGraphStageSpec("b", output_slots=("out",), facts=flag),
            StageGraphStageSpec("t", output_slots=("out",)),
        ),
        max_concurrency=8,
        routes=(
            StageRoute(
                route_id="r",
                mode="all_matching",
                branches=(
                    RouteBranch(
                        branch_id="both",
                        predicates=(
                            FactPredicate(stage_id="a", fact_id="f", op="eq", value=True),
                            FactPredicate(stage_id="b", fact_id="f", op="eq", value=True),
                        ),
                        target_stage_ids=("t",),
                    ),
                ),
            ),
        ),
        graph_semantics=GRAPH_SEMANTICS_V1,
    )
    driver = Driver(graph)
    driver.run("a", facts={"f": None})  # final unknown
    driver.admit("b")  # still pending: could resolve false and decide the branch
    (decision,) = driver.interpreter.route_view(driver.projection).decisions
    assert decision.branches[0].truth == "unknown" and not decision.exhausted
    assert driver.interpreter.exhaustion(driver.projection) == ()
    driver.finish("b", facts={"f": False})
    (decided,) = driver.interpreter.route_view(driver.projection).decisions
    assert decided.branches[0].truth == "false" and not decided.exhausted


def test_after_the_cap_the_graph_concludes_failed_never_success() -> None:
    from mission_control.application.programs.service import _completion_payload

    graph = Driver(region_graph(max_visits=2))
    graph.run("side")
    visit(graph, 1)
    revisit(graph)
    visit(graph, 2)
    graph.run("publish")
    ordinary = graph.interpreter.completion(graph.projection)
    assert not ordinary.can_terminalize and not ordinary.required_obligations_accepted
    concluded = graph.interpreter.failure_completion(graph.projection)
    assert concluded is not None and concluded.failed and concluded.can_terminalize
    assert concluded.unmet_reasons == ("revisit-cap-exhausted:refine:visit-2-of-2",)
    assert _completion_payload(concluded)["unmet_reasons"] == concluded.unmet_reasons
    # Never while the region may still run, nor once its obligations are fulfilled.
    running = Driver(region_graph(max_visits=2))
    visit(running, 1)
    assert running.interpreter.failure_completion(running.projection) is None

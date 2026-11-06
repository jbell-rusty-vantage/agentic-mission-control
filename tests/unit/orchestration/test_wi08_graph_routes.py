"""OVE-171 / WI-08: explicit routes, named release groups and visible optional omission in the
pure Stage Graph interpreter (OUTPUT-CONTRACTS §7 engineering resolution).

all-matching true releases while unknown waits; first-match never skips an earlier unknown; else
needs every branch conclusively false; unknown exhaustion is actionable (never false); a quorum
never waives coverage; any/quorum selection is the first qualifying distinct set in durable
order; surplus continues and a late arrival cannot alter a frozen release; an optional pending
input is omitted visibly; a blueprint without the semantics marker keeps its old behavior.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.domain.authoring.contracts import JoinKind, StageGraphBlueprint
from mission_control.domain.authoring.graph_routes import (
    GRAPH_SEMANTICS_V1,
    FactPredicate,
    RouteBranch,
    StageFact,
    StageRoute,
)
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    StageInputBindingSpec,
    StageReleaseGroupSpec,
    build_stagegraph_v2,
)
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    LateResultFacts,
    StageGraphAcceptedProjection,
    StageResultObservation,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from mission_control.domain.programs.routing import ROUTE_FACTS_KEY

RUN = "run-wi08"


class Driver:
    """Admit and decide stages one at a time against the pure interpreter."""

    def __init__(self, blueprint: StageGraphBlueprint) -> None:
        self.interpreter = StageGraphInterpreter(blueprint, effective_max_concurrency=8)
        self.projection: StageGraphAcceptedProjection = self.interpreter.initial_projection(
            ExecutionIdentity(RUN), run_version=1
        )
        self.order = 0
        self.proposals: dict[str, Any] = {}

    def ready(self) -> set[str]:
        return {
            item.identity.stage_id
            for item in self.interpreter.frontier(self.projection, available_concurrency=8)
        }

    def admit(self, stage_id: str) -> Any:
        frontier = self.interpreter.frontier(self.projection, available_concurrency=8)
        proposal = next(item for item in frontier if item.identity.stage_id == stage_id)
        self.projection = self.interpreter.apply_admission(
            self.projection,
            proposal,
            next_run_version=self.projection.run_version + 1,
            next_family_version=self.projection.family_version + 1,
        )
        self.proposals[stage_id] = proposal
        return proposal

    def finish(
        self,
        stage_id: str,
        *,
        facts: dict[str, Any] | None = None,
        outcome: str = "completed",
        ref: str | None = None,
        obligations: tuple[str, ...] = (),
    ) -> None:
        proposal = self.proposals[stage_id]
        self.order += 1
        result: dict[str, Any] = {"output_refs": [ref or f"artifact://{stage_id}/out"]}
        if obligations:
            result["obligation_refs"] = list(obligations)
        if facts is not None:
            result[ROUTE_FACTS_KEY] = {
                key: {"status": "known", "value": value, "evidence_ref": f"ev:{stage_id}:{key}"}
                if value is not None
                else {"status": "unknown", "reason": "fact_pointer_absent"}
                for key, value in facts.items()
            }
        consumers = {
            edge.consumer_stage_id
            for edge in self.interpreter.blueprint.dependencies
            if edge.producer_stage_id == stage_id
        }
        admitted = any(
            item.candidate.stage_id in consumers
            and item.status not in {"blocked", "ready", "structurally_unavailable"}
            for item in self.projection.stages.values()
        )
        decision = self.interpreter.result_decision(
            proposal.identity,
            LateResultFacts(consumer_already_admitted=admitted),
            operation_disposition=outcome,
            operation_result=result if outcome == "completed" else None,
        )
        self.projection = self.interpreter.apply_result_decision(
            self.projection,
            StageResultObservation(
                identity=proposal.identity,
                operation_result=result,
                child_closed_or_quiesced=True,
                reservations_and_usage_settled=True,
                effects_settled=True,
                cancellation_reconciled=True,
                accepted_order=self.order,
                operation_disposition=outcome,
            ),
            decision,
            next_run_version=self.projection.run_version + 1,
            next_family_version=self.projection.family_version + 1,
        )

    def run(self, stage_id: str, **kwargs: Any) -> Any:
        proposal = self.admit(stage_id)
        self.finish(stage_id, **kwargs)
        return proposal


def _route(
    mode: str, *branches: tuple[str, str, str, tuple[str, Any], str], else_: tuple[str, ...] = ()
) -> StageRoute:
    """`(branch, fact stage, fact, (op, value), target)` per branch, in declared order."""

    return StageRoute(
        route_id="r",
        mode=mode,  # type: ignore[arg-type]
        branches=tuple(
            RouteBranch(
                branch_id=branch_id,
                predicates=(
                    FactPredicate(
                        stage_id=stage, fact_id=fact, op=comparison[0], value=comparison[1]
                    ),  # type: ignore[arg-type]
                ),
                target_stage_ids=(target,),
            )
            for branch_id, stage, fact, comparison, target in branches
        ),
        else_stage_ids=else_,
    )


def _flag_fact(name: str = "flagged", kind: str = "boolean") -> tuple[StageFact, ...]:
    return (StageFact(fact_id=name, output_slot_id="out", pointer=f"/{name}", value_type=kind),)


def all_matching_graph() -> StageGraphBlueprint:
    return build_stagegraph_v2(
        logical_id="wi08.all",
        title="all matching",
        description="two flags, three follow-ups",
        stages=(
            StageGraphStageSpec("scan_a", output_slots=("out",), facts=_flag_fact()),
            StageGraphStageSpec("scan_b", output_slots=("out",), facts=_flag_fact()),
            StageGraphStageSpec("follow_a", output_slots=("out",)),
            StageGraphStageSpec("follow_b", output_slots=("out",)),
            StageGraphStageSpec("none", output_slots=("out",)),
        ),
        max_concurrency=8,
        routes=(
            _route(
                "all_matching",
                ("a", "scan_a", "flagged", ("eq", True), "follow_a"),
                ("b", "scan_b", "flagged", ("eq", True), "follow_b"),
                else_=("none",),
            ),
        ),
        graph_semantics=GRAPH_SEMANTICS_V1,
    )


def first_match_graph() -> StageGraphBlueprint:
    return build_stagegraph_v2(
        logical_id="wi08.first",
        title="first match",
        description="ordered triage",
        stages=(
            StageGraphStageSpec(
                "triage",
                output_slots=("out",),
                facts=(
                    StageFact(
                        fact_id="severity", output_slot_id="out", pointer="/s", value_type="string"
                    ),
                    StageFact(
                        fact_id="sources", output_slot_id="out", pointer="/n", value_type="integer"
                    ),
                ),
            ),
            StageGraphStageSpec("deep", output_slots=("out",)),
            StageGraphStageSpec("light", output_slots=("out",)),
            StageGraphStageSpec("archive", output_slots=("out",)),
            StageGraphStageSpec("report", depends_on=("deep",), output_slots=("out",)),
        ),
        max_concurrency=8,
        routes=(
            _route(
                "first_match",
                ("urgent", "triage", "severity", ("eq", "high"), "deep"),
                ("broad", "triage", "sources", ("ge", 3), "light"),
                else_=("archive",),
            ),
        ),
        graph_semantics=GRAPH_SEMANTICS_V1,
    )


# ---------------------------------------------------------------- routes


def test_all_matching_true_releases_while_an_unknown_branch_waits() -> None:
    graph = Driver(all_matching_graph())
    assert graph.ready() == {"scan_a", "scan_b"}
    graph.admit("scan_b")  # scan_b runs; its fact stays unknown
    graph.run("scan_a", facts={"flagged": True})
    assert graph.ready() == {"follow_a"}  # follow_b and else wait on the unknown
    (decision,) = graph.interpreter.route_view(graph.projection).decisions
    assert [(b.branch_id, b.truth, b.disposition) for b in decision.branches] == [
        ("a", "true", "selected"),
        ("b", "unknown", "waiting"),
    ]
    assert decision.else_disposition == "not_selected"
    assert decision.branches[0].evidence_refs == ("ev:scan_a:flagged",)
    released = graph.admit("follow_a")
    assert released.route_decisions == (decision,)
    graph.finish("follow_a")
    graph.finish("scan_b", facts={"flagged": False})
    view = graph.interpreter.route_view(graph.projection)
    assert view.skipped == {"follow_b", "none"}
    completion = graph.interpreter.completion(graph.projection)
    assert completion.can_terminalize
    assert completion.route_skipped_stage_ids == ("follow_b", "none")
    assert completion.route_decisions == view.decisions


def test_else_needs_every_branch_conclusively_false() -> None:
    graph = Driver(all_matching_graph())
    graph.run("scan_a", facts={"flagged": False})
    assert "none" not in graph.ready()  # scan_b unknown: else waits, never assumed false
    graph.run("scan_b", facts={"flagged": False})
    assert graph.ready() == {"none"}
    assert graph.interpreter.route_view(graph.projection).skipped == {"follow_a", "follow_b"}


def test_first_match_never_skips_an_earlier_unknown_branch() -> None:
    graph = Driver(first_match_graph())
    # `sources >= 3` is true but `severity` is unknown (absent): urgent waits, broad cannot win.
    graph.run("triage", facts={"severity": None, "sources": 5})
    assert graph.ready() == set()
    (decision,) = graph.interpreter.route_view(graph.projection).decisions
    assert [(b.truth, b.disposition) for b in decision.branches] == [
        ("unknown", "waiting"),
        ("true", "waiting"),
    ]
    # The fact can never become known: exhaustion is actionable, never false.
    assert decision.exhausted and decision.else_disposition == "waiting"
    assert graph.interpreter.route_view(graph.projection).skipped == frozenset()
    assert graph.interpreter.failure_completion(graph.projection) is None
    assert not graph.interpreter.completion(graph.projection).can_terminalize


def test_first_match_selects_in_declared_order_and_skips_dependents_visibly() -> None:
    graph = Driver(first_match_graph())
    graph.run("triage", facts={"severity": "normal", "sources": 5})
    assert graph.ready() == {"light"}
    view = graph.interpreter.route_view(graph.projection)
    # `report` requires `deep`, which no branch selected: conclusively unreleasable.
    assert view.skipped == {"deep", "archive", "report"}
    graph.run("light")
    completion = graph.interpreter.completion(graph.projection)
    assert completion.can_terminalize and completion.pending_dependency_ids == ()
    assert completion.route_skipped_stage_ids == ("archive", "deep", "report")


def test_a_failed_fact_source_leaves_its_route_exhausted_not_false() -> None:
    graph = Driver(first_match_graph())
    graph.run("triage", outcome="failed")
    (decision,) = graph.interpreter.route_view(graph.projection).decisions
    assert decision.exhausted
    assert {b.unknown_reasons[0].split(":")[1] for b in decision.branches} == {
        "source_not_accepted"
    }
    assert graph.ready() == set()


def test_a_provider_cannot_supply_a_fact_of_the_wrong_type() -> None:
    graph = Driver(first_match_graph())
    graph.run("triage", facts={"severity": 7, "sources": "many"})
    (decision,) = graph.interpreter.route_view(graph.projection).decisions
    assert all(b.truth == "unknown" for b in decision.branches)


# ---------------------------------------------------------------- named groups


def quorum_graph(*, optional_context: bool = False) -> StageGraphBlueprint:
    stages = [
        StageGraphStageSpec("safety_a", output_slots=("out",)),
        StageGraphStageSpec("safety_b", output_slots=("out",)),
        StageGraphStageSpec("efficacy", output_slots=("out",)),
        StageGraphStageSpec("context", output_slots=("out",)),
        StageGraphStageSpec(
            "synth",
            output_slots=("out",),
            depends_on=("context",) if optional_context else (),
            bindings=(StageInputBindingSpec("context", "out", required=False),)
            if optional_context
            else (),
            groups=(
                StageReleaseGroupSpec(
                    group_id="reviews",
                    member_stage_ids=("safety_a", "safety_b", "efficacy"),
                    join=JoinKind.MINIMUM,
                    minimum=2,
                    coverage_subjects=("efficacy", "safety"),
                    member_coverage=(
                        ("efficacy", ("efficacy",)),
                        ("safety_a", ("safety",)),
                        ("safety_b", ("safety",)),
                    ),
                ),
            ),
        ),
        StageGraphStageSpec(
            "quick",
            output_slots=("out",),
            groups=(
                StageReleaseGroupSpec(
                    group_id="first",
                    member_stage_ids=("safety_a", "safety_b"),
                    join=JoinKind.ANY,
                ),
            ),
        ),
    ]
    return build_stagegraph_v2(
        logical_id="wi08.groups",
        title="groups",
        description="quorum with coverage and any",
        stages=tuple(stages),
        max_concurrency=8,
        graph_semantics=GRAPH_SEMANTICS_V1,
    )


def _selections(proposal: Any) -> dict[str, str | None]:
    return {item.producer_stage_id: item.selection for item in proposal.released_by}


def test_a_quorum_never_waives_group_coverage() -> None:
    graph = Driver(quorum_graph())
    graph.run("safety_a")
    graph.run("safety_b")
    assert "synth" not in graph.ready()  # quorum 2 met, efficacy uncovered
    graph.run("efficacy")
    assert "synth" in graph.ready()


def test_quorum_coverage_is_impossible_once_the_only_covering_member_fails() -> None:
    graph = Driver(quorum_graph())
    graph.run("safety_a")
    graph.run("safety_b")
    graph.run("efficacy", outcome="failed")
    assert "synth" not in graph.ready()
    graph.run("quick")
    graph.run("context")
    concluded = graph.interpreter.failure_completion(graph.projection)
    assert concluded is not None and concluded.skipped_stage_ids == ("synth",)


def test_selection_is_the_first_qualifying_set_and_surplus_never_enters_the_release() -> None:
    graph = Driver(quorum_graph())
    graph.run("efficacy")
    graph.run("safety_b")
    graph.admit("safety_a")  # still running: surplus to the qualifying {efficacy, safety_b}
    release = graph.admit("synth")
    assert _selections(release) == {
        "efficacy": "selected",
        "safety_b": "selected",
        "safety_a": "surplus",
    }
    assert {item.producer_stage_key for item in release.frozen_input_bindings} == {
        "efficacy",
        "safety_b",
    }
    assert "artifact://safety_a/out" not in release.frozen_input_refs
    # Graph surplus continues; its late result is admitted but cannot alter the release.
    graph.finish("safety_a")
    synth = next(
        item for item in graph.projection.stages.values() if item.candidate.stage_id == "synth"
    )
    assert synth.frozen_input_refs == release.frozen_input_refs
    assert graph.projection.dependencies["safety_a:to:synth"].disposition.value == "fulfilled"


def test_any_selects_exactly_one_member_even_when_both_finished_first() -> None:
    graph = Driver(quorum_graph())
    graph.run("safety_b")
    graph.run("safety_a")
    release = graph.admit("quick")
    assert _selections(release) == {"safety_b": "selected", "safety_a": "surplus"}
    assert [item.producer_stage_key for item in release.frozen_input_bindings] == ["safety_b"]


def test_an_optional_pending_input_is_omitted_visibly_when_otherwise_ready() -> None:
    graph = Driver(quorum_graph(optional_context=True))
    graph.admit("context")  # still running when the group qualifies
    graph.run("safety_a")
    graph.run("efficacy")
    release = graph.admit("synth")
    assert _selections(release)["context"] == "omitted"
    assert "context" not in {item.producer_stage_key for item in release.frozen_input_bindings}
    graph.finish("context")  # a late arrival cannot alter the frozen release
    synth = next(
        item for item in graph.projection.stages.values() if item.candidate.stage_id == "synth"
    )
    assert synth.frozen_input_refs == release.frozen_input_refs


def test_a_failed_optional_producer_is_omitted_never_selected() -> None:
    graph = Driver(quorum_graph(optional_context=True))
    graph.run("context", outcome="failed")
    graph.run("safety_a")
    graph.run("efficacy")
    release = graph.admit("synth")
    assert _selections(release)["context"] == "omitted"


def test_a_legacy_blueprint_keeps_waiting_for_its_optional_input() -> None:
    legacy = build_stagegraph_v2(
        logical_id="wi08.legacy",
        title="legacy",
        description="no graph routes semantics",
        stages=(
            StageGraphStageSpec("context", output_slots=("out",)),
            StageGraphStageSpec(
                "use",
                depends_on=("context",),
                bindings=(StageInputBindingSpec("context", "out", required=False),),
                output_slots=("out",),
            ),
        ),
    )
    assert legacy.graph_semantics is None and legacy.routes == ()
    graph = Driver(legacy)
    graph.admit("context")
    assert graph.ready() == set()  # unchanged: replays of admitted runs see the same frontier
    graph.finish("context")
    proposal = graph.admit("use")
    assert all(item.selection is None for item in proposal.released_by)


def test_routes_and_groups_require_the_semantics_marker() -> None:
    graph = all_matching_graph()
    with pytest.raises(ValueError, match="require the graph routes semantics"):
        StageGraphBlueprint.model_validate(
            {**graph.model_dump(mode="python"), "graph_semantics": None}
        )


def test_a_route_cannot_release_its_own_fact_source() -> None:
    graph = all_matching_graph()
    bad = _route("all_matching", ("a", "scan_a", "flagged", ("eq", True), "scan_a"))
    with pytest.raises(ValueError, match="whose facts decide it"):
        StageGraphBlueprint.model_validate({**graph.model_dump(mode="python"), "routes": (bad,)})


def test_a_route_through_a_dependency_cycle_is_refused() -> None:
    graph = first_match_graph()
    # `report` depends on `deep`; a route deciding `deep` from `report` facts is a cycle.
    stages = [
        stage.model_copy(update={"facts": _flag_fact()}) if stage.stage_id == "report" else stage
        for stage in graph.stages
    ]
    bad = _route("first_match", ("x", "report", "flagged", ("eq", True), "deep"))
    with pytest.raises(ValueError, match="cycle"):
        StageGraphBlueprint.model_validate(
            {**graph.model_dump(mode="python"), "stages": stages, "routes": (bad,)}
        )


def test_the_blueprint_digest_is_unchanged_without_routes_or_groups() -> None:
    legacy = build_stagegraph_v2(
        logical_id="wi08.digest",
        title="digest",
        description="additive fields stay digest-neutral",
        stages=(StageGraphStageSpec("only", output_slots=("out",)),),
    )
    dumped = legacy.model_dump(mode="json")
    assert "routes" not in dumped and "graph_semantics" not in dumped
    assert all("facts" not in stage for stage in dumped["stages"])

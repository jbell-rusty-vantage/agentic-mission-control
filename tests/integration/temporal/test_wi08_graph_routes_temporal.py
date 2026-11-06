"""OVE-171 / WI-08 on real Temporal (test server): the Stage Graph workflow executes an explicit
first-match route and a named any-group, never admits a not-selected branch, lets a surplus
group member finish without altering the consumer's frozen release, terminalizes with the route
outcome recorded, and replays deterministically. The workflow command sequence is unchanged:
route gating and selection are pure interpreter decisions over the projection."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import StageGraphWorkflow
from mission_control.domain.authoring.contracts import JoinKind, StageGraphBlueprint
from mission_control.domain.authoring.graph_routes import (
    GRAPH_SEMANTICS_V1,
    CarriedOutput,
    FactPredicate,
    RevisitRegion,
    RouteBranch,
    StageFact,
    StageRoute,
)
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    StageReleaseGroupSpec,
    build_stagegraph_v2,
)
from mission_control.domain.programs.contracts import (
    BoundaryLifecycleOutcome,
    BoundaryLifecycleRequest,
    StageGraphAdmissionActivityRequest,
    StageGraphAdmissionActivityResult,
    StageGraphCycleActivityRequest,
    StageGraphCycleActivityResult,
    StageGraphResultActivityRequest,
    StageGraphResultActivityResult,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from mission_control.domain.programs.routing import ROUTE_FACTS_KEY
from tests.fixtures.operation_activities import wait_heartbeating
from tests.integration.temporal.test_wp_bp_010_temporal import (
    QUEUE,
    FakeStageGraphActivities,
    _operation,
    _run_input,
)


def routed_graph() -> StageGraphBlueprint:
    """triage -(first_match)-> deep | light | else archive; `report` releases on the any-group
    over the three alternatives; `side_fast`/`side_slow` feed `pick` through an any-group."""

    return build_stagegraph_v2(
        logical_id="wi08.temporal",
        title="WI-08 routes on Temporal",
        description="first-match route plus any-groups",
        stages=(
            StageGraphStageSpec(
                "triage",
                output_slots=("out",),
                facts=(
                    StageFact(
                        fact_id="severity",
                        output_slot_id="out",
                        pointer="/severity",
                        value_type="string",
                    ),
                ),
            ),
            StageGraphStageSpec("deep", output_slots=("out",)),
            StageGraphStageSpec("light", output_slots=("out",)),
            StageGraphStageSpec("archive", output_slots=("out",)),
            StageGraphStageSpec(
                "report",
                output_slots=("out",),
                groups=(
                    StageReleaseGroupSpec(
                        group_id="review",
                        member_stage_ids=("deep", "light", "archive"),
                        join=JoinKind.ANY,
                    ),
                ),
            ),
            StageGraphStageSpec("side_fast", output_slots=("out",)),
            StageGraphStageSpec("side_slow", output_slots=("out",)),
            StageGraphStageSpec(
                "pick",
                output_slots=("out",),
                groups=(
                    StageReleaseGroupSpec(
                        group_id="first",
                        member_stage_ids=("side_slow", "side_fast"),
                        join=JoinKind.ANY,
                    ),
                ),
            ),
        ),
        max_concurrency=3,
        routes=(
            StageRoute(
                route_id="triage_route",
                mode="first_match",
                branches=(
                    RouteBranch(
                        branch_id="urgent",
                        predicates=(
                            FactPredicate(
                                stage_id="triage", fact_id="severity", op="eq", value="high"
                            ),
                        ),
                        target_stage_ids=("deep",),
                    ),
                    RouteBranch(
                        branch_id="normal",
                        predicates=(
                            FactPredicate(
                                stage_id="triage", fact_id="severity", op="eq", value="normal"
                            ),
                        ),
                        target_stage_ids=("light",),
                    ),
                ),
                else_stage_ids=("archive",),
            ),
        ),
        graph_semantics=GRAPH_SEMANTICS_V1,
    )


class RoutedActivities(FakeStageGraphActivities):
    """The fixture family seam, with the host's fact attribution for `triage` and a slow
    surplus member that only finishes after `pick` was admitted."""

    def __init__(self, facts: Any = None) -> None:
        super().__init__()
        self.pick_admitted = asyncio.Event()
        self.releases: dict[str, Any] = {}
        self.release_log: list[Any] = []
        self.final_projection: Any = None
        self.boundary: list[BoundaryLifecycleRequest] = []
        self.held = asyncio.Event()
        # (stage_id, workflow cycle) -> attributed facts; default: triage is `normal`.
        self.facts = facts or (
            lambda stage, cycle: (
                {
                    "severity": {
                        "status": "known",
                        "value": "normal",
                        "evidence_ref": "artifact:triage#/severity@sha256:" + "1" * 64,
                    }
                }
                if stage == "triage"
                else None
            )
        )

    @activity.defn(name="stagegraph.apply_boundary_command")
    async def boundary_command(self, request: BoundaryLifecycleRequest) -> BoundaryLifecycleOutcome:
        self.boundary.append(request)
        self.held.set()
        return BoundaryLifecycleOutcome(
            accepted=True,
            status="accepted",
            reason_code="accepted",
            resulting_run_version=50 + len(self.boundary),
            phase="waiting",
        )

    @activity.defn(name="stagegraph.apply_cycle")
    async def apply_cycle(
        self, request: StageGraphCycleActivityRequest
    ) -> StageGraphCycleActivityResult:
        if request.cycle_scope != "revisit":
            return await super().apply_cycle(request)
        interpreter = StageGraphInterpreter(
            StageGraphBlueprint.model_validate(request.blueprint),
            effective_max_concurrency=request.effective_max_concurrency,
        )
        proposal = interpreter.revisit_invalidation(
            request.projection, region_id="refine", next_objective=request.next_objective
        )
        projection = interpreter.apply_workflow_invalidation(
            request.projection,
            proposal,
            next_run_version=request.projection.run_version + 1,
            next_family_version=request.projection.family_version + 1,
        )
        return StageGraphCycleActivityResult(
            accepted=True, projection=projection, proposal=proposal, reason_code="accepted"
        )

    @activity.defn(name="stagegraph.admit_operation")
    async def admit(
        self, request: StageGraphAdmissionActivityRequest
    ) -> StageGraphAdmissionActivityResult:
        interpreter = StageGraphInterpreter(
            StageGraphBlueprint.model_validate(request.blueprint),
            effective_max_concurrency=request.effective_max_concurrency,
        )
        authoritative = interpreter.frontier(
            request.projection,
            available_concurrency=request.effective_max_concurrency
            - interpreter.running_concurrency(request.projection),
        )
        assert authoritative and authoritative[0] == request.proposal
        stage_id = request.proposal.identity.stage_id
        self.admission_order.append(stage_id)
        self.releases[stage_id] = request.proposal
        self.release_log.append(request.proposal)
        if stage_id == "pick":
            self.pick_admitted.set()
        return StageGraphAdmissionActivityResult(
            accepted=True,
            projection=interpreter.apply_admission(
                request.projection,
                request.proposal,
                next_run_version=request.projection.run_version + 1,
                next_family_version=request.projection.family_version + 1,
            ),
            operation=_operation(request, None),
            reason_code="accepted",
        )

    @activity.defn(name="stagegraph.decide_result")
    async def decide(
        self, request: StageGraphResultActivityRequest
    ) -> StageGraphResultActivityResult:
        interpreter = StageGraphInterpreter(
            StageGraphBlueprint.model_validate(request.blueprint),
            effective_max_concurrency=request.effective_max_concurrency,
        )
        observation = request.observation
        result = {k: v for k, v in observation.operation_result.items() if k != ROUTE_FACTS_KEY}
        # What `attribute_route_facts` records from the validated output bytes.
        attributed = self.facts(
            observation.identity.stage_id, observation.identity.candidate.workflow_cycle_ordinal
        )
        if attributed is not None:
            result[ROUTE_FACTS_KEY] = attributed
        observation = replace(observation, operation_result=result)
        proposal = interpreter.result_decision(
            observation.identity,
            request.late_facts,
            operation_disposition=observation.operation_disposition,
            operation_result=result,
        )
        self.result_decisions.append((observation.identity.stage_id, proposal.decision.value))
        projection = interpreter.apply_result_decision(
            request.projection,
            observation,
            proposal,
            next_run_version=request.projection.run_version + 1,
            next_family_version=request.projection.family_version + 1,
        )
        self.final_projection = projection
        return StageGraphResultActivityResult(
            accepted=True, projection=projection, proposal=proposal, reason_code="accepted"
        )

    @activity.defn(name="operation.execute")
    async def execute_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        operation_id = str(request["identity"]["operation_id"])
        stage_id = operation_id.split(":stage:")[1].split(":", maxsplit=1)[0]
        if stage_id == "side_slow":
            await wait_heartbeating(self.pick_admitted)
        cycle = (
            operation_id.split(":workflow-cycle:")[1].split(":", maxsplit=1)[0]
            if ":workflow-cycle:" in operation_id
            else "0"
        )
        return {"output_refs": [f"artifact:{stage_id}:c{cycle}"]}

    @property
    def functions(self) -> list[object]:
        return [
            self.initialize,
            self.admit,
            self.decide,
            self.apply_cycle,
            self.complete,
            self.execute_operation,
            self.cancel_operation,
            self.boundary_command,
        ]


@pytest.mark.asyncio
async def test_routes_and_groups_execute_on_temporal_and_replay() -> None:
    activities = RoutedActivities()
    try:
        environment = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")

    graph = routed_graph()
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            handle = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                _run_input(graph),
                id="family/run-wi08-routes/1",
                task_queue=QUEUE,
            )
            result = await asyncio.wait_for(handle.result(), timeout=60)
            history = await handle.fetch_history()

        await Replayer(
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ).replay_workflow(history)

    admitted = set(activities.admission_order)
    # The route selected `light`; `deep` and `archive` were never admitted.
    assert {"triage", "light", "report"} <= admitted
    assert not admitted & {"deep", "archive"}
    report = activities.releases["report"]
    assert {item.producer_stage_id: item.selection for item in report.released_by} == {
        "deep": "unavailable",
        "light": "selected",
        "archive": "unavailable",
    }
    assert report.route_decisions == ()  # a group consumer, not a route target
    (decision,) = activities.releases["light"].route_decisions  # frozen at the branch release
    assert [(b.branch_id, b.truth, b.disposition) for b in decision.branches] == [
        ("urgent", "false", "not_selected"),
        ("normal", "true", "selected"),
    ]
    # `side_fast` qualified first; `side_slow` kept running (surplus) and finished after `pick`
    # was released, without entering its frozen inputs.
    pick = activities.releases["pick"]
    assert [item.producer_stage_key for item in pick.frozen_input_bindings] == ["side_fast"]
    assert activities.admission_order.index("pick") < len(activities.admission_order)
    assert ("side_slow", "admit") in activities.result_decisions
    final = activities.final_projection
    pick_instance = next(s for s in final.stages.values() if s.candidate.stage_id == "pick")
    assert pick_instance.frozen_input_refs == pick.frozen_input_refs
    completion = result.completion_proposal
    assert completion.can_terminalize
    assert completion.route_skipped_stage_ids == ("archive", "deep")
    assert completion.route_decisions and completion.route_decisions[0].route_id == "triage_route"


def revisit_graph(*, max_visits: int = 3, owed: tuple[str, ...] = ()) -> StageGraphBlueprint:
    """draft -> critique (region `refine`, at most 3 visits, until approved) -> publish."""

    base = build_stagegraph_v2(
        logical_id="wi08.temporal.revisit",
        title="WI-08 revisit on Temporal",
        description="a bounded revisit region",
        stages=(
            StageGraphStageSpec("draft", output_slots=("out",)),
            StageGraphStageSpec(
                "critique",
                depends_on=("draft",),
                output_slots=("out",),
                obligation_refs=owed,
                facts=(
                    StageFact(
                        fact_id="approved",
                        output_slot_id="out",
                        pointer="/approved",
                        value_type="boolean",
                    ),
                ),
            ),
            StageGraphStageSpec("publish", depends_on=("critique",), output_slots=("out",)),
        ),
        max_concurrency=3,
        graph_semantics=GRAPH_SEMANTICS_V1,
    )
    region = RevisitRegion(
        region_id="refine",
        stage_ids=("draft", "critique"),
        entry_stage_id="draft",
        exit_stage_id="critique",
        max_visits=max_visits,
        until=(FactPredicate(stage_id="critique", fact_id="approved", op="eq", value=True),),
        carry=(CarriedOutput(stage_id="critique", output_slot_id="out"),),
    )
    return StageGraphBlueprint.model_validate(
        {**base.model_dump(mode="python"), "revisit_regions": (region,)}
    )


def _approved_on_second_visit(stage: str, cycle: int) -> Any:
    if stage != "critique":
        return None
    return {"approved": {"status": "known", "value": cycle >= 1, "evidence_ref": f"ev:c{cycle}"}}


async def _environment() -> WorkflowEnvironment:
    try:
        return await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")


@pytest.mark.asyncio
async def test_a_revisit_region_reruns_governed_by_the_host_and_replays() -> None:
    activities = RoutedActivities(facts=_approved_on_second_visit)
    environment = await _environment()
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            handle = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                _run_input(revisit_graph()),
                id="family/run-wi08-revisit/1",
                task_queue=QUEUE,
            )
            result = await asyncio.wait_for(handle.result(), timeout=60)
            history = await handle.fetch_history()
        await Replayer(
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ).replay_workflow(history)

    assert activities.admission_order == ["draft", "critique", "draft", "critique", "publish"]
    second_draft = activities.release_log[2]
    carried = [
        b.artifact_ref
        for b in second_draft.frozen_input_bindings
        if b.consumer_input_slot_id.startswith("carry:")
    ]
    assert carried == ["artifact:critique:c0"]  # exactly the prior visit's accepted exit output
    assert second_draft.revisit_decisions[0].visit == 2
    publish = activities.releases["publish"]
    assert publish.frozen_input_refs == ("artifact:critique:c1",)  # final visit only
    assert result.completion_proposal.can_terminalize
    assert result.completion_proposal.revisit_decisions[0].disposition == "exit"


def _unknown_severity(stage: str, cycle: int) -> Any:
    if stage != "triage":
        return None
    return {"severity": {"status": "unknown", "reason": "fact_pointer_absent"}}


@pytest.mark.asyncio
async def test_an_exhausted_route_is_held_durably_until_an_operator_command() -> None:
    activities = RoutedActivities(facts=_unknown_severity)
    environment = await _environment()
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            handle = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                _run_input(routed_graph()),
                id="family/run-wi08-exhausted/1",
                task_queue=QUEUE,
            )
            await asyncio.wait_for(activities.held.wait(), timeout=60)
            await handle.signal(StageGraphWorkflow.request_cancel)
            result = await asyncio.wait_for(handle.result(), timeout=60)
            history = await handle.fetch_history()
        await Replayer(
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ).replay_workflow(history)

    (held,) = activities.boundary
    condition = held.action["condition"]
    assert held.action["kind"] == "set_wait" and condition["kind"] == "external_result"
    assert condition["condition_id"] == "route-exhausted:triage_route"
    assert set(condition["scope"]) == {"stage:deep", "stage:light", "stage:archive"}
    assert "triage.severity:fact_pointer_absent" in held.reason
    # The run held for intervention (never false, never a silent failure); the operator's
    # cancel then concluded it.
    assert not {"deep", "light", "archive", "report"} & set(activities.admission_order)
    assert result.completion_proposal.cancelled


def _never_approved(stage: str, cycle: int) -> Any:
    if stage != "critique":
        return None
    return {"approved": {"status": "known", "value": False, "evidence_ref": f"ev:c{cycle}"}}


@pytest.mark.asyncio
async def test_a_capped_region_concludes_failed_with_the_typed_unmet_reason() -> None:
    """Review S2: the cap is a governed terminal outcome, never success. Consumers continue from
    the last visit; the required obligation the region owes stays unmet; the graph concludes
    `failed` with a typed reason citing the cap (a failure ref, so the reducer records FAILED)."""

    activities = RoutedActivities(facts=_never_approved)
    environment = await _environment()
    async with environment:
        async with Worker(
            environment.client,
            task_queue=QUEUE,
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            handle = await environment.client.start_workflow(
                StageGraphWorkflow.run,
                _run_input(revisit_graph(max_visits=2, owed=("critiqued",))),
                id="family/run-wi08-capped/1",
                task_queue=QUEUE,
            )
            result = await asyncio.wait_for(handle.result(), timeout=60)
            history = await handle.fetch_history()
        await Replayer(
            workflows=[StageGraphWorkflow, OperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
        ).replay_workflow(history)

    assert activities.admission_order == ["draft", "critique", "draft", "critique", "publish"]
    completion = result.completion_proposal
    assert completion.failed and not completion.required_obligations_accepted
    assert completion.unmet_reasons == ("revisit-cap-exhausted:refine:visit-2-of-2",)
    assert completion.revisit_decisions[0].disposition == "cap_exhausted"

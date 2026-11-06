"""Completion decisions over real in-memory lifecycle and family repositories."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
    RunControlRepository,
)
from mission_control.application.execution.service import (
    FamilyAdmissionRegistry,
    RunControlService,
)
from mission_control.application.programs.completion_validation import ArtifactPublicationPending
from mission_control.application.programs.service import (
    StageGraphDecisionService,
    register_stagegraph_family_mutations,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageGraphBlueprint, StageOutputSlot
from mission_control.domain.authoring.graph_routes import (
    GRAPH_SEMANTICS_V1,
    FactPredicate,
    RevisitRegion,
    RouteBranch,
    StageFact,
    StageRoute,
)
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    CommandStatus,
    RecordUsageAction,
    StartAction,
)
from mission_control.domain.programs.completion import OutputSchemaBinding, SchemaCriterion
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    LateResultFacts,
    StageGraphAdmissionActivityRequest,
    StageGraphDecisionMutation,
    StageGraphResultActivityRequest,
    StageResultObservation,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.unit.operations.test_operation_execution import operation_request
from tests.unit.orchestration.test_artifact_schema_validation import SCHEMA, Custody, captured
from tests.unit.run_control.test_atomic_family_admission import admission_policies
from tests.unit.run_control.test_run_control import ConfigurationVerifier, command, request

SCOPE = "tenant-1"
OUTPUT = "workspace-candidate://report"


@pytest.mark.asyncio
async def test_bound_valid_artifact_cannot_launder_extra_output_ref():
    fixture = await prepared()
    candidate = replace(
        fixture.result,
        observation=replace(
            fixture.result.observation,
            operation_result={
                "output_refs": [OUTPUT, "artifact://unchecked"],
                "output_bindings": {"report": [OUTPUT]},
                "obligation_refs": ["goal"],
            },
        ),
    )
    decided = await fixture.service.decide_result(candidate)
    assert decided.proposal.decision.value == "reject"
    assert fixture.custody.calls == []
    assert not (
        await fixture.run_control.get_run(SCOPE, fixture.result.run_id)
    ).accepted_output_evidence


@dataclass
class Prepared:
    run_control: RunControlService
    repository: RunControlRepository
    service: StageGraphDecisionService
    custody: Custody
    result: StageGraphResultActivityRequest
    scope: str = SCOPE
    operation: OperationExecutionRequest | None = None

    async def journal(self) -> StageGraphDecisionMutation:
        head = await self.repository.get_family_head(
            self.scope, self.result.run_id, "stagegraph", StageGraphDecisionMutation
        )
        assert head is not None
        return head


async def prepared(
    repository: RunControlRepository | None = None,
    scope: str = SCOPE,
    operation_template: OperationExecutionRequest | None = None,
    release_usage: bool = True,
    currency_reservation: int = 0,
    revisit: bool = False,
    named_promises: Any = None,
    route: bool = False,
) -> Prepared:
    repository = repository if repository is not None else InMemoryRunControlRepository()
    registry = FamilyAdmissionRegistry()
    register_stagegraph_family_mutations(registry)
    control = RunControlService(
        repository, ConfigurationVerifier(frozenset({"goal"})), admission_policies(), registry
    )
    run_request = request(request_scope=scope)
    envelope = run_request.budget_envelope.model_copy(
        update={
            "dimensions": tuple(
                item.model_copy(update={"applicability": BudgetApplicability.UNBOUNDED})
                if item.dimension == "operation.attempts"
                or (currency_reservation and item.dimension == "currency.estimated_micros")
                else item
                for item in run_request.budget_envelope.dimensions
            )
        }
    )
    admitted = await control.admit(run_request.model_copy(update={"budget_envelope": envelope}))
    assert admitted.run_id is not None
    run_id = admitted.run_id
    started = await control.execute(
        command(run_id, 1, "start", StartAction()).model_copy(update={"request_scope": scope})
    )
    assert started.status == CommandStatus.ACCEPTED
    schema = OutputSchemaBinding(
        schema_ref="schema:report@1",
        source_digest="sha256:" + "a" * 64,
        schema_digest=sha256_digest(SCHEMA),
        json_schema=SCHEMA,
    )
    graph = build_stagegraph_v2(
        logical_id="test.completion.service",
        title="Completion service",
        description="Validate custody through the family decision service",
        stages=(
            StageGraphStageSpec(
                "final",
                output_slots=("report",),
                obligation_refs=("goal",),
                reservation={
                    "tokens.total": 1,
                    **(
                        {"currency.estimated_micros": currency_reservation}
                        if currency_reservation
                        else {}
                    ),
                },
                output_declarations=(
                    StageOutputSlot(
                        output_slot_id="report",
                        output_contract_ref="schema:report@1",
                        required=True,
                        validation_schema=schema,
                    ),
                ),
                schema_criteria=(
                    SchemaCriterion(
                        criterion_key="report-valid",
                        obligation_ref="goal",
                        schema_ref="schema:report@1",
                        output_slots=("report",),
                    ),
                ),
                # OVE-171 slice D: the `count` fact a one-stage Revisit Region stops on.
                facts=(
                    StageFact(
                        fact_id="count",
                        output_slot_id="report",
                        pointer="/count",
                        value_type="integer",
                    ),
                )
                if revisit or route
                else (),
            ),
            # L1-02: the targets of an ordered first_match route over the `count` fact.
            *(
                (
                    StageGraphStageSpec("deep", output_slots=("out",)),
                    StageGraphStageSpec("archive", output_slots=("out",)),
                )
                if route
                else ()
            ),
        ),
        routes=(
            StageRoute(
                route_id="final_route",
                mode="first_match",
                branches=(
                    RouteBranch(
                        branch_id="counted",
                        predicates=(
                            FactPredicate(stage_id="final", fact_id="count", op="ge", value=1),
                        ),
                        target_stage_ids=("deep",),
                    ),
                ),
                else_stage_ids=("archive",),
            ),
        )
        if route
        else (),
        graph_semantics=GRAPH_SEMANTICS_V1 if revisit or route else None,
    )
    if revisit:
        graph = StageGraphBlueprint.model_validate(
            {
                **graph.model_dump(mode="python"),
                "revisit_regions": (
                    RevisitRegion(
                        region_id="refine",
                        stage_ids=("final",),
                        entry_stage_id="final",
                        exit_stage_id="final",
                        max_visits=2,
                        until=(FactPredicate(stage_id="final", fact_id="count", op="ge", value=2),),
                    ),
                ),
            }
        )
    if named_promises is not None:
        graph = graph.model_copy(update={"output_promises": named_promises})
    interpreter = StageGraphInterpreter(graph, effective_max_concurrency=1)
    projection = interpreter.initial_projection(
        ExecutionIdentity(run_id), run_version=started.resulting_run_version
    )
    proposal = interpreter.frontier(projection, available_concurrency=1)[0]
    operation = (operation_template or operation_request()).model_copy(
        update={
            "identity": OperationAttemptIdentity(
                run_id=run_id,
                operation_id=proposal.identity.operation_id,
                operation_attempt=proposal.identity.semantic_attempt,
            ),
            "budget_reservation_id": proposal.reservation_id,
            "run_control_revision": projection.run_version + 1,
            "request_scope": scope,
        }
    )
    custody = Custody(captured(source_ref=OUTPUT))
    service = StageGraphDecisionService(control, repository, artifacts=custody)
    now = datetime.now(UTC)
    accepted = await service.admit_operation(
        StageGraphAdmissionActivityRequest(
            run_id=run_id,
            request_scope=scope,
            projection=projection,
            proposal=proposal,
            operation=OperationWorkflowRequest(
                semantic_attempt_id=proposal.identity.semantic_key,
                operation_kind="bound_operation",
                operation=operation,
            ),
            blueprint=graph.model_dump(mode="json"),
            effective_max_concurrency=1,
            occurred_at=now,
            idempotency_issuer="operator",
            correlation_id="completion-test",
        )
    )
    assert accepted.accepted, accepted.reason_code
    if release_usage:
        await _release_fixture_usage(control, scope, run_id, accepted, proposal)
    result = StageGraphResultActivityRequest(
        run_id=run_id,
        request_scope=scope,
        projection=accepted.projection,
        observation=StageResultObservation(
            proposal.identity, {"output_refs": [OUTPUT]}, True, True, True, True, 1
        ),
        late_facts=LateResultFacts(),
        blueprint=graph.model_dump(mode="json"),
        effective_max_concurrency=1,
        occurred_at=now,
        idempotency_issuer="operator",
        correlation_id="completion-test",
    )
    assert accepted.operation is not None and accepted.operation.operation is not None
    return Prepared(
        control, repository, service, custody, result, scope, accepted.operation.operation
    )


async def _release_fixture_usage(control, scope, run_id, accepted, proposal):
    settled = await control.execute(
        command(
            run_id,
            accepted.projection.run_version,
            "settle-producer-usage",
            RecordUsageAction(
                usage_id="producer-usage",
                reservation_id=proposal.reservation_id,
                actual_amounts={},
                release_amounts=proposal.reservation,
            ),
        ).model_copy(update={"request_scope": scope})
    )
    assert settled.status == CommandStatus.ACCEPTED


@pytest.mark.asyncio
async def test_valid_artifact_derives_obligation_without_provider_assertion() -> None:
    fixture = await prepared()
    result = await fixture.service.decide_result(fixture.result)
    assert result.accepted and result.proposal.decision.value == "admit"
    run = await fixture.run_control.get_run(SCOPE, fixture.result.run_id)
    assert [item.obligation_ref for item in run.accepted_obligation_evidence] == ["goal"]
    assert [item.output_ref for item in run.accepted_output_evidence] == [OUTPUT]
    validation = (await fixture.journal()).decision_payload["completion_validation"]
    assert validation["status"] == "satisfied"
    assert validation["criteria"][0]["obligation_ref"] == "goal"
    assert validation["checks"][0]["artifact_digest"] == fixture.custody.content.content_digest


async def test_finalized_named_schema_submission_derives_criterion_from_exact_value():
    from mission_control.application.programs.named_outputs import NamedStageOutputs
    from mission_control.domain.outputs.contracts import OutputForm
    from tests.fixtures.output_contracts import InMemoryOutputContractStore
    from tests.unit.outputs.scenario import build_stack, obligation, promises, schema, structured
    from tests.unit.outputs.test_output_fulfillment import invocation

    access = invocation()
    promise = obligation(
        "final.report",
        OutputForm.STRUCTURED,
        position="final",
        schema_pin=schema("schema:report@1", SCHEMA),
    )
    fixture = await prepared(scope=access.scope, named_promises=promises(promise))
    identity = fixture.result.observation.identity
    access = invocation(
        run_id=fixture.result.run_id,
        operation_id=identity.operation_id,
        generation=identity.execution_generation,
    )
    store = InMemoryOutputContractStore()
    stack = await build_stack(store, store.submissions, access, promise)
    ack = await stack.submit(
        "actual-named-submission",
        "final.report",
        structured(
            "report",
            {"count": 1},
            schema_ref="schema:report@1",
        ),
        position="final",
    )
    assert ack.status == "accepted", ack.error
    await stack.submissions.finalize(access.identity(("final.report",)))
    service = StageGraphDecisionService(
        fixture.run_control,
        fixture.repository,
        artifacts=fixture.custody,
        named_outputs=NamedStageOutputs(store, stack.outputs),
    )
    request = replace(
        fixture.result,
        observation=replace(
            fixture.result.observation,
            operation_result={
                "output_refs": [ack.revisions[0].revision_id],
                "output_bindings": {"report": [ack.revisions[0].revision_id]},
            },
        ),
    )
    decided = await service.decide_result(request)
    assert decided.accepted and decided.proposal.decision.value == "admit"
    canonical_ref = (
        f"output-revision:{ack.revisions[0].revision_id}#digest={ack.revisions[0].content_digest}"
    )
    run = await fixture.run_control.get_run(fixture.scope, fixture.result.run_id)
    assert [item.obligation_ref for item in run.accepted_obligation_evidence] == ["goal"]
    assert [item.output_ref for item in run.accepted_output_evidence] == [canonical_ref]
    validation = (await fixture.journal()).decision_payload["completion_validation"]
    assert validation["status"] == "satisfied"
    assert validation["checks"][0]["artifact_digest"] == sha256_digest({"count": 1})
    assert (
        fixture.custody.calls == []
    )  # No legacy artifact lookup or invented artifact publication.
    assert run.accepted_obligation_evidence[0].evidence_digest == sha256_digest(validation)


async def test_route_facts_read_the_accepted_named_output_revision_exactly():
    """L1-02 (E3 ed9951b6): a stage whose schema output is a `submit_output` revision has its
    route facts read from that accepted revision's canonical value (digest-bound), so a
    first_match route on them releases instead of holding `route-exhausted`."""
    from mission_control.application.programs.named_outputs import NamedStageOutputs
    from mission_control.domain.outputs.contracts import OutputForm
    from mission_control.domain.programs.routing import ROUTE_FACTS_KEY
    from tests.fixtures.output_contracts import InMemoryOutputContractStore
    from tests.unit.outputs.scenario import build_stack, obligation, promises, schema, structured
    from tests.unit.outputs.test_output_fulfillment import invocation

    access = invocation()
    promise = obligation(
        "final.report",
        OutputForm.STRUCTURED,
        position="final",
        schema_pin=schema("schema:report@1", SCHEMA),
    )
    fixture = await prepared(scope=access.scope, named_promises=promises(promise), route=True)
    identity = fixture.result.observation.identity
    access = invocation(
        run_id=fixture.result.run_id,
        operation_id=identity.operation_id,
        generation=identity.execution_generation,
    )
    store = InMemoryOutputContractStore()
    stack = await build_stack(store, store.submissions, access, promise)
    ack = await stack.submit(
        "named-verdict",
        "final.report",
        structured("report", {"count": 2}, schema_ref="schema:report@1"),
        position="final",
    )
    assert ack.status == "accepted", ack.error
    await stack.submissions.finalize(access.identity(("final.report",)))
    service = StageGraphDecisionService(
        fixture.run_control,
        fixture.repository,
        artifacts=fixture.custody,
        named_outputs=NamedStageOutputs(store, stack.outputs),
    )
    revision = ack.revisions[0]
    request = replace(
        fixture.result,
        observation=replace(
            fixture.result.observation,
            operation_result={
                "output_refs": [revision.revision_id],
                "output_bindings": {"report": [revision.revision_id]},
            },
        ),
    )
    decided = await service.decide_result(request)
    assert decided.accepted and decided.proposal.decision.value == "admit"
    canonical_ref = f"output-revision:{revision.revision_id}#digest={revision.content_digest}"
    digest = sha256_digest({"count": 2})
    assert revision.content_digest == digest
    (accepted,) = decided.projection.accepted_results
    facts = accepted.operation_result[ROUTE_FACTS_KEY]
    assert facts["count"] == {
        "status": "known",
        "value": 2,
        "evidence_ref": f"{canonical_ref}#/count@{digest}",
    }
    assert fixture.custody.calls == []  # never a custody read for a named value
    graph = StageGraphBlueprint.model_validate(fixture.result.blueprint)
    interpreter = StageGraphInterpreter(graph, effective_max_concurrency=1)
    (decision,) = interpreter.route_view(decided.projection).decisions
    assert [(b.branch_id, b.truth, b.disposition) for b in decision.branches] == [
        ("counted", "true", "selected")
    ]
    assert not decision.exhausted
    ready = {
        item.identity.candidate.stage_id
        for item in interpreter.frontier(decided.projection, available_concurrency=2)
    }
    assert ready == {"deep"}


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_invalid_or_missing_output_cannot_be_accepted_by_provider_claim(
    missing: bool,
) -> None:
    fixture = await prepared()
    fixture.custody.content = captured('{"count":0}', source_ref=OUTPUT)
    payload: dict[str, Any] = {
        "output_refs": [] if missing else [OUTPUT],
        "obligation_refs": ["goal"],
    }
    request_result = replace(
        fixture.result,
        observation=replace(fixture.result.observation, operation_result=payload),
    )
    result = await fixture.service.decide_result(request_result)
    assert result.accepted and result.proposal.decision.value == "reject"
    run = await fixture.run_control.get_run(SCOPE, fixture.result.run_id)
    assert not run.accepted_obligation_evidence and not run.accepted_output_evidence
    validation = (await fixture.journal()).decision_payload["completion_validation"]
    assert validation["status"] == "unsatisfied"
    expected = "output_missing" if missing else "artifact_schema_invalid"
    assert expected in validation["reason_codes"]


@pytest.mark.asyncio
async def test_delayed_publication_retries_without_mutation_across_service_restart() -> None:
    fixture = await prepared()
    fixture.custody.content = None
    before_run = await fixture.run_control.get_run(SCOPE, fixture.result.run_id)
    before_journal = await fixture.journal()
    with pytest.raises(ArtifactPublicationPending):
        await fixture.service.decide_result(fixture.result)
    assert await fixture.run_control.get_run(SCOPE, fixture.result.run_id) == before_run
    assert await fixture.journal() == before_journal
    fixture.custody.content = captured(source_ref=OUTPUT)
    restarted = StageGraphDecisionService(
        fixture.run_control, fixture.repository, artifacts=fixture.custody
    )
    accepted = await restarted.decide_result(fixture.result)
    assert accepted.accepted and accepted.proposal.decision.value == "admit"


@pytest.mark.asyncio
async def test_lost_response_replays_without_artifact_bytes_and_changed_delivery_rejects() -> None:
    fixture = await prepared()
    accepted = await fixture.service.decide_result(fixture.result)
    assert accepted.accepted
    before_run = await fixture.run_control.get_run(SCOPE, fixture.result.run_id)
    before_journal = await fixture.journal()
    fixture.custody.content = None
    fixture.custody.calls.clear()
    restarted = StageGraphDecisionService(
        fixture.run_control, fixture.repository, artifacts=fixture.custody
    )
    replayed = await restarted.decide_result(fixture.result)
    assert replayed == accepted
    assert fixture.custody.calls == []
    changed = replace(
        fixture.result,
        observation=replace(fixture.result.observation, operation_result={"output_refs": []}),
    )
    with pytest.raises(ValueError, match="reused with different request content"):
        await restarted.decide_result(changed)
    assert fixture.custody.calls == []
    assert await fixture.run_control.get_run(SCOPE, fixture.result.run_id) == before_run
    assert await fixture.journal() == before_journal


@pytest.mark.asyncio
async def test_publication_deadline_records_explicit_unmet_evidence() -> None:
    fixture = await prepared()
    fixture.custody.content = None
    expired = replace(fixture.result, occurred_at=datetime.now(UTC) - timedelta(minutes=16))
    result = await fixture.service.decide_result(expired)
    assert result.accepted and result.proposal.decision.value == "reject"
    validation = (await fixture.journal()).decision_payload["completion_validation"]
    assert validation["status"] == "unsatisfied"
    assert "artifact_publication_deadline_exceeded" in validation["reason_codes"]
    run = await fixture.run_control.get_run(SCOPE, fixture.result.run_id)
    assert not run.accepted_obligation_evidence and not run.accepted_output_evidence


@pytest.mark.asyncio
async def test_superseded_generation_is_quarantined_without_reading_valid_artifact() -> None:
    fixture = await prepared()
    stale = replace(fixture.result, late_facts=LateResultFacts(generation_superseded=True))
    result = await fixture.service.decide_result(stale)
    assert result.accepted and result.proposal.decision.value == "quarantine"
    assert not fixture.custody.calls
    run = await fixture.run_control.get_run(SCOPE, fixture.result.run_id)
    assert not run.accepted_obligation_evidence and not run.accepted_output_evidence
    validation = (await fixture.journal()).decision_payload["completion_validation"]
    assert validation["artifact_schema_validation"] == "not_evaluated"


@pytest.mark.asyncio
async def test_setup_supports_supplied_repository_and_canonical_request_scope() -> None:
    repository = InMemoryRunControlRepository()
    scope = "mc/installation-test/application-test/tenant-test"
    fixture = await prepared(repository, scope)
    assert fixture.repository is repository
    assert fixture.scope == scope
    accepted = await fixture.service.decide_result(fixture.result)
    assert accepted.accepted and accepted.proposal.decision.value == "admit"
    assert fixture.custody.calls == [(OUTPUT, scope, 1_048_576)]
    assert (await fixture.journal()).request_scope == scope


# --- 1.4.4 (P3.8, TR-D7): the decision table rows and the joinable events of a result -----


@pytest.mark.asyncio
async def test_result_decided_writes_its_completion_rows_in_the_family_transaction() -> None:
    from mission_control.domain.programs.runtime_units import stage_runtime_unit

    fixture = await prepared()
    run_id = fixture.result.run_id
    unit_key = stage_runtime_unit(SCOPE, fixture.result.observation.identity).unit_key
    assert fixture.repository.completion_decisions(SCOPE, run_id) == ()
    result = await fixture.service.decide_result(fixture.result)
    assert result.accepted and result.proposal.decision.value == "admit"

    journal = await fixture.journal()
    assert journal.completion is not None
    decisions = fixture.repository.completion_decisions(SCOPE, run_id)
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.decision_key == journal.mutation_id
    assert decision.result_disposition == "accepted"
    assert decision.activation_key == unit_key
    assert decision.candidate_key == (
        f"stagegraph-result:{fixture.result.observation.identity.semantic_key}"
    )
    assert decision.requirement_refs == ("goal",) and decision.result_refs == (OUTPUT,)
    assert decision.reason_codes == ()
    assert decision.decision["completion_validation"] == "satisfied"
    assert decision.policy_digest.startswith("sha256:") and decision.contract_digest.startswith(
        "sha256:"
    )
    candidates = fixture.repository.completion_candidates(SCOPE)
    assert [item.candidate_key for item in candidates] == [decision.candidate_key]
    assert candidates[0].activation_key == unit_key and candidates[0].artifact_refs == (OUTPUT,)
    assert candidates[0].candidate["observation_digest"].startswith("sha256:")
    assert candidates[0].submitted_at is None, "the writer takes the mutation's decided_at"

    # The admission and result events join on the unit (TR-D7); run-level events do not.
    by_type: dict[str, list[Any]] = {}
    for record in await fixture.run_control.pending_outbox(SCOPE):
        by_type.setdefault(record.envelope.event_type, []).append(record.envelope)
    assert by_type["workflow_run.reserve_budget"][0].unit_key == unit_key
    assert by_type["workflow_run.apply_authority_batch"][0].unit_key == unit_key
    assert by_type["workflow_run.start"][0].unit_key is None
    # The journal row keeps the proposal without the empty 1.4.4 fields.
    admission = await fixture.repository.get_family_mutation(
        SCOPE,
        run_id,
        "stagegraph",
        f"admit-{sha256_digest(fixture.result.observation.identity.semantic_key)[7:]}",
        StageGraphDecisionMutation,
    )
    assert admission is not None
    recorded = admission.decision_payload["proposal"]
    assert isinstance(recorded, dict)
    assert "released_by" not in recorded and "continues_from" not in recorded


@pytest.mark.asyncio
async def test_a_rejected_result_records_a_rejected_decision_with_its_reason_codes() -> None:
    fixture = await prepared()
    candidate = replace(
        fixture.result,
        observation=replace(
            fixture.result.observation,
            operation_result={
                "output_refs": [OUTPUT, "artifact://unchecked"],
                "output_bindings": {"report": [OUTPUT]},
                "obligation_refs": ["goal"],
            },
        ),
    )
    decided = await fixture.service.decide_result(candidate)
    assert decided.proposal.decision.value == "reject"
    decisions = fixture.repository.completion_decisions(SCOPE, fixture.result.run_id)
    assert len(decisions) == 1
    assert decisions[0].result_disposition == "rejected"
    assert decisions[0].reason_codes, "the validation's reason codes are recorded"
    assert decisions[0].candidate_key is not None, "a completed operation has a candidate"


def test_completion_disposition_mapping() -> None:
    from mission_control.application.programs.service import completion_disposition
    from mission_control.domain.programs.contracts import (
        ResultDecision,
        ResultDispositionProposal,
        StageCandidateIdentity,
        StageExecutionIdentity,
    )

    identity = StageExecutionIdentity(
        run_id="run-1",
        execution_epoch=1,
        candidate=StageCandidateIdentity("final", 0, "NO_MAPPED_INSTANCE", 0, 0, "execute"),
        semantic_attempt=1,
    )

    def proposal(decision: ResultDecision) -> ResultDispositionProposal:
        return ResultDispositionProposal(
            identity=identity, decision=decision, dependency_dispositions={}
        )

    admit, reject = proposal(ResultDecision.ADMIT), proposal(ResultDecision.REJECT)
    assert (
        completion_disposition(admit, operation_disposition="completed", evaluation="")
        == "accepted"
    )
    assert (
        completion_disposition(admit, operation_disposition="completed", evaluation="accept")
        == "accepted"
    )
    assert (
        completion_disposition(reject, operation_disposition="completed", evaluation="")
        == "rejected"
    )
    assert (
        completion_disposition(reject, operation_disposition="failed", evaluation="") == "rejected"
    )
    assert (
        completion_disposition(admit, operation_disposition="completed", evaluation="cycle")
        == "needs_more_work"
    )
    assert (
        completion_disposition(admit, operation_disposition="completed", evaluation="degrade")
        == "abandoned"
    )
    assert (
        completion_disposition(reject, operation_disposition="completed", evaluation="escalate")
        == "abandoned"
    )
    assert (
        completion_disposition(reject, operation_disposition="cancelled", evaluation="cycle")
        == "abandoned"
    )
    assert (
        completion_disposition(
            proposal(ResultDecision.QUARANTINE), operation_disposition="completed", evaluation=""
        )
        == "rejected"
    )

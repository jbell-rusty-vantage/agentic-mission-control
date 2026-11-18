"""Completion decisions over real in-memory lifecycle and family repositories."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from mission_control.application.programs.completion_validation import ArtifactPublicationPending
from mission_control.application.programs.service import (
    StageGraphDecisionService,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.policies.contracts import (
    AcceptedOutputEvidence,
    CommandStatus,
    RecordOutputEvidenceAction,
)
from mission_control.domain.programs.contracts import (
    LateResultFacts,
    StageGraphDecisionMutation,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.support.run_control import DIGEST, command
from tests.support.unit.orchestration.artifact_schema_validation import SCHEMA, captured
from tests.support.unit.orchestration.completion_validation_service import OUTPUT, SCOPE, prepared


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
    from mission_control.adapters.outputs.memory import InMemoryOutputContractStore
    from mission_control.application.programs.named_outputs import NamedStageOutputs
    from mission_control.domain.outputs.contracts import OutputForm
    from tests.support.unit.outputs.output_fulfillment import invocation
    from tests.unit.outputs.scenario import build_stack, obligation, promises, schema, structured

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
    from mission_control.adapters.outputs.memory import InMemoryOutputContractStore
    from mission_control.application.programs.named_outputs import NamedStageOutputs
    from mission_control.domain.outputs.contracts import OutputForm
    from mission_control.domain.programs.routing import ROUTE_FACTS_KEY
    from tests.support.unit.outputs.output_fulfillment import invocation
    from tests.unit.outputs.scenario import build_stack, obligation, promises, schema, structured

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


@pytest.mark.asyncio
async def test_sibling_authority_cas_loss_rebuilds_result_without_poisoning_decision_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = await prepared()
    original = fixture.repository.commit_family_admission
    attempts: list[Any] = []

    async def commit(mutation: Any):  # type: ignore[no-untyped-def]
        attempts.append(mutation)
        if len(attempts) == 1:
            run = await fixture.run_control.get_run(fixture.scope, fixture.result.run_id)
            sibling = await fixture.run_control.execute(
                command(
                    run.run_id,
                    run.version,
                    "sibling-completed",
                    RecordOutputEvidenceAction(
                        evidence=AcceptedOutputEvidence(
                            output_ref="output:sibling",
                            evidence_digest=DIGEST,
                            accepted_by_authority_ref="authority:lifecycle",
                        ),
                    ),
                ).model_copy(update={"request_scope": fixture.scope})
            )
            assert sibling.status is CommandStatus.ACCEPTED
        return await original(mutation)

    # Fault injection: a sibling's lifecycle command lands between the decision and its commit.
    monkeypatch.setattr(fixture.repository, "commit_family_admission", commit)
    result = await fixture.service.decide_result(fixture.result)
    assert result.accepted and len(attempts) == 2
    assert all(item.receipt.command_result.status is CommandStatus.ACCEPTED for item in attempts)
    assert attempts[0].family_mutation.mutation_id == attempts[1].family_mutation.mutation_id
    assert attempts[0].family_mutation.prior_projection_digest == (
        attempts[1].family_mutation.prior_projection_digest
    )
    command_id = (
        "stagegraph:result-"
        + sha256_digest(
            fixture.result.observation.identity.semantic_key,
        )[7:]
    )
    persisted = await fixture.repository.get_family_admission_receipt(
        fixture.scope,
        fixture.result.run_id,
        fixture.result.idempotency_issuer,
        command_id,
    )
    assert persisted is not None and persisted.command_result.status is CommandStatus.ACCEPTED
    assert await fixture.service.decide_result(fixture.result) == result
    assert len(attempts) == 2


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

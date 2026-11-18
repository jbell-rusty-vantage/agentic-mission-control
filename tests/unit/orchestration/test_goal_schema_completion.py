"""Goal fulfillment consumes captured bytes, not the independent verifier's assertion."""

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mission_control.application.programs.completion_validation import ArtifactPublicationPending
from mission_control.application.programs.goal_directed import GoalDirectedOperationResultService
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    OperationExecutionResult,
    RuntimeUsage,
)
from mission_control.domain.programs.goal_directed_runtime import (
    GoalExecutorObservation,
    GoalNamedExecutorObservation,
)
from tests.support.unit.orchestration.artifact_schema_validation import Custody, captured
from tests.support.unit.orchestration.goal_schema_completion import (
    OUTPUT,
    SUMMARY,
    ScopedCustody,
    goal_request,
    multi_goal_request,
)


class Documents:
    def __init__(self):
        self.saved = None

    async def load_verification(self, *args):
        return self.saved

    async def persist_verification(self, scope, run_id, revision, verification, at, **kwargs):
        self.saved = {
            "verification": asdict(verification),
            "request_digest": kwargs["request_digest"],
            "completion_validation": kwargs["completion_validation"].model_dump(mode="json"),
        }
        digest = sha256_digest(asdict(verification))
        return f"goal-verification:{verification.verification_id}@{digest}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "refs", "expected"),
    [
        ('{"count":1}', (OUTPUT,), "satisfied"),
        ('{"count":"bad"}', (OUTPUT,), "unsatisfied"),
        ('{"count":1}', (), "unsatisfied"),
        ('{"count":1}', (OUTPUT, "workspace-candidate://other-tenant"), "unsatisfied"),
    ],
)
async def test_goal_schema_rejects_missing_wrong_or_extra_and_replays(body, refs, expected):
    documents = Documents()
    custody = Custody(captured(body, source_ref=OUTPUT))
    request = goal_request(refs=refs)
    service = GoalDirectedOperationResultService(documents, artifacts=custody)
    result = await service.reconcile(request)
    assert result.completion_validation.status == expected
    assert result.verification_result.decision == (
        "accepted" if expected == "satisfied" else "rejected"
    )
    assert bool(result.verification_result.accepted_obligation_refs) == (expected == "satisfied")
    custody.content = None
    custody.calls.clear()
    assert (
        await GoalDirectedOperationResultService(documents, artifacts=custody).reconcile(request)
        == result
    )
    assert custody.calls == []
    changed = request.model_copy(
        update={
            "executor_result": replace(request.executor_result, output_refs=("artifact://changed",))
        }
    )
    with pytest.raises(ValueError, match="replay differs"):
        await service.reconcile(changed)


@pytest.mark.asyncio
async def test_goal_pending_has_no_partial_receipt_and_resumes():
    documents = Documents()
    custody = Custody(None)
    request = goal_request()
    with pytest.raises(ArtifactPublicationPending):
        await GoalDirectedOperationResultService(documents, artifacts=custody).reconcile(request)
    assert documents.saved is None
    custody.content = captured(source_ref=OUTPUT)
    result = await GoalDirectedOperationResultService(documents, artifacts=custody).reconcile(
        request
    )
    assert result.completion_validation.status == "satisfied"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("valid", None),
        ("no_bindings", "output_bindings_required"),
        ("missing", "output_missing"),
        ("extra", "unbound_output_ref"),
        ("unknown_slot", "invalid_output_bindings"),
        ("unregistered", "unregistered_output_binding"),
        ("invalid_report", "artifact_schema_invalid"),
        ("invalid_summary", "artifact_schema_invalid"),
        ("cross_scope", "artifact_publication_deadline_exceeded"),
    ],
)
async def test_named_goal_outputs_are_individually_validated_and_replay_bound(case, reason):
    request = multi_goal_request()
    custody, documents = ScopedCustody(), Documents()
    result = request.executor_result
    if case == "no_bindings":
        result = replace(result, output_bindings=None)
    elif case == "missing":
        result = replace(result, output_refs=(OUTPUT,), output_bindings={"report": (OUTPUT,)})
    elif case == "extra":
        result = replace(result, output_refs=(*result.output_refs, "workspace-candidate://extra"))
    elif case == "unknown_slot":
        result = replace(result, output_bindings={"report": (OUTPUT,), "undeclared": (SUMMARY,)})
    elif case == "unregistered":
        result = replace(
            result, output_bindings={"report": (OUTPUT,), "summary": ("not-returned",)}
        )
    elif case.startswith("invalid_"):
        ref = OUTPUT if case == "invalid_report" else SUMMARY
        custody.contents[("tenant-1", ref)] = captured('{"unrelated":true}', source_ref=ref)
    elif case == "cross_scope":
        custody.contents[("tenant-2", SUMMARY)] = custody.contents.pop(("tenant-1", SUMMARY))
        request = request.model_copy(
            update={"recorded_at": datetime.now(UTC) - timedelta(minutes=16)}
        )
    request = request.model_copy(update={"executor_result": result})
    service = GoalDirectedOperationResultService(documents, artifacts=custody)
    settled = await service.reconcile(request)
    assert settled.verification_result.decision == ("accepted" if reason is None else "rejected")
    assert bool(settled.verification_result.accepted_obligation_refs) == (reason is None)
    validation = settled.completion_validation
    if reason:
        assert reason in validation.reason_codes
    else:
        assert {check.output_slot for check in validation.checks} == {"report", "summary"}
        assert len({check.schema_digest for check in validation.checks}) == 2
        assert all(check.artifact_digest for check in validation.checks)
    assert all(scope == "tenant-1" for scope, _ in custody.calls)
    if case in {"no_bindings", "extra", "unknown_slot", "unregistered"}:
        assert not custody.calls
    custody.contents.clear()
    custody.calls.clear()
    assert (
        await GoalDirectedOperationResultService(documents, artifacts=custody).reconcile(request)
        == settled
    )
    assert custody.calls == []
    changed = request.model_copy(
        update={
            "executor_result": replace(
                result, output_bindings={"report": (SUMMARY,), "summary": (OUTPUT,)}
            )
        }
    )
    with pytest.raises(ValueError, match="replay differs"):
        await service.reconcile(changed)


@pytest.mark.asyncio
async def test_named_goal_optional_missing_output_and_cancelled_publication():
    request = multi_goal_request(optional=True)
    request = request.model_copy(
        update={
            "executor_result": replace(
                request.executor_result,
                output_refs=(OUTPUT,),
                output_bindings={"report": (OUTPUT,)},
            )
        }
    )
    result = await GoalDirectedOperationResultService(
        Documents(), artifacts=ScopedCustody()
    ).reconcile(request)
    assert result.completion_validation.status == "satisfied"
    request = multi_goal_request()
    custody, documents = ScopedCustody(), Documents()
    custody.contents.pop(("tenant-1", SUMMARY))
    control = SimpleNamespace(
        get_run=AsyncMock(return_value=SimpleNamespace(phase=SimpleNamespace(value="active")))
    )
    service = GoalDirectedOperationResultService(documents, artifacts=custody, run_control=control)
    with pytest.raises(ArtifactPublicationPending):
        await service.reconcile(request)
    assert documents.saved is None
    control.get_run.return_value.phase.value = "cancelling"
    cancelled = await service.reconcile(request)
    assert cancelled.verification_result.decision == "rejected"
    assert not cancelled.verification_result.accepted_obligation_refs
    assert cancelled.completion_validation.reason_codes == ("run_cancelled_during_publication",)
    custody.contents[("tenant-1", SUMMARY)] = captured('{"summary":"late"}', source_ref=SUMMARY)
    assert await service.reconcile(request) == cancelled


def test_legacy_goal_wire_document_and_schema_identities_are_preserved():
    request = goal_request()
    original = asdict(request.executor_result)
    original.pop("output_bindings")
    assert request.executor_result.to_payload() == original
    assert "output_bindings" not in request.model_dump(mode="python")["executor_result"]
    assert (
        sha256_digest(GoalExecutorObservation.model_json_schema())
        == "sha256:2230a49ad6c99845be21e70034608cca1ed2f34297f83b4b469423570575abea"
    )
    assert "output_bindings" in GoalNamedExecutorObservation.model_json_schema()["properties"]
    named = multi_goal_request()
    assert named.model_dump(mode="python")["executor_result"]["output_bindings"]


# --- 1.4.4 (P3.8): the verifier's decision and the executor's candidate in the decision table


@pytest.mark.asyncio
async def test_verification_records_its_completion_decision_once() -> None:
    from mission_control.application.execution.operations.operation_execution import (
        operation_settlement_id,
    )
    from mission_control.application.programs.goal_directed import InMemoryCompletionRecords

    documents = Documents()
    custody = Custody(captured('{"count":1}', source_ref=OUTPUT))
    completions = InMemoryCompletionRecords()
    request = goal_request()
    service = GoalDirectedOperationResultService(
        documents, artifacts=custody, completions=completions
    )
    result = await service.reconcile(request)
    verification = result.verification_result
    run_id = request.claim.identity.iteration.run_id
    decision = completions.decisions[("tenant-1", run_id, verification.verification_id)]
    assert decision.result_disposition == "accepted"
    assert decision.candidate_key == operation_settlement_id("binding:executor")
    assert decision.result_refs == (OUTPUT,)
    assert decision.requirement_refs == ("fixture-obligation",)
    assert decision.decision["completion_validation"] == "satisfied"
    assert decision.activation_key is not None and decision.activation_key.startswith("bl-unit-v1:")
    candidate = completions.candidates[("tenant-1", decision.candidate_key)]
    assert candidate.activation_key == decision.activation_key
    assert candidate.artifact_refs == (OUTPUT,) and candidate.execution_generation == 1
    # The replayed reconciliation (cached verification) re-issues the same keys: no new rows.
    custody.content = None
    again = await GoalDirectedOperationResultService(
        documents, artifacts=custody, completions=completions
    ).reconcile(request)
    assert again == result
    assert len(completions.decisions) == 1 and len(completions.candidates) == 1


@pytest.mark.asyncio
async def test_a_rejecting_verifier_records_needs_more_work_or_rejected() -> None:
    from mission_control.application.programs.goal_directed import (
        InMemoryCompletionRecords,
        goal_completion_disposition,
    )

    documents = Documents()
    custody = Custody(captured('{"count":"bad"}', source_ref=OUTPUT))
    completions = InMemoryCompletionRecords()
    request = goal_request()
    result = await GoalDirectedOperationResultService(
        documents, artifacts=custody, completions=completions
    ).reconcile(request)
    verification = result.verification_result
    assert verification.decision == "rejected" and verification.progress_made
    decision = completions.decisions[
        ("tenant-1", request.claim.identity.iteration.run_id, verification.verification_id)
    ]
    assert decision.result_disposition == "needs_more_work"
    assert decision.reason_codes, "the validation's reason codes are recorded"
    assert goal_completion_disposition(replace(verification, progress_made=False)) == "rejected"
    assert goal_completion_disposition(replace(verification, decision="accepted")) == "accepted"


# --- Tracing Stage 3 (R1-F6): every non-admissible model answer is a typed observation -------


def _provider_result(structured_output):
    return OperationExecutionResult(
        binding_id="binding:verifier",
        semantic_attempt_key="attempt",
        status="completed",
        structured_output=structured_output,
        output_text="the model's final text",
        usage=RuntimeUsage(amounts={}),
    )


_EXECUTOR_BODY = {"disposition": "completed", "output_contract_ref": "fixture-output"}
_VERIFIER_BODY = {
    "decision": "accepted",
    "progress_made": True,
    "output_contract_ref": "fixture-output",
}


@pytest.mark.parametrize(
    ("case", "executor", "verifier"),
    [
        ("missing", None, None),
        ("not_validating", {"disposition": "done"}, {"decision": "maybe"}),
        (
            "wrong_contract_ref",
            {**_EXECUTOR_BODY, "output_contract_ref": "other-output"},
            {**_VERIFIER_BODY, "output_contract_ref": "other-output"},
        ),
    ],
)
def test_a_non_admissible_answer_settles_as_output_unparseable(case, executor, verifier):
    from mission_control.application.programs.goal_directed import OUTPUT_UNPARSEABLE

    service = GoalDirectedOperationResultService(Documents())
    request = goal_request()

    observed = service._executor_observation(_provider_result(executor), request)
    assert observed.disposition == "failed", case
    assert observed.irrecoverable_failure_ref.startswith(f"{OUTPUT_UNPARSEABLE}:sha256:")
    assert observed.output_contract_ref == "fixture-output"

    verdict = service._verifier_observation(_provider_result(verifier), request)
    assert (verdict.decision, verdict.progress_made) == ("rejected", False), case
    assert verdict.irrecoverable_failure_ref.startswith(f"{OUTPUT_UNPARSEABLE}:sha256:")
    assert verdict.output_contract_ref == "fixture-output"


def test_an_admissible_answer_is_parsed_and_each_failure_has_its_own_evidence():
    service = GoalDirectedOperationResultService(Documents())
    request = goal_request()
    assert (
        service._executor_observation(
            _provider_result(_EXECUTOR_BODY), request
        ).irrecoverable_failure_ref
        == ""
    )
    assert service._verifier_observation(_provider_result(_VERIFIER_BODY), request).decision == (
        "accepted"
    )
    wrong = {**_VERIFIER_BODY, "output_contract_ref": "other-output"}
    _parsed, missing = service._parsed(
        service._verification_adapter, _provider_result(None), ("fixture-output",)
    )
    _parsed, mismatch = service._parsed(
        service._verification_adapter, _provider_result(wrong), ("fixture-output",)
    )
    assert missing != mismatch


@pytest.mark.asyncio
async def test_a_verifier_naming_another_output_contract_rejects_instead_of_raising():
    """R1-F6: the mismatch used to raise `ValueError` (non-retryable `goal_completion_invalid`
    on the verifier); it now reconciles to a rejected verification without progress."""

    documents = Documents()
    custody = Custody(captured('{"count":1}', source_ref=OUTPUT))
    request = goal_request()
    observed = request.operation_result
    body = {
        **dict(observed.result),
        "structured_output": {**_VERIFIER_BODY, "output_contract_ref": "x"},
    }
    request = request.model_copy(
        update={"operation_result": observed.model_copy(update={"result": body})}
    )
    result = await GoalDirectedOperationResultService(documents, artifacts=custody).reconcile(
        request
    )
    assert result.verification_result.decision == "rejected"
    assert not result.verification_result.progress_made

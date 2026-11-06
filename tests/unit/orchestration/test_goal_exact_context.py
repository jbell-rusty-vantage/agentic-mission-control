"""Exact scoped producer custody and complete non-authoritative repair feedback."""

from dataclasses import asdict, replace
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest

from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.programs.goal_context import resolve_goal_context
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.packet import ContextTrust, ExpandMode
from mission_control.domain.execution.contracts import PromptTrustClass
from tests.unit.orchestration.test_rrm_016_goal_directed_settlement import (
    _claim,
    _composition,
    _preparation,
)
from tests.unit.orchestration.test_wp_bp_020_goal_directed import _execution, _verification


def redigest(verification, **changes):
    updated = replace(verification, **changes)
    payload = asdict(updated)
    payload.pop("verification_digest")
    return replace(updated, verification_digest=sha256_digest(payload))


async def fixture(*, repair=True):
    composition, run_id = await _composition()
    claim = await _claim(run_id)
    initial = _preparation(run_id, claim, "executor", 2, 0)
    dispatch = await composition.family.execute_iteration(initial)
    binding = bind_operation_execution_request(dispatch.workflow_request.operation)
    source = replace(
        _execution(claim),
        operation_identity=binding.semantic_attempt_key,
        operation_binding_ref=binding.binding_id,
        session_id=binding.session_id,
        workspace_id=binding.workspace.workspace_id,
    )
    feedback = redigest(
        _verification(claim),
        findings=("Repair the unsupported claim. é " * 2500,),
        decision="repair_required",
    )
    if repair:
        request = initial.model_copy(
            update={
                "goal_iteration": 2,
                "subject_execution": source,
                "verification_feedback": feedback,
            }
        )
    else:
        request = _preparation(run_id, claim, "verifier", 3, 0, source).model_copy(
            update={"subject_execution": source}
        )
    retained_execution = {
        "goal_revision_id": source.identity.iteration.goal_revision_id,
        "result": source.to_payload(),
    }
    retained_feedback = {
        "goal_revision_id": source.identity.iteration.goal_revision_id,
        "verification": asdict(feedback),
    }
    documents = AsyncMock()
    documents.load_iteration.side_effect = lambda scope, run, key: (
        retained_execution
        if (scope, run, key) == (initial.request_scope, run_id, source.identity.semantic_key)
        else None
    )
    documents.load_verification.side_effect = lambda scope, run, key: (
        retained_feedback
        if (scope, run, key) == (initial.request_scope, run_id, feedback.verification_id)
        else None
    )
    bindings = AsyncMock()
    bindings.get_binding_by_id.return_value = binding
    return (
        request,
        source,
        feedback,
        binding,
        documents,
        bindings,
        retained_execution,
        retained_feedback,
    )


@pytest.mark.asyncio
async def test_complete_scoped_feedback_is_untrusted_and_mandatory_exact_bytes():
    request, source, feedback, binding, docs, bindings, *_ = await fixture()
    resolved = await resolve_goal_context(request, docs, bindings)
    assert resolved.subject.operation_ref == binding.operation_id
    assert resolved.subject.operation_attempt == binding.operation_attempt
    assert resolved.subject.execution_generation == binding.lane_dispatch.execution_generation
    assert resolved.feedback.trust_class is PromptTrustClass.UNTRUSTED_CONTENT
    assert feedback.findings[0] in resolved.feedback.content
    assert source.identity.iteration.run_id in resolved.feedback.content
    (candidate,) = resolved.candidates()
    assert candidate.mandatory and candidate.expand is ExpandMode.INLINE
    assert candidate.trust is ContextTrust.UNTRUSTED_CONTENT
    assert candidate.text == resolved.feedback.content
    data = candidate.text.encode("utf-8")
    assert candidate.bytes == len(data) > 50_000
    assert candidate.content_digest == "sha256:" + sha256(data).hexdigest()
    docs.load_iteration.assert_awaited_once_with(
        request.request_scope, request.run_id, source.identity.semantic_key
    )
    docs.load_verification.assert_awaited_once_with(
        request.request_scope, request.run_id, feedback.verification_id
    )
    bindings.get_binding_by_id.assert_awaited_once_with(
        source.operation_binding_ref, request_scope=request.request_scope
    )


@pytest.mark.asyncio
async def test_current_verifier_gets_exact_producer_without_repair_feedback():
    request, _, _, binding, docs, bindings, *_ = await fixture(repair=False)
    resolved = await resolve_goal_context(request, docs, bindings)
    assert resolved.subject.operation_ref == binding.operation_id
    assert resolved.feedback is None and resolved.candidates() == ()
    docs.load_verification.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["stale_iteration", "wrong_scope", "wrong_run", "wrong_revision"]
)
async def test_subject_cannot_cross_iteration_scope_run_or_revision(change):
    request, _, _, _, docs, bindings, *_ = await fixture()
    updates = {
        "stale_iteration": {"goal_iteration": 3},
        "wrong_scope": {"request_scope": "other-tenant"},
        "wrong_run": {"run_id": "sibling-run"},
        "wrong_revision": {"goal_revision_id": "sibling-revision"},
    }[change]
    with pytest.raises(ValueError, match="Goal subject"):
        await resolve_goal_context(request.model_copy(update=updates), docs, bindings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "operation",
        "session",
        "workspace",
        "configuration",
        "missing",
        "role_location",
        "agent_location",
        "generation_location",
    ],
)
async def test_exact_producer_binding_required(change):
    request, _, _, binding, docs, bindings, *_ = await fixture()
    changed = {
        "scope": {"request_scope": "other-scope"},
        "operation": {"operation_id": "sibling"},
        "session": {"session_id": "sibling-session"},
        "workspace": {
            "workspace": binding.workspace.model_copy(update={"workspace_id": "sibling"})
        },
        "configuration": {"effective_configuration_digest": "sha256:" + "0" * 64},
    }
    location = binding.runtime_unit.location
    location_changes = {
        "role_location": {"operation_role": "verifier"},
        "agent_location": {"agent_run": location.agent_run + 1},
        "generation_location": {"session_generation": location.session_generation + 1},
    }
    if change in location_changes:
        changed[change] = {
            "runtime_unit": binding.runtime_unit.model_copy(
                update={"location": location.model_copy(update=location_changes[change])}
            )
        }
    bindings.get_binding_by_id.return_value = (
        None if change == "missing" else binding.model_copy(update=changed[change])
    )
    with pytest.raises(ValueError, match="Goal subject"):
        await resolve_goal_context(request, docs, bindings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["execution", "execution_revision", "feedback", "feedback_digest", "feedback_revision"],
)
async def test_saved_execution_and_verification_must_match_exactly(change):
    request, source, feedback, _, docs, bindings, execution, retained = await fixture()
    if change == "execution":
        execution["result"] = replace(source, output_refs=("sibling-output",)).to_payload()
    elif change == "execution_revision":
        execution["goal_revision_id"] = "sibling-revision"
    elif change == "feedback":
        retained["verification"] = asdict(redigest(feedback, findings=("stale findings",)))
    elif change == "feedback_revision":
        retained["goal_revision_id"] = "sibling-revision"
    else:
        request = request.model_copy(
            update={
                "verification_feedback": replace(feedback, verification_digest="sha256:" + "0" * 64)
            }
        )
    with pytest.raises(ValueError, match="Goal (subject|feedback)"):
        await resolve_goal_context(request, docs, bindings)


@pytest.mark.asyncio
async def test_first_executor_without_subject_keeps_backward_shape_and_reads_nothing():
    _composition_value, run_id = await _composition()
    claim = await _claim(run_id)
    request = _preparation(run_id, claim, "executor", 2, 0)
    assert "subject_execution" not in request.model_dump()
    assert "verification_feedback" not in request.model_dump()
    docs, bindings = AsyncMock(), AsyncMock()
    resolved = await resolve_goal_context(request, docs, bindings)
    assert resolved.subject is None and resolved.feedback is None and resolved.candidates() == ()
    docs.load_iteration.assert_not_awaited()
    docs.load_verification.assert_not_awaited()
    bindings.get_binding_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_oversized_feedback_is_refused_instead_of_silently_truncated():
    request, _, feedback, _, docs, bindings, _, retained = await fixture()
    oversized = redigest(feedback, findings=("Full actionable finding é " * 5000,))
    retained["verification"] = asdict(oversized)
    request = request.model_copy(update={"verification_feedback": oversized})
    with pytest.raises(ValueError, match="100000"):
        await resolve_goal_context(request, docs, bindings)


@pytest.mark.asyncio
async def test_requested_source_payload_cannot_replace_persisted_result():
    request, source, _, _, docs, bindings, *_ = await fixture()
    tampered = replace(source, output_refs=("unrecorded-sibling-result",))
    request = request.model_copy(update={"subject_execution": tampered})
    with pytest.raises(ValueError, match="scoped immutable execution record"):
        await resolve_goal_context(request, docs, bindings)


def _failed(source, retained, request):
    failed = replace(source, disposition="failed")
    retained["result"] = failed.to_payload()
    return failed, request.model_copy(update={"subject_execution": failed})


@pytest.mark.asyncio
async def test_verifier_judges_a_failed_executor_of_its_own_iteration():
    # W1 D36 (run af51473c): an unparseable executor settles `failed` and the verifier must still
    # see it (`_executor_observation`); refusing it failed the whole family workflow.
    request, source, _, binding, docs, bindings, retained, _ = await fixture(repair=False)
    _, request = _failed(source, retained, request)
    resolved = await resolve_goal_context(request, docs, bindings)
    assert resolved.subject.operation_ref == binding.operation_id


@pytest.mark.asyncio
async def test_repair_executor_still_needs_a_completed_predecessor():
    request, source, _, _, docs, bindings, retained, _ = await fixture()
    _, request = _failed(source, retained, request)
    with pytest.raises(ValueError, match="exact completed producing iteration"):
        await resolve_goal_context(request, docs, bindings)

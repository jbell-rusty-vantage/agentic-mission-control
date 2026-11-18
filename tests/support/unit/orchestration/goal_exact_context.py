"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_goal_exact_context.py.
"""

from dataclasses import asdict, replace
from unittest.mock import AsyncMock

from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.domain.authoring.canonical import sha256_digest
from tests.support.unit.orchestration.goal_loop_operation_settlement import (
    _claim,
    _composition,
    _preparation,
)
from tests.support.unit.orchestration.goal_loop_rules import _execution, _verification


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

"""W1 (OVE-169) GoalDirected runtime defects found by the first real model runs.

D10: the run-control 8192-character string bound applied to a context packet segment inside
the prepared dispatch only when the family *decoded* it (construction never walked a nested
model), so a real 8,524-character packet failed every workflow task forever. The embedded
operation request and result now validate under their own contracts on both paths, and any
dispatch that still could not decode is refused typed in the activity.

D14: a verifier unit that failed (its required subject report was never delivered) returned no
typed result and the family workflow crashed. It now reconciles to a typed, recorded rejection
whose irrecoverable failure makes the convergence policy terminate the run visibly.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from temporalio import workflow
from temporalio.exceptions import ApplicationError

from mission_control.adapters.temporal.activities.goal_directed import GoalDirectedActivities
from mission_control.adapters.temporal.workflows.goal_directed import GoalDirectedWorkflow
from mission_control.adapters.temporal.workflows.payload_contracts import (
    PAYLOAD_BOUND_VIOLATION,
    decode_contract,
)
from mission_control.adapters.temporal.workflows.stagegraph import StageGraphWorkflow
from mission_control.application.context.materialization import ContextDeliveryBlocked
from mission_control.application.programs.goal_directed import _undelivered_verification
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    OperationExecutionResult,
    OperationWorkflowResult,
    PromptSegment,
    PromptTrustClass,
)
from mission_control.domain.programs.goal_directed import GoalDirectedInterpreter
from mission_control.domain.programs.goal_directed_runtime import (
    GOAL_DISPATCH_INVALID,
    GOAL_RECONCILIATION_OVERSIZE,
    MAX_RECONCILIATION_REQUEST_BYTES,
    GoalOperationDispatch,
    GoalOperationReconciliationRequest,
    GoalOperationReconciliationResult,
    reconciliation_payload_bytes,
)
from tests.fixtures.checkpoint_lineage import activity_attempt
from tests.fixtures.goal_directed_journaled import SCOPE, goal_blueprint, goal_run_input
from tests.unit.orchestration.test_rrm_016_goal_directed_settlement import (
    _claim,
    _composition,
    _preparation,
    _reconciliation,
)

# The real W1 dry-run context packet was 8,524 characters (W1-EVIDENCE session 3, dry 2).
PACKET_CHARS = 8_524


def _long_segment(chars: int = PACKET_CHARS) -> PromptSegment:
    content = ("mission context packet line\n" * (chars // 28 + 1))[:chars]
    return PromptSegment(
        source_ref="context-packet:w1-d10",
        source_revision=1,
        trust_class=PromptTrustClass.ADMITTED_INPUT,
        content=content,
        rendered_digest=sha256_digest(content),
    )


def _with_long_packet(dispatch: GoalOperationDispatch) -> GoalOperationDispatch:
    operation = dispatch.workflow_request.operation
    request = dispatch.workflow_request.model_copy(
        update={
            "operation": operation.model_copy(
                update={"prompt_segments": (*operation.prompt_segments, _long_segment())}
            )
        }
    )
    # Validated as the activity builds it: nested contracts are instances here.
    return GoalOperationDispatch(
        workflow_request=request,
        operation_binding_ref=dispatch.operation_binding_ref,
        operation_request_digest=dispatch.operation_request_digest,
        resulting_run_version=dispatch.resulting_run_version,
        resulting_family_version=dispatch.resulting_family_version,
    )


async def _executor_dispatch() -> tuple[Any, str, Any, GoalOperationDispatch]:
    composition, run_id = await _composition()
    claim = await _claim(run_id)
    run = await composition.run_control.get_run(SCOPE, run_id)
    dispatch = await composition.family.execute_iteration(
        _preparation(run_id, claim, "executor", run.version, 0)
    )
    return composition, run_id, claim, dispatch


@pytest.mark.asyncio
async def test_d10_a_realistic_context_packet_decodes_as_the_family_reads_it() -> None:
    *_, claim, dispatch = await _executor_dispatch()
    long_dispatch = _with_long_packet(dispatch)

    # What the family workflow does with the activity result: decode it from its JSON.
    decoded = GoalOperationDispatch.model_validate_json(long_dispatch.model_dump_json())
    assert decoded == long_dispatch
    assert decoded.workflow_request.operation.prompt_segments[-1].content == (
        _long_segment().content
    )
    # The sealed lane binding travels base64 inside the same request and decodes too.
    assert decoded.workflow_request.operation.lane_binding is not None

    # The reconciliation request carries the same request and a long provider answer.
    answer = OperationExecutionResult(
        binding_id=dispatch.operation_binding_ref,
        semantic_attempt_key=dispatch.workflow_request.semantic_attempt_id,
        status="completed",
        output_text="x" * 20_000,
    )
    reconciliation = _reconciliation(claim, "executor", long_dispatch, answer)
    assert (
        GoalOperationReconciliationRequest.model_validate_json(reconciliation.model_dump_json())
        == reconciliation
    )


@pytest.mark.asyncio
async def test_d10_run_control_fields_keep_their_8192_character_bound() -> None:
    *_, dispatch = await _executor_dispatch()
    payload = dispatch.model_dump(mode="json")
    payload["operation_binding_ref"] = "b" * 8_193
    with pytest.raises(ValidationError, match="8192"):
        GoalOperationDispatch.model_validate(payload)
    # The embedded request still enforces its own segment ceiling.
    oversized = dispatch.model_dump(mode="json")
    content = "y" * 100_001
    segment = {
        **_long_segment().model_dump(mode="json"),
        "content": content,
        "rendered_digest": sha256_digest(content),
    }
    oversized["workflow_request"]["operation"]["prompt_segments"].append(segment)
    with pytest.raises(ValidationError, match="at most 100000 characters"):
        GoalOperationDispatch.model_validate(oversized)


class _UndecodableDispatchPreparation:
    """A preparation whose result the family could not decode (built without validation)."""

    def __init__(self, dispatch: GoalOperationDispatch) -> None:
        self._dispatch = dispatch

    async def prepare(self, request: Any) -> GoalOperationDispatch:
        return GoalOperationDispatch.model_construct(
            **{**dict(self._dispatch), "operation_binding_ref": "b" * 9_000}
        )


@pytest.mark.asyncio
async def test_d10_an_undecodable_dispatch_is_refused_typed_and_never_retried() -> None:
    composition, run_id, claim, dispatch = await _executor_dispatch()
    run = await composition.run_control.get_run(SCOPE, run_id)
    activities = GoalDirectedActivities(
        operations=_UndecodableDispatchPreparation(dispatch),  # type: ignore[arg-type]
        results=composition.family._results,
        lifecycle=composition.family._lifecycle,
    )
    with pytest.raises(ApplicationError) as refused:
        await activities.execute_iteration(_preparation(run_id, claim, "executor", run.version, 0))
    assert refused.value.type == GOAL_DISPATCH_INVALID
    assert refused.value.non_retryable
    assert "8192" in refused.value.message
    assert "bbbb" not in refused.value.message  # contract messages only, never input values


def test_d10_only_a_payload_bound_violation_fails_a_decode_site_terminally() -> None:
    oversized = {
        "schema_version": "belllabs.goal-operation-dispatch.v1",
        "operation_binding_ref": "b" * 8_193,
    }
    with pytest.raises(ApplicationError) as refused:
        decode_contract(GoalOperationDispatch, oversized, site="goaldirected.prepare_executor")
    assert refused.value.type == PAYLOAD_BOUND_VIOLATION and refused.value.non_retryable
    # Any other contract error (for example rolling-deploy skew: a field this worker does not
    # know) stays a plain validation error, so the workflow task retries until a deploy fixes it.
    with pytest.raises(ValidationError):
        decode_contract(
            GoalOperationDispatch,
            {"schema_version": "belllabs.goal-operation-dispatch.v1", "unknown": 1},
            site="goaldirected.prepare_executor",
        )
    # The families declare no blanket failure type: workflow-code errors stay retryable.
    for family in (GoalDirectedWorkflow, StageGraphWorkflow):
        assert not workflow._Definition.must_from_class(family).failure_exception_types


@pytest.mark.asyncio
async def test_s1_embedded_payloads_keep_structural_and_secret_name_scans() -> None:
    *_, claim, dispatch = await _executor_dispatch()
    payload = dispatch.model_dump(mode="json")
    payload["workflow_request"]["operation"]["metadata_probe"] = {"api_key": "x"}
    with pytest.raises(ValidationError, match="raw secrets"):
        GoalOperationDispatch.model_validate(payload)
    answer = OperationExecutionResult(
        binding_id=dispatch.operation_binding_ref,
        semantic_attempt_key=dispatch.workflow_request.semantic_attempt_id,
        status="completed",
    )
    base = _reconciliation(claim, "executor", dispatch, answer).model_dump(mode="json")
    secret = {**base["operation_result"], "result": {"authorization": "Bearer x"}}
    with pytest.raises(ValidationError, match="raw secrets"):
        GoalOperationReconciliationRequest.model_validate({**base, "operation_result": secret})
    deep: dict[str, Any] = {}
    cursor = deep
    for _ in range(40):
        cursor["n"] = {}
        cursor = cursor["n"]
    nested = {**base["operation_result"], "result": deep}
    with pytest.raises(ValidationError, match="structural limits"):
        GoalOperationReconciliationRequest.model_validate({**base, "operation_result": nested})
    # Built (nested instances) or decoded (dicts): the same scan refuses the same bytes.
    with pytest.raises(ValidationError, match="raw secrets"):
        GoalOperationReconciliationRequest(
            **{
                **_reconciliation(claim, "executor", dispatch, answer).__dict__,
                "operation_result": OperationWorkflowResult.model_validate(secret),
            }
        )


@pytest.mark.asyncio
async def test_b1_an_oversized_reconciliation_request_is_refused_typed() -> None:
    composition, _run_id, claim, dispatch = await _executor_dispatch()
    answer = OperationExecutionResult(
        binding_id=dispatch.operation_binding_ref,
        semantic_attempt_key=dispatch.workflow_request.semantic_attempt_id,
        status="completed",
        output_text="x" * 1_000_000,
    )
    near = _reconciliation(claim, "executor", _with_long_packet(dispatch), answer)
    assert reconciliation_payload_bytes(near) < MAX_RECONCILIATION_REQUEST_BYTES
    big = answer.model_copy(update={"output_text": "x" * MAX_RECONCILIATION_REQUEST_BYTES})
    oversized = _reconciliation(claim, "executor", dispatch, big)
    assert reconciliation_payload_bytes(oversized) > MAX_RECONCILIATION_REQUEST_BYTES
    with pytest.raises(ApplicationError) as refused:
        await composition.family.prepare_handoff(oversized)
    assert refused.value.type == GOAL_RECONCILIATION_OVERSIZE and refused.value.non_retryable


def _verifier_failure_request(
    claim: Any,
    dispatch: GoalOperationDispatch,
    result: OperationExecutionResult,
    executor: Any,
) -> GoalOperationReconciliationRequest:
    request = _reconciliation(claim, "verifier", dispatch, result, executor)
    return request.model_copy(
        update={
            "operation_result": OperationWorkflowResult(
                semantic_attempt_id=dispatch.workflow_request.semantic_attempt_id,
                execution_generation=1,
                disposition="failed",
                result=result.model_dump(mode="json"),
                message_cursor=0,
            )
        }
    )


@pytest.mark.asyncio
async def test_d14_a_failed_verifier_reconciles_to_a_recorded_typed_rejection() -> None:
    composition, run_id = await _composition()
    claim = await _claim(run_id)
    run = await composition.run_control.get_run(SCOPE, run_id)
    executor_dispatch = await composition.family.execute_iteration(
        _preparation(run_id, claim, "executor", run.version, 0)
    )
    executor_result = await composition.service.execute(
        executor_dispatch.workflow_request.operation,
        activity_attempt(workflow_id=executor_dispatch.workflow_request.workflow_id),
    )
    executor = await composition.family.prepare_handoff(
        _reconciliation(claim, "executor", executor_dispatch, executor_result)
    )
    assert executor.execution_result is not None and executor.settlement is not None
    verifier_dispatch = await composition.family.verify_iteration(
        _preparation(
            run_id,
            claim,
            "verifier",
            executor.settlement.settled_run_version,
            executor_dispatch.resulting_family_version,
            executor.execution_result,
        )
    )
    # The verifier's first model call fails: the governed boundary settles the unit `failed`.
    composition.model.fail_on(
        len(composition.model.calls) + 1,
        ContextDeliveryBlocked("SOURCE_NOT_ACCEPTED:subject-root-report"),
    )
    verifier_result = await composition.service.execute(
        verifier_dispatch.workflow_request.operation,
        activity_attempt(workflow_id=verifier_dispatch.workflow_request.workflow_id),
    )
    assert verifier_result.status == "failed", verifier_result

    # S2: a transient failure (`runtime_failed`) is never turned into a judged rejection; the
    # unit's settlement is consumed and the family fails typed (the root terminalizes, D15).
    transient = await composition.family.prepare_handoff(
        _verifier_failure_request(
            claim,
            verifier_dispatch,
            verifier_result.model_copy(update={"failure_code": "runtime_failed"}),
            executor.execution_result,
        )
    )
    assert transient.verification_result is None and transient.settlement is not None
    # The boundary records a blocked delivery as `context_delivery_blocked` with its
    # host-generated reason (operation_execution.py, OperationSettlement failure_code).
    blocked = verifier_result.model_copy(
        update={
            "failure_code": "context_delivery_blocked",
            "failure_message": "context_delivery_blocked: SOURCE_NOT_ACCEPTED:subject-root-report",
        }
    )
    reconciled = await composition.family.prepare_handoff(
        _verifier_failure_request(claim, verifier_dispatch, blocked, executor.execution_result)
    )
    # What the family decodes: the typed rejection survives the JSON round trip.
    reconciled = GoalOperationReconciliationResult.model_validate_json(reconciled.model_dump_json())
    verification = reconciled.verification_result
    assert reconciled.operation_disposition == "failed"
    assert reconciled.settlement is not None
    assert reconciled.settlement.reservation_id == f"{claim.reservation_id}:verifier"
    assert verification is not None
    assert verification.decision == "rejected" and not verification.progress_made
    assert verification.irrecoverable_failure_ref.startswith("verifier_unit_failed:")
    blueprint = goal_blueprint()
    # Without a completion blueprint no obligation refs are invented.
    assert verification.unmet_obligations == ()
    assert verification.output_contract_ref == executor.execution_result.output_contract_ref
    assert verification.actual_usage == reconciled.settlement.usage
    # The rejection is a recorded verification like any other (visible in inspection).
    assert reconciled.detail_ref.startswith("goal-verification:")
    # Only a failed verifier's irrecoverable rejection may ride with a non-completed unit.
    for disposition in ("cancelled",):
        payload = reconciled.model_dump(mode="json")
        payload["operation_disposition"] = disposition
        with pytest.raises(ValidationError, match="failed verifier"):
            GoalOperationReconciliationResult.model_validate(payload)
    accepted = reconciled.model_dump(mode="json")
    accepted["verification_result"]["irrecoverable_failure_ref"] = ""
    with pytest.raises(ValidationError, match="failed verifier"):
        GoalOperationReconciliationResult.model_validate(accepted)

    # The convergence policy terminates the run on the irrecoverable failure.
    interpreter = GoalDirectedInterpreter(blueprint)
    state = interpreter.initial_state(goal_run_input(run_id, blueprint, baseline={}))
    claimed, _ = interpreter.claim_execution(state)
    projected = interpreter.apply_execution_result(claimed, executor.execution_result)
    stopped = interpreter.apply_verification(projected, verification)
    assert stopped.status == "stopping"
    assert stopped.terminalization_proposal is not None
    assert stopped.terminalization_proposal.proposed_outcome != "complete"


def test_d14_the_undelivered_reason_is_host_typed_and_provider_text_never_recorded() -> None:
    request = type(
        "Request",
        (),
        {
            "completion_blueprint": goal_blueprint(),
            "required_output_contract_refs": ("report",),
            "executor_result": None,
        },
    )()
    blocked = OperationExecutionResult(
        binding_id="binding",
        semantic_attempt_key="attempt",
        status="failed",
        failure_code="context_delivery_blocked",
        failure_message="context_delivery_blocked: SOURCE_NOT_ACCEPTED:subject-root-report",
    )
    observation = _undelivered_verification(blocked, request)
    assert observation.irrecoverable_failure_ref == (
        "verifier_unit_failed:context_delivery_blocked: SOURCE_NOT_ACCEPTED:subject-root-report"
    )
    assert observation.blocker_class == "context_delivery_blocked"
    assert set(observation.unmet_obligations) == set(goal_blueprint().required_obligation_refs)
    unsupported = blocked.model_copy(
        update={
            "failure_code": "unsupported_runtime_policy",
            "failure_message": "provider said: secret",
        }
    )
    other = _undelivered_verification(unsupported, request)
    assert other is not None
    assert other.irrecoverable_failure_ref == "verifier_unit_failed:unsupported_runtime_policy"
    assert "secret" not in repr(other)
    for transient in ("runtime_failed", "preparation_failed", "budget_exceeded", None):
        changed = blocked.model_copy(update={"failure_code": transient})
        assert _undelivered_verification(changed, request) is None
    # Two required contracts and no executor contract to name: no arbitrary pick.
    ambiguous = type(request)()
    ambiguous.required_output_contract_refs = ("a", "b")
    assert _undelivered_verification(blocked, ambiguous) is None


def test_s2_every_boundary_failure_code_is_classified() -> None:
    """A new failure code the operation boundary records must be classified as deterministic
    (a typed rejection) or not judged (the family's typed failure); it cannot fall through."""

    import ast
    import inspect

    from mission_control.application.execution.operations import operation_execution
    from mission_control.application.programs.goal_directed import (
        DETERMINISTIC_VERIFIER_FAILURES,
        NON_JUDGED_VERIFIER_FAILURES,
    )

    tree = ast.parse(inspect.getsource(operation_execution))
    codes = {
        node.value
        for keyword in ast.walk(tree)
        if isinstance(keyword, ast.keyword) and keyword.arg == "failure_code"
        for node in ast.walk(keyword.value)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    codes |= {ContextDeliveryBlocked.code}  # `failure_code=ContextDeliveryBlocked.code`
    codes |= {"fork_lineage_missing", "incompatible_restore"}  # `failure_code=error.code`
    assert not DETERMINISTIC_VERIFIER_FAILURES & NON_JUDGED_VERIFIER_FAILURES
    assert codes <= DETERMINISTIC_VERIFIER_FAILURES | NON_JUDGED_VERIFIER_FAILURES, (
        codes - DETERMINISTIC_VERIFIER_FAILURES - NON_JUDGED_VERIFIER_FAILURES
    )


@pytest.mark.asyncio
async def test_d40_a_failed_executor_reconciles_to_a_typed_failed_execution() -> None:
    """W1 D40: a failed executor unit is a typed, recorded failed execution the verifier and
    the convergence policy see, never `goal_operation_unreported` (which failed the family
    before either could). A `transient_transport` failure (the call never reached the
    provider and its in-turn retry was exhausted) is recoverable by a later iteration; every
    other failure code is irrecoverable and the policy terminates the run visibly."""

    composition, run_id = await _composition()
    claim = await _claim(run_id)
    run = await composition.run_control.get_run(SCOPE, run_id)
    dispatch = await composition.family.execute_iteration(
        _preparation(run_id, claim, "executor", run.version, 0)
    )
    composition.model.fail_on(len(composition.model.calls) + 1, ValueError("provider failed"))
    failed = await composition.service.execute(
        dispatch.workflow_request.operation,
        activity_attempt(workflow_id=dispatch.workflow_request.workflow_id),
    )
    assert failed.status == "failed" and failed.failure_code == "runtime_failed", failed

    def request(result: OperationExecutionResult) -> GoalOperationReconciliationRequest:
        return _reconciliation(claim, "executor", dispatch, result).model_copy(
            update={
                "operation_result": OperationWorkflowResult(
                    semantic_attempt_id=dispatch.workflow_request.semantic_attempt_id,
                    execution_generation=1,
                    disposition="failed",
                    result=result.model_dump(mode="json"),
                    message_cursor=0,
                )
            }
        )

    blueprint = goal_blueprint()
    interpreter = GoalDirectedInterpreter(blueprint)
    for code, irrecoverable in (("transient_transport", ""), ("runtime_failed", "x")):
        reconciled = await composition.family.prepare_handoff(
            request(failed.model_copy(update={"failure_code": code}))
        )
        reconciled = GoalOperationReconciliationResult.model_validate_json(
            reconciled.model_dump_json()
        )
        execution = reconciled.execution_result
        assert reconciled.operation_disposition == "failed"
        assert reconciled.settlement is not None and execution is not None
        assert execution.disposition == "failed" and not execution.completion_claim
        assert execution.output_refs == ()
        assert execution.blocker_class == code
        assert execution.actual_usage == reconciled.settlement.usage
        assert bool(execution.irrecoverable_failure_ref) == bool(irrecoverable)
        if irrecoverable:
            assert execution.irrecoverable_failure_ref == f"executor_unit_failed:{code}"
        # Recorded like any iteration (inspection reads its failure reference).
        assert reconciled.detail_ref.startswith("goal-iteration:")
        # The family can project it and wait for the verifier's judgment.
        state = interpreter.initial_state(goal_run_input(run_id, blueprint, baseline={}))
        claimed, _ = interpreter.claim_execution(state)
        projected = interpreter.apply_execution_result(claimed, execution)
        assert projected.status == "awaiting_verification"

    # A cancelled executor still carries no role result (the cancellation saga owns it).
    cancelled = request(failed.model_copy(update={"status": "cancelled"}))
    cancelled = cancelled.model_copy(
        update={
            "operation_result": cancelled.operation_result.model_copy(
                update={"disposition": "cancelled"}
            )
        }
    )
    result = await composition.family.prepare_handoff(cancelled)
    assert result.execution_result is None and result.operation_disposition == "cancelled"

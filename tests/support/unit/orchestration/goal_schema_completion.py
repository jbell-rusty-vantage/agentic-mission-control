"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_goal_schema_completion.py.
"""

from dataclasses import replace
from datetime import UTC, datetime

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageOutputSlot
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.execution.contracts import (
    OperationExecutionResult,
    OperationWorkflowRequest,
    OperationWorkflowResult,
    RuntimeUsage,
)
from mission_control.domain.programs.completion import OutputSchemaBinding, SchemaCriterion
from mission_control.domain.programs.contracts import GoalExecutionResult
from mission_control.domain.programs.goal_directed import GoalDirectedInterpreter
from mission_control.domain.programs.goal_directed_runtime import (
    GoalOperationPreparationRequest,
    GoalOperationReconciliationRequest,
)
from tests.support.integration.temporal.wp_bp_020_temporal import _operation, _run_input
from tests.support.unit.orchestration.artifact_schema_validation import SCHEMA, captured

OUTPUT = "workspace-candidate://goal-output"
SUMMARY = "workspace-candidate://goal-summary"


def goal_request(scope="tenant-1", refs=(OUTPUT,)):
    run = _run_input()
    _, claim = GoalDirectedInterpreter(GENERIC_GOAL_DIRECTED).claim_execution(
        GoalDirectedInterpreter(GENERIC_GOAL_DIRECTED).initial_state(run)
    )
    execution = GoalExecutionResult(
        identity=claim.identity,
        disposition="completed",
        operation_identity="executor",
        operation_binding_ref="binding:executor",
        session_id=claim.session_id,
        workspace_id=claim.workspace_namespace,
        writable_paths=("/goal/executor/work",),
        output_refs=refs,
    )
    prep = GoalOperationPreparationRequest(
        request_scope=scope,
        run_id=run.run_id,
        effective_configuration_digest=run.effective_configuration_digest,
        semantic_input_binding_ref=run.semantic_input_binding_ref,
        goal_revision_id=run.initial_revision.revision_id,
        goal_revision_digest=run.initial_revision.canonical_digest,
        goal_revision=run.initial_revision,
        goal_iteration=1,
        operation_role="verifier",
        operation_attempt=1,
        execution_generation=1,
        expected_run_version=2,
        expected_family_version=1,
        reservation_id="reservation:verifier",
        reservation={"goal.iterations": 1},
        session_id=claim.session_id + ":verifier",
        workspace_id=claim.workspace_namespace + ":verifier",
        read_workspace_id=execution.workspace_id,
        verifier_input_refs=refs,
        decided_at=datetime.now(UTC),
    )
    operation = _operation(prep)
    work = OperationWorkflowRequest(
        semantic_attempt_id=operation.identity.semantic_key,
        operation_kind="bound_operation",
        operation=operation,
    )
    body = {
        "decision": "accepted",
        "progress_made": True,
        "accepted_obligation_refs": ["fixture-obligation"],
        "output_contract_ref": "fixture-output",
    }
    observed = OperationWorkflowResult(
        semantic_attempt_id=work.semantic_attempt_id,
        execution_generation=1,
        disposition="completed",
        message_cursor=0,
        effect_frontier=(),
        result=OperationExecutionResult(
            binding_id="binding:verifier",
            semantic_attempt_key=work.semantic_attempt_id,
            status="completed",
            structured_output=body,
            usage=RuntimeUsage(amounts={}),
        ).model_dump(mode="json"),
    )
    schema = OutputSchemaBinding(
        schema_ref="schema:report@1",
        source_digest="sha256:" + "a" * 64,
        schema_digest=sha256_digest(SCHEMA),
        json_schema=SCHEMA,
    )
    blueprint = GENERIC_GOAL_DIRECTED.model_copy(
        update={
            "output_slots": (
                StageOutputSlot(
                    output_slot_id="report",
                    output_contract_ref=schema.schema_ref,
                    required=True,
                    validation_schema=schema,
                ),
            ),
            "schema_criteria": (
                SchemaCriterion(
                    criterion_key="valid-report",
                    obligation_ref="fixture-obligation",
                    schema_ref=schema.schema_ref,
                    output_slots=("report",),
                ),
            ),
        }
    )
    policy = blueprint.verifier_policy
    return GoalOperationReconciliationRequest(
        request_scope=scope,
        goal_revision_id=run.initial_revision.revision_id,
        operation_role="verifier",
        operation_binding_ref="binding:verifier",
        required_output_contract_refs=("fixture-output",),
        operation_request=work,
        claim=claim,
        executor_result=execution,
        operation_result=observed,
        remaining_iterations=0,
        verifier_policy_binding_ref=policy.binding_ref,
        verifier_rubric_ref=policy.rubric_ref,
        verifier_rubric_version=policy.rubric_version,
        acceptance_contract_ref=blueprint.acceptance_contract,
        acceptance_version=policy.acceptance_version,
        recorded_at=datetime.now(UTC),
        completion_blueprint=blueprint,
    )


def multi_goal_request(scope="tenant-1", *, optional=False):
    request = goal_request(scope, (OUTPUT, SUMMARY))
    schema = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
    }
    binding = OutputSchemaBinding(
        schema_ref="schema:summary@1",
        source_digest="sha256:" + "b" * 64,
        schema_digest=sha256_digest(schema),
        json_schema=schema,
    )
    blueprint = request.completion_blueprint
    slot = StageOutputSlot(
        output_slot_id="summary",
        output_contract_ref=binding.schema_ref,
        required=not optional,
        validation_schema=binding,
    )
    blueprint = blueprint.model_copy(update={"output_slots": (*blueprint.output_slots, slot)})
    return request.model_copy(
        update={
            "completion_blueprint": blueprint,
            "executor_result": replace(
                request.executor_result,
                output_bindings={
                    "report": (OUTPUT,),
                    "summary": (SUMMARY,),
                },
            ),
        }
    )


class ScopedCustody:
    def __init__(self, scope="tenant-1"):
        self.contents = {
            (scope, OUTPUT): captured(source_ref=OUTPUT),
            (scope, SUMMARY): captured('{"summary":"verified"}', source_ref=SUMMARY),
        }
        self.calls = []

    async def capture(self, source_ref, *, request_scope, max_text_bytes):
        self.calls.append((request_scope, source_ref))
        return self.contents.get((request_scope, source_ref))

"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_wp_bp_020_temporal.py.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from temporalio import activity

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    ExactDefinitionRef,
    GoalDirectedBlueprint,
)
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.execution.contracts import (
    CapabilityGrant,
    ModelPolicy,
    NativeOperationExecutionPlacement,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
    PromptSegment,
    PromptTrustClass,
    StructuredOutputBinding,
    WorkspaceContract,
)
from mission_control.domain.policies.contracts import RunOutcome
from mission_control.domain.programs.contracts import (
    GoalDirectedRunInput,
    GoalExecutionResult,
    GoalRevision,
    GoalVerificationResult,
    LifecycleCommandOutcome,
    LifecycleCommandRequest,
)
from mission_control.domain.programs.goal_directed_runtime import (
    GoalOperationDispatch,
    GoalOperationPreparationRequest,
    GoalOperationReconciliationRequest,
    GoalOperationReconciliationResult,
    GoalOperationSettlement,
)
from tests.support.temporal import sleep_heartbeating

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)


def _exact(kind: DefinitionKind, logical_id: str) -> ExactDefinitionRef:
    return ExactDefinitionRef(kind=kind, logical_id=logical_id, revision=1, digest=DIGEST)


def _revision() -> GoalRevision:
    values = {
        "schema_version": "belllabs.goal-revision.v1",
        "revision_id": "goal-revision:1",
        "revision": 1,
        "parent_revision_id": None,
        "envelope_digest": sha256_digest("temporal-envelope"),
        "objective": "Produce one independently verified bounded result.",
        "tactical_changes": (),
        "evidence_refs": ("input:goal",),
        "unmet_obligations": ("fixture-obligation",),
        "proposer": "application:test",
        "deciding_authority": "authority:test",
        "applicability": "remaining_run",
        "tactics": (),
        "subgoals": (),
        "coverage_emphasis": (),
    }
    return GoalRevision(canonical_digest=sha256_digest(values), **values)  # type: ignore[arg-type]


def _run_input(
    *,
    blueprint: GoalDirectedBlueprint = GENERIC_GOAL_DIRECTED,
    run_id: str = "run-wp-bp-020-temporal",
) -> GoalDirectedRunInput:
    revision = _revision()
    return GoalDirectedRunInput(
        run_id=run_id,
        request_scope="tenant-1",
        effective_configuration_digest=DIGEST,
        blueprint_digest=sha256_digest(blueprint),
        blueprint=blueprint.model_dump(mode="json"),
        envelope_digest=revision.envelope_digest,
        initial_revision=revision,
        initial_run_version=1,
        task_timeout_seconds=10,
        required_obligation_refs=("fixture-obligation",),
        required_output_contract_refs=("fixture-output",),
        semantic_input_binding_ref="semantic-input:test",
    )


def _operation(request: GoalOperationPreparationRequest) -> OperationExecutionRequest:
    operation_id = f"goal-iteration/{request.goal_iteration}/{request.operation_role}"
    identity = OperationAttemptIdentity(
        run_id=request.run_id,
        operation_id=operation_id,
        operation_attempt=request.operation_attempt,
    )
    content = f"Execute exact GoalDirected role {request.operation_role}."
    return OperationExecutionRequest(
        identity=identity,
        request_scope=request.request_scope,
        effective_configuration_digest=request.effective_configuration_digest,
        run_control_revision=request.expected_run_version,
        operation_contract_ref=f"operation:{request.operation_role}@1",
        prompt_segments=(
            PromptSegment(
                source_ref=f"prompt:{request.operation_role}@1",
                source_revision=1,
                trust_class=PromptTrustClass.SYSTEM_AUTHORITY,
                content=content,
                rendered_digest=sha256_digest(content),
            ),
        ),
        model_policy=ModelPolicy(
            provider="fixture",
            model="deterministic",
            max_turns=1,
        ),
        output_schema=StructuredOutputBinding(
            schema_id=f"fixture-{request.operation_role}-output",
            revision=1,
            schema_digest=DIGEST,
        ),
        session_id=request.session_id,
        agent_profile_ref=_exact(DefinitionKind.AGENT_PROFILE, "fixture.agent"),
        capability_grant=CapabilityGrant(capabilities=frozenset()),
        workspace=WorkspaceContract(
            namespace_id=f"run/{request.run_id}",
            workspace_id=request.workspace_id,
            provider="fixture",
            template_ref=_exact(DefinitionKind.WORKSPACE_TEMPLATE, "fixture.workspace"),
            exclusive_write_paths=(
                f"/goal/{request.goal_iteration}/{request.operation_role}/work",
            ),
            runtime_digest=DIGEST,
            image_digest=DIGEST,
            package_digest=DIGEST,
            environment_digest=DIGEST,
        ),
        native_placement=NativeOperationExecutionPlacement.create(
            placement_id=f"native.goal.{request.operation_role}",
            revision=1,
            task_queue="wp-bp-020-temporal",
            qualification_refs=("QUAL-BP-GOAL-DIRECTED-CONVERGENCE",),
        ),
        budget_reservation_id=request.reservation_id,
        budget_limits=request.reservation,
        tracing_policy_ref="tracing:test@1",
        sensitive_data_policy_ref="sensitive:test@1",
        snapshot_policy_ref="snapshot:test@1",
        requested_at=NOW,
        idempotency_key=(f"goal:{identity.semantic_key}:generation:{request.execution_generation}"),
    )


def fake_settlement(
    request: GoalOperationReconciliationRequest, usage: dict[str, int]
) -> GoalOperationSettlement:
    """The run-control settlement shape the family consumes (RRM-016), for fixtures whose
    operation child is a fake: the binding's claim, observation and settlement each advance
    the run version once past its bound revision."""

    operation = request.operation_request.operation
    return GoalOperationSettlement(
        binding_id=request.operation_binding_ref,
        settlement_id=f"settlement:{request.operation_binding_ref}",
        effect_claim_id=f"effect:{request.operation_binding_ref}",
        reservation_id=operation.budget_reservation_id,
        usage=usage,
        settlement_payload_digest=DIGEST,
        settled_run_version=operation.run_control_revision + 3,
    )


class FakeGoalDirectedActivities:
    def __init__(
        self,
        *,
        slow_operation: bool = False,
        complete_at_iteration: int = 1,
        scope_expansion_route: str | None = None,
    ) -> None:
        self.prepared_roles: list[str] = []
        self.lifecycle_kinds: list[str] = []
        self.cancelled_operations: list[str] = []
        self.operation_started = asyncio.Event()
        # RRM-008: a test that cancels a running unit may shorten its heartbeat timeout (the
        # cancel is delivered to the running `operation.execute` on its next heartbeat).
        self.operation_heartbeat_timeout_seconds: int | None = None
        self._slow_operation = slow_operation
        self._complete_at_iteration = complete_at_iteration
        self._scope_expansion_route = scope_expansion_route

    async def _prepare(self, request: GoalOperationPreparationRequest) -> GoalOperationDispatch:
        self.prepared_roles.append(request.operation_role)
        operation = _operation(request)
        workflow_request = OperationWorkflowRequest(
            semantic_attempt_id=operation.identity.semantic_key,
            execution_generation=request.execution_generation,
            operation_kind="bound_operation",
            operation=operation,
            **(
                {"heartbeat_timeout_seconds": self.operation_heartbeat_timeout_seconds}
                if self.operation_heartbeat_timeout_seconds is not None
                else {}
            ),
        )
        return GoalOperationDispatch(
            workflow_request=workflow_request,
            operation_binding_ref=f"binding:{request.operation_role}",
            operation_request_digest=sha256_digest(workflow_request),
            resulting_run_version=request.expected_run_version + 1,
            resulting_family_version=request.expected_family_version + 1,
        )

    @activity.defn(name="goaldirected.prepare_executor")
    async def prepare_executor(
        self, request: GoalOperationPreparationRequest
    ) -> GoalOperationDispatch:
        return await self._prepare(request)

    @activity.defn(name="goaldirected.prepare_verifier")
    async def prepare_verifier(
        self, request: GoalOperationPreparationRequest
    ) -> GoalOperationDispatch:
        return await self._prepare(request)

    @activity.defn(name="operation.execute")
    async def execute_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        self.operation_started.set()
        if self._slow_operation:
            await sleep_heartbeating(60)
        return {"operation_id": str(request["identity"])}

    @activity.defn(name="operation.cancel")
    async def cancel_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        """RRM-008: the fixture settlement of a cancelled unit."""

        self.cancelled_operations.append(str(request["identity"]["operation_id"]))
        return {
            "binding_id": f"binding:{str(request['identity']['operation_id']).split('/')[-1]}",
            "semantic_attempt_key": str(request["identity"]),
            "status": "cancelled",
            "failure_code": "cancelled",
        }

    @activity.defn(name="goaldirected.reconcile_operation")
    async def reconcile(
        self, request: GoalOperationReconciliationRequest
    ) -> GoalOperationReconciliationResult:
        operation = request.operation_request.operation
        if request.operation_result.disposition == "cancelled":
            # RRM-008: a cancelled unit is consumed through its settlement only.
            return GoalOperationReconciliationResult(
                operation_role=request.operation_role,
                detail_ref=f"goal-operation:cancelled:{request.operation_binding_ref}",
                settlement=fake_settlement(request, {}),
                operation_disposition="cancelled",
            )
        if request.operation_role == "executor":
            result = GoalExecutionResult(
                identity=request.claim.identity,
                disposition="completed",
                operation_identity=operation.identity.semantic_key,
                operation_binding_ref=request.operation_binding_ref,
                session_id=operation.session_id or "",
                workspace_id=operation.workspace.workspace_id,
                writable_paths=operation.workspace.exclusive_write_paths,
                output_refs=("artifact:verified-result",),
                completion_claim=True,
                actual_usage={"goal.iterations": 1},
                evidence_refs=("evidence:executor",),
                output_contract_ref="fixture-output",
            )
            return GoalOperationReconciliationResult(
                operation_role="executor",
                execution_result=result,
                detail_ref="goal-iteration:1",
                settlement=fake_settlement(request, result.actual_usage),
            )

        accepted = self._scope_expansion_route is None and (
            request.claim.identity.iteration.goal_iteration >= self._complete_at_iteration
        )
        values = {
            "schema_version": "belllabs.goal-verification.v1",
            "verification_id": "verification:1",
            "executor_identity": request.claim.identity,
            "verifier_operation_identity": operation.identity.semantic_key,
            "verifier_binding_ref": request.operation_binding_ref,
            "verifier_policy_binding_ref": (GENERIC_GOAL_DIRECTED.verifier_policy.binding_ref),
            "verifier_session_id": operation.session_id or "",
            "verifier_workspace_id": operation.workspace.workspace_id,
            "verifier_writable_paths": operation.workspace.exclusive_write_paths,
            "decision": ("accepted" if accepted else "rejected"),
            "verification_ref": "verification-ref:1",
            "rubric_ref": GENERIC_GOAL_DIRECTED.verifier_policy.rubric_ref,
            "rubric_version": 1,
            "acceptance_contract_ref": GENERIC_GOAL_DIRECTED.acceptance_contract,
            "acceptance_version": 1,
            "progress_made": True,
            "accepted_obligation_refs": (("fixture-obligation",) if accepted else ()),
            "findings": (),
            "evidence_refs": ("evidence:verifier",),
            "admitted_executor_output_refs": ("artifact:verified-result",),
            "admitted_executor_evidence_refs": ("evidence:executor",),
            "unmet_obligations": (() if accepted else ("fixture-obligation",)),
            "obligation_applicability": (("fixture-obligation", True),),
            "stale_frontier_digest": sha256_digest("stale-frontier"),
            "blocker_class": "",
            "authority_breach_ref": "",
            "hard_budget_exhausted_dimensions": (),
            "soft_budget_dimensions": (),
            "irrecoverable_failure_ref": "",
            "proposed_revision": None,
            "scope_expansion_route": self._scope_expansion_route,
            "route_ref": ("route:governed-expansion" if self._scope_expansion_route else ""),
            "actual_usage": {"goal.iterations": 1},
            "effect_refs": (),
            "output_contract_ref": "fixture-output",
        }
        draft = GoalVerificationResult(  # type: ignore[arg-type]
            verification_digest="pending",
            **values,
        )
        payload = asdict(draft)
        payload.pop("verification_digest")
        verification = replace(draft, verification_digest=sha256_digest(payload))
        return GoalOperationReconciliationResult(
            operation_role="verifier",
            verification_result=verification,
            detail_ref="goal-verification:1",
            settlement=fake_settlement(request, verification.actual_usage),
        )

    @activity.defn(name="goaldirected.apply_lifecycle_command")
    async def lifecycle(self, request: LifecycleCommandRequest) -> LifecycleCommandOutcome:
        kind = str(request.action["kind"])
        self.lifecycle_kinds.append(kind)
        return LifecycleCommandOutcome(
            accepted=True,
            resulting_run_version=request.expected_run_version + 1,
            phase=("terminal" if kind == "terminalize" else "active"),
            reason_code="accepted",
            evidence_frontier_digest=DIGEST,
            obligation_revision=DIGEST,
            accepted_obligation_evidence_digest=DIGEST,
            required_obligations_accepted=True,
            workflow_type_digest=DIGEST,
            terminal_outcome=(RunOutcome.COMPLETED if kind == "terminalize" else None),
        )

    @property
    def functions(self) -> list[object]:
        return [
            self.prepare_executor,
            self.prepare_verifier,
            self.execute_operation,
            self.cancel_operation,
            self.reconcile,
            self.lifecycle,
        ]

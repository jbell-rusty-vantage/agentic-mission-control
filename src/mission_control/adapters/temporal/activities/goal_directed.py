from __future__ import annotations

from pydantic import ValidationError
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker, WorkerDeploymentConfig

from mission_control.adapters.temporal.activities.human_gate import HumanGateActivities
from mission_control.adapters.temporal.boundary_activities import apply_boundary_fact
from mission_control.adapters.temporal.family_failure_activity import terminalize_failed_family
from mission_control.adapters.temporal.nested_program_activities import NestedProgramActivities
from mission_control.adapters.temporal.registration.activities import coordinator_activities
from mission_control.adapters.temporal.registration.workflows import coordinator_workflows
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.application.context.linked_transfer import LinkedExportPort
from mission_control.application.context.pack_service import (
    ArtifactBytesPort,
    ContextPackRejected,
    ContextPackService,
)
from mission_control.application.coordinator.coordinator_results import (
    TerminalWorkflowCompletionPort,
)
from mission_control.application.execution.boundary_interventions import (
    BoundaryCommandApplicationService,
)
from mission_control.application.execution.family_failure import FamilyFailureTerminalization
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.execution.operations.semantic_operation_bindings import (
    SemanticOperationBindingRepository,
)
from mission_control.application.execution.service import RunControlService
from mission_control.application.programs.goal_directed import (
    CompletionRecordPort,
    GoalAdmissionStale,
    GoalDirectedDocumentRepository,
    GoalDirectedOperationPreparationService,
    GoalDirectedOperationResultService,
    GoalFulfillmentConvergence,
    GoalOperationTemplateProvider,
    RunControlGoalOperationSettlements,
)
from mission_control.application.programs.service import (
    RunControlLifecycleGateway,
    orchestration_lifecycle_actor,
)
from mission_control.application.resolution.lane_bindings import LaneRebinders
from mission_control.domain.coordinator.launch import (
    LaunchAuthorizationError,
    TerminalWorkflowCompletion,
)
from mission_control.domain.execution.heartbeats import (
    DEFAULT_OPERATION_HEARTBEATS,
    OperationHeartbeatPolicy,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.programs.contracts import (
    BoundaryLifecycleOutcome,
    BoundaryLifecycleRequest,
    LifecycleCommandOutcome,
    LifecycleCommandRequest,
)
from mission_control.domain.programs.family_failure import (
    FamilyFailureTerminalizationRequest,
    FamilyFailureTerminalizationResult,
)
from mission_control.domain.programs.goal_directed_runtime import (
    GOAL_ADMISSION_STALE,
    GOAL_DISPATCH_INVALID,
    GOAL_OUTPUT_INVALID,
    GOAL_RECONCILIATION_OVERSIZE,
    MAX_RECONCILIATION_REQUEST_BYTES,
    GoalOperationDispatch,
    GoalOperationPreparationRequest,
    GoalOperationReconciliationRequest,
    GoalOperationReconciliationResult,
    reconciliation_payload_bytes,
)


class GoalDirectedActivities:
    """GoalDirected I/O adapters; cognition runs only through OperationWorkflow."""

    def __init__(
        self,
        *,
        operations: GoalDirectedOperationPreparationService,
        results: GoalDirectedOperationResultService,
        lifecycle: RunControlLifecycleGateway,
        completion: TerminalWorkflowCompletionPort | None = None,
        boundary: BoundaryCommandApplicationService | None = None,
        failed_family: FamilyFailureTerminalization | None = None,
    ) -> None:
        self._operations = operations
        self._results = results
        self._lifecycle = lifecycle
        self._completion = completion
        self._boundary = boundary
        self._failed_family = failed_family

    @property
    def completion_configured(self) -> bool:
        return self._completion is not None

    @activity.defn(name="goaldirected.prepare_executor")
    async def execute_iteration(
        self, request: GoalOperationPreparationRequest
    ) -> GoalOperationDispatch:
        if request.operation_role != "executor":
            raise ApplicationError(
                "executor preparation received another operation role",
                type="goal_operation_role_mismatch",
                non_retryable=True,
            )
        return await self._prepare(request)

    @activity.defn(name="goaldirected.prepare_verifier")
    async def verify_iteration(
        self, request: GoalOperationPreparationRequest
    ) -> GoalOperationDispatch:
        if request.operation_role != "verifier":
            raise ApplicationError(
                "verifier preparation received another operation role",
                type="goal_operation_role_mismatch",
                non_retryable=True,
            )
        return await self._prepare(request)

    async def _prepare(self, request: GoalOperationPreparationRequest) -> GoalOperationDispatch:
        try:
            dispatch = await self._operations.prepare(request)
        except GoalAdmissionStale as error:
            # RRM-016 review fix 2: reported to the family, which re-admits once at the
            # current version or enters cancellation; never retried by Temporal as-is.
            raise ApplicationError(
                str(error),
                error.current_run_version,
                error.phase,
                type=GOAL_ADMISSION_STALE,
                non_retryable=True,
            ) from error
        except ContextPackRejected as error:
            # FT-B3: a packet that cannot be sealed rejects the admission before any provider
            # work (for example a mandatory Loop State over budget); never truncated.
            raise ApplicationError(str(error), type=error.code, non_retryable=True) from error
        except ValidationError as error:
            # W1 D10: a dispatch outside its contract (for example a prompt segment over the
            # operation request's ceiling) is deterministic: refused typed, never retried.
            raise _dispatch_refused(error) from error
        try:
            # W1 D10: the family decodes this result from its JSON; prove it decodes here, so
            # a payload the activity could build but the workflow could not read fails this
            # activity (typed, terminal) instead of every workflow task forever.
            return GoalOperationDispatch.model_validate_json(dispatch.model_dump_json())
        except ValidationError as error:
            raise _dispatch_refused(error) from error

    @activity.defn(name="goaldirected.reconcile_nested_executor")
    async def reconcile_nested_executor(
        self, request: GoalOperationReconciliationRequest
    ) -> GoalOperationReconciliationResult:
        """OVE-176: reconcile the export receipt of a nested executor-phase body."""

        try:
            return await self._results.reconcile_nested_executor(request)
        except (ValidationError, ValueError) as error:
            raise ApplicationError(
                str(error), type="goal_nested_executor_invalid", non_retryable=True
            ) from error

    @activity.defn(name="goaldirected.reconcile_operation")
    async def prepare_handoff(
        self, request: GoalOperationReconciliationRequest
    ) -> GoalOperationReconciliationResult:
        size = reconciliation_payload_bytes(request)
        if size > MAX_RECONCILIATION_REQUEST_BYTES:
            # W1 B1: the family refuses first (patched); this guards any other caller.
            raise ApplicationError(
                f"reconciliation request is {size} bytes, over {MAX_RECONCILIATION_REQUEST_BYTES}",
                type=GOAL_RECONCILIATION_OVERSIZE,
                non_retryable=True,
            )
        try:
            return await self._results.reconcile(request)
        except ValidationError as error:
            # F-T3-1: validating a completed provider payload is deterministic; a replay of
            # the activity cannot repair it, so the classifier never retries it.
            raise ApplicationError(
                str(error), type=GOAL_OUTPUT_INVALID, non_retryable=True
            ) from error
        except ValueError as error:
            if request.completion_blueprint is None:
                raise
            raise ApplicationError(
                str(error), type="goal_completion_invalid", non_retryable=True
            ) from error

    @activity.defn(name="goaldirected.apply_lifecycle_command")
    async def apply_lifecycle_command(
        self, request: LifecycleCommandRequest
    ) -> LifecycleCommandOutcome:
        return await self._lifecycle.execute(request)

    @activity.defn(name="goaldirected.apply_boundary_command")
    async def apply_boundary_command(
        self, request: BoundaryLifecycleRequest
    ) -> BoundaryLifecycleOutcome:
        """RRM-007: the family boundary's run-control facts, bound to the current version."""

        if self._boundary is None:
            raise ApplicationError(
                "boundary command application is not composed for GoalDirected",
                type="boundary_application_unavailable",
                non_retryable=True,
            )
        return await apply_boundary_fact(self._boundary, request)

    @activity.defn(name="coordinator.materialize_workflow_result")
    async def materialize_workflow_result(self, completion: TerminalWorkflowCompletion) -> object:
        if self._completion is None:
            raise ApplicationError(
                "typed Workflow Result materializer is unavailable",
                type="workflow_result_materializer_unavailable",
                non_retryable=True,
            )
        try:
            return await self._completion.complete(completion)
        except (LaunchAuthorizationError, ValueError) as error:
            raise ApplicationError(
                str(error),
                type="workflow_result_completion_conflict",
                non_retryable=True,
            ) from error

    @activity.defn(name="coordinator.terminalize_failed_family")
    async def terminalize_failed_family(
        self, request: FamilyFailureTerminalizationRequest
    ) -> FamilyFailureTerminalizationResult:
        """W1 D15: the root's terminalization of a run whose family ended unterminalized."""

        return await terminalize_failed_family(self._failed_family, request)


def _dispatch_refused(error: ValidationError) -> ApplicationError:
    """A typed, non-retryable refusal naming the contract messages only (never input values,
    which can carry prompt content)."""

    messages = "; ".join(str(item.get("msg", "")) for item in error.errors()[:3])
    return ApplicationError(
        f"goal operation dispatch refused by its contract ({error.error_count()}): {messages}",
        type=GOAL_DISPATCH_INVALID,
        non_retryable=True,
    )


def compose_goal_directed_activities(
    *,
    run_control: RunControlService,
    operation_bindings: SemanticOperationBindingRepository,
    templates: GoalOperationTemplateProvider,
    documents: GoalDirectedDocumentRepository,
    lifecycle: RunControlLifecycleGateway,
    actor: ActorContext,
    completion: TerminalWorkflowCompletionPort | None = None,
    boundary: BoundaryCommandApplicationService | None = None,
    heartbeats: OperationHeartbeatPolicy = DEFAULT_OPERATION_HEARTBEATS,
    context_packs: ContextPackService | None = None,
    linked_exports: LinkedExportPort | None = None,
    mailbox: MailboxDeliveryService | None = None,
    artifacts: ArtifactBytesPort | None = None,
    completions: CompletionRecordPort | None = None,
    lane_bindings: LaneRebinders | None = None,
    fulfillment: GoalFulfillmentConvergence | None = None,
) -> GoalDirectedActivities:
    """Wire production GoalDirected activities on the OperationWorkflow path."""

    return GoalDirectedActivities(
        operations=GoalDirectedOperationPreparationService(
            templates=templates,
            operation_bindings=operation_bindings,
            run_control=run_control,
            documents=documents,
            actor=actor,
            heartbeats=heartbeats,
            context_packs=context_packs,
            linked_exports=linked_exports,
            mailbox=mailbox,
            lane_bindings=lane_bindings,
        ),
        # RRM-016: the family consumes each operation's journaled run-control settlement.
        results=GoalDirectedOperationResultService(
            documents,
            RunControlGoalOperationSettlements(run_control, operation_bindings),
            artifacts=artifacts,
            run_control=run_control,
            completions=completions,
            fulfillment=fulfillment,
        ),
        lifecycle=lifecycle,
        completion=completion,
        boundary=boundary,
        failed_family=FamilyFailureTerminalization(run_control, orchestration_lifecycle_actor()),
    )


def create_goal_directed_worker(
    client: Client,
    *,
    task_queue: str,
    activities: GoalDirectedActivities,
    deployment_config: WorkerDeploymentConfig | None = None,
    human_gates: HumanGateActivities | None = None,
    nested: NestedProgramActivities | None = None,
) -> Worker:
    # MP-10: the review gate's activities run on the family queue when composed.
    return Worker(
        client,
        task_queue=task_queue,
        workflows=coordinator_workflows("GoalDirected"),
        workflow_runner=coordinator_workflow_runner(),
        activities=[
            *coordinator_activities("GoalDirected", activities),
            *(human_gates.functions if human_gates is not None else ()),
            # OVE-176: nested-body activate/settle/propagate on the family queue.
            *(nested.activities() if nested is not None else ()),
        ],
        deployment_config=deployment_config,
    )


__all__ = [
    "GoalDirectedActivities",
    "compose_goal_directed_activities",
    "create_goal_directed_worker",
]

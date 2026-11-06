from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client
from temporalio.worker import Worker, WorkerDeploymentConfig

from mission_control.adapters.temporal.activities.goal_directed import (
    GoalDirectedActivities,
    compose_goal_directed_activities,
    create_goal_directed_worker,
)
from mission_control.adapters.temporal.activities.human_gate import HumanGateActivities
from mission_control.adapters.temporal.nested_program_activities import NestedProgramActivities
from mission_control.adapters.temporal.orchestration_activities import (
    StageGraphActivities,
    create_stagegraph_worker,
)
from mission_control.adapters.temporal.registration.task_queues import BellLabsTaskQueues
from mission_control.application.context.linked_transfer import LinkedExportPort
from mission_control.application.context.pack_service import ArtifactBytesPort, ContextPackService
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
from mission_control.application.execution.run_control_repository import RunControlRepository
from mission_control.application.execution.service import RunControlService
from mission_control.application.human_tasks.service import HumanTaskRepository
from mission_control.application.programs.goal_directed import (
    CompletionRecordPort,
    GoalDirectedDocumentRepository,
    GoalFulfillmentConvergence,
    GoalOperationTemplateProvider,
)
from mission_control.application.programs.named_outputs import NamedStageOutputs
from mission_control.application.programs.nested_bodies import (
    InMemoryNestedActivationStore,
    NestedActivationStore,
    NestedProgramService,
)
from mission_control.application.programs.orchestration_binding_repository import (
    RunSemanticInputBindingRepository,
)
from mission_control.application.programs.orchestration_routing import (
    OperationExecutionBindingReader,
    SemanticHandlerRegistry,
)
from mission_control.application.programs.service import (
    RunControlLifecycleGateway,
    StageGraphDecisionService,
    StageGraphHumanGateProvider,
    StageGraphOperationPreparationService,
    StageGraphOperationTemplateProvider,
    orchestration_lifecycle_actor,
)
from mission_control.application.resolution.lane_bindings import LaneRebinders
from mission_control.domain.execution.heartbeats import (
    DEFAULT_OPERATION_HEARTBEATS,
    OperationHeartbeatPolicy,
)
from mission_control.domain.policies.contracts import ActorContext


@dataclass(frozen=True)
class CoordinatorTaskQueues:
    stagegraph: str
    goal_directed: str

    def __post_init__(self) -> None:
        if not self.stagegraph or not self.goal_directed:
            raise ValueError("coordinator Temporal task queues must be non-empty")
        if self.stagegraph == self.goal_directed:
            raise ValueError(
                "StageGraph and GoalDirected require distinct task queues for readiness"
            )


@dataclass(frozen=True)
class CoordinatorWorkerActivities:
    stagegraph: StageGraphActivities
    goal_directed: GoalDirectedActivities
    # MP-10: Human Gate open/observe/cancel/settle, served by both family workers.
    human_gates: HumanGateActivities | None = None
    # OVE-176: nested-body activate/settle/propagate, served by both family workers.
    nested: NestedProgramActivities | None = None

    @property
    def completion_configured(self) -> bool:
        return self.stagegraph.completion_configured and self.goal_directed.completion_configured


@dataclass(frozen=True)
class GoalDirectedCoordinatorDependencies:
    artifacts: ArtifactBytesPort | None = field(default=None, kw_only=True)
    """Exact ports required to compose the canonical GoalDirected activity surface."""

    run_control: RunControlService
    operation_bindings: SemanticOperationBindingRepository
    templates: GoalOperationTemplateProvider
    documents: GoalDirectedDocumentRepository
    actor: ActorContext
    # RRM-009: the deployment's heartbeat timeout per operation class (RRM-008 cancel latency).
    operation_heartbeats: OperationHeartbeatPolicy = DEFAULT_OPERATION_HEARTBEATS
    # FT-B3: when composed, every iteration and role starts from a sealed Context Packet.
    context_packs: ContextPackService | None = None
    linked_exports: LinkedExportPort | None = None
    # FT-F1: queued instructions and context enter the executor packet at iteration start.
    mailbox: MailboxDeliveryService | None = None
    # 1.4.4 (tracing, TR-G9): the verifier's decision lands in `completion_decision`.
    completions: CompletionRecordPort | None = None
    # OC-R2: the lanes' rebind port (a template's sealed binding to the live attempt).
    lane_bindings: LaneRebinders | None = None
    # W1 (OVE-169): explicit output fulfillment at the convergence boundary.
    fulfillment: GoalFulfillmentConvergence | None = None


@dataclass(frozen=True)
class StageGraphCoordinatorDependencies:
    """Exact authority and operation-template ports for canonical StageGraph activities."""

    run_control: RunControlService
    repository: RunControlRepository
    operation_bindings: SemanticOperationBindingRepository
    templates: StageGraphOperationTemplateProvider
    operation_heartbeats: OperationHeartbeatPolicy = DEFAULT_OPERATION_HEARTBEATS
    # FT-B2: when composed, every admitted stage starts from a sealed Context Packet.
    context_packs: ContextPackService | None = None
    linked_exports: LinkedExportPort | None = None
    # FT-F1: queued instructions and context enter the next admitted stage's packet.
    mailbox: MailboxDeliveryService | None = None
    artifacts: ArtifactBytesPort | None = None
    human_gate_provider: StageGraphHumanGateProvider | None = None
    # OC-R2: the lanes' rebind port (a template's sealed binding to the live attempt).
    lane_bindings: LaneRebinders | None = None

    named_outputs: NamedStageOutputs | None = None
    human_tasks: HumanTaskRepository | None = None
    nested_activations: NestedActivationStore | None = None


def create_routed_coordinator_activities(
    *,
    bindings: RunSemanticInputBindingRepository,
    handlers: SemanticHandlerRegistry,
    lifecycle: RunControlLifecycleGateway,
    goal_directed: GoalDirectedCoordinatorDependencies,
    stagegraph: StageGraphCoordinatorDependencies,
    operation_bindings: OperationExecutionBindingReader | None = None,
    completion: TerminalWorkflowCompletionPort | None = None,
    human_gates: HumanGateActivities | None = None,
    nested: NestedProgramActivities | None = None,
) -> CoordinatorWorkerActivities:
    """Compose production activity ports from durable bindings and exact handlers.

    OVE-176: without a composed nested-body launcher the family workers still serve the
    nested activities, refusing typed (`nested_execution_unavailable`) and releasing the
    hosting unit's reservation; a nested body is never flattened into an operation.
    """

    # RRM-007: both family boundaries apply governed commands with the orchestration
    # identity, which holds every lifecycle permission and the orchestration authority.
    return CoordinatorWorkerActivities(
        stagegraph=StageGraphActivities(
            lifecycle_gateway=lifecycle,
            completion=completion,
            decision_service=StageGraphDecisionService(
                stagegraph.run_control,
                stagegraph.repository,
                artifacts=stagegraph.artifacts,
                human_gates=stagegraph.human_gate_provider,
                named_outputs=stagegraph.named_outputs,
                human_tasks=stagegraph.human_tasks,
                nested_activations=stagegraph.nested_activations,
            ),
            operation_materializer=StageGraphOperationPreparationService(
                templates=stagegraph.templates,
                operation_bindings=stagegraph.operation_bindings,
                heartbeats=stagegraph.operation_heartbeats,
                context_packs=stagegraph.context_packs,
                linked_exports=stagegraph.linked_exports,
                mailbox=stagegraph.mailbox,
                lane_bindings=stagegraph.lane_bindings,
            ),
            boundary=BoundaryCommandApplicationService(
                stagegraph.run_control, orchestration_lifecycle_actor()
            ),
            failed_family=FamilyFailureTerminalization(
                stagegraph.run_control, orchestration_lifecycle_actor()
            ),
        ),
        goal_directed=compose_goal_directed_activities(
            run_control=goal_directed.run_control,
            operation_bindings=goal_directed.operation_bindings,
            templates=goal_directed.templates,
            documents=goal_directed.documents,
            lifecycle=lifecycle,
            actor=goal_directed.actor,
            completion=completion,
            boundary=BoundaryCommandApplicationService(
                goal_directed.run_control, orchestration_lifecycle_actor()
            ),
            heartbeats=goal_directed.operation_heartbeats,
            context_packs=goal_directed.context_packs,
            linked_exports=goal_directed.linked_exports,
            mailbox=goal_directed.mailbox,
            artifacts=goal_directed.artifacts,
            completions=goal_directed.completions,
            lane_bindings=goal_directed.lane_bindings,
            fulfillment=goal_directed.fulfillment,
        ),
        human_gates=human_gates,
        nested=nested
        or NestedProgramActivities(
            NestedProgramService(
                run_control=stagegraph.run_control,
                launcher=None,
                outputs=None,
                controls=None,
                activations=InMemoryNestedActivationStore(),
            )
        ),
    )


@dataclass(frozen=True)
class CoordinatorWorkerSet:
    stagegraph: Worker
    goal_directed: Worker
    task_queues: CoordinatorTaskQueues

    @property
    def workers(self) -> tuple[Worker, Worker]:
        return (self.stagegraph, self.goal_directed)


@dataclass(frozen=True)
class TemporalFamilyReadiness:
    family: str
    task_queue: str
    workflow_registered: bool
    workflow_pollers: int

    @property
    def available(self) -> bool:
        return self.workflow_registered and self.workflow_pollers > 0


def coordinator_task_queues(base_task_queue: str) -> CoordinatorTaskQueues:
    if not base_task_queue:
        raise ValueError("base Temporal task queue must be non-empty")
    logical = BellLabsTaskQueues.from_base(base_task_queue)
    return CoordinatorTaskQueues(
        stagegraph=f"{logical.coordinator_family}-stagegraph",
        goal_directed=f"{logical.coordinator_family}-goal-directed",
    )


def create_coordinator_workers(
    client: Client,
    *,
    task_queues: CoordinatorTaskQueues,
    activities: CoordinatorWorkerActivities,
    deployment_config: WorkerDeploymentConfig | None = None,
) -> CoordinatorWorkerSet:
    """Register both accepted coordinator workflow families with real activities."""

    if not activities.completion_configured:
        raise ValueError("coordinator workers require durable typed-result completion providers")
    return CoordinatorWorkerSet(
        stagegraph=create_stagegraph_worker(
            client,
            task_queue=task_queues.stagegraph,
            activities=activities.stagegraph,
            deployment_config=deployment_config,
            human_gates=activities.human_gates,
            nested=activities.nested,
        ),
        goal_directed=create_goal_directed_worker(
            client,
            task_queue=task_queues.goal_directed,
            activities=activities.goal_directed,
            deployment_config=deployment_config,
            human_gates=activities.human_gates,
            nested=activities.nested,
        ),
        task_queues=task_queues,
    )


async def coordinator_worker_readiness(
    client: Client,
    *,
    task_queues: CoordinatorTaskQueues,
    rpc_timeout: timedelta = timedelta(seconds=5),
) -> tuple[TemporalFamilyReadiness, TemporalFamilyReadiness]:
    """Report actual workflow pollers; configured queue names alone are not availability."""

    stagegraph_pollers = await _workflow_poller_count(
        client,
        task_queues.stagegraph,
        rpc_timeout=rpc_timeout,
    )
    goal_directed_pollers = await _workflow_poller_count(
        client,
        task_queues.goal_directed,
        rpc_timeout=rpc_timeout,
    )
    return (
        TemporalFamilyReadiness(
            family="StageGraph",
            task_queue=task_queues.stagegraph,
            workflow_registered=True,
            workflow_pollers=stagegraph_pollers,
        ),
        TemporalFamilyReadiness(
            family="GoalDirected",
            task_queue=task_queues.goal_directed,
            workflow_registered=True,
            workflow_pollers=goal_directed_pollers,
        ),
    )


async def _workflow_poller_count(
    client: Client,
    task_queue: str,
    *,
    rpc_timeout: timedelta,
) -> int:
    response = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace=client.namespace,
            task_queue=TaskQueue(name=task_queue),
            task_queue_type=TaskQueueType.Value("TASK_QUEUE_TYPE_WORKFLOW"),
        ),
        timeout=rpc_timeout,
    )
    return len(response.pollers)

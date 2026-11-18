"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_wp_bp_010_temporal.py.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from temporalio import activity

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    AllowedOperationVariant,
    DefinitionKind,
    ExactDefinitionRef,
    FairnessGroup,
    LateResultPolicy,
    LateResultRule,
    SlowSiblingPolicy,
    StageCyclePolicy,
    StageDependency,
    StageGraphBlueprint,
    StageGraphWait,
    StageInputSlot,
    StageJoin,
    StageNode,
    StageOperationSlot,
    StageOutputSlot,
    WorkflowCyclePolicy,
)
from mission_control.domain.execution.contracts import (
    CapabilityGrant,
    ModelPolicy,
    NativeOperationExecutionPlacement,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
    PromptSegment,
    PromptTrustClass,
    WorkspaceContract,
)
from mission_control.domain.policies.contracts import RunOutcome
from mission_control.domain.programs.contracts import (
    StageGraphAdmissionActivityRequest,
    StageGraphAdmissionActivityResult,
    StageGraphCompletionActivityRequest,
    StageGraphCompletionActivityResult,
    StageGraphCycleActivityRequest,
    StageGraphCycleActivityResult,
    StageGraphInitializeRequest,
    StageGraphInitializeResult,
    StageGraphResultActivityRequest,
    StageGraphResultActivityResult,
    StageGraphRunInput,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.fixtures.operation_activities import cancelled_operation_result, wait_heartbeating

DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
QUEUE = "wp-bp-010-temporal"


def _exact(kind: DefinitionKind, logical_id: str) -> ExactDefinitionRef:
    return ExactDefinitionRef(kind=kind, logical_id=logical_id, revision=1, digest=DIGEST)


def _slot() -> StageOperationSlot:
    return StageOperationSlot(
        operation_slot_id="execute",
        reservation={"operation.attempts": 1},
        allowed_variants=(
            AllowedOperationVariant(
                operation_variant_id="default",
                operation_contract_ref="operation:temporal-fixture@1",
            ),
        ),
    )


def _blueprint(
    *,
    cancel_slow_sibling: bool = False,
    workflow_cycles: int = 0,
    stage_cycles: int = 0,
    workflow_wait: bool = False,
) -> StageGraphBlueprint:
    dependencies = (
        StageDependency(
            dependency_id="fast-to-downstream",
            consumer_stage_id="downstream",
            join_id="first-result",
            producer_stage_id="fast",
            producer_output_slot_id="result",
            consumer_input_slot_id="fast-input",
            dependency_class="required",
        ),
        StageDependency(
            dependency_id="slow-to-downstream",
            consumer_stage_id="downstream",
            join_id="first-result",
            producer_stage_id="slow",
            producer_output_slot_id="result",
            consumer_input_slot_id="slow-input",
            dependency_class="required",
        ),
    )
    return StageGraphBlueprint(
        logical_id="wp-bp-010-temporal",
        title="Temporal incremental StageGraph",
        description="A deterministic fast/slow any-join fixture.",
        stages=(
            StageNode(
                stage_id="fast",
                output_slots=(
                    StageOutputSlot(
                        output_slot_id="result",
                        output_contract_ref="output:fast@1",
                    ),
                ),
                operation_slots=(_slot(),),
            ),
            StageNode(
                stage_id="slow",
                output_slots=(
                    StageOutputSlot(
                        output_slot_id="result",
                        output_contract_ref="output:slow@1",
                    ),
                ),
                operation_slots=(_slot(),),
            ),
            StageNode(
                stage_id="downstream",
                input_slots=(
                    StageInputSlot(input_slot_id="fast-input"),
                    StageInputSlot(input_slot_id="slow-input"),
                ),
                output_slots=(
                    StageOutputSlot(
                        output_slot_id="result",
                        output_contract_ref="output:downstream@1",
                    ),
                ),
                operation_slots=(_slot(),),
                stage_cycle_policy=(
                    StageCyclePolicy(
                        max_cycles=stage_cycles,
                        evaluation_contract_ref="evaluation:temporal-fixture@1",
                        objective_contract_ref="objective:temporal-fixture@1",
                        reservation={"stage.cycles": 1},
                    )
                    if stage_cycles
                    else None
                ),
            ),
        ),
        joins=(
            StageJoin(
                consumer_stage_id="downstream",
                join_id="first-result",
                kind="any",
                dependency_ids=tuple(item.dependency_id for item in dependencies),
                slow_sibling_policy=SlowSiblingPolicy(
                    triggers=("join_released",),
                    execution_action=("request_cancel" if cancel_slow_sibling else "continue"),
                    arrival_route="evaluate_late_result",
                ),
            ),
        ),
        dependencies=dependencies,
        fairness_groups=(FairnessGroup(group_id="default", weight=1),),
        late_result_policy=LateResultPolicy(
            rules=(
                LateResultRule(
                    rule_id="admit-late-sibling",
                    trigger="consumer_already_admitted",
                    decision="admit",
                ),
            )
        ),
        workflow_evaluation_contract_ref=(
            "evaluation:temporal-fixture@1" if workflow_cycles else None
        ),
        workflow_cycle_policy=(
            WorkflowCyclePolicy(
                max_cycles=workflow_cycles,
                evaluation_contract_ref="evaluation:temporal-fixture@1",
                objective_contract_ref="objective:temporal-fixture@1",
                reservation={"workflow.cycles": 1},
            )
            if workflow_cycles
            else None
        ),
        waits=(
            (
                StageGraphWait(
                    scope_kind="workflow",
                    scope_id="wp-bp-010-temporal",
                    wait_id="release-workflow",
                ),
            )
            if workflow_wait
            else ()
        ),
    )


def _operation(
    request: StageGraphAdmissionActivityRequest, heartbeat_timeout_seconds: int | None = None
) -> OperationWorkflowRequest:
    proposal = request.proposal
    identity = OperationAttemptIdentity(
        run_id=request.run_id,
        operation_id=proposal.identity.operation_id,
        operation_attempt=proposal.identity.semantic_attempt,
    )
    content = f"Execute StageGraph stage {proposal.identity.stage_id}."
    operation = OperationExecutionRequest(
        identity=identity,
        request_scope=request.request_scope,
        effective_configuration_digest=request.effective_configuration_digest,
        run_control_revision=request.projection.run_version + 1,
        operation_contract_ref="operation:temporal-fixture@1",
        prompt_segments=(
            PromptSegment(
                source_ref="prompt:stagegraph-temporal@1",
                source_revision=1,
                trust_class=PromptTrustClass.SYSTEM_AUTHORITY,
                content=content,
                rendered_digest=sha256_digest(content),
            ),
        ),
        model_policy=ModelPolicy(provider="fixture", model="deterministic", max_turns=1),
        agent_profile_ref=_exact(DefinitionKind.AGENT_PROFILE, "fixture.stagegraph"),
        capability_grant=CapabilityGrant(capabilities=frozenset()),
        workspace=WorkspaceContract(
            namespace_id=f"run/{request.run_id}",
            workspace_id=f"workspace:{proposal.identity.semantic_key}",
            provider="fixture",
            template_ref=_exact(DefinitionKind.WORKSPACE_TEMPLATE, "fixture.workspace"),
            exclusive_write_paths=(f"/stages/{proposal.identity.stage_id}",),
            runtime_digest=DIGEST,
            image_digest=DIGEST,
            package_digest=DIGEST,
            environment_digest=DIGEST,
        ),
        native_placement=NativeOperationExecutionPlacement.create(
            placement_id="native.stagegraph.fixture",
            revision=1,
            task_queue=QUEUE,
            qualification_refs=("QUAL-BP-STAGEGRAPH-SEMANTICS-RECOVERY",),
        ),
        budget_reservation_id=proposal.reservation_id,
        budget_limits=proposal.reservation,
        tracing_policy_ref="tracing:test@1",
        sensitive_data_policy_ref="sensitive:test@1",
        snapshot_policy_ref="snapshot:test@1",
        requested_at=NOW,
        idempotency_key=f"stagegraph:{identity.semantic_key}",
    )
    return OperationWorkflowRequest(
        semantic_attempt_id=identity.semantic_key,
        execution_generation=proposal.identity.execution_generation,
        operation_kind="bound_operation",
        operation=operation,
        timeout_seconds=120,
        **(
            {"heartbeat_timeout_seconds": heartbeat_timeout_seconds}
            if heartbeat_timeout_seconds is not None
            else {}
        ),
    )


class FakeStageGraphActivities:
    def __init__(self, *, cycle_once: bool = False, cycle_scope: str = "workflow") -> None:
        self.slow_started = asyncio.Event()
        self.initialized = asyncio.Event()
        self.slow_release = asyncio.Event()
        self.slow_completed = asyncio.Event()
        self.slow_cancelled = asyncio.Event()
        self.downstream_started = asyncio.Event()
        self.admission_order: list[str] = []
        self.result_decisions: list[tuple[str, str]] = []
        self._cycle_once = cycle_once
        self._cycle_scope = cycle_scope
        self._cycle_emitted = False
        # RRM-008: every OperationWorkflow reconciles a cancelled unit through
        # `operation.cancel`; a cancel reaches a running `operation.execute` only through its
        # heartbeat. A test that cancels a running unit may shorten the heartbeat timeout.
        self.cancel_settlements: list[str] = []
        self.operation_heartbeat_timeout_seconds: int | None = None

    @activity.defn(name="stagegraph.initialize")
    async def initialize(self, request: StageGraphInitializeRequest) -> StageGraphInitializeResult:
        self.initialized.set()
        return StageGraphInitializeResult(
            accepted=True,
            projection=request.initial_projection.__class__(
                **{**request.initial_projection.__dict__, "run_version": 2}
            ),
            reason_code="accepted",
        )

    @activity.defn(name="stagegraph.admit_operation")
    async def admit(
        self, request: StageGraphAdmissionActivityRequest
    ) -> StageGraphAdmissionActivityResult:
        interpreter = StageGraphInterpreter(
            StageGraphBlueprint.model_validate(request.blueprint),
            effective_max_concurrency=request.effective_max_concurrency,
        )
        operation = _operation(request, self.operation_heartbeat_timeout_seconds)
        projection = interpreter.apply_admission(
            request.projection,
            request.proposal,
            next_run_version=request.projection.run_version + 1,
            next_family_version=request.projection.family_version + 1,
        )
        self.admission_order.append(request.proposal.identity.stage_id)
        return StageGraphAdmissionActivityResult(
            accepted=True,
            projection=projection,
            operation=operation,
            reason_code="accepted",
        )

    @activity.defn(name="stagegraph.decide_result")
    async def decide(
        self, request: StageGraphResultActivityRequest
    ) -> StageGraphResultActivityResult:
        interpreter = StageGraphInterpreter(
            StageGraphBlueprint.model_validate(request.blueprint),
            effective_max_concurrency=request.effective_max_concurrency,
        )
        proposal = interpreter.result_decision(
            request.observation.identity,
            request.late_facts,
            operation_disposition=request.observation.operation_disposition,
        )
        self.result_decisions.append(
            (request.observation.identity.semantic_key, proposal.decision.value)
        )
        projection = interpreter.apply_result_decision(
            request.projection,
            request.observation,
            proposal,
            next_run_version=request.projection.run_version + 1,
            next_family_version=request.projection.family_version + 1,
        )
        return StageGraphResultActivityResult(
            accepted=True,
            projection=projection,
            proposal=proposal,
            reason_code="accepted",
        )

    @activity.defn(name="stagegraph.complete")
    async def complete(
        self, request: StageGraphCompletionActivityRequest
    ) -> StageGraphCompletionActivityResult:
        assert request.proposal.can_terminalize
        return StageGraphCompletionActivityResult(
            accepted=True,
            terminal_outcome=RunOutcome.COMPLETED,
            resulting_run_version=request.projection.run_version + 1,
            reason_code="accepted",
        )

    @activity.defn(name="stagegraph.apply_cycle")
    async def apply_cycle(
        self, request: StageGraphCycleActivityRequest
    ) -> StageGraphCycleActivityResult:
        interpreter = StageGraphInterpreter(
            StageGraphBlueprint.model_validate(request.blueprint),
            effective_max_concurrency=request.effective_max_concurrency,
        )
        if request.cycle_scope == "stage":
            assert request.stage_id is not None
            proposal = interpreter.stage_invalidation(
                request.projection,
                stage_id=request.stage_id,
                next_objective=request.next_objective,
            )
            projection = interpreter.apply_stage_invalidation(
                request.projection,
                proposal,
                next_run_version=request.projection.run_version + 1,
                next_family_version=request.projection.family_version + 1,
            )
        else:
            proposal = interpreter.workflow_invalidation(
                request.projection,
                invalidation_frontier=request.invalidation_frontier,
                next_objective=request.next_objective,
            )
            projection = interpreter.apply_workflow_invalidation(
                request.projection,
                proposal,
                next_run_version=request.projection.run_version + 1,
                next_family_version=request.projection.family_version + 1,
            )
        return StageGraphCycleActivityResult(
            accepted=True,
            projection=projection,
            proposal=proposal,
            reason_code="accepted",
        )

    @activity.defn(name="operation.execute")
    async def execute_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        operation_id = str(request["identity"]["operation_id"])
        if ":stage:slow:" in operation_id:
            self.slow_started.set()
            try:
                await wait_heartbeating(self.slow_release)
            except asyncio.CancelledError:
                self.slow_cancelled.set()
                raise
            self.slow_completed.set()
            stage_id = "slow"
        elif ":stage:downstream:" in operation_id:
            self.downstream_started.set()
            stage_id = "downstream"
        else:
            await wait_heartbeating(self.slow_started)
            stage_id = "fast"
        result: dict[str, Any] = {"output_refs": [f"artifact:{stage_id}"]}
        if stage_id == "downstream" and self._cycle_once and not self._cycle_emitted:
            self._cycle_emitted = True
            result.update(
                {
                    "evaluation": "cycle",
                    "evaluation_ref": "evaluation:evidence:cycle-1",
                    "evaluation_contract_ref": "evaluation:temporal-fixture@1",
                    "objective_contract_ref": "objective:temporal-fixture@1",
                    "next_objective": "Repair only the downstream result.",
                    "invalidation_frontier": ["downstream"],
                    "cycle_scope": self._cycle_scope,
                }
            )
        return result

    @activity.defn(name="operation.cancel")
    async def cancel_operation(self, request: dict[str, Any]) -> dict[str, Any]:
        """RRM-008: the fixture settlement of a cancelled unit (the boundary's result shape)."""

        self.cancel_settlements.append(str(request["identity"]["operation_id"]))
        return cancelled_operation_result(request)

    @property
    def functions(self) -> list[object]:
        return [
            self.initialize,
            self.admit,
            self.decide,
            self.apply_cycle,
            self.complete,
            self.execute_operation,
            self.cancel_operation,
        ]


def _run_input(graph: StageGraphBlueprint) -> StageGraphRunInput:
    return StageGraphRunInput(
        run_id="run-wp-bp-010-temporal",
        request_scope="tenant-1",
        effective_configuration_digest=DIGEST,
        workflow_type_digest=DIGEST,
        blueprint_digest=sha256_digest(graph),
        blueprint=graph.model_dump(mode="json"),
        initial_run_version=1,
        max_concurrency=3,
        task_timeout_seconds=10,
        correlation_id="stagegraph:temporal-test",
        semantic_input_binding_ref="semantic-input:test",
    )


class RecordingOperationBindings:
    def __init__(self) -> None:
        self.bindings: list[object] = []

    async def create_binding(self, binding: Any, *, request_scope: str) -> Any:
        self.bindings.append(binding)
        return binding

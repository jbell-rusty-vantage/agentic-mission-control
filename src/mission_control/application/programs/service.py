from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import TypeAdapter

from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.context.linked_transfer import LinkedExportPort
from mission_control.application.context.pack_service import ArtifactBytesPort, ContextPackService
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.execution.operations.semantic_operation_bindings import (
    SemanticOperationBindingRepository,
)
from mission_control.application.execution.run_control_repository import RunControlRepository
from mission_control.application.execution.service import (
    ACTION_PERMISSIONS,
    FamilyAdmissionRegistry,
    RunControlService,
)
from mission_control.application.human_tasks.service import HumanTaskRepository
from mission_control.application.programs.completion_validation import (
    ArtifactPublicationPending,
    expire_pending,
    validate_completion,
    validated_result,
)
from mission_control.application.programs.linked_context import attach_linked_context
from mission_control.application.programs.named_outputs import NamedStageOutputs
from mission_control.application.programs.orchestration_binding_repository import (
    RunSemanticInputBindingService,
)
from mission_control.application.programs.route_facts import attribute_route_facts
from mission_control.application.resolution.lane_bindings import LaneInvocation, LaneRebinders
from mission_control.application.subordinates.parent_effects import ASYNC_CHILD_EFFECT_KIND
from mission_control.domain.authoring.canonical import (
    contract_fingerprint,
    sha256_digest,
    stable_json_dump,
)
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    GoalDirectedBlueprint,
    StageGraphBlueprint,
    StageNode,
)
from mission_control.domain.authoring.identity import stable_id
from mission_control.domain.context import transfer_builders
from mission_control.domain.context.packet import PackCandidate
from mission_control.domain.context.transfer import Placement, TransferSelection
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
    OperationWorkflowRequest,
    PromptSegment,
    WorkspaceContract,
)
from mission_control.domain.execution.heartbeats import (
    DEFAULT_OPERATION_HEARTBEATS,
    OperationHeartbeatPolicy,
)
from mission_control.domain.execution.lane_turns import default_lane_profile
from mission_control.domain.outputs.contracts import ExactOutput, OutputPromiseSet
from mission_control.domain.policies.contracts import (
    AcceptedObligationEvidence,
    AcceptedOperationSettlementEvidence,
    AcceptedOutputEvidence,
    ActorContext,
    AdmitHumanGateAction,
    ApplyAuthorityBatchAction,
    BudgetState,
    CommandStatus,
    EffectLedgerState,
    LifecycleAction,
    LifecycleCommand,
    RecordAdmissionRejectionAction,
    RecordObligationEvidenceAction,
    RecordOperationSettlementEvidenceAction,
    RecordOutputEvidenceAction,
    RecordUsageAction,
    ReserveBudgetAction,
    RunOutcome,
    RunPhase,
    StartAction,
    TerminalizationProposal,
    TerminalizeAction,
)
from mission_control.domain.policies.errors import IdempotencyConflict, RunVersionConflict
from mission_control.domain.policies.family_admission import (
    AtomicFamilyMutation,
    AuthorityStateConflict,
    FamilyAdmissionReceipt,
)
from mission_control.domain.policies.reducer import conclusive_budget_rejection
from mission_control.domain.programs.bindings import RunSemanticInputBinding
from mission_control.domain.programs.completion import CompletionValidation
from mission_control.domain.programs.contracts import (
    CompletionCandidateRecord,
    CompletionDecisionRecord,
    CompletionDisposition,
    CompletionRecords,
    GoalDirectedRunInput,
    GoalRevision,
    LifecycleCommandOutcome,
    LifecycleCommandRequest,
    ResultDispositionProposal,
    StageAuthoredInput,
    StageExecutionIdentity,
    StageGraphAcceptedProjection,
    StageGraphAdmissionActivityRequest,
    StageGraphAdmissionActivityResult,
    StageGraphAdmissionRejectionMutation,
    StageGraphBaselineSettlementRequest,
    StageGraphBaselineSettlementResult,
    StageGraphCompletionActivityRequest,
    StageGraphCompletionActivityResult,
    StageGraphCompletionProposal,
    StageGraphControlAdmissionMutation,
    StageGraphCycleActivityRequest,
    StageGraphCycleActivityResult,
    StageGraphDecisionMutation,
    StageGraphInitializeRequest,
    StageGraphInitializeResult,
    StageGraphResultActivityRequest,
    StageGraphResultActivityResult,
    StageGraphRunInput,
    StageInvalidationProposal,
    StageOperationAdmissionProposal,
    StageOperationRequest,
    StageOperationResult,
    StageResultObservation,
    WorkflowEvaluationRequest,
    WorkflowEvaluationResult,
    WorkflowInvalidationProposal,
    admission_proposal_payload,
)
from mission_control.domain.programs.human_gate import (
    HumanGateOutcome,
    HumanGateSpec,
    bind_outcome,
    outcome_for,
    stagegraph_gate_result,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from mission_control.domain.programs.routing import ROUTE_FACTS_KEY
from mission_control.domain.programs.runtime_units import stage_runtime_unit

if TYPE_CHECKING:
    from mission_control.application.programs.nested_bodies import NestedActivationStore

LIFECYCLE_ACTION_ADAPTER: TypeAdapter[LifecycleAction] = TypeAdapter(LifecycleAction)
ORCHESTRATION_AUTHORITY_REF = "orchestration-authority"


def orchestration_lifecycle_actor() -> ActorContext:
    """Return the least-privilege service identity for workflow lifecycle commands."""

    return ActorContext(
        actor_id=ORCHESTRATION_AUTHORITY_REF,
        authority_refs=frozenset({ORCHESTRATION_AUTHORITY_REF}),
        permissions=frozenset(ACTION_PERMISSIONS.values()),
    )


def _completion_payload(proposal: StageGraphCompletionProposal) -> dict[str, object]:
    """The recorded completion decision; the MP-20 concluded-failure fields are additive and
    omitted when absent, so every other completion records exactly what it did before."""

    payload = asdict(proposal)
    if not proposal.failed:
        payload.pop("failed")
        payload.pop("skipped_stage_ids")
    # OVE-171: route outcomes are recorded only for a graph that declares routes.
    if not proposal.route_skipped_stage_ids:
        payload.pop("route_skipped_stage_ids")
    if not proposal.route_decisions:
        payload.pop("route_decisions")
    if not proposal.revisit_decisions:
        payload.pop("revisit_decisions")
    if not proposal.unmet_reasons:
        payload.pop("unmet_reasons")
    return payload


def admission_proposal_with_unit_keys(
    proposal: StageOperationAdmissionProposal, request_scope: str
) -> StageOperationAdmissionProposal:
    """1.4.4 (P3.8): the unit keys of `released_by` producers and the `continues_from`
    prior attempt. The pure interpreter carries their identities; the key needs the
    request scope, so the admitting service fills it once the proposal passed the
    authoritative-frontier check (the comparison is made before the keys are added)."""

    released = tuple(
        replace(
            item,
            producer_unit_key=stage_runtime_unit(request_scope, item.producer_identity).unit_key,
        )
        if item.producer_identity is not None
        else item
        for item in proposal.released_by
    )
    continues = proposal.continues_from
    if continues is not None:
        continues = replace(
            continues,
            prior_unit_key=stage_runtime_unit(request_scope, continues.prior_identity).unit_key,
        )
    return replace(proposal, released_by=released, continues_from=continues)


def completion_disposition(
    proposal: ResultDispositionProposal,
    *,
    operation_disposition: str,
    evaluation: str,
) -> CompletionDisposition:
    """The `completion_decision.result_disposition` of a Stage Graph result (P10 decision
    table, Stage 1 mapping), in precedence order:

    - a cancelled operation -> `abandoned` (the cancellation, not the result, decided);
    - a result whose evaluation asks for a cycle -> `needs_more_work`;
    - an evaluation of `degrade` or `escalate` -> `abandoned`;
    - an admitted result -> `accepted`;
    - everything else (a rejected result, a completion validation failure, a quarantine,
      a failed or in-doubt operation) -> `rejected`.
    """

    if operation_disposition == "cancelled":
        return "abandoned"
    if evaluation == "cycle":
        return "needs_more_work"
    if evaluation in {"degrade", "escalate"}:
        return "abandoned"
    if proposal.decision.value == "admit":
        return "accepted"
    return "rejected"


def _string_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value)


def stage_completion_records(
    *,
    stage: StageNode,
    proposal: ResultDispositionProposal,
    observation: StageResultObservation,
    validation: CompletionValidation | None,
    reason_codes: tuple[str, ...],
    unit_key: str,
    decision_key: str,
) -> CompletionRecords:
    """1.4.4 (P3.8): the decision-table rows of one `result_decided`. The candidate is the
    settlement's result manifest (refs and digests, keyed by the settlement id the result
    evidence carries) and exists only for a completed operation; the decision is keyed by
    the mutation id. `policy_digest` digests the stage's completion requirements (output,
    obligation and schema criteria); `contract_digest` digests the result's output
    contract refs. Unused columns stay NULL."""

    result = observation.operation_result
    output_refs = _string_refs(result.get("output_refs", ()))
    obligation_refs = _string_refs(result.get("obligation_refs", ()))
    evaluation = str(result.get("evaluation") or "")
    output_contract_ref = result.get("output_contract_ref")
    # The owner's rule (TRACING-PROPOSAL §P10): `candidate_key = settlement_id`, the
    # operation settlement the result came from (`operation_settlement_id(binding_id)`,
    # which the operation result names); the family's own settlement evidence id is the
    # fallback for an observation without a binding.
    binding_id = result.get("binding_id")
    candidate_key = (
        stable_id("operation-settlement", str(binding_id))
        if isinstance(binding_id, str) and binding_id
        else f"stagegraph-result:{observation.identity.semantic_key}"
    )
    candidate: CompletionCandidateRecord | None = None
    if observation.operation_disposition == "completed":
        candidate = CompletionCandidateRecord(
            candidate_key=candidate_key,
            activation_key=unit_key,
            execution_generation=observation.identity.execution_generation,
            candidate={
                "output_refs": list(output_refs),
                "obligation_refs": list(obligation_refs),
                "output_contract_ref": (str(output_contract_ref) if output_contract_ref else None),
                "observation_digest": sha256_digest(result),
                "evaluation": evaluation or None,
            },
            artifact_refs=output_refs,
            evidence_refs=obligation_refs,
        )
    # Set-order independent (`stable_json_dump` sorts sets; a JSON-mode dump does not).
    requirements = stable_json_dump(stage)
    policy_digest = sha256_digest(
        {
            "stage_id": stage.stage_id,
            "output_slots": requirements.get("output_slots", []),
            "obligation_slots": requirements.get("obligation_slots", []),
            "schema_criteria": requirements.get("schema_criteria", []),
        }
    )
    contract_digest = sha256_digest(
        {
            "output_contract_ref": str(output_contract_ref) if output_contract_ref else None,
            "output_contract_refs": sorted(slot.output_contract_ref for slot in stage.output_slots),
        }
    )
    decision = CompletionDecisionRecord(
        decision_key=decision_key,
        activation_key=unit_key,
        candidate_key=candidate_key if candidate is not None else None,
        policy_digest=policy_digest,
        contract_digest=contract_digest,
        result_disposition=completion_disposition(
            proposal,
            operation_disposition=observation.operation_disposition,
            evaluation=evaluation,
        ),
        requirement_refs=tuple(slot.obligation_ref for slot in stage.obligation_slots),
        result_refs=output_refs,
        reason_codes=reason_codes,
        decision={
            "decision": proposal.decision.value,
            "matched_veto": proposal.matched_veto,
            "matched_rule_id": proposal.matched_rule_id,
            "quarantine_reason": proposal.quarantine_reason,
            "dependency_dispositions": {
                key: value.value for key, value in proposal.dependency_dispositions.items()
            },
            "operation_disposition": observation.operation_disposition,
            "evaluation": evaluation or None,
            "completion_validation": validation.status if validation else "not_evaluated",
        },
    )
    return CompletionRecords(candidate=candidate, decision=decision)


def _prior_cycle_unit_key(
    projection: StageGraphAcceptedProjection,
    proposal: StageInvalidationProposal,
    request_scope: str,
) -> str | None:
    """The unit a stage cycle advances from: the latest attempt of the invalidated stage at
    the prior stage cycle (None when no attempt ran)."""

    priors = [
        item
        for item in projection.stages.values()
        if item.candidate.stage_id == proposal.stage_id
        and item.candidate.workflow_cycle_ordinal == projection.workflow_cycle_ordinal
        and item.candidate.stage_cycle_ordinal == proposal.prior_stage_cycle_ordinal
        and item.semantic_attempt > 0
    ]
    if not priors:
        return None
    prior = max(priors, key=lambda item: (item.semantic_attempt, item.candidate.semantic_prefix))
    identity = StageExecutionIdentity(
        run_id=projection.identity.run_id,
        execution_epoch=projection.identity.execution_epoch,
        candidate=prior.candidate,
        semantic_attempt=prior.semantic_attempt,
    )
    return stage_runtime_unit(request_scope, identity).unit_key


class OrchestrationBindingVerifier(Protocol):
    async def verify(
        self,
        effective_configuration_digest: str,
        blueprint_digest: str,
    ) -> None: ...


class F1OrchestrationBindingVerifier:
    def __init__(self, control_plane: ControlPlaneService) -> None:
        self._control_plane = control_plane

    async def verify(
        self,
        effective_configuration_digest: str,
        blueprint_digest: str,
    ) -> None:
        configuration = await self._control_plane.retrieve_for_admission(
            effective_configuration_digest
        )
        blueprint_ref = next(
            (ref for ref in configuration.source_refs if ref.kind == DefinitionKind.BLUEPRINT),
            None,
        )
        if (
            configuration.digest != effective_configuration_digest
            or blueprint_ref is None
            or blueprint_ref.digest != blueprint_digest
            or sha256_digest(configuration.selected_blueprint) != blueprint_digest
        ):
            raise ValueError("orchestration blueprint does not match the admitted F1 binding")


class StageGraphLaunchService:
    """Resolves exact admitted F1/F2 bindings before Temporal receives immutable input."""

    def __init__(
        self,
        run_control: RunControlService,
        control_plane: ControlPlaneService,
    ) -> None:
        self._run_control = run_control
        self._control_plane = control_plane

    async def prepare(
        self,
        request_scope: str,
        run_id: str,
        *,
        execution_epoch: int = 1,
        task_timeout_seconds: int = 30,
        orchestration_authority_ref: str = ORCHESTRATION_AUTHORITY_REF,
        semantic_input_binding_ref: str = "",
        human_gates: tuple[HumanGateSpec, ...] = (),
        authored_inputs: tuple[StageAuthoredInput, ...] = (),
    ) -> StageGraphRunInput:
        if execution_epoch != 1:
            raise ValueError(
                "execution epoch rollover requires the deferred orchestration continuity contract"
            )
        projection = await self._run_control.get_run(request_scope, run_id)
        configuration = await self._control_plane.retrieve_for_admission(
            projection.effective_configuration_digest
        )
        if configuration.digest != projection.effective_configuration_digest:
            raise ValueError("admitted effective configuration digest does not match F1 authority")
        blueprint = configuration.selected_blueprint
        if not isinstance(blueprint, StageGraphBlueprint):
            raise ValueError("admitted blueprint is not a StageGraph")
        blueprint_ref = next(
            (ref for ref in configuration.source_refs if ref.kind == DefinitionKind.BLUEPRINT),
            None,
        )
        if blueprint_ref is None or blueprint_ref.digest != sha256_digest(blueprint):
            raise ValueError("exact StageGraph reference does not match the frozen blueprint")
        _check_authored_inputs(authored_inputs, blueprint)
        budget = await self._run_control.get_budget(request_scope, run_id)
        # MP-10: a stage that runs as a Human Gate is its own human control; the manifest
        # lowering's same-id stage wait (pre-MP-10 authoring) is superseded by it, or the gate
        # child would never start.
        gate_keys = {gate.gate_key for gate in human_gates}
        superseded_waits = tuple(
            sorted(
                wait.wait_id
                for wait in blueprint.waits
                if wait.scope_kind == "stage"
                and wait.scope_id in gate_keys
                and wait.wait_id == wait.scope_id
            )
        )
        return StageGraphRunInput(
            run_id=run_id,
            request_scope=request_scope,
            effective_configuration_digest=configuration.digest,
            workflow_type_digest=projection.workflow_type_ref.digest,
            blueprint_digest=blueprint_ref.digest,
            blueprint=blueprint.model_dump(mode="json"),
            initial_run_version=projection.version,
            execution_epoch=execution_epoch,
            max_concurrency=configuration.effective_authority.max_concurrency,
            task_timeout_seconds=task_timeout_seconds,
            orchestration_authority_ref=orchestration_authority_ref,
            correlation_id=f"orchestration:{run_id}:epoch:{execution_epoch}",
            baseline_reservation=dict(budget.reservations.get("baseline", {})),
            semantic_input_binding_ref=semantic_input_binding_ref,
            human_gates=human_gates,
            satisfied_wait_ids=superseded_waits,
            authored_inputs=authored_inputs,
        )


def _check_authored_inputs(
    authored_inputs: tuple[StageAuthoredInput, ...], blueprint: StageGraphBlueprint
) -> None:
    """MP-20: every authored input names a dependency of the frozen blueprint, once."""

    edges = {(item.consumer_stage_id, item.producer_stage_id) for item in blueprint.dependencies}
    seen: set[tuple[str, str]] = set()
    for item in authored_inputs:
        if (item.consumer_stage_id, item.producer_stage_id) not in edges:
            raise ValueError(
                f"authored input {item.consumer_stage_id}.{item.name} is not delivered by a "
                f"dependency on {item.producer_stage_id} of the frozen blueprint"
            )
        key = (item.consumer_stage_id, item.name)
        if key in seen:
            raise ValueError(f"authored input {item.consumer_stage_id}.{item.name} is duplicated")
        seen.add(key)


# Completion proposals one StageGraph run may make (each rejected one keeps its receipt).
MAX_COMPLETION_PROPOSALS = 256
# RRM-021: a baseline release retried at the reported version while outside commands move it.
BASELINE_SETTLEMENT_ATTEMPTS = 4


def producer_effects_settled(
    effects: EffectLedgerState,
    *,
    cancelled_binding_id: str | None = None,
    producer_reservation_id: str | None = None,
    producer_side_effect_key: str | None = None,
) -> bool:
    """Whether a producer's result may close its liability on the run's effects.

    Every claimed effect must be settled, with one exception under cancellation (RRM-008
    steps 4-5, composed by RRM-009): the async children of a unit the saga settled
    `cancelled` were reached by that saga, and a child whose provider attributed no usage
    keeps it pending on the child's own effect. That pending usage is a liability of the
    run's terminal settlement (the reducer refuses `cancelled` until a privileged usage
    reconciliation; the family waits for it), not of the producer, exactly as the operation
    boundary does not park the cancelled unit on it (`_settle_cancelled`). Without this,
    a StageGraph run cancelled while its unit's async child ran failed its family with
    "cancellation left a producer liability open" (found by the RRM-009 live drill).
    """

    claims = tuple(effects.claims.values())
    if producer_reservation_id is not None or producer_side_effect_key is not None:
        if producer_reservation_id is None or producer_side_effect_key is None:
            return False
        owners = tuple(
            claim
            for claim in claims
            if (
                claim.effect_kind == "operation.runtime"
                and claim.reservation_id == producer_reservation_id
                and claim.provider_idempotency_key == producer_side_effect_key
            )
        )
        if len(owners) != 1:
            return False
        binding_id = owners[0].operation_ref
        if cancelled_binding_id is not None and cancelled_binding_id != binding_id:
            return False
        # Runtime/tool/async-child claims retain their exact immutable parent binding.
        # A parallel sibling's open claim is a run liability, never this producer's.
        claims = tuple(claim for claim in claims if claim.operation_ref == binding_id)
    return all(
        claim.settlement is not None
        or (
            cancelled_binding_id is not None
            and claim.effect_kind == ASYNC_CHILD_EFFECT_KIND
            and claim.operation_ref == cancelled_binding_id
        )
        for claim in claims
    )


class StageGraphHumanGateProvider(Protocol):
    async def verify(
        self, request: StageGraphAdmissionActivityRequest
    ) -> tuple[HumanGateSpec, ...]: ...


class StageGraphDecisionService:
    """Commit StageGraph proposals through the frozen atomic family seam."""

    def __init__(
        self,
        run_control: RunControlService,
        repository: RunControlRepository,
        *,
        artifacts: ArtifactBytesPort | None = None,
        human_gates: StageGraphHumanGateProvider | None = None,
        named_outputs: NamedStageOutputs | None = None,
        human_tasks: HumanTaskRepository | None = None,
        nested_activations: NestedActivationStore | None = None,
    ) -> None:
        self._run_control = run_control
        self._repository = repository
        self._artifacts = artifacts
        self._human_gates = human_gates
        self._named_outputs = named_outputs
        self._human_tasks = human_tasks
        self._nested_activations = nested_activations

    async def initialize(self, request: StageGraphInitializeRequest) -> StageGraphInitializeResult:
        expected_run_version = request.expected_run_version
        for attempt in range(2):
            result = await self._run_control.execute(
                LifecycleCommand(
                    # RRM-008: an outside command accepted between admission and the start
                    # fact (a cancel) moved the version; the start is retried once at the
                    # version the stale result reports, under a new command identity.
                    command_id=(
                        f"stagegraph:{request.run_id}:start"
                        if attempt == 0
                        else f"stagegraph:{request.run_id}:start:at-version:{expected_run_version}"
                    ),
                    idempotency_issuer=request.idempotency_issuer,
                    request_scope=request.request_scope,
                    run_id=request.run_id,
                    expected_run_version=expected_run_version,
                    actor=orchestration_lifecycle_actor(),
                    action=StartAction(execution_target=request.execution_target),
                    reason="Canonical StageGraph execution started",
                    occurred_at=request.occurred_at,
                    correlation_id=request.correlation_id,
                )
            )
            if result.status != CommandStatus.STALE:
                break
            expected_run_version = result.resulting_run_version
        projection = replace(
            request.initial_projection,
            run_version=result.resulting_run_version,
        )
        return StageGraphInitializeResult(
            accepted=result.status == CommandStatus.ACCEPTED,
            projection=projection,
            reason_code=result.reason_code,
            phase=result.phase.value,
        )

    async def admit_operation(
        self, request: StageGraphAdmissionActivityRequest
    ) -> StageGraphAdmissionActivityResult:
        if request.control_gate_keys or request.human_gate is not None:
            if self._human_gates is None:
                raise ValueError("trusted Human Gate admission provider is not configured")
            gates = await self._human_gates.verify(request)
            expected_gate = next(
                (gate for gate in gates if gate.gate_key == request.proposal.identity.stage_id),
                None,
            )
            if request.human_gate != expected_gate:
                raise ValueError("candidate does not match the admitted Human Gate policy")
        prior_control = None
        if request.human_gate is not None:
            prior_control = await self._repository.get_family_admission_receipt(
                request.request_scope,
                request.run_id,
                request.idempotency_issuer,
                f"stagegraph:admit-{sha256_digest(request.proposal.identity.semantic_key)[7:]}",
            )
        prior_rejection = None
        if request.conclude_budget_rejection:
            prior_rejection = await self._repository.get_family_mutation(
                request.request_scope,
                request.run_id,
                "stagegraph",
                f"reject-{sha256_digest(request.proposal.identity.semantic_key)[7:]}",
                StageGraphDecisionMutation,
            )
        if prior_control is None and prior_rejection is None:
            await self._verify_family_head(
                request.request_scope, request.run_id, request.projection
            )
        proposal = request.proposal
        operation = request.operation
        if operation is None:
            raise ValueError("StageGraph admission requires a materialized operation request")
        interpreter = StageGraphInterpreter(
            StageGraphBlueprint.model_validate(request.blueprint),
            effective_max_concurrency=request.effective_max_concurrency,
            control_gate_keys=frozenset(request.control_gate_keys),
        )
        available_concurrency = max(
            request.effective_max_concurrency - interpreter.running_concurrency(request.projection),
            0,
        )
        authoritative_frontier = interpreter.frontier(
            request.projection,
            available_concurrency=available_concurrency,
        )
        if not authoritative_frontier or authoritative_frontier[0] != proposal:
            raise ValueError("StageGraph admission proposal is stale or not authoritative")
        if (
            operation.semantic_attempt_id != proposal.identity.semantic_key
            or operation.operation.identity.run_id != request.run_id
            or operation.operation.budget_reservation_id != proposal.reservation_id
            or operation.operation.run_control_revision != request.projection.run_version + 1
        ):
            raise ValueError("exact operation request does not match StageGraph admission")
        next_projection = interpreter.apply_admission(
            request.projection,
            proposal,
            next_run_version=request.projection.run_version + 1,
            next_family_version=request.projection.family_version + 1,
        )
        # 1.4.4 (P3.8): the proposal is recorded with the unit keys of what released it.
        proposal = admission_proposal_with_unit_keys(proposal, request.request_scope)
        unit_key = stage_runtime_unit(request.request_scope, proposal.identity).unit_key
        mutation = self._mutation(
            request.projection,
            next_projection,
            decision_kind="operation_admitted",
            mutation_id=f"admit-{sha256_digest(proposal.identity.semantic_key)[7:]}",
            exact_operation_request_ref=proposal.exact_operation_request_ref,
            request_scope=request.request_scope,
            decided_at=request.occurred_at,
            decision_payload={"proposal": admission_proposal_payload(proposal)},
        )
        action: LifecycleAction = ReserveBudgetAction(
            reservation_id=proposal.reservation_id, amounts=proposal.reservation
        )
        if request.human_gate is not None:
            if proposal.reservation:
                raise ValueError("Human Gate admission may not reserve cognitive resources")
            mutation = StageGraphControlAdmissionMutation.model_validate(
                {
                    **mutation.model_dump(mode="python"),
                    "decision_kind": "control_admitted",
                    "decision_payload": {
                        **mutation.decision_payload,
                        "human_gate": request.human_gate.model_dump(mode="json"),
                    },
                }
            )
            action = AdmitHumanGateAction(
                gate_key=request.human_gate.gate_key,
                gate_spec_digest=sha256_digest(request.human_gate),
                exact_operation_request_ref=proposal.exact_operation_request_ref,
            )
        reserve_command = LifecycleCommand(
            command_id=f"stagegraph:{mutation.mutation_id}",
            idempotency_issuer=request.idempotency_issuer,
            request_scope=request.request_scope,
            run_id=request.run_id,
            expected_run_version=request.projection.run_version,
            actor=orchestration_lifecycle_actor(),
            action=action,
            reason="Atomically admit StageGraph operation and advance fairness cursors",
            evidence_refs=(proposal.exact_operation_request_ref,),
            occurred_at=request.occurred_at,
            correlation_id=request.correlation_id,
            unit_key=unit_key,
        )
        try:
            # Loop iter-1 L1-03: a version that moved under a parallel sibling is transient.
            # Persisting a STALE receipt would bind this admission's command identity to the
            # old version, so every correct re-admission would conflict; refuse it unrecorded.
            receipt = await self._run_control.execute_family_admission(
                reserve_command, mutation, transient_version_conflict=True
            )
        except (RunVersionConflict, AuthorityStateConflict):
            # Loop iter-2 L2-01: return the run's live version so the workflow can retry this
            # sibling now rather than after the running one completes. The family head did not
            # move, so the semantic projection (and its digest, which excludes run_version) is
            # the caller's.
            run = await self._run_control.get_run(request.request_scope, request.run_id)
            live_version = max(run.version, request.projection.run_version)
            return StageGraphAdmissionActivityResult(
                accepted=False,
                projection=replace(request.projection, run_version=live_version),
                operation=None,
                reason_code="stale_run_version",
            )
        accepted = receipt.command_result.status == CommandStatus.ACCEPTED
        if (
            not accepted
            and request.conclude_budget_rejection
            and request.human_gate is None
            and receipt.command_result.status == CommandStatus.REJECTED
            and receipt.command_result.reason_code == "budget_hard_cap_exceeded"
        ):
            return await self._record_admission_rejection(
                request, reserve_command, receipt, interpreter
            )
        return StageGraphAdmissionActivityResult(
            accepted=accepted,
            projection=next_projection if accepted else request.projection,
            operation=operation if accepted else None,
            reason_code=receipt.command_result.reason_code,
        )

    async def _record_admission_rejection(
        self,
        request: StageGraphAdmissionActivityRequest,
        rejected: LifecycleCommand,
        receipt: FamilyAdmissionReceipt,
        interpreter: StageGraphInterpreter,
    ) -> StageGraphAdmissionActivityResult:
        if not isinstance(rejected.action, ReserveBudgetAction):
            raise ValueError("only a rejected reservation can conclude admission")
        budget = await self._run_control.get_budget(request.request_scope, request.run_id)
        if not conclusive_budget_rejection(budget, rejected.action):
            return StageGraphAdmissionActivityResult(
                accepted=False,
                projection=request.projection,
                operation=None,
                reason_code=receipt.command_result.reason_code,
            )
        proposal = request.proposal
        mutation_id = f"reject-{sha256_digest(proposal.identity.semantic_key)[7:]}"
        next_projection = interpreter.apply_admission_rejection(
            request.projection,
            proposal,
            next_run_version=request.projection.run_version + 1,
            next_family_version=request.projection.family_version + 1,
        )
        mutation = StageGraphAdmissionRejectionMutation.model_validate(
            self._mutation(
                request.projection,
                next_projection,
                decision_kind="admission_rejected",
                mutation_id=mutation_id,
                exact_operation_request_ref=proposal.exact_operation_request_ref,
                request_scope=request.request_scope,
                decided_at=request.occurred_at,
                decision_payload={
                    # Tracing Stage 3 (R2-17): the recorded proposal form (as the admission).
                    "proposal": admission_proposal_payload(proposal),
                    "rejected_command": rejected.model_dump(mode="json"),
                    "rejected_family_fingerprint": receipt.family_mutation_fingerprint,
                },
            ).model_dump(mode="python")
        )
        actual = await self._run_control.execute_family_admission(
            LifecycleCommand(
                command_id=f"stagegraph:{mutation_id}",
                idempotency_issuer=request.idempotency_issuer,
                request_scope=request.request_scope,
                run_id=request.run_id,
                expected_run_version=request.projection.run_version,
                actor=orchestration_lifecycle_actor(),
                action=RecordAdmissionRejectionAction(
                    stage_id=proposal.identity.stage_id,
                    rejected_command_id=rejected.command_id,
                    rejected_command_issuer=rejected.idempotency_issuer,
                    rejected_command_fingerprint=receipt.command_result.command_fingerprint,
                    rejected_family_fingerprint=receipt.family_mutation_fingerprint,
                    exact_operation_request_ref=proposal.exact_operation_request_ref,
                ),
                reason="Conclude persisted budget admission rejection; no execution ran",
                evidence_refs=(f"command:{rejected.idempotency_issuer}:{rejected.command_id}",),
                occurred_at=request.occurred_at,
                correlation_id=request.correlation_id,
            ),
            mutation,
        )
        accepted = actual.command_result.status == CommandStatus.ACCEPTED
        return StageGraphAdmissionActivityResult(
            accepted=False,
            projection=next_projection if accepted else request.projection,
            operation=None,
            reason_code="budget_hard_cap_exceeded"
            if accepted
            else actual.command_result.reason_code,
        )

    async def decide_result(
        self, request: StageGraphResultActivityRequest
    ) -> StageGraphResultActivityResult:
        for _attempt in range(8):
            try:
                return await self._decide_result_once(request)
            except (RunVersionConflict, AuthorityStateConflict):
                continue
        raise AuthorityStateConflict("StageGraph result authority changed during every retry")

    async def _decide_result_once(
        self, request: StageGraphResultActivityRequest
    ) -> StageGraphResultActivityResult:
        replayed = await self._replay_result(request)
        if replayed is not None:
            return replayed
        await self._verify_family_head(
            request.request_scope,
            request.run_id,
            request.projection,
        )
        blueprint = StageGraphBlueprint.model_validate(request.blueprint)
        interpreter = StageGraphInterpreter(
            blueprint,
            effective_max_concurrency=request.effective_max_concurrency,
        )
        run = await self._run_control.get_run(request.request_scope, request.run_id)
        facts = replace(
            request.late_facts,
            run_cancelling=request.late_facts.run_cancelling or run.phase.value == "cancelling",
            run_terminal=request.late_facts.run_terminal or run.phase.value == "terminal",
        )
        stage = next(
            item
            for item in blueprint.stages
            if item.stage_id == request.observation.identity.candidate.stage_id
        )
        validation = None
        fulfilled_named: Mapping[str, ExactOutput] = {}
        observation = request.observation
        proposal = interpreter.result_decision(
            observation.identity,
            facts,
            operation_disposition=observation.operation_disposition,
            operation_result=observation.operation_result,
        )
        structurally_invalid = any(
            not reason.startswith("outputs_missing:")
            for reason in interpreter.result_validation_errors(
                observation.identity, observation.operation_result
            )
        )
        if (
            self._named_outputs is not None
            and blueprint.output_promises is not None
            and proposal.decision.value != "quarantine"
            and observation.operation_disposition == "completed"
            and not structurally_invalid
        ):
            named = await self._named_outputs.reconcile_with_validation(
                request.request_scope,
                observation.identity,
                stage,
                observation.operation_result,
            )
            observation = replace(observation, operation_result=named.result)
            validation = named.validation
            fulfilled_named = named.fulfilled
            proposal = interpreter.result_decision(
                observation.identity,
                facts,
                operation_disposition=observation.operation_disposition,
                operation_result=observation.operation_result,
            )
        if (
            proposal.decision.value != "quarantine"
            and observation.operation_disposition == "completed"
            and not structurally_invalid
            and (
                stage.schema_criteria or any(slot.validation_schema for slot in stage.output_slots)
            )
        ):
            if validation is None:
                validation = await validate_completion(
                    self._artifacts,
                    request_scope=request.request_scope,
                    stage=stage,
                    interpreter=interpreter,
                    operation_result=observation.operation_result,
                )
            if validation.status == "pending":
                if datetime.now(UTC) < request.occurred_at + timedelta(minutes=15):
                    raise ArtifactPublicationPending(
                        "declared output artifact is not published yet"
                    )
                validation = expire_pending(validation)
            observation = replace(
                observation,
                operation_result=validated_result(observation.operation_result, validation),
            )
            proposal = interpreter.result_decision(
                observation.identity,
                facts,
                operation_disposition=observation.operation_disposition,
                operation_result=observation.operation_result,
                completion_valid=validation.status == "satisfied",
            )
        if stage.facts or ROUTE_FACTS_KEY in observation.operation_result:
            # OVE-171: the host attributes route facts from the exact accepted output bytes;
            # a provider-supplied `route_facts` key never survives.
            observation = replace(
                observation,
                operation_result=await attribute_route_facts(
                    self._artifacts if proposal.decision.value == "admit" else None,
                    request_scope=request.request_scope,
                    stage=stage,
                    interpreter=interpreter,
                    operation_result=observation.operation_result,
                    # The exact bytes the completion validation accepted (S4 review pin).
                    validated_digests={
                        check.artifact_ref: check.artifact_digest
                        for check in (validation.checks if validation is not None else ())
                        if check.artifact_ref and check.artifact_digest
                    },
                    # L1-02: a named (`submit_output`) value is read from its accepted revision.
                    fulfilled=fulfilled_named if proposal.decision.value == "admit" else None,
                ),
            )
        current_projection = replace(request.projection, run_version=run.version)
        effects = await self._run_control.get_effects(request.request_scope, request.run_id)
        budget = await self._run_control.get_budget(request.request_scope, request.run_id)
        liability = current_projection.producer_liabilities[observation.identity.semantic_key]
        side_effect_key = (
            f"stagegraph:{observation.identity.semantic_key}:"
            f"generation:{observation.identity.execution_generation}"
        )
        own_claims = tuple(
            claim
            for claim in effects.claims.values()
            if (
                claim.effect_kind == "operation.runtime"
                and claim.reservation_id == liability.reservation_id
                and claim.provider_idempotency_key == side_effect_key
            )
        )
        cancelled_binding = (
            own_claims[0].operation_ref
            if len(own_claims) == 1
            and run.phase.value == "cancelling"
            and request.observation.operation_disposition == "cancelled"
            else None
        )
        scoped_effects_settled = producer_effects_settled(
            effects,
            cancelled_binding_id=cancelled_binding,
            producer_reservation_id=liability.reservation_id,
            producer_side_effect_key=side_effect_key,
        )
        if not own_claims:
            scoped_effects_settled = await self._nonoperation_effects_settled(
                request,
                liability.reservation_id,
                budget,
                effects,
            )
        observation = replace(
            observation,
            reservations_and_usage_settled=True,
            effects_settled=scoped_effects_settled,
            cancellation_reconciled=(
                run.phase.value != "cancelling" or request.observation.cancellation_reconciled
            ),
        )
        if liability.reservation_id in budget.reservations:
            raise ValueError("operation usage reservation is not authoritatively settled")
        reservation_id = next(
            (
                instance.admitted_operation_request_ref
                for instance in current_projection.stages.values()
                if instance.candidate == request.observation.identity.candidate
            ),
            None,
        )
        if reservation_id is None:
            raise ValueError("StageGraph result has no admitted operation reference")
        next_projection = interpreter.apply_result_decision(
            current_projection,
            observation,
            proposal,
            next_run_version=current_projection.run_version + 1,
            next_family_version=current_projection.family_version + 1,
        )
        unit_key = stage_runtime_unit(request.request_scope, observation.identity).unit_key
        mutation_id = f"result-{sha256_digest(observation.identity.semantic_key)[7:]}"
        reason_codes = tuple(
            validation.reason_codes
            if validation
            else interpreter.result_validation_errors(
                observation.identity, observation.operation_result
            )
        )
        mutation = self._mutation(
            current_projection,
            next_projection,
            decision_kind="result_decided",
            mutation_id=mutation_id,
            exact_operation_request_ref=reservation_id,
            request_scope=request.request_scope,
            decided_at=request.occurred_at,
            decision_payload={
                "proposal": asdict(proposal),
                "result_request_digest": sha256_digest(asdict(request)),
                "prior_liability": asdict(liability),
                "observation_digest": sha256_digest(observation.operation_result),
                "completion_validation": validation.model_dump(mode="json")
                if validation
                else {
                    "schema_version": "mc.stage_completion_validation.v1",
                    "execution_disposition": observation.operation_disposition,
                    "reason_codes": interpreter.result_validation_errors(
                        observation.identity, observation.operation_result
                    ),
                    "artifact_schema_validation": "not_evaluated",
                },
            },
            completion=stage_completion_records(
                stage=stage,
                proposal=proposal,
                observation=observation,
                validation=validation,
                reason_codes=reason_codes,
                unit_key=unit_key,
                decision_key=mutation_id,
            ),
        )
        output_evidence = observation.operation_result.get("output_refs", ())
        if not isinstance(output_evidence, list | tuple):
            output_evidence = ()
        obligation_evidence = observation.operation_result.get("obligation_refs", ())
        if not isinstance(obligation_evidence, list | tuple):
            obligation_evidence = ()
        batch_actions: list[
            RecordObligationEvidenceAction
            | RecordOutputEvidenceAction
            | RecordOperationSettlementEvidenceAction
        ] = []
        if proposal.decision.value == "admit":
            admitted_outputs = next(
                (
                    item.output_refs
                    for item in next_projection.stages.values()
                    if item.candidate == request.observation.identity.candidate
                ),
                (),
            )
            batch_actions.extend(
                RecordObligationEvidenceAction(
                    evidence=AcceptedObligationEvidence(
                        obligation_ref=str(obligation_ref),
                        evidence_digest=sha256_digest(validation)
                        if validation
                        else sha256_digest(str(obligation_ref)),
                        accepted_by_authority_ref=ORCHESTRATION_AUTHORITY_REF,
                    )
                )
                for obligation_ref in sorted(
                    {str(item) for item in obligation_evidence},
                    key=lambda item: item.encode("utf-8"),
                )
            )
            batch_actions.extend(
                RecordOutputEvidenceAction(
                    evidence=AcceptedOutputEvidence(
                        output_ref=output_ref,
                        evidence_digest=sha256_digest(validation)
                        if validation
                        else sha256_digest(output_ref),
                        accepted_by_authority_ref=ORCHESTRATION_AUTHORITY_REF,
                    )
                )
                for output_ref in sorted(
                    admitted_outputs,
                    key=lambda item: item.encode("utf-8"),
                )
            )
        batch_actions.append(
            RecordOperationSettlementEvidenceAction(
                evidence=AcceptedOperationSettlementEvidence(
                    settlement_id=(
                        f"stagegraph-result:{request.observation.identity.semantic_key}"
                    ),
                    settlement_payload_digest=sha256_digest(observation.operation_result),
                    accepted_by_authority_ref=ORCHESTRATION_AUTHORITY_REF,
                )
            )
        )
        receipt = await self._run_control.execute_family_admission(
            LifecycleCommand(
                command_id=f"stagegraph:{mutation.mutation_id}",
                idempotency_issuer=request.idempotency_issuer,
                request_scope=request.request_scope,
                run_id=request.run_id,
                expected_run_version=current_projection.run_version,
                actor=orchestration_lifecycle_actor(),
                action=ApplyAuthorityBatchAction(actions=tuple(batch_actions)),
                reason="Settle StageGraph producer usage and decide its result",
                evidence_refs=tuple(str(item) for item in output_evidence),
                occurred_at=request.occurred_at,
                correlation_id=request.correlation_id,
                unit_key=unit_key,
            ),
            mutation,
            transient_version_conflict=True,
        )
        accepted = receipt.command_result.status == CommandStatus.ACCEPTED
        if accepted:
            if receipt.family_receipt is None:
                raise RuntimeError("accepted StageGraph result is missing its family receipt")
            next_projection = replace(
                next_projection,
                run_version=receipt.command_result.resulting_run_version,
                family_version=receipt.family_receipt.family_version,
            )
        return StageGraphResultActivityResult(
            accepted=accepted,
            projection=next_projection if accepted else current_projection,
            proposal=proposal,
            reason_code=receipt.command_result.reason_code,
        )

    async def _nonoperation_effects_settled(
        self,
        request: StageGraphResultActivityRequest,
        reservation_id: str,
        budget: BudgetState,
        effects: EffectLedgerState,
    ) -> bool:
        """No-runtime stages require their own persisted host settlement evidence."""
        if any(claim.reservation_id == reservation_id for claim in effects.claims.values()):
            return False
        identity = request.observation.identity
        admission = await self._repository.get_family_mutation(
            request.request_scope,
            request.run_id,
            "stagegraph",
            f"admit-{sha256_digest(identity.semantic_key)[7:]}",
            StageGraphDecisionMutation,
        )
        if admission is None:
            return False
        try:
            proposal = TypeAdapter(StageOperationAdmissionProposal).validate_python(
                admission.decision_payload.get("proposal")
            )
        except ValueError:
            return False
        if proposal.identity != identity or proposal.reservation_id != reservation_id:
            return False
        if admission.decision_kind == "control_admitted" and self._human_tasks is not None:
            try:
                spec = HumanGateSpec.model_validate(admission.decision_payload.get("human_gate"))
                observed = HumanGateOutcome.model_validate(
                    request.observation.operation_result.get("human_gate")
                )
            except ValueError:
                return False
            task = await self._human_tasks.get(request.request_scope, observed.human_task_id)
            if task is None:
                return False
            activation = task.activation
            if (
                activation.request_scope != request.request_scope
                or activation.run_id != request.run_id
                or activation.family != "StageGraph"
                or activation.execution_epoch != identity.execution_epoch
                or activation.activation_key != f"stage:{identity.semantic_key}"
                or activation.spec != spec
                or spec.gate_key != identity.stage_id
                or outcome_for(task) != observed
            ):
                return False
            try:
                bind_outcome(activation, observed)
                # The HumanGate workflow projects remediation through the workflow cycle,
                # not a stage-local cycle. Rebuild the same exact host-authored result.
                policy = StageGraphBlueprint.model_validate(request.blueprint).workflow_cycle_policy
                disposition, payload = stagegraph_gate_result(
                    observed,
                    evaluation_contract_ref=policy.evaluation_contract_ref if policy else None,
                    objective_contract_ref=policy.objective_contract_ref if policy else None,
                )
            except ValueError:
                return False
            host_fields = {
                "human_gate",
                "output_refs",
                "evaluation",
                "cycle_scope",
                "invalidation_frontier",
                "next_objective",
                "evaluation_ref",
                "evaluation_contract_ref",
                "objective_contract_ref",
            }
            host_payload = {
                key: value
                for key, value in request.observation.operation_result.items()
                if key in host_fields
            }
            # obligation_refs are independently derived/validated by normal completion.
            return (
                disposition == request.observation.operation_disposition and host_payload == payload
            )
        nested = request.observation.operation_result.get("nested")
        if not isinstance(nested, dict) or self._nested_activations is None:
            return False
        blueprint = StageGraphBlueprint.model_validate(request.blueprint)
        host_body = next(
            (body for body in blueprint.nested_bodies if body.host_id == identity.stage_id), None
        )
        if host_body is None or nested.get("position") != host_body.position:
            return False
        body = {key: value for key, value in nested.items() if key != "receipt_digest"}
        if nested.get("schema") != "mc.nested_export_receipt.v1" or nested.get(
            "receipt_digest"
        ) != sha256_digest(body):
            return False
        if admission.decision_kind != "operation_admitted":
            return False
        actual = nested.get("actual_usage")
        if not isinstance(actual, dict) or any(
            not isinstance(key, str) or type(amount) is not int or amount < 0
            for key, amount in actual.items()
        ):
            return False
        usage = budget.usage_records.get(f"nested-usage:{reservation_id}")
        record = await self._nested_activations.get(
            request.request_scope,
            request.run_id,
            identity.stage_id,
            identity.semantic_key,
        )
        actual = {key: amount for key, amount in actual.items() if amount}
        child_id = nested.get("child_run_id")
        if not child_id:
            # A never-activated refusal still needs the exact host's recorded zero-spend
            # release; a missing runtime owner or a fabricated receipt is not authority.
            released = (
                usage is not None
                and usage.reservation_id == reservation_id
                and not usage.pending_external_amounts
                and not usage.actual_amounts
            )
            return (
                record is None
                and nested.get("composite_accepted") is False
                and not actual
                and released
                and not nested.get("exports")
                and not nested.get("early_exports")
                and not nested.get("adopted")
                and request.observation.operation_disposition in {"failed", "cancelled"}
                and not request.observation.operation_result.get("output_refs")
            )
        if (
            usage is None
            or usage.reservation_id != reservation_id
            or usage.pending_external_amounts
            or usage.actual_amounts != actual
        ):
            return False
        if record is None or record.receipt != nested or record.settled_at is None:
            return False
        if (
            record.request_scope != request.request_scope
            or record.parent_run_id != request.run_id
            or record.host_id != identity.stage_id
            or record.semantic_attempt_id != identity.semantic_key
            or record.child_run_id != child_id
            or record.position != nested.get("position")
            or record.body_digest != sha256_digest(host_body)
            or record.family != host_body.family
            or record.depth != host_body.depth
        ):
            return False
        child = await self._run_control.get_run(request.request_scope, str(child_id))
        if child.phase == RunPhase.TERMINAL:
            return (
                not nested.get("composite_accepted")
                or child.terminal_outcome == RunOutcome.COMPLETED
            )
        if (
            child.phase != RunPhase.CANCELLING
            or child.execution_target is not None
            or nested.get("composite_accepted")
            or actual
        ):
            return False
        # A child cancelled before its root started is durably unable to dispatch; its
        # cancellation saga may still be pending. Require independent zero-spend facts.
        child_effects = await self._run_control.get_effects(request.request_scope, str(child_id))
        child_budget = await self._run_control.get_budget(request.request_scope, str(child_id))
        return (
            not child_effects.claims
            and not any(child_budget.consumed.values())
            and not any(child_budget.pending_settlement.values())
        )

    async def read_result_decision(
        self, request: StageGraphResultActivityRequest
    ) -> StageGraphResultActivityResult | None:
        """Read only the persisted decision matching this exact result request."""
        return await self._replay_result(request)

    async def _replay_result(
        self,
        request: StageGraphResultActivityRequest,
    ) -> StageGraphResultActivityResult | None:
        mutation_id = f"result-{sha256_digest(request.observation.identity.semantic_key)[7:]}"
        receipt = await self._repository.get_family_admission_receipt(
            request.request_scope,
            request.run_id,
            request.idempotency_issuer,
            f"stagegraph:{mutation_id}",
        )
        if receipt is None or receipt.family_receipt is None:
            return None
        mutation = await self._repository.get_family_mutation(
            request.request_scope,
            request.run_id,
            "stagegraph",
            mutation_id,
            StageGraphDecisionMutation,
        )
        if mutation is None:
            raise ValueError("committed StageGraph result has no journal mutation")
        if mutation.decision_payload.get("result_request_digest") != sha256_digest(asdict(request)):
            raise ValueError("StageGraph result identity was reused with different request content")
        projection = TypeAdapter(StageGraphAcceptedProjection).validate_python(
            mutation.decision_payload["projection"]
        )
        proposal = TypeAdapter(ResultDispositionProposal).validate_python(
            mutation.decision_payload["proposal"]
        )
        if (
            projection.digest != mutation.next_projection_digest
            or receipt.family_mutation_fingerprint
            != contract_fingerprint(mutation, exclude={"decided_at"})
            or proposal.identity != request.observation.identity
        ):
            raise ValueError("committed StageGraph result replay evidence does not match")
        projection = replace(
            projection,
            run_version=receipt.command_result.resulting_run_version,
            family_version=receipt.family_receipt.family_version,
        )
        return StageGraphResultActivityResult(
            accepted=True,
            projection=projection,
            proposal=proposal,
            reason_code=receipt.command_result.reason_code,
        )

    async def apply_cycle(
        self, request: StageGraphCycleActivityRequest
    ) -> StageGraphCycleActivityResult:
        await self._verify_family_head(
            request.request_scope,
            request.run_id,
            request.projection,
        )
        run = await self._run_control.get_run(request.request_scope, request.run_id)
        current_projection = replace(request.projection, run_version=run.version)
        blueprint = StageGraphBlueprint.model_validate(request.blueprint)
        if request.cycle_scope == "revisit":
            return await self._apply_revisit(request, current_projection, blueprint)
        stage = (
            next((item for item in blueprint.stages if item.stage_id == request.stage_id), None)
            if request.cycle_scope == "stage"
            else None
        )
        policy = stage.stage_cycle_policy if stage is not None else blueprint.workflow_cycle_policy
        if policy is None:
            raise ValueError(f"StageGraph {request.cycle_scope} cycle is not authored")
        if (
            request.evaluation_contract_ref != policy.evaluation_contract_ref
            or request.objective_contract_ref != policy.objective_contract_ref
            or not request.evaluation_ref
        ):
            raise ValueError(f"{request.cycle_scope} cycle evidence is outside frozen contracts")
        interpreter = StageGraphInterpreter(
            blueprint,
            effective_max_concurrency=request.effective_max_concurrency,
        )
        proposal: StageInvalidationProposal | WorkflowInvalidationProposal
        cycle_unit_key: str | None = None
        if request.cycle_scope == "stage":
            if request.stage_id is None:
                raise ValueError("stage cycle requires a stage identity")
            stage_proposal = interpreter.stage_invalidation(
                current_projection,
                stage_id=request.stage_id,
                next_objective=request.next_objective,
            )
            cycle_unit_key = _prior_cycle_unit_key(
                current_projection, stage_proposal, request.request_scope
            )
            next_projection = interpreter.apply_stage_invalidation(
                current_projection,
                stage_proposal,
                next_run_version=current_projection.run_version + 1,
                next_family_version=current_projection.family_version + 1,
            )
            proposal = stage_proposal
            cycle_ordinal = stage_proposal.next_stage_cycle_ordinal
        else:
            workflow_proposal = interpreter.workflow_invalidation(
                current_projection,
                invalidation_frontier=request.invalidation_frontier,
                next_objective=request.next_objective,
            )
            next_projection = interpreter.apply_workflow_invalidation(
                current_projection,
                workflow_proposal,
                next_run_version=current_projection.run_version + 1,
                next_family_version=current_projection.family_version + 1,
            )
            proposal = workflow_proposal
            cycle_ordinal = workflow_proposal.next_workflow_cycle_ordinal
        exact_ref = next(
            (
                item.admitted_operation_request_ref
                for item in current_projection.stages.values()
                if item.admitted_operation_request_ref is not None
            ),
            None,
        )
        if exact_ref is None:
            raise ValueError("workflow cycle requires an admitted producer operation")
        mutation = self._mutation(
            current_projection,
            next_projection,
            decision_kind="cycle_decided",
            mutation_id=(
                f"cycle-{request.run_id}-{request.cycle_scope}-{request.stage_id or 'graph'}-"
                f"{cycle_ordinal}"
            ),
            exact_operation_request_ref=exact_ref,
            request_scope=request.request_scope,
            decided_at=request.occurred_at,
            decision_payload={
                "proposal": asdict(proposal),
                "evaluation_ref": request.evaluation_ref,
            },
        )
        receipt = await self._run_control.execute_family_admission(
            LifecycleCommand(
                command_id=f"stagegraph:{mutation.mutation_id}",
                idempotency_issuer=request.idempotency_issuer,
                request_scope=request.request_scope,
                run_id=request.run_id,
                expected_run_version=current_projection.run_version,
                actor=orchestration_lifecycle_actor(),
                # 1.4.4 (FX-TR, found by the first real cycle on the production stack): the
                # cycle policy's amounts are consumed against the run's standing `baseline`
                # reservation, which the completion path settles. A usage record naming no
                # reservation was rejected `reservation_required` by the reducer, and a
                # reservation of its own was never consumed, so terminalization refused
                # `budget_not_settled`.
                action=RecordUsageAction(
                    usage_id=(
                        f"stagegraph-cycle:{request.run_id}:"
                        f"{request.cycle_scope}:{request.stage_id or 'graph'}:{cycle_ordinal}"
                    ),
                    authority_ref=ORCHESTRATION_AUTHORITY_REF,
                    actual_amounts=policy.reservation,
                    reservation_id="baseline",
                ),
                reason="Accept typed StageGraph workflow cycle and invalidation frontier",
                evidence_refs=(request.evaluation_ref,),
                occurred_at=request.occurred_at,
                correlation_id=request.correlation_id,
                unit_key=cycle_unit_key,
            ),
            mutation,
        )
        accepted = receipt.command_result.status == CommandStatus.ACCEPTED
        if accepted:
            if receipt.family_receipt is None:
                raise RuntimeError("accepted StageGraph cycle is missing its family receipt")
            next_projection = replace(
                next_projection,
                run_version=receipt.command_result.resulting_run_version,
                family_version=receipt.family_receipt.family_version,
            )
        return StageGraphCycleActivityResult(
            accepted=accepted,
            projection=next_projection if accepted else current_projection,
            proposal=proposal,
            reason_code=receipt.command_result.reason_code,
        )

    async def _apply_revisit(
        self,
        request: StageGraphCycleActivityRequest,
        current_projection: StageGraphAcceptedProjection,
        blueprint: StageGraphBlueprint,
    ) -> StageGraphCycleActivityResult:
        """OVE-171 slice D: the host-governed next visit of a declared Revisit Region.

        The interpreter re-derives the due decision from the authoritative projection (never
        the workflow's word for it); the decision is the evidence. A revisit consumes no cycle
        reservation of its own: the region's visit cap governs it and every visit's operations
        reserve their own budget at admission."""

        interpreter = StageGraphInterpreter(
            blueprint, effective_max_concurrency=request.effective_max_concurrency
        )
        due = interpreter.revisit_due(current_projection)
        region = blueprint.revisit_regions[0] if blueprint.revisit_regions else None
        if (
            due is None
            or region is None
            or request.evaluation_ref != f"revisit:{region.region_id}:{due.visit}"
        ):
            raise ValueError("no revisit of this region is due at the authoritative head")
        proposal = interpreter.revisit_invalidation(
            current_projection, region_id=region.region_id, next_objective=request.next_objective
        )
        next_projection = interpreter.apply_workflow_invalidation(
            current_projection,
            proposal,
            next_run_version=current_projection.run_version + 1,
            next_family_version=current_projection.family_version + 1,
        )
        # The exit attempt whose accepted result decided the revisit (deterministic).
        exit_instance = interpreter.current_instance(region.exit_stage_id, current_projection)
        exact_ref = exit_instance.admitted_operation_request_ref if exit_instance else None
        if exact_ref is None:
            raise ValueError("a revisit requires the admitted exit operation")
        mutation = self._mutation(
            current_projection,
            next_projection,
            decision_kind="cycle_decided",
            mutation_id=f"revisit-{request.run_id}-{region.region_id}-{due.visit}",
            exact_operation_request_ref=exact_ref,
            request_scope=request.request_scope,
            decided_at=request.occurred_at,
            decision_payload={
                "proposal": asdict(proposal),
                "evaluation_ref": request.evaluation_ref,
                "revisit": asdict(due),
            },
        )
        receipt = await self._run_control.execute_family_admission(
            LifecycleCommand(
                command_id=f"stagegraph:{mutation.mutation_id}",
                idempotency_issuer=request.idempotency_issuer,
                request_scope=request.request_scope,
                run_id=request.run_id,
                expected_run_version=current_projection.run_version,
                actor=orchestration_lifecycle_actor(),
                action=ApplyAuthorityBatchAction(
                    actions=(
                        RecordOperationSettlementEvidenceAction(
                            evidence=AcceptedOperationSettlementEvidence(
                                settlement_id=(
                                    f"stagegraph-revisit:{request.run_id}:{region.region_id}:"
                                    f"{due.visit}"
                                ),
                                settlement_payload_digest=sha256_digest(asdict(due)),
                                accepted_by_authority_ref=ORCHESTRATION_AUTHORITY_REF,
                            )
                        ),
                    )
                ),
                reason="Accept the governed revisit of a Stage Graph Revisit Region",
                evidence_refs=(request.evaluation_ref,),
                occurred_at=request.occurred_at,
                correlation_id=request.correlation_id,
            ),
            mutation,
        )
        accepted = receipt.command_result.status == CommandStatus.ACCEPTED
        if accepted:
            if receipt.family_receipt is None:
                raise RuntimeError("accepted StageGraph revisit is missing its family receipt")
            next_projection = replace(
                next_projection,
                run_version=receipt.command_result.resulting_run_version,
                family_version=receipt.family_receipt.family_version,
            )
        return StageGraphCycleActivityResult(
            accepted=accepted,
            projection=next_projection if accepted else current_projection,
            proposal=proposal,
            reason_code=receipt.command_result.reason_code,
        )

    async def complete(
        self, request: StageGraphCompletionActivityRequest
    ) -> StageGraphCompletionActivityResult:
        if not request.proposal.can_terminalize:
            raise ValueError("StageGraph completion proposal still has open obligations")
        command_id = await self._completion_command_id(
            request, f"stagegraph:complete-{sha256_digest(request.projection.digest)[7:]}"
        )
        replay = await self._replay_completion(request, command_id)
        if replay is not None:
            return replay
        await self._verify_family_head(
            request.request_scope,
            request.run_id,
            request.projection,
        )
        run = await self._run_control.get_run(request.request_scope, request.run_id)
        current_projection = replace(request.projection, run_version=run.version)
        budget = await self._run_control.get_budget(request.request_scope, request.run_id)
        effects = await self._run_control.get_effects(request.request_scope, request.run_id)
        next_projection = replace(
            current_projection,
            family_version=current_projection.family_version + 1,
            run_version=current_projection.run_version + 1,
        )
        rejected_refs: dict[str, tuple[str, str]] = {}
        for instance in current_projection.stages.values():
            if instance.status != "failed":
                continue
            # Rejection did not admit/increment this next attempt. Its journal key is
            # derived from the candidate; no new field changes old projection bytes.
            identity = StageExecutionIdentity(
                run_id=request.run_id,
                execution_epoch=current_projection.identity.execution_epoch,
                candidate=instance.candidate,
                semantic_attempt=instance.semantic_attempt + 1,
            )
            rejection_ref = f"reject-{sha256_digest(identity.semantic_key)[7:]}"
            fact = await self._repository.get_family_mutation(
                request.request_scope,
                request.run_id,
                "stagegraph",
                rejection_ref,
                StageGraphDecisionMutation,
            )
            if fact is None:
                continue
            if fact.decision_kind != "admission_rejected":
                raise ValueError("candidate rejection journal has a different decision kind")
            denied = LifecycleCommand.model_validate(fact.decision_payload.get("rejected_command"))
            actual = await self._repository.get_family_admission_receipt(
                request.request_scope, request.run_id, denied.idempotency_issuer, denied.command_id
            )
            snapshot = fact.decision_payload.get("projection")
            snapshot_stages = snapshot.get("stages", {}) if isinstance(snapshot, dict) else {}
            snapshot_stage = snapshot_stages.get(instance.candidate.semantic_prefix, {})
            fact_proposal = fact.decision_payload.get("proposal")
            if (
                not isinstance(fact_proposal, dict)
                or fact_proposal.get("identity") != asdict(identity)
                or denied.request_scope != request.request_scope
                or denied.run_id != request.run_id
                or not isinstance(denied.action, ReserveBudgetAction)
                or actual is None
                or actual.command_result.status != CommandStatus.REJECTED
                or actual.command_result.reason_code != "budget_hard_cap_exceeded"
                or actual.command_result.command_fingerprint
                != contract_fingerprint(denied, exclude={"occurred_at"})
                or actual.family_mutation_fingerprint
                != fact.decision_payload.get("rejected_family_fingerprint")
                or snapshot_stage.get("status") != "failed"
                or snapshot_stage.get("candidate") != asdict(instance.candidate)
                or snapshot_stage.get("semantic_attempt") != instance.semantic_attempt
            ):
                raise ValueError("candidate admission rejection provenance is not authoritative")
            rejected_refs[instance.candidate.semantic_prefix] = (
                rejection_ref,
                fact.exact_operation_request_ref,
            )
        exact_ref = next(
            (
                item.admitted_operation_request_ref
                for item in current_projection.stages.values()
                if item.admitted_operation_request_ref is not None
            ),
            None,
        )
        if exact_ref is None:
            exact_ref = next((item[1] for item in rejected_refs.values()), None)
        if exact_ref is None:
            raise ValueError(
                "terminalization requires an admitted operation or verified rejected proposal"
            )
        mutation = self._mutation(
            current_projection,
            next_projection,
            decision_kind="completion_proposed",
            mutation_id=f"complete-{sha256_digest(request.projection.digest)[7:]}",
            exact_operation_request_ref=exact_ref,
            request_scope=request.request_scope,
            decided_at=request.occurred_at,
            decision_payload={
                "completion": _completion_payload(request.proposal),
                "completion_request_digest": sha256_digest(asdict(request)),
            },
        )
        failure_refs = tuple(
            (
                f"stage-admission-rejection:{rejected_refs[item.candidate.semantic_prefix][0]}"
                if item.candidate.semantic_prefix in rejected_refs
                else item.candidate.semantic_prefix
            )
            for item in current_projection.stages.values()
            if item.status == "failed"
        ) + tuple(request.proposal.unmet_reasons)
        obligation_payload = [
            item.model_dump(mode="json")
            for item in sorted(
                run.accepted_obligation_evidence,
                key=lambda item: item.obligation_ref,
            )
        ]
        terminal = TerminalizationProposal(
            proposal_id=mutation.mutation_id,
            expected_run_version=run.version,
            workflow_type_digest=request.workflow_type_digest,
            obligation_revision=run.obligation_revision,
            evidence_frontier_digest=run.evidence_frontier_digest,
            accepted_obligation_evidence_digest=sha256_digest(obligation_payload),
            proposing_execution_binding_ref=exact_ref,
            required_obligations_accepted=request.proposal.required_obligations_accepted,
            execution_failure_refs=failure_refs,
            valid_output_refs=request.proposal.valid_output_refs,
            # RRM-008 (REQ-CP-EXEC-008 step 7): the family asserts that every producer
            # liability was reconciled under cancellation; the reducer still requires every
            # reservation and effect settled before it records `cancelled`.
            cancellation_settled=(
                request.proposal.cancelled
                if run.phase.value == "cancelling"
                else run.phase.value != "cancelling"
            ),
            budget_settled=(
                not any(budget.reserved.values()) and not any(budget.pending_settlement.values())
            ),
            effects_settled=all(claim.settlement is not None for claim in effects.claims.values()),
            pending_wait_or_link_ids=(
                () if request.proposal.cancelled else request.proposal.pending_dependency_ids
            ),
            proposed_at=request.occurred_at,
            finalization_plan=run.finalization_plan,
            output_omission_reason=run.finalization_omission_reason,
        )
        command = LifecycleCommand(
            command_id=command_id,
            idempotency_issuer=request.idempotency_issuer,
            request_scope=request.request_scope,
            run_id=request.run_id,
            expected_run_version=run.version,
            actor=orchestration_lifecycle_actor(),
            action=TerminalizeAction(proposal=terminal),
            reason=(
                "StageGraph concluded without acceptance: failed " + ", ".join(failure_refs)
                if request.proposal.failed
                else "Reducer-authorized StageGraph obligation completion"
            ),
            evidence_refs=request.proposal.valid_output_refs,
            occurred_at=request.occurred_at,
            correlation_id=request.correlation_id,
        )
        prior_receipt = await self._repository.get_family_admission_receipt(
            request.request_scope, request.run_id, request.idempotency_issuer, command_id
        )
        if (
            prior_receipt is not None
            and prior_receipt.command_result.status == CommandStatus.REJECTED
        ):
            # Old rejected proposals have no committed family journal. Reconstruct
            # their exact representation; both normal idempotency fingerprints
            # must match before omitting the additive field. Never rewrite a receipt.
            legacy = mutation.model_copy(
                update={
                    "decision_payload": {
                        key: value
                        for key, value in mutation.decision_payload.items()
                        if key != "completion_request_digest"
                    }
                }
            )
            if (
                prior_receipt.command_result.recorded_at == request.occurred_at
                and prior_receipt.command_result.command_fingerprint
                == contract_fingerprint(command, exclude={"occurred_at"})
                and prior_receipt.family_mutation_fingerprint
                == contract_fingerprint(legacy, exclude={"decided_at"})
            ):
                mutation = legacy
        receipt = await self._run_control.execute_family_admission(command, mutation)
        result = receipt.command_result
        return StageGraphCompletionActivityResult(
            accepted=result.status == CommandStatus.ACCEPTED,
            terminal_outcome=result.terminal_outcome,
            resulting_run_version=result.resulting_run_version,
            reason_code=result.reason_code,
        )

    async def _replay_completion(
        self, request: StageGraphCompletionActivityRequest, command_id: str
    ) -> StageGraphCompletionActivityResult | None:
        """Read a committed exact request before its own commit makes its head stale.

        Historical mutations without a full request digest are never rewritten or
        inferred to match. Rejected proposals retain the existing bounded retry policy.
        """
        receipt = await self._repository.get_family_admission_receipt(
            request.request_scope, request.run_id, request.idempotency_issuer, command_id
        )
        if receipt is None or receipt.command_result.status != CommandStatus.ACCEPTED:
            return None
        mutation_id = f"complete-{sha256_digest(request.projection.digest)[7:]}"
        mutation = await self._repository.get_family_mutation(
            request.request_scope,
            request.run_id,
            "stagegraph",
            mutation_id,
            StageGraphDecisionMutation,
        )
        if mutation is None:
            raise ValueError("committed StageGraph completion has no journal mutation")
        digest = mutation.decision_payload.get("completion_request_digest")
        if digest is None:
            raise ValueError("legacy StageGraph completion replay has no exact request evidence")
        if digest != sha256_digest(asdict(request)):
            raise ValueError(
                "StageGraph completion identity was reused with different request content"
            )
        result, family = receipt.command_result, receipt.family_receipt
        prior = replace(request.projection, run_version=result.resulting_run_version - 1)
        expected = replace(
            prior,
            run_version=result.resulting_run_version,
            family_version=prior.family_version + 1,
        )
        projection = TypeAdapter(StageGraphAcceptedProjection).validate_python(
            mutation.decision_payload.get("projection")
        )
        fingerprint = contract_fingerprint(mutation, exclude={"decided_at"})
        if (
            family is None
            or mutation.decision_kind != "completion_proposed"
            or mutation.mutation_id != mutation_id
            or mutation.request_scope != request.request_scope
            or mutation.run_id != request.run_id
            or mutation.decided_at != request.occurred_at
            or mutation.expected_family_version != request.projection.family_version
            or mutation.prior_projection_digest != prior.digest
            or mutation.next_projection_digest != expected.digest
            or projection != expected
            or sha256_digest(mutation.decision_payload.get("completion"))
            != sha256_digest(_completion_payload(request.proposal))
            or receipt.family_mutation_fingerprint != fingerprint
            or family.mutation_fingerprint != fingerprint
            or family.family_kind != mutation.family_kind
            or family.mutation_kind != mutation.mutation_kind
            or family.mutation_id != mutation_id
            or family.family_version != expected.family_version
            or family.exact_operation_request_ref != mutation.exact_operation_request_ref
            or result.command_id != command_id
            or result.idempotency_issuer != request.idempotency_issuer
            or result.run_id != request.run_id
            or result.recorded_at != request.occurred_at
            or result.phase.value != "terminal"
            or result.terminal_outcome is None
        ):
            raise ValueError("committed StageGraph completion replay evidence does not match")
        return StageGraphCompletionActivityResult(
            accepted=True,
            terminal_outcome=result.terminal_outcome,
            resulting_run_version=result.resulting_run_version,
            reason_code=result.reason_code,
        )

    async def settle_baseline(
        self, request: StageGraphBaselineSettlementRequest
    ) -> StageGraphBaselineSettlementResult:
        """Release the run's unused baseline reservation before terminalization (RRM-021).

        REQ-CP-RUN-006: reservations are released or settled before terminalization. The
        stages reserve and settle their own operation reservations, so the admission-time
        `baseline` reservation is never consumed by a StageGraph run: it is released whole,
        against zero recorded usage. Idempotent: the authoritative budget is the source of
        truth, so a baseline already settled (an Activity retry, a continued segment) is a
        no-op that reports the current run version, and nothing is counted twice.
        """

        result_version = 0
        reason_code = ""
        accepted = True
        admitted = {
            dimension: amount
            for dimension, amount in request.baseline_reservation.items()
            if amount > 0
        }
        for attempt in range(BASELINE_SETTLEMENT_ATTEMPTS):
            budget = await self._run_control.get_budget(request.request_scope, request.run_id)
            run = await self._run_control.get_run(request.request_scope, request.run_id)
            remaining = {
                dimension: amount
                for dimension, amount in budget.reservations.get("baseline", {}).items()
                if amount > 0
            }
            if not remaining:
                return StageGraphBaselineSettlementResult(
                    accepted=True, resulting_run_version=run.version, reason_code=""
                )
            if admitted and admitted != remaining:
                raise ValueError("StageGraph baseline differs from the admitted reservation")
            result = await self._run_control.execute(
                LifecycleCommand(
                    command_id=(
                        f"stagegraph:{request.run_id}:baseline-settlement"
                        if attempt == 0
                        else f"stagegraph:{request.run_id}:baseline-settlement:"
                        f"at-version:{run.version}"
                    ),
                    idempotency_issuer=request.idempotency_issuer,
                    request_scope=request.request_scope,
                    run_id=request.run_id,
                    expected_run_version=run.version,
                    actor=orchestration_lifecycle_actor(),
                    action=RecordUsageAction(
                        usage_id=f"stagegraph-usage:{request.run_id}:baseline",
                        actual_amounts={},
                        reservation_id="baseline",
                        release_amounts=remaining,
                    ),
                    reason="Release the unused StageGraph baseline reservation",
                    occurred_at=request.occurred_at,
                    correlation_id=request.correlation_id,
                )
            )
            accepted = result.status == CommandStatus.ACCEPTED
            result_version = result.resulting_run_version
            reason_code = result.reason_code
            if result.status != CommandStatus.STALE:
                break
        else:
            # Still stale after every attempt: retryable, so the Activity retry policy
            # re-reads the run (the release is idempotent).
            raise RuntimeError("StageGraph baseline settlement is stale; retrying")
        return StageGraphBaselineSettlementResult(
            accepted=accepted, resulting_run_version=result_version, reason_code=reason_code
        )

    async def _completion_command_id(
        self, request: StageGraphCompletionActivityRequest, base: str
    ) -> str:
        """The identity of this completion proposal.

        RRM-008's cancellation saga proposes terminalization again after a liability
        rejection (`budget_not_settled`, `effects_not_settled`, ...) once the liability is
        reconciled or its backoff elapses. The projection, and so the mutation identity, is
        unchanged, but the proposal is a new decision (its `proposed_at` and settled facts
        differ), so reusing the identity of the rejected proposal was an identity conflict
        that failed the family (found by the RRM-009 live drill). A rejected proposal keeps
        its receipt; the next proposal takes the next unused `:retry:{n}` identity. An
        Activity retry of the same request finds its own receipt and replays it.
        """

        command_id = base
        for attempt in range(1, MAX_COMPLETION_PROPOSALS + 1):
            prior = await self._repository.get_family_admission_receipt(
                request.request_scope, request.run_id, request.idempotency_issuer, command_id
            )
            if (
                prior is None
                or prior.command_result.status != CommandStatus.REJECTED
                # the result records the command's `occurred_at` (the request's, on a retry)
                or prior.command_result.recorded_at == request.occurred_at
            ):
                return command_id
            command_id = f"{base}:retry:{attempt}"
        raise ValueError("StageGraph completion was refused too many times")

    async def _verify_family_head(
        self,
        request_scope: str,
        run_id: str,
        projection: StageGraphAcceptedProjection,
    ) -> None:
        head = await self._repository.get_family_head(
            request_scope,
            run_id,
            "stagegraph",
            StageGraphDecisionMutation,
        )
        if projection.family_version == 0:
            if head is not None:
                raise ValueError("StageGraph projection is stale against the family head")
            return
        if (
            head is None
            or head.expected_family_version + 1 != projection.family_version
            or head.next_projection_digest != projection.digest
        ):
            raise ValueError("StageGraph projection does not match the authoritative family head")

    @staticmethod
    def _mutation(
        prior: StageGraphAcceptedProjection,
        next_projection: StageGraphAcceptedProjection,
        *,
        decision_kind: Literal[
            "operation_admitted",
            "admission_rejected",
            "result_decided",
            "wait_decided",
            "cycle_decided",
            "completion_proposed",
        ],
        mutation_id: str,
        exact_operation_request_ref: str,
        request_scope: str,
        decided_at: datetime,
        decision_payload: dict[str, object],
        completion: CompletionRecords | None = None,
    ) -> StageGraphDecisionMutation:
        return StageGraphDecisionMutation(
            mutation_id=mutation_id,
            request_scope=request_scope,
            run_id=prior.identity.run_id,
            expected_family_version=prior.family_version,
            exact_operation_request_ref=exact_operation_request_ref,
            decided_at=decided_at,
            decision_kind=decision_kind,
            prior_projection_digest=prior.digest,
            next_projection_digest=next_projection.digest,
            decision_payload={
                **decision_payload,
                "projection": asdict(next_projection),
            },
            completion=completion,
        )


class StageGraphOperationMaterializer(Protocol):
    """Prepare the exact OperationWorkflow child; persist its binding once it is admitted."""

    async def materialize(
        self,
        request: StageGraphAdmissionActivityRequest,
    ) -> OperationWorkflowRequest: ...

    async def prepare(
        self,
        request: StageGraphAdmissionActivityRequest,
    ) -> OperationWorkflowRequest: ...

    async def persist(
        self,
        request: StageGraphAdmissionActivityRequest,
        operation: OperationWorkflowRequest,
    ) -> None: ...


class StageGraphOperationTemplateProvider(Protocol):
    """Resolve an immutable operation template from the admitted semantic binding."""

    async def get_template(
        self,
        *,
        semantic_input_binding_ref: str,
        operation_request_key: str,
        request_scope: str,
        run_id: str,
    ) -> OperationExecutionRequest: ...


class StaticStageGraphOperationTemplateProvider:
    """Process-local adapter for an immutable, already-admitted template set."""

    def __init__(self, templates: dict[str, OperationExecutionRequest]) -> None:
        if not templates:
            raise ValueError("StageGraph operation templates cannot be empty")
        if any(not key for key in templates):
            raise ValueError("StageGraph operation template keys cannot be empty")
        self._templates = dict(templates)

    async def get_template(
        self,
        *,
        semantic_input_binding_ref: str,
        operation_request_key: str,
        request_scope: str,
        run_id: str,
    ) -> OperationExecutionRequest:
        del request_scope, run_id
        if not semantic_input_binding_ref:
            raise ValueError("StageGraph template lookup requires an immutable semantic binding")
        template = self._templates.get(operation_request_key)
        if template is None:
            raise ValueError(
                f"StageGraph operation template is unavailable: {operation_request_key}"
            )
        return template


class StageGraphOperationPreparationService:
    """Prepare the exact OperationWorkflow child; persist its binding once admitted."""

    def __init__(
        self,
        *,
        templates: StageGraphOperationTemplateProvider,
        operation_bindings: SemanticOperationBindingRepository,
        heartbeats: OperationHeartbeatPolicy = DEFAULT_OPERATION_HEARTBEATS,
        context_packs: ContextPackService | None = None,
        mailbox: MailboxDeliveryService | None = None,
        lane_bindings: LaneRebinders | None = None,
        linked_exports: LinkedExportPort | None = None,
    ) -> None:
        self._templates = templates
        self._linked_exports = linked_exports
        self._operation_bindings = operation_bindings
        # RRM-009 (RRM-008 composition): the deployment's heartbeat timeout per operation
        # class, which bounds worker-loss detection and cancel latency of the unit.
        self._heartbeats = heartbeats
        # OC-R2: the lanes' rebind port. The family names the template's sealed binding and
        # the live coordinates; the lane that sealed it reseals it (never read here).
        self._lane_bindings = lane_bindings or LaneRebinders()
        # FT-B2 (ADR-0027): when composed, every admitted stage starts from a sealed Context
        # Packet; without it the template's prompt and workspace are used unchanged.
        self._context_packs = context_packs
        # FT-F1: the StageGraph admission boundary delivers queued instructions and context
        # into the admitted operation's packet (requires the packer).
        self._mailbox = mailbox

    async def materialize(
        self,
        request: StageGraphAdmissionActivityRequest,
    ) -> OperationWorkflowRequest:
        """Prepare and persist at once (callers that admit separately use prepare/persist)."""

        operation = await self.prepare(request)
        await self.persist(request, operation)
        return operation

    async def persist(
        self,
        request: StageGraphAdmissionActivityRequest,
        operation: OperationWorkflowRequest,
    ) -> None:
        """Persist the admitted child's exact binding before it is dispatched.

        Loop iter-1 L1-03: only an admitted operation is bound. The binding embeds the
        run-control revision, so a binding saved for a refused (`stale_run_version`)
        admission would make every correct re-admission conflict. A true duplicate with
        another intent still raises `IdempotencyConflict`, naming its stage and unit.
        """

        binding = bind_operation_execution_request(operation.operation)
        try:
            persisted = await self._operation_bindings.create_binding(
                binding,
                request_scope=request.request_scope,
            )
        except IdempotencyConflict as error:
            unit = operation.operation.runtime_unit
            raise IdempotencyConflict(
                f"{error} (stage {request.proposal.identity.stage_id}, "
                f"unit {unit.unit_key if unit is not None else 'unknown'}, "
                f"semantic attempt {binding.semantic_attempt_key})"
            ) from error
        if persisted != binding:
            raise ValueError("persisted StageGraph operation binding differs from exact intent")

    async def prepare(
        self,
        request: StageGraphAdmissionActivityRequest,
    ) -> OperationWorkflowRequest:
        """Build the exact OperationWorkflow child without persisting anything binding."""

        proposal = request.proposal
        template = await self._templates.get_template(
            semantic_input_binding_ref=request.semantic_input_binding_ref,
            operation_request_key=proposal.operation_request_key,
            request_scope=request.request_scope,
            run_id=request.run_id,
        )
        workspace = template.workspace.model_copy(
            update={
                "namespace_id": template.workspace.namespace_id.replace("{run_id}", request.run_id),
                "workspace_id": template.workspace.workspace_id.replace("{run_id}", request.run_id),
            }
        )
        prompt_segments = (
            template.prompt_segments
            if proposal.objective_override is None
            else (
                *template.prompt_segments,
                PromptSegment(
                    source_ref=f"stage-cycle-objective:{proposal.identity.semantic_key}",
                    source_revision=1,
                    # The cycle objective is a reducer-admitted run input,
                    # not a newly published privileged prompt definition.
                    trust_class="admitted_input",
                    content=proposal.objective_override,
                    rendered_digest=sha256_digest(proposal.objective_override),
                ),
            )
        )
        if self._context_packs is not None:
            # FT-B2: the packet replaces the ad hoc objective segment (the objective is its
            # `goals_and_criteria` item); materialized inputs and the `.mission/` files join
            # the compiled slots as read-only, digest-verified durable inputs.
            queued: tuple[PackCandidate, ...] = ()
            if self._mailbox is not None:
                stage = proposal.identity
                entries = await self._mailbox.deliver(
                    request.request_scope,
                    request.run_id,
                    delivery_key=(
                        f"stagegraph:{stage.semantic_key}:generation:{stage.execution_generation}"
                    ),
                    family="StageGraph",
                    node_key=stage.stage_id,
                    iteration_start=True,
                    lane_profile=default_lane_profile(template),
                    unit_key=stage_runtime_unit(request.request_scope, stage).unit_key,
                )
                queued = await self._context_packs.queued_candidates(
                    entries, request_scope=request.request_scope
                )
            sealed = await self._context_packs.pack_for_stage(
                request, template, extra_candidates=queued
            )
            prompt_segments = (*template.prompt_segments, sealed.prompt_segment)
            if sealed.slot_bindings:
                workspace = WorkspaceContract.model_validate(
                    {
                        **workspace.model_dump(mode="python"),
                        "slot_bindings": (*workspace.slot_bindings, *sealed.slot_bindings),
                    }
                )
        identity = OperationAttemptIdentity(
            run_id=request.run_id,
            operation_id=proposal.identity.operation_id,
            operation_attempt=proposal.identity.semantic_attempt,
        )
        # REQ-CP-EXEC-013: the mapped instance/cycle/slot location becomes the unit identity.
        runtime_unit = stage_runtime_unit(request.request_scope, proposal.identity)
        control_revision = request.projection.run_version + 1
        lane_binding, lane_dispatch = template.lane_binding, template.lane_dispatch
        if lane_binding is not None and lane_dispatch is not None:
            # SV-01: the lane rebinds its own bytes to the live attempt by digest.
            lane_binding, lane_dispatch = self._lane_bindings.rebind(
                lane_binding,
                lane_dispatch,
                LaneInvocation(
                    binding_id=f"deep-agent:{identity.semantic_key}",
                    run_id=request.run_id,
                    operation_id=identity.operation_id,
                    operation_attempt=identity.operation_attempt,
                    execution_generation=proposal.identity.execution_generation,
                    erc_digest=request.effective_configuration_digest,
                    control_revision=control_revision,
                    workspace=workspace,
                    reservation_id=proposal.reservation_id,
                    runtime_unit=runtime_unit,
                    capability_grant=template.capability_grant,
                ),
            )
        operation = OperationExecutionRequest.model_validate(
            {
                **template.model_dump(mode="python"),
                "identity": OperationAttemptIdentity(
                    run_id=identity.run_id,
                    operation_id=identity.operation_id,
                    operation_attempt=identity.operation_attempt,
                ),
                "request_scope": request.request_scope,
                "effective_configuration_digest": request.effective_configuration_digest,
                "run_control_revision": control_revision,
                "workspace": workspace,
                "lane_binding": lane_binding,
                "lane_dispatch": lane_dispatch,
                # WI-02: a dependent stage receives exactly its declared input bindings.
                "transfer": _stage_transfer(
                    template,
                    request,
                    promises=StageGraphBlueprint.model_validate(request.blueprint).output_promises,
                ),
                "budget_reservation_id": proposal.reservation_id,
                "budget_limits": proposal.reservation,
                "prompt_segments": prompt_segments,
                "prior_binding_id": None,
                "requested_at": request.occurred_at,
                "idempotency_key": (
                    f"stagegraph:{proposal.identity.semantic_key}:"
                    f"generation:{proposal.identity.execution_generation}"
                ),
                "runtime_unit": runtime_unit,
            }
        )
        if operation.identity.semantic_key != proposal.identity.semantic_key:
            raise ValueError("StageGraph and OperationWorkflow semantic identities diverged")
        operation = await attach_linked_context(operation, self._linked_exports)
        return OperationWorkflowRequest(
            semantic_attempt_id=operation.identity.semantic_key,
            execution_generation=proposal.identity.execution_generation,
            operation_kind="bound_operation",
            operation=operation,
            heartbeat_timeout_seconds=self._heartbeats.timeout_for(operation),
            segments=self._heartbeats.segments_for(operation),
            capacity_wait=self._heartbeats.capacity_wait,
        )


def validate_stagegraph_authority_batch(
    mutation: AtomicFamilyMutation,
    batch: ApplyAuthorityBatchAction,
) -> str | None:
    """Narrow StageGraph batch references to the exact producer decision under admission."""

    if not isinstance(mutation, StageGraphDecisionMutation):
        return "unexpected StageGraph mutation type"
    settlement_actions = tuple(
        action
        for action in batch.actions
        if isinstance(action, RecordOperationSettlementEvidenceAction)
    )
    output_actions = tuple(
        action for action in batch.actions if isinstance(action, RecordOutputEvidenceAction)
    )
    obligation_actions = tuple(
        action for action in batch.actions if isinstance(action, RecordObligationEvidenceAction)
    )
    if len(settlement_actions) != 1:
        return "StageGraph result batches require exactly one settlement observation"
    if mutation.decision_kind != "result_decided":
        if output_actions or obligation_actions:
            return "only StageGraph result decisions may batch evidence acceptance"
        return None
    payload = mutation.decision_payload.get("prior_liability")
    if not isinstance(payload, dict):
        return "StageGraph result batch lacks prior producer liability binding"
    semantic_key = payload.get("semantic_attempt_id")
    evidence = settlement_actions[0].evidence
    if evidence.settlement_id != f"stagegraph-result:{semantic_key}":
        return "StageGraph settlement observation does not bind the producer liability"
    if evidence.settlement_payload_digest != mutation.decision_payload.get("observation_digest"):
        return "StageGraph settlement observation digest does not bind the result"
    return None


def validate_control_admission(
    mutation: AtomicFamilyMutation, command: LifecycleCommand
) -> str | None:
    if not isinstance(mutation, StageGraphControlAdmissionMutation) or not isinstance(
        command.action, AdmitHumanGateAction
    ):
        return "Human Gate admission requires its typed atomic mutation and action"
    gate = HumanGateSpec.model_validate(mutation.decision_payload.get("human_gate"))
    proposal = mutation.decision_payload.get("proposal")
    if not isinstance(proposal, dict) or proposal.get("reservation") != {}:
        return "Human Gate admission cannot reserve cognitive resources"
    identity = proposal.get("identity")
    candidate = identity.get("candidate") if isinstance(identity, dict) else None
    if not isinstance(candidate, dict) or candidate.get("stage_id") != gate.gate_key:
        return "Human Gate candidate differs from its policy"
    if (
        command.action.gate_key != gate.gate_key
        or command.action.gate_spec_digest != sha256_digest(gate)
        or command.action.exact_operation_request_ref != mutation.exact_operation_request_ref
    ):
        return "Human Gate action differs from its atomic mutation"
    return None


def validate_admission_rejection(
    mutation: AtomicFamilyMutation, command: LifecycleCommand
) -> str | None:
    if not isinstance(mutation, StageGraphAdmissionRejectionMutation) or not isinstance(
        command.action, RecordAdmissionRejectionAction
    ):
        return "admission rejection requires its exact typed atomic mutation and action"
    denied = LifecycleCommand.model_validate(mutation.decision_payload.get("rejected_command"))
    proposal = mutation.decision_payload.get("proposal")
    if not isinstance(proposal, dict) or not isinstance(denied.action, ReserveBudgetAction):
        return "admission rejection requires its frozen reserve proposal"
    identity = proposal.get("identity")
    candidate = identity.get("candidate") if isinstance(identity, dict) else None
    try:
        stage_identity = TypeAdapter(StageExecutionIdentity).validate_python(identity)
    except (ValueError, TypeError):
        return "admission rejection requires its full typed candidate identity"
    semantic_digest = sha256_digest(stage_identity.semantic_key)[7:]
    action = command.action
    if (
        denied.command_id != f"stagegraph:admit-{semantic_digest}"
        or denied.request_scope != command.request_scope
        or denied.run_id != command.run_id
        or stage_identity.run_id != command.run_id
        or denied.expected_run_version != command.expected_run_version
        or denied.actor != orchestration_lifecycle_actor()
        or proposal.get("reservation_id") != f"reservation:{stage_identity.semantic_key}"
        or mutation.exact_operation_request_ref != f"operation-request:{semantic_digest}"
        or not isinstance(candidate, dict)
        or candidate.get("stage_id") != action.stage_id
        or action.rejected_command_id != denied.command_id
        or action.rejected_command_issuer != denied.idempotency_issuer
        or action.rejected_command_fingerprint
        != contract_fingerprint(denied, exclude={"occurred_at"})
        or action.rejected_family_fingerprint
        != mutation.decision_payload.get("rejected_family_fingerprint")
        or action.exact_operation_request_ref != mutation.exact_operation_request_ref
        or proposal.get("exact_operation_request_ref") != mutation.exact_operation_request_ref
        or denied.action.reservation_id != proposal.get("reservation_id")
        or denied.action.amounts != proposal.get("reservation")
    ):
        return "admission rejection action differs from its actual reserve proposal"
    return None


def register_stagegraph_family_mutations(registry: FamilyAdmissionRegistry) -> None:
    """Publish the exact StageGraph policy for integrator-owned composition."""

    registry.register(
        StageGraphAdmissionRejectionMutation,
        family_kind="stagegraph",
        mutation_kind="decision_committed",
        required_permission="workflow_run.reserve_budget",
        allowed_action_kinds=frozenset({"record_admission_rejection"}),
        action_binding_validator=validate_admission_rejection,
    )
    registry.register(
        StageGraphControlAdmissionMutation,
        family_kind="stagegraph",
        mutation_kind="decision_committed",
        required_permission="workflow_run.reserve_budget",
        allowed_action_kinds=frozenset({"admit_human_gate"}),
        action_binding_validator=validate_control_admission,
    )
    registry.register(
        StageGraphDecisionMutation,
        family_kind="stagegraph",
        mutation_kind="decision_committed",
        required_permission="workflow_run.reserve_budget",
        allowed_action_kinds=frozenset(
            {
                "reserve_budget",
                "record_usage",
                "terminalize",
                "apply_authority_batch",
            }
        ),
        allowed_batch_action_kinds=frozenset(
            {
                "record_obligation_evidence",
                "record_output_evidence",
                "record_operation_settlement_evidence",
            }
        ),
        required_batch_action_kinds=frozenset({"record_operation_settlement_evidence"}),
        batch_binding_validator=validate_stagegraph_authority_batch,
    )


class GoalDirectedLaunchService:
    """Resolve one admitted GoalDirected run into immutable Temporal input."""

    def __init__(
        self,
        run_control: RunControlService,
        control_plane: ControlPlaneService,
    ) -> None:
        self._run_control = run_control
        self._control_plane = control_plane

    async def prepare(
        self,
        request_scope: str,
        run_id: str,
        *,
        initial_goal: str,
        execution_epoch: int = 1,
        task_timeout_seconds: int = 300,
        orchestration_authority_ref: str = ORCHESTRATION_AUTHORITY_REF,
        semantic_input_binding_ref: str = "",
        human_review: HumanGateSpec | None = None,
    ) -> GoalDirectedRunInput:
        if not initial_goal.strip():
            raise ValueError("GoalDirected launch requires a concrete initial goal")
        if execution_epoch != 1:
            raise ValueError(
                "execution epoch rollover requires the deferred orchestration continuity contract"
            )
        projection = await self._run_control.get_run(request_scope, run_id)
        configuration = await self._control_plane.retrieve_for_admission(
            projection.effective_configuration_digest
        )
        if configuration.digest != projection.effective_configuration_digest:
            raise ValueError("admitted effective configuration digest does not match F1 authority")
        blueprint = configuration.selected_blueprint
        if not isinstance(blueprint, GoalDirectedBlueprint):
            raise ValueError("admitted blueprint is not GoalDirected")
        blueprint_ref = next(
            (ref for ref in configuration.source_refs if ref.kind == DefinitionKind.BLUEPRINT),
            None,
        )
        if blueprint_ref is None or blueprint_ref.digest != sha256_digest(blueprint):
            raise ValueError("exact GoalDirected reference does not match the frozen blueprint")
        budget = await self._run_control.get_budget(request_scope, run_id)
        envelope_digest = sha256_digest(
            {
                "initial_goal": initial_goal,
                "objective_contract": blueprint.objective_contract,
                "acceptance_contract": blueprint.acceptance_contract,
                "workflow_invariants": configuration.workflow_type.invariants,
                "admitted_input_manifest": configuration.input_manifest,
                "admitted_input_classes": blueprint.admitted_input_classes,
                "effective_authority": configuration.effective_authority,
                "blueprint_authority_ceiling": blueprint.authority_ceiling,
                "budget_limits": budget.limits,
                "prohibited_work": blueprint.prohibited_work,
                "required_output_contracts": blueprint.required_output_contracts,
                "required_obligation_refs": blueprint.required_obligation_refs,
                "allowed_operation_classes": blueprint.allowed_operation_classes,
                "allowed_async_subgoal_classes": blueprint.allowed_async_subgoal_classes,
                "allowed_linked_run_slot_ids": blueprint.allowed_linked_run_slot_ids,
                "verifier_policy": blueprint.verifier_policy,
                "session_policy": blueprint.session_policy,
                "handoff_policy": blueprint.handoff_policy,
                "workspace_policy": blueprint.workspace_policy,
                "convergence_policy": blueprint.convergence_policy,
                "max_iterations": blueprint.max_iterations,
                "protected_fields": blueprint.protected_scope_policy.protected_fields,
            }
        )
        initial_revision_id = sha256_digest(
            {
                "run_id": run_id,
                "execution_epoch": execution_epoch,
                "revision": 1,
                "objective": initial_goal,
                "envelope_digest": envelope_digest,
            }
        )
        revision_digest = sha256_digest(
            {
                "schema_version": "belllabs.goal-revision.v1",
                "revision_id": initial_revision_id,
                "revision": 1,
                "parent_revision_id": None,
                "envelope_digest": envelope_digest,
                "objective": initial_goal,
                "tactical_changes": (),
                "evidence_refs": (configuration.input_manifest.digest,),
                "unmet_obligations": tuple(sorted(projection.required_obligation_refs)),
                "proposer": "application:goal-launch",
                "deciding_authority": orchestration_authority_ref,
                "applicability": "remaining_run",
                "tactics": (),
                "subgoals": (),
                "coverage_emphasis": (),
            }
        )
        initial_revision = GoalRevision(
            schema_version="belllabs.goal-revision.v1",
            revision_id=initial_revision_id,
            revision=1,
            parent_revision_id=None,
            canonical_digest=revision_digest,
            envelope_digest=envelope_digest,
            objective=initial_goal,
            tactical_changes=(),
            evidence_refs=(configuration.input_manifest.digest,),
            unmet_obligations=tuple(sorted(projection.required_obligation_refs)),
            proposer="application:goal-launch",
            deciding_authority=orchestration_authority_ref,
            applicability="remaining_run",
        )
        return GoalDirectedRunInput(
            run_id=run_id,
            request_scope=request_scope,
            effective_configuration_digest=configuration.digest,
            blueprint_digest=blueprint_ref.digest,
            blueprint=blueprint.model_dump(mode="json"),
            envelope_digest=envelope_digest,
            initial_revision=initial_revision,
            initial_run_version=projection.version,
            execution_epoch=execution_epoch,
            task_timeout_seconds=task_timeout_seconds,
            orchestration_authority_ref=orchestration_authority_ref,
            correlation_id=f"orchestration:{run_id}:epoch:{execution_epoch}",
            baseline_reservation=dict(budget.reservations.get("baseline", {})),
            required_obligation_refs=tuple(sorted(projection.required_obligation_refs)),
            required_output_contract_refs=tuple(
                sorted(configuration.workflow_type.output_contracts)
            ),
            semantic_input_binding_ref=semantic_input_binding_ref,
            human_review=human_review,
        )


PreparedWorkflowInput = StageGraphRunInput | GoalDirectedRunInput


class WorkflowLaunchDispatcher:
    """Select an available orchestrator only from the admitted blueprint family."""

    def __init__(
        self,
        *,
        stagegraph: StageGraphLaunchService | None,
        goal_directed: GoalDirectedLaunchService | None,
        run_control: RunControlService,
        control_plane: ControlPlaneService,
    ) -> None:
        self._stagegraph = stagegraph
        self._goal_directed = goal_directed
        self._run_control = run_control
        self._control_plane = control_plane

    async def prepare(
        self,
        request_scope: str,
        run_id: str,
        *,
        initial_goal: str | None = None,
        task_timeout_seconds: int = 300,
        orchestration_authority_ref: str = ORCHESTRATION_AUTHORITY_REF,
        semantic_input_binding_ref: str = "",
        human_gates: tuple[HumanGateSpec, ...] = (),
        human_review: HumanGateSpec | None = None,
        stage_inputs: tuple[StageAuthoredInput, ...] = (),
    ) -> PreparedWorkflowInput:
        projection = await self._run_control.get_run(request_scope, run_id)
        configuration = await self._control_plane.retrieve_for_admission(
            projection.effective_configuration_digest
        )
        blueprint = configuration.selected_blueprint
        if isinstance(blueprint, StageGraphBlueprint):
            if self._stagegraph is None:
                raise ValueError("StageGraph execution family is unavailable")
            if initial_goal is not None:
                raise ValueError("StageGraph launch does not accept a GoalDirected initial goal")
            if human_review is not None:
                raise ValueError("StageGraph launch does not accept a GoalDirected human review")
            return await self._stagegraph.prepare(
                request_scope,
                run_id,
                task_timeout_seconds=task_timeout_seconds,
                orchestration_authority_ref=orchestration_authority_ref,
                semantic_input_binding_ref=semantic_input_binding_ref,
                human_gates=human_gates,
                authored_inputs=stage_inputs,
            )
        if isinstance(blueprint, GoalDirectedBlueprint):
            if self._goal_directed is None:
                raise ValueError("GoalDirected execution family is unavailable")
            if initial_goal is None:
                raise ValueError("GoalDirected launch requires a concrete initial goal")
            if human_gates:
                raise ValueError("GoalDirected launch does not accept Stage Graph human gates")
            if stage_inputs:
                raise ValueError("GoalDirected launch does not accept Stage Graph stage inputs")
            return await self._goal_directed.prepare(
                request_scope,
                run_id,
                initial_goal=initial_goal,
                task_timeout_seconds=task_timeout_seconds,
                orchestration_authority_ref=orchestration_authority_ref,
                semantic_input_binding_ref=semantic_input_binding_ref,
                human_review=human_review,
            )
        raise ValueError(f"unsupported admitted blueprint family: {type(blueprint).__name__}")

    async def prepare_bound(
        self,
        request_scope: str,
        run_id: str,
        *,
        semantic_binding: RunSemanticInputBinding,
        binding_service: RunSemanticInputBindingService,
        initial_goal: str | None = None,
        task_timeout_seconds: int = 300,
        orchestration_authority_ref: str = ORCHESTRATION_AUTHORITY_REF,
    ) -> PreparedWorkflowInput:
        """Verify, freeze, and attach semantic inputs before Temporal submission."""

        prepared = await self.prepare(
            request_scope,
            run_id,
            initial_goal=initial_goal,
            task_timeout_seconds=task_timeout_seconds,
            orchestration_authority_ref=orchestration_authority_ref,
        )
        expected_family = (
            "StageGraph" if isinstance(prepared, StageGraphRunInput) else "GoalDirected"
        )
        if (
            semantic_binding.request_scope != request_scope
            or semantic_binding.run_id != run_id
            or semantic_binding.blueprint_family != expected_family
            or semantic_binding.effective_configuration_digest
            != prepared.effective_configuration_digest
            or semantic_binding.blueprint_digest != prepared.blueprint_digest
        ):
            raise ValueError("semantic input binding does not match the admitted workflow launch")
        binding_ref = await binding_service.freeze(semantic_binding)
        return replace(prepared, semantic_input_binding_ref=binding_ref)


class StageOperationExecutor(Protocol):
    """F4 seam for bounded runtime execution; issue 3 uses explicit fakes."""

    async def execute(self, request: StageOperationRequest) -> StageOperationResult: ...


class WorkflowEvaluator(Protocol):
    """Typed evaluator seam; free text never controls orchestration."""

    async def evaluate(self, request: WorkflowEvaluationRequest) -> WorkflowEvaluationResult: ...


class RunControlLifecycleGateway:
    """Issues orchestration facts only through the authoritative F2 command service."""

    def __init__(
        self,
        service: RunControlService,
        binding_verifier: OrchestrationBindingVerifier,
        actor: ActorContext,
    ) -> None:
        self._service = service
        self._binding_verifier = binding_verifier
        self._actor = actor

    async def execute(self, request: LifecycleCommandRequest) -> LifecycleCommandOutcome:
        if not all(
            (
                request.run_id,
                request.request_scope,
                request.effective_configuration_digest,
                request.idempotency_issuer,
                request.correlation_id,
                request.blueprint_digest,
            )
        ):
            raise ValueError("lifecycle activity request is missing its run-scoped binding")
        action = LIFECYCLE_ACTION_ADAPTER.validate_python(request.action)
        occurred_at = request.occurred_at or datetime.now(UTC)
        await self._binding_verifier.verify(
            request.effective_configuration_digest,
            request.blueprint_digest,
        )
        bound_projection = await self._service.get_run(
            request.request_scope,
            request.run_id,
        )
        if (
            bound_projection.effective_configuration_digest
            != request.effective_configuration_digest
        ):
            raise ValueError(
                "orchestration context does not match the admitted effective configuration"
            )
        result = await self._service.execute(
            LifecycleCommand(
                command_id=request.command_id,
                idempotency_issuer=request.idempotency_issuer,
                request_scope=request.request_scope,
                run_id=request.run_id,
                expected_run_version=request.expected_run_version,
                actor=self._actor,
                action=action,
                reason=request.reason,
                evidence_refs=request.evidence_refs,
                occurred_at=occurred_at,
                correlation_id=request.correlation_id,
                causation_id=request.command_id,
            )
        )
        projection = bound_projection
        if result.status == CommandStatus.ACCEPTED:
            transitions = await self._service.list_transitions(
                request.request_scope,
                request.run_id,
            )
            exact_projection = next(
                (
                    transition.resulting_projection
                    for transition in transitions
                    if transition.resulting_version == result.resulting_run_version
                ),
                None,
            )
            if exact_projection is None:
                raise ValueError("accepted lifecycle command has no exact resulting transition")
            projection = exact_projection
        evidence_payload = [
            item.model_dump(mode="json")
            for item in sorted(
                projection.accepted_obligation_evidence,
                key=lambda item: item.obligation_ref,
            )
        ]
        return LifecycleCommandOutcome(
            accepted=result.status == CommandStatus.ACCEPTED,
            resulting_run_version=result.resulting_run_version,
            phase=result.phase.value,
            reason_code=result.reason_code,
            evidence_frontier_digest=projection.evidence_frontier_digest,
            obligation_revision=projection.obligation_revision,
            accepted_obligation_evidence_digest=sha256_digest(evidence_payload),
            required_obligations_accepted=projection.required_obligation_refs
            <= {item.obligation_ref for item in projection.accepted_obligation_evidence},
            workflow_type_digest=projection.workflow_type_ref.digest,
            terminal_outcome=projection.terminal_outcome,
        )


_EXPAND_PLACEMENT: dict[str, Placement] = {"materialize": "file", "inline": "inline"}
_RELEASE_OMISSION_CODES = {
    "omitted": "RELEASE_OPTIONAL_PENDING",
    "surplus": "RELEASE_SURPLUS",
}


def _stage_transfer(
    template: OperationExecutionRequest,
    request: StageGraphAdmissionActivityRequest,
    *,
    promises: OutputPromiseSet | None = None,
) -> TransferSelection | None:
    """The stage's declared ``from: <producer>.<output>`` bindings as its transfer selection
    (no bindings: the template's first-invocation selection, which invents no predecessor).

    OVE-171: under the graph routes semantics the release froze each producer's part
    (``released_by[].selection``): only selected producers become inputs; a surplus group
    member or an optional input still pending at release is a visible release omission, so a
    late arrival can never enter the sealed plan."""

    selection = template.transfer
    if selection is None:
        return None
    stage = request.proposal.identity.stage_id
    authored = [item for item in request.authored_inputs if item.consumer_stage_id == stage]

    def output_key(producer: str, slot: str) -> str:
        # Stage dependencies name local slots; transfer sources name registered promise
        # keys. Resolve at this boundary, never guess aliases in the exact content reader.
        key = f"{producer}.{slot}"
        obligation = None if promises is None else promises.obligation(key)
        if obligation is None or obligation.owner_position != producer:
            raise ValueError(f"stage input {producer}.{slot} has no admitted owned output promise")
        return obligation.key

    # OVE-171 slice D: a revisited region entry also receives the exit outputs of the prior
    # visit (required: the interpreter carried them only because that visit accepted them).
    carried = list(
        dict.fromkeys(
            (
                f"carry-{item.producer_output_slot_id}",
                item.producer_stage_key,
                output_key(item.producer_stage_key, item.producer_output_slot_id),
            )
            for item in request.proposal.frozen_input_bindings
            if item.consumer_input_slot_id.startswith("carry:")
        )
    )
    if not authored:
        return transfer_builders.dependent_stage(selection, carried) if carried else selection
    frozen = {
        (item.producer_stage_id, item.producer_output_slot_id): item.selection
        for item in request.proposal.released_by
        if item.selection is not None
    }
    by_producer: dict[str, set[str | None]] = {}
    for (producer, _output), frozen_part in frozen.items():
        by_producer.setdefault(producer, set()).add(frozen_part)

    def part(item: StageAuthoredInput) -> str | None:
        chosen = frozen.get((item.producer_stage_id, item.producer_output_slot_id))
        if chosen is None and frozen:
            # An ordering-only edge (the producer's declared slots): one part per producer.
            parts = by_producer.get(item.producer_stage_id, set())
            chosen = next(iter(parts)) if len(parts) == 1 else None
        return chosen

    bindings = []
    omitted = []
    for item in authored:
        release_part = part(item)
        if release_part in {None, "selected"}:
            bindings.append(
                (
                    item.name,
                    item.producer_stage_id,
                    output_key(item.producer_stage_id, item.producer_output_slot_id),
                )
            )
        else:
            omitted.append(
                (
                    item.name,
                    item.producer_stage_id,
                    output_key(item.producer_stage_id, item.producer_output_slot_id),
                    _RELEASE_OMISSION_CODES.get(release_part or "", "RELEASE_MEMBER_UNAVAILABLE"),
                )
            )
    optional = {item.name for item in authored if not item.required}
    # L1-08: the authored expansion tier is the input's placement (`materialize` a read-only
    # file under /inputs/<binding>/<revision>/, `inline` the prompt); `auto` and `reference`
    # keep the receiver profile's default.
    placements: dict[str, Placement] = {
        item.name: _EXPAND_PLACEMENT[item.expand]
        for item in authored
        if item.expand in _EXPAND_PLACEMENT
    }
    return transfer_builders.dependent_stage(
        selection,
        [*bindings, *carried],
        optional=optional,
        omitted=omitted,
        placements=placements,
    )

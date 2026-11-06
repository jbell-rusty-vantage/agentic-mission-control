from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from pydantic import TypeAdapter, ValidationError

from mission_control.application.context.linked_transfer import LinkedExportPort
from mission_control.application.context.pack_service import (
    ArtifactBytesPort,
    ContextPackService,
    SealedPacket,
    context_packet_ref,
)
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.execution.operations.journaled_operation_execution import (
    operation_effect_claim_id,
)
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
    operation_settlement_id,
)
from mission_control.application.execution.operations.semantic_operation_bindings import (
    SemanticOperationBindingRepository,
)
from mission_control.application.execution.service import (
    FamilyAdmissionRegistry,
    RunControlService,
)
from mission_control.application.outputs.fulfillment import HostAccess
from mission_control.application.programs.completion_validation import (
    ArtifactPublicationPending,
    expire_pending,
    validate_completion,
    validated_result,
)
from mission_control.application.programs.goal_context import GoalContext, resolve_goal_context
from mission_control.application.programs.linked_context import attach_linked_context
from mission_control.application.resolution.lane_bindings import LaneInvocation, LaneRebinders
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context import transfer_builders
from mission_control.domain.context.packet import PackCandidate
from mission_control.domain.context.transfer import ProducerAttempt, TransferSelection
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionBinding,
    OperationExecutionRequest,
    OperationExecutionResult,
    OperationWorkflowRequest,
    OperationWorkflowResult,
    PromptSegment,
    PromptTrustClass,
    WorkspaceContract,
    WorkspaceMount,
    WorkspaceOwner,
    WorkspaceOwnerKind,
    WorkspaceSlotBinding,
    workspace_durable_reference,
)
from mission_control.domain.execution.heartbeats import (
    DEFAULT_OPERATION_HEARTBEATS,
    OperationHeartbeatPolicy,
)
from mission_control.domain.execution.lane_turns import default_lane_profile
from mission_control.domain.execution.lanes import LaneDispatch
from mission_control.domain.graph_runtime.identities import RuntimeUnitIdentity
from mission_control.domain.outputs.contracts import FulfillmentResult
from mission_control.domain.outputs.current_set import with_current_set_index
from mission_control.domain.policies.contracts import (
    ActorContext,
    BudgetState,
    CommandStatus,
    EffectLedgerState,
    LifecycleCommand,
    ReserveBudgetAction,
    RunProjection,
)
from mission_control.domain.programs.completion import CompletionValidation
from mission_control.domain.programs.contracts import (
    CompletionCandidateRecord,
    CompletionDecisionRecord,
    CompletionDisposition,
    CompletionRecords,
    GoalExecutionClaim,
    GoalExecutionResult,
    GoalHandoff,
    GoalReleasedBy,
    GoalRevision,
    GoalVerificationResult,
)
from mission_control.domain.programs.goal_directed_runtime import (
    GoalFamilyDecisionMutation,
    GoalHandoffDraft,
    GoalNamedExecutorObservation,
    GoalOperationDispatch,
    GoalOperationPreparationRequest,
    GoalOperationReconciliationRequest,
    GoalOperationReconciliationResult,
    GoalOperationSettlement,
    GoalVerifierObservation,
)
from mission_control.domain.programs.human_gate import feedback_instruction
from mission_control.domain.programs.runtime_units import (
    goal_operation_id,
    goal_runtime_unit,
    goal_unit_workspace_root,
)
from mission_control.domain.resolution.sealed import SealedLaneBinding

# F-T3-1 (output contracts specification §3.6): the reason prefix of the irrecoverable failure
# reference a non-parsing executor payload settles with.
OUTPUT_UNPARSEABLE = "output_unparseable"


class GoalDirectedDocumentRepository(Protocol):
    async def load_iteration(
        self, request_scope: str, run_id: str, semantic_key: str
    ) -> dict[str, Any] | None: ...

    async def persist_revision(
        self, request_scope: str, run_id: str, revision: GoalRevision, recorded_at: datetime
    ) -> str: ...

    async def persist_iteration(
        self,
        request_scope: str,
        result: GoalExecutionResult,
        goal_revision_id: str,
        recorded_at: datetime,
    ) -> str: ...

    async def persist_handoff(
        self, request_scope: str, handoff: GoalHandoff, recorded_at: datetime
    ) -> str: ...

    async def persist_verification(
        self,
        request_scope: str,
        run_id: str,
        goal_revision_id: str,
        verification: GoalVerificationResult,
        recorded_at: datetime,
        *,
        completion_validation: CompletionValidation | None = None,
        request_digest: str | None = None,
    ) -> str: ...

    async def load_verification(
        self,
        request_scope: str,
        run_id: str,
        verification_id: str,
    ) -> dict[str, Any] | None: ...


class CompletionRecordPort(Protocol):
    """1.4.4 (P3.8): the decision-table writer for decisions made outside a family
    transaction (the verifier reconciliation). Idempotent by key."""

    async def record(
        self,
        request_scope: str,
        run_id: str,
        records: CompletionRecords,
        *,
        actor_ref: str,
        recorded_at: datetime,
    ) -> None: ...


class InMemoryCompletionRecords:
    """Behavioral test adapter: first write per key wins (`ON CONFLICT DO NOTHING`)."""

    def __init__(self) -> None:
        self.candidates: dict[tuple[str, str], CompletionCandidateRecord] = {}
        self.decisions: dict[tuple[str, str, str], CompletionDecisionRecord] = {}

    async def record(
        self,
        request_scope: str,
        run_id: str,
        records: CompletionRecords,
        *,
        actor_ref: str,
        recorded_at: datetime,
    ) -> None:
        del actor_ref, recorded_at
        if records.candidate is not None:
            self.candidates.setdefault(
                (request_scope, records.candidate.candidate_key), records.candidate
            )
        if records.decision is not None:
            self.decisions.setdefault(
                (request_scope, run_id, records.decision.decision_key), records.decision
            )


def goal_released_by(request: GoalOperationPreparationRequest) -> GoalReleasedBy:
    """1.4.4 (P1.2): what released the role unit being admitted. A verifier follows the
    executor of its iteration (same claim identity, attempt 1 as the workflow admits it);
    an executor admitted with a handoff follows the verification that sent it back (the
    prior verifier's unit key is not in the preparation request; the handoff names it);
    any other executor starts its iteration."""

    if request.operation_role == "verifier":
        prior: str | None = None
        if request.agent_run is not None and request.session_generation is not None:
            prior = goal_runtime_unit(
                request_scope=request.request_scope,
                run_id=request.run_id,
                execution_epoch=request.execution_epoch,
                operation_id=goal_operation_id(request.goal_iteration, "executor"),
                operation_attempt=1,
                goal_iteration=request.goal_iteration,
                goal_revision_id=request.goal_revision_id,
                operation_role="executor",
                agent_run=request.agent_run,
                session_generation=request.session_generation,
            ).unit_key
        return GoalReleasedBy(
            kind="verifier_after_executor", prior_unit_key=prior, handoff_ref=None
        )
    if request.handoff_ref is not None:
        return GoalReleasedBy(
            kind="executor_after_verification",
            prior_unit_key=None,
            handoff_ref=request.handoff_ref,
        )
    return GoalReleasedBy(kind="iteration_start", prior_unit_key=None, handoff_ref=None)


def goal_completion_disposition(
    verification: GoalVerificationResult,
) -> CompletionDisposition:
    """P10 decision table, Goal Directed: an accepting verifier -> `accepted`; a rejecting
    verifier (`rejected`, `revision_required`, `repair_required`) that saw progress ->
    `needs_more_work`; otherwise `rejected`."""

    if verification.decision == "accepted":
        return "accepted"
    if verification.progress_made:
        return "needs_more_work"
    return "rejected"


def _executor_attempt(operation_identity: str) -> int:
    """The attempt ordinal of an executor semantic key (`...:attempt:{n}`); 1 when absent."""

    prefix, separator, tail = operation_identity.rpartition(":attempt:")
    if separator and prefix and tail.isdigit():
        return int(tail)
    return 1


def goal_completion_records(
    request: GoalOperationReconciliationRequest,
    verification: GoalVerificationResult,
    validation: CompletionValidation | None,
) -> CompletionRecords:
    """1.4.4 (P3.8): the decision-table rows of one verification. The decision is keyed by
    the verification id; the candidate is the executor's settlement (keyed by its
    settlement id, under the executor's activation); `goal_id` stays NULL."""

    executor_result = request.executor_result
    assert executor_result is not None  # the request validator requires it for a verifier
    identity = request.claim.identity
    executor_unit = goal_runtime_unit(
        request_scope=request.request_scope,
        run_id=identity.iteration.run_id,
        execution_epoch=identity.iteration.execution_epoch,
        operation_id=goal_operation_id(identity.iteration.goal_iteration, "executor"),
        operation_attempt=_executor_attempt(executor_result.operation_identity),
        goal_iteration=identity.iteration.goal_iteration,
        goal_revision_id=identity.iteration.goal_revision_id,
        operation_role="executor",
        agent_run=identity.agent_run,
        session_generation=identity.session_generation,
    ).unit_key
    candidate_key = operation_settlement_id(executor_result.operation_binding_ref)
    candidate = CompletionCandidateRecord(
        candidate_key=candidate_key,
        activation_key=executor_unit,
        # The executor's generation: the verifier's request carries the same one, since the
        # Goal workflow prepares every role unit at execution generation 1 and
        # `GoalExecutionResult` carries none of its own (Tracing Stage 3 review note).
        execution_generation=request.operation_request.execution_generation,
        candidate={
            "output_refs": list(executor_result.output_refs),
            "evidence_refs": list(executor_result.evidence_refs),
            "output_contract_ref": executor_result.output_contract_ref or None,
            "frontier_digest": sha256_digest(executor_result.frontier_payload()),
            "disposition": executor_result.disposition,
        },
        artifact_refs=executor_result.output_refs,
        evidence_refs=executor_result.evidence_refs,
    )
    reason_codes: tuple[str, ...] = tuple(validation.reason_codes) if validation else ()
    if verification.blocker_class:
        reason_codes = (*reason_codes, f"blocker:{verification.blocker_class}")
    decision = CompletionDecisionRecord(
        decision_key=verification.verification_id,
        activation_key=executor_unit,
        candidate_key=candidate_key,
        policy_digest=sha256_digest(
            {
                "verifier_policy_binding_ref": verification.verifier_policy_binding_ref,
                "rubric_ref": verification.rubric_ref,
                "rubric_version": verification.rubric_version,
                "acceptance_contract_ref": verification.acceptance_contract_ref,
                "acceptance_version": verification.acceptance_version,
            }
        ),
        contract_digest=sha256_digest(
            {
                "required_output_contract_refs": sorted(request.required_output_contract_refs),
                "output_contract_ref": executor_result.output_contract_ref or None,
            }
        ),
        result_disposition=goal_completion_disposition(verification),
        requirement_refs=tuple(
            sorted({*verification.accepted_obligation_refs, *verification.unmet_obligations})
        ),
        result_refs=executor_result.output_refs,
        reason_codes=reason_codes,
        decision={
            "decision": verification.decision,
            "progress_made": verification.progress_made,
            "verification_ref": verification.verification_ref,
            "verification_digest": verification.verification_digest,
            "accepted_obligation_refs": list(verification.accepted_obligation_refs),
            "unmet_obligations": list(verification.unmet_obligations),
            "completion_validation": validation.status if validation else "not_evaluated",
        },
    )
    return CompletionRecords(candidate=candidate, decision=decision)


class GoalOperationTemplateProvider(Protocol):
    async def get_template(
        self,
        *,
        semantic_input_binding_ref: str,
        operation_role: str,
        request_scope: str,
        run_id: str,
    ) -> OperationExecutionRequest: ...


class GoalOperationTemplateRepository(GoalOperationTemplateProvider, Protocol):
    async def persist_templates(
        self,
        *,
        request_scope: str,
        semantic_input_binding_ref: str,
        executor: OperationExecutionRequest,
        verifier: OperationExecutionRequest,
        recorded_at: datetime,
    ) -> None: ...


class InMemoryGoalOperationTemplateRepository:
    """Deterministic test adapter for immutable per-run operation templates."""

    def __init__(self) -> None:
        self._templates: dict[
            tuple[str, str, str],
            OperationExecutionRequest,
        ] = {}

    async def persist_templates(
        self,
        *,
        request_scope: str,
        semantic_input_binding_ref: str,
        executor: OperationExecutionRequest,
        verifier: OperationExecutionRequest,
        recorded_at: datetime,
    ) -> None:
        del recorded_at
        for operation_role, template in (("executor", executor), ("verifier", verifier)):
            key = (request_scope, semantic_input_binding_ref, operation_role)
            prior = self._templates.get(key)
            if prior is not None and prior != template:
                raise ValueError("GoalDirected operation template identity conflict")
            self._templates[key] = template

    async def get_template(
        self,
        *,
        semantic_input_binding_ref: str,
        operation_role: str,
        request_scope: str,
        run_id: str,
    ) -> OperationExecutionRequest:
        del run_id
        template = self._templates.get((request_scope, semantic_input_binding_ref, operation_role))
        if template is None:
            raise ValueError("GoalDirected operation template is unavailable")
        return template


class GoalOperationSettlementUnavailable(ValueError):
    """The operation has no accepted run-control settlement the family may consume."""


class GoalAdmissionStale(RuntimeError):
    """An operation admission was stale: the run moved past the family's expected version."""

    def __init__(self, *, current_run_version: int, phase: str) -> None:
        super().__init__(
            f"GoalDirected operation admission is stale: run is at version "
            f"{current_run_version} ({phase})"
        )
        self.current_run_version = current_run_version
        self.phase = phase


class GoalOperationSettlementPort(Protocol):
    async def observe(
        self,
        request: GoalOperationReconciliationRequest,
        provider_result: OperationExecutionResult,
    ) -> GoalOperationSettlement:
        """The operation's accepted run-control settlement, or raise."""
        ...

    async def observe_terminal(
        self,
        request: GoalOperationReconciliationRequest,
        provider_result: OperationExecutionResult,
    ) -> GoalOperationSettlement:
        """RRM-008: the settlement of a cancelled or failed operation, or raise."""
        ...


class GoalFulfillmentConvergence(Protocol):
    """W1 (OVE-169): the run's explicit output fulfillment at the convergence boundary
    (`OutputFulfillmentService.converge`); None for a run that registered no promises."""

    async def converge(
        self,
        access: HostAccess,
        run_id: str,
        *,
        operation_ref: str,
        generation: int,
        promote: bool = True,
    ) -> FulfillmentResult | None: ...


class GoalOperationBindingReader(Protocol):
    async def get_binding_by_id(
        self, binding_id: str, *, request_scope: str
    ) -> OperationExecutionBinding | None: ...


class GoalOperationSettlementReader(Protocol):
    async def get_run(self, request_scope: str, run_id: str) -> RunProjection: ...

    async def get_budget(self, request_scope: str, run_id: str) -> BudgetState: ...

    async def get_effects(self, request_scope: str, run_id: str) -> EffectLedgerState: ...


class RunControlGoalOperationSettlements:
    """Consume the journaled run-control settlement of one GoalDirected operation (RRM-016).

    The operation boundary (`OperationExecutionService` with the journaled coordinator)
    claims, observes and settles the operation exactly once in run control: one usage record
    under the operation's settlement identity against its own reservation, the effect
    settlement, and the accepted settlement evidence bound to the operation binding. The
    family consumes that settlement as StageGraph's `decide_result` does: it verifies the
    authoritative facts and continues from the current run version. It never records the
    operation's usage itself (REQ-CP-RUN-006/009: a budget settles once).
    """

    def __init__(
        self,
        run_control: GoalOperationSettlementReader,
        bindings: GoalOperationBindingReader,
    ) -> None:
        self._run_control = run_control
        self._bindings = bindings

    async def observe(
        self,
        request: GoalOperationReconciliationRequest,
        provider_result: OperationExecutionResult,
    ) -> GoalOperationSettlement:
        return await self._observe(request, provider_result)

    async def observe_terminal(
        self,
        request: GoalOperationReconciliationRequest,
        provider_result: OperationExecutionResult,
    ) -> GoalOperationSettlement:
        """RRM-008: consume the settlement of a `cancelled` or `failed` operation.

        The journaled operation boundary wrote it exactly as a completed one (usage, release,
        effect settlement, accepted evidence); the family verifies the same facts and never
        records usage for the unit itself. A unit whose effect is still pending (an async
        child's unattributed usage) is consumed too: the run's terminal settlement is what
        waits for the reconciliation, not the family's bookkeeping.
        """

        if provider_result.status not in {"cancelled", "failed"}:
            raise GoalOperationSettlementUnavailable(
                "terminal consumption requires a cancelled or failed operation result"
            )
        return await self._observe(request, provider_result)

    async def _observe(
        self,
        request: GoalOperationReconciliationRequest,
        provider_result: OperationExecutionResult,
    ) -> GoalOperationSettlement:
        operation = request.operation_request.operation
        scope = request.request_scope
        run_id = operation.identity.run_id
        binding_id = request.operation_binding_ref
        if provider_result.binding_id != binding_id or operation.request_scope != scope:
            raise GoalOperationSettlementUnavailable(
                "operation result does not belong to the admitted GoalDirected binding"
            )
        settlement_id = operation_settlement_id(binding_id)
        effect_claim_id = operation_effect_claim_id(scope, binding_id)
        reservation_id = operation.budget_reservation_id
        # Review fix 4 (required since the re-check): the binding and reservation the
        # settlement is read under are the stored binding's, the exact admitted intent.
        stored = await self._bindings.get_binding_by_id(binding_id, request_scope=scope)
        if (
            stored is None
            or stored != bind_operation_execution_request(operation)
            or stored.budget_reservation_id != reservation_id
        ):
            raise GoalOperationSettlementUnavailable(
                "operation binding is not the stored binding of the admitted operation"
            )
        # Settlement facts are monotonic: read them first and the run version last, so the
        # version the family continues from is at or after the settlement.
        budget = await self._run_control.get_budget(scope, run_id)
        effects = await self._run_control.get_effects(scope, run_id)
        run = await self._run_control.get_run(scope, run_id)
        usage = budget.usage_records.get(settlement_id)
        if (
            usage is None
            or usage.authority_ref != binding_id
            or usage.reservation_id != reservation_id
        ):
            raise GoalOperationSettlementUnavailable(
                "operation usage is not recorded once by its own run-control settlement"
            )
        if reservation_id in budget.reservations:
            raise GoalOperationSettlementUnavailable(
                "operation reservation is not authoritatively settled"
            )
        if (
            usage.actual_amounts != provider_result.usage.amounts
            or usage.pending_external_amounts != provider_result.usage.pending_external_amounts
        ):
            raise GoalOperationSettlementUnavailable(
                "settled operation usage differs from the operation result"
            )
        claim = effects.claims.get(effect_claim_id)
        if (
            claim is None
            or claim.operation_ref != binding_id
            or claim.reservation_id != reservation_id
        ):
            raise GoalOperationSettlementUnavailable(
                "operation has no journaled run-control effect claim"
            )
        pending_external = any(usage.pending_external_amounts.values())
        if not pending_external and (
            claim.settlement is None or claim.settlement.settlement_id != settlement_id
        ):
            raise GoalOperationSettlementUnavailable(
                "operation effect claim is not settled by its own settlement"
            )
        evidence = [
            item
            for item in run.accepted_operation_settlement_evidence
            if item.settlement_id == settlement_id
        ]
        if len(evidence) != 1 or evidence[0].accepted_by_authority_ref != binding_id:
            raise GoalOperationSettlementUnavailable(
                "operation settlement evidence is not accepted by run control"
            )
        if run.version < operation.run_control_revision:
            raise GoalOperationSettlementUnavailable(
                "run authority is older than the operation binding"
            )
        return GoalOperationSettlement(
            binding_id=binding_id,
            settlement_id=settlement_id,
            effect_claim_id=effect_claim_id,
            reservation_id=reservation_id,
            usage=dict(usage.actual_amounts),
            pending_external_usage=dict(usage.pending_external_amounts),
            settlement_payload_digest=evidence[0].settlement_payload_digest,
            settled_run_version=run.version,
        )


def configure_goal_directed_family_admissions(registry: FamilyAdmissionRegistry) -> None:
    """Register the one exact GoalDirected mutation shape on the frozen generic seam."""

    registry.register(
        GoalFamilyDecisionMutation,
        family_kind="goal_directed",
        mutation_kind="decision",
        required_permission="workflow_run.goal_directed",
        allowed_action_kinds=frozenset({"reserve_budget"}),
    )


class GoalDirectedOperationPreparationService:
    """Prepare and atomically admit one exact executor or verifier operation."""

    def __init__(
        self,
        *,
        templates: GoalOperationTemplateProvider,
        operation_bindings: SemanticOperationBindingRepository,
        run_control: RunControlService,
        documents: GoalDirectedDocumentRepository,
        actor: ActorContext,
        heartbeats: OperationHeartbeatPolicy = DEFAULT_OPERATION_HEARTBEATS,
        context_packs: ContextPackService | None = None,
        mailbox: MailboxDeliveryService | None = None,
        lane_bindings: LaneRebinders | None = None,
        linked_exports: LinkedExportPort | None = None,
    ) -> None:
        self._templates = templates
        self._linked_exports = linked_exports
        self._operation_bindings = operation_bindings
        self._run_control = run_control
        self._documents = documents
        self._actor = actor
        # OC-R2: the lanes' rebind port. The family names the template's sealed binding and
        # the live coordinates; the lane that sealed it reseals it (never read here).
        self._lane_bindings = lane_bindings or LaneRebinders()
        # RRM-009 (RRM-008 composition): heartbeat timeout per operation class.
        self._heartbeats = heartbeats
        # FT-B3 (ADR-0027): when composed, each iteration and role starts from a sealed
        # Context Packet instead of the stringified handoff.
        self._context_packs = context_packs
        # FT-F1: the iteration boundary delivers queued instructions and context into the
        # executor's packet (the verifier only takes entries that name `goal/verifier`).
        self._mailbox = mailbox

    async def prepare(self, request: GoalOperationPreparationRequest) -> GoalOperationDispatch:
        context = await resolve_goal_context(request, self._documents, self._operation_bindings)
        if request.operation_role == "executor":
            await self._documents.persist_revision(
                request.request_scope,
                request.run_id,
                request.goal_revision,
                request.decided_at,
            )
        template = await self._templates.get_template(
            semantic_input_binding_ref=request.semantic_input_binding_ref,
            operation_role=request.operation_role,
            request_scope=request.request_scope,
            run_id=request.run_id,
        )
        if template.output_schema is None or not template.output_schema.strict:
            raise ValueError("GoalDirected operation template requires strict structured output")
        # RRM-016: the operation binds the run version its own admission produces (an
        # accepted command advances the version by exactly one), as StageGraph does. The
        # journaled effect claim is made at exactly that revision (REQ-CP-EXEC-014).
        bound_revision = request.expected_run_version + 1
        sealed = None
        if self._context_packs is not None:
            role_root = goal_unit_workspace_root(
                _runtime_unit_for(
                    request,
                    OperationAttemptIdentity(
                        run_id=request.run_id,
                        operation_id=goal_operation_id(
                            request.goal_iteration, request.operation_role
                        ),
                        operation_attempt=request.operation_attempt,
                    ),
                )
            )
            assert role_root is not None  # a goal unit always has a role root
            queued: tuple[PackCandidate, ...] = ()
            if self._mailbox is not None:
                identity = OperationAttemptIdentity(
                    run_id=request.run_id,
                    operation_id=goal_operation_id(request.goal_iteration, request.operation_role),
                    operation_attempt=request.operation_attempt,
                )
                entries = await self._mailbox.deliver(
                    request.request_scope,
                    request.run_id,
                    # The bound operation's idempotency key: a re-admission or a retried
                    # preparation re-reads exactly the entries this attempt took.
                    delivery_key=(
                        f"goal:{identity.semantic_key}:generation:{request.execution_generation}"
                    ),
                    family="GoalDirected",
                    node_key=f"goal/{request.operation_role}",
                    iteration_start=request.operation_attempt == 1,
                    lane_profile=default_lane_profile(template),
                    unit_key=_runtime_unit_for(request, identity).unit_key,
                )
                queued = await self._context_packs.queued_candidates(
                    entries, request_scope=request.request_scope
                )
            sealed = await self._context_packs.pack_for_iteration(
                request,
                template,
                role_root=role_root,
                extra_candidates=(*queued, *context.candidates()),
            )
        operation = _instantiate_operation_request(
            template, request, bound_revision, sealed, self._lane_bindings, context=context
        )
        if request.operation_role == "executor":
            operation = await attach_linked_context(operation, self._linked_exports)
        binding = bind_operation_execution_request(operation)

        operation_request_digest = sha256_digest(operation)
        operation_ref = f"goal-operation:{operation_request_digest.removeprefix('sha256:')}"
        # 1.4.4 (TR-D7, P1.2): the admitted unit, and what released it.
        admitted_unit = _runtime_unit_for(
            request,
            OperationAttemptIdentity(
                run_id=request.run_id,
                operation_id=goal_operation_id(request.goal_iteration, request.operation_role),
                operation_attempt=request.operation_attempt,
            ),
        )
        mutation = GoalFamilyDecisionMutation(
            mutation_id=(
                f"{request.run_id}.goal.{request.goal_iteration}."
                f"{request.operation_role}.{request.operation_attempt}"
            ),
            request_scope=request.request_scope,
            run_id=request.run_id,
            expected_family_version=request.expected_family_version,
            exact_operation_request_ref=operation_ref,
            decided_at=request.decided_at,
            goal_revision_id=request.goal_revision_id,
            goal_revision_digest=request.goal_revision_digest,
            goal_iteration=request.goal_iteration,
            operation_role=request.operation_role,
            operation_request_digest=operation_request_digest,
            semantic_input_binding_ref=request.semantic_input_binding_ref,
            handoff_ref=request.handoff_ref,
            convergence_action="continue",
            released_by=goal_released_by(request),
        )
        command = LifecycleCommand(
            # RRM-016 review fix 2: a re-admission after a stale result is a new command (a
            # stale result is stored under its command identity).
            command_id=(
                f"goal-admission:{mutation.mutation_id}"
                if request.admission_attempt == 1
                else f"goal-admission:{mutation.mutation_id}:attempt:{request.admission_attempt}"
            ),
            idempotency_issuer="goal-directed-worker",
            request_scope=request.request_scope,
            run_id=request.run_id,
            expected_run_version=request.expected_run_version,
            actor=self._actor,
            action=ReserveBudgetAction(
                reservation_id=request.reservation_id,
                amounts=request.reservation,
            ),
            reason=f"Atomically admit GoalDirected {request.operation_role} operation",
            evidence_refs=(operation_ref, binding.binding_id),
            occurred_at=request.decided_at,
            correlation_id=(
                f"goal:{request.run_id}:iteration:{request.goal_iteration}:{request.operation_role}"
            ),
            causation_id=mutation.mutation_id,
            unit_key=admitted_unit.unit_key,
        )
        receipt = await self._run_control.execute_family_admission(command, mutation)
        if receipt.family_receipt is None:
            if receipt.command_result.status == CommandStatus.STALE:
                # A command outside the family moved the run between the family's read of
                # its version and this admission. Nothing was admitted or bound; the family
                # decides (re-admit once at the current version, or enter cancellation).
                raise GoalAdmissionStale(
                    current_run_version=receipt.command_result.resulting_run_version,
                    phase=receipt.command_result.phase.value,
                )
            raise ValueError("GoalDirected operation admission was not accepted")
        if receipt.command_result.resulting_run_version != bound_revision:
            raise ValueError(
                "GoalDirected operation admission did not produce the bound run revision"
            )
        # The binding is persisted only once its admission is accepted (review fix 2): a
        # stale admission leaves no binding behind, so the re-admission binds the same
        # semantic attempt at the new revision without an identity conflict.
        persisted = await self._operation_bindings.create_binding(
            binding,
            request_scope=request.request_scope,
        )
        if persisted != binding:
            raise ValueError("persisted GoalDirected operation binding differs from exact intent")
        workflow_request = OperationWorkflowRequest(
            semantic_attempt_id=operation.identity.semantic_key,
            execution_generation=request.execution_generation,
            operation_kind="bound_operation",
            operation=operation,
            heartbeat_timeout_seconds=self._heartbeats.timeout_for(operation),
            segments=self._heartbeats.segments_for(operation),
            capacity_wait=self._heartbeats.capacity_wait,
        )
        return GoalOperationDispatch(
            workflow_request=workflow_request,
            operation_binding_ref=persisted.binding_id,
            operation_request_digest=operation_request_digest,
            resulting_run_version=receipt.command_result.resulting_run_version,
            resulting_family_version=receipt.family_receipt.family_version,
        )


class GoalDirectedOperationResultService:
    """Validate provider output against exact operation intent and persist immutable detail."""

    def __init__(
        self,
        documents: GoalDirectedDocumentRepository,
        settlements: GoalOperationSettlementPort | None = None,
        artifacts: ArtifactBytesPort | None = None,
        run_control: RunControlService | None = None,
        completions: CompletionRecordPort | None = None,
        fulfillment: GoalFulfillmentConvergence | None = None,
    ) -> None:
        # W1: explicit fulfillment at the convergence boundary (None: not composed).
        self._fulfillment = fulfillment
        self._documents = documents
        self._settlements = settlements
        self._artifacts = artifacts
        self._run_control = run_control
        self._completions = completions
        self._execution_adapter = TypeAdapter(GoalNamedExecutorObservation)
        self._verification_adapter = TypeAdapter(GoalVerifierObservation)

    def _parsed(
        self,
        adapter: TypeAdapter[Any],
        provider_result: OperationExecutionResult,
        required_output_contract_refs: tuple[str, ...],
    ) -> tuple[Any | None, str]:
        """The role's typed observation, or None and an `output_unparseable` reference (F-T3-1).

        A completed provider turn whose payload is missing or does not validate is a model
        answer, not a reconciliation fault: replaying the activity cannot repair it. The
        reference names the reason and the digest of the error, the payload and the text.
        Tracing Stage 3 (R1-F6): so is a schema-valid answer naming an output contract
        outside the frozen required ones; it used to raise `ValueError` (retried on the
        executor until the family workflow failed, `goal_completion_invalid` on the
        verifier), leaving the run `running`.
        """

        payload = provider_result.structured_output
        if payload is not None:
            try:
                parsed = adapter.validate_python(payload)
            except ValidationError as error:
                detail = [
                    {"type": item["type"], "loc": list(item["loc"]), "msg": item["msg"]}
                    for item in error.errors(include_url=False)
                ]
            else:
                if parsed.output_contract_ref in required_output_contract_refs:
                    return parsed, ""
                detail = [
                    {
                        "type": "output_contract_ref",
                        "loc": ["output_contract_ref"],
                        "msg": "outside the frozen required output contracts",
                    }
                ]
        else:
            detail = [{"type": "missing", "loc": [], "msg": "no structured payload"}]
        evidence = sha256_digest(
            {"error": detail, "payload": payload, "output_text": provider_result.output_text}
        )
        return None, f"{OUTPUT_UNPARSEABLE}:{evidence}"

    def _executor_observation(
        self,
        provider_result: OperationExecutionResult,
        request: GoalOperationReconciliationRequest,
    ) -> GoalNamedExecutorObservation:
        """F-T3-1: a non-parsing executor payload settles as `disposition: failed` with the
        `output_unparseable` reference; the settlement already observed stands, the verifier
        sees the failure and the convergence policy stops on the irrecoverable fact."""

        parsed, failure = self._parsed(
            self._execution_adapter, provider_result, request.required_output_contract_refs
        )
        if parsed is not None:
            return cast(GoalNamedExecutorObservation, parsed)
        return GoalNamedExecutorObservation(
            disposition="failed",
            irrecoverable_failure_ref=failure,
            output_contract_ref=request.required_output_contract_refs[0],
        )

    def _verifier_observation(
        self,
        provider_result: OperationExecutionResult,
        request: GoalOperationReconciliationRequest,
    ) -> GoalVerifierObservation:
        """Tracing Stage 2 (F-S2-2): the verifier's non-parsing payload settles the same way, as
        a `rejected` observation with no progress and the `output_unparseable` reference, so
        the convergence policy terminates the run instead of the family workflow failing on
        an exhausted activity with the run left active."""

        parsed, failure = self._parsed(
            self._verification_adapter, provider_result, request.required_output_contract_refs
        )
        if parsed is not None:
            return cast(GoalVerifierObservation, parsed)
        return GoalVerifierObservation(
            decision="rejected",
            progress_made=False,
            irrecoverable_failure_ref=failure,
            output_contract_ref=request.required_output_contract_refs[0],
        )

    async def reconcile_nested_executor(
        self, request: GoalOperationReconciliationRequest
    ) -> GoalOperationReconciliationResult:
        """OVE-176: the executor phase ran a nested family body as its own child run.

        Its observation is the body's export receipt: the exported refs are the iteration's
        outputs only when the composite was accepted; a governed non-acceptance is a failed
        execution result the convergence policy decides on. The unit's reservation was settled
        by the nested settlement against the child's actual usage; that settlement is what the
        family consumes (never an operation boundary that did not run).
        """

        if request.operation_role != "executor":
            raise ValueError("a nested body replaces the executor phase only")
        observed = request.operation_result
        receipt = observed.result.get("nested")
        settled = observed.result.get("nested_settlement")
        if not isinstance(receipt, dict) or not isinstance(settled, dict):
            raise ValueError("nested executor result carries no export receipt or settlement")
        if settled.get("reservation_id") != request.claim.reservation_id:
            raise ValueError("nested settlement is not the claimed iteration's reservation")
        usage = {str(key): int(value) for key, value in dict(settled.get("usage") or {}).items()}
        digest = str(receipt.get("receipt_digest", ""))
        settlement = GoalOperationSettlement(
            binding_id=request.operation_binding_ref,
            settlement_id=f"nested-usage:{request.claim.reservation_id}",
            effect_claim_id=f"nested-run:{receipt.get('child_run_id') or 'unstarted'}",
            reservation_id=request.claim.reservation_id,
            usage=usage,
            settlement_payload_digest=digest,
            settled_run_version=max(int(settled.get("settled_run_version") or 0), 1),
        )
        if observed.disposition != "completed":
            return GoalOperationReconciliationResult(
                operation_role="executor",
                detail_ref=f"nested-receipt:{digest}",
                settlement=settlement,
                operation_disposition=(
                    "cancelled" if observed.disposition == "cancelled" else "failed"
                ),
            )
        accepted = bool(receipt.get("composite_accepted"))
        operation = request.operation_request.operation
        exported = observed.result.get("output_refs")
        refs = tuple(str(item) for item in exported) if isinstance(exported, list | tuple) else ()
        result = GoalExecutionResult(
            identity=request.claim.identity,
            disposition="completed" if accepted else "failed",
            operation_identity=operation.identity.semantic_key,
            operation_binding_ref=request.operation_binding_ref,
            # The body ran in its own child run: the iteration keeps the claim's session and
            # workspace identity (no agent session of this run executed it).
            session_id=request.claim.session_id,
            workspace_id=request.claim.workspace_namespace,
            writable_paths=operation.workspace.exclusive_write_paths,
            output_refs=refs if accepted else (),
            completion_claim=accepted,
            actual_usage=usage,
            blocker_class="" if accepted else "nested_body_not_accepted",
            evidence_refs=(f"nested-receipt:{digest}",),
            output_contract_ref=request.required_output_contract_refs[0],
        )
        detail_ref = await self._documents.persist_iteration(
            request.request_scope, result, request.goal_revision_id, request.recorded_at
        )
        return GoalOperationReconciliationResult(
            operation_role="executor",
            execution_result=result,
            detail_ref=detail_ref,
            settlement=settlement,
        )

    async def reconcile(
        self, request: GoalOperationReconciliationRequest
    ) -> GoalOperationReconciliationResult:
        operation = request.operation_request.operation
        if operation.output_schema is None or not operation.output_schema.strict:
            raise ValueError(
                "GoalDirected operation requires an exact strict structured-output binding"
            )
        observed = request.operation_result
        if (
            observed.semantic_attempt_id != request.operation_request.semantic_attempt_id
            or observed.execution_generation != request.operation_request.execution_generation
            or observed.result is None
        ):
            raise ValueError("GoalDirected operation result does not match its durable request")
        if observed.disposition in {"cancelled", "failed"}:
            # RRM-008: a cancelled or failed unit is consumed through its own settlement path;
            # no family document is persisted and `_consume_settlement` is never reached.
            if self._settlements is None:
                raise ValueError(
                    "a cancelled or failed GoalDirected operation requires the settlement port"
                )
            terminal_result = OperationExecutionResult.model_validate(observed.result)
            if (
                terminal_result.status != observed.disposition
                or terminal_result.binding_id != request.operation_binding_ref
            ):
                raise ValueError(
                    "GoalDirected terminal operation result is not the exact bound settlement"
                )
            terminal_settlement = await self._settlements.observe_terminal(request, terminal_result)
            undelivered = (
                _undelivered_verification(terminal_result, request)
                if observed.disposition == "failed" and request.operation_role == "verifier"
                else None
            )
            if observed.disposition == "failed" and request.operation_role == "executor":
                # W1 D40: a failed executor unit is a typed failed execution the verifier and
                # the convergence policy see, instead of the family failing untyped.
                return await self._reconcile_failed_execution(
                    request, terminal_result, terminal_settlement
                )
            if undelivered is not None:
                # W1 D14: a verifier that failed (its required subject was never delivered,
                # or it failed outright) is a typed rejection with the unmet obligations and
                # an irrecoverable failure, recorded like any verification, so the
                # convergence policy terminates the run visibly instead of the family
                # workflow failing on a missing typed result with the run left active.
                return await self._reconcile_verification(
                    request,
                    observed,
                    undelivered,
                    dict(terminal_result.usage.amounts),
                    terminal_settlement,
                    operation_disposition="failed",
                )
            return GoalOperationReconciliationResult(
                operation_role=request.operation_role,
                detail_ref=f"goal-operation:{observed.disposition}:{request.operation_binding_ref}",
                settlement=terminal_settlement,
                operation_disposition=observed.disposition,
            )
        if observed.disposition != "completed":
            raise ValueError("GoalDirected operation result does not match its durable request")
        provider_result = OperationExecutionResult.model_validate(observed.result)
        # F-T3-1: a turn that answered without a structured payload is not a mismatch; it
        # settles as a typed `output_unparseable` observation below.
        if (
            provider_result.status != "completed"
            or provider_result.binding_id != request.operation_binding_ref
            or provider_result.semantic_attempt_key != request.operation_request.semantic_attempt_id
        ):
            mismatches = []
            if provider_result.status != "completed":
                mismatches.append(f"status={provider_result.status!r}")
            if provider_result.binding_id != request.operation_binding_ref:
                mismatches.append("binding_id")
            if (
                provider_result.semantic_attempt_key
                != request.operation_request.semantic_attempt_id
            ):
                mismatches.append("semantic_attempt_key")
            raise ValueError(
                "GoalDirected provider result is not the exact completed structured operation: "
                + ", ".join(mismatches)
            )
        # RRM-016: the accepted run-control settlement is verified before any family document
        # is persisted. A composition without one returns no settlement, and the family
        # fails closed on it (no ungoverned usage recording).
        settlement = (
            await self._settlements.observe(request, provider_result)
            if self._settlements is not None
            else None
        )
        observed_usage = dict(provider_result.usage.amounts)
        if request.operation_role == "executor":
            parsed = self._executor_observation(provider_result, request)
            if parsed.output_contract_ref not in request.required_output_contract_refs:
                raise ValueError("executor result is outside the frozen required output contracts")
            handoff = (
                _bind_handoff(
                    parsed.handoff,
                    claim=request.claim,
                    operation_identity=operation.identity.semantic_key,
                    actual_usage=observed_usage,
                    remaining_iterations=request.remaining_iterations,
                    protected_fact_classes=request.protected_fact_classes,
                    context_selection_policy_ref=request.context_selection_policy_ref or "",
                    context_compaction_policy_ref=request.context_compaction_policy_ref or "",
                    workspace_ref_class=request.workspace_ref_class or "",
                    context_packet=context_packet_ref(operation.prompt_segments),
                )
                if parsed.handoff is not None
                else None
            )
            if (
                handoff is not None
                and handoff.compaction_status == "failed"
                and request.compaction_failure_action
                in {
                    "retry",
                    "fresh_from_handoff",
                }
            ):
                handoff = _recover_handoff_compaction(
                    handoff,
                    action=(
                        "retry"
                        if request.compaction_failure_action == "retry"
                        else "fresh_from_handoff"
                    ),
                )
            result = GoalExecutionResult(
                identity=request.claim.identity,
                disposition=parsed.disposition,
                operation_identity=operation.identity.semantic_key,
                operation_binding_ref=request.operation_binding_ref,
                session_id=operation.session_id or "",
                workspace_id=operation.workspace.workspace_id,
                writable_paths=operation.workspace.exclusive_write_paths,
                output_refs=parsed.output_refs,
                output_bindings=parsed.output_bindings,
                completion_claim=parsed.completion_claim,
                actual_usage=observed_usage,
                blocker_class=parsed.blocker_class,
                authority_breach_ref=parsed.authority_breach_ref,
                hard_budget_exhausted_dimensions=(parsed.hard_budget_exhausted_dimensions),
                irrecoverable_failure_ref=parsed.irrecoverable_failure_ref,
                accepted_fact_refs=parsed.accepted_fact_refs,
                evidence_refs=parsed.evidence_refs,
                effect_frontier_refs=tuple(
                    dict.fromkeys((*parsed.effect_frontier_refs, *observed.effect_frontier))
                ),
                pending_liability_refs=tuple(
                    dict.fromkeys(
                        (
                            *parsed.pending_liability_refs,
                            *(
                                f"async-child:{child_id}"
                                for child_id in observed.active_async_child_ids
                            ),
                        )
                    )
                ),
                handoff=handoff,
                output_contract_ref=parsed.output_contract_ref,
            )
            detail_ref = await self._documents.persist_iteration(
                request.request_scope,
                result,
                request.goal_revision_id,
                request.recorded_at,
            )
            if result.handoff is not None:
                await self._documents.persist_handoff(
                    request.request_scope,
                    result.handoff,
                    request.recorded_at,
                )
            return GoalOperationReconciliationResult(
                operation_role="executor",
                execution_result=result,
                detail_ref=detail_ref,
                settlement=settlement,
            )

        return await self._reconcile_verification(
            request,
            observed,
            self._verifier_observation(provider_result, request),
            observed_usage,
            settlement,
        )

    async def _reconcile_failed_execution(
        self,
        request: GoalOperationReconciliationRequest,
        terminal_result: OperationExecutionResult,
        settlement: GoalOperationSettlement,
    ) -> GoalOperationReconciliationResult:
        """W1 D40: the recorded failed execution of an executor unit that settled `failed`.

        It names only the boundary's failure code, never provider text, and carries the unit's
        settled usage (the family consumes that settlement, as for any executor). A
        `transient_transport` failure (the call never reached the provider and its bounded
        in-turn retry was exhausted) is recoverable: a later iteration may succeed, within the
        policy's iteration and repeated-blocker bounds. Any other code is irrecoverable, so the
        convergence policy terminates the run visibly after the verifier has seen it.
        """

        operation = request.operation_request.operation
        code = terminal_result.failure_code or "runtime_failed"
        result = GoalExecutionResult(
            identity=request.claim.identity,
            disposition="failed",
            operation_identity=operation.identity.semantic_key,
            operation_binding_ref=request.operation_binding_ref,
            session_id=operation.session_id or "",
            workspace_id=operation.workspace.workspace_id,
            writable_paths=operation.workspace.exclusive_write_paths,
            completion_claim=False,
            actual_usage=dict(settlement.usage),
            blocker_class=code,
            irrecoverable_failure_ref=(
                "" if code in RECOVERABLE_EXECUTOR_FAILURES else f"executor_unit_failed:{code}"
            )[:MAX_UNDELIVERED_REF_CHARS],
            output_contract_ref=request.required_output_contract_refs[0],
        )
        detail_ref = await self._documents.persist_iteration(
            request.request_scope, result, request.goal_revision_id, request.recorded_at
        )
        return GoalOperationReconciliationResult(
            operation_role="executor",
            execution_result=result,
            detail_ref=detail_ref,
            settlement=settlement,
            operation_disposition="failed",
        )

    async def _reconcile_verification(
        self,
        request: GoalOperationReconciliationRequest,
        observed: OperationWorkflowResult,
        observation: GoalVerifierObservation,
        observed_usage: dict[str, int],
        settlement: GoalOperationSettlement | None,
        *,
        operation_disposition: Literal["completed", "failed"] = "completed",
    ) -> GoalOperationReconciliationResult:
        """Bind one verifier observation to its frozen authority, persist and record it.

        A failed verifier unit (W1 D14) carries no completion validation of its own: the
        verifier never judged the executor's outputs, so its rejection stands as observed.
        """

        operation = request.operation_request.operation
        if observation.output_contract_ref not in request.required_output_contract_refs:
            raise ValueError("verifier result is outside the frozen required output contracts")
        executor_result = request.executor_result
        if executor_result is None:
            raise ValueError("verifier reconciliation omitted the admitted executor result")
        policy_binding_ref = request.verifier_policy_binding_ref
        rubric_ref = request.verifier_rubric_ref
        rubric_version = request.verifier_rubric_version
        acceptance_contract_ref = request.acceptance_contract_ref
        acceptance_version = request.acceptance_version
        if (
            policy_binding_ref is None
            or rubric_ref is None
            or rubric_version is None
            or acceptance_contract_ref is None
            or acceptance_version is None
        ):
            raise ValueError("verifier reconciliation omitted frozen policy authority")
        verification_identity = sha256_digest(
            {
                "executor_identity": request.claim.identity.semantic_key,
                "verifier_operation_identity": operation.identity.semantic_key,
                "operation_result": observed.model_dump(mode="json"),
            }
        )
        verification_id = "goal-verification:" + verification_identity.removeprefix("sha256:")
        validation = None
        blueprint = request.completion_blueprint if operation_disposition == "completed" else None
        request_digest = sha256_digest(request.model_dump(mode="python"))
        if blueprint is not None:
            cached = await self._documents.load_verification(
                request.request_scope, request.claim.identity.iteration.run_id, verification_id
            )
            if cached is not None:
                if cached.get("request_digest") != request_digest:
                    raise ValueError("GoalDirected validation replay differs from frozen request")
                saved = TypeAdapter(GoalVerificationResult).validate_python(cached["verification"])
                saved_validation = CompletionValidation.model_validate(
                    cached["completion_validation"]
                )
                await self._record_completion(request, saved, saved_validation)
                return GoalOperationReconciliationResult(
                    operation_role="verifier",
                    verification_result=saved,
                    detail_ref=f"goal-verification:{saved.verification_id}@{sha256_digest(document_payload(saved))}",
                    settlement=settlement,
                    completion_validation=saved_validation,
                )
            validation = await validate_completion(
                self._artifacts,
                request_scope=request.request_scope,
                stage=blueprint,
                interpreter=None,
                operation_result={
                    "output_refs": list(executor_result.output_refs),
                    **(
                        {"output_bindings": executor_result.output_bindings}
                        if executor_result.output_bindings is not None
                        else {}
                    ),
                },
            )
            if validation.status == "pending":
                run = (
                    await self._run_control.get_run(
                        request.request_scope, request.claim.identity.iteration.run_id
                    )
                    if self._run_control is not None
                    else None
                )
                if (
                    run is None or run.phase.value not in {"cancelling", "terminal"}
                ) and datetime.now(UTC) < request.recorded_at + timedelta(minutes=15):
                    raise ArtifactPublicationPending("declared goal output is not published yet")
                validation = expire_pending(
                    validation,
                    reason=(
                        "run_cancelled_during_publication"
                        if run is not None and run.phase.value in {"cancelling", "terminal"}
                        else "artifact_publication_deadline_exceeded"
                    ),
                )
            accepted = validated_result(
                {"obligation_refs": observation.accepted_obligation_refs}, validation
            )["obligation_refs"]
            unmet = set(observation.unmet_obligations)
            unmet.update(
                item.obligation_ref
                for item in validation.criteria
                if item.obligation_ref and item.status != "satisfied"
            )
            observation = observation.model_copy(
                update={
                    "decision": observation.decision
                    if validation.status == "satisfied"
                    else "rejected",
                    "accepted_obligation_refs": tuple(accepted)
                    if validation.status == "satisfied"
                    else (),
                    "unmet_obligations": tuple(sorted(unmet)),
                    "evidence_refs": (
                        *observation.evidence_refs,
                        "completion-validation:" + sha256_digest(validation),
                    ),
                }
            )
        observation = await self._with_fulfillment(request, observation)
        verification_result = GoalVerificationResult(
            schema_version="belllabs.goal-verification.v1",
            verification_id=verification_id,
            verification_digest="pending",
            executor_identity=request.claim.identity,
            verifier_operation_identity=operation.identity.semantic_key,
            verifier_binding_ref=request.operation_binding_ref,
            verifier_policy_binding_ref=policy_binding_ref,
            verifier_session_id=operation.session_id or "",
            verifier_workspace_id=operation.workspace.workspace_id,
            verifier_writable_paths=operation.workspace.exclusive_write_paths,
            rubric_ref=rubric_ref,
            rubric_version=rubric_version,
            acceptance_contract_ref=acceptance_contract_ref,
            acceptance_version=acceptance_version,
            decision=observation.decision,
            progress_made=observation.progress_made,
            accepted_obligation_refs=observation.accepted_obligation_refs,
            findings=observation.findings,
            evidence_refs=observation.evidence_refs,
            admitted_executor_output_refs=executor_result.output_refs,
            admitted_executor_evidence_refs=executor_result.evidence_refs,
            unmet_obligations=observation.unmet_obligations,
            obligation_applicability=observation.obligation_applicability,
            verification_ref=f"{verification_id}@{verification_identity}",
            stale_frontier_digest=sha256_digest(executor_result.frontier_payload()),
            blocker_class=observation.blocker_class,
            authority_breach_ref=observation.authority_breach_ref,
            hard_budget_exhausted_dimensions=(observation.hard_budget_exhausted_dimensions),
            soft_budget_dimensions=observation.soft_budget_dimensions,
            irrecoverable_failure_ref=observation.irrecoverable_failure_ref,
            proposed_revision=observation.proposed_revision,
            scope_expansion_route=observation.scope_expansion_route,
            route_ref=observation.route_ref,
            actual_usage=observed_usage,
            effect_refs=tuple(
                dict.fromkeys(
                    (
                        *observation.effect_refs,
                        *observed.effect_frontier,
                        *(
                            f"async-child:{child_id}"
                            for child_id in observed.active_async_child_ids
                        ),
                    )
                )
            ),
            output_contract_ref=observation.output_contract_ref,
        )
        verification_payload = asdict(verification_result)
        verification_payload.pop("verification_digest")
        verification_result = replace(
            verification_result,
            verification_digest=sha256_digest(verification_payload),
        )
        if validation is not None:
            detail_ref = await self._documents.persist_verification(
                request.request_scope,
                request.claim.identity.iteration.run_id,
                request.goal_revision_id,
                verification_result,
                request.recorded_at,
                completion_validation=validation,
                request_digest=request_digest,
            )
        else:
            detail_ref = await self._documents.persist_verification(
                request.request_scope,
                request.claim.identity.iteration.run_id,
                request.goal_revision_id,
                verification_result,
                request.recorded_at,
            )
        await self._record_completion(request, verification_result, validation)
        return GoalOperationReconciliationResult(
            operation_role="verifier",
            verification_result=verification_result,
            detail_ref=detail_ref,
            settlement=settlement,
            completion_validation=validation,
            operation_disposition=operation_disposition,
        )

    async def _with_fulfillment(
        self, request: GoalOperationReconciliationRequest, observation: GoalVerifierObservation
    ) -> GoalVerifierObservation:
        """W1: decide the run's declared promises at this boundary and bind the verdict to them.

        The verifier's acceptance stands only when every required promise is fulfilled; a
        required promise that is missing, waiting or blocked turns it into a rejection with the
        promise named as unmet (`output:<key>`). An expected shortfall is a visible finding and
        never blocks; an optional absence adds nothing. The pinned set is cited as evidence.
        """

        if self._fulfillment is None:
            return observation
        identity = request.claim.identity
        frontier = await self._fulfillment.converge(
            HostAccess(
                scope=request.request_scope,
                actor_ref=GOAL_FULFILLMENT_ACTOR,
                origin_ref="mc-host:goal-convergence",
            ),
            identity.iteration.run_id,
            operation_ref=goal_operation_id(identity.iteration.goal_iteration, "executor"),
            generation=request.operation_request.execution_generation,
            # Only an accepted iteration's output may become an accepted head (W1 review S1).
            promote=observation.decision == "accepted",
        )
        if frontier is None:
            return observation
        return bind_fulfillment(observation, frontier)

    async def _record_completion(
        self,
        request: GoalOperationReconciliationRequest,
        verification: GoalVerificationResult,
        validation: CompletionValidation | None,
    ) -> None:
        """1.4.4 (P3.8): the verifier's decision and the executor's candidate in the decision
        table. Written after the verification document, on the replayed path too: the
        port is idempotent by key, so a retry between the two writes converges."""

        if self._completions is None:
            return
        await self._completions.record(
            request.request_scope,
            request.claim.identity.iteration.run_id,
            goal_completion_records(request, verification, validation),
            actor_ref="goal-directed-worker",
            recorded_at=request.recorded_at,
        )


def _iteration_transfer(
    template: OperationExecutionRequest,
    request: GoalOperationPreparationRequest,
    *,
    subject_attempt: ProducerAttempt | None = None,
    repair: bool = False,
) -> TransferSelection | None:
    """WI-02: the first executor iteration invents no predecessor; a later one receives the
    admitted predecessor outputs; the verifier keeps its nominated-subject selection. WI-07: both
    a later executor and the verifier also receive the goal's exact current-set index as a file
    (OUTPUT-CONTRACTS §7), never inline."""

    selection = template.transfer
    if selection is None:
        return None
    if request.operation_role == "verifier":
        # The subject is this iteration's executor, never another iteration's submission, beside
        # every accepted head of the goal (WI-07: the verifier assesses the whole current set)
        # and the exact current-set index file.
        if subject_attempt is not None:
            selection = transfer_builders.authorized_subjects(selection, subject_attempt)
        return with_current_set_index(
            transfer_builders.for_producer(
                selection, goal_operation_id(request.goal_iteration, "executor")
            ),
            purpose="evaluation_subject",
        )
    if request.goal_iteration == 1:
        return transfer_builders.first_invocation(
            selection.receiver_position, selection.bounds, selection.backend
        )
    if subject_attempt is not None and repair:
        selection = transfer_builders.authorized_subjects(selection, subject_attempt, repair=True)
    return with_current_set_index(
        transfer_builders.for_producer(
            selection, goal_operation_id(request.goal_iteration - 1, "executor")
        ),
        purpose="current_set",
    )


def _instantiate_operation_request(
    template: OperationExecutionRequest,
    request: GoalOperationPreparationRequest,
    bound_revision: int,
    sealed: SealedPacket | None = None,
    lane_bindings: LaneRebinders | None = None,
    *,
    context: GoalContext | None = None,
) -> OperationExecutionRequest:
    context = context or GoalContext()
    operation_id = goal_operation_id(request.goal_iteration, request.operation_role)
    identity = OperationAttemptIdentity(
        run_id=request.run_id,
        operation_id=operation_id,
        operation_attempt=request.operation_attempt,
    )
    runtime_unit = _runtime_unit_for(request, identity)
    workspace = _workspace_for(
        template.workspace,
        request,
        runtime_unit,
        context_slots=sealed.slot_bindings if sealed is not None else (),
    )
    prompt_segments = (
        (*template.prompt_segments, sealed.prompt_segment)
        if sealed is not None
        else _prompt_segments(template.prompt_segments, request)
    ) + _review_feedback_segments(request)
    if sealed is None and context.feedback is not None:
        prompt_segments = (*prompt_segments, context.feedback)
    lane_binding, lane_dispatch = _lane_binding_for(
        template,
        lane_bindings or LaneRebinders(),
        request=request,
        identity=identity,
        workspace=workspace,
        runtime_unit=runtime_unit,
        bound_revision=bound_revision,
    )
    payload = template.model_dump(mode="python")
    payload.update(
        {
            "identity": identity,
            "transfer": _iteration_transfer(
                template,
                request,
                subject_attempt=context.subject,
                repair=request.verification_feedback is not None,
            ),
            "request_scope": request.request_scope,
            "effective_configuration_digest": request.effective_configuration_digest,
            "run_control_revision": bound_revision,
            "prompt_segments": prompt_segments,
            "session_id": request.session_id,
            "workspace": workspace,
            "lane_binding": lane_binding,
            "lane_dispatch": lane_dispatch,
            "budget_reservation_id": request.reservation_id,
            "budget_limits": request.reservation,
            "prior_binding_id": None,
            "requested_at": request.decided_at,
            "idempotency_key": (
                f"goal:{identity.semantic_key}:generation:{request.execution_generation}"
            ),
            "runtime_unit": runtime_unit,
        }
    )
    return OperationExecutionRequest.model_validate(payload)


def _runtime_unit_for(
    request: GoalOperationPreparationRequest,
    identity: OperationAttemptIdentity,
) -> RuntimeUnitIdentity:
    """REQ-CP-EXEC-013: iteration, revision, role, agent run, and session generation."""

    if request.agent_run is None or request.session_generation is None:
        raise ValueError(
            "GoalDirected operation preparation requires its agent run and session generation"
        )
    return goal_runtime_unit(
        request_scope=request.request_scope,
        run_id=request.run_id,
        execution_epoch=request.execution_epoch,
        operation_id=identity.operation_id,
        operation_attempt=identity.operation_attempt,
        goal_iteration=request.goal_iteration,
        goal_revision_id=request.goal_revision_id,
        operation_role=request.operation_role,
        agent_run=request.agent_run,
        session_generation=request.session_generation,
    )


GOAL_FULFILLMENT_ACTOR = "goal-directed-worker"


def bind_fulfillment(
    observation: GoalVerifierObservation, frontier: FulfillmentResult
) -> GoalVerifierObservation:
    """The verifier observation with the run's recorded fulfillment applied (W1)."""

    unmet = tuple(f"output:{key}" for key in (*frontier.blocking, *frontier.waiting_on))
    satisfied = frontier.completion == "satisfied"
    return observation.model_copy(
        update={
            "decision": observation.decision
            if satisfied or observation.decision != "accepted"
            else "rejected",
            "accepted_obligation_refs": observation.accepted_obligation_refs if satisfied else (),
            "unmet_obligations": tuple(dict.fromkeys((*observation.unmet_obligations, *unmet))),
            "findings": (
                *observation.findings,
                *(f"expected output shortfall: {key}" for key in frontier.shortfalls),
            ),
            "evidence_refs": (
                *observation.evidence_refs,
                f"output-fulfillment:{frontier.set_id}@{frontier.membership_digest}",
            ),
        }
    )


# W1 D14: the longest irrecoverable-failure reference an undelivered verification records.
MAX_UNDELIVERED_REF_CHARS = 1_024
# W1 review S2: the verifier failures a retry can never repair. The journaled boundary settles a
# failed unit once (`operation_execution.py`, the `OperationSettlement(status="failed")` of the
# governed boundary), so there is no retry below this point; a transient code (`runtime_failed`,
# `preparation_failed`, `budget_exceeded`) keeps the family's typed failure instead, which the
# root terminalizes (D15) without pretending the verifier judged anything.
DETERMINISTIC_VERIFIER_FAILURES = frozenset(
    {"context_delivery_blocked", "unsupported_runtime_policy"}
)
# Every other failure code the operation boundary records: not a judgment about the outputs, so
# the family keeps its typed failure. A new code must be classified in one of the two sets
# (`tests/unit/orchestration/test_w1_goal_failure_paths.py` enumerates the boundary's codes).
NON_JUDGED_VERIFIER_FAILURES = frozenset(
    {
        "budget_exceeded",
        "cancelled",
        "fork_lineage_missing",
        "generation_superseded",
        "in_doubt_abandoned",
        "incompatible_restore",
        "lane_not_qualified",
        "preparation_failed",
        "runtime_failed",
        "saved_result_too_large",
        # W1 D40: a verifier whose call never reached the provider judged nothing either.
        "transient_transport",
    }
)
# W1 D40: the executor failure codes a later iteration may repair (the unit's own bounded
# in-turn retry was exhausted); every other failed executor unit is irrecoverable.
RECOVERABLE_EXECUTOR_FAILURES = frozenset({"transient_transport"})


def _undelivered_verification(
    result: OperationExecutionResult, request: GoalOperationReconciliationRequest
) -> GoalVerifierObservation | None:
    """The typed rejection of a verifier unit that failed deterministically (W1 D14,
    OUTPUT-CONTRACTS: required absence blocks), or None.

    A `context_delivery_blocked` failure names its host-generated reason (typed codes and exact
    binding keys, e.g. `SOURCE_NOT_ACCEPTED:subject-root-report`); any other failure names only
    its code, never provider text. The unmet obligations are the blueprint's required ones
    (none are invented without a blueprint); the output contract is the one the admitted
    executor answered under, or the only required one, never an arbitrary pick."""

    code = result.failure_code or ""
    if code not in DETERMINISTIC_VERIFIER_FAILURES:
        return None
    contracts = request.required_output_contract_refs
    executor = request.executor_result
    if executor is not None and executor.output_contract_ref in contracts:
        contract = executor.output_contract_ref
    elif len(contracts) == 1:
        contract = contracts[0]
    else:
        return None
    blocked = code == "context_delivery_blocked" and bool(result.failure_message)
    reason = (result.failure_message or code) if blocked else code
    blueprint = request.completion_blueprint
    unmet = blueprint.required_obligation_refs if blueprint is not None else frozenset()
    return GoalVerifierObservation(
        decision="rejected",
        progress_made=False,
        findings=(
            f"required verifier input was not delivered: {reason}"
            if blocked
            else f"verifier operation failed: {code}",
        ),
        unmet_obligations=tuple(sorted(unmet)),
        blocker_class=code,
        irrecoverable_failure_ref=f"verifier_unit_failed:{reason}"[:MAX_UNDELIVERED_REF_CHARS],
        output_contract_ref=contract,
    )


def _bind_handoff(
    handoff: GoalHandoffDraft,
    *,
    claim: GoalExecutionClaim,
    operation_identity: str,
    actual_usage: dict[str, int],
    remaining_iterations: int,
    protected_fact_classes: tuple[str, ...],
    context_selection_policy_ref: str,
    context_compaction_policy_ref: str,
    workspace_ref_class: str,
    context_packet: str | None = None,
) -> GoalHandoff:
    provider_content = handoff.model_dump(mode="python")
    if context_packet is not None:
        # FT-B3: the packet the iteration consumed leads the selection refs (authority);
        # model-authored refs follow as data. `goal_handoff_reference` reads it back.
        provider_content["context_selection_refs"] = tuple(
            dict.fromkeys((context_packet, *handoff.context_selection_refs))
        )
    identity_digest = sha256_digest(
        {
            "agent_run_identity": claim.identity.semantic_key,
            "operation_identity": operation_identity,
            "content": provider_content,
        }
    )
    provider_content.pop("schema_version")
    bound = GoalHandoff(
        schema_version="belllabs.goal-handoff.v1",
        handoff_id=f"goal-handoff:{identity_digest.removeprefix('sha256:')}",
        handoff_digest="pending",
        run_id=claim.identity.iteration.run_id,
        execution_epoch=claim.identity.iteration.execution_epoch,
        goal_revision_id=claim.identity.iteration.goal_revision_id,
        source_iteration=claim.identity.iteration,
        consumed_budget=actual_usage,
        reserved_budget=claim.reservation,
        remaining_budget={
            dimension: max(limit - actual_usage.get(dimension, 0), 0)
            for dimension, limit in claim.reservation.items()
        },
        remaining_iterations=remaining_iterations,
        protected_context_facts=tuple(
            (fact_class, _protected_context_value(fact_class, claim))
            for fact_class in protected_fact_classes
        ),
        context_selection_policy_ref=context_selection_policy_ref,
        context_compaction_policy_ref=context_compaction_policy_ref,
        workspace_refs=(f"{workspace_ref_class}:{claim.workspace_namespace}",),
        snapshot_refs=(),
        source_document_digests=(claim.goal_revision_digest,),
        source_binding_digests=(sha256_digest(operation_identity),),
        **provider_content,
    )
    digest_payload = asdict(bound)
    digest_payload.pop("handoff_digest")
    return replace(bound, handoff_digest=sha256_digest(digest_payload))


def _protected_context_value(fact_class: str, claim: GoalExecutionClaim) -> str:
    values = {
        "objective": claim.objective,
        "envelope_digest": claim.envelope_digest,
        "goal_revision_digest": claim.goal_revision_digest,
        "operation_class": claim.operation_class,
    }
    try:
        return values[fact_class]
    except KeyError as error:
        raise ValueError(
            f"unsupported protected GoalDirected context fact class: {fact_class}"
        ) from error


def _recover_handoff_compaction(
    handoff: GoalHandoff,
    *,
    action: Literal["retry", "fresh_from_handoff"],
) -> GoalHandoff:
    decision_ref = "goal-compaction:" + sha256_digest(
        {
            "prior_handoff_digest": handoff.handoff_digest,
            "prior_decision_ref": handoff.compaction_decision_ref,
            "failure_ref": handoff.compaction_failure_ref,
            "action": action,
            "attempt": handoff.compaction_attempt + 1,
            "selected_context_refs": handoff.context_selection_refs,
            "protected_context_facts": handoff.protected_context_facts,
            "source_document_digests": handoff.source_document_digests,
            "source_binding_digests": handoff.source_binding_digests,
        }
    ).removeprefix("sha256:")
    recovered = replace(
        handoff,
        handoff_digest="pending",
        compaction_decision_ref=decision_ref,
        compaction_status="accepted",
        compaction_attempt=handoff.compaction_attempt + 1,
        compaction_failure_ref="",
    )
    digest_payload = asdict(recovered)
    digest_payload.pop("handoff_digest")
    return replace(recovered, handoff_digest=sha256_digest(digest_payload))


def _workspace_for(
    template: WorkspaceContract,
    request: GoalOperationPreparationRequest,
    runtime_unit: RuntimeUnitIdentity,
    *,
    context_slots: tuple[WorkspaceSlotBinding, ...] = (),
) -> WorkspaceContract:
    role_root = goal_unit_workspace_root(runtime_unit)
    if role_root is None:  # pragma: no cover - `_runtime_unit_for` always builds a goal unit
        raise ValueError("GoalDirected workspace requires a GoalDirected runtime unit")
    if not template.slot_bindings:
        # RRM-016 review fix 3: REQ-CP-DA-013 requires exact exclusive writable slots, and
        # the run-control authority admits a GoalDirected unit only with the compiled slots
        # rebased under its role root. A template without them fails closed here.
        raise ValueError("GoalDirected operation template requires compiled workspace slots")
    payload = template.model_dump(mode="python")
    namespace_id = f"run/{request.run_id}"
    read_mounts: tuple[WorkspaceMount, ...] = ()
    if request.read_workspace_id is not None:
        read_mounts = (
            WorkspaceMount(
                logical_path=f"{role_root}/input",
                durable_ref=workspace_durable_reference(namespace_id, request.read_workspace_id),
                content_digest=sha256_digest(
                    {
                        "workspace_id": request.read_workspace_id,
                        "input_refs": request.verifier_input_refs,
                    }
                ),
            ),
        )
    # RRM-016 / REQ-CP-DA-013: bind the exact compiled slots under the role-scoped root,
    # owned by this iteration's executor or verifier. The run-control authority recomputes
    # the root from the unit identity and verifies the exact slot set.
    owner = WorkspaceOwner(
        kind=(
            WorkspaceOwnerKind.ITERATION
            if request.operation_role == "executor"
            else WorkspaceOwnerKind.EVALUATOR
        ),
        owner_id=goal_operation_id(request.goal_iteration, request.operation_role),
    )
    slot_bindings = tuple(
        slot.model_copy(update={"logical_path": f"{role_root}{slot.logical_path}", "owner": owner})
        for slot in template.slot_bindings
    )
    writable = tuple(
        slot.logical_path for slot in slot_bindings if slot.access == "exclusive_write"
    )
    payload.update(
        {
            "namespace_id": namespace_id,
            "workspace_id": request.workspace_id,
            # FT-B3: the packet's read-only inputs (already under the role root) join the
            # compiled slots; the verifier's packet and workspace stay independent.
            "slot_bindings": (*slot_bindings, *context_slots),
            "exclusive_write_paths": writable,
            "read_mounts": read_mounts,
            "restore_snapshot_id": None,
        }
    )
    return WorkspaceContract.model_validate(payload)


def _prompt_segments(
    template: tuple[PromptSegment, ...],
    request: GoalOperationPreparationRequest,
) -> tuple[PromptSegment, ...]:
    continuation = {
        "goal_revision_id": request.goal_revision_id,
        "goal_revision_digest": request.goal_revision_digest,
        "goal_iteration": request.goal_iteration,
        "operation_role": request.operation_role,
        "handoff_ref": request.handoff_ref,
        "handoff": (asdict(request.handoff) if request.handoff is not None else None),
        "verifier_input_refs": request.verifier_input_refs,
    }
    content = str(continuation)
    segment = PromptSegment(
        source_ref=(
            f"goal-context:{request.run_id}:{request.goal_iteration}:{request.operation_role}"
        ),
        source_revision=request.goal_iteration,
        # RRM-016: the goal context (revision, iteration, role, handoff and verifier input
        # refs) is run state derived partly from model output (the handoff and the
        # executor's output refs). It is never a configured prompt source and must not reach
        # the system prompt. SPEC-CP-DEFINITIONS (Security) treats prompt text and retrieved
        # content as untrusted inputs; SPEC-CP-DEEP-AGENT-RUNTIME invariant 5: model output
        # never grants authority; SPEC-BP-GOAL-DIRECTED invariant 1 and Security: goal text
        # and context cannot expand the envelope or grant capabilities. So the segment is
        # admitted under the most restrictive non-privileged trust class.
        trust_class=PromptTrustClass.UNTRUSTED_CONTENT,
        content=content,
        rendered_digest=sha256_digest(content),
    )
    return (*template, segment)


def _review_feedback_segments(
    request: GoalOperationPreparationRequest,
) -> tuple[PromptSegment, ...]:
    """MP-10: human review feedback for the executor; an instruction, never authority."""

    if request.operation_role != "executor":
        return ()
    segments = []
    for outcome in request.review_feedback:
        content = feedback_instruction(outcome)
        segments.append(
            PromptSegment(
                source_ref=f"human-review:{outcome.human_task_id}",
                source_revision=outcome.review_round,
                trust_class=PromptTrustClass.UNTRUSTED_CONTENT,
                content=content,
                rendered_digest=sha256_digest(content),
            )
        )
    return tuple(segments)


def _lane_binding_for(
    template: OperationExecutionRequest,
    lane_bindings: LaneRebinders,
    *,
    request: GoalOperationPreparationRequest,
    identity: OperationAttemptIdentity,
    workspace: WorkspaceContract,
    runtime_unit: RuntimeUnitIdentity,
    bound_revision: int,
) -> tuple[SealedLaneBinding | None, LaneDispatch | None]:
    binding, dispatch = template.lane_binding, template.lane_dispatch
    if binding is None or dispatch is None:
        return binding, dispatch
    # SV-01: the lane rebinds its own bytes to the live attempt; the family names them by
    # digest and never reads them.
    return lane_bindings.rebind(
        binding,
        dispatch,
        LaneInvocation(
            binding_id=sha256_digest(
                {
                    "template": binding.digest,
                    "semantic_attempt": identity.semantic_key,
                    "generation": request.execution_generation,
                }
            ),
            run_id=request.run_id,
            operation_id=identity.operation_id,
            operation_attempt=identity.operation_attempt,
            execution_generation=request.execution_generation,
            erc_digest=request.effective_configuration_digest,
            control_revision=bound_revision,
            workspace=workspace,
            reservation_id=request.reservation_id,
            runtime_unit=runtime_unit,
            capability_grant=template.capability_grant,
        ),
    )


def document_payload(
    value: GoalRevision | GoalExecutionResult | GoalHandoff | GoalVerificationResult,
) -> dict[str, object]:
    """Canonical dataclass payload helper used by family persistence adapters."""

    payload = value.to_payload() if isinstance(value, GoalExecutionResult) else asdict(value)
    return {str(key): item for key, item in payload.items()}


__all__ = [
    "GoalAdmissionStale",
    "GoalDirectedDocumentRepository",
    "GoalDirectedOperationPreparationService",
    "GoalDirectedOperationResultService",
    "GoalOperationBindingReader",
    "GoalOperationSettlementPort",
    "GoalOperationSettlementReader",
    "GoalOperationSettlementUnavailable",
    "GoalOperationTemplateProvider",
    "GoalOperationTemplateRepository",
    "InMemoryGoalOperationTemplateRepository",
    "RunControlGoalOperationSettlements",
    "configure_goal_directed_family_admissions",
    "document_payload",
]

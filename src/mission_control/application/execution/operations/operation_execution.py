from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol, runtime_checkable

from pydantic import TypeAdapter

from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.context.materialization import ContextDeliveryBlocked
from mission_control.application.execution.harness.budget_controls import BudgetControlAuthority
from mission_control.application.execution.harness.inject import (
    InjectionParked,
    InterruptAndInjectService,
    TurnRecord,
)
from mission_control.application.execution.harness.protocol import (
    OperationLane,
    ValidatesOperationRequest,
)
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    UnitAttempt,
    transition_id_for,
)
from mission_control.application.execution.operations.invocation_settlement import (
    InvocationSettlementStore,
    SavedResultTooLarge,
    SavedSettlementConflict,
    SettlementEvent,
    SettlesInvocation,
    StaleSettlementHolder,
)
from mission_control.application.execution.operations.operation_progress import (
    cancel_requested,
    report_phase,
)
from mission_control.application.execution.service import RunControlService
from mission_control.application.execution.stop_fence import StopFenceRepository
from mission_control.application.resolution.registries import (
    LaneNotQualified,
    LaneRegistry,
    lane_profile_for,
)
from mission_control.domain.authoring.canonical import contract_fingerprint, sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, SecretRef
from mission_control.domain.authoring.identity import stable_id
from mission_control.domain.context.refs import parse_workspace_candidate_ref
from mission_control.domain.context.render import is_context_input_slot
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.budget_controls import LaneBudgetControlRequest
from mission_control.domain.execution.checkpoint_lineage import (
    CheckpointCapture,
    CheckpointInvocationPlan,
    CheckpointLineageConflict,
    CheckpointLineageError,
    CheckpointLineageInDoubt,
    InDoubtReason,
    OperationActivityAttempt,
    StaleClaimFence,
    UnitReconciliationIncident,
    UnitResultObservation,
)
from mission_control.domain.execution.cognition_points import (
    CognitionCoordinate,
    CognitionPointObservation,
    CognitionPointRecord,
    PointWriter,
)
from mission_control.domain.execution.contracts import (
    IN_TURN_RUN_DIMENSIONS,
    ArtifactPromotionRequest,
    AsyncChildCancellationRecord,
    DeepAgentExecutionBinding,
    MaterializedWorkspace,
    OperationExecutionBinding,
    OperationExecutionRequest,
    OperationExecutionResult,
    OperationSettlement,
    PromotedArtifact,
    PromptTrustClass,
    ReusedResultRef,
    RuntimeInvocation,
    RuntimeResult,
    RuntimeUsage,
    SnapshotCloneRequest,
    SnapshotCloneResult,
)
from mission_control.domain.execution.environment_preparation import ENVIRONMENT_NOT_READY
from mission_control.domain.execution.errors import (
    OutputSchemaUnsupported,
    RuntimeInvocationFailure,
    UnsupportedRuntimePolicy,
    WorkspaceMaterializationError,
)
from mission_control.domain.execution.invocation_settlement import (
    InvocationSettlement,
    SettlementOutcome,
    SettlementWait,
    WaitReason,
)
from mission_control.domain.execution.journal import OperationClaimResult, OperationEffectClaim
from mission_control.domain.execution.lane_turns import MAX_EXCERPT_CHARS, ClosingFacts
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from mission_control.domain.policies.contracts import (
    ActorContext,
    BoundaryCommandRecord,
    BudgetApplicability,
    BudgetState,
    CommandStatus,
    LifecycleCommand,
    RecordUsageAction,
    RunPhase,
    RunProjection,
    UnitReconciliationDecision,
)
from mission_control.domain.policies.errors import IdempotencyConflict
from mission_control.domain.policies.forks import ForkOutputsNotCarried, ForkRejected
from mission_control.domain.policies.stop_fence import run_fence_generation
from mission_control.domain.programs.contracts import (
    StageExecutionIdentity,
    StageGraphDecisionMutation,
)
from mission_control.domain.programs.runtime_units import (
    goal_unit_operation_id,
    goal_unit_workspace_root,
    stage_runtime_unit,
)

_LOGGER = logging.getLogger(__name__)

MAX_COMPLETION_CANDIDATE_CHARS: Final = 262_144
"""Bound on the final assistant text a Session Lane's Completion Candidate is parsed from; a
longer final answer yields no candidate (fail closed, with a provenance warning)."""

LANE_TOKEN_DIMENSIONS: Final = ("tokens.input", "tokens.output", "tokens.total")
"""The run-budget dimensions a Session Lane settlement can charge from its closing usage."""

RUN_CHARGED_DIMENSIONS: Final = tuple(
    dict.fromkeys((*LANE_TOKEN_DIMENSIONS, *IN_TURN_RUN_DIMENSIONS))
)
"""Every run-budget dimension a lane's usage may be charged on without a unit reservation
(MP-20 tokens; W1 D38 the in-turn model turns and tool calls)."""

# The lease deadline of the attempt holding the claim lease, so that a cancellation raised
# by the deadline is told apart from a Temporal cancel delivered through the heartbeat.
_LEASE_DEADLINE: ContextVar[asyncio.Timeout | None] = ContextVar(
    "belllabs_operation_lease_deadline", default=None
)


def _uncancel_current_task() -> None:
    """Clear the swallowed cancellation so the settlement's own awaits are not cancelled."""

    task = asyncio.current_task()
    if task is not None:
        task.uncancel()


def _lease_deadline_expired() -> bool:
    deadline = _LEASE_DEADLINE.get()
    return deadline is not None and deadline.expired()


class _SavedResultReady(Exception):
    """Internal: cognition completed and a saved-result store is composed (WI-04)."""


class OperationExecutionInProgress(RuntimeError):
    """A durable claim exists and requires retry or explicit reconciliation."""


class OperationCancellationPending(ValueError):
    """Accepted cancellation fences cognition while its workflow delivery is in transit."""


class OperationLeaseExpired(OperationExecutionInProgress):
    """The holder stopped at its lease deadline; a retry classifies and continues the unit."""


class OperationClaimHeld(OperationExecutionInProgress):
    """W1 D39: another attempt holds the unit's claim lease (REQ-CP-EXEC-014).

    A live holder releases the lease when it stops; a lost worker's lease only expires at
    `lease_expires_at` (the holder's scheduler deadline). The refused attempt does nothing;
    its retry is scheduled after that deadline (`worker_lost` recovery, the L5 rung), so it
    takes the lease over and continues the unit from its latest checkpoint instead of every
    early retry being refused and the unit failing.
    """

    def __init__(self, message: str, *, lease_expires_at: datetime | None) -> None:
        super().__init__(message)
        self.lease_expires_at = lease_expires_at


class OperationStopFencePending(OperationExecutionInProgress):
    """Tracing Stage 3 (R1-F1): the turn ended under a persisted Stop Fence whose cancel run
    control has not journaled. Nothing settles (a fenced turn's output is not admitted as
    `completed`); the lease is released and the retry finds the cancel journaled (the run is
    `cancelling`, so the cancellation saga settles the unit) or the fence's cancel rejected.
    """


class ForkMaterializationPending(OperationExecutionInProgress):
    """RRM-006: the derived run started before its fork's materialization committed.

    Transient: nothing settles, the lease is released and a retry resolves the reuse
    decision once the materialization is visible.
    """

    code = "fork_not_materialized"


class OperationBudgetViolation(ValueError):
    """Runtime usage is outside the operation's immutable budget binding."""


class OperationBudgetReconciliationInProgress(RuntimeError):
    """Concurrent run mutations prevented reconciliation; a retry is safe."""


class OperationAuthorityPort(Protocol):
    async def verify(self, request: OperationExecutionRequest) -> None:
        """Admit the first binding of a semantic operation attempt."""
        ...

    async def verify_continuation(
        self, request: OperationExecutionRequest, binding: OperationExecutionBinding
    ) -> None:
        """Admit a retry, takeover or recovery of an already bound attempt."""
        ...

    async def verify_cancellation(
        self, request: OperationExecutionRequest, binding: OperationExecutionBinding
    ) -> None:
        """RRM-008: admit the cancellation saga's settlement of a bound attempt.

        The accepted cancel command is the authority; the run is `cancelling` (or still
        running when the family's cancel reached the unit first) and never terminal.
        """
        ...


@runtime_checkable
class RunBudgetDimensionsPort(Protocol):
    """The budget dimensions the run's admitted envelope can be charged on (MP-20).

    A Session Lane unit charges its settled/estimated token usage on these even when its own
    reservation does not bound them (a Stage Graph stage reserves `operation.attempts` and
    `concurrency.slots`, a Goal Loop iteration `goal.iterations`): the usage is a provider
    fact recorded in full, the reservation is not widened and the run's hard caps gate the
    next reservation. An authority without this port charges only reserved dimensions."""

    async def charged_budget_dimensions(self, request_scope: str, run_id: str) -> frozenset[str]:
        """The run's declared, applicable budget dimensions."""
        ...


@runtime_checkable
class RunBudgetStatePort(Protocol):
    """W1 D41: the run's budget account, read to bound a lane turn by the authored run budget
    (`in_turn_run_budget`). An authority without this port runs turns bounded by their own
    reservation only, as before."""

    async def run_budget_state(self, request_scope: str, run_id: str) -> BudgetState:
        """The run's current budget state."""
        ...


def in_turn_run_budget(
    budget: BudgetState, binding: OperationExecutionBinding
) -> tuple[tuple[str, ...], dict[str, int]]:
    """W1 D38/D41: the run's in-turn dimensions a turn's usage is charged on, and what each
    bounded one's hard cap leaves for this unit.

    The remainder is the hard cap less what the run consumed, holds pending and holds reserved,
    with this unit's own share added back: its own reservation (it is spending it) and the
    usage already recorded under its own settlement identity (a settlement re-checked after
    its usage was recorded reads the same remainder). Never negative."""

    own_reservation = budget.reservations.get(binding.budget_reservation_id, {})
    own_usage = budget.usage_records.get(operation_settlement_id(binding.binding_id))
    dimensions: list[str] = []
    remaining: dict[str, int] = {}
    for item in budget.limits:
        if (
            item.dimension not in IN_TURN_RUN_DIMENSIONS
            or item.applicability == BudgetApplicability.NOT_APPLICABLE
        ):
            continue
        dimensions.append(item.dimension)
        if item.applicability != BudgetApplicability.BOUNDED or item.hard_cap is None:
            continue
        dimension = item.dimension
        held = (
            budget.consumed.get(dimension, 0)
            + budget.pending_settlement.get(dimension, 0)
            + budget.reserved.get(dimension, 0)
            - own_reservation.get(dimension, 0)
        )
        if own_usage is not None:
            held -= own_usage.actual_amounts.get(dimension, 0)
            held -= own_usage.pending_external_amounts.get(dimension, 0)
        remaining[dimension] = max(item.hard_cap - held, 0)
    return tuple(sorted(dimensions)), remaining


def charged_dimensions(budget: BudgetState) -> frozenset[str]:
    """A run budget's declared dimensions that usage may be recorded on (not `not_applicable`;
    the reducer rejects usage on an undeclared or not-applicable dimension)."""

    return frozenset(
        item.dimension
        for item in budget.limits
        if item.applicability != BudgetApplicability.NOT_APPLICABLE
    )


@runtime_checkable
class RunProjectionPort(Protocol):
    """Tracing Stage 3 (R1-F5): the run projection a fenced turn is matched against (the
    run's execution-target generation). An authority without it is read at the generation
    of a target-less run (`run_fence_generation(None)`)."""

    async def run_projection(self, request_scope: str, run_id: str) -> RunProjection: ...


class AsyncChildCancellationPort(Protocol):
    """REQ-CP-EXEC-008 step 4: cancel every active async child of a unit per its link
    policy and record the provider's acknowledgement or its absence."""

    async def cancel_children(
        self,
        binding: OperationExecutionBinding,
        *,
        reason: str,
        requested_at: datetime,
    ) -> tuple[AsyncChildCancellationRecord, ...]: ...


class CancellableRuntimePort(Protocol):
    """A runtime that can report the latest durable checkpoint of a unit being cancelled."""

    async def observe_latest(
        self,
        invocation: RuntimeInvocation,
        resolved_secrets: Mapping[str, str],
    ) -> RuntimeResult: ...


class RunControlOperationAuthority:
    """Verifies F1/F2 authority without allowing execution records to mutate it."""

    def __init__(self, run_control: RunControlService, control_plane: ControlPlaneService) -> None:
        self._run_control = run_control
        self._control_plane = control_plane

    async def verify_budget_control(
        self, request: LaneBudgetControlRequest
    ) -> BoundaryCommandRecord:
        """Control authority for an existing session; admits no new operation or turn."""
        from mission_control.domain.graph_runtime.identities import StageGraphUnitLocation
        from mission_control.domain.policies.contracts import (
            PauseAction,
            ReceiptState,
            ResumeAction,
        )

        operation = request.operation
        binding = ProviderExecutionBinding.carried_by(operation)
        ceiling = binding.budget_gate_ceiling() if binding is not None else None
        if (
            binding is None
            or ceiling is None
            or not binding.lane_dispatch().declares("budget_gate")
        ):
            raise ValueError("budget gate requires a binding that declares it")
        run = await self._run_control.get_run(operation.request_scope, operation.identity.run_id)
        if run.phase not in {RunPhase.ACTIVE, RunPhase.WAITING, RunPhase.PAUSED}:
            raise ValueError("budget control requires a non-stopping run")
        status = await self._run_control.get_boundary_command(
            operation.request_scope,
            operation.identity.run_id,
            request.command_issuer,
            request.command_id,
        )
        if status is None or status.receipts[-1].state == ReceiptState.REJECTED:
            raise ValueError("budget control has no accepted command authority")
        command = status.command
        action = command.action
        if (
            not isinstance(action, (PauseAction, ResumeAction))
            or action.decision.budget_gate is None
        ):
            raise ValueError("command did not opt into budget_gate")
        if (
            run.execution_target is None
            or command.target.kind != "family"
            or command.target.target_ref != run.execution_target.family_workflow_id
            or command.target.family_workflow_id != run.execution_target.family_workflow_id
            or command.target.root_workflow_id != run.execution_target.root_workflow_id
            or command.target.execution_epoch != run.execution_target.execution_epoch
            or command.target.execution_generation != run.execution_target.execution_generation
            or request.generation != run.execution_target.execution_generation
        ):
            raise ValueError("budget control targets stale family authority")
        if run.version < command.accepted_run_version:
            raise ValueError("budget control run revision regressed")
        await self._verify_bound_authority(operation, run)
        if isinstance(action, PauseAction):
            scope = action.decision.scope
        else:
            gate = action.decision.budget_gate
            if not gate.hold_command_id or not gate.hold_command_issuer:
                raise ValueError("budget resume must name its exact held command")
            hold = await self._run_control.get_boundary_command(
                operation.request_scope,
                operation.identity.run_id,
                gate.hold_command_issuer,
                gate.hold_command_id,
            )
            if (
                hold is None
                or not isinstance(hold.command.action, PauseAction)
                or hold.command.action.decision.budget_gate is None
                or hold.command.action.decision.decision_id != action.decision.pause_decision_id
                or hold.command.target != command.target
                or hold.receipts[-1].state == ReceiptState.REJECTED
            ):
                raise ValueError("budget resume references a different pause")
            scope = hold.command.action.decision.scope
            # No allocation is invented here. The operation's existing reservation must
            # cover its entire retained remote ceiling, including possible in-flight work.
            budget = await self._run_control.get_budget(
                operation.request_scope, operation.identity.run_id
            )
            dimension = "currency.estimated_micros"
            target = gate.target_cap_minor_units or ceiling
            required = target * 10_000
            reservation = budget.reservations.get(operation.budget_reservation_id, {})
            if (
                target > ceiling
                or reservation.get(dimension, 0) < required
                or operation.budget_limits.get(dimension, 0) < required
            ):
                raise ValueError("budget resume lacks retained currency reservation coverage")
            if budget.outstanding_usage_ids or budget.pending_settlement.get(dimension, 0):
                raise ValueError("budget resume has unsettled cost liability")
            limit = next((item for item in budget.limits if item.dimension == dimension), None)
            if (
                limit is None
                or limit.hard_cap is None
                or sum(
                    values.get(dimension, 0)
                    for values in (budget.reserved, budget.consumed, budget.pending_settlement)
                )
                > limit.hard_cap
            ):
                raise ValueError("budget resume remaining run budget is not bounded")
        unit = operation.runtime_unit
        stage = (
            unit.location.stage_id
            if unit and isinstance(unit.location, StageGraphUnitLocation)
            else None
        )
        if not ({"run", "workflow"} & scope) and (stage is None or f"stage:{stage}" not in scope):
            raise ValueError("budget control scope does not cover this operation")
        return command

    async def charged_budget_dimensions(self, request_scope: str, run_id: str) -> frozenset[str]:
        """`RunBudgetDimensionsPort`: the run's declared, applicable budget dimensions."""

        return charged_dimensions(await self._run_control.get_budget(request_scope, run_id))

    async def run_budget_state(self, request_scope: str, run_id: str) -> BudgetState:
        """`RunBudgetStatePort`: the run's budget account as run control holds it."""

        return await self._run_control.get_budget(request_scope, run_id)

    async def run_projection(self, request_scope: str, run_id: str) -> RunProjection:
        """`RunProjectionPort`: the run as run control holds it."""

        return await self._run_control.get_run(request_scope, run_id)

    async def verify(self, request: OperationExecutionRequest) -> None:
        run = await self._run_control.get_run(request.request_scope, request.identity.run_id)
        if run.version != request.run_control_revision:
            await self._verify_stage_admission(request, run)
        if run.phase != RunPhase.ACTIVE:
            raise ValueError("semantic operations require an active Workflow Run")
        await self._verify_bound_authority(request, run)

    async def _verify_stage_admission(
        self, request: OperationExecutionRequest, run: RunProjection
    ) -> None:
        """A sibling may advance global CAS after this exact StageGraph admission.

        The semantic request reference identifies the attempt, not its full payload. The
        immutable family mutation proves admission; normal sealed authority and binding
        fingerprint checks still validate the actual operation request.
        """
        unit = request.runtime_unit
        refusal = "operation is not bound to the accepted Run Control revision"
        if (
            unit is None
            or unit.family != "stage_graph"
            or run.version < request.run_control_revision
        ):
            raise ValueError(refusal)
        digest = sha256_digest(request.identity.semantic_key)[7:]
        mutation_id = f"admit-{digest}"
        mutation = await self._run_control.get_family_mutation(
            request.request_scope,
            request.identity.run_id,
            "stagegraph",
            mutation_id,
            StageGraphDecisionMutation,
        )
        if mutation is None or mutation.decision_kind != "operation_admitted":
            raise ValueError(refusal)
        proposal = mutation.decision_payload.get("proposal")
        if not isinstance(proposal, dict):
            raise ValueError(refusal)
        try:
            identity = TypeAdapter(StageExecutionIdentity).validate_python(proposal.get("identity"))
        except (TypeError, ValueError) as error:
            raise ValueError(refusal) from error
        exact_ref = f"operation-request:{digest}"
        if (
            identity.semantic_key != request.identity.semantic_key
            or request.idempotency_key
            != (f"stagegraph:{identity.semantic_key}:generation:{identity.execution_generation}")
            or stage_runtime_unit(request.request_scope, identity) != unit
            or mutation.exact_operation_request_ref != exact_ref
            or proposal.get("exact_operation_request_ref") != exact_ref
            or proposal.get("reservation_id") != request.budget_reservation_id
            or proposal.get("reservation") != request.budget_limits
        ):
            raise ValueError(refusal)
        transitions = await self._run_control.list_transitions(
            request.request_scope, request.identity.run_id
        )
        admission = next(
            (
                item
                for item in transitions
                if (
                    item.resulting_version == request.run_control_revision
                    and item.command_id == f"stagegraph:{mutation_id}"
                    and item.evidence_refs == (exact_ref,)
                )
            ),
            None,
        )
        if (
            admission is None
            or admission.resulting_projection.effective_configuration_digest
            != request.effective_configuration_digest
            or admission.resulting_projection.execution_target != run.execution_target
            or run.execution_target is None
            or run.execution_target.family != "StageGraph"
            or run.execution_target.execution_epoch != unit.execution_epoch
        ):
            raise ValueError(refusal)

    async def verify_continuation(
        self, request: OperationExecutionRequest, binding: OperationExecutionBinding
    ) -> None:
        """Admit a technical retry, claim takeover or recovery of the same bound attempt.

        REQ-CP-EXEC-005 (AMD-RRM-001): Activity attempts, worker restarts and claim takeovers
        are not disruptive; they continue the same semantic attempt, whose own claim has
        already advanced the run version past the bound revision. So the exact-revision check
        of the first binding does not apply. What must still hold: the binding is the one
        being continued, the run never went backwards, the configuration and reservation
        are the bound ones, and the run is not terminal, paused or cancelling (cancellation
        reconciliation is REQ-CP-EXEC-008's saga). A run that is `waiting` is admitted:
        while a unit is `in_doubt` the run keeps its phase, and other waits do not supersede
        a claimed unit (REQ-CP-RUN-007, REQ-CP-EXEC-014).
        """

        run = await self._run_control.get_run(request.request_scope, request.identity.run_id)
        if (
            binding.run_id != request.identity.run_id
            or binding.request_scope != request.request_scope
            or binding.run_control_revision != request.run_control_revision
        ):
            raise ValueError("continuation does not target the bound operation attempt")
        if run.version < binding.run_control_revision:
            raise ValueError("run authority is older than the operation binding")
        if run.phase == RunPhase.CANCELLING:
            raise OperationCancellationPending(
                "a bound operation cannot continue in a cancelling Workflow Run"
            )
        if run.phase not in {RunPhase.ACTIVE, RunPhase.WAITING}:
            raise ValueError(
                f"a bound operation cannot continue in a {run.phase.value} Workflow Run"
            )
        await self._verify_bound_authority(request, run)

    async def verify_cancellation(
        self, request: OperationExecutionRequest, binding: OperationExecutionBinding
    ) -> None:
        """RRM-008 (REQ-CP-EXEC-008): the accepted cancel is the authority for settling the
        bound attempt `cancelled`. The intent is journaled first: the run is `cancelling`
        (the accepted `cancel` command moved it there before any delivery), never pending,
        active or terminal. A Temporal cancellation without that journal entry is not a
        cancel of the unit (review F1). The binding stays the authentic one
        (configuration, prompts, workspace and reservation are the bound ones)."""

        run = await self._run_control.get_run(request.request_scope, request.identity.run_id)
        if (
            binding.run_id != request.identity.run_id
            or binding.request_scope != request.request_scope
            or binding.run_control_revision != request.run_control_revision
        ):
            raise ValueError("cancellation does not target the bound operation attempt")
        if run.version < binding.run_control_revision:
            raise ValueError("run authority is older than the operation binding")
        if run.phase != RunPhase.CANCELLING:
            raise ValueError(
                f"run control journaled no cancel for a {run.phase.value} Workflow Run"
            )
        await self._verify_bound_authority(request, run)

    async def _verify_bound_authority(
        self, request: OperationExecutionRequest, run: RunProjection
    ) -> None:
        if run.effective_configuration_digest != request.effective_configuration_digest:
            raise ValueError("operation configuration does not match the admitted run")
        configuration = await self._control_plane.retrieve_for_admission(
            request.effective_configuration_digest
        )
        if not (
            request.capability_grant.capabilities <= configuration.effective_authority.capabilities
        ):
            raise ValueError("operation capabilities exceed effective run authority")
        authoritative_prompts = {
            f"prompt:{ref.logical_id}@{ref.revision}"
            for ref in configuration.source_refs
            if ref.kind == DefinitionKind.PROMPT
        }
        privileged_prompt_sources = {
            segment.source_ref
            for segment in request.prompt_segments
            if segment.trust_class
            in {
                PromptTrustClass.SYSTEM_AUTHORITY,
                PromptTrustClass.AUTHORED_INSTRUCTION,
            }
        }
        if not privileged_prompt_sources <= authoritative_prompts:
            raise ValueError(
                "privileged prompt segments are not exact accepted configuration sources"
            )
        workspace_ref = next(
            (
                ref
                for ref in configuration.source_refs
                if ref.kind == DefinitionKind.WORKSPACE_TEMPLATE
            ),
            None,
        )
        if workspace_ref != request.workspace.template_ref:
            raise ValueError("operation workspace does not match the frozen template")
        _verify_family_unit(request, run)
        # RRM-016: a GoalDirected unit binds the exact compiled slots under its role-scoped
        # root, which is recomputed here from the digest-bound unit identity (REQ-CP-DA-013;
        # executor and verifier writable paths stay disjoint, REQ-BP-GD-004). The unit itself
        # was cross-checked against the run's family and the operation above.
        slot_root = goal_unit_workspace_root(request.runtime_unit) or ""
        configured_slots = {
            (slot.name, f"{slot_root}{slot.path}", slot.access)
            for slot in configuration.workflow_workspace_contract.slots
        }
        # FT-B2 (ADR-0027): read-only, digest-bound Context Packet inputs join the compiled
        # slots; they cannot write and cannot overlap a compiled path (WorkspaceContract).
        bound_slots = {
            (slot.slot_name, slot.logical_path, slot.access)
            for slot in request.workspace.slot_bindings
            if not is_context_input_slot(slot)
        }
        if configured_slots != bound_slots:
            raise ValueError("operation workspace slots do not exactly match the compiled contract")
        contract_digest = sha256_digest(
            configuration.workflow_workspace_contract.model_dump(mode="json")
        )
        if request.workspace.workflow_contract_digest != contract_digest:
            raise ValueError("operation workspace contract digest is not authoritative")
        allowed_write_paths = {
            path for _name, path, access in configured_slots if access == "exclusive_write"
        }
        if set(request.workspace.exclusive_write_paths) != allowed_write_paths:
            raise ValueError("operation writable paths do not exactly match its workspace contract")
        budget = await self._run_control.get_budget(request.request_scope, request.identity.run_id)
        reservation = budget.reservations.get(request.budget_reservation_id)
        if reservation is None:
            raise ValueError("operation budget reservation is not authoritative")
        if not request.budget_limits.keys() <= reservation.keys():
            raise ValueError("operation budget contains dimensions outside the reservation")
        if any(
            request.budget_limits.get(dimension, 0) > amount
            for dimension, amount in reservation.items()
        ):
            raise ValueError("operation budget limits exceed the authoritative reservation")


def _verify_family_unit(request: OperationExecutionRequest, run: RunProjection) -> None:
    """RRM-016 review fix 1: a GoalDirected unit is admitted only on a GoalDirected run and
    only for the operation its location names, so the workspace root derived from it cannot
    be borrowed by another family's or another iteration's operation. Conversely (re-check
    a), a GoalDirected run admits only GoalDirected units: an operation without one would
    bind unrebased slots, so executor and verifier would no longer be disjoint."""

    unit = request.runtime_unit
    target = run.execution_target
    goal_directed_run = target is not None and target.family == "GoalDirected"
    if unit is None or unit.family != "goal_directed":
        if goal_directed_run:
            raise ValueError("a GoalDirected Workflow Run admits only GoalDirected runtime units")
        return
    if not goal_directed_run:
        raise ValueError("a GoalDirected runtime unit requires a GoalDirected Workflow Run")
    if (
        unit.belllabs_run_id != request.identity.run_id
        or goal_unit_operation_id(unit) != request.identity.operation_id
    ):
        raise ValueError("GoalDirected runtime unit location does not match its operation")


class RunControlOperationBudgetAuthority:
    """Idempotently reconciles operation usage through the F2 PostgreSQL authority."""

    def __init__(
        self,
        run_control: RunControlService,
        *,
        actor: ActorContext,
        idempotency_issuer: str = "operation-runtime",
    ) -> None:
        self._run_control = run_control
        self._actor = actor
        self._idempotency_issuer = idempotency_issuer

    async def reconcile(
        self,
        *,
        binding: OperationExecutionBinding,
        settlement_id: str,
        usage: RuntimeUsage,
        budget_violation: bool = False,
    ) -> None:
        if not budget_violation:
            unreserved: frozenset[str] = frozenset()
            unbound = _unbound_dimensions(binding, usage)
            if unbound and unbound <= frozenset(RUN_CHARGED_DIMENSIONS):
                # MP-20 / W1 D38: a lane charges its usage on run dimensions its reservation
                # does not bound; they must be the run's declared, applicable dimensions.
                unreserved = frozenset(RUN_CHARGED_DIMENSIONS) & charged_dimensions(
                    await self._run_control.get_budget(binding.request_scope, binding.run_id)
                )
            _validate_bound_usage(binding, usage, unreserved=unreserved)
        release_amounts = {
            dimension: limit
            - min(
                limit,
                usage.amounts.get(dimension, 0) + usage.pending_external_amounts.get(dimension, 0),
            )
            for dimension, limit in binding.budget_limits.items()
            if limit
            > usage.amounts.get(dimension, 0) + usage.pending_external_amounts.get(dimension, 0)
        }
        for _attempt in range(5):
            budget = await self._run_control.get_budget(binding.request_scope, binding.run_id)
            if settlement_id in budget.usage_ids:
                return
            run = await self._run_control.get_run(binding.request_scope, binding.run_id)
            result = await self._run_control.execute(
                LifecycleCommand(
                    command_id=f"operation-budget:{settlement_id}:v{run.version}",
                    idempotency_issuer=self._idempotency_issuer,
                    request_scope=binding.request_scope,
                    run_id=binding.run_id,
                    expected_run_version=run.version,
                    actor=self._actor,
                    action=RecordUsageAction(
                        usage_id=settlement_id,
                        actual_amounts=usage.amounts,
                        reservation_id=binding.budget_reservation_id,
                        release_amounts=release_amounts,
                        pending_external_amounts=usage.pending_external_amounts,
                    ),
                    reason="Reconcile immutable operation settlement usage",
                    evidence_refs=(binding.binding_id,),
                    occurred_at=datetime.now(UTC),
                    correlation_id=f"operation:{binding.semantic_attempt_key}",
                    causation_id=binding.binding_id,
                )
            )
            if result.status == CommandStatus.ACCEPTED:
                return
            if result.status == CommandStatus.STALE:
                continue
            if result.reason_code == "usage_exists":
                current_budget = await self._run_control.get_budget(
                    binding.request_scope, binding.run_id
                )
                if settlement_id in current_budget.usage_ids:
                    return
            raise ValueError(f"operation budget settlement was not accepted: {result.reason_code}")
        raise OperationBudgetReconciliationInProgress(
            "operation budget settlement remained stale after retries"
        )


class OperationBindingRepository(Protocol):
    async def get_binding(
        self,
        semantic_attempt_key: str,
        *,
        request_scope: str,
    ) -> OperationExecutionBinding | None: ...

    async def get_binding_by_id(
        self,
        binding_id: str,
        *,
        request_scope: str,
    ) -> OperationExecutionBinding | None: ...

    async def create_binding(
        self,
        binding: OperationExecutionBinding,
        *,
        request_scope: str,
    ) -> OperationExecutionBinding: ...

    async def get_settlement(
        self,
        binding_id: str,
        *,
        request_scope: str,
    ) -> OperationSettlement | None: ...

    async def claim_execution(self, binding: OperationExecutionBinding) -> bool: ...

    async def settle(
        self,
        settlement: OperationSettlement,
        *,
        request_scope: str,
    ) -> OperationSettlement: ...


ResultManifestObserver = Callable[[str, str, int], Awaitable[None]]
"""Called with the staged result manifest ref, digest and size before authority settlement."""


class OperationExecutionJournalPort(Protocol):
    async def existing_lane_claim(
        self, binding: OperationExecutionBinding, expected_claim_id: str
    ) -> OperationEffectClaim: ...

    async def acquire(
        self,
        binding: OperationExecutionBinding,
        *,
        claimed_by: str,
        at_current_version: bool = False,
    ) -> OperationClaimResult: ...

    async def get_settlement(
        self,
        binding: OperationExecutionBinding,
    ) -> OperationSettlement | None: ...

    async def settle(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim,
        settlement: OperationSettlement,
        *,
        started_at: datetime,
        technical_attempt: int = 1,
        before_authority: ResultManifestObserver | None = None,
        expected_run_version: int | None = None,
    ) -> OperationSettlement: ...

    # --- RRM-004 recovery seams (REQ-CP-DA-018, REQ-CP-RUN-007, `reconcile_unit`) ---

    async def load_result_manifest(
        self,
        binding: OperationExecutionBinding,
        *,
        manifest_ref: str,
        manifest_digest: str,
        manifest_size_bytes: int,
    ) -> OperationSettlement: ...

    async def record_in_doubt(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim,
        incident: UnitReconciliationIncident,
    ) -> None: ...

    async def get_unit_reconciliation(
        self,
        binding: OperationExecutionBinding,
        *,
        unit_key: str,
        execution_generation: int,
        incident_id: str,
    ) -> UnitReconciliationDecision | None: ...

    async def unsettled_effect_ids(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim,
    ) -> tuple[str, ...]: ...

    async def record_reconciliation_applied(
        self,
        binding: OperationExecutionBinding,
        decision: UnitReconciliationDecision,
    ) -> None: ...


@runtime_checkable
class LaneAdmissionRejectionJournal(Protocol):
    """Claim only a never-started rejection, excluding normal dispatch authority."""

    async def acquire_lane_admission_rejection(
        self,
        binding: OperationExecutionBinding,
        *,
        claimed_by: str,
        verify_authority: Callable[[], Awaitable[None]],
    ) -> OperationClaimResult: ...


class RuntimePort(Protocol):
    async def execute(
        self,
        invocation: RuntimeInvocation,
        resolved_secrets: Mapping[str, str],
    ) -> RuntimeResult: ...


class SandboxPort(Protocol):
    async def materialize(self, binding: OperationExecutionBinding) -> MaterializedWorkspace: ...


class CapabilityAssetPort(Protocol):
    async def verify(self, binding: OperationExecutionBinding) -> None: ...


class MCPRuntimePort(Protocol):
    """Verifies exact server revisions, schemas, filters, and approval policy."""

    async def verify_servers(self, binding: OperationExecutionBinding) -> None: ...


class SecretResolutionPort(Protocol):
    async def resolve(self, refs: tuple[SecretRef, ...]) -> Mapping[str, str]: ...


class OperationEventPort(Protocol):
    async def publish(
        self, *, event_key: str, binding_id: str, payload: dict[str, object]
    ) -> None: ...


class OperationBudgetPort(Protocol):
    async def reconcile(
        self,
        *,
        binding: OperationExecutionBinding,
        settlement_id: str,
        usage: RuntimeUsage,
        budget_violation: bool = False,
    ) -> None: ...


class ArtifactPromotionPort(Protocol):
    async def promote(self, request: ArtifactPromotionRequest) -> PromotedArtifact: ...


class SnapshotPort(Protocol):
    async def clone_restore(self, request: SnapshotCloneRequest) -> SnapshotCloneResult: ...


class ReusedSourceResult(Protocol):
    """An immutable source result a fork-derived unit settles by reference (EXEC-012)."""

    @property
    def ref(self) -> ReusedResultRef: ...

    @property
    def source_settlement(self) -> OperationSettlement: ...


class ForkReusePort(Protocol):
    """RRM-006: the reuse decision recorded for a fork-derived unit, if any.

    Returns `None` for an ordinary unit or one the fork decided to re-execute; raises (fails
    closed) for an unmaterialized fork (transient, retried) or an incompatible restore or
    missing fork lineage (terminal, settled `failed`).
    """

    async def reused_result(
        self, binding: OperationExecutionBinding
    ) -> ReusedSourceResult | None: ...


class ReusedOutputCarryPort(Protocol):
    """F1-G4: carries a reused unit's accepted named outputs into the derived run before it
    settles (``application/recovery/fork_outputs.py``). Raises an error with ``code`` and
    ``message`` when the carry is terminally impossible; other errors are retried."""

    async def carry(self, binding: OperationExecutionBinding, reused: ReusedResultRef) -> Any: ...


class OperationExecutionService:
    """Binds immutable intent before invoking any semantic provider side effect."""

    def __init__(
        self,
        *,
        authority: OperationAuthorityPort,
        bindings: OperationBindingRepository,
        lanes: LaneRegistry,
        sandbox: SandboxPort,
        assets: CapabilityAssetPort,
        mcp: MCPRuntimePort,
        secrets: SecretResolutionPort,
        events: OperationEventPort,
        budget: OperationBudgetPort,
        journal: OperationExecutionJournalPort | None = None,
        journal_claimed_by: str = "operation-runtime",
        lineage: CheckpointLineageService | None = None,
        fork_reuse: ForkReusePort | None = None,
        reused_outputs: ReusedOutputCarryPort | None = None,
        children: AsyncChildCancellationPort | None = None,
        stop_fences: StopFenceRepository | None = None,
        mailbox: MailboxDeliveryService | None = None,
        injections: InterruptAndInjectService | None = None,
        cursor_cost_settlement: bool = False,
        saved_results: InvocationSettlementStore | None = None,
        settlement_wait_cap: timedelta = timedelta(hours=1),
        effect_wait_deadline: timedelta = timedelta(hours=24),
        review_alarm_interval: timedelta = timedelta(hours=1),
        settlement_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._authority = authority
        self._bindings = bindings
        # Sprint OC WI-04 (OUTPUT-CONTRACTS §4): a completed lineage-qualified result is saved
        # here before the lane's post-execution settlement; the record owns that settlement.
        # Without a store (unit fixtures), the lane settles inline and its outcome is ignored.
        self._saved_results = saved_results
        # The durable wait's delay cap; an effect wait older than the deadline becomes an
        # operator incident; a review wait (no deadline) emits one durable alarm per interval.
        self._settlement_wait_cap = settlement_wait_cap
        self._effect_wait_deadline = effect_wait_deadline
        self._review_alarm_interval = review_alarm_interval
        self._settlement_clock = settlement_clock or (lambda: datetime.now(UTC))
        # FT-G1: dispatch by lane; composition registers every lane this process runs
        # (OC-R3: the Deep Agents harness is its lane package's, not a default here).
        self._lanes = lanes
        # FT-F3: the immediate cancel's Delivery Report milestones (no-op without a fence).
        self._stop_fences = stop_fences
        # FT-F1: the lane boundary consumes delivered mailbox entries when the turn that
        # carries them starts, and completes their Commands when it settles.
        self._mailbox = mailbox
        # FT-F2: interrupt_and_inject by the lane's semantics while a lineage-qualified turn
        # runs (cancel_and_replace with uncertain-effect settlement, or cooperative_inject).
        self._injections = injections
        self._cursor_cost_settlement = cursor_cost_settlement
        if cursor_cost_settlement and journal is None:
            raise ValueError("delayed Cursor cost requires the durable operation journal")
        self._sandbox = sandbox
        self._assets = assets
        self._mcp = mcp
        self._secrets = secrets
        self._events = events
        self._budget = budget
        self._journal = journal
        self._journal_claimed_by = journal_claimed_by
        self._lineage = lineage
        self._fork_reuse = fork_reuse
        self._reused_outputs = reused_outputs
        self._children = children

    async def execute(
        self,
        request: OperationExecutionRequest,
        attempt: OperationActivityAttempt | None = None,
    ) -> OperationExecutionResult:
        """Execute one bound unit; `attempt` is the observed Temporal Activity delivery."""

        if self._lineage is not None and attempt is None:
            raise ValueError("lineage-qualified execution requires the Activity attempt (EXEC-014)")
        lane = self._lanes.lane_for(request)
        if isinstance(lane, ValidatesOperationRequest):
            # OC-R2: the lane checks its own bytes against this operation's authority envelope
            # before authority, budget reservation, binding or claim are touched.
            lane.validate_request(request)
        if lane.requires_checkpoint_lineage(request) and self._lineage is None:
            raise ValueError(
                "Deep Agent execution requires checkpoint lineage composition (REQ-CP-DA-016)"
            )
        fingerprint = contract_fingerprint(request, exclude={"requested_at"})
        prior = await self._bindings.get_binding(
            request.identity.semantic_key,
            request_scope=request.request_scope,
        )
        if prior is not None:
            if prior.request_fingerprint != fingerprint:
                raise IdempotencyConflict(
                    "semantic operation attempt was reused with conflicting execution intent"
                )
            # `settled`: an authoritative settlement returns unchanged, with no provider work.
            settlement = await self._get_settlement(prior)
            if settlement is not None:
                await self._complete_post_effects(prior, settlement)
                return _public_result(prior, settlement)
            binding = prior
            # A retry, takeover or recovery continues the bound attempt (REQ-CP-EXEC-005).
            await self._authority.verify_continuation(request, binding)
        else:
            await self._authority.verify(request)
            binding = _binding_for(request, fingerprint)
            binding = await self._bindings.create_binding(
                binding,
                request_scope=request.request_scope,
            )
            await self._authority.verify(request)
        claim_result = (
            await self._journal.acquire(
                binding,
                claimed_by=self._journal_claimed_by,
            )
            if self._journal is not None
            else None
        )
        claim = claim_result.claim if claim_result is not None else None
        if (
            self._lineage is not None
            and attempt is not None
            and (claim_result is None or claim is not None)
        ):
            return await self._execute_unit(request, binding, claim, attempt, self._lineage)
        claimed = (
            claim_result.status == "acquired"
            if claim_result is not None
            else await self._bindings.claim_execution(binding)
        )
        if not claimed:
            settlement = await self._get_settlement(binding)
            if settlement is not None:
                await self._complete_post_effects(binding, settlement)
                return _public_result(binding, settlement)
            raise OperationExecutionInProgress(
                "a prior worker owns the durable side-effect claim; retry until its "
                "settlement is visible or explicitly reconcile the claim"
            )
        return await self._dispatch_and_settle(request, binding, claim, attempt=attempt)

    def _lane(self, binding: OperationExecutionBinding) -> OperationLane:
        return self._lanes.lane_for(binding)

    async def _execute_unit(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        attempt: OperationActivityAttempt,
        lineage: CheckpointLineageService,
    ) -> OperationExecutionResult:
        """REQ-CP-EXEC-014 + REQ-CP-DA-018: hold the claim lease, classify, then act once.

        The journal claim records that the unit's consequential effect is claimed. Whether
        this Activity attempt may act on it is decided by the unit generation's claim lease:
        the attempt is observed, then holds or takes over the lease (advancing the fence) or
        stands down while a live holder works. Holding the lease, it classifies the unit
        from durable facts before any provider work.
        """

        try:
            admitted = await lineage.admit_attempt(binding, attempt)
        except StaleClaimFence:
            # REQ-CP-EXEC-005: an accepted generation boundary fences this generation; it
            # reports the boundary instead of failing as a lineage conflict.
            unit, generation = lineage.unit_generation(binding)
            incident = await lineage.repository.get_incident(
                binding.request_scope, unit.unit_key, generation
            )
            if incident is None or incident.decision != "start_new_generation":
                raise
            return _unsettled_result(
                binding,
                failure_code="generation_superseded",
                message="an accepted generation boundary superseded this generation",
                incident_id=incident.incident_id,
            )
        return await self._hold_lease(
            binding,
            admitted,
            lineage,
            lambda: self._recover_or_dispatch(request, binding, claim, admitted, lineage),
        )

    async def cancel(
        self,
        request: OperationExecutionRequest,
        attempt: OperationActivityAttempt,
        *,
        native_ambiguity: bool = False,
    ) -> OperationExecutionResult:
        """RRM-008 (REQ-CP-EXEC-008 steps 3-6): settle a unit that is being cancelled.

        Cognition is never dispatched or resumed here. The attempt holds the claim lease
        (standing down behind a live holder, which settles the unit `cancelled` itself when
        the cancel reached it through its heartbeat), classifies the unit from durable
        facts and acts once: a settled unit returns unchanged; a fenced result settles as
        recorded; an `in_doubt` unit stays with its incident unless an accepted
        `reconcile_unit` decision resolves it; otherwise the unit settles `cancelled` with
        its latest durable checkpoint as the result checkpoint (its partial evidence), after
        every active async child was cancelled under its link policy.
        """

        if self._lineage is None:
            raise ValueError("cancellation requires checkpoint lineage composition (EXEC-008)")
        lineage = self._lineage
        report_phase("cancelling")
        fingerprint = contract_fingerprint(request, exclude={"requested_at"})
        prior = await self._bindings.get_binding(
            request.identity.semantic_key,
            request_scope=request.request_scope,
        )
        if prior is not None:
            if prior.request_fingerprint != fingerprint:
                raise IdempotencyConflict(
                    "semantic operation attempt was reused with conflicting execution intent"
                )
            settlement = await self._get_settlement(prior)
            if settlement is not None:
                await self._complete_post_effects(prior, settlement)
                return _public_result(prior, settlement)
            binding = prior
        else:
            # Never bound (cancelled before dispatch): the binding exists so that the unit
            # has exactly one settlement, which releases its reservation.
            binding = await self._bindings.create_binding(
                _binding_for(request, fingerprint),
                request_scope=request.request_scope,
            )
        await self._authority.verify_cancellation(request, binding)
        claim: OperationEffectClaim | None = None
        if self._journal is not None:
            # The claim is made at the run's current version: an accepted cancel moved the
            # version past the bound revision, which must not strand the unit (RRM-016 risk).
            claim_result = await self._journal.acquire(
                binding, claimed_by=self._journal_claimed_by, at_current_version=True
            )
            claim = claim_result.claim
            if claim is None:
                settlement = await self._get_settlement(binding)
                if settlement is not None:
                    await self._complete_post_effects(binding, settlement)
                    return _public_result(binding, settlement)
                raise OperationExecutionInProgress(
                    f"cancellation claim was not acquired ({claim_result.reason}); retry"
                )
        try:
            admitted = await lineage.admit_attempt(binding, attempt)
        except StaleClaimFence:
            unit, generation = lineage.unit_generation(binding)
            incident = await lineage.repository.get_incident(
                binding.request_scope, unit.unit_key, generation
            )
            if incident is None or incident.decision != "start_new_generation":
                raise
            return await self._settle_superseded(binding, claim, attempt, incident.incident_id)
        return await self._hold_lease(
            binding,
            admitted,
            lineage,
            lambda: self._cancel_or_settle(
                request, binding, claim, admitted, lineage, native_ambiguity=native_ambiguity
            ),
        )

    # --- FT-G2: protocol lanes driven by `lane.turn` (SPEC-07 section 4.1) ------------------

    async def reconcile_lane_cancellation(
        self,
        request: OperationExecutionRequest,
        *,
        attempt: OperationActivityAttempt | None = None,
        reason: str | None = None,
    ) -> OperationExecutionResult | None:
        """Bridge a real lane cancellation into existing fenced operator reconciliation.

        No provider is consulted. A reason records observed uncertainty, never evidence
        that nothing ran. Without a reason only an existing incident is considered.
        The normal cancellation boundary verifies authority and acquires the real attempt
        lease before producing an incident or applying an accepted operator decision.
        """
        if self._lineage is None or attempt is None:
            return None
        binding = await self._bindings.get_binding(
            request.identity.semantic_key, request_scope=request.request_scope
        )
        if binding is None:
            return None
        if binding.execution_runtime == "deep_agent":
            raise ValueError("protocol-lane reconciliation cannot invoke a Deep Agent binding")
        unit, generation = self._lineage.unit_generation(binding)
        incident = await self._lineage.repository.get_incident(
            binding.request_scope, unit.unit_key, generation
        )
        if incident is None and reason is None:
            return None
        return await self.cancel(request, attempt, native_ambiguity=reason is not None)

    async def admit_lane_session(
        self,
        request: OperationExecutionRequest,
        *,
        attempt: OperationActivityAttempt | None = None,
        budget_control: LaneBudgetControlRequest | None = None,
    ) -> LaneSessionAdmission:
        """Bind, authorize and claim a protocol-lane attempt before any provider work.

        A Session Lane (Cursor) keeps its provider session across `lane.turn` segments, so
        the attempt is admitted once and settled once: the binding and the run-control
        effect claim exist before the first `send`, and a resumed segment re-admits the same
        binding (idempotent). A settled attempt returns its settlement and no provider work.
        """

        admitted = self._lanes.admit(lane_profile_for(request))
        if isinstance(admitted, ValidatesOperationRequest):
            admitted.validate_request(request)
        fingerprint = contract_fingerprint(request, exclude={"requested_at"})
        prior = await self._bindings.get_binding(
            request.identity.semantic_key, request_scope=request.request_scope
        )
        if prior is not None:
            if prior.request_fingerprint != fingerprint:
                raise IdempotencyConflict(
                    "semantic operation attempt was reused with conflicting execution intent"
                )
            settlement = await self._get_settlement(prior)
            if settlement is not None:
                await self._complete_post_effects(prior, settlement)
                return LaneSessionAdmission(prior, _public_result(prior, settlement))
            binding = prior
            if budget_control is not None:
                if not isinstance(self._authority, BudgetControlAuthority):
                    raise ValueError("governed budget observation authority is unavailable")
                await self._authority.verify_budget_control(budget_control)
            else:
                await self._authority.verify_continuation(request, binding)
        else:
            if budget_control is not None:
                raise ValueError("budget observation cannot create an operation binding")
            await self._authority.verify(request)
            binding = await self._bindings.create_binding(
                _binding_for(request, fingerprint), request_scope=request.request_scope
            )
            await self._authority.verify(request)
        self._validate_policy_support(request)
        await self._assets.verify(binding)
        await self._mcp.verify_servers(binding)
        await self._lane_claim(binding)
        if self._lineage is not None and attempt is not None:
            # A Session Lane's frames and harness execution hang off the unit's attempt row,
            # which the governed `operation.execute` path records on its own admission.
            await self._lineage.observe_attempt(binding, attempt, dispatching=True)
        return LaneSessionAdmission(binding, None)

    async def _lane_claim(self, binding: OperationExecutionBinding) -> OperationEffectClaim | None:
        if self._journal is None:
            # The side-effect key belongs to this binding; a resumed segment owns it already.
            await self._bindings.claim_execution(binding)
            return None
        claim_result = await self._journal.acquire(binding, claimed_by=self._journal_claimed_by)
        if claim_result.claim is None:
            raise OperationExecutionInProgress(
                f"lane session claim was not acquired ({claim_result.reason}); retry"
            )
        return claim_result.claim

    async def lane_settlement(
        self, request: OperationExecutionRequest
    ) -> OperationExecutionResult | None:
        """The attempt's settled public result, if it settled (`lane.status`)."""

        binding = await self._bindings.get_binding(
            request.identity.semantic_key, request_scope=request.request_scope
        )
        if binding is None:
            return None
        if binding.request_fingerprint != contract_fingerprint(request, exclude={"requested_at"}):
            raise IdempotencyConflict(
                "semantic operation attempt was reused with conflicting execution intent"
            )
        settlement = await self._get_settlement(binding)
        return None if settlement is None else _public_result(binding, settlement)

    async def settle_lane_admission_rejection(
        self,
        request: OperationExecutionRequest,
        rejection: LaneNotQualified,
        *,
        attempt: OperationActivityAttempt | None = None,
    ) -> OperationExecutionResult:
        """Settle an explicit registry refusal before a session or dispatch ever existed.

        The caller must prove the durable harness execution is absent. The dedicated
        journal authority excludes normal dispatch claims, including a claim whose
        authority committed but whose journal write was lost. Missing proof retains
        the reservation; no provider closing facts or unknown usage become zero here.
        """

        if not isinstance(
            rejection, LaneNotQualified
        ) or rejection.lane_profile != lane_profile_for(request):
            raise ValueError("lane admission rejection does not match the operation profile")
        binding = await self._bindings.get_binding(
            request.identity.semantic_key, request_scope=request.request_scope
        )
        if binding is None:
            raise rejection
        expected = bind_operation_execution_request(request)
        if binding.model_copy(update={"bound_at": expected.bound_at}) != expected:
            raise IdempotencyConflict("lane admission rejection differs from the admitted binding")
        settlement = await self._get_settlement(binding)
        if settlement is not None:
            await self._complete_post_effects(binding, settlement)
            return _public_result(binding, settlement)
        if self._lineage is not None:
            unit, generation = self._lineage.unit_generation(binding)
            repository = self._lineage.repository
            if (
                await repository.list_attempts(binding.request_scope, unit.unit_key)
                or await repository.get_transition(binding.request_scope, unit.unit_key, generation)
                or await repository.get_result(binding.request_scope, unit.unit_key, generation)
                or await repository.get_incident(binding.request_scope, unit.unit_key, generation)
            ):
                raise OperationExecutionInProgress("lane rejection has prior execution lineage")
        # Without optional lineage, the dedicated authority claim still proves no
        # dispatch: both execute and admit_lane_session acquire normal authority
        # before recording lineage or opening any native execution. The caller also
        # requires an absent durable harness row; an existing normal claim is refused.
        if not isinstance(self._journal, LaneAdmissionRejectionJournal):
            raise OperationExecutionInProgress("never-started lane rejection authority unavailable")

        async def verify_authority() -> None:
            await self._authority.verify_continuation(request, binding)

        acquired = await self._journal.acquire_lane_admission_rejection(
            binding,
            claimed_by=self._journal_claimed_by,
            verify_authority=verify_authority,
        )
        if acquired.claim is None or acquired.status not in {"acquired", "existing"}:
            raise OperationExecutionInProgress(
                f"lane rejection cannot release retained liability ({acquired.reason})"
            )
        settlement = _failed_settlement(
            binding, failure_code="lane_not_qualified", message=str(rejection)
        ).model_copy(update={"settled_at": acquired.claim.claimed_at})
        return await self._settle(
            binding,
            acquired.claim,
            settlement,
            started_at=acquired.claim.claimed_at,
            attempt=attempt,
            admitted=None,
        )

    async def read_lane_settlement(
        self, request: OperationExecutionRequest
    ) -> OperationSettlement | None:
        """Read the journal's verified immutable result without dispatch or post-effects."""
        binding = await self._bindings.get_binding(
            request.identity.semantic_key, request_scope=request.request_scope
        )
        if binding is None:
            return None
        expected = bind_operation_execution_request(request)
        if binding != expected:
            raise ValueError("lane result read differs from its admitted binding")
        return await self._get_settlement(binding)

    async def read_lane_result(
        self, request: OperationExecutionRequest
    ) -> OperationExecutionResult | None:
        """Read an immutable settled result without replaying post effects."""
        settlement = await self.read_lane_settlement(request)
        if settlement is None:
            return None
        binding = await self._bindings.get_binding(
            request.identity.semantic_key, request_scope=request.request_scope
        )
        assert binding is not None
        return _public_result(binding, settlement)

    async def settle_lane_session(
        self,
        request: OperationExecutionRequest,
        facts: ClosingFacts,
        *,
        attempt: OperationActivityAttempt | None = None,
        native_turn_ref: str | None = None,
        cancelled_by_command: bool = False,
        final_text: str | None = None,
        existing_claim_id: str | None = None,
        expected_run_version: int | None = None,
        settlement_time: datetime | None = None,
        points: tuple[CognitionPointObservation, ...] = (),
    ) -> OperationExecutionResult:
        """Settle a protocol-lane attempt once from its closing facts (never from deltas).

        A provider `finished` completes the operation (acceptance stays with the Completion
        Contract); `error` and `expired` fail it; `cancelled` settles `cancelled` and, for a
        command, records the Stop Fence milestones. Token usage is charged on the dimensions
        the binding bounds and (MP-20) on the run's declared token dimensions the unit's
        reservation does not bound; `unknown` usage charges nothing. The full lane usage and
        the closing facts travel in the event payload.

        `final_text` is the lane's full final assistant text (never an excerpt); the
        Completion Candidate is parsed from it (see `lane_final_text`).

        K1 (cross-provider control, 2026-11-05): `points` are the generation's cognition
        points the lane folded from its persisted frames. With a lineage and an attempt the
        attempt is admitted against its unit generation (the claim lease it holds while the
        result and the point batch are written, `written_by: adapter`, in the settlement
        transaction) and released after; without them, or when the admission fails, the
        settlement proceeds and the points are dropped (evidence only; the reconciler
        re-derives them).
        """

        if existing_claim_id is not None and cancelled_by_command:
            raise ValueError("retained evidence cannot acknowledge provider cancellation")
        binding = await self._bindings.get_binding(
            request.identity.semantic_key, request_scope=request.request_scope
        )
        if binding is None:
            raise ValueError("a lane session settles only an admitted binding")
        settlement = await self._get_settlement(binding)
        if settlement is not None:
            await self._complete_post_effects(binding, settlement)
            return _public_result(binding, settlement)
        if not facts.terminal:
            raise ValueError("a lane session settles only from terminal closing facts")
        claim: OperationEffectClaim | None
        if existing_claim_id is not None:
            if self._journal is None:
                raise ValueError("terminal evidence adoption requires its durable journal")
            claim = await self._journal.existing_lane_claim(binding, existing_claim_id)
        else:
            claim = await self._lane_claim(binding)
        if cancelled_by_command:
            await self._fence_milestone(binding, "provider_acknowledged")
        run_dimensions = await self._run_dimensions(binding)
        settlement = _lane_settlement(
            binding,
            facts,
            native_turn_ref=native_turn_ref,
            cancelled_by_command=cancelled_by_command,
            final_text=final_text,
            run_dimensions=run_dimensions,
            settle_cursor_cost=(self._cursor_cost_settlement or existing_claim_id is not None)
            and request.lane_dispatch is not None
            and request.lane_dispatch.declares("external_cost_settlement"),
        )
        if settlement_time is not None:
            if settlement_time.utcoffset() is None:
                raise ValueError("retained settlement time must be attributable")
            settlement = settlement.model_copy(update={"settled_at": settlement_time})
        try:
            _validate_bound_usage(binding, settlement.usage, unreserved=run_dimensions)
        except OperationBudgetViolation as violation:
            # The lane ran past the bound budget: the attempt fails `budget_exceeded`, with the
            # observed usage recorded (never counted as zero).
            settlement = settlement.model_copy(
                update={
                    "status": "failed",
                    "failure_code": "budget_exceeded",
                    "failure_message": f"{type(violation).__name__} at governed operation boundary",
                }
            )
        admitted: UnitAttempt | None = None
        if points and self._lineage is not None and attempt is not None:
            try:
                admitted = await self._lineage.admit_attempt(binding, attempt)
            except Exception:
                _LOGGER.warning(
                    "the lane attempt was not admitted for its points; the settlement "
                    "proceeds without them",
                    exc_info=True,
                )
        try:
            result = await self._settle(
                binding,
                claim,
                settlement,
                started_at=min(datetime.now(UTC), settlement.settled_at),
                attempt=attempt,
                admitted=admitted,
                expected_run_version=expected_run_version,
                points=points if admitted is not None else (),
                points_written_by="adapter",
            )
        finally:
            if admitted is not None and self._lineage is not None:
                with suppress(Exception):
                    await self._lineage.release(admitted)
        if cancelled_by_command:
            await self._fence_milestone(binding, "settled")
        return result

    async def _run_dimensions(self, binding: OperationExecutionBinding) -> frozenset[str]:
        """The run's chargeable dimensions (MP-20), when the authority can say; otherwise a
        lane settlement charges only what its own reservation bounds, as before."""

        if not isinstance(self._authority, RunBudgetDimensionsPort):
            return frozenset()
        return frozenset(RUN_CHARGED_DIMENSIONS) & await self._authority.charged_budget_dimensions(
            binding.request_scope, binding.run_id
        )

    async def _validate_turn_usage(
        self, binding: OperationExecutionBinding, result: RuntimeResult
    ) -> None:
        """A finished turn's usage is within budget: bounded by the unit's limits, charged on
        unreserved run dimensions only when the run declares them (MP-20, W1 D38), and never
        a turn the lane ended at an exhausted budget (W1 D41: `budget_stop`)."""

        _validate_bound_usage(binding, result.usage, unreserved=await self._run_dimensions(binding))
        if result.budget_stop:
            raise OperationBudgetViolation(
                "the lane ended the turn at an exhausted budget: "
                + ", ".join(sorted(result.budget_stop))
            )

    async def lane_in_doubt(
        self, request: OperationExecutionRequest, *, reason: str
    ) -> OperationExecutionResult:
        """The attempt's `in_doubt` disposition when the provider state cannot be known
        (native turn lost, status unresolved after the poll bound). Nothing settles; the
        claim stays unsettled for operator reconciliation."""

        binding = await self._bindings.get_binding(
            request.identity.semantic_key, request_scope=request.request_scope
        )
        if binding is None:
            binding = bind_operation_execution_request(request)
        settlement = await self._get_settlement(binding)
        if settlement is not None:
            return _public_result(binding, settlement)
        return OperationExecutionResult(
            binding_id=binding.binding_id,
            semantic_attempt_key=binding.semantic_attempt_key,
            status="in_doubt",
            failure_code=reason,
            failure_message="lane provider state is unknown; the unit awaits reconciliation",
            unit_key=binding.runtime_unit.unit_key if binding.runtime_unit is not None else None,
        )

    async def _hold_lease(
        self,
        binding: OperationExecutionBinding,
        admitted: UnitAttempt,
        lineage: CheckpointLineageService,
        body: Callable[[], Awaitable[OperationExecutionResult]],
    ) -> OperationExecutionResult:
        if not admitted.admission.lease_granted:
            settlement = await self._get_settlement(binding)
            if settlement is not None:
                await self._complete_post_effects(binding, settlement)
                return _public_result(binding, settlement)
            raise OperationClaimHeld(
                "a live attempt holds the unit's claim lease; retry until its settlement is "
                "visible or the lease expires (REQ-CP-EXEC-014)",
                lease_expires_at=admitted.admission.holder_lease_expires_at,
            )
        budget = admitted.work_budget(lineage.now())
        if budget <= 0:
            with suppress(Exception):
                await lineage.release(admitted)
            raise OperationLeaseExpired(
                "the attempt's claim lease is already within its safety margin"
            )
        try:
            # REQ-CP-EXEC-014: a live holder never outlives its lease. It stops (cancelling
            # in-flight cognition) before a later attempt may take the lease over, so a
            # superseded holder cannot keep calling the model or tools.
            async with asyncio.timeout(budget) as deadline:
                token = _LEASE_DEADLINE.set(deadline)
                try:
                    result = await body()
                finally:
                    _LEASE_DEADLINE.reset(token)
        except TimeoutError as error:
            with suppress(Exception):
                await lineage.release(admitted)
            if not deadline.expired():
                raise
            raise OperationLeaseExpired(
                "the attempt reached its claim lease deadline and stopped; a later attempt "
                "classifies and continues the unit (REQ-CP-EXEC-014)"
            ) from error
        except (Exception, asyncio.CancelledError):
            # The holder knows it is stopping: release the lease so the next attempt takes it
            # over (advancing the fence) instead of waiting for it to expire. A lost worker
            # releases nothing; its lease simply expires with the attempt's deadline.
            with suppress(Exception):
                await lineage.release(admitted)
            raise
        with suppress(Exception):
            await lineage.release(admitted)
        return result

    async def _recover_or_dispatch(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        lineage: CheckpointLineageService,
    ) -> OperationExecutionResult:
        admission = admitted.admission
        # `settled` (a concurrent holder may have settled before this lease was granted).
        settlement = await self._get_settlement(binding)
        if settlement is not None:
            await self._complete_post_effects(binding, settlement)
            return _public_result(binding, settlement)
        # `observed_unsettled`: the fenced result manifest settles without provider work.
        if admission.existing_result is not None:
            return await self._settle_recorded(binding, claim, admitted, admission.existing_result)
        if admission.existing_transition is not None:
            return await self._in_doubt(
                binding, claim, admitted, reason="unrecoverable_result_manifest"
            )
        # WI-04: a saved provider result settles; its cognition is never dispatched again. An
        # incident on the unit (an effect wait past its deadline) is decided by the operator
        # first.
        saved = await self._saved_result(binding)
        accepted_leaf: QualifiedCheckpointKey | None = None
        reconciled = False
        if admission.incident is not None:
            decision = await self._reconciliation(binding, admitted, admission.incident)
            if decision is None:
                return await self._in_doubt(
                    binding, claim, admitted, reason=admission.incident.reason
                )
            await lineage.repository.apply_reconciliation(binding.request_scope, decision)
            if self._journal is not None:
                # RRM-007: the operation boundary applied the accepted decision.
                await self._journal.record_reconciliation_applied(binding, decision)
            if decision.decision == "abandon_unit":
                if saved is not None:
                    return await self._settle_abandoned_saved(
                        binding, claim, admitted, saved, decision.decision_id
                    )
                return await self._settle(
                    binding,
                    claim,
                    _failed_settlement(
                        binding,
                        failure_code="in_doubt_abandoned",
                        message="in_doubt unit abandoned by operator reconciliation",
                    ),
                    started_at=datetime.now(UTC),
                    attempt=admitted.attempt,
                    admitted=admitted,
                )
            if decision.decision == "start_new_generation":
                # REQ-CP-EXEC-005: this generation is fenced and can never settle the unit.
                return _unsettled_result(
                    binding,
                    failure_code="generation_superseded",
                    message="an accepted generation boundary superseded this generation",
                    incident_id=admission.incident.incident_id,
                )
            if saved is not None:
                # The operator decided the incident: the saved result's wait resumes, its
                # effect deadline measured from the decision.
                return await self._resume_saved(
                    request,
                    binding,
                    claim,
                    admitted,
                    lineage,
                    saved,
                    resumed_by=decision.decision_id,
                )
            accepted_leaf = decision.accepted_checkpoint
            reconciled = True
        if saved is not None:
            return await self._resume_saved(request, binding, claim, admitted, lineage, saved)
        if self._fork_reuse is not None and not reconciled:
            # REQ-CP-EXEC-012: a fork-derived unit inside the reuse frontier settles by the
            # immutable source result; cognition is never re-run and nothing is copied.
            try:
                reused = await self._fork_reuse.reused_result(binding)
            except ForkRejected as error:
                if error.code == "fork_not_materialized":
                    # Transient: the derived root started before the fork's materialization
                    # committed. Nothing settles; the lease is released and a retry
                    # resolves the recorded reuse decision.
                    raise ForkMaterializationPending(error.message) from error
                # Terminal (`incompatible_restore`, `fork_lineage_missing`): fail closed and
                # terminate cleanly. The unit settles `failed` with the typed reason (claim,
                # reservation and lease released); cognition never runs, nothing is reused.
                return await self._settle(
                    binding,
                    claim,
                    _failed_settlement(binding, failure_code=error.code, message=error.message),
                    started_at=datetime.now(UTC),
                    attempt=admitted.attempt,
                    admitted=admitted,
                )
            if reused is not None:
                return await self._settle_reused(binding, claim, admitted, reused)
        if admitted.deep_binding is None and admission.prior_dispatch and not reconciled:
            # A native effect dispatched by an earlier holder is ambiguous: it is reconciled
            # through its claim, never repeated speculatively (REQ-CP-RUN-007).
            return await self._in_doubt(binding, claim, admitted, reason="ambiguous_native_effect")
        return await self._dispatch_and_settle(
            request,
            binding,
            claim,
            attempt=admitted.attempt,
            admitted=admitted,
            plan=lineage.plan(admitted, accepted_leaf=accepted_leaf),
        )

    async def _cancel_or_settle(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        lineage: CheckpointLineageService,
        *,
        native_ambiguity: bool = False,
    ) -> OperationExecutionResult:
        """Classify a unit being cancelled from durable facts and act once (EXEC-008)."""

        admission = admitted.admission
        settlement = await self._get_settlement(binding)
        if settlement is not None:
            await self._complete_post_effects(binding, settlement)
            return _public_result(binding, settlement)
        if admission.existing_result is not None:
            return await self._settle_recorded(binding, claim, admitted, admission.existing_result)
        if admission.existing_transition is not None:
            return await self._in_doubt(
                binding, claim, admitted, reason="unrecoverable_result_manifest"
            )
        # WI-04: cognition completed before the cancel. The saved result settles honestly
        # (`cancelled`, its completed execution outcome and usage retained); the stop fence
        # starts no new evaluation and committed work is still reconciled.
        saved = await self._saved_result(binding)
        accepted_leaf: QualifiedCheckpointKey | None = None
        if admission.incident is not None:
            # Step 5: an ambiguous effect is reconciled by the operator, never speculatively.
            decision = await self._reconciliation(binding, admitted, admission.incident)
            if decision is None:
                return await self._in_doubt(
                    binding, claim, admitted, reason=admission.incident.reason
                )
            await lineage.repository.apply_reconciliation(binding.request_scope, decision)
            if self._journal is not None:
                await self._journal.record_reconciliation_applied(binding, decision)
            if decision.decision == "abandon_unit":
                await self._abandon_saved(saved, admitted, decision.decision_id)
                # A saved result's known spend is charged; the abandonment closed the lineage,
                # so its checkpoint is not transitioned (the key travels as evidence).
                return await self._settle_cancelled(
                    binding,
                    claim,
                    admitted,
                    None,
                    None
                    if saved is None
                    else saved.saved_result.model_copy(
                        update={
                            "checkpoint": None,
                            "cognition_points": (),
                            "event_payloads": (
                                _abandoned_saved_evidence(saved, decision.decision_id),
                            ),
                        }
                    ),
                    failure_code="in_doubt_abandoned",
                    abandonment_decision_id=decision.decision_id,
                )
            if decision.decision == "start_new_generation":
                return await self._settle_superseded(
                    binding, claim, admitted.attempt, admission.incident.incident_id
                )
            if saved is not None:
                return await self._resume_saved(
                    request,
                    binding,
                    claim,
                    admitted,
                    lineage,
                    saved,
                    fenced=True,
                    resumed_by=decision.decision_id,
                )
            accepted_leaf = decision.accepted_checkpoint
        if saved is not None:
            return await self._resume_saved(
                request, binding, claim, admitted, lineage, saved, fenced=True
            )
        if admitted.deep_binding is None:
            if admission.prior_dispatch or native_ambiguity:
                return await self._in_doubt(
                    binding, claim, admitted, reason="ambiguous_native_effect"
                )
            return await self._settle_cancelled(binding, claim, admitted, None, None)
        plan = lineage.plan(admitted, accepted_leaf=accepted_leaf)
        invocation = await self._invocation(request, binding, plan)
        resolved_secrets = await self._secrets.resolve(binding.secret_refs)
        try:
            latest = await self._observe_latest(invocation, resolved_secrets)
        except CheckpointLineageInDoubt as error:
            return await self._in_doubt(
                binding, claim, admitted, reason=error.reason, candidates=error.candidates
            )
        return await self._settle_cancelled(binding, claim, admitted, plan, latest)

    async def _observe_latest(
        self, invocation: RuntimeInvocation, resolved_secrets: Mapping[str, str]
    ) -> RuntimeResult:
        observe = getattr(self._lanes.lane_for(invocation.binding), "observe_latest", None)
        if observe is None:
            raise CheckpointLineageInDoubt(
                "the runtime cannot report the latest durable checkpoint of a cancelled unit",
                reason="unclassifiable",
            )
        result: RuntimeResult = await observe(invocation, resolved_secrets)
        return result

    async def _invocation(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        plan: CheckpointInvocationPlan | None,
    ) -> RuntimeInvocation:
        workspace = await self._sandbox.materialize(binding)
        dimensions: tuple[str, ...] = ()
        remaining: dict[str, int] = {}
        if isinstance(self._authority, RunBudgetStatePort):
            # W1 D41: the authored run budget bounds the turn, not only its reservation.
            dimensions, remaining = in_turn_run_budget(
                await self._authority.run_budget_state(binding.request_scope, binding.run_id),
                binding,
            )
        return RuntimeInvocation(
            binding=binding,
            prompt_segments=request.prompt_segments,
            workspace=workspace,
            resolved_secret_names=tuple(
                sorted(f"{ref.provider}:{ref.key}" for ref in binding.secret_refs)
            ),
            checkpoint_plan=plan,
            run_budget_dimensions=dimensions,
            run_budget_remaining=remaining,
        )

    async def _settle_cancelled(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        plan: CheckpointInvocationPlan | None,
        latest: RuntimeResult | None,
        *,
        failure_code: str = "cancelled",
        abandonment_decision_id: str | None = None,
        points: tuple[CognitionPointObservation, ...] = (),
    ) -> OperationExecutionResult:
        """Steps 4-5: cancel the active async children, then settle `cancelled` once.

        The settlement records the usage the unit's completed calls incurred (a call in
        flight is unobservable and recorded by nothing; a child's unattributed usage stays
        pending on the child's own effect), releases the rest of the reservation, settles the
        unit's effect claim `cancelled`, and names the latest durable checkpoint as the
        result checkpoint so the namespace head advances over the partial lineage.
        """

        report_phase("settling")
        started_at = datetime.now(UTC)
        # An operator abandonment is authority to dispose of the unit, not a provider ack.
        abandoned = failure_code == "in_doubt_abandoned"
        if not abandoned:
            await self._fence_milestone(binding, "provider_acknowledged")
        children = await self._cancel_children(binding, started_at)
        if self._journal is not None and claim is not None:
            # Step 5 (REQ-CP-RUN-007 narrowed): a consequential effect the unit claimed and
            # could not settle is ambiguous; the unit parks `in_doubt` for the operator. The
            # children just reached are not ambiguous: their outcome is recorded on their
            # own effect, whose pending usage blocks the run's terminal settlement instead.
            handled = {item.effect_id for item in children}
            unsettled = tuple(
                effect_id
                for effect_id in await self._journal.unsettled_effect_ids(binding, claim)
                if effect_id not in handled
            )
            if unsettled:
                return await self._in_doubt(
                    binding,
                    claim,
                    admitted,
                    reason="unsettled_effect_claims",
                    unsettled_effect_ids=unsettled,
                )
        capture = latest.checkpoint if latest is not None else None
        evidence: tuple[dict[str, object], ...] = ()
        if abandoned:
            incident = admitted.admission.incident
            if incident is None or abandonment_decision_id is None:
                raise ValueError("operator abandonment requires its accepted incident decision")
            evidence = (
                {
                    "operator_abandonment": {
                        "incident_id": incident.incident_id,
                        "decision_id": abandonment_decision_id,
                        "native_status": "unknown",
                        # WI-04: a saved result's spend is known; otherwise it is not.
                        "usage_disposition": "saved_result" if latest is not None else "unknown",
                        "provider_acknowledged": False,
                    }
                },
            )
        settlement = OperationSettlement(
            settlement_id=operation_settlement_id(binding.binding_id),
            binding_id=binding.binding_id,
            status="cancelled",
            output_text=latest.output_text if latest is not None else "",
            usage=latest.usage if latest is not None else RuntimeUsage(),
            provider_run_id=latest.provider_run_id if latest is not None else None,
            event_payloads=evidence
            + (
                ({"cancelled_async_children": [item.model_dump(mode="json") for item in children]},)
                if children
                else ()
            ),
            failure_code=failure_code,
            failure_message=(
                "operation abandoned by operator; native outcome and usage remain unknown"
                if abandoned
                else "operation cancelled by the governed cancellation saga"
            ),
            settled_at=datetime.now(UTC),
            checkpoint_transition_id=(
                transition_id_for(plan) if plan is not None and capture is not None else None
            ),
            result_checkpoint=capture.result_key if capture is not None else None,
        )
        result = await self._settle(
            binding,
            claim,
            settlement,
            started_at=started_at,
            attempt=admitted.attempt,
            admitted=admitted,
            plan=plan if capture is not None else None,
            capture=capture,
            # Tracing Stage 3 (R1-F4): a fenced turn that finished keeps its cognition points
            # (and with them the result point's budget snapshot).
            points=points if capture is not None else (),
        )
        await self._fence_milestone(binding, "settled")
        return result

    async def _fence_milestone(
        self,
        binding: OperationExecutionBinding,
        milestone: Literal["provider_acknowledged", "settled"],
    ) -> None:
        if self._stop_fences is None:
            return
        try:
            await self._stop_fences.record_milestone(
                binding.request_scope,
                binding.run_id,
                None,
                milestone,
                unit_key=binding.binding_id,
            )
        except Exception:
            # Report evidence only: the settlement above is the authority.
            _LOGGER.warning("stop fence milestone %s was not recorded", milestone, exc_info=True)

    async def _settle_superseded(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        attempt: OperationActivityAttempt,
        incident_id: str,
    ) -> OperationExecutionResult:
        """RRM-008 re-review: settle a generation superseded before the cancel (EXEC-005/008).

        An accepted `start_new_generation` fenced this generation before the run was
        cancelled, and a cancelling run admits no new generation (the reducer rejects it and
        cancellation re-executes nothing), so no later generation will ever settle the unit.
        Its claim, reservation and effect settle `cancelled` here, exactly once, with the
        `generation_superseded` code. The fenced generation writes nothing to its lineage (no
        result observation, no transition) and no cognition is observed or resumed; as with
        `abandon_unit`, no usage is attributed to the in_doubt generation. Active async
        children are cancelled first. An unsettled consequential effect is never settled
        over: the unit then stays unsettled for the operator.
        """

        report_phase("settling")
        started_at = datetime.now(UTC)
        children = await self._cancel_children(binding, started_at)
        if self._journal is not None and claim is not None:
            handled = {item.effect_id for item in children}
            unsettled = tuple(
                effect_id
                for effect_id in await self._journal.unsettled_effect_ids(binding, claim)
                if effect_id not in handled
            )
            if unsettled:
                return _unsettled_result(
                    binding,
                    failure_code="generation_superseded",
                    message=(
                        "the superseded generation holds unsettled effect claims; it awaits "
                        "operator reconciliation"
                    ),
                    incident_id=incident_id,
                )
        settlement = OperationSettlement(
            settlement_id=operation_settlement_id(binding.binding_id),
            binding_id=binding.binding_id,
            status="cancelled",
            event_payloads=(
                ({"cancelled_async_children": [item.model_dump(mode="json") for item in children]},)
                if children
                else ()
            ),
            failure_code="generation_superseded",
            failure_message="superseded generation settled by the governed cancellation saga",
            settled_at=datetime.now(UTC),
        )
        return await self._settle(
            binding,
            claim,
            settlement,
            started_at=started_at,
            attempt=attempt,
            admitted=None,
        )

    async def _turn_fence(
        self, request: OperationExecutionRequest, binding: OperationExecutionBinding
    ) -> Literal["journaled", "pending"] | None:
        """Whether a persisted Stop Fence covers the run after the turn, and whether run
        control journaled its cancel (`pending`: not yet, or the reducer rejected it).

        Tracing Stage 3 (R1-F5): the fence is the run's and is matched against the run's
        execution-target generation (`run_fence_generation`), not the unit's per-unit
        `execution_generation`, which a `start_new_generation` advances (a generation-2 unit
        is fenced like any other unit of the run). R1-F2: the check only decides how a
        finished turn settles; a failing read is logged and is not a fence.
        """

        if self._stop_fences is None or binding.execution_runtime != "deep_agent":
            return None
        try:
            fence = await self._stop_fences.get(binding.request_scope, binding.run_id)
            if fence is None or fence.fenced_at is None:
                return None
            run = (
                await self._authority.run_projection(binding.request_scope, binding.run_id)
                if isinstance(self._authority, RunProjectionPort)
                else None
            )
            if not fence.covers(run_fence_generation(run)):
                return None
            journaled = await self._cancel_journaled(request, binding)
        except Exception:
            _LOGGER.warning(
                "operation %s: the stop fence check after the turn failed; not fenced",
                binding.binding_id,
                exc_info=True,
            )
            return None
        return "journaled" if journaled else "pending"

    async def _settle_fenced_turn(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        plan: CheckpointInvocationPlan | None,
        runtime_result: RuntimeResult,
    ) -> OperationExecutionResult:
        """Settle a finished turn `cancelled` under a journaled immediate cancel.

        Tracing Stage 3 (R1-F8): this path runs exactly while the cancel is in flight, so
        the heartbeat can deliver Temporal's cancellation into the settlement's awaits. The
        settlement runs shielded; a requested Temporal cancel is swallowed (as the heartbeat
        path does with `_uncancel_current_task`) and the settlement is awaited to its end.
        Any other cancellation (the lease deadline, a worker shutdown) stops it as before.
        """

        return await self._shielded(
            lambda: self._settle_cancelled(
                binding,
                claim,
                admitted,
                plan,
                runtime_result,
                points=runtime_result.cognition_points,
            )
        )

    async def _cancel_journaled(
        self, request: OperationExecutionRequest, binding: OperationExecutionBinding
    ) -> bool:
        """Whether run control journaled the cancel this attempt is being asked to apply."""

        try:
            await self._authority.verify_cancellation(request, binding)
        except ValueError:
            return False
        return True

    async def _cancel_children(
        self, binding: OperationExecutionBinding, requested_at: datetime
    ) -> tuple[AsyncChildCancellationRecord, ...]:
        if self._children is None:
            return ()
        return await self._children.cancel_children(
            binding,
            reason="parent operation cancelled by the governed cancellation saga",
            requested_at=requested_at,
        )

    async def _dispatch_and_settle(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        *,
        attempt: OperationActivityAttempt | None,
        admitted: UnitAttempt | None = None,
        plan: CheckpointInvocationPlan | None = None,
    ) -> OperationExecutionResult:
        runtime_invoked = False
        started_at = datetime.now(UTC)
        observed_usage = RuntimeUsage()
        capture: CheckpointCapture | None = None
        points: tuple[CognitionPointObservation, ...] = ()
        turns = TurnRecord()
        completed: RuntimeResult | None = None
        report_phase("dispatching")
        try:
            self._validate_policy_support(request)
            await self._assets.verify(binding)
            await self._mcp.verify_servers(binding)
            resolved_secrets = await self._secrets.resolve(binding.secret_refs)
            invocation = await self._invocation(request, binding, plan)
            await self._mailbox_turn_started(request, binding)
            runtime_invoked = True
            report_phase("cognition")
            try:
                runtime_result = await self._execute_turns(
                    request, binding, claim, admitted, invocation, resolved_secrets, turns
                )
            except InjectionParked as parked:
                # FT-F2: the interrupted turn's uncertain effects did not settle; no
                # replacement runs and the unit parks with a typed incident.
                assert admitted is not None
                return await self._in_doubt(
                    binding,
                    claim,
                    admitted,
                    reason="unsettled_effect_claims",
                    unsettled_effect_ids=parked.pending_effect_ids,
                )
            except asyncio.CancelledError:
                # REQ-CP-EXEC-008 step 3: a requested Temporal cancel reached this Activity
                # through its heartbeat and interrupted the in-flight step. The holder
                # records the latest durable checkpoint and settles `cancelled` itself;
                # nothing resumes. Every other cancellation of the task is not a cancel of
                # the unit (REQ-CP-EXEC-011): the lease deadline (REQ-CP-EXEC-014), a worker
                # shutdown, a heartbeat or start-to-close timeout, a pause or a reset. The
                # holder then stands down and the next attempt classifies and recovers. The
                # journal is the authority: run control must hold the accepted cancel.
                if (
                    admitted is None
                    or plan is None
                    or _lease_deadline_expired()
                    or not cancel_requested()
                    or not await self._cancel_journaled(request, binding)
                ):
                    raise
                _uncancel_current_task()
                try:
                    latest = await self._observe_latest(invocation, resolved_secrets)
                except CheckpointLineageInDoubt as error:
                    return await self._in_doubt(
                        binding, claim, admitted, reason=error.reason, candidates=error.candidates
                    )
                return await self._settle_cancelled(binding, claim, admitted, plan, latest)
            # Tracing Stage 3 (R1-F2): the turn's usage, capture and points are known before
            # the fence check, so a later failure settles with them.
            observed_usage = runtime_result.usage
            capture = runtime_result.checkpoint
            points = runtime_result.cognition_points
            if plan is not None and capture is None:
                raise CheckpointLineageInDoubt(
                    "a lineage-qualified invocation returned no captured result checkpoint",
                    reason="unclassifiable",
                )
            if self._saved_results is not None and admitted is not None:
                # WI-04: save first. The fence and usage checks then run on the saved record
                # (`_settle_saved_checked`), so no later error can lose or redispatch it.
                completed = runtime_result
                raise _SavedResultReady
            fence = await self._turn_fence(request, binding) if admitted is not None else None
            if fence == "journaled":
                # Tracing Stage 2 (F-S2-9): an immediate cancel reaches the Activity only
                # through its next heartbeat, so a short turn used to finish first and settle
                # `completed` under a persisted fence. A result that lands after the fence is
                # not admitted: the unit settles `cancelled` with what it spent.
                assert admitted is not None
                return await self._settle_fenced_turn(
                    binding, claim, admitted, plan, runtime_result
                )
            if fence == "pending":
                # Tracing Stage 3 (R1-F1): the fence is persisted but its cancel is not
                # journaled (in transit, or rejected by the reducer). The turn may have been
                # ended by the fence, so its output is never settled `completed`: the
                # attempt retries once the cancel lands (and the saga settles `cancelled`).
                raise OperationStopFencePending(
                    "the turn ended under a stop fence whose cancel run control has not "
                    "journaled; retry once the cancel is journaled"
                )
            await self._validate_turn_usage(binding, runtime_result)
            # No durable owner is composed (a non-unit placement or a fixture without the
            # store): the lane settles inline once and a failure fails the attempt.
            await self._settlement_pass(invocation, fenced=False, inline=True)
            settlement = OperationSettlement(
                settlement_id=operation_settlement_id(binding.binding_id),
                binding_id=binding.binding_id,
                status="completed",
                output_text=runtime_result.output_text,
                structured_output=runtime_result.structured_output,
                output_refs=runtime_result.output_refs,
                usage=runtime_result.usage,
                provider_run_id=runtime_result.provider_run_id,
                event_payloads=runtime_result.event_payloads,
                settled_at=datetime.now(UTC),
                checkpoint_transition_id=(transition_id_for(plan) if plan is not None else None),
                result_checkpoint=capture.result_key if capture is not None else None,
            )
        except _SavedResultReady:
            pass
        except CheckpointLineageInDoubt as error:
            # REQ-CP-DA-018: ambiguity is never settled as an ordinary failure, and never
            # re-executed: it becomes a typed incident awaiting `reconcile_unit`.
            if admitted is None:
                raise
            return await self._in_doubt(
                binding, claim, admitted, reason=error.reason, candidates=error.candidates
            )
        except (CheckpointLineageError, OperationStopFencePending):
            raise
        except Exception as error:
            # The settlement keeps only the error type (provider and secret text never
            # persist); an idempotency conflict is Mission Control's own text and names the
            # colliding identity, so it is logged for the operator.
            _LOGGER.warning(
                "operation %s failed before settlement: %s%s",
                binding.binding_id,
                type(error).__name__,
                _failure_detail(error),
            )
            if turns.completed is not None:
                # A later queued turn's admission/materialization can fail after an earlier
                # turn completed. Its actual spend and checkpoint must still settle.
                observed_usage = turns.completed.usage
                capture = turns.completed.checkpoint
                points = turns.completed.cognition_points
            if admitted is not None and not isinstance(error, OperationBudgetViolation):
                ambiguity = await self._post_failure_ambiguity(
                    binding, claim, admitted, error, runtime_invoked=runtime_invoked
                )
                if ambiguity is not None:
                    reason, unsettled = ambiguity
                    return await self._in_doubt(
                        binding,
                        claim,
                        admitted,
                        reason=reason,
                        candidates=_failure_candidates(error),
                        unsettled_effect_ids=unsettled,
                    )
            # RRM-008 (RRM-004 review finding 4): a failed unit with a unique stamped lineage
            # records its latest durable checkpoint as the result checkpoint, so a shared
            # session namespace advances over the partial lineage instead of wedging the
            # next unit as `foreign_descendant`.
            if isinstance(error, RuntimeInvocationFailure):
                latest_capture = error.latest_capture
                if isinstance(latest_capture, CheckpointCapture):
                    capture = latest_capture
                    points = tuple(
                        item
                        for item in error.cognition_points
                        if isinstance(item, CognitionPointObservation)
                    )
            if isinstance(error, RuntimeInvocationFailure) and isinstance(
                error.usage, RuntimeUsage
            ):
                # F-S2-11: the completed calls' spend reaches the budget ledger.
                if turns.completed is None:
                    observed_usage = error.usage
                else:
                    # Queued failure usage is cumulative. Early instrumentation failures
                    # may know less than the preceding successful native turn; never erase it.
                    observed_usage = RuntimeUsage(
                        amounts={
                            dimension: max(
                                observed_usage.amounts.get(dimension, 0),
                                error.usage.amounts.get(dimension, 0),
                            )
                            for dimension in observed_usage.amounts.keys()
                            | error.usage.amounts.keys()
                        },
                        pending_external_amounts={
                            dimension: max(
                                observed_usage.pending_external_amounts.get(dimension, 0),
                                error.usage.pending_external_amounts.get(dimension, 0),
                            )
                            for dimension in observed_usage.pending_external_amounts.keys()
                            | error.usage.pending_external_amounts.keys()
                        },
                    )
            settlement = OperationSettlement(
                settlement_id=operation_settlement_id(binding.binding_id),
                binding_id=binding.binding_id,
                status="failed",
                usage=observed_usage,
                failure_code=(
                    ContextDeliveryBlocked.code
                    if isinstance(error, ContextDeliveryBlocked)
                    else "budget_exceeded"
                    if isinstance(error, OperationBudgetViolation)
                    else OutputSchemaUnsupported.code
                    if isinstance(error, OutputSchemaUnsupported)
                    else "unsupported_runtime_policy"
                    if isinstance(error, UnsupportedRuntimePolicy)
                    else "transient_transport"
                    if isinstance(error, RuntimeInvocationFailure)
                    and error.failure_class == "transient_transport"
                    else "runtime_failed"
                    if runtime_invoked
                    else "preparation_failed"
                ),
                # Provider and secret exception text is deliberately not persisted; a blocked
                # context delivery carries its host-generated reason (codes and handles).
                failure_message=str(error)
                if isinstance(error, ContextDeliveryBlocked)
                else f"{_error_type(error)} at governed operation boundary",
                settled_at=datetime.now(UTC),
                checkpoint_transition_id=(
                    transition_id_for(plan) if plan is not None and capture is not None else None
                ),
                result_checkpoint=capture.result_key if capture is not None else None,
            )
        if completed is not None:
            # WI-04 (OUTPUT-CONTRACTS §4): save the completed provider result before the fence
            # and usage checks and any post-execution assessment, effect or review wait; the
            # saved record then owns the settlement. A crash or error from here on never
            # dispatches this cognition again.
            assert admitted is not None
            saved = await self._save_or_classify(binding, claim, admitted, plan, completed)
            if isinstance(saved, OperationExecutionResult):
                return saved
            return await self._settle_saved_checked(
                request,
                binding,
                claim,
                admitted,
                saved,
                plan=plan,
                invocation=invocation,
                started_at=started_at,
                injected=tuple(turns.delivery_keys),
            )
        report_phase("settling")
        settled = await self._settle(
            binding,
            claim,
            settlement,
            started_at=started_at,
            attempt=attempt,
            admitted=admitted,
            plan=plan if capture is not None else None,
            capture=capture,
            points=points if capture is not None else (),
        )
        await self._mailbox_turn_settled(
            request,
            binding,
            settlement,
            runtime_invoked=runtime_invoked,
            injected=tuple(turns.delivery_keys),
        )
        return settled

    async def _execute_turns(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt | None,
        invocation: RuntimeInvocation,
        resolved_secrets: Mapping[str, str],
        turns: TurnRecord,
    ) -> RuntimeResult:
        """The attempt's turn; with injections composed on a lineage-qualified unit, an
        admitted `interrupt_and_inject` interrupts and replaces it (FT-F2)."""

        lane = self._lane(binding)
        if (
            self._injections is None
            or admitted is None
            or request.runtime_unit is None
            or self._mailbox is None
        ):
            return await lane.execute(invocation, resolved_secrets)

        async def unsettled() -> tuple[str, ...]:
            if self._journal is None or claim is None:
                return ()
            return await self._journal.unsettled_effect_ids(binding, claim)

        initial_target = (
            (
                await self._authority.run_projection(binding.request_scope, binding.run_id)
            ).execution_target
            if isinstance(self._authority, RunProjectionPort)
            else None
        )

        async def before_follow_up(result: RuntimeResult, replay: bool) -> None:
            # Native completion is not operation acceptance. A queued Session Turn must
            # still hold the same authority and reservation, and share its existing cap.
            if isinstance(self._authority, RunProjectionPort):
                while True:
                    run = await self._authority.run_projection(
                        binding.request_scope, binding.run_id
                    )
                    if run.execution_target != initial_target:
                        raise CheckpointLineageError("queued turn macro execution target changed")
                    if run.phase != RunPhase.PAUSED:
                        break
                    await asyncio.sleep(0.1)
            if cancel_requested():
                raise asyncio.CancelledError
            try:
                await self._authority.verify_continuation(request, binding)
            except OperationCancellationPending as error:
                raise OperationStopFencePending(
                    "queued turn awaits governed cancellation"
                ) from error
            fence = await self._turn_fence(request, binding)
            if fence is not None:
                raise OperationStopFencePending("queued turn cannot cross the run stop fence")
            await self._validate_turn_usage(binding, result)
            for dimension in ("model.turns", "tokens.total", "tokens.input", "tokens.output"):
                limit = binding.budget_limits.get(dimension)
                if (
                    not replay
                    and limit is not None
                    and result.usage.amounts.get(dimension, 0) >= limit
                ):
                    raise OperationBudgetViolation("queued turn has no remaining bounded budget")

        return await self._injections.run_turn(
            request=request,
            lane=lane,
            invocation=invocation,
            secrets=resolved_secrets,
            unsettled=unsettled,
            record=turns,
            before_follow_up=before_follow_up,
        )

    async def _mailbox_turn_started(
        self, request: OperationExecutionRequest, binding: OperationExecutionBinding
    ) -> None:
        """FT-F1: the turn carrying delivered mailbox entries starts; they are consumed once
        (a retried attempt of the same bound operation finds them already consumed)."""

        if self._mailbox is None:
            return
        deep = DeepAgentExecutionBinding.carried_by(request)
        await self._mailbox.turn_started(
            request.request_scope,
            request.identity.run_id,
            delivery_key=request.idempotency_key,
            lane_profile=self._lane(binding).describe().lane_profile,
            session_ref=(
                deep.cognitive_session_namespace if deep is not None else request.session_id
            ),
        )

    async def _mailbox_turn_settled(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        settlement: OperationSettlement,
        *,
        runtime_invoked: bool,
        injected: tuple[str, ...] = (),
    ) -> None:
        if self._mailbox is None:
            return
        try:
            for key in injected:
                # FT-F2: the replacement turn settled; the injected Commands complete.
                await self._mailbox.turn_settled(
                    request.request_scope,
                    request.identity.run_id,
                    delivery_key=key,
                    lane_profile=self._lane(binding).describe().lane_profile,
                    succeeded=settlement.status == "completed",
                    turn_ref=settlement.provider_run_id,
                )
            if not runtime_invoked:
                # SPEC-06: a turn that failed before it started returns its entries.
                await self._mailbox.turn_not_started(
                    request.request_scope,
                    request.identity.run_id,
                    delivery_key=request.idempotency_key,
                )
                return
            await self._mailbox.turn_settled(
                request.request_scope,
                request.identity.run_id,
                delivery_key=request.idempotency_key,
                lane_profile=self._lane(binding).describe().lane_profile,
                succeeded=settlement.status == "completed",
                turn_ref=settlement.provider_run_id,
            )
        except Exception:
            # Receipts are evidence of an already settled unit; the settlement stands and the
            # terminal receipts close the Commands if this record is never written.
            _LOGGER.exception(
                "mailbox settlement receipts were not recorded",
                extra={"run_id": request.identity.run_id, "key": request.idempotency_key},
            )

    async def _post_failure_ambiguity(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        error: Exception,
        *,
        runtime_invoked: bool,
    ) -> tuple[InDoubtReason, tuple[str, ...]] | None:
        """REQ-CP-RUN-007 (narrowed): `failed` only without a terminal result and with every
        effect claim of the unit settled; otherwise the disposition is `in_doubt`."""

        terminal_absent = isinstance(error, RuntimeInvocationFailure) and (
            not error.terminal_result_observed
        )
        if isinstance(error, RuntimeInvocationFailure) and error.terminal_result_observed:
            return "terminal_result_after_failure", ()  # candidates travel on the error
        if (
            admitted.deep_binding is not None
            and admitted.admission.prior_dispatch
            and not terminal_absent
        ):
            # An earlier holder dispatched this unit generation and this attempt could not
            # classify the checkpointer: a terminal result is not provably absent.
            return "unclassifiable", ()
        if not runtime_invoked or self._journal is None or claim is None:
            return None
        unsettled = await self._journal.unsettled_effect_ids(binding, claim)
        if unsettled:
            return "unsettled_effect_claims", unsettled
        return None

    async def _settle(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        settlement: OperationSettlement,
        *,
        started_at: datetime,
        attempt: OperationActivityAttempt | None,
        admitted: UnitAttempt | None,
        plan: CheckpointInvocationPlan | None = None,
        capture: CheckpointCapture | None = None,
        expected_run_version: int | None = None,
        points: tuple[CognitionPointObservation, ...] = (),
        points_written_by: PointWriter = "adapter",
        point_parents: Mapping[str, CognitionCoordinate] | None = None,
    ) -> OperationExecutionResult:
        before_authority: ResultManifestObserver | None = None
        if admitted is not None and self._lineage is not None:
            lineage = self._lineage
            unit_attempt = admitted
            settled = settlement
            # K1: the profile the binding names (a Session Lane has no `execute` for
            # `lane_for` to admit; the points carry the lane that folded them).
            lane_profile = lane_profile_for(binding) if points else None
            budget_snapshot = settlement_budget_snapshot(binding, settled)

            async def record_result(
                manifest_ref: str, manifest_digest: str, manifest_size_bytes: int
            ) -> None:
                # REQ-CP-EXEC-014: the result manifest is fixed by the current fence holder
                # (with its checkpoint transition, by CAS on the namespace head) before any
                # authority settlement, and its cognition points land in the same
                # transaction (TR-D6). A superseded holder's write is rejected here.
                await lineage.record_result(
                    unit_attempt,
                    binding_id=binding.binding_id,
                    settlement_id=settled.settlement_id,
                    status=settled.status,
                    result_manifest_ref=manifest_ref,
                    result_manifest_digest=manifest_digest,
                    result_manifest_size_bytes=manifest_size_bytes,
                    plan=plan,
                    capture=capture,
                    points=points,
                    lane_profile=lane_profile,
                    budget_snapshot=budget_snapshot,
                    written_by=points_written_by,
                    parents=point_parents,
                )

            before_authority = record_result
        technical_attempt = attempt.attempt if attempt is not None else 1
        if self._journal is not None and claim is not None:
            extra = (
                {"expected_run_version": expected_run_version}
                if expected_run_version is not None
                else {}
            )
            settlement = await self._journal.settle(
                binding,
                claim,
                settlement,
                started_at=started_at,
                technical_attempt=technical_attempt,
                before_authority=before_authority,
                **extra,
            )
        else:
            if before_authority is not None:
                manifest = settlement_result_manifest(settlement)
                await before_authority(
                    f"operation-settlement:{settlement.settlement_id}",
                    f"sha256:{hashlib.sha256(manifest).hexdigest()}",
                    len(manifest),
                )
            settlement = await self._bindings.settle(
                settlement,
                request_scope=binding.request_scope,
            )
        await self._complete_post_effects(binding, settlement)
        report_phase("settled")
        return _public_result(binding, settlement)

    # --- WI-04: saved provider results and their durable settlement ---------------------------

    async def _saved_result(
        self, binding: OperationExecutionBinding
    ) -> InvocationSettlement | None:
        if self._saved_results is None:
            return None
        return await self._saved_results.get(binding.request_scope, binding.binding_id)

    async def _save_or_classify(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        plan: CheckpointInvocationPlan | None,
        result: RuntimeResult,
    ) -> InvocationSettlement | OperationExecutionResult:
        """Save the completed result, or classify why it cannot be saved (typed, no retry).

        Too large: the unit settles ``failed`` (``saved_result_too_large``) with its usage,
        result checkpoint and points retained. Another saved result for this binding: the unit
        parks ``in_doubt`` (``unrecoverable_result_manifest``) for operator reconciliation.
        """

        assert self._saved_results is not None
        try:
            return await self._saved_results.save(
                InvocationSettlement.save(
                    request_scope=binding.request_scope,
                    run_id=binding.run_id,
                    binding_id=binding.binding_id,
                    operation_ref=binding.operation_id,
                    operation_attempt=binding.operation_attempt,
                    unit_key=admitted.unit.unit_key,
                    execution_generation=admitted.execution_generation,
                    result=result,
                    # The one durable reconciler of the wait: this unit's operation workflow.
                    recovery_owner=admitted.attempt.workflow_id,
                    claim_fence=admitted.fence,
                    at=self._settlement_clock(),
                )
            )
        except IdempotencyConflict:
            _LOGGER.warning("operation %s saved another provider result", binding.binding_id)
            return await self._in_doubt(
                binding, claim, admitted, reason="unrecoverable_result_manifest"
            )
        except SavedResultTooLarge as error:
            _LOGGER.warning("operation %s: %s", binding.binding_id, error)
            capture = result.checkpoint
            return await self._settle(
                binding,
                claim,
                OperationSettlement(
                    settlement_id=operation_settlement_id(binding.binding_id),
                    binding_id=binding.binding_id,
                    status="failed",
                    usage=result.usage,
                    provider_run_id=result.provider_run_id,
                    failure_code="saved_result_too_large",
                    failure_message="the completed provider result exceeds the saved-result bound",
                    settled_at=datetime.now(UTC),
                    checkpoint_transition_id=(
                        transition_id_for(plan)
                        if plan is not None and capture is not None
                        else None
                    ),
                    result_checkpoint=capture.result_key if capture is not None else None,
                ),
                started_at=datetime.now(UTC),
                attempt=admitted.attempt,
                admitted=admitted,
                plan=plan if capture is not None else None,
                capture=capture,
                points=result.cognition_points if capture is not None else (),
            )

    async def _settlement_pass(
        self, invocation: RuntimeInvocation, *, fenced: bool, inline: bool = False
    ) -> SettlementOutcome:
        """One post-execution settlement pass of the lane; never dispatches cognition.

        A failing pass is a wait (``settlement_unavailable``), not a cognition failure; only
        the inline (store-less) path lets it fail the attempt as before.
        """

        lane = self._lane(invocation.binding)
        if not isinstance(lane, SettlesInvocation):
            return SettlementOutcome.done()
        try:
            return await lane.settle_invocation(invocation, fenced=fenced)
        except Exception as error:
            if inline:
                raise
            outcome = SettlementOutcome.unavailable(error)
            # W1 D20: the typed code, reason and bounded issues (what a KS refusal refused).
            _LOGGER.warning(
                "settlement of the saved result of %s did not complete: %s %s",
                invocation.binding.binding_id,
                type(error).__name__,
                {key: value for key, value in outcome.detail.items() if key != "error_type"},
                exc_info=error,
            )
            return outcome

    async def _advance_saved(
        self,
        record: InvocationSettlement,
        outcome: SettlementOutcome,
        admitted: UnitAttempt,
        *,
        fenced: bool,
        resumed_by: str | None = None,
    ) -> InvocationSettlement:
        assert self._saved_results is not None
        successor = record.advanced(
            outcome,
            claim_fence=admitted.fence,
            at=self._settlement_clock(),
            recovery_owner=admitted.attempt.workflow_id,
            stop_fence="cancelled" if fenced else None,
            resumed_by=resumed_by,
        )
        try:
            return await self._saved_results.advance(successor, expected_version=record.version)
        except StaleSettlementHolder as error:
            # A takeover fenced this holder out (even before the new holder wrote): stand down.
            raise OperationLeaseExpired(
                "a newer claim fence holds the unit; this holder cannot advance its saved result"
            ) from error
        except SavedSettlementConflict as error:
            current = await self._saved_results.get(record.request_scope, record.binding_id)
            if current is not None and current.settled:
                return current
            raise OperationExecutionInProgress(
                "another holder advanced the saved result; retry to read its settlement"
            ) from error

    async def _abandon_saved(
        self, saved: InvocationSettlement | None, admitted: UnitAttempt, decision_id: str
    ) -> None:
        """An operator abandoned the unit: its saved result's settlement ends with it."""

        if saved is None or saved.settled:
            return
        await self._advance_saved(
            saved,
            SettlementOutcome.done(detail={"abandoned_by_decision": decision_id}),
            admitted,
            fenced=False,
        )

    async def _settle_abandoned_saved(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        saved: InvocationSettlement,
        decision_id: str,
    ) -> OperationExecutionResult:
        """An operator abandoned a unit whose cognition completed: it settles ``failed``
        (``in_doubt_abandoned``) charging the saved result's known spend. The accepted
        abandonment already closed the unit's lineage (no in-flight invocation remains), so no
        checkpoint transition is written; the saved checkpoint key travels as evidence."""

        await self._abandon_saved(saved, admitted, decision_id)
        result = saved.saved_result
        return await self._settle(
            binding,
            claim,
            OperationSettlement(
                settlement_id=operation_settlement_id(binding.binding_id),
                binding_id=binding.binding_id,
                status="failed",
                usage=result.usage,
                provider_run_id=result.provider_run_id,
                event_payloads=(_abandoned_saved_evidence(saved, decision_id),),
                failure_code="in_doubt_abandoned",
                failure_message="in_doubt unit abandoned by operator reconciliation",
                settled_at=datetime.now(UTC),
            ),
            started_at=datetime.now(UTC),
            attempt=admitted.attempt,
            admitted=admitted,
        )

    async def _resume_saved(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        lineage: CheckpointLineageService,
        saved: InvocationSettlement,
        *,
        fenced: bool = False,
        resumed_by: str | None = None,
    ) -> OperationExecutionResult:
        """A retry, restart, cancellation or operator decision reaches a saved result."""

        plan = lineage.plan(admitted)
        invocation = await self._invocation(request, binding, plan)
        if fenced:
            return await self._settle_saved(
                request,
                binding,
                claim,
                admitted,
                saved,
                plan=plan,
                invocation=invocation,
                started_at=datetime.now(UTC),
                fenced=True,
                resumed_by=resumed_by,
            )
        return await self._settle_saved_checked(
            request,
            binding,
            claim,
            admitted,
            saved,
            plan=plan,
            invocation=invocation,
            started_at=datetime.now(UTC),
            resumed_by=resumed_by,
        )

    async def _settle_saved_checked(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        saved: InvocationSettlement,
        *,
        plan: CheckpointInvocationPlan | None,
        invocation: RuntimeInvocation,
        started_at: datetime,
        injected: tuple[str, ...] = (),
        resumed_by: str | None = None,
    ) -> OperationExecutionResult:
        """The stop-fence check on a saved result (it runs after the save, never before).

        A journaled fence settles the saved result through the fenced path, shielded against
        the in-flight cancel (Tracing Stage 3, R1-F8); a pending fence retries until the cancel
        is journaled; a saved result already settled or fenced is settled as recorded.
        """

        if not saved.settled and saved.stop_fence != "cancelled":
            fence = await self._turn_fence(request, binding)
            if fence == "pending":
                raise OperationStopFencePending(
                    "the turn ended under a stop fence whose cancel run control has not "
                    "journaled; retry once the cancel is journaled"
                )
            if fence == "journaled":
                return await self._shielded(
                    lambda: self._settle_saved(
                        request,
                        binding,
                        claim,
                        admitted,
                        saved,
                        plan=plan,
                        invocation=invocation,
                        started_at=started_at,
                        fenced=True,
                        injected=injected,
                        resumed_by=resumed_by,
                    )
                )
        return await self._settle_saved(
            request,
            binding,
            claim,
            admitted,
            saved,
            plan=plan,
            invocation=invocation,
            started_at=started_at,
            injected=injected,
            resumed_by=resumed_by,
        )

    async def _settle_saved(
        self,
        request: OperationExecutionRequest,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        saved: InvocationSettlement,
        *,
        plan: CheckpointInvocationPlan | None,
        invocation: RuntimeInvocation,
        started_at: datetime,
        fenced: bool = False,
        injected: tuple[str, ...] = (),
        resumed_by: str | None = None,
    ) -> OperationExecutionResult:
        """Settle a saved result: one settlement pass, then the operation settlement.

        A pass that leaves a review or effect pending records the wait (pending refs, next
        action, owner) and returns ``waiting``; the operation workflow waits durably and runs
        the boundary again, which lands here with the same saved result. ``fenced`` (the
        cancellation saga): no new evaluation starts and a pending review no longer holds the
        result, but an unresolved effect or an unavailable pass still waits, so committed work
        is reconciled before the unit settles ``cancelled`` with its completed outcome and
        usage retained. A usage over the bound settles ``failed`` (``budget_exceeded``) from
        the saved record, after the same evaluation-free reconciliation. An effect wait older
        than the configured deadline (from the start of the effect wait, restarted once per
        operator decision ``resumed_by``) becomes an operator incident; a review wait emits one
        durable alarm per configured interval.
        """

        report_phase("settling")
        record = saved
        fenced = fenced or record.stop_fence == "cancelled"
        refusal: str | None = None
        refusal_message = "runtime usage exceeds immutable operation budget"
        try:
            await self._validate_turn_usage(binding, record.saved_result)
        except OperationBudgetViolation as violation:
            # Mission Control's own text (dimension names only), never provider text.
            refusal, refusal_message = "budget_exceeded", str(violation)
        if not record.settled:
            outcome = await self._settlement_pass(invocation, fenced=fenced or refusal is not None)
            if (
                (fenced or refusal is not None)
                and outcome.state == "waiting"
                and outcome.reason is WaitReason.REVIEW_PENDING
            ):
                # No evaluation holds a fenced or refused result; committed work still does.
                outcome = SettlementOutcome.done(
                    fulfillment_refs=outcome.fulfillment_refs,
                    finalization_ref=outcome.finalization_ref,
                    detail={**outcome.detail, "fenced_reviews": list(outcome.pending_reviews)},
                )
            record = await self._advance_saved(
                record, outcome, admitted, fenced=fenced, resumed_by=resumed_by
            )
            if not record.settled:
                return await self._wait_or_escalate(binding, claim, admitted, record)
        children: tuple[AsyncChildCancellationRecord, ...] = ()
        if fenced:
            await self._fence_milestone(binding, "provider_acknowledged")
            children = await self._cancel_children(binding, started_at)
        result = record.saved_result
        capture = result.checkpoint
        cancelled = record.stop_fence == "cancelled"
        assert record.settled_at is not None
        status: Literal["completed", "failed", "cancelled"] = (
            "cancelled" if cancelled else "failed" if refusal is not None else "completed"
        )
        settlement = OperationSettlement(
            settlement_id=operation_settlement_id(binding.binding_id),
            binding_id=binding.binding_id,
            status=status,
            output_text=result.output_text,
            structured_output=result.structured_output,
            output_refs=result.output_refs,
            usage=result.usage,
            provider_run_id=result.provider_run_id,
            event_payloads=(
                *result.event_payloads,
                record.evidence(),
                *(
                    ({"cancelled_async_children": [c.model_dump(mode="json") for c in children]},)
                    if children
                    else ()
                ),
            ),
            failure_code="cancelled" if cancelled else refusal,
            failure_message=(
                "operation cancelled after its cognition completed; the saved result is retained"
                if cancelled
                else refusal_message
                if refusal is not None
                else None
            ),
            # The record's own time: a restarted settlement rebuilds the same manifest bytes.
            settled_at=record.settled_at,
            checkpoint_transition_id=(
                transition_id_for(plan) if plan is not None and capture is not None else None
            ),
            result_checkpoint=capture.result_key if capture is not None else None,
        )
        settled = await self._settle(
            binding,
            claim,
            settlement,
            started_at=min(started_at, record.settled_at),
            attempt=admitted.attempt,
            admitted=admitted,
            plan=plan if capture is not None else None,
            capture=capture,
            points=result.cognition_points if capture is not None else (),
        )
        if fenced:
            await self._fence_milestone(binding, "settled")
        await self._mailbox_turn_settled(
            request, binding, settlement, runtime_invoked=True, injected=injected
        )
        return settled

    async def _wait_or_escalate(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        record: InvocationSettlement,
    ) -> OperationExecutionResult:
        """A waiting saved result: the typed wait, an operator incident once an effect wait
        outlives its deadline, and a durable alarm per interval while a review holds it."""

        assert self._saved_results is not None
        now = self._settlement_clock()
        anchor = record.effect_wait_since
        if (
            record.reason is WaitReason.EFFECT_PENDING
            and anchor is not None
            and now - anchor >= self._effect_wait_deadline
        ):
            await self._saved_results.record_event(
                record,
                SettlementEvent(
                    settlement_id=record.settlement_id,
                    kind="effect_deadline",
                    sequence=record.waits,
                    occurred_at=now,
                    detail={"pending_effects": list(record.pending_effects)},
                ),
            )
            return await self._in_doubt(
                binding,
                claim,
                admitted,
                reason="unsettled_effect_claims",
                unsettled_effect_ids=record.pending_effects,
            )
        interval = self._review_alarm_interval.total_seconds()
        if record.reason is WaitReason.REVIEW_PENDING and interval > 0:
            elapsed = (now - record.saved_at).total_seconds()
            if elapsed >= interval:
                await self._saved_results.record_event(
                    record,
                    SettlementEvent(
                        settlement_id=record.settlement_id,
                        kind="review_alarm",
                        sequence=int(elapsed // interval),
                        occurred_at=now,
                        detail={
                            "pending_reviews": list(record.pending_reviews),
                            "waiting_seconds": int(elapsed),
                        },
                    ),
                )
        return _waiting_result(binding, record, cap=int(self._settlement_wait_cap.total_seconds()))

    async def _shielded(
        self, body: Callable[[], Awaitable[OperationExecutionResult]]
    ) -> OperationExecutionResult:
        """Run a settlement while an immediate cancel is in flight (Tracing Stage 3, R1-F8).

        A requested Temporal cancel is swallowed (as the heartbeat path does with
        `_uncancel_current_task`) and the settlement is awaited to its end. Any other
        cancellation (the lease deadline, a worker shutdown) stops it as before.
        """

        settlement = asyncio.ensure_future(body())
        while True:
            try:
                return await asyncio.shield(settlement)
            except asyncio.CancelledError:
                if settlement.done() or _lease_deadline_expired() or not cancel_requested():
                    settlement.cancel()
                    raise
                _uncancel_current_task()

    async def _settle_recorded(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        recorded: UnitResultObservation,
    ) -> OperationExecutionResult:
        """`observed_unsettled`: settle exactly the recorded manifest; no provider work."""

        if self._journal is None or claim is None:
            return await self._in_doubt(
                binding, claim, admitted, reason="unrecoverable_result_manifest"
            )
        settlement = await self._journal.load_result_manifest(
            binding,
            manifest_ref=recorded.result_manifest_ref,
            manifest_digest=recorded.result_manifest_digest,
            manifest_size_bytes=recorded.result_manifest_size_bytes,
        )
        if (
            settlement.settlement_id != recorded.settlement_id
            or settlement.status != recorded.status
            or settlement.checkpoint_transition_id != recorded.checkpoint_transition_id
        ):
            return await self._in_doubt(
                binding, claim, admitted, reason="unrecoverable_result_manifest"
            )

        async def verify_recorded(
            manifest_ref: str, manifest_digest: str, manifest_size_bytes: int
        ) -> None:
            if (manifest_ref, manifest_digest, manifest_size_bytes) != (
                recorded.result_manifest_ref,
                recorded.result_manifest_digest,
                recorded.result_manifest_size_bytes,
            ):
                raise CheckpointLineageConflict(
                    "the recovered settlement manifest differs from the recorded result"
                )

        settled = await self._journal.settle(
            binding,
            claim,
            settlement,
            started_at=min(datetime.now(UTC), settlement.settled_at),
            technical_attempt=admitted.attempt.attempt,
            before_authority=verify_recorded,
        )
        await self._complete_post_effects(binding, settled)
        return _public_result(binding, settled)

    async def _settle_reused(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        reused: ReusedSourceResult,
    ) -> OperationExecutionResult:
        source = reused.source_settlement
        if self._reused_outputs is not None:
            # F1-G4: under output contracts the source's outputs are accepted obligation
            # revisions of the source run (`output_refs` is empty); they are carried, still
            # accepted, into the derived run before the unit settles, so its consumers resolve.
            # Any other error is transient: the Activity retries and the carry is idempotent.
            try:
                await self._reused_outputs.carry(binding, reused.ref)
            except ForkOutputsNotCarried as error:
                return await self._settle(
                    binding,
                    claim,
                    _failed_settlement(binding, failure_code=error.code, message=error.message),
                    started_at=datetime.now(UTC),
                    attempt=admitted.attempt,
                    admitted=admitted,
                )
        settled_at = datetime.now(UTC)
        settlement = OperationSettlement(
            settlement_id=stable_id("operation-settlement", binding.binding_id),
            binding_id=binding.binding_id,
            status="completed",
            output_text=source.output_text,
            structured_output=source.structured_output,
            output_refs=source.output_refs,
            settled_at=settled_at,
            reused_result=reused.ref,
        )
        # P5.5 (`reused_from`): one point per reused unit, written by the fork seed in the
        # settlement transaction: the source unit's result point is its parent and its key
        # (`channel_facts.source_result`); nothing of the source's cognition is copied.
        points: tuple[CognitionPointObservation, ...] = ()
        parents: dict[str, CognitionCoordinate] | None = None
        source_point = await self._source_result_point(binding, reused)
        if source_point is not None:
            points = (
                CognitionPointObservation(
                    point=source_point.coordinate.point,
                    source="fork",
                    roles=("reused",),
                    ordinal=source_point.ordinal,
                    message_count=source_point.message_count,
                    channel_facts={
                        "source_result": {
                            "run_id": source_point.coordinate.run_id,
                            "unit_key": source_point.coordinate.unit_key,
                            "execution_generation": source_point.coordinate.execution_generation,
                            "point_id": source_point.point_id,
                            "point": source_point.coordinate.point.model_dump(mode="json"),
                            "fork_request_id": reused.ref.fork_request_id,
                        }
                    },
                    files_digest=source_point.files_digest,
                    seedable=source_point.seedable,
                ),
            )
            parents = {source_point.coordinate.locator: source_point.coordinate}
        return await self._settle(
            binding,
            claim,
            settlement,
            started_at=settled_at,
            attempt=admitted.attempt,
            admitted=admitted,
            points=points,
            points_written_by="fork_seed",
            point_parents=parents,
        )

    async def _source_result_point(
        self, binding: OperationExecutionBinding, reused: ReusedSourceResult
    ) -> CognitionPointRecord | None:
        """The source unit's result point in the index (by the source run, kind and the
        source settlement's result checkpoint); None when the index holds no such row."""

        points = self._lineage.points if self._lineage is not None else None
        result_key = reused.source_settlement.result_checkpoint
        if points is None or result_key is None:
            return None
        return await points.find_point(
            binding.request_scope,
            reused.ref.source_run_id,
            kind="checkpoint",
            locator=result_key.checkpoint_id,
        )

    async def _reconciliation(
        self,
        binding: OperationExecutionBinding,
        admitted: UnitAttempt,
        incident: UnitReconciliationIncident,
    ) -> UnitReconciliationDecision | None:
        """The accepted operator decision for an in_doubt unit generation, if any."""

        if self._journal is not None:
            decision = await self._journal.get_unit_reconciliation(
                binding,
                unit_key=admitted.unit.unit_key,
                execution_generation=admitted.execution_generation,
                incident_id=incident.incident_id,
            )
            if decision is not None:
                return decision
        if incident.status == "resolved":
            assert incident.decision is not None and incident.decision_id is not None
            return UnitReconciliationDecision(
                decision_id=incident.decision_id,
                unit_key=incident.unit_key,
                execution_generation=incident.execution_generation,
                incident_id=incident.incident_id,
                decision=incident.decision,
                accepted_checkpoint=incident.accepted_checkpoint,
                actor_id="recorded-incident",
                decided_at=incident.recorded_at,
            )
        return None

    async def _in_doubt(
        self,
        binding: OperationExecutionBinding,
        claim: OperationEffectClaim | None,
        admitted: UnitAttempt,
        *,
        reason: InDoubtReason,
        candidates: tuple[QualifiedCheckpointKey, ...] = (),
        unsettled_effect_ids: tuple[str, ...] = (),
    ) -> OperationExecutionResult:
        """REQ-CP-DA-018 / REQ-CP-RUN-007: a typed incident; no invocation; park the unit."""

        assert self._lineage is not None
        incident = await self._lineage.open_incident(
            admitted,
            binding=binding,
            reason=reason,
            candidates=candidates,
            unsettled_effect_ids=unsettled_effect_ids,
        )
        if self._journal is not None and claim is not None:
            await self._journal.record_in_doubt(binding, claim, incident)
        return _unsettled_result(
            binding,
            failure_code=incident.reason,
            message="runtime unit is in_doubt and awaits operator reconcile_unit",
            incident_id=incident.incident_id,
        )

    async def _complete_post_effects(
        self,
        binding: OperationExecutionBinding,
        settlement: OperationSettlement,
    ) -> None:
        if self._journal is not None:
            return
        for index, payload in enumerate(settlement.event_payloads):
            await self._events.publish(
                event_key=f"{binding.side_effect_key}:event:{index}",
                binding_id=binding.binding_id,
                payload=payload,
            )
        await self._budget.reconcile(
            binding=binding,
            settlement_id=settlement.settlement_id,
            usage=settlement.usage,
            budget_violation=settlement.failure_code == "budget_exceeded",
        )

    async def _get_settlement(
        self,
        binding: OperationExecutionBinding,
    ) -> OperationSettlement | None:
        if self._journal is not None:
            return await self._journal.get_settlement(binding)
        return await self._bindings.get_settlement(
            binding.binding_id,
            request_scope=binding.request_scope,
        )

    @staticmethod
    def _validate_policy_support(request: OperationExecutionRequest) -> None:
        for unsupported in request.unsupported_policies:
            if unsupported.required:
                raise ValueError(f"required runtime policy is unsupported: {unsupported.policy}")
            if unsupported.authored_degradation is None:
                raise ValueError(
                    f"unsupported runtime policy lacks authored degradation: {unsupported.policy}"
                )


class LaneSessionAdmission:
    """An admitted protocol-lane attempt: its binding, or its settled result."""

    __slots__ = ("binding", "settled")

    def __init__(
        self, binding: OperationExecutionBinding, settled: OperationExecutionResult | None
    ) -> None:
        self.binding = binding
        self.settled = settled


_LANE_STATUS: dict[str, Literal["completed", "failed", "cancelled"]] = {
    "finished": "completed",
    "error": "failed",
    "expired": "failed",
    "cancelled": "cancelled",
}


def lane_usage_amounts(
    binding: OperationExecutionBinding,
    facts: ClosingFacts,
    run_dimensions: frozenset[str] = frozenset(),
) -> dict[str, int]:
    """The token amounts a Session Lane settlement charges (MP-20).

    Exactly the settled turn's closing usage as the lane reports it (`settled` or
    `estimated`): provider-inclusive totals (subagent work the provider already counts in
    the turn's usage) are charged once and never summed with subordinate frames. `unknown`
    usage charges nothing: the dimension stays absent, never zero, never invented. A
    dimension is charged when the unit's reservation bounds it (validated against that
    bound) or the run's envelope declares it (`run_dimensions`)."""

    if facts.usage.disposition == "unknown":
        return {}
    amounts = {
        "tokens.input": facts.usage.input_tokens,
        "tokens.output": facts.usage.output_tokens,
        "tokens.total": facts.usage.total_tokens,
    }
    return {
        dimension: amount
        for dimension, amount in amounts.items()
        if dimension in binding.budget_limits or dimension in run_dimensions
    }


def lane_final_text(
    facts: ClosingFacts, final_text: str | None
) -> tuple[str | None, tuple[dict[str, object], ...]]:
    """The full final assistant text a Completion Candidate may be parsed from, bounded by
    `MAX_COMPLETION_CANDIDATE_CHARS`; never a truncated excerpt.

    The lane's own final text wins. Without it, the closing facts' text is used only when it
    provably is the whole text (shorter than the excerpt cap). A text over the bound, or an
    excerpt at the cap, yields no candidate (fail closed, as an unparsable answer does) with a
    provenance warning when it looked like a JSON object."""

    if final_text is not None:
        if len(final_text) <= MAX_COMPLETION_CANDIDATE_CHARS:
            return final_text, ()
        reason, size = "completion_candidate_too_large", len(final_text)
        looked_like_json = final_text.lstrip().startswith("{")
    else:
        excerpt = facts.result_excerpt
        if len(excerpt) < MAX_EXCERPT_CHARS:
            return excerpt, ()
        reason, size = "completion_candidate_truncated", len(excerpt)
        looked_like_json = excerpt.lstrip().startswith("{")
    if not looked_like_json:
        return None, ()
    return None, (
        {
            "kind": "provenance",
            "reason": reason,
            "final_text_chars": size,
            "bound_chars": MAX_COMPLETION_CANDIDATE_CHARS,
        },
    )


def _lane_settlement(
    binding: OperationExecutionBinding,
    facts: ClosingFacts,
    *,
    native_turn_ref: str | None,
    cancelled_by_command: bool = True,
    final_text: str | None = None,
    run_dimensions: frozenset[str] = frozenset(),
    settle_cursor_cost: bool = False,
) -> OperationSettlement:
    status = _LANE_STATUS[facts.native_status]
    charged = lane_usage_amounts(binding, facts, run_dimensions)
    pending: dict[str, int] = {}
    currency = "currency.estimated_micros"
    reserved = binding.budget_limits.get(currency, 0)
    if settle_cursor_cost and reserved > 0:
        if facts.cost_disposition == "settled" and facts.usage.cost_micros_usd is not None:
            charged[currency] = facts.usage.cost_micros_usd
        else:
            # Keep the admitted currency liability until attributable provider billing
            # arrives. Unknown usage is never an invented zero or a released reservation.
            pending[currency] = reserved
    failure_code: str | None = None
    if facts.native_status == "finished" and facts.missing_outputs:
        # FT-G4: a native `finished` without the declared outputs is not acceptance
        # (`not_accepted(outputs_missing)`, after the one follow-up turn the lane allowed).
        status = "failed"
        failure_code = "outputs_missing"
    elif facts.native_status == "expired":
        failure_code = "timeout"
    elif facts.native_status == "error":
        # MO-16: a session the launch policy refused to start never reached the provider.
        failure_code = (
            facts.error_code
            if facts.error_code in {"capacity", ENVIRONMENT_NOT_READY}
            else "provider_error"
        )
    elif facts.native_status == "cancelled" and not cancelled_by_command:
        # SPEC-07 section 8: a provider cancel no command caused is an infrastructure failure.
        status = "failed"
        failure_code = "infrastructure"
    elif facts.native_status == "cancelled":
        failure_code = "cancelled"
    refs = tuple(
        dict.fromkeys(
            (
                *facts.output_refs,
                *((facts.patch_ref,) if facts.patch_ref else ()),
                *((facts.result_text_ref,) if facts.result_text_ref else ()),
            )
        )
    )
    structured: dict[str, object] | None = None
    warnings: tuple[dict[str, object], ...] = ()
    if status == "completed":
        text, warnings = lane_final_text(facts, final_text)
        if text is not None:
            structured, warnings = lane_completion_candidate(text, refs)
    event_payload: dict[str, object] = {"lane_closing_facts": facts.model_dump(mode="json")}
    if warnings:
        event_payload["provenance_warnings"] = list(warnings)
    return OperationSettlement(
        settlement_id=operation_settlement_id(binding.binding_id),
        binding_id=binding.binding_id,
        status=status,
        output_text=facts.result_excerpt,
        structured_output=structured,
        output_refs=refs,
        usage=RuntimeUsage(amounts=charged, pending_external_amounts=pending),
        provider_run_id=native_turn_ref,
        event_payloads=(event_payload,),
        failure_code=failure_code,
        failure_message=(
            None
            if failure_code is None
            else (
                "declared outputs were not registered: " + ", ".join(facts.missing_outputs)[:900]
                if failure_code == "outputs_missing"
                else facts.error_message
                if failure_code == ENVIRONMENT_NOT_READY and facts.error_message
                else f"lane reported {facts.native_status} at governed operation boundary"
            )
        ),
        settled_at=datetime.now(UTC),
    )


def lane_completion_candidate(
    final_text: str, registered_refs: tuple[str, ...]
) -> tuple[dict[str, object] | None, tuple[dict[str, object], ...]]:
    """MP-20: a Session Lane's Completion Candidate, read exactly as the Deep Agents lane reads
    its final answer (`adapters/deep_agents/adapter._structured_output`): the final assistant
    text when it is one JSON object, else no structured output.

    The family reads it as the operation's typed result (Stage Graph `obligation_refs` and
    outputs, the GoalDirected executor/verifier observation). A lane agent cannot know the refs
    its files are registered under (custody happens at `end_session`), so a candidate that
    names `output_refs` gets exactly the attempt's registered workspace candidates (FT-B2
    `drop_unregistered`); every emitted ref that is not one of them is dropped with a
    provenance warning. A candidate without the key is left as written (a verifier observation
    declares no outputs). Patch, snapshot and transcript refs stay on the settlement's custody
    refs, never on the candidate.
    """

    text = final_text.strip()
    if not text.startswith("{"):
        return None, ()
    try:
        decoded = json.loads(text)
    except ValueError:
        return None, ()
    if not isinstance(decoded, dict):
        return None, ()
    if "output_refs" not in decoded:
        return decoded, ()
    registered = tuple(ref for ref in registered_refs if parse_workspace_candidate_ref(ref))
    emitted = decoded.get("output_refs", ())
    values = emitted if isinstance(emitted, list | tuple) else (emitted,)
    warnings: tuple[dict[str, object], ...] = tuple(
        {
            "kind": "provenance",
            "dropped_output_ref": str(value),
            "reason": "not_registered_by_this_attempt",
        }
        for value in values
        if value is not None and str(value) not in registered
    )
    return {**decoded, "output_refs": list(registered)}, warnings


class InMemoryOperationBindingRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._bindings: dict[str, OperationExecutionBinding] = {}
        self._settlements: dict[str, OperationSettlement] = {}
        self._claims: dict[str, str] = {}

    async def get_binding(
        self,
        semantic_attempt_key: str,
        *,
        request_scope: str | None = None,
    ) -> OperationExecutionBinding | None:
        binding = self._bindings.get(semantic_attempt_key)
        if (
            binding is not None
            and request_scope is not None
            and binding.request_scope != request_scope
        ):
            return None
        return deepcopy(binding)

    async def get_binding_by_id(
        self,
        binding_id: str,
        *,
        request_scope: str | None = None,
    ) -> OperationExecutionBinding | None:
        binding = next(
            (item for item in self._bindings.values() if item.binding_id == binding_id),
            None,
        )
        if (
            binding is not None
            and request_scope is not None
            and binding.request_scope != request_scope
        ):
            return None
        return deepcopy(binding)

    async def create_binding(
        self,
        binding: OperationExecutionBinding,
        *,
        request_scope: str | None = None,
    ) -> OperationExecutionBinding:
        if request_scope is not None and binding.request_scope != request_scope:
            raise ValueError("operation binding write cannot cross request scope")
        async with self._lock:
            prior = self._bindings.get(binding.semantic_attempt_key)
            if prior is not None:
                if prior.request_fingerprint != binding.request_fingerprint:
                    raise IdempotencyConflict(
                        "semantic operation binding has a conflicting fingerprint"
                    )
                return deepcopy(prior)
            self._bindings[binding.semantic_attempt_key] = deepcopy(binding)
            return deepcopy(binding)

    async def get_settlement(
        self,
        binding_id: str,
        *,
        request_scope: str | None = None,
    ) -> OperationSettlement | None:
        if request_scope is not None:
            binding = next(
                (item for item in self._bindings.values() if item.binding_id == binding_id),
                None,
            )
            if binding is None or binding.request_scope != request_scope:
                return None
        return deepcopy(self._settlements.get(binding_id))

    async def claim_execution(self, binding: OperationExecutionBinding) -> bool:
        async with self._lock:
            prior = self._claims.get(binding.side_effect_key)
            if prior is not None:
                if prior != binding.binding_id:
                    raise IdempotencyConflict(
                        "operation side-effect key belongs to another binding"
                    )
                return False
            self._claims[binding.side_effect_key] = binding.binding_id
            return True

    async def settle(
        self,
        settlement: OperationSettlement,
        *,
        request_scope: str | None = None,
    ) -> OperationSettlement:
        if request_scope is not None:
            binding = next(
                (
                    item
                    for item in self._bindings.values()
                    if item.binding_id == settlement.binding_id
                ),
                None,
            )
            if binding is None or binding.request_scope != request_scope:
                raise ValueError("operation settlement cannot cross request scope")
        async with self._lock:
            prior = self._settlements.get(settlement.binding_id)
            if prior is not None:
                if prior != settlement:
                    # Settlement identity is stable. Provider retries must return the same
                    # observable result and usage for the semantic side-effect key.
                    comparable_prior = prior.model_copy(
                        update={"settled_at": settlement.settled_at}
                    )
                    if comparable_prior != settlement:
                        raise IdempotencyConflict(
                            "operation settlement conflicts with its prior result"
                        )
                return deepcopy(prior)
            self._settlements[settlement.binding_id] = deepcopy(settlement)
            return deepcopy(settlement)


def bind_operation_execution_request(
    request: OperationExecutionRequest,
) -> OperationExecutionBinding:
    """Create the immutable OEB document without invoking its provider side effect."""

    fingerprint = contract_fingerprint(request, exclude={"requested_at"})
    return _binding_for(request, fingerprint)


def _binding_for(request: OperationExecutionRequest, fingerprint: str) -> OperationExecutionBinding:
    binding_id = stable_id(
        "operation-binding",
        f"{request.request_scope}:{request.identity.semantic_key}",
    )
    return OperationExecutionBinding(
        binding_id=binding_id,
        semantic_attempt_key=request.identity.semantic_key,
        request_fingerprint=fingerprint,
        request_scope=request.request_scope,
        run_id=request.identity.run_id,
        operation_id=request.identity.operation_id,
        operation_attempt=request.identity.operation_attempt,
        prior_binding_id=request.prior_binding_id,
        effective_configuration_digest=request.effective_configuration_digest,
        run_control_revision=request.run_control_revision,
        operation_contract_ref=request.operation_contract_ref,
        prompt_sources=tuple(
            (
                segment.source_ref,
                segment.source_revision,
                segment.trust_class,
                segment.rendered_digest,
            )
            for segment in request.prompt_segments
        ),
        model_policy=request.model_policy,
        tools=request.tools,
        mcp_servers=request.mcp_servers,
        skills=request.skills,
        plugins=request.plugins,
        output_schema=request.output_schema,
        guardrails=request.guardrails,
        delegations=request.delegations,
        delegation_ceiling=request.delegation_ceiling,
        session_id=request.session_id,
        agent_profile_ref=request.agent_profile_ref,
        capability_grant=request.capability_grant,
        workspace=request.workspace,
        secret_refs=request.secret_refs,
        budget_reservation_id=request.budget_reservation_id,
        budget_limits=request.budget_limits,
        tracing_policy_ref=request.tracing_policy_ref,
        sensitive_data_policy_ref=request.sensitive_data_policy_ref,
        snapshot_policy_ref=request.snapshot_policy_ref,
        applied_degradations=tuple(
            policy.authored_degradation
            for policy in request.unsupported_policies
            if not policy.required and policy.authored_degradation is not None
        ),
        execution_runtime=request.execution_runtime,
        native_placement=request.native_placement,
        lane_profile=request.lane_profile,
        # OC-R2: the sealed lane binding moves by digest; only its lane reads the bytes.
        lane_binding=request.lane_binding,
        lane_dispatch=request.lane_dispatch,
        transfer=request.transfer,
        side_effect_key=request.idempotency_key,
        bound_at=request.requested_at,
        runtime_unit=request.runtime_unit,
    )


def settlement_result_manifest(settlement: OperationSettlement) -> bytes:
    """Canonical immutable result manifest bytes; transcripts and payloads stay out."""

    excluded = {"output_text", "structured_output", "event_payloads"}
    if settlement.reused_result is None:
        # RRM-006: the field is additive; manifests without a reused result stay byte-identical.
        excluded.add("reused_result")
    return json.dumps(
        settlement.model_dump(mode="json", exclude=excluded),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _public_result(
    binding: OperationExecutionBinding, settlement: OperationSettlement
) -> OperationExecutionResult:
    return OperationExecutionResult(
        binding_id=binding.binding_id,
        semantic_attempt_key=binding.semantic_attempt_key,
        status=settlement.status,
        output_text=settlement.output_text,
        structured_output=settlement.structured_output,
        output_refs=settlement.output_refs,
        usage=settlement.usage,
        failure_code=settlement.failure_code,
        failure_message=settlement.failure_message,
        unit_key=binding.runtime_unit.unit_key if binding.runtime_unit is not None else None,
        checkpoint_transition_id=settlement.checkpoint_transition_id,
        result_checkpoint=settlement.result_checkpoint,
    )


def _failed_settlement(
    binding: OperationExecutionBinding, *, failure_code: str, message: str
) -> OperationSettlement:
    return OperationSettlement(
        settlement_id=operation_settlement_id(binding.binding_id),
        binding_id=binding.binding_id,
        status="failed",
        failure_code=failure_code,
        failure_message=message,
        settled_at=datetime.now(UTC),
    )


def _unsettled_result(
    binding: OperationExecutionBinding,
    *,
    failure_code: str,
    message: str,
    incident_id: str,
) -> OperationExecutionResult:
    """An `in_doubt` disposition: no settlement exists; the claim stays unsettled."""

    return OperationExecutionResult(
        binding_id=binding.binding_id,
        semantic_attempt_key=binding.semantic_attempt_key,
        status="in_doubt",
        failure_code=failure_code,
        failure_message=message,
        unit_key=binding.runtime_unit.unit_key if binding.runtime_unit is not None else None,
        reconciliation_incident_id=incident_id,
    )


def _abandoned_saved_evidence(saved: InvocationSettlement, decision_id: str) -> dict[str, object]:
    checkpoint = saved.saved_result.checkpoint
    return {
        "abandoned_saved_result": {
            "saved_result_ref": saved.saved_result_ref,
            "decision_id": decision_id,
            "result_checkpoint": None
            if checkpoint is None
            else checkpoint.result_key.model_dump(mode="json"),
        }
    }


def _waiting_result(
    binding: OperationExecutionBinding, record: InvocationSettlement, *, cap: int
) -> OperationExecutionResult:
    """WI-04: the saved result's settlement waits; nothing is settled and no claim moves."""

    wait = SettlementWait.of(record, cap=cap)
    return OperationExecutionResult(
        binding_id=binding.binding_id,
        semantic_attempt_key=binding.semantic_attempt_key,
        status="waiting",
        failure_code=wait.reason.value,
        failure_message=f"saved result settlement waits ({wait.next_action})",
        unit_key=binding.runtime_unit.unit_key if binding.runtime_unit is not None else None,
        settlement_wait=wait.model_dump(mode="json"),
    )


def _failure_candidates(error: BaseException) -> tuple[QualifiedCheckpointKey, ...]:
    if not isinstance(error, RuntimeInvocationFailure):
        return ()
    return tuple(item for item in error.candidates if isinstance(item, QualifiedCheckpointKey))


def settlement_budget_snapshot(
    binding: OperationExecutionBinding, settlement: OperationSettlement
) -> dict[str, object]:
    """TR-D6: the result point carries the settlement's usage and reservation; Tracing
    Stage 2 (FX-TR-BUDGET) adds the bound limits and the dimensions the attempt exhausted,
    so the point says which budget ended the unit. Tracing Stage 3 (R1-F12): exhausted is
    the stop rule's and `_validate_bound_usage`'s `>` over amounts plus pending external
    amounts; a unit that spends exactly its limit exhausted nothing."""

    usage = settlement.usage
    return {
        "usage": usage.model_dump(mode="json"),
        "reservation_id": binding.budget_reservation_id,
        "limits": dict(sorted(binding.budget_limits.items())),
        "exhausted": sorted(
            dimension
            for dimension, limit in binding.budget_limits.items()
            if usage.amounts.get(dimension, 0) + usage.pending_external_amounts.get(dimension, 0)
            > limit
        ),
        "failure_code": settlement.failure_code,
    }


def _failure_detail(error: BaseException) -> str:
    """What the pre-settlement failure log adds to the error type: Mission Control's own
    text for an idempotency conflict or a workspace materialization error, the provider's
    error type for a runtime invocation failure, nothing otherwise."""

    if isinstance(error, IdempotencyConflict | WorkspaceMaterializationError):
        return f": {error}"
    if isinstance(error, RuntimeInvocationFailure):
        return f" ({error.error_type})"
    return ""


def _error_type(error: BaseException) -> str:
    if isinstance(error, RuntimeInvocationFailure):
        return error.error_type
    return type(error).__name__


def _unbound_dimensions(binding: OperationExecutionBinding, usage: RuntimeUsage) -> frozenset[str]:
    return frozenset(
        (usage.amounts.keys() | usage.pending_external_amounts.keys())
        - binding.budget_limits.keys()
    )


def _validate_bound_usage(
    binding: OperationExecutionBinding,
    usage: RuntimeUsage,
    *,
    unreserved: frozenset[str] = frozenset(),
) -> None:
    """Usage is bounded by the binding's limits. `unreserved` (MP-20, Session Lane token
    usage) names run dimensions that may be charged without a unit bound: recorded actual
    amounts only (never pending), checked against the run's hard caps by the reducer."""

    usage_dimensions = usage.amounts.keys() | usage.pending_external_amounts.keys()
    unbound_dimensions = (usage_dimensions - binding.budget_limits.keys()) - (
        unreserved - usage.pending_external_amounts.keys()
    )
    if unbound_dimensions:
        raise OperationBudgetViolation(
            "runtime reported unbound budget dimensions: " + ", ".join(sorted(unbound_dimensions))
        )
    exceeded = {
        dimension
        for dimension in usage_dimensions & binding.budget_limits.keys()
        if (
            usage.amounts.get(dimension, 0) + usage.pending_external_amounts.get(dimension, 0)
            > binding.budget_limits[dimension]
        )
    }
    if exceeded:
        raise OperationBudgetViolation(
            "runtime usage exceeds immutable operation budget: " + ", ".join(sorted(exceeded))
        )


def operation_settlement_id(binding_id: str) -> str:
    """The one settlement identity of a bound operation attempt (any status).

    Run control records the operation's usage and settlement evidence under this identity,
    so a family that consumes the settlement (RRM-016) can find exactly that record.
    """

    return stable_id("operation-settlement", binding_id)

"""`lane.turn`, `lane.status`, `lane.cancel` and `lane.cleanup` for Session Lanes (SPEC-07
section 4; FT-G2; MO-05).

One lifecycle synthesis for every protocol lane (ADR-0031). A segment of `lane.turn`:

1. admits the attempt at the operation boundary (binding, authority and the run-control
   effect claim exist before any provider work; a settled attempt returns its settlement);
2. on `start` prepares, starts and sends the turn, recording the native session and turn on
   the harness execution *before* it observes; on `resume` (or a retried `start` whose turn
   is already recorded) it reattaches and never sends again: a lost native turn makes the
   unit `in_doubt`;
3. persists every observed Provider Frame through the FrameSink, deduplicated by provider
   key, and only then heartbeats the cursor (the persisted frames are the resume truth, the
   throttled heartbeat a hint);
4. stops at the segment bound (`done=False` with the cursor) or at a terminal frame, whose
   closing facts end the session (patch, outputs, lease) and settle the operation once.

The Deep Agents lane is not a Session Lane: its governed `operation.execute` body already
synthesizes a bounded turn with checkpoint lineage, so the activity adapter runs it through
`lane.turn` unchanged (`governed`).

MP-06 (SPEC-01 runtime): each segment first claims the fenced session ownership of its
worker's `WorkerSessionManager`; every native create/send (first turn, replacement,
continuation) is journaled `intended` before it is issued and acknowledged with its native
identity after it (`dispatch.py`), passes the run's Stop Fence as a governed effect, and an
`intended` record without acknowledgement is reconciled with the lane before anything is
sent again: found is observed, an authoritative `not_received` is sent once more under the
same idempotency key, anything else parks `in_doubt`. Settlement asserts the owner first, so
an owner fenced out by a takeover cannot settle. A segment that ends with the turn running
retains the session in the manager; only settlement releases it.

MP-12 (SPEC-01 "Four independent progress mechanisms", ADR-0039): a turn's terminal
`finished` frame is the safe boundary. There the service measures context pressure from the
occupancy the lane exposes (or reports it `unknown`), records the assessment as a
non-closing frame, runs a *qualified* native compaction when the policy routes to it (and
remeasures), and otherwise, when work continues under hard pressure or a
`request_continuation` is pending, ends the segment without settling
(`done=False` with the closing facts) so the operation workflow drives the persisted
continuation phase machine through `continuation.advance`. While a transfer fences the
harness execution no new create/send reaches the source session
(`ContinuationInFlight`); after the activation the next `lane.turn` (`turn_no + 1`) sends
the continuation turn to the recorded target session, journaled under its own key. A
continuation handover whose dispatch the Stop Fence denies settles `cancelled` (nothing
reached the target; the fence is the admitted immediate cancel); an *ambiguous* handover
dispatch still parks `in_doubt` (the target may have accepted it).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import aclosing, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from mission_control.application.context.lane_continuation import (
    LaneContinuationCoordinator,
    continuation_instruction_ref,
    is_continuation_instruction,
)
from mission_control.application.context.lane_support import (
    CompactingLane,
    CompactionRequest,
    ContextOccupancyLane,
    ContinuationInFlight,
)
from mission_control.application.environments.discovery import (
    DiscoveringLane,
    discovery_observation,
    discovery_report_of,
)
from mission_control.application.environments.preparation import (
    EnvironmentNotReady,
    EnvironmentPreparationService,
)
from mission_control.application.execution.cognition_points import (
    CognitionPointRepository,
    latest_point,
)
from mission_control.application.execution.harness.budget_controls import (
    BudgetControlService,
    ManagedBudgetProvider,
)
from mission_control.application.execution.harness.controls import (
    SessionHandover,
    SessionHandoverLane,
    TurnTextStaging,
    open_tool_calls,
    usage_from_frames,
)
from mission_control.application.execution.harness.dispatch import (
    DispatchFenced,
    DispatchKind,
    DispatchLookup,
    DispatchOutcome,
    DispatchReconcilingLane,
    DispatchRecord,
    ProviderCapacityLimited,
    SessionOwner,
    StaleSessionOwner,
    SteeringLane,
    instruction_digest,
)
from mission_control.application.execution.harness.inject import (
    INJECT_KIND,
    InjectionParked,
    InterruptAndInjectService,
    cancel_and_replace_turn,
    resolve_interrupt_mode,
    unit_boundary,
)
from mission_control.application.execution.harness.native_run_usage import summarize_usage
from mission_control.application.execution.harness.points import (
    PointCollectingLane,
    fold_generation_points,
)
from mission_control.application.execution.harness.protocol import (
    CancelledCloseLane,
    HistoryReconciliationLane,
    NativeRunUsageLane,
    NativeTurnLost,
    SessionLane,
    WorkspaceLeasingLane,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.execution.harness.state import (
    LaneExecutionState,
    LaneExecutionStateStore,
    LaneExecutionUpdate,
    segment_update,
)
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.execution.stop_fence import StopFenceRepository
from mission_control.application.frames.kinds import classify
from mission_control.application.frames.reducer import FrameFactProjector, FrameFactTarget
from mission_control.application.frames.sink import FrameReader, FrameStore, harness_execution_id
from mission_control.application.frames.writer import FrameWriter
from mission_control.application.resolution.registries import (
    LaneNotQualified,
    LaneRegistry,
    lane_profile_for,
)
from mission_control.application.secrets.redaction import SecretValueRegistry
from mission_control.application.workspaces.errors import WorkspaceError
from mission_control.application.workspaces.placement import PlacementAdmission
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.authoring.contracts import SecretRef
from mission_control.domain.context.checkpoint import ContinuationTriggerKind
from mission_control.domain.context.pressure import (
    ContextOccupancy,
    PressureAssessment,
    compaction_route,
    native_unavailable_reason,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.budget_controls import (
    BudgetControlRecord,
    LaneBudgetControlRequest,
)
from mission_control.domain.execution.checkpoint_lineage import (
    OperationActivityAttempt,
    activity_attempt_observation_id,
)
from mission_control.domain.execution.cognition_points import (
    CognitionPointFilter,
    CognitionPointObservation,
    CognitionPointRef,
)
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationExecutionResult,
)
from mission_control.domain.execution.environment_preparation import ENVIRONMENT_NOT_READY
from mission_control.domain.execution.history_reconciliation import (
    HISTORY_POLL_SECONDS,
    HISTORY_TIMEOUT_SECONDS,
    MAX_HISTORY_FRAMES,
    HistoryDeferred,
    HistoryReplayComplete,
    HistoryReplayIncomplete,
    HistoryRequest,
)
from mission_control.domain.execution.lane_turns import (
    ClosingFacts,
    LaneCancelRequest,
    LaneCancelResult,
    LaneCleanupRequest,
    LaneCleanupResult,
    LaneStatusRequest,
    LaneStatusResult,
    LaneTurnRequest,
    LaneTurnResult,
    NativeRefs,
)
from mission_control.domain.execution.lanes import (
    PLACEMENT_OF_PROFILE,
    CancelReceipt,
    CancelTurnRequest,
    CursorExecutionBinding,
    EndSessionRequest,
    HarnessScope,
    LaneFrame,
    LaneSeedHead,
    LaneSegmentBounds,
    ObserveRequest,
    PreparedSession,
    PrepareRequest,
    ReattachRequest,
    SendTurnRequest,
    SessionHandle,
    StartRequest,
    StatusRequest,
    TurnHandle,
    UsageReport,
    UsageRequest,
)
from mission_control.domain.frames.body import frame_body_object
from mission_control.domain.frames.contracts import (
    FrameKind,
    FrameObservation,
    HarnessExecutionHandle,
    HarnessExecutionStart,
    LaneProfile,
    ProviderFrame,
)
from mission_control.domain.policies.mailbox import MailboxEntry, MailboxState
from mission_control.domain.policies.stop_fence import EffectAdmission

_LOGGER = logging.getLogger(__name__)
# How long a cancelled activity still waits for an in-flight native call to return, so its
# acknowledgement is journaled before the cancel proceeds (the call itself is never retried).
DISPATCH_RECEIPT_GRACE_S = 10.0
LANE_ACTOR = "mission-control-lane-turn"
MC_AFTER_COMPACTION_RAW_KIND = "custom.mc.after_compaction"
# `lane.cleanup` before the unit settled: its custody may not be registered yet; kept.
UNIT_NOT_SETTLED = "UNIT_NOT_SETTLED"

# Typed lane-state columns (`LaneExecutionUpdate`). The Claude lane records its state root
# under `bridge_state_root`; its SDK pin and auth route live in its describe and frames.
_RECORDED_DETAILS = frozenset(
    {"cursor_sdk_version", "bridge_state_root", "cloud_branch", "cloud_agent_url"}
)


class LaneSessionAdmissionView(Protocol):
    binding: Any
    settled: OperationExecutionResult | None


class LaneBoundary(Protocol):
    """What `lane.turn` needs from the governed operation boundary."""

    async def admit_lane_session(
        self,
        request: OperationExecutionRequest,
        *,
        attempt: OperationActivityAttempt | None = None,
        budget_control: LaneBudgetControlRequest | None = None,
    ) -> LaneSessionAdmissionView: ...

    async def settle_lane_session(
        self,
        request: OperationExecutionRequest,
        facts: ClosingFacts,
        *,
        attempt: OperationActivityAttempt | None = None,
        native_turn_ref: str | None = None,
        cancelled_by_command: bool = False,
        final_text: str | None = None,
        points: tuple[CognitionPointObservation, ...] = (),
    ) -> OperationExecutionResult: ...

    async def lane_settlement(
        self, request: OperationExecutionRequest
    ) -> OperationExecutionResult | None: ...

    async def settle_lane_admission_rejection(
        self,
        request: OperationExecutionRequest,
        rejection: LaneNotQualified,
        *,
        attempt: OperationActivityAttempt | None = None,
    ) -> OperationExecutionResult: ...

    async def lane_in_doubt(
        self, request: OperationExecutionRequest, *, reason: str
    ) -> OperationExecutionResult: ...


@runtime_checkable
class LaneReconciliationBoundary(Protocol):
    """Optional composition seam; absence keeps ambiguous native effects parked."""

    async def reconcile_lane_cancellation(
        self,
        request: OperationExecutionRequest,
        *,
        attempt: OperationActivityAttempt | None = None,
        reason: str | None = None,
    ) -> OperationExecutionResult | None: ...


@runtime_checkable
class FinalTextLane(Protocol):
    """MP-20: a Session Lane that reads its turn's *full* final assistant text from the
    terminal frame body (the closing facts carry only a bounded excerpt). The settlement
    parses the Completion Candidate from it; a lane without it falls back to the closing
    facts' text only when that text provably is whole (`operation_execution.lane_final_text`)."""

    def final_text(self, turn: TurnHandle, frame: LaneFrame) -> str | None: ...


def read_final_text(harness: SessionLane, turn: TurnHandle, frame: LaneFrame) -> str | None:
    """The lane's full final text of `turn` from its terminal `frame`, if the lane reads it."""

    if not isinstance(harness, FinalTextLane):
        return None
    try:
        return harness.final_text(turn, frame)
    except Exception:
        _LOGGER.warning("the lane's final text was not read; the closing facts decide")
        return None


class SecretValues(Protocol):
    async def resolve(self, refs: tuple[SecretRef, ...]) -> Mapping[str, str]: ...


class TurnSignals(Protocol):
    """The activity's view of Temporal: heartbeat, prior heartbeat and requested cancel."""

    def heartbeat(self, cursor: str | None, frames_persisted: int) -> None: ...

    def prior_cursor(self) -> str | None: ...

    def cancel_requested(self) -> bool: ...


class LaneNotSessionDriven(TypeError):
    """The lane is governed by the operation boundary's bounded execute path (Deep Agents)."""


class LaneStartStalled(RuntimeError):
    """F3-G1: prepare, start and the first send did not finish within the segment's duration.

    Nothing settles: the activity fails with this type, and its retry reconciles the
    dispatch journal (a create or send the provider accepted is found, never re-sent)."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def harness_scope(request_scope: str, actor_id: str = LANE_ACTOR) -> HarnessScope:
    try:
        parsed = parse_request_scope(request_scope)
    except ValueError:
        # Non-canonical scopes (local proof) name all three parts by the same value.
        return HarnessScope(
            installation_id=request_scope,
            application_id=request_scope,
            tenant_id=request_scope,
            actor_id=actor_id,
        )
    return HarnessScope(
        installation_id=str(parsed.installation_id),
        application_id=parsed.application_id,
        tenant_id=str(parsed.tenant_id),
        actor_id=actor_id,
    )


@dataclass(frozen=True)
class LaneExecutionIdentity:
    """Where one lane attempt's frames and state live (SPEC-03 harness execution)."""

    request_scope: str
    run_key: str
    activation_key: str
    attempt_no: int
    lane_profile: str
    harness_execution_id: UUID

    @classmethod
    def of(cls, operation: OperationExecutionRequest, lane_profile: str, generation: int) -> Any:
        unit = operation.runtime_unit
        request_scope = unit.request_scope if unit is not None else operation.request_scope
        run_key = unit.belllabs_run_id if unit is not None else operation.identity.run_id
        activation_key = unit.unit_key if unit is not None else operation.identity.operation_id
        return cls(
            request_scope=request_scope,
            run_key=run_key,
            activation_key=activation_key,
            attempt_no=generation,
            lane_profile=lane_profile,
            harness_execution_id=harness_execution_id(
                request_scope=request_scope,
                run_key=run_key,
                activation_key=activation_key,
                attempt_no=generation,
                lane=lane_profile,
            ),
        )


def _binding_digest(operation: OperationExecutionRequest) -> str:
    cursor = CursorExecutionBinding.carried_by(operation)
    return cursor.binding_digest if cursor is not None else operation.effective_configuration_digest


def execution_start(
    operation: OperationExecutionRequest,
    identity: LaneExecutionIdentity,
    generation: int,
    session_ref: str,
) -> HarnessExecutionStart:
    """The harness execution a Session Lane's frames (provider and hook) are written under."""

    placement = PLACEMENT_OF_PROFILE.get(identity.lane_profile, "worker_hosted")
    return HarnessExecutionStart(
        harness_execution_id=identity.harness_execution_id,
        request_scope=identity.request_scope,
        run_key=identity.run_key,
        activation_key=identity.activation_key,
        attempt_no=identity.attempt_no,
        generation=generation,
        lane_profile=LaneProfile(identity.lane_profile),
        native_session_ref=session_ref,
        runtime_kind=operation.execution_runtime,
        provider_kind=identity.lane_profile,
        placement_kind=placement,
        intended_binding_digest=_binding_digest(operation),
        launch_key=f"{identity.harness_execution_id}:{generation}",
        native_identity={
            "operation_id": operation.identity.operation_id,
            "semantic_attempt_key": operation.identity.semantic_key,
        },
    )


class LaneTurnService:
    """Drives a Session Lane through `lane.turn` segments, `lane.status` and `lane.cancel`."""

    def __init__(
        self,
        *,
        lanes: LaneRegistry,
        placement: PlacementAdmission | None = None,
        boundary: LaneBoundary,
        frames: FrameStore,
        states: LaneExecutionStateStore,
        secrets: SecretValues | None = None,
        redaction: SecretValueRegistry | None = None,
        frame_facts: FrameFactProjector | None = None,
        clock: Callable[[], datetime] = _utc_now,
        excerpt_cap_bytes: int = 8_192,
        mailbox: MailboxDeliveryService | None = None,
        injections: InterruptAndInjectService | None = None,
        frame_reader: FrameReader | None = None,
        sessions: WorkerSessionManager | None = None,
        fences: StopFenceRepository | None = None,
        receipt_grace_s: float = DISPATCH_RECEIPT_GRACE_S,
        continuations: LaneContinuationCoordinator | None = None,
        preparations: EnvironmentPreparationService | None = None,
        budget_controls: BudgetControlService | None = None,
        session_registration: Callable[
            [OperationExecutionRequest, LaneExecutionIdentity, int, str], Awaitable[None]
        ]
        | None = None,
        points: CognitionPointRepository | None = None,
    ) -> None:
        # K1/K2 (cross-provider control, 2026-11-05): the cognition point index, read for
        # the previous generation's result point (the first point's parent) and for the
        # `fork_seed` point a derived unit's first session continues from; the points
        # themselves are written by the boundary's settlement, never here.
        self._points = points
        # MO-16: the environment preparation record of every prepared attempt and the launch
        # policy's minimum readiness a session starts at (none composed: nothing recorded).
        self._preparations = preparations
        self._budget_controls = budget_controls
        self._session_registration = session_registration
        # MP-06: the worker-owned session manager (fenced ownership, retained sessions), the
        # Stop Fence every new native dispatch is admitted against, and the bounded grace a
        # dispatch receipt gets before an activity cancel lands
        # (`MISSION_CONTROL_DISPATCH_RECEIPT_GRACE_S`).
        self._sessions = sessions or WorkerSessionManager()
        self._fences = fences
        self._receipt_grace_s = receipt_grace_s
        # MP-12: context pressure, continuation triggers, the in-flight fence and the
        # activated target of a continuation (none composed: the FT-G4 handover path only).
        self._continuations = continuations
        # FT-G4: the mailbox consumes queued content at the send that carries it
        # (`wait_then_send`) and settles it with the turn; `injections` watches a running
        # turn for `interrupt_and_inject` (`cancel_and_replace`); the frame reader names the
        # turn's Uncertain Effects and its last reported usage.
        self._mailbox = mailbox
        self._injections = injections
        reader = frame_reader
        if reader is None and hasattr(frames, "frames_for_execution"):
            reader = frames  # type: ignore[assignment]
        self._reader: FrameReader | None = reader
        self._lanes = lanes
        self._placement = placement
        self._boundary = boundary
        self._frames = frames
        self._states = states
        self._secrets = secrets
        # MO-11: every value the Secret Broker resolved or minted in this process (a lane's
        # launch envVars, a local child's delivered values) is redacted from frames too.
        self._redaction = redaction
        self._frame_facts = frame_facts
        self._clock = clock
        self._cap = excerpt_cap_bytes

    @property
    def sessions(self) -> WorkerSessionManager:
        return self._sessions

    @property
    def preparations(self) -> EnvironmentPreparationService | None:
        return self._preparations

    # --- dispatch ---------------------------------------------------------------------------

    def governed(self, lane_profile: str) -> bool:
        """True when the lane runs the boundary's governed execute path (Deep Agents)."""

        return not isinstance(self._lanes.for_profile(lane_profile), SessionLane)

    def _session_lane(
        self, lane_profile: str, operation: OperationExecutionRequest, generation: int
    ) -> SessionLane:
        harness = self._lanes.admit(lane_profile)
        if not isinstance(harness, SessionLane):
            raise LaneNotSessionDriven(f"lane profile {lane_profile} is governed, not driven")
        identity = LaneExecutionIdentity.of(operation, lane_profile, generation)
        harness.stage(str(identity.harness_execution_id), operation)
        return harness

    # --- shared request fields --------------------------------------------------------------

    def _fields(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        generation: int,
        key: str,
    ) -> dict[str, Any]:
        return {
            "scope": harness_scope(identity.request_scope),
            "lane_profile": identity.lane_profile,
            "harness_execution_id": str(identity.harness_execution_id),
            "binding_digest": _binding_digest(operation),
            "idempotency_key": f"{identity.harness_execution_id}:{generation}:{key}",
            "generation": generation,
        }

    async def _secret_values(self, operation: OperationExecutionRequest) -> tuple[str, ...]:
        delivered = self._redaction.values() if self._redaction is not None else ()
        if self._secrets is None or not operation.secret_refs:
            return delivered
        resolved = await self._secrets.resolve(operation.secret_refs)
        return (*delivered, *(value for value in resolved.values() if value))

    async def _open(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        generation: int,
        session_ref: str,
    ) -> HarnessExecutionHandle:
        return await self._frames.open_execution(
            execution_start(operation, identity, generation, session_ref)
        )

    # --- lane.turn --------------------------------------------------------------------------

    async def budget_control(self, request: LaneBudgetControlRequest) -> BudgetControlRecord:
        from mission_control.domain.execution.budget_controls import budget_control_key

        if self._budget_controls is None:
            raise ValueError("governed budget controls are not composed")
        if not _declares_budget_gate(request.operation):
            raise ValueError("the operation's lane declares no budget gate")
        profile = lane_profile_for(request.operation)
        identity = LaneExecutionIdentity.of(request.operation, profile, request.generation)
        await self._budget_controls.enqueue(request, identity.harness_execution_id, self._clock())
        state = await self._states.load(identity.request_scope, identity.harness_execution_id)
        if (
            state is not None
            and state.owner is not None
            and (
                state.owner.expired(self._clock())
                or state.owner.owner_ref == self._sessions.owner_ref
            )
        ):
            owner = await self._sessions.claim(
                self._states,
                identity.request_scope,
                identity.harness_execution_id,
                generation=request.generation,
                now=self._clock(),
                heartbeat_timeout_s=30,
            )
            harness = self._session_lane(profile, request.operation, request.generation)
            if not isinstance(harness, ManagedBudgetProvider):
                raise ValueError("Managed budget provider control is unavailable")
            await self._budget_controls.drain(
                request.operation, identity.harness_execution_id, owner, harness, self._clock()
            )
        state = await self._states.load(identity.request_scope, identity.harness_execution_id)
        assert state is not None
        return state.budget_controls[budget_control_key(request.command_issuer, request.command_id)]

    async def turn(
        self,
        request: LaneTurnRequest,
        signals: TurnSignals,
        *,
        attempt: OperationActivityAttempt | None = None,
    ) -> LaneTurnResult:
        operation = request.operation
        identity = LaneExecutionIdentity.of(operation, request.lane_profile, request.generation)
        prior_settlement = await self._boundary.lane_settlement(operation)
        if prior_settlement is not None:
            return LaneTurnResult(
                done=True,
                segment_no=request.segment_no,
                operation_result=prior_settlement.model_dump(mode="json"),
            )
        # Catch only registry admission, before stage or any native preparation. A
        # qualification change on an existing execution must preserve all its facts.
        try:
            self._lanes.admit(request.lane_profile)
        except LaneNotQualified as rejection:
            state = await self._states.load(identity.request_scope, identity.harness_execution_id)
            if (
                state is not None
                or self._reader is None
                or await self._reader.current_generation(
                    identity.request_scope, identity.harness_execution_id
                )
                is not None
            ):
                raise
            result = await self._boundary.settle_lane_admission_rejection(
                operation, rejection, attempt=attempt
            )
            return LaneTurnResult(
                done=True,
                segment_no=request.segment_no,
                operation_result=result.model_dump(mode="json"),
            )
        harness = self._session_lane(request.lane_profile, operation, request.generation)
        before = await self._states.load(identity.request_scope, identity.harness_execution_id)
        control = None
        if (
            self._budget_controls is not None
            and before is not None
            and before.budget_controls
            and before.native_turn_ref
        ):
            from mission_control.domain.execution.budget_controls import LaneBudgetControlRequest

            controls = [
                item
                for item in before.budget_controls.values()
                if item.action == "hold" and item.phase != "rejected"
            ]
            if controls:
                last = max(controls, key=lambda item: item.command_sequence)
                control = LaneBudgetControlRequest(
                    operation=operation,
                    generation=request.generation,
                    command_id=last.command_id,
                    command_issuer=last.command_issuer,
                )
        admission = await self._boundary.admit_lane_session(
            operation, attempt=attempt, **({"budget_control": control} if control else {})
        )
        if admission.settled is not None:
            return LaneTurnResult(
                done=True,
                segment_no=request.segment_no,
                operation_result=admission.settled.model_dump(mode="json"),
            )
        identity = LaneExecutionIdentity.of(operation, request.lane_profile, request.generation)
        scope, heid = identity.request_scope, identity.harness_execution_id
        state = await self._states.load(scope, heid)
        # The row exists before the claim and before any native call is journaled on it.
        await self._open(
            operation,
            identity,
            request.generation,
            (state.native_session_ref if state is not None else None) or str(heid),
        )
        owner = await self._sessions.claim(
            self._states,
            scope,
            heid,
            generation=request.generation,
            now=self._clock(),
            heartbeat_timeout_s=request.segment.heartbeat_timeout_s,
        )
        # A queued hint from a superseded generation cannot authorize a native read.
        # Resolve it under the newly claimed owner before recovery can advance a turn.
        state = await self._states.load(scope, heid)
        journal = None if state is None else state.history_reconciliation
        if (
            journal is not None
            and journal.pending
            and journal.requested.generation < owner.generation
        ):
            await self._states.refresh_history_authority(
                journal.requested, owner=owner, at=self._clock()
            )
        fields = self._fields(operation, identity, request.generation, f"turn:{request.turn_no}")
        state = await self._acknowledged_turn(
            identity, fields, await self._states.load(scope, heid), turn_no=request.turn_no
        )
        record = state.dispatch("send", fields["idempotency_key"]) if state is not None else None
        if request.turn_no > 1:
            # MP-12: a later turn (the continuation turn) is "sent" only by its own journal
            # entry; the row's native turn is the latest turn, whichever number it carries.
            sent = (
                record is not None
                and record.phase == "acknowledged"
                and state is not None
                and state.native_turn_ref == record.native_ref
            )
        else:
            sent = state is not None and state.native_turn_ref is not None
        journaled = record is not None
        if not sent and state is not None and state.budget_controls:
            from mission_control.application.execution.harness.budget_controls import held

            if held(state.budget_controls):
                return LaneTurnResult(
                    done=False,
                    busy=True,
                    segment_no=request.segment_no,
                    native=NativeRefs(
                        session_ref=state.native_session_ref, turn_ref=state.native_turn_ref
                    ),
                )
            # The control path authorizes observation while paused, never fresh cognition.
            # A resume's cap readback may precede its family applied receipt briefly.
            try:
                await self._boundary.admit_lane_session(operation, attempt=attempt)
            except ValueError:
                return LaneTurnResult(
                    done=False,
                    busy=True,
                    segment_no=request.segment_no,
                    native=NativeRefs(
                        session_ref=state.native_session_ref, turn_ref=state.native_turn_ref
                    ),
                )
        if self._continuations is not None and not sent:
            # MP-12: a session frozen for a continuation takes no new agent action.
            fencing = await self._continuations.fencing(
                scope, identity.run_key, harness_execution_id=str(heid)
            )
            if fencing is not None:
                raise ContinuationInFlight(fencing.transfer_id, fencing.phase.value)
            request = await self._continuation_instruction(request, harness, identity, state)
        if request.capacity_exhausted:
            if not sent:
                await self._turn_not_started(operation)
            return await self._settle(
                request,
                harness,
                identity,
                None,
                ClosingFacts(native_status="error", error_code="capacity"),
                attempt=attempt,
                native=NativeRefs(
                    session_ref=state.native_session_ref if state else None,
                    turn_ref=state.native_turn_ref if state else None,
                ),
                owner=owner,
            )
        if not sent and (request.phase == "start" or journaled):
            started = await self._beating(
                request,
                identity,
                owner,
                signals,
                self._start_and_send(request, harness, identity, fields, owner),
            )
            if isinstance(started, LaneTurnResult):
                return started
            session, turn, reconciled = started
            cursor = None
            if reconciled:
                # A turn the provider accepted before a lost receipt: observe it from the
                # persisted frames, never send it again.
                cursor = await self._resume_cursor(
                    harness, identity, request, signals.prior_cursor()
                )
        else:
            if state is None or state.native_session_ref is None:
                return await self._lost(request, identity, reason="native_session_unrecorded")
            if self._continuations is not None and request.phase == "resume":
                # MP-12: a continuation that ended without a target leaves a finished turn
                # whose terminal frame is persisted; the resumed segment settles it.
                settled = await self._settle_after_continuation(
                    request, harness, identity, fields, state, owner, attempt=attempt
                )
                if settled is not None:
                    return settled
            try:
                session = await harness.reattach(
                    ReattachRequest(
                        **fields,
                        native_session_ref=state.native_session_ref,
                        native_turn_ref=state.native_turn_ref,
                    )
                )
            except NativeTurnLost:
                return await self._lost(request, identity, reason="native_turn_lost")
            turn = TurnHandle(
                session=session, turn_no=request.turn_no, native_turn_ref=state.native_turn_ref
            )
            cursor = await self._resume_cursor(
                harness, identity, request, signals.prior_cursor() or state.provider_cursor
            )
        handle = await self._open(
            operation, identity, request.generation, session.native_session_ref or str(heid)
        )
        writer = FrameWriter(
            self._frames,
            handle,
            excerpt_cap_bytes=self._cap,
            secret_values=await self._secret_values(operation),
        )
        return await self._observe_segment(
            request,
            harness,
            identity,
            fields,
            turn,
            cursor,
            writer,
            signals,
            attempt=attempt,
            owner=owner,
        )

    async def _acknowledged_turn(
        self,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        state: LaneExecutionState | None,
        *,
        turn_no: int = 1,
    ) -> LaneExecutionState | None:
        """A send acknowledged in the journal but not yet on the row (lost between the two
        writes) is recorded now: the journal is the receipt. MP-12: a later turn's receipt
        supersedes the earlier turn's identity explicitly."""

        if state is None:
            return state
        record = state.dispatch("send", fields["idempotency_key"])
        if record is None or record.phase != "acknowledged" or record.native_ref is None:
            return state
        if state.native_turn_ref == record.native_ref:
            return state
        if state.native_turn_ref is not None and turn_no <= 1:
            return state
        return await self._states.record(
            identity.request_scope,
            identity.harness_execution_id,
            LaneExecutionUpdate(
                native_turn_ref=record.native_ref, supersedes_turn_ref=state.native_turn_ref
            ),
        )

    async def _continuation_instruction(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        state: LaneExecutionState | None,
    ) -> LaneTurnRequest:
        """MP-12: the first turn of an activated target carries the continuation instruction
        (the sealed packet's `admitted_input`), staged on the lane when it sends text by
        reference; a workflow that lost the reference across continue-as-new still finds it
        here, from the activated transfer that names this turn."""

        assert self._continuations is not None
        if request.turn_no <= 1 or state is None:
            return request
        activated = await self._continuations.activated_for_turn(
            identity.request_scope,
            identity.run_key,
            harness_execution_id=str(identity.harness_execution_id),
            turn_no=request.turn_no,
        )
        if activated is None:
            if is_continuation_instruction(request.instruction_ref):
                raise NativeTurnLost(
                    f"turn {request.turn_no} names a continuation that is not activated"
                )
            return request
        ref = continuation_instruction_ref(activated.transfer_id)
        if isinstance(harness, TurnTextStaging):
            prompt = await self._continuations.hydration_prompt(activated)
            if prompt is not None:
                harness.stage_turn(str(identity.harness_execution_id), ref, prompt)
        return request.model_copy(update={"instruction_ref": ref})

    async def _beating[T](
        self,
        request: LaneTurnRequest,
        identity: LaneExecutionIdentity,
        owner: SessionOwner,
        signals: TurnSignals,
        body: Awaitable[T],
    ) -> T:
        """F3-G1: heartbeat and renew the owner's lease while the lane prepares, starts and
        sends, as observation does.

        A hosted prepare (resource sync with readback polling) can outlast the heartbeat
        timeout. Unbeaten, Temporal times the attempt out and starts the next one beside it on
        the same worker; the two race the dispatch journal and the unit parks `in_doubt`
        before anything is sent. The beat carries the prior attempt's cursor hint, so a loss
        here never erases it. The phase is bounded by the segment duration: a start that
        never reaches its send fails as `LaneStartStalled` instead of beating forever."""

        bounds = request.segment
        progress = _SegmentProgress(owner=owner, cursor=signals.prior_cursor() or request.cursor)

        async def renew() -> None:
            await self._renew(identity, progress, bounds.heartbeat_timeout_s)

        ticker = asyncio.create_task(
            _heartbeat_ticker(
                signals, lambda: (progress.cursor, 0), bounds.heartbeat_timeout_s, renew=renew
            )
        )
        deadline = asyncio.timeout(bounds.max_duration_s)
        try:
            async with deadline:
                return await body
        except TimeoutError as error:
            if not deadline.expired():
                raise
            raise LaneStartStalled(
                f"{request.lane_profile} did not prepare, start and send within "
                f"{bounds.max_duration_s}s"
            ) from error
        finally:
            ticker.cancel()
            with suppress(asyncio.CancelledError):
                await ticker

    async def _start_and_send(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        owner: SessionOwner,
    ) -> tuple[SessionHandle, TurnHandle, bool] | LaneTurnResult:
        operation = request.operation
        scope, heid = identity.request_scope, identity.harness_execution_id
        if self._placement is not None:
            try:
                await self._placement.reserve(scope, heid, identity.lane_profile, self._clock())
            except ProviderCapacityLimited:
                await self._turn_not_started(operation)
                raise
        # K2: a derived unit's first session continues from the seed head its fork recorded.
        seed = await self._seed_head(identity, operation, request.generation)
        try:
            prepared = await harness.prepare(
                PrepareRequest(
                    **fields,
                    run_id=operation.identity.run_id,
                    operation_id=operation.identity.operation_id,
                    attempt_no=identity.attempt_no,
                    seed=seed,
                )
            )
        except Exception:
            state = await self._states.load(scope, heid)
            if self._placement is not None and (state is None or state.native_session_ref is None):
                await self._placement.release(scope, heid)
            raise
        state = await self._states.load(scope, heid)
        if state is None or state.native_session_ref is None:
            refused = await self._admit_environment(request, harness, identity, prepared, owner)
            if refused is not None:
                if self._placement is not None:
                    await self._placement.release(scope, heid)
                return refused
        try:
            if state is not None and state.native_session_ref is not None:
                session = await harness.reattach(
                    ReattachRequest(**fields, native_session_ref=state.native_session_ref)
                )
            else:
                created = await self._dispatch_once(
                    request,
                    harness,
                    identity,
                    owner,
                    "create",
                    fields["idempotency_key"],
                    instruction_ref=None,
                    turn_no=request.turn_no,
                    session=None,
                    issue=lambda: harness.start(
                        StartRequest(**fields, prepared=prepared, seed=seed)
                    ),
                    native_of=lambda handle: handle.native_session_ref,
                    declined_of=lambda _handle: False,
                )
                if created.value is not None:
                    session = created.value
                else:
                    assert created.native_ref is not None
                    session = await harness.reattach(
                        ReattachRequest(**fields, native_session_ref=created.native_ref)
                    )
                if session.native_session_ref is None:
                    raise ValueError("a Session Lane start returns the native session identity")
                # Native identity first, then observation (SPEC-07 section 5.2).
                handle = await self._open(
                    operation, identity, request.generation, session.native_session_ref
                )
                details = {
                    key: value
                    for key, value in session.native_details.items()
                    if key in _RECORDED_DETAILS and value
                }
                await self._states.record(
                    scope,
                    heid,
                    LaneExecutionUpdate(native_session_ref=session.native_session_ref, **details),
                )
                await self._discover(harness, identity, session, handle)
            if self._session_registration is not None and session.native_session_ref is not None:
                await self._session_registration(
                    operation, identity, request.generation, session.native_session_ref
                )
            send = SendTurnRequest(
                **fields,
                session=session,
                turn_no=request.turn_no,
                instruction_ref=request.instruction_ref
                or f"operation:{operation.identity.semantic_key}:turn:{request.turn_no}",
            )
            dispatched = await self._dispatch_send(request, harness, identity, owner, send)
        except _DispatchParked as parked:
            return await self._park(request, identity, owner, reason=parked.reason)
        except DispatchFenced:
            return await self._fenced_before_send(request, harness, identity, owner)
        except ProviderCapacityLimited:
            await self._turn_not_started(operation)
            current = await self._states.load(scope, heid)
            if self._placement is not None and (
                current is None or current.native_session_ref is None
            ):
                await self._placement.release(scope, heid)
            raise
        turn = dispatched.handle
        if turn.status == "busy":
            # `wait_then_send`: nothing was sent; the workflow polls `lane.status` until idle.
            return LaneTurnResult(
                done=False,
                busy=True,
                segment_no=request.segment_no,
                native=NativeRefs(session_ref=session.native_session_ref),
            )
        if turn.native_turn_ref is None:
            raise ValueError("a Session Lane send returns the native turn identity")
        update = LaneExecutionUpdate(native_turn_ref=turn.native_turn_ref)
        if (
            request.turn_no > 1
            and state is not None
            and state.native_turn_ref not in {None, turn.native_turn_ref}
        ):
            # MP-12: the continuation turn supersedes the frozen source turn explicitly.
            update = LaneExecutionUpdate(
                native_turn_ref=turn.native_turn_ref, supersedes_turn_ref=state.native_turn_ref
            )
        await self._states.record(scope, heid, update)
        await self._turn_started(operation, harness, session, turn)
        return session, turn, dispatched.reconciled

    async def _admit_environment(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        prepared: PreparedSession,
        owner: SessionOwner,
    ) -> LaneTurnResult | None:
        """MO-16: record what `prepare` proved about the environment; a session never starts
        below the launch policy's minimum readiness. Nothing reached the provider, so the unit
        settles `failed(environment_not_ready)` with the policy's reason."""

        operation = request.operation
        binding = ProviderExecutionBinding.carried_by(
            operation
        ) or CursorExecutionBinding.carried_by(operation)
        if self._preparations is None or binding is None:
            return None
        try:
            await self._preparations.admit_start(identity, binding, prepared)
        except EnvironmentNotReady as refused:
            await self._turn_not_started(operation)
            return await self._settle(
                request,
                harness,
                identity,
                None,
                ClosingFacts(
                    native_status="error",
                    error_code=ENVIRONMENT_NOT_READY,
                    error_message=str(refused)[:1_024],
                ),
                attempt=None,
                native=NativeRefs(),
                owner=owner,
            )
        return None

    async def _discover(
        self,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        session: SessionHandle,
        handle: HarnessExecutionHandle,
    ) -> None:
        """MO-34: a lane that reads back what its provider loaded does so once its new native
        session exists; the report is persisted as a frame and raises the readiness ladder.
        Evidence only: a read-back that fails never fails the turn."""

        if self._preparations is None or not isinstance(harness, DiscoveringLane):
            return
        try:
            report = await harness.discover(session)
            if report is None:
                return
            observation = discovery_observation(
                report,
                provider_key=f"discovery:{session.native_session_ref}:{report.mechanism}",
                native_session_ref=session.native_session_ref,
            )
            await FrameWriter(self._frames, handle, excerpt_cap_bytes=self._cap).write(
                [observation]
            )
        except Exception:
            _LOGGER.warning("the lane's discovery read-back was not recorded", exc_info=True)
            return
        await self._preparations.discovered(
            identity, report, evidence_ref=f"frame:{observation.provider_key}"
        )

    # --- MP-06 dispatch journal ---------------------------------------------------------------

    async def _dispatch_send(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        owner: SessionOwner,
        send: SendTurnRequest,
    ) -> _SentTurn:
        """`send_turn` once through the journal; a reconciled turn is never re-sent."""

        dispatched = await self._dispatch_once(
            request,
            harness,
            identity,
            owner,
            "send",
            send.idempotency_key,
            instruction_ref=send.instruction_ref,
            turn_no=send.turn_no,
            session=send.session,
            issue=lambda: harness.send_turn(send),
            native_of=lambda handle: handle.native_turn_ref,
            declined_of=lambda handle: handle.status == "busy",
        )
        if dispatched.value is not None:
            return _SentTurn(dispatched.value, reconciled=False)
        return _SentTurn(
            TurnHandle(
                session=send.session, turn_no=send.turn_no, native_turn_ref=dispatched.native_ref
            ),
            reconciled=True,
        )

    async def _dispatch_once[T](
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        owner: SessionOwner,
        kind: DispatchKind,
        idempotency_key: str,
        *,
        instruction_ref: str | None,
        turn_no: int,
        session: SessionHandle | None,
        issue: Callable[[], Awaitable[T]],
        native_of: Callable[[T], str | None],
        declined_of: Callable[[T], bool],
    ) -> _Dispatched[T]:
        """Journal, admit and issue one native create/send (SPEC-01 steps 2-3 and 7).

        Raises `_DispatchParked` when an earlier dispatch of the key cannot be reconciled
        and `DispatchFenced` when the Stop Fence denies a new one.
        """

        scope, heid = identity.request_scope, identity.harness_execution_id
        record = DispatchRecord(
            kind=kind,
            idempotency_key=idempotency_key,
            expected_generation=request.generation,
            instruction_digest=instruction_digest(
                kind=kind,
                instruction_ref=instruction_ref,
                binding_digest=_binding_digest(request.operation),
                turn_no=turn_no,
            ),
            owner_ref=owner.owner_ref,
            owner_epoch=owner.epoch,
            intended_at=self._clock(),
        )
        claim = await self._states.intend_dispatch(scope, heid, record, owner=owner)
        if not claim.fresh:
            stored = claim.record
            if stored.phase == "acknowledged" and stored.native_ref is not None:
                return _Dispatched(native_ref=stored.native_ref, reconciled=True)
            if stored.phase != "intended":
                raise _DispatchParked(stored.reason or f"{kind}_dispatch_in_doubt")
            lookup = await self._lookup(harness, stored, session)
            if lookup.outcome == "found" and lookup.native_ref is not None:
                await self._resolve(identity, owner, stored, "acknowledged", lookup.native_ref)
                return _Dispatched(native_ref=lookup.native_ref, reconciled=True)
            if lookup.outcome != "not_received":
                await self._resolve(
                    identity, owner, stored, "in_doubt", reason=f"{kind}_dispatch_ambiguous"
                )
                raise _DispatchParked(f"{kind}_dispatch_ambiguous")
            await self._resolve(identity, owner, stored, "not_received", reason="reconciled")
            claim = await self._states.intend_dispatch(scope, heid, record, owner=owner)
            if not claim.fresh:
                raise _DispatchParked(f"{kind}_dispatch_contended")
        fenced = await self._fence_denies(request, record)
        if fenced is not None:
            await self._resolve(identity, owner, record, "declined", reason="stop_fenced")
            raise DispatchFenced(record.key, fenced)

        async def issue_and_record() -> _Dispatched[T]:
            try:
                value = await issue()
            except ProviderCapacityLimited:
                await self._resolve(identity, owner, record, "declined", reason="capacity")
                raise
            if declined_of(value):
                await self._resolve(identity, owner, record, "declined", reason="busy")
                return _Dispatched(native_ref=None, value=value)
            native_ref = native_of(value)
            if native_ref is not None:
                await self._resolve(identity, owner, record, "acknowledged", native_ref)
            return _Dispatched(native_ref=native_ref, value=value)

        # An activity cancel must not cut the receipt off from a call the provider may have
        # accepted: the call and its journal write finish (bounded) before the cancel lands.
        task = asyncio.ensure_future(issue_and_record())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.wait({task}, timeout=self._receipt_grace_s)
            task.add_done_callback(_late_dispatch)
            raise

    async def _lookup(
        self, harness: SessionLane, record: DispatchRecord, session: SessionHandle | None
    ) -> DispatchLookup:
        if not isinstance(harness, DispatchReconcilingLane):
            return DispatchLookup(outcome="unknown", detail="the lane cannot reconcile dispatches")
        try:
            return await harness.reconcile_dispatch(record, session=session)
        except NativeTurnLost:
            return DispatchLookup(outcome="unknown", detail="native identity is lost")

    async def _resolve(
        self,
        identity: LaneExecutionIdentity,
        owner: SessionOwner,
        record: DispatchRecord,
        outcome: DispatchOutcome,
        native_ref: str | None = None,
        *,
        reason: str | None = None,
    ) -> DispatchRecord:
        return await self._states.resolve_dispatch(
            identity.request_scope,
            identity.harness_execution_id,
            record.kind,
            record.idempotency_key,
            outcome=outcome,
            owner=owner,
            at=self._clock(),
            native_ref=native_ref,
            reason=reason,
        )

    async def _fence_denies(self, request: LaneTurnRequest, record: DispatchRecord) -> str | None:
        """A new native dispatch is a governed effect: admitted against the Stop Fence
        atomically with fence writes (admitted before the fence stays admitted)."""

        if self._fences is None:
            return None
        operation = request.operation
        verdict = await self._fences.admit_effect(
            EffectAdmission(
                request_scope=operation.request_scope,
                run_id=operation.identity.run_id,
                generation=request.generation,
                effect_ref=f"dispatch:{record.key}"[:512],
                effect_kind="model",
                lane_profile=request.lane_profile,
            )
        )
        return None if verdict.allowed else (verdict.fence_command_id or "stop_fence")

    async def _park(
        self,
        request: LaneTurnRequest,
        identity: LaneExecutionIdentity,
        owner: SessionOwner,
        *,
        reason: str,
    ) -> LaneTurnResult:
        """Unrecoverable dispatch uncertainty: `in_doubt`, nothing sent, nothing replaced."""

        await self._states.assert_owner(
            identity.request_scope, identity.harness_execution_id, owner
        )
        return await self._lost(request, identity, reason=reason)

    async def _fenced_before_send(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        owner: SessionOwner,
    ) -> LaneTurnResult:
        """The Stop Fence landed before the first send: nothing reached the provider, so the
        unit settles `cancelled` (the immediate cancel's own settlement)."""

        await self._turn_not_started(request.operation)
        state = await self._states.load(identity.request_scope, identity.harness_execution_id)
        return await self._settle(
            request,
            harness,
            identity,
            None,
            ClosingFacts(native_status="cancelled", error_code="cancelled_by_command"),
            attempt=None,
            native=NativeRefs(session_ref=state.native_session_ref if state else None),
            cancelled_by_command=True,
            owner=owner,
        )

    async def _resume_cursor(
        self,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        request: LaneTurnRequest,
        hint: str | None,
    ) -> str | None:
        """The persisted frames are the truth; the heartbeat, workflow and recorded segment
        cursors are hints (each is written only after the frames it names were persisted)."""

        last = await self._frames.last_cursor(
            identity.harness_execution_id, request.generation, request_scope=identity.request_scope
        )
        if last is not None:
            persisted = harness.resume_cursor(last.provider_key)
            if persisted is not None:
                return persisted
        return hint or request.cursor

    async def _observe_segment(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        turn: TurnHandle,
        cursor: str | None,
        writer: FrameWriter,
        signals: TurnSignals,
        *,
        attempt: OperationActivityAttempt | None,
        owner: SessionOwner,
    ) -> LaneTurnResult:
        bounds = request.segment
        progress = _SegmentProgress(cursor=cursor, max_frames=bounds.max_frames, owner=owner)
        terminal: LaneFrame | None = None
        # The lane declares its budget gate on the dispatch (OC-R3), never by profile name.
        budget_gate = _declares_budget_gate(request.operation)

        async def control_tick() -> None:
            await self._renew(identity, progress, bounds.heartbeat_timeout_s)
            if self._budget_controls is not None and budget_gate:
                if not isinstance(harness, ManagedBudgetProvider):
                    raise ValueError("Managed budget provider control is unavailable")
                await self._budget_controls.drain(
                    request.operation,
                    identity.harness_execution_id,
                    progress.owner,
                    harness,
                    self._clock(),
                )

        if self._budget_controls is not None and budget_gate:
            await control_tick()
        ticker = asyncio.create_task(
            _heartbeat_ticker(
                signals,
                lambda: (progress.cursor, progress.persisted),
                bounds.heartbeat_timeout_s,
                renew=control_tick,
            )
        )
        try:
            with suppress(TimeoutError):
                async with asyncio.timeout(bounds.max_duration_s):
                    while True:
                        pumped = await self._pump(
                            request, harness, identity, fields, turn, writer, signals, progress
                        )
                        if pumped.history is not None:
                            pumped = await self._replay_history(
                                harness,
                                identity,
                                fields,
                                turn,
                                writer,
                                signals,
                                progress,
                                pumped.history,
                            )
                            if pumped.terminal is None:
                                if progress.max_frames and progress.observed >= progress.max_frames:
                                    break
                                continue
                        if pumped.injection is not None:
                            replaced = await self._interrupt(
                                request,
                                harness,
                                identity,
                                fields,
                                turn,
                                pumped.injection,
                                writer,
                                signals,
                                progress,
                                cancel_first=True,
                            )
                            if isinstance(replaced, LaneTurnResult):
                                return replaced
                            turn = replaced
                            continue
                        if pumped.terminal is None:
                            break
                        pending_history = await self._pending_history(identity, turn)
                        if pending_history is not None:
                            reconciled = await self._replay_history(
                                harness,
                                identity,
                                fields,
                                turn,
                                writer,
                                signals,
                                progress,
                                pending_history,
                            )
                            if await self._pending_history(identity, turn) is not None:
                                break  # retain the owner until native history is acknowledged
                            if reconciled.terminal is not None:
                                pumped = reconciled
                        if isinstance(harness, HistoryReconciliationLane) and turn.native_turn_ref:
                            try:
                                await self._states.close_history_window(
                                    identity.request_scope,
                                    identity.harness_execution_id,
                                    owner=progress.owner,
                                    native_turn_ref=turn.native_turn_ref,
                                )
                            except HistoryDeferred:
                                break  # enqueue won the row lock; next segment drains it
                        assert pumped.terminal is not None
                        following = await self._after_terminal(
                            request,
                            harness,
                            identity,
                            fields,
                            turn,
                            pumped.terminal,
                            writer,
                            signals,
                            progress,
                        )
                        if isinstance(following, LaneTurnResult):
                            return following
                        if following is None:
                            terminal = pumped.terminal
                            break
                        turn = following
        except HistoryDeferred:
            pass  # retain the current turn; no replacement or settlement was issued
        except asyncio.CancelledError:
            if signals.cancel_requested():
                # A requested cancel, not a worker shutdown, pause or reset.
                with suppress(Exception):
                    receipt = await harness.cancel_turn(
                        CancelTurnRequest(**fields, turn=turn, reason="command")
                    )
                    await self._cancel_acknowledged(request.operation, identity, receipt)
                if progress.observed and progress.cursor is not None:
                    # The cursor names only frames whose append already succeeded (new
                    # or duplicate). Cancellation skips the normal segment flush below;
                    # retain this resume point so its tail need not replay that prefix.
                    try:
                        await self._states.assert_owner(
                            identity.request_scope, identity.harness_execution_id, progress.owner
                        )
                        await self._states.record(
                            identity.request_scope,
                            identity.harness_execution_id,
                            segment_update(progress.cursor, self._clock()),
                            owner=progress.owner,
                        )
                    except StaleSessionOwner:
                        pass  # A takeover owns the cursor; preserve the original cancellation.
                    except Exception:
                        _LOGGER.warning("cancel resume cursor was not recorded", exc_info=True)
            raise
        except NativeTurnLost:
            return await self._lost(request, identity, reason="native_turn_lost")
        finally:
            ticker.cancel()
            with suppress(asyncio.CancelledError):
                await ticker
        native = NativeRefs(
            session_ref=turn.session.native_session_ref, turn_ref=turn.native_turn_ref
        )
        now = self._clock()
        scope, heid = identity.request_scope, identity.harness_execution_id
        await self._states.assert_owner(scope, heid, progress.owner)
        await self._states.record(scope, heid, segment_update(progress.cursor, now))
        if terminal is None:
            await self._project(writer.handle, identity)
            # The segment ends, the session does not: the manager keeps it for the next one.
            self._sessions.retain(scope, heid, progress.owner, session=turn.session, turn=turn)
            return LaneTurnResult(
                done=False,
                cursor=progress.cursor,
                segment_no=request.segment_no,
                frames_persisted=progress.persisted,
                frames_duplicate=progress.duplicates,
                native=native,
            )
        facts = harness.closing_facts(turn, terminal)
        return await self._settle(
            request,
            harness,
            identity,
            turn,
            facts,
            attempt=attempt,
            native=native,
            cursor=progress.cursor,
            persisted=progress.persisted,
            duplicates=progress.duplicates,
            handle=writer.handle,
            owner=progress.owner,
            final_text=read_final_text(harness, turn, terminal),
        )

    async def _renew(
        self, identity: LaneExecutionIdentity, progress: _SegmentProgress, heartbeat_s: int
    ) -> None:
        """Extend the owner's lease while it observes; a takeover fences this segment out."""

        if progress.fenced_out is not None:
            return
        try:
            progress.owner = await self._states.renew_owner(
                identity.request_scope,
                identity.harness_execution_id,
                progress.owner,
                expires_at=self._clock() + self._sessions.lease_for(heartbeat_s),
            )
            self._sessions.renewed(
                identity.request_scope, identity.harness_execution_id, progress.owner
            )
        except StaleSessionOwner as error:
            progress.fenced_out = error

    async def _pump(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        turn: TurnHandle,
        writer: FrameWriter,
        signals: TurnSignals,
        progress: _SegmentProgress,
    ) -> _Pumped:
        """Observe the turn from the progress cursor, persisting before each heartbeat, until
        a terminal frame, the frame bound, the end of the stream, or an injected command."""

        bounds = request.segment
        stream: AsyncIterator[LaneFrame] = harness.observe(
            ObserveRequest(**fields, turn=turn, after=progress.cursor, max_frames=bounds.max_frames)
        )
        watch = self._watch(request, frozenset(progress.stale_steers))
        history = asyncio.create_task(self._watch_history(identity, turn, progress))
        try:
            async with aclosing(stream) as frames:  # type: ignore[type-var]
                iterator = aiter(frames)
                pending: asyncio.Future[LaneFrame] | None = None
                try:
                    while True:
                        pending = asyncio.ensure_future(anext(iterator))
                        waits: set[asyncio.Future[Any]] = {pending, history}
                        if watch is not None:
                            waits.add(watch)
                        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
                        ended: _Pumped | None = None
                        if pending.done():
                            done, pending = pending, None
                            try:
                                frame = done.result()
                            except StopAsyncIteration:
                                ended = _Pumped()
                            else:
                                # A read completing with either watcher still owns a native
                                # frame. Persist it before closing/reopening the observer.
                                ended = await self._take(
                                    frame, identity, writer, signals, turn, progress
                                )
                        if ended is not None:
                            return ended
                        if history.done():
                            return _Pumped(history=history.result())
                        if watch is not None and watch.done():
                            return _Pumped(injection=watch.result())
                finally:
                    # Close only the owner's observer, after its outstanding read ends.
                    if pending is not None:
                        pending.cancel()
                        with suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                            await pending
        finally:
            history.cancel()
            if watch is not None:
                watch.cancel()
            await asyncio.gather(
                history, *(() if watch is None else (watch,)), return_exceptions=True
            )

    async def _pending_history(
        self, identity: LaneExecutionIdentity, turn: TurnHandle
    ) -> HistoryRequest | None:
        state = await self._states.load(identity.request_scope, identity.harness_execution_id)
        journal = None if state is None else state.history_reconciliation
        if journal is None or not journal.pending:
            return None
        requested = journal.requested
        if requested.generation < turn.session.generation:
            return requested  # Only the current owner may persist its terminal rejection.
        if (
            requested.generation != turn.session.generation
            or requested.native_session_ref != turn.session.native_session_ref
            or requested.native_turn_ref != turn.native_turn_ref
        ):
            return None
        return requested

    async def _watch_history(
        self, identity: LaneExecutionIdentity, turn: TurnHandle, progress: _SegmentProgress
    ) -> HistoryRequest:
        while True:
            requested = await self._pending_history(identity, turn)
            if requested is not None:
                authority = await self._states.refresh_history_authority(
                    requested, owner=progress.owner, at=self._clock()
                )
                if not authority.pending:
                    requested = None
            if (
                requested is not None
                and progress.history_passes < 3
                and requested.watermark != progress.history_attempted
            ):
                return requested
            await asyncio.sleep(HISTORY_POLL_SECONDS)

    async def _replay_history(
        self,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        turn: TurnHandle,
        writer: FrameWriter,
        signals: TurnSignals,
        progress: _SegmentProgress,
        requested: HistoryRequest,
    ) -> _Pumped:
        authority = await self._states.refresh_history_authority(
            requested, owner=progress.owner, at=self._clock()
        )
        if authority.rejects(requested):
            return _Pumped()
        if progress.history_passes >= 3:
            return _Pumped()
        progress.history_attempted = requested.watermark
        progress.history_passes += 1
        if not isinstance(harness, HistoryReconciliationLane):
            return _Pumped()
        terminal: LaneFrame | None = None
        scanned = 0
        try:
            async with asyncio.timeout(HISTORY_TIMEOUT_SECONDS):
                stream = harness.reconcile_history(
                    ObserveRequest(
                        **fields, turn=turn, after=progress.cursor, max_frames=MAX_HISTORY_FRAMES
                    )
                )
                async with aclosing(stream):  # type: ignore[type-var]
                    async for item in stream:
                        if isinstance(item, HistoryReplayComplete):
                            resolved = await self._states.acknowledge_history(
                                requested,
                                owner=progress.owner,
                                cursor=progress.cursor,
                                at=self._clock(),
                            )
                            if not resolved.covers(requested) and not resolved.rejects(requested):
                                raise HistoryReplayIncomplete("history disposition remains pending")
                            # Native terminal frames remain valid when only the webhook's
                            # authority expired during the read. Rejection never wakes ingress.
                            return _Pumped(terminal=terminal)
                        scanned += 1
                        if scanned > MAX_HISTORY_FRAMES:
                            raise HistoryReplayIncomplete("native history frame bound")
                        ended = await self._take(item, identity, writer, signals, turn, progress)
                        if item.terminal:
                            terminal = item
                        elif ended is not None:
                            return _Pumped()
        except (HistoryReplayIncomplete, TimeoutError):
            pass  # pending durable receipt survives; normal observation resumes at its cursor
        return _Pumped()

    async def _take(
        self,
        frame: LaneFrame,
        identity: LaneExecutionIdentity,
        writer: FrameWriter,
        signals: TurnSignals,
        turn: TurnHandle,
        progress: _SegmentProgress,
    ) -> _Pumped | None:
        if progress.fenced_out is not None:
            # Another owner took the session over: this segment stops writing here.
            raise progress.fenced_out
        await self._persist(frame, identity, writer, turn, progress)
        # Persisted first, then the heartbeat (the resume hint).
        signals.heartbeat(progress.cursor, progress.persisted)
        if frame.terminal:
            return _Pumped(terminal=frame)
        if progress.max_frames and progress.observed >= progress.max_frames:
            return _Pumped()
        return None

    async def _persist(
        self,
        frame: LaneFrame,
        identity: LaneExecutionIdentity,
        writer: FrameWriter,
        turn: TurnHandle,
        progress: _SegmentProgress,
    ) -> None:
        observation = self._observation(
            frame, identity, session_ref=turn.session.native_session_ref
        )
        receipt = await writer.write([observation])
        if receipt.stale:
            raise StaleSessionOwner("native frame was refused by the execution fence")
        progress.persisted += receipt.new
        progress.duplicates += receipt.duplicate
        progress.observed += 1
        progress.cursor = frame.cursor
        if self._preparations is not None:
            # MO-16/MO-34: a Discovery Proof or a fired hook raises the readiness ladder.
            evidence = f"frame:{frame.provider_key}"
            report = discovery_report_of(observation.raw_kind, observation.body)
            if report is not None:
                await self._preparations.discovered(identity, report, evidence_ref=evidence)
            else:
                await self._preparations.observed(identity, observation.kind, evidence_ref=evidence)

    # --- FT-G4 interrupt_and_inject: cancel_and_replace on a Session Lane ---------------------

    def _watch(
        self, request: LaneTurnRequest, skip: frozenset[str] = frozenset()
    ) -> asyncio.Task[MailboxEntry] | None:
        """Watch the mailbox for an `interrupt_and_inject` this turn would take (`skip`: the
        commands a stale steer requeued for the next boundary, not for this turn)."""

        if self._injections is None or self._mailbox is None:
            return None
        node = unit_boundary(request.operation)
        if node is None:
            return None
        injections = self._injections

        async def poll() -> MailboxEntry:
            while True:
                entry = await injections.pending(request.operation, node)
                if entry is not None and entry.command_id not in skip:
                    return entry
                await asyncio.sleep(injections.settings.poll_seconds)

        return asyncio.create_task(poll())

    def _inject_prefix(self, operation: OperationExecutionRequest) -> str:
        return f"{operation.idempotency_key}:inject:"

    async def _claimed_injection(self, operation: OperationExecutionRequest) -> MailboxEntry | None:
        """An injected command this turn claimed but never replaced (a retried replacement)."""

        if self._mailbox is None:
            return None
        prefix = self._inject_prefix(operation)
        for entry in await self._mailbox.list_entries(
            operation.request_scope, operation.identity.run_id
        ):
            if (
                entry.kind == INJECT_KIND
                and entry.state == MailboxState.DELIVERED
                and (entry.delivery_key or "").startswith(prefix)
            ):
                return entry
        return None

    async def _interrupt(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        turn: TurnHandle,
        entry: MailboxEntry,
        writer: FrameWriter,
        signals: TurnSignals,
        progress: _SegmentProgress,
        *,
        cancel_first: bool,
    ) -> TurnHandle | LaneTurnResult:
        """SPEC-07 section 7 `interrupt_and_inject` on a lane without a native steer: cancel
        the running turn, settle its Uncertain Effects (a running tool call without a
        completion parks the unit `in_doubt`), then send a replacement turn carrying the
        injected item; the Delivery Report says `cancel_and_replace`."""

        assert self._mailbox is not None and self._injections is not None
        operation = request.operation
        describe = harness.describe()
        lane_profile = describe.lane_profile
        node = unit_boundary(operation)
        # MP-06: the frozen per-profile semantics and the describe must agree; no fallback.
        semantics = resolve_interrupt_mode(lane_profile, describe, harness)
        scope, run_id = operation.request_scope, operation.identity.run_id
        if node is None or semantics not in {"cancel_and_replace", "cooperative_inject"}:
            await self._mailbox.inject_unsupported(scope, entry, lane_profile=lane_profile)
            return turn  # the running turn is never interrupted
        if signals.cancel_requested():
            return turn  # a cancel owns the turn now; nothing replaces or steers it
        old_ref = turn.native_turn_ref
        key = f"{self._inject_prefix(operation)}{entry.command_id}"
        if semantics == "cooperative_inject":
            return await self._steer(request, harness, identity, turn, entry, key, node, progress)
        if isinstance(harness, HistoryReconciliationLane) and old_ref:
            pending_history = await self._pending_history(identity, turn)
            if pending_history is not None:
                await self._replay_history(
                    harness, identity, fields, turn, writer, signals, progress, pending_history
                )
                if await self._pending_history(identity, turn) is not None:
                    raise HistoryDeferred("native_history_pending")
        delivered = await self._mailbox.deliver(
            scope,
            run_id,
            delivery_key=key,
            family=node[0],
            node_key=node[1],
            iteration_start=False,
            lane_profile=lane_profile,
            kinds=(INJECT_KIND,),
            cancelled_turn_ref=old_ref,
        )
        if not delivered:
            return turn  # another boundary took it first; keep observing this turn
        follow_up = await self._injections.follow_up_segment(operation, delivered, key)
        if isinstance(harness, TurnTextStaging):
            harness.stage_turn(fields["harness_execution_id"], key, follow_up.content)
        replacement = SendTurnRequest(
            **{
                **fields,
                "idempotency_key": (
                    f"{identity.harness_execution_id}:{request.generation}{_REPLACE_KEY}{old_ref}"
                ),
            },
            session=turn.session,
            turn_no=turn.turn_no + 1,
            instruction_ref=key,
        )

        async def unsettled() -> tuple[str, ...]:
            return await self._open_effects(identity, request.generation, old_ref)

        async def persist(frame: LaneFrame) -> None:
            await self._persist(frame, identity, writer, turn, progress)
            signals.heartbeat(progress.cursor, progress.persisted)

        owner = progress.owner

        async def send(replacing: SendTurnRequest) -> TurnHandle:
            # The replacement is a new governed dispatch: journaled, fenced, sent once.
            return (await self._dispatch_send(request, harness, identity, owner, replacing)).handle

        if isinstance(harness, HistoryReconciliationLane) and old_ref:
            # Admission and closure serialize before cancellation or a replacement send.
            # A claimed mailbox delivery is replayable if enqueue wins this boundary.
            await self._states.close_history_window(
                identity.request_scope,
                identity.harness_execution_id,
                owner=progress.owner,
                native_turn_ref=old_ref,
            )
        # The interrupted turn's Uncertain Effects, before the cancel (reported as settled).
        uncertain = await unsettled()
        try:
            replaced = await cancel_and_replace_turn(
                harness,
                cancel=CancelTurnRequest(**fields, turn=turn, reason="interrupt_and_inject"),
                replacement=replacement,
                unsettled=unsettled,
                settings=self._injections.settings,
                after=progress.cursor,
                on_frame=persist,
                cancel_first=cancel_first,
                send=send,
                on_cancelled=lambda receipt: self._cancel_acknowledged(
                    operation, identity, receipt
                ),
            )
            new_turn = replaced.handle
            if new_turn.status == "busy" or new_turn.native_turn_ref is None:
                new_turn = await self._send_when_idle(harness, fields, replacement, send)
        except DispatchFenced:
            # A Stop Fence landed while the old turn drained: no replacement, ever. The old
            # turn is cancelled and its pre-fence effects keep their disposition.
            await self._mailbox.turn_not_started(scope, run_id, delivery_key=key)
            return await self._settle(
                request,
                harness,
                identity,
                turn,
                ClosingFacts(
                    native_status="cancelled",
                    error_code="cancelled_by_command",
                    usage=await self._turn_usage(harness, identity, request.generation, old_ref),
                ),
                attempt=None,
                native=NativeRefs(session_ref=turn.session.native_session_ref, turn_ref=old_ref),
                cursor=progress.cursor,
                persisted=progress.persisted,
                duplicates=progress.duplicates,
                handle=writer.handle,
                cancelled_by_command=True,
                owner=owner,
            )
        except _DispatchParked as parked:
            # The replacement's earlier dispatch is ambiguous: never send a second one.
            await self._mailbox.inject_parked(
                scope,
                run_id,
                delivery_key=key,
                lane_profile=lane_profile,
                cancelled_turn_ref=old_ref,
                pending_effect_ids=(),
            )
            return await self._park(request, identity, owner, reason=parked.reason)
        except InjectionParked as parked:
            await self._mailbox.inject_parked(
                scope,
                run_id,
                delivery_key=key,
                lane_profile=lane_profile,
                cancelled_turn_ref=old_ref,
                pending_effect_ids=parked.pending_effect_ids,
            )
            result = await self._boundary.lane_in_doubt(operation, reason="unsettled_effect_claims")
            return LaneTurnResult(
                done=True,
                cursor=progress.cursor,
                segment_no=request.segment_no,
                frames_persisted=progress.persisted,
                frames_duplicate=progress.duplicates,
                native=NativeRefs(session_ref=turn.session.native_session_ref, turn_ref=old_ref),
                closing_facts=ClosingFacts(
                    native_status="in_doubt", error_code="unsettled_effect_claims"
                ),
                operation_result=result.model_dump(mode="json"),
            )
        await self._states.record(
            identity.request_scope,
            identity.harness_execution_id,
            LaneExecutionUpdate(
                native_turn_ref=new_turn.native_turn_ref, supersedes_turn_ref=old_ref
            ),
        )
        await self._mailbox.inject_replaced(
            scope,
            run_id,
            delivery_key=key,
            lane_profile=lane_profile,
            delivered_semantics="cancel_and_replace",
            cancelled_turn_ref=old_ref,
            replacement_turn_ref=new_turn.native_turn_ref or f"turn:{new_turn.turn_no}",
            settled_effect_ids=tuple(dict.fromkeys((*uncertain, *replaced.settled_effect_ids))),
            session_ref=turn.session.native_session_ref,
        )
        # The replacement turn is observed from its start (its own provider keys).
        progress.cursor = None
        signals.heartbeat(None, progress.persisted)
        return new_turn

    async def _send_when_idle(
        self,
        harness: SessionLane,
        fields: dict[str, Any],
        request: SendTurnRequest,
        send: Callable[[SendTurnRequest], Awaitable[TurnHandle]],
    ) -> TurnHandle:
        """A cancelled run can take a moment to release the agent (`409 agent_busy`)."""

        session = request.session
        for _attempt in range(30):
            observed = await harness.status(StatusRequest(**fields, session=session))
            if observed.idle or observed.terminal:
                sent = await send(request)
                if sent.status != "busy" and sent.native_turn_ref is not None:
                    return sent
            await asyncio.sleep(0.5)
        raise NativeTurnLost("the agent never became idle for the replacement turn")

    async def _steer(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        turn: TurnHandle,
        entry: MailboxEntry,
        key: str,
        node: tuple[Any, str],
        progress: _SegmentProgress,
    ) -> TurnHandle:
        """`cooperative_inject`: steer the exact active native turn. A turn that completed
        concurrently is a typed `stale_target`: the command is requeued (same command id) for
        the next boundary and never lands on another turn."""

        assert self._mailbox is not None and isinstance(harness, SteeringLane)
        operation = request.operation
        scope, run_id = operation.request_scope, operation.identity.run_id
        lane_profile = harness.describe().lane_profile
        delivered = await self._mailbox.deliver(
            scope,
            run_id,
            delivery_key=key,
            family=node[0],
            node_key=node[1],
            iteration_start=False,
            lane_profile=lane_profile,
            kinds=(INJECT_KIND,),
        )
        if not delivered:
            return turn
        # KR3 (2026-11-05): the steered text is staged on the lane under the instruction
        # ref before the native steer, as a replacement send is; a `SteeringLane` reads it
        # from `stage_turn`, never from the mailbox.
        assert self._injections is not None
        follow_up = await self._injections.follow_up_segment(operation, delivered, key)
        if isinstance(harness, TurnTextStaging):
            harness.stage_turn(str(identity.harness_execution_id), key, follow_up.content)
        fenced = await self._fence_denies(
            request,
            DispatchRecord(
                kind="send",
                idempotency_key=f"{key}:steer:{turn.native_turn_ref}",
                expected_generation=request.generation,
                instruction_digest=instruction_digest(
                    kind="send",
                    instruction_ref=key,
                    binding_digest=_binding_digest(operation),
                    turn_no=turn.turn_no,
                ),
                owner_ref=progress.owner.owner_ref,
                owner_epoch=progress.owner.epoch,
                intended_at=self._clock(),
            ),
        )
        if fenced is not None:
            await self._mailbox.turn_not_started(scope, run_id, delivery_key=key)
            progress.stale_steers.add(entry.command_id)
            return turn
        steered = await harness.steer(turn, instruction_ref=key)
        if steered.outcome != "applied" or steered.target_turn_ref not in {
            None,
            turn.native_turn_ref,
        }:
            await self._mailbox.turn_not_started(scope, run_id, delivery_key=key)
            progress.stale_steers.add(entry.command_id)
            _LOGGER.info(
                "steer of %s for %s is stale_target; requeued for the next boundary",
                turn.native_turn_ref,
                entry.command_id,
            )
            return turn
        await self._mailbox.inject_replaced(
            scope,
            run_id,
            delivery_key=key,
            lane_profile=lane_profile,
            delivered_semantics="cooperative_inject",
            cancelled_turn_ref=None,
            replacement_turn_ref=turn.native_turn_ref or f"turn:{turn.turn_no}",
            session_ref=turn.session.native_session_ref,
        )
        return turn

    async def _frames_of(
        self, identity: LaneExecutionIdentity, generation: int
    ) -> tuple[ProviderFrame, ...]:
        if self._reader is None:
            return ()
        frames: list[ProviderFrame] = []
        after = 0
        while True:
            page = await self._reader.frames_for_execution(
                identity.request_scope,
                identity.harness_execution_id,
                generation,
                after_ordinal=after,
                limit=10_000,
            )
            if not page:
                break
            frames.extend(page)
            after = page[-1].arrival_ordinal
            if len(page) < 10_000:
                break
        return tuple(frames)

    async def _open_effects(
        self, identity: LaneExecutionIdentity, generation: int, turn_ref: str | None
    ) -> tuple[str, ...]:
        return open_tool_calls(await self._frames_of(identity, generation), turn_ref)

    async def _turn_usage(
        self,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        generation: int,
        turn_ref: str | None,
    ) -> UsageReport:
        """Attributed cancellation usage; a native-run lane attributes it by its own rules
        (Cursor requires a cumulative native run result)."""

        frames = await self._frames_of(identity, generation)
        if isinstance(harness, NativeRunUsageLane):
            return harness.cancelled_turn_usage(frames, turn_ref)
        return usage_from_frames(frames, turn_ref)

    # --- terminal frame: retried replacement, continuation handover ---------------------------

    async def _after_terminal(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        turn: TurnHandle,
        frame: LaneFrame,
        writer: FrameWriter,
        signals: TurnSignals,
        progress: _SegmentProgress,
    ) -> TurnHandle | LaneTurnResult | None:
        """The turn after a terminal frame, if any: the replacement of an injection claimed
        before a lost worker (the cancelled turn is already terminal), or the continuation
        turn on a freshly hydrated agent. None settles the session."""

        facts = harness.closing_facts(turn, frame)
        if facts.native_status == "cancelled":
            claimed = await self._claimed_injection(request.operation)
            if claimed is not None and self._injections is not None:
                return await self._interrupt(
                    request,
                    harness,
                    identity,
                    fields,
                    turn,
                    claimed,
                    writer,
                    signals,
                    progress,
                    cancel_first=False,
                )
        if facts.native_status != "finished":
            return None
        if isinstance(harness, SessionHandoverLane):
            handover = await harness.pending_handover(fields["harness_execution_id"])
            if handover is not None:
                return await self._hand_over(
                    request, harness, identity, fields, turn, handover, writer, progress
                )
        # CM-09: one authored missing-output allowance uses the normal dispatch journal,
        # stop fence, busy boundary and native identity supersession. A replay of the
        # followup's terminal frame cannot create a third run.
        followup = getattr(harness, "missing_output_followup", None)
        if (
            callable(followup)
            and facts.missing_outputs
            and request.operation.budget_limits.get("model.turns", 0) > turn.turn_no
            and isinstance(harness, TurnTextStaging)
        ):
            key = f"{identity.harness_execution_id}:{request.generation}:missing-outputs:1"
            state = await self._states.load(identity.request_scope, identity.harness_execution_id)
            recorded = state.dispatch("send", key) if state is not None else None
            consumed = (
                recorded is not None
                and recorded.phase == "acknowledged"
                and recorded.native_ref == turn.native_turn_ref
            )
            text = None if consumed else await followup(turn, facts)
            if text is not None:
                harness.stage_turn(str(identity.harness_execution_id), key, text)
                send_request = SendTurnRequest(
                    **{**fields, "idempotency_key": key},
                    session=turn.session,
                    turn_no=turn.turn_no + 1,
                    instruction_ref=key,
                )

                async def send_followup(send_request: SendTurnRequest) -> TurnHandle:
                    return (
                        await self._dispatch_send(
                            request, harness, identity, progress.owner, send_request
                        )
                    ).handle

                try:
                    sent = await send_followup(send_request)
                    if sent.status == "busy" or sent.native_turn_ref is None:
                        sent = await self._send_when_idle(
                            harness, fields, send_request, send_followup
                        )
                except DispatchFenced:
                    return await self._fenced_handover(
                        request, harness, identity, turn, writer, progress
                    )
                except _DispatchParked as parked:
                    return await self._park(request, identity, progress.owner, reason=parked.reason)
                await self._states.record(
                    identity.request_scope,
                    identity.harness_execution_id,
                    LaneExecutionUpdate(
                        native_turn_ref=sent.native_turn_ref,
                        supersedes_turn_ref=turn.native_turn_ref,
                    ),
                )
                progress.cursor = None
                signals.heartbeat(None, progress.persisted)
                return sent
        if self._continuations is None:
            return None
        return await self._continuation_boundary(
            request, harness, identity, turn, facts, writer, signals, progress
        )

    # --- MP-12: the safe boundary (context pressure, native compaction, continuation) --------

    async def _continuation_boundary(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        turn: TurnHandle,
        facts: ClosingFacts,
        writer: FrameWriter,
        signals: TurnSignals,
        progress: _SegmentProgress,
    ) -> LaneTurnResult | None:
        """At a turn's `finished` frame: measure pressure, compact natively where qualified,
        and when the session must continue in a fresh generation end the segment without
        settling (the workflow drives the phase machine). `None` settles as before."""

        assert self._continuations is not None
        coordinator = self._continuations
        operation = request.operation
        scope, heid = identity.request_scope, identity.harness_execution_id
        session_ref = turn.session.native_session_ref or str(heid)
        describe = harness.describe()
        assessment = await self._observe_pressure(
            harness, identity, turn, writer, signals, progress, turns_in_session=request.turn_no
        )
        pending = await coordinator.pending(scope, identity.run_key, source_session_ref=session_ref)
        continues = bool(facts.missing_outputs)
        can_compact = isinstance(harness, CompactingLane)
        route = (
            compaction_route(
                coordinator.policy,
                assessment,
                compaction_control=describe.compaction_control,
                lane_can_compact=can_compact,
            )
            if continues
            else "none"
        )
        if route == "native":
            after = await self._native_compaction(
                harness, identity, turn, writer, signals, progress, assessment
            )
            route = "none"
            if after is None:
                route = coordinator.policy.fallback
            elif after.level == "hard":
                route = coordinator.policy.fallback
                assessment = after
        elif continues and assessment.level != "none" and route != "none":
            await self._pressure_note(
                identity,
                turn,
                writer,
                signals,
                progress,
                "native_compaction_unavailable",
                native_unavailable_reason(describe.compaction_control, can_compact),
            )
        if route == "fail":
            # The policy requires a native compaction the lane cannot provide: recorded,
            # and the unit settles on its own completion evaluation (nothing is invented).
            await self._pressure_note(
                identity,
                turn,
                writer,
                signals,
                progress,
                "native_compaction_required",
                (
                    "policy requires native compaction; "
                    + native_unavailable_reason(describe.compaction_control, can_compact)
                ),
            )
            route = "none"
        if pending is None and route == "sealed_checkpoint":
            kind = (
                ContinuationTriggerKind.CONTEXT_HEALTH_HARD
                if assessment.level == "hard"
                else ContinuationTriggerKind.CONTEXT_HEALTH_SOFT
            )
            pending = await coordinator.request(
                kind,
                f"pressure://{heid}/{turn.native_turn_ref or turn.turn_no}/{request.turn_no}",
                request_scope=scope,
                run_key=identity.run_key,
                activation_key=identity.activation_key,
                logical_execution_id=identity.activation_key,
                lane_profile=identity.lane_profile,
                source_session_ref=session_ref,
            )
        if pending is None:
            return None
        # The safe boundary of a continuation: the turn finished, the operation did not.
        now = self._clock()
        await self._states.assert_owner(scope, heid, progress.owner)
        await self._states.record(scope, heid, segment_update(progress.cursor, now))
        await self._project(writer.handle, identity)
        self._sessions.retain(scope, heid, progress.owner, session=turn.session, turn=turn)
        _LOGGER.info(
            "operation %s reached a continuation boundary (transfer %s, trigger %s)",
            operation.identity.semantic_key,
            pending.transfer_id,
            pending.trigger.kind.value,
        )
        return LaneTurnResult(
            done=False,
            cursor=progress.cursor,
            segment_no=request.segment_no,
            frames_persisted=progress.persisted,
            frames_duplicate=progress.duplicates,
            native=NativeRefs(
                session_ref=turn.session.native_session_ref, turn_ref=turn.native_turn_ref
            ),
            closing_facts=facts,
            usage_estimate=facts.usage,
        )

    async def _observe_pressure(
        self,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        turn: TurnHandle,
        writer: FrameWriter,
        signals: TurnSignals,
        progress: _SegmentProgress,
        *,
        turns_in_session: int,
        label: str = "pressure",
    ) -> PressureAssessment:
        """The lane's occupancy (or `unknown`) through the policy, persisted as a frame."""

        assert self._continuations is not None
        occupancy: ContextOccupancy | None = None
        if isinstance(harness, ContextOccupancyLane):
            occupancy = await harness.context_occupancy(
                str(identity.harness_execution_id), turn.session, turn
            )
        if occupancy is None:
            occupancy = ContextOccupancy.unknown("the lane exposes no context occupancy")
        assessment = self._continuations.assess(occupancy, turns_in_session=turns_in_session)
        await self._write_frame(
            identity,
            turn,
            writer,
            signals,
            progress,
            provider_key=f"mc:{label}:{identity.harness_execution_id}:{turn.native_turn_ref}:{turns_in_session}",
            raw_kind="mc.context_pressure",
            kind=FrameKind.STATUS,
            body={**assessment.observation(), "occupancy_source": occupancy.source},
        )
        return assessment

    async def _native_compaction(
        self,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        turn: TurnHandle,
        writer: FrameWriter,
        signals: TurnSignals,
        progress: _SegmentProgress,
        assessment: PressureAssessment,
    ) -> PressureAssessment | None:
        """The lane's explicit compaction, serialized at the turn boundary: intent, start and
        completion are frames; the epoch advances only on completion and nothing else moves
        (no iteration, no budget, no retry counter). `None` means it failed."""

        assert isinstance(harness, CompactingLane)
        frames = await self._frames_of(identity, turn.session.generation)
        # A compaction Mission Control requested is observed twice when the provider also
        # emits its own completion (Codex `thread/compacted`); a provider-automatic one only
        # natively. Each count alone never double-counts, so the epoch follows the larger.
        ours = sum(
            1
            for frame in frames
            if frame.kind == FrameKind.AFTER_COMPACTION
            and frame.raw_kind == MC_AFTER_COMPACTION_RAW_KIND
        )
        native = sum(
            1
            for frame in frames
            if frame.kind == FrameKind.AFTER_COMPACTION
            and frame.raw_kind != MC_AFTER_COMPACTION_RAW_KIND
        )
        epoch = 1 + max(ours, native)
        heid = str(identity.harness_execution_id)
        await self._write_frame(
            identity,
            turn,
            writer,
            signals,
            progress,
            provider_key=f"mc:compaction:{heid}:{epoch}:before",
            raw_kind="custom.mc.before_compaction",
            kind=FrameKind.BEFORE_COMPACTION,
            body={"epoch": epoch, "trigger": "explicit", "reason": assessment.reason},
        )
        try:
            receipt = await harness.compact(
                CompactionRequest(
                    harness_execution_id=heid,
                    session=turn.session,
                    turn=turn,
                    epoch=epoch,
                    reason=f"context_pressure_{assessment.level}",
                )
            )
        except Exception as error:
            _LOGGER.warning("native compaction failed on %s: %s", identity.lane_profile, error)
            await self._pressure_note(
                identity, turn, writer, signals, progress, "native_compaction_failed", str(error)
            )
            return None
        if not receipt.completed:
            await self._pressure_note(
                identity,
                turn,
                writer,
                signals,
                progress,
                "native_compaction_failed",
                receipt.detail or "the provider did not complete the compaction",
            )
            return None
        await self._write_frame(
            identity,
            turn,
            writer,
            signals,
            progress,
            provider_key=f"mc:compaction:{heid}:{epoch}:after",
            raw_kind=MC_AFTER_COMPACTION_RAW_KIND,
            kind=FrameKind.AFTER_COMPACTION,
            body={
                "epoch": epoch,
                "cutoff_index": f"explicit:{epoch}",
                "summary_digest": receipt.summary_digest,
                "native_ref": receipt.native_ref,
            },
        )
        if receipt.occupancy_after is not None:
            assert self._continuations is not None
            after = self._continuations.assess(
                receipt.occupancy_after, turns_in_session=assessment.turns_in_session
            )
            await self._write_frame(
                identity,
                turn,
                writer,
                signals,
                progress,
                provider_key=f"mc:remeasure:{heid}:{epoch}",
                raw_kind="mc.context_pressure",
                kind=FrameKind.STATUS,
                body={**after.observation(), "occupancy_source": receipt.occupancy_after.source},
            )
            return after
        return await self._observe_pressure(
            harness,
            identity,
            turn,
            writer,
            signals,
            progress,
            turns_in_session=assessment.turns_in_session,
            label=f"remeasure:{epoch}",
        )

    async def _pressure_note(
        self,
        identity: LaneExecutionIdentity,
        turn: TurnHandle,
        writer: FrameWriter,
        signals: TurnSignals,
        progress: _SegmentProgress,
        event: str,
        detail: str,
    ) -> None:
        await self._write_frame(
            identity,
            turn,
            writer,
            signals,
            progress,
            provider_key=f"mc:{event}:{identity.harness_execution_id}:{turn.native_turn_ref}",
            raw_kind=f"mc.{event}",
            kind=FrameKind.STATUS,
            body={"event": event, "detail": detail[:1_024]},
        )

    async def _write_frame(
        self,
        identity: LaneExecutionIdentity,
        turn: TurnHandle,
        writer: FrameWriter,
        signals: TurnSignals,
        progress: _SegmentProgress,
        *,
        provider_key: str,
        raw_kind: str,
        kind: FrameKind,
        body: dict[str, Any],
    ) -> None:
        del identity
        receipt = await writer.write(
            [
                FrameObservation(
                    provider_key=provider_key[:512],
                    raw_kind=raw_kind,
                    kind=kind,
                    body=body,
                    native_turn_ref=turn.native_turn_ref,
                    native_session_ref=turn.session.native_session_ref,
                )
            ]
        )
        progress.persisted += receipt.new
        progress.duplicates += receipt.duplicate
        signals.heartbeat(progress.cursor, progress.persisted)

    async def _settle_after_continuation(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        state: LaneExecutionState,
        owner: SessionOwner,
        *,
        attempt: OperationActivityAttempt | None,
    ) -> LaneTurnResult | None:
        """A continuation that ended without activating (failed, exhausted, human review)
        leaves the source turn finished at its boundary: settle it from the persisted terminal
        frame instead of observing a stream that has nothing left."""

        assert self._continuations is not None
        scope, heid = identity.request_scope, identity.harness_execution_id
        latest = await self._continuations.latest_for_execution(
            scope, identity.run_key, harness_execution_id=str(heid)
        )
        if latest is None or not latest.ended or latest.activated:
            return None
        if state.native_session_ref is None or state.native_turn_ref is None:
            return None
        terminal = next(
            (
                frame
                for frame in reversed(await self._frames_of(identity, request.generation))
                if frame.kind == FrameKind.RUN_RESULT
                and frame.native_turn_ref == state.native_turn_ref
            ),
            None,
        )
        if terminal is None:
            return None
        from mission_control.domain.frames.body import frame_body_object

        session = SessionHandle(
            lane_profile=request.lane_profile,
            harness_execution_id=str(heid),
            generation=request.generation,
            native_session_ref=state.native_session_ref,
        )
        turn = TurnHandle(
            session=session, turn_no=request.turn_no, native_turn_ref=state.native_turn_ref
        )
        frame = LaneFrame(
            harness_execution_id=str(heid),
            generation=request.generation,
            provider_key=terminal.provider_key,
            cursor=harness.resume_cursor(terminal.provider_key) or terminal.provider_key,
            kind=terminal.raw_kind,
            raw_kind=terminal.raw_kind,
            terminal=True,
            digest=terminal.body_digest,
            body=frame_body_object(
                terminal.body_excerpt, terminal.body_bytes, terminal.lifecycle_body
            ),
            native_turn_ref=terminal.native_turn_ref,
            tool_call_ref=terminal.tool_call_ref,
        )
        facts = harness.closing_facts(turn, frame)
        handle = await self._open(
            request.operation, identity, request.generation, state.native_session_ref
        )
        _LOGGER.info(
            "continuation %s ended %s without a target; settling the source turn",
            latest.transfer_id,
            latest.status.value,
        )
        return await self._settle(
            request,
            harness,
            identity,
            turn,
            facts,
            attempt=attempt,
            native=NativeRefs(session_ref=state.native_session_ref, turn_ref=state.native_turn_ref),
            cursor=state.provider_cursor,
            handle=handle,
            owner=owner,
            # The persisted body is whole only when it fit its excerpt; otherwise no final
            # text is read and an over-cap candidate fails closed.
            final_text=read_final_text(harness, turn, frame),
        )

    async def _hand_over(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        turn: TurnHandle,
        handover: SessionHandover,
        writer: FrameWriter,
        progress: _SegmentProgress,
    ) -> TurnHandle | LaneTurnResult:
        """SPEC-07 section 7 `request_continuation` (emulated): the next turn runs the fresh
        agent a sealed Continuation Checkpoint hydrated; the native session moves by an
        explicit supersession and the new session's `session_init` frame confirms it.

        MP-12 decision on the MP-06 open item: a handover dispatch the Stop Fence denies
        settles the unit `cancelled` (the fence is the admitted immediate cancel; nothing
        reached the target; the source turn is already terminal); an *ambiguous* handover
        dispatch parks `in_doubt` as before (the target may have accepted the turn)."""

        assert isinstance(harness, SessionHandoverLane)
        new_session = handover.session
        await writer.write(
            [
                FrameObservation(
                    provider_key=(
                        f"continuation:{handover.transfer_id}:{new_session.native_session_ref}"
                    )[:512],
                    raw_kind="agent.created",
                    kind=FrameKind.SESSION_INIT,
                    body={
                        "agentId": new_session.native_session_ref,
                        "transfer_id": handover.transfer_id,
                        "source_session_ref": handover.source_session_ref,
                    },
                    native_session_ref=new_session.native_session_ref,
                )
            ]
        )
        try:
            sent = (
                await self._dispatch_send(
                    request,
                    harness,
                    identity,
                    progress.owner,
                    SendTurnRequest(
                        **{
                            **fields,
                            "idempotency_key": (
                                f"{identity.harness_execution_id}:{request.generation}:"
                                f"continuation:{handover.transfer_id}"
                            ),
                        },
                        session=new_session,
                        turn_no=turn.turn_no + 1,
                        instruction_ref=handover.instruction_ref,
                    ),
                )
            ).handle
        except _DispatchParked as parked:
            raise NativeTurnLost(
                f"the continuation turn was not dispatched: {parked.reason}"
            ) from None
        except DispatchFenced:
            return await self._fenced_handover(request, harness, identity, turn, writer, progress)
        if sent.native_turn_ref is None:
            raise NativeTurnLost("the continuation turn was not accepted")
        await self._states.record(
            identity.request_scope,
            identity.harness_execution_id,
            LaneExecutionUpdate(
                native_session_ref=new_session.native_session_ref,
                supersedes_session_ref=turn.session.native_session_ref,
                native_turn_ref=sent.native_turn_ref,
                supersedes_turn_ref=turn.native_turn_ref,
            ),
        )
        await harness.complete_handover(fields["harness_execution_id"], handover.transfer_id)
        progress.cursor = None
        return sent

    async def _fenced_handover(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        turn: TurnHandle,
        writer: FrameWriter,
        progress: _SegmentProgress,
    ) -> LaneTurnResult:
        """The Stop Fence denied the continuation handover: the source turn is terminal, the
        target received nothing, the unit settles `cancelled` by the fencing command."""

        return await self._settle(
            request,
            harness,
            identity,
            turn,
            ClosingFacts(
                native_status="cancelled",
                error_code="cancelled_by_command",
                usage=await self._turn_usage(
                    harness, identity, request.generation, turn.native_turn_ref
                ),
            ),
            attempt=None,
            native=NativeRefs(
                session_ref=turn.session.native_session_ref, turn_ref=turn.native_turn_ref
            ),
            cursor=progress.cursor,
            persisted=progress.persisted,
            duplicates=progress.duplicates,
            handle=writer.handle,
            cancelled_by_command=True,
            owner=progress.owner,
        )

    # --- FT-G4 wait_then_send: the mailbox at the send that carries it -------------------------

    async def _turn_started(
        self,
        operation: OperationExecutionRequest,
        harness: SessionLane,
        session: SessionHandle,
        turn: TurnHandle,
    ) -> None:
        """The send carrying the delivered entries was accepted: consume them once. Content
        queued while a turn runs waits for the following boundary (`wait_then_send`)."""

        if self._mailbox is None:
            return
        await self._mailbox.turn_started(
            operation.request_scope,
            operation.identity.run_id,
            delivery_key=operation.idempotency_key,
            lane_profile=harness.describe().lane_profile,
            session_ref=session.native_session_ref,
            turn_ref=turn.native_turn_ref,
        )

    async def _turn_not_started(self, operation: OperationExecutionRequest) -> None:
        if self._mailbox is None:
            return
        await self._mailbox.turn_not_started(
            operation.request_scope,
            operation.identity.run_id,
            delivery_key=operation.idempotency_key,
        )

    async def _turns_settled(
        self,
        operation: OperationExecutionRequest,
        lane_profile: str,
        result: OperationExecutionResult,
        turn_ref: str | None,
    ) -> None:
        if self._mailbox is None:
            return
        succeeded = result.status == "completed"
        prefix = self._inject_prefix(operation)
        keys = {operation.idempotency_key}
        try:
            for entry in await self._mailbox.list_entries(
                operation.request_scope, operation.identity.run_id
            ):
                key = entry.delivery_key or ""
                if entry.state == MailboxState.CONSUMED and key.startswith(prefix):
                    keys.add(key)
            for key in sorted(keys):
                await self._mailbox.turn_settled(
                    operation.request_scope,
                    operation.identity.run_id,
                    delivery_key=key,
                    lane_profile=lane_profile,
                    succeeded=succeeded,
                    turn_ref=turn_ref,
                )
        except Exception:
            # Receipts are evidence of an already settled unit (FT-F1 rule).
            _LOGGER.exception("mailbox settlement receipts were not recorded")

    def _observation(
        self,
        frame: LaneFrame,
        identity: LaneExecutionIdentity,
        *,
        session_ref: str | None = None,
    ) -> FrameObservation:
        lane = LaneProfile(identity.lane_profile)
        raw_kind = frame.raw_kind or frame.kind
        body = frame.body if frame.body is not None else {"excerpt": frame.excerpt}
        return FrameObservation(
            provider_key=frame.provider_key,
            raw_kind=raw_kind,
            kind=classify(lane, raw_kind, body).kind,
            body=body,
            native_turn_ref=frame.native_turn_ref,
            tool_call_ref=frame.tool_call_ref,
            provider_timestamp=frame.provider_timestamp,
            native_session_ref=session_ref,
            subordinate_ref=frame.subordinate_ref,
        )

    async def _settle(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        turn: TurnHandle | None,
        facts: ClosingFacts,
        *,
        attempt: OperationActivityAttempt | None,
        native: NativeRefs,
        cursor: str | None = None,
        persisted: int = 0,
        duplicates: int = 0,
        handle: HarnessExecutionHandle | None = None,
        cancelled_by_command: bool = False,
        owner: SessionOwner | None = None,
        final_text: str | None = None,
    ) -> LaneTurnResult:
        operation = request.operation
        scope, heid = identity.request_scope, identity.harness_execution_id
        if owner is not None:
            # A stale owner or generation never ends the session or settles the attempt.
            await self._states.assert_owner(scope, heid, owner)
        fields = self._fields(operation, identity, request.generation, "settle")
        state = await self._states.load(scope, heid)
        if not cancelled_by_command and state is not None and state.budget_controls:
            from mission_control.application.execution.harness.budget_controls import held

            if held(state.budget_controls):
                return await self._lost(
                    request, identity, reason="budget_control_requires_reconciliation"
                )
        if turn is not None:
            facts = await self._settled_usage(
                harness,
                fields,
                turn,
                facts,
                identity=identity,
                semantic_attempt_key=operation.identity.semantic_key,
                binding_digest=_binding_digest(operation),
            )
            if owner is not None:
                await self._states.assert_owner(scope, heid, owner)
            facts = await self._end_session(harness, fields, turn.session, facts)
            reconciliation = (
                harness.unknown_usage_reconciliation_reason()
                if isinstance(harness, NativeRunUsageLane)
                else None
            )
            if reconciliation is not None and facts.usage.disposition == "unknown":
                # Native completion does not erase unknown consumption. Retain the
                # operation claim/reservation for reconciliation after cleanup.
                return await self._lost(request, identity, reason=reconciliation)
        if owner is not None:
            await self._states.assert_owner(scope, heid, owner)
        # K1: the generation's cognition points, folded from its persisted frames by the
        # lane and written in the settlement transaction (`written_by: adapter`). Points are
        # evidence: a fold that fails costs the points, never the settlement.
        points = await self._turn_points(request, harness, identity, native, facts, attempt)
        result = await self._boundary.settle_lane_session(
            operation,
            facts,
            attempt=attempt,
            native_turn_ref=native.turn_ref,
            cancelled_by_command=cancelled_by_command,
            final_text=final_text,
            points=points,
        )
        await self._states.record(
            scope, heid, LaneExecutionUpdate(usage_disposition=facts.cost_disposition)
        )
        self._sessions.release(scope, heid)
        if self._placement is not None:
            await self._placement.release(scope, heid)
        if turn is not None or cancelled_by_command:
            await self._turns_settled(
                operation, harness.describe().lane_profile, result, native.turn_ref
            )
        if handle is not None:
            await self._project(handle, identity, cancelled_by_command=cancelled_by_command)
        return LaneTurnResult(
            done=True,
            cursor=cursor,
            segment_no=request.segment_no,
            frames_persisted=persisted,
            frames_duplicate=duplicates,
            native=native,
            closing_facts=facts,
            usage_estimate=facts.usage,
            operation_result=result.model_dump(mode="json"),
        )

    # --- K1/K2: cognition points of a session lane --------------------------------------------

    async def _turn_points(
        self,
        request: LaneTurnRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        native: NativeRefs,
        facts: ClosingFacts,
        attempt: OperationActivityAttempt | None,
    ) -> tuple[CognitionPointObservation, ...]:
        """The generation's points from its persisted frames, every native turn chained
        (`fold_generation_points`): the dispatch journal names the turn a `cancel_and_replace`
        interrupted, the index names the point the first turn continues from. Nothing here
        settles; a lane that is no `PointCollectingLane` writes no points, as before."""

        if not isinstance(harness, PointCollectingLane):
            return ()
        operation = request.operation
        scope, heid = identity.request_scope, identity.harness_execution_id
        try:
            frames = await self._frames_of(identity, request.generation)
            if not frames:
                return ()
            state = await self._states.load(scope, heid)
            unit = operation.runtime_unit
            attempt_ref = (
                activity_attempt_observation_id(scope, unit.unit_key, request.generation, attempt)
                if unit is not None and attempt is not None
                else None
            )
            return fold_generation_points(
                frames,
                collect=harness.turn_points,
                lane_profile=identity.lane_profile,
                harness_execution_id=str(heid),
                generation=request.generation,
                session_ref=native.session_ref,
                facts=facts,
                operation=operation,
                attempt_ref=attempt_ref,
                last_turn_no=request.turn_no,
                last_turn_ref=native.turn_ref,
                replaced=_replacement_map(state, heid),
                source_point=await self._source_point(identity, operation, request.generation),
            )
        except Exception:
            _LOGGER.warning(
                "the cognition points of %s generation %s were not folded; the settlement "
                "proceeds without them (the reconciler re-derives them)",
                heid,
                request.generation,
                exc_info=True,
            )
            return ()

    async def _source_point(
        self,
        identity: LaneExecutionIdentity,
        operation: OperationExecutionRequest,
        generation: int,
    ) -> CognitionPointRef | None:
        """The point this generation's first point continues from: the previous generation's
        result point, or (generation 1) the `fork_seed` point a fork recorded for this unit."""

        unit = operation.runtime_unit
        if self._points is None or unit is None:
            return None
        selection = (
            CognitionPointFilter(
                unit_key=unit.unit_key, execution_generation=generation - 1, role="result"
            )
            if generation > 1
            else CognitionPointFilter(unit_key=unit.unit_key, role="fork_seed")
        )
        page = await self._points.list_points(
            identity.request_scope,
            operation.identity.run_id,
            selection=selection,
            limit=50,
            cursor=None,
        )
        prior = latest_point(page.entries)
        return prior.coordinate.point if prior is not None else None

    async def _seed_head(
        self,
        identity: LaneExecutionIdentity,
        operation: OperationExecutionRequest,
        generation: int,
    ) -> LaneSeedHead | None:
        """K2: the `mc.lane_seed_head.v1` the fork saga recorded on this unit's `fork_seed`
        point (`channel_facts.seed_head`), for a generation-1 unit of a derived run; None for
        every ordinary attempt, a Deep Agents seed (namespace head, no seed head) or a read
        that fails (the session then starts fresh, logged)."""

        unit = operation.runtime_unit
        if self._points is None or unit is None or generation != 1:
            return None
        try:
            page = await self._points.list_points(
                identity.request_scope,
                operation.identity.run_id,
                selection=CognitionPointFilter(
                    unit_key=unit.unit_key, execution_generation=1, role="fork_seed"
                ),
                limit=10,
                cursor=None,
            )
            for record in page.entries:
                raw = record.channel_facts.get("seed_head")
                if isinstance(raw, Mapping):
                    return LaneSeedHead.model_validate(dict(raw))
        except Exception:
            _LOGGER.warning(
                "the seed head of %s was not read; the session starts fresh", unit.unit_key
            )
        return None

    async def _settled_usage(
        self,
        harness: SessionLane,
        fields: dict[str, Any],
        turn: TurnHandle,
        facts: ClosingFacts,
        *,
        identity: LaneExecutionIdentity | None = None,
        semantic_attempt_key: str = "",
        binding_digest: str = "",
    ) -> ClosingFacts:
        """Tokens settle per turn; cost upgrades from `estimated` only when the provider
        reports it (`feature_unavailable` leaves it estimated, never zero)."""

        if identity is not None and isinstance(harness, NativeRunUsageLane):
            from mission_control.application.frames.sink import SemanticAttemptFrameReader

            if not isinstance(self._reader, SemanticAttemptFrameReader):
                return facts.model_copy(
                    update={
                        "usage": UsageReport(disposition="unknown"),
                        "cost_disposition": "unknown",
                    }
                )
            try:
                frames = await self._reader.frames_for_semantic_attempt(
                    identity.request_scope,
                    identity.run_key,
                    identity.activation_key,
                    semantic_attempt_key,
                    binding_digest,
                    identity.lane_profile,
                )
            except ValueError:
                _LOGGER.warning("lane semantic-attempt usage attribution is unavailable")
                return facts.model_copy(
                    update={
                        "usage": UsageReport(disposition="unknown"),
                        "cost_disposition": "unknown",
                    }
                )
            reports = harness.observed_usage(frames)
            if turn.session.native_session_ref is not None and turn.native_turn_ref is not None:
                current = (turn.session.native_session_ref, turn.native_turn_ref)
                harness.attribute_closing_usage(reports, current, facts.usage)
            for session_ref, run_ref in tuple(reports):
                if not harness.attests_native_run((session_ref, run_ref)):
                    # Root-thread usage cannot attest a provider child thread.
                    continue
                session = turn.session.model_copy(update={"native_session_ref": session_ref})
                native_turn = turn.model_copy(
                    update={"session": session, "native_turn_ref": run_ref}
                )
                try:
                    reported = await harness.usage(
                        UsageRequest(**fields, session=session, turn=native_turn)
                    )
                except Exception:
                    _LOGGER.warning("Cursor native-run usage unavailable; retained observation")
                    continue
                # The provider's per-run usage read is authoritative about attribution;
                # an unknown read must not be replaced with cumulative stream counters.
                reports[(session_ref, run_ref)] = harness.reconcile_reported_usage(
                    reports[(session_ref, run_ref)], reported
                )
            summary = summarize_usage(reports)
            if summary.unknown_runs:
                _LOGGER.warning(
                    "lane usage aggregate is incomplete (%d unknown native runs)",
                    len(summary.unknown_runs),
                )
            return facts.model_copy(
                update={"usage": summary.report, "cost_disposition": summary.cost_disposition}
            )
        try:
            report = await harness.usage(UsageRequest(**fields, session=turn.session, turn=turn))
        except Exception:
            _LOGGER.warning("lane usage was not read; closing usage stays as observed")
            return facts
        usage = facts.usage if report.disposition == "unknown" else report
        cost = facts.cost_disposition
        if report.cost_micros_usd is not None:
            cost = "settled"
        elif cost == "unknown" and usage.disposition != "unknown":
            cost = "estimated"
        return facts.model_copy(update={"usage": usage, "cost_disposition": cost})

    async def _end_session(
        self,
        harness: SessionLane,
        fields: dict[str, Any],
        session: SessionHandle,
        facts: ClosingFacts,
    ) -> ClosingFacts:
        receipt = await harness.end_session(
            EndSessionRequest(**fields, session=session, reason=facts.native_status)
        )
        refs = tuple(
            ref
            for ref in dict.fromkeys((*facts.output_refs, *receipt.artifact_refs))
            if ref != receipt.patch_ref
        )
        patch = receipt.patch_ref or facts.patch_ref
        return facts.model_copy(update={"output_refs": refs, "patch_ref": patch})

    async def _lost(
        self, request: LaneTurnRequest, identity: LaneExecutionIdentity, *, reason: str
    ) -> LaneTurnResult:
        result = await self._boundary.lane_in_doubt(request.operation, reason=reason)
        return LaneTurnResult(
            done=True,
            segment_no=request.segment_no,
            closing_facts=ClosingFacts(native_status="in_doubt", error_code=reason[:128]),
            operation_result=result.model_dump(mode="json"),
        )

    async def _project(
        self,
        handle: HarnessExecutionHandle,
        identity: LaneExecutionIdentity,
        *,
        cancelled_by_command: bool = False,
    ) -> None:
        """Closing-frame facts become mission events; best effort (frames are durable and the
        next projection re-derives every fact). The operation settlement decides `finished`."""

        if self._frame_facts is None:
            return
        try:
            state = await self._states.load(identity.request_scope, identity.harness_execution_id)
            await self._frame_facts.project(
                FrameFactTarget.from_handle(
                    handle, run_key=identity.run_key, unit_key=identity.activation_key
                ),
                completion_policy="deferred",
                cancel_command_admitted=cancelled_by_command,
                replaced_turn_refs=_replaced_turn_refs(state, identity.harness_execution_id),
            )
        except Exception:
            _LOGGER.warning("lane frame facts were not applied; the next projection re-derives")

    # --- lane.status ------------------------------------------------------------------------

    async def status(self, request: LaneStatusRequest) -> LaneStatusResult:
        settled = await self._boundary.lane_settlement(request.operation)
        if settled is not None:
            return LaneStatusResult(
                status=settled.status,
                terminal=True,
                settled=True,
                idle=True,
                operation_result=settled.model_dump(mode="json"),
            )
        harness = self._session_lane(request.lane_profile, request.operation, request.generation)
        identity = LaneExecutionIdentity.of(
            request.operation, request.lane_profile, request.generation
        )
        state = await self._states.load(identity.request_scope, identity.harness_execution_id)
        # A local session's status is readable only by the worker that owns it.
        self._sessions.check_control(
            state.owner if state else None,
            placement=_placement(request.lane_profile),
            now=self._clock(),
        )
        session_ref = request.native.session_ref or (state.native_session_ref if state else None)
        turn_ref = request.native.turn_ref or (state.native_turn_ref if state else None)
        if session_ref is None:
            return LaneStatusResult(status="not_started", terminal=False, idle=True)
        fields = self._fields(request.operation, identity, request.generation, "status")
        session = SessionHandle(
            lane_profile=request.lane_profile,
            harness_execution_id=str(identity.harness_execution_id),
            generation=request.generation,
            native_session_ref=session_ref,
        )
        turn = (
            None
            if turn_ref is None
            else TurnHandle(session=session, turn_no=1, native_turn_ref=turn_ref)
        )
        try:
            observed = await harness.status(StatusRequest(**fields, session=session, turn=turn))
        except NativeTurnLost:
            return LaneStatusResult(status="lost", terminal=False)
        return LaneStatusResult(
            status=observed.status,
            terminal=observed.terminal,
            idle=observed.idle,
            usage=observed.usage,
        )

    # --- lane.cancel ------------------------------------------------------------------------

    async def cancel(
        self,
        request: LaneCancelRequest,
        *,
        attempt: OperationActivityAttempt | None = None,
    ) -> LaneCancelResult:
        """Idempotent provider cancel; settles `cancelled` once the provider is terminal."""

        settled = await self._boundary.lane_settlement(request.operation)
        if settled is not None:
            abandoned = settled.failure_code == "in_doubt_abandoned"
            return LaneCancelResult(
                receipt=CancelReceipt(
                    acknowledged=not abandoned,
                    already_terminal=not abandoned,
                    native_status="unknown" if abandoned else settled.status,
                ),
                settled=True,
                operation_result=settled.model_dump(mode="json"),
            )
        identity = LaneExecutionIdentity.of(
            request.operation, request.lane_profile, request.generation
        )
        state = await self._states.load(identity.request_scope, identity.harness_execution_id)
        owner = await self._control_owner(request.lane_profile, identity, request.generation, state)

        async def reconcile(reason: str | None = None) -> LaneCancelResult | None:
            if not request.settle or not isinstance(self._boundary, LaneReconciliationBoundary):
                return None
            # A foreign live owner cannot be abandoned by a competing controller.
            if state is not None and state.owner is not None and owner is None:
                return None
            if owner is not None:
                await self._states.assert_owner(
                    identity.request_scope, identity.harness_execution_id, owner
                )
            result = await self._boundary.reconcile_lane_cancellation(
                request.operation, attempt=attempt, reason=reason
            )
            if result is None:
                return None
            return LaneCancelResult(
                receipt=CancelReceipt(acknowledged=False, native_status="unknown"),
                settled=result.status in {"cancelled", "completed", "failed"},
                operation_result=result.model_dump(mode="json"),
            )

        recovered = await reconcile()
        if recovered is not None:
            return recovered
        if request.in_doubt:
            recovered = await reconcile("lane_status_unresolved")
            if recovered is not None:
                return recovered
            result = await self._boundary.lane_in_doubt(
                request.operation, reason="lane_status_unresolved"
            )
            return LaneCancelResult(
                receipt=CancelReceipt(acknowledged=False, native_status="unknown"),
                operation_result=result.model_dump(mode="json"),
            )
        session_ref = request.native.session_ref or (state.native_session_ref if state else None)
        turn_ref = request.native.turn_ref or (state.native_turn_ref if state else None)
        fields = self._fields(request.operation, identity, request.generation, "cancel")
        if turn_ref is None and state is not None:
            ambiguous = [
                record
                for record in state.dispatches.values()
                if record.phase in {"intended", "in_doubt"}
            ]
            if ambiguous:
                # A send may have been accepted without a receipt: "never sent" would be a
                # false claim, so the cancel cannot settle it; reconciliation decides.
                recovered = await reconcile(f"{ambiguous[0].kind}_dispatch_ambiguous")
                if recovered is not None:
                    return recovered
                result = await self._boundary.lane_in_doubt(
                    request.operation, reason=f"{ambiguous[0].kind}_dispatch_ambiguous"
                )
                return LaneCancelResult(
                    receipt=CancelReceipt(acknowledged=False, native_status="unknown"),
                    operation_result=result.model_dump(mode="json"),
                )
        harness = self._session_lane(request.lane_profile, request.operation, request.generation)
        if session_ref is None or turn_ref is None:
            # Never sent: nothing to cancel at the provider; the unit settles cancelled.
            receipt = CancelReceipt(acknowledged=True, already_terminal=True, native_status="idle")
            turn: TurnHandle | None = None
        else:
            session = SessionHandle(
                lane_profile=request.lane_profile,
                harness_execution_id=str(identity.harness_execution_id),
                generation=request.generation,
                native_session_ref=session_ref,
            )
            turn = TurnHandle(session=session, turn_no=1, native_turn_ref=turn_ref)
            receipt = await harness.cancel_turn(
                CancelTurnRequest(
                    **fields, turn=turn, reason=request.reason, urgency=request.urgency
                )
            )
            await self._cancel_acknowledged(request.operation, identity, receipt)
        if not request.settle or not (receipt.already_terminal or receipt.acknowledged):
            return LaneCancelResult(receipt=receipt)
        if turn is not None:
            observed = await harness.status(
                StatusRequest(**fields, session=turn.session, turn=turn)
            )
            if not observed.terminal:
                return LaneCancelResult(receipt=receipt)
        cancelled_facts: ClosingFacts | None = None
        if turn is not None and isinstance(harness, CancelledCloseLane):
            # Preserve the provider's post-interrupt close before settlement/cleanup.
            # A foreign live owner must first expire: controls cannot write its frames.
            if owner is None:
                return LaneCancelResult(receipt=receipt)
            cancelled_facts = await self._cancel_observation(
                request, harness, identity, fields, turn, state, owner
            )
            if cancelled_facts is None:
                return LaneCancelResult(receipt=receipt)
        turn_request = LaneTurnRequest(
            operation=request.operation,
            lane_profile=request.lane_profile,
            generation=request.generation,
            phase="resume",
        )
        usage = (
            cancelled_facts.usage
            if cancelled_facts is not None
            else await self._turn_usage(harness, identity, request.generation, turn_ref)
        )
        cancelled = await self._settle(
            turn_request,
            harness,
            identity,
            turn,
            ClosingFacts(
                native_status="cancelled",
                error_code="cancelled_by_command",
                usage=usage,
                cost_disposition="estimated" if usage.disposition != "unknown" else "unknown",
            ),
            attempt=attempt,
            native=NativeRefs(session_ref=session_ref, turn_ref=turn_ref),
            cancelled_by_command=True,
            owner=owner,
        )
        return LaneCancelResult(
            receipt=receipt,
            settled=(
                OperationExecutionResult.model_validate(cancelled.operation_result).status
                != "in_doubt"
            ),
            operation_result=cancelled.operation_result,
        )

    async def _cancel_observation(
        self,
        request: LaneCancelRequest,
        harness: SessionLane,
        identity: LaneExecutionIdentity,
        fields: dict[str, Any],
        turn: TurnHandle,
        state: LaneExecutionState | None,
        owner: SessionOwner,
    ) -> ClosingFacts | None:
        if (
            isinstance(harness, CancelledCloseLane)
            and harness.cancelled_close == "observe_or_stored"
            and self._reader is not None
            and state is not None
            and state.native_session_ref == turn.session.native_session_ref
            and state.native_turn_ref == turn.native_turn_ref
        ):
            # A cancelled observation activity may have persisted the complete close
            # without flushing its segment cursor. Replaying that native backlog one
            # frame/transaction at a time can otherwise take many bounded cancel calls.
            # Reuse only this owner's exact durable turn close; _settled_usage still
            # requires complete attributed usage and retains every unknown liability.
            await self._states.assert_owner(
                identity.request_scope, identity.harness_execution_id, owner
            )
            stored = await self._reader.frames_for_execution(
                identity.request_scope,
                identity.harness_execution_id,
                request.generation,
                closing_only=True,
            )
            current = await self._states.load(identity.request_scope, identity.harness_execution_id)
            await self._states.assert_owner(
                identity.request_scope, identity.harness_execution_id, owner
            )
            if current is None or (
                current.native_session_ref != turn.session.native_session_ref
                or current.native_turn_ref != turn.native_turn_ref
                or any(
                    dispatch.phase in {"intended", "in_doubt"}
                    for dispatch in current.dispatches.values()
                )
            ):
                return None
            for stored_frame in reversed(stored):
                if (
                    stored_frame.kind != FrameKind.RUN_RESULT
                    or stored_frame.scope.request_scope != identity.request_scope
                    or stored_frame.harness_execution_id != identity.harness_execution_id
                    or stored_frame.generation != request.generation
                    or stored_frame.native_session_ref != turn.session.native_session_ref
                    or stored_frame.native_turn_ref != turn.native_turn_ref
                    or stored_frame.subordinate_ref is not None
                    or len(stored_frame.provider_key) > 512
                ):
                    continue
                body = frame_body_object(
                    stored_frame.body_excerpt, stored_frame.body_bytes, stored_frame.lifecycle_body
                )
                native = body.get("turn")
                if (
                    not isinstance(native, dict)
                    or native.get("id") != turn.native_turn_ref
                    or native.get("status") not in {"completed", "interrupted", "failed"}
                ):
                    continue
                facts = harness.closing_facts(
                    turn,
                    LaneFrame(
                        harness_execution_id=str(identity.harness_execution_id),
                        generation=request.generation,
                        provider_key=stored_frame.provider_key,
                        cursor=stored_frame.provider_key,
                        kind=stored_frame.kind.value,
                        raw_kind=stored_frame.raw_kind,
                        digest=stored_frame.body_digest,
                        body=body,
                        native_turn_ref=stored_frame.native_turn_ref,
                        terminal=True,
                    ),
                )
                await self._states.assert_owner(
                    identity.request_scope, identity.harness_execution_id, owner
                )
                return facts
        handle = await self._open(
            request.operation,
            identity,
            request.generation,
            turn.session.native_session_ref or str(identity.harness_execution_id),
        )
        writer = FrameWriter(
            self._frames,
            handle,
            excerpt_cap_bytes=self._cap,
            secret_values=await self._secret_values(request.operation),
        )
        stream = harness.observe(
            ObserveRequest(
                **fields, turn=turn, after=state.provider_cursor if state else None, max_frames=256
            )
        )
        with suppress(TimeoutError):
            async with asyncio.timeout(5), aclosing(stream) as observations:  # type: ignore[type-var]
                count = 0
                async for frame in observations:
                    await self._states.assert_owner(
                        identity.request_scope, identity.harness_execution_id, owner
                    )
                    receipt = await writer.write(
                        [
                            self._observation(
                                frame, identity, session_ref=turn.session.native_session_ref
                            )
                        ]
                    )
                    if receipt.stale:
                        raise StaleSessionOwner("cancel tail was refused by the execution fence")
                    await self._states.assert_owner(
                        identity.request_scope, identity.harness_execution_id, owner
                    )
                    await self._states.record(
                        identity.request_scope,
                        identity.harness_execution_id,
                        LaneExecutionUpdate(provider_cursor=frame.cursor),
                    )
                    if frame.terminal:
                        return harness.closing_facts(turn, frame)
                    count += 1
                    if count >= 256:
                        return None
        return None

    async def _control_owner(
        self,
        lane_profile: str,
        identity: LaneExecutionIdentity,
        generation: int,
        state: LaneExecutionState | None,
    ) -> SessionOwner | None:
        """The owner a control acts as: this worker when it holds (or may take over) the
        session; none for a hosted session another live owner holds (settlement is once at
        the boundary). A live foreign owner of a local session refuses the control."""

        current = state.owner if state is not None else None
        now = self._clock()
        self._sessions.check_control(current, placement=_placement(lane_profile), now=now)
        if current is None:
            return None
        if current.owner_ref != self._sessions.owner_ref and not current.expired(now):
            return None
        # Ours, or expired: claiming it (a takeover bumps the epoch) fences the old owner.
        return await self._sessions.claim(
            self._states,
            identity.request_scope,
            identity.harness_execution_id,
            generation=generation,
            now=now,
            heartbeat_timeout_s=LaneSegmentBounds().heartbeat_timeout_s,
        )

    async def _cancel_acknowledged(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        receipt: CancelReceipt,
    ) -> None:
        """The provider acknowledged the cancel: its own Delivery Report timestamp, recorded
        now and never folded into the settlement time (four independent timestamps)."""

        if self._fences is None or not receipt.acknowledged:
            return
        try:
            await self._fences.record_milestone(
                operation.request_scope,
                operation.identity.run_id,
                None,
                "provider_acknowledged",
                unit_key=str(identity.harness_execution_id),
                recorded_at=self._clock(),
            )
        except Exception:
            _LOGGER.warning("provider_acknowledged milestone was not recorded", exc_info=True)

    # --- lane.cleanup -----------------------------------------------------------------------

    async def cleanup(self, request: LaneCleanupRequest) -> LaneCleanupResult:
        """MO-05 (SPEC-03 section 2): remove the worktree a unit generation released, once
        the unit is settled (its Artifacts registered and its liabilities settled). A refusal
        keeps the worktree and names why; a lane that leases no workspace has none to clean.
        """

        harness = self._lanes.for_profile(request.lane_profile)
        if not isinstance(harness, WorkspaceLeasingLane):
            return LaneCleanupResult(outcome="not_required")
        settlement = await self._boundary.lane_settlement(request.operation)
        if settlement is None:
            return LaneCleanupResult(outcome="retained", reason_code=UNIT_NOT_SETTLED)
        identity = LaneExecutionIdentity.of(
            request.operation, request.lane_profile, request.generation
        )
        state = await self._states.load(identity.request_scope, identity.harness_execution_id)
        if settlement.failure_code == "in_doubt_abandoned" or (
            state is not None
            and any(
                record.phase in {"intended", "in_doubt"} for record in state.dispatches.values()
            )
        ):
            return LaneCleanupResult(outcome="retained", reason_code="native_dispatch_unresolved")
        try:
            outcome = await harness.cleanup_workspace(
                request_scope=identity.request_scope,
                harness_execution_id=str(identity.harness_execution_id),
                generation=request.generation,
            )
        except WorkspaceError as error:
            return LaneCleanupResult(outcome="retained", reason_code=error.code)
        return LaneCleanupResult(outcome=outcome)


_REPLACE_KEY = ":replace:"


def _replaced_turn_refs(
    state: LaneExecutionState | None, harness_execution: UUID
) -> frozenset[str]:
    """The native turns an applied `cancel_and_replace` interrupted, from the journaled
    replacement sends (`<harness execution>:<generation>:replace:<turn>`). A replacement the
    Stop Fence declined never ran: that turn's cancellation stays the command's."""

    if state is None:
        return frozenset()
    prefix = f"{harness_execution}:"
    refs: set[str] = set()
    for record in state.dispatches.values():
        key = record.idempotency_key
        if record.kind != "send" or not key.startswith(prefix) or _REPLACE_KEY not in key:
            continue
        if record.reason == "stop_fenced":
            continue
        refs.add(key.split(_REPLACE_KEY, 1)[1])
    return frozenset(refs)


def _replacement_map(state: LaneExecutionState | None, harness_execution: UUID) -> dict[str, str]:
    """K1: replacement native turn → the turn it replaced, from the acknowledged replacement
    sends of the dispatch journal (`<harness execution>:<generation>:replace:<turn>`); a
    replacement the Stop Fence declined never ran."""

    if state is None:
        return {}
    prefix = f"{harness_execution}:"
    replaced: dict[str, str] = {}
    for record in state.dispatches.values():
        key = record.idempotency_key
        if record.kind != "send" or not key.startswith(prefix) or _REPLACE_KEY not in key:
            continue
        if record.reason == "stop_fenced" or record.native_ref is None:
            continue
        replaced[record.native_ref] = key.split(_REPLACE_KEY, 1)[1]
    return replaced


def _late_dispatch(task: asyncio.Future[Any]) -> None:
    """A native call that returned after its activity was cancelled: its receipt was journaled
    if this owner still held the session, or refused (`StaleSessionOwner`) after a takeover."""

    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        _LOGGER.warning("a late native dispatch receipt was not recorded: %s", error)


def _placement(lane_profile: str) -> str:
    return PLACEMENT_OF_PROFILE[lane_profile]


@dataclass
class _SegmentProgress:
    owner: SessionOwner
    cursor: str | None = None
    max_frames: int = 0
    persisted: int = 0
    duplicates: int = 0
    observed: int = 0
    # MP-06: set when a takeover fenced this owner out (the segment stops at the next frame)
    # and the commands a stale steer requeued for the next boundary.
    fenced_out: StaleSessionOwner | None = None
    stale_steers: set[str] = field(default_factory=set)
    history_attempted: tuple[datetime, int] | None = None
    history_passes: int = 0


@dataclass(frozen=True)
class _Pumped:
    terminal: LaneFrame | None = None
    history: HistoryRequest | None = None
    injection: MailboxEntry | None = None


@dataclass(frozen=True)
class _Dispatched[T]:
    """A journaled create/send: the provider's return when this call issued it, or only the
    native identity when an earlier, acknowledged or reconciled dispatch is reused."""

    native_ref: str | None
    value: T | None = None
    reconciled: bool = False


@dataclass(frozen=True)
class _SentTurn:
    handle: TurnHandle
    reconciled: bool


class _DispatchParked(Exception):
    """An earlier dispatch of the key is ambiguous and cannot be reconciled: `in_doubt`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason[:128]


async def _heartbeat_ticker(
    signals: TurnSignals,
    progress: Callable[[], tuple[str | None, int]],
    heartbeat_timeout_s: int,
    *,
    renew: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Keep heartbeating the last persisted cursor while the provider is silent, so a long
    tool call is not mistaken for a lost worker (the SDK throttles sends anyway); renew the
    owner's session lease on the same beat."""

    interval = max(heartbeat_timeout_s / 3, 1.0)
    while True:
        await asyncio.sleep(interval)
        cursor, persisted = progress()
        signals.heartbeat(cursor, persisted)
        if renew is not None:
            try:
                await renew()
            except Exception:
                _LOGGER.warning("session lease renewal failed; retried on the next beat")


def _declares_budget_gate(operation: OperationExecutionRequest) -> bool:
    """Whether the attempt's lane applies a budget gate natively (its dispatch says so)."""

    dispatch = operation.lane_dispatch
    return dispatch is not None and dispatch.declares("budget_gate")


__all__ = [
    "UNIT_NOT_SETTLED",
    "FinalTextLane",
    "LaneBoundary",
    "LaneExecutionIdentity",
    "LaneNotSessionDriven",
    "LaneStartStalled",
    "LaneTurnService",
    "TurnSignals",
    "execution_start",
    "harness_scope",
    "read_final_text",
]

"""A registry refusal settles only with exclusive never-started authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.execution.harness.dispatch import DispatchRecord
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.state import LaneExecutionUpdate
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.operation_execution import (
    OperationExecutionInProgress,
    RunControlOperationAuthority,
    bind_operation_execution_request,
)
from mission_control.application.resolution.registries import LaneNotQualified, LaneRegistry
from mission_control.domain.execution.checkpoint_lineage import OperationActivityAttempt
from mission_control.domain.execution.contracts import OperationExecutionResult
from mission_control.domain.execution.journal import OperationClaimResult
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.graph_runtime.identities import (
    RuntimeUnitIdentity,
    StageGraphUnitLocation,
)
from mission_control.domain.policies.contracts import (
    CommandStatus,
    PauseAction,
    PauseDecision,
    RecordUsageAction,
    StartAction,
)
from mission_control.domain.policies.errors import IdempotencyConflict
from tests.fixtures.checkpoint_recovery import FixtureControlPlane, governed_workspace
from tests.fixtures.lane_turns import SCOPE, RecordingSignals, cursor_operation, lane_stack
from tests.unit.run_control.test_run_control import actor, command, request, service


class RejectionJournal:
    def __init__(self) -> None:
        self.claims: dict[str, Any] = {}
        self.settlements: dict[str, Any] = {}
        self.crash_claim = False
        self.crash_settlement = False

    async def commit(self, mutation: Any) -> OperationClaimResult:
        if mutation.settlement is None and self.crash_claim:
            self.crash_claim = False
            raise RuntimeError("lost claim journal write")
        if mutation.settlement is not None and self.crash_settlement:
            self.crash_settlement = False
            raise RuntimeError("lost settlement journal write")
        claim = mutation.claim
        prior = self.claims.get(claim.effect_claim_id)
        if mutation.settlement is not None:
            previous = self.settlements.get(claim.effect_claim_id)
            if previous is not None and previous != mutation.settlement:
                raise IdempotencyConflict("rejection settlement changed on replay")
            self.settlements[claim.effect_claim_id] = mutation.settlement
        self.claims[claim.effect_claim_id] = prior or claim
        return OperationClaimResult(
            status="existing" if prior else "acquired", claim=prior or claim, reason="recorded"
        )

    async def get_settlement(self, request_scope: str, effect_claim_id: str) -> Any:
        del request_scope
        return self.settlements.get(effect_claim_id)


@dataclass
class RejectionStack:
    lane: Any
    run_control: Any
    journal: RejectionJournal
    coordinator: JournaledOperationExecutionCoordinator
    operation: Any
    binding: Any

    async def turn(self) -> Any:
        return await self.lane.service.turn(
            LaneTurnRequest(operation=self.operation, lane_profile="cursor_local", generation=1),
            RecordingSignals(self.lane.frames),
        )

    async def budget(self) -> Any:
        return await self.run_control.get_budget(SCOPE, self.operation.identity.run_id)


async def rejection_stack() -> RejectionStack:
    run_control, _repository = service()
    admitted = await run_control.admit(request(request_scope=SCOPE))
    assert admitted.run_id is not None
    started = await run_control.execute(
        command(admitted.run_id, 1, "start-rejection", StartAction()).model_copy(
            update={"request_scope": SCOPE}
        )
    )
    assert started.status == CommandStatus.ACCEPTED
    operation = cursor_operation()
    operation = operation.model_copy(
        update={
            "identity": operation.identity.model_copy(update={"run_id": admitted.run_id}),
            "run_control_revision": 2,
            "budget_reservation_id": "baseline",
            "budget_limits": {"tokens.total": 20},
            "workspace": governed_workspace(operation.workspace),
        }
    )
    lane = lane_stack(operation=operation)
    binding = bind_operation_execution_request(operation)
    await lane.bindings.create_binding(binding)
    journal = RejectionJournal()
    coordinator = JournaledOperationExecutionCoordinator(
        journal=journal,  # type: ignore[arg-type]
        run_control=run_control,
        results=InMemoryArtifactPayloadStore(),
        actor=actor(),
    )
    lane.boundary._journal = coordinator
    lane.boundary._authority = RunControlOperationAuthority(
        run_control,
        FixtureControlPlane(operation),  # type: ignore[arg-type]
    )
    lane.service._lanes = LaneRegistry([lane.lane], allow_unqualified=False)
    return RejectionStack(lane, run_control, journal, coordinator, operation, binding)


async def test_rejection_settles_once_with_normal_release_and_no_native_work() -> None:
    stack = await rejection_stack()
    first = await stack.turn()
    result = OperationExecutionResult.model_validate(first.operation_result)
    assert result.status == "failed" and result.failure_code == "lane_not_qualified"
    assert result.usage.amounts == {} and result.usage.pending_external_amounts == {}
    assert first.closing_facts is None
    assert stack.lane.lane.calls == [] and stack.lane.lane.staged == {}
    assert stack.lane.frames._executions == {}
    budget = await stack.budget()
    assert "baseline" not in budget.reservations
    assert len(budget.usage_records) == len(stack.journal.settlements) == 1
    usage = next(iter(budget.usage_records.values()))
    assert usage.actual_amounts == {} and usage.release_amounts == {"tokens.total": 20}
    settlement = next(iter(stack.journal.settlements.values()))
    assert settlement.settled_at > stack.binding.bound_at
    assert settlement.settled_at == next(iter(stack.journal.claims.values())).claimed_at
    assert (await stack.turn()).operation_result == first.operation_result
    assert len((await stack.budget()).usage_records) == len(stack.journal.settlements) == 1


async def test_rejection_replay_refuses_a_changed_request() -> None:
    stack = await rejection_stack()
    await stack.turn()
    stack.operation = stack.operation.model_copy(update={"tracing_policy_ref": "trace:changed"})
    with pytest.raises(IdempotencyConflict):
        await stack.turn()


@pytest.mark.parametrize("authority_only", [False, True])
async def test_existing_normal_claim_retains_liability_even_without_journal(
    authority_only: bool,
) -> None:
    stack = await rejection_stack()
    stack.journal.crash_claim = authority_only
    if authority_only:
        with pytest.raises(RuntimeError, match="lost claim"):
            await stack.coordinator.acquire(stack.binding, claimed_by="normal")
    else:
        assert (await stack.coordinator.acquire(stack.binding, claimed_by="normal")).claim
    with pytest.raises(OperationExecutionInProgress, match="prior operation effect"):
        await stack.turn()
    assert (await stack.budget()).reservations["baseline"] == {"tokens.total": 20}
    assert stack.journal.settlements == {} and stack.lane.lane.staged == {}


@pytest.mark.parametrize("crash", ["claim", "settlement"])
async def test_own_rejection_authority_recovers_crash_and_blocks_normal_dispatch(
    crash: str,
) -> None:
    stack = await rejection_stack()
    setattr(stack.journal, f"crash_{crash}", True)
    with pytest.raises(RuntimeError, match="journal write"):
        await stack.turn()
    normal = await stack.coordinator.acquire(
        stack.binding, claimed_by="normal", at_current_version=True
    )
    assert normal.claim is None and "effect_claim_exists" in normal.reason
    result = await stack.turn()
    assert OperationExecutionResult.model_validate(result.operation_result).failure_code == (
        "lane_not_qualified"
    )
    assert len(stack.journal.settlements) == len((await stack.budget()).usage_records) == 1
    assert stack.lane.lane.calls == [] and stack.lane.lane.staged == {}


@pytest.mark.parametrize("pending", [False, True])
async def test_positive_or_unknown_pending_usage_refuses_release(pending: bool) -> None:
    stack = await rejection_stack()
    recorded = await stack.run_control.execute(
        command(
            stack.binding.run_id,
            2,
            "prior-usage",
            RecordUsageAction(
                usage_id="prior-usage",
                reservation_id="baseline",
                authority_ref=stack.binding.binding_id,
                actual_amounts={} if pending else {"tokens.total": 1},
                pending_external_amounts={"tokens.total": 1} if pending else {},
            ),
        ).model_copy(update={"request_scope": SCOPE})
    )
    assert recorded.status == CommandStatus.ACCEPTED
    before = await stack.budget()
    with pytest.raises(OperationExecutionInProgress, match="prior operation usage"):
        await stack.turn()
    assert await stack.budget() == before and not stack.journal.settlements


@pytest.mark.parametrize(
    "update",
    [
        LaneExecutionUpdate(native_session_ref="native-session"),
        LaneExecutionUpdate(native_turn_ref="native-turn"),
        LaneExecutionUpdate(usage_disposition="unknown"),
    ],
)
async def test_existing_native_or_unknown_usage_state_never_settles_zero(update: Any) -> None:
    stack = await rejection_stack()
    identity = LaneExecutionIdentity.of(stack.operation, "cursor_local", 1)
    before = await stack.lane.states.record(SCOPE, identity.harness_execution_id, update)
    with pytest.raises(LaneNotQualified):
        await stack.turn()
    assert await stack.lane.states.load(SCOPE, identity.harness_execution_id) == before
    assert (await stack.budget()).reservations["baseline"] == {"tokens.total": 20}
    assert not stack.journal.settlements and stack.lane.lane.staged == {}


async def test_no_journal_composition_fails_closed_without_claiming() -> None:
    stack = await rejection_stack()
    stack.lane.boundary._journal = None
    with pytest.raises(OperationExecutionInProgress, match="authority unavailable"):
        await stack.turn()
    assert stack.lane.bindings._claims == {}
    assert (await stack.budget()).reservations["baseline"] == {"tokens.total": 20}


@pytest.mark.parametrize("phase", ["intended", "in_doubt"])
async def test_any_existing_dispatch_retains_liability(phase: str) -> None:
    stack = await rejection_stack()
    identity = LaneExecutionIdentity.of(stack.operation, "cursor_local", 1)
    owner = await stack.lane.states.claim_owner(
        SCOPE,
        identity.harness_execution_id,
        owner_ref="prior-worker",
        generation=1,
        now=stack.binding.bound_at,
        lease=timedelta(seconds=30),
    )
    record = DispatchRecord(
        kind="create",
        idempotency_key="prior-create",
        expected_generation=1,
        instruction_digest="digest:prior-create",
        owner_ref=owner.owner_ref,
        owner_epoch=owner.epoch,
        intended_at=stack.binding.bound_at,
    )
    await stack.lane.states.intend_dispatch(
        SCOPE, identity.harness_execution_id, record, owner=owner
    )
    if phase == "in_doubt":
        await stack.lane.states.resolve_dispatch(
            SCOPE,
            identity.harness_execution_id,
            "create",
            record.idempotency_key,
            outcome="in_doubt",
            owner=owner,
            at=stack.binding.bound_at,
            reason="ambiguous",
        )
    before = await stack.lane.states.load(SCOPE, identity.harness_execution_id)
    with pytest.raises(LaneNotQualified):
        await stack.turn()
    assert await stack.lane.states.load(SCOPE, identity.harness_execution_id) == before
    assert not stack.journal.settlements and stack.lane.lane.staged == {}


async def test_existing_execution_without_lane_state_is_still_refused() -> None:
    stack = await rejection_stack()
    identity = LaneExecutionIdentity.of(stack.operation, "cursor_local", 1)
    await stack.lane.service._open(stack.operation, identity, 1, "prior-execution")
    assert await stack.lane.states.load(SCOPE, identity.harness_execution_id) is None
    with pytest.raises(LaneNotQualified):
        await stack.turn()
    assert not stack.journal.settlements


@pytest.mark.parametrize("dispatching", [False, True])
async def test_even_unstarted_existing_lineage_retains_liability(dispatching: bool) -> None:
    stack = await rejection_stack()
    unit = RuntimeUnitIdentity(
        request_scope=SCOPE,
        belllabs_run_id=stack.binding.run_id,
        execution_epoch=1,
        family="stage_graph",
        unit_kind="stage_operation",
        semantic_operation_id=stack.binding.operation_id,
        semantic_attempt=1,
        location=StageGraphUnitLocation(
            stage_id="stage",
            mapped_instance_id="none",
            workflow_cycle_ordinal=0,
            stage_cycle_ordinal=0,
            operation_slot_id="operation",
        ),
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    stack.lane.boundary._lineage = lineage
    stack.operation = stack.operation.model_copy(update={"runtime_unit": unit})
    stack.binding = bind_operation_execution_request(stack.operation)
    stack.lane.bindings._bindings[stack.operation.identity.semantic_key] = stack.binding
    await lineage.observe_attempt(
        stack.binding,
        OperationActivityAttempt(
            workflow_id="workflow",
            workflow_run_id="workflow-run",
            activity_id="activity",
            attempt=1,
            worker_identity="prior-worker",
        ),
        dispatching=dispatching,
    )
    with pytest.raises(OperationExecutionInProgress, match="prior execution lineage"):
        await stack.turn()
    assert not stack.journal.claims and not stack.journal.settlements


async def test_generic_stage_failure_is_not_a_zero_usage_rejection() -> None:
    stack = await rejection_stack()
    stack.lane.service._lanes = LaneRegistry([stack.lane.lane], allow_unqualified=True)

    def broken_stage(*_args: Any) -> None:
        raise ValueError("generic stage failure")

    stack.lane.lane.stage = broken_stage
    with pytest.raises(ValueError, match="generic stage failure"):
        await stack.turn()
    assert not stack.journal.claims and not stack.journal.settlements
    assert (await stack.budget()).reservations["baseline"] == {"tokens.total": 20}


async def test_paused_current_authority_refuses_rejection_settlement() -> None:
    stack = await rejection_stack()
    paused = await stack.run_control.execute(
        command(
            stack.binding.run_id,
            2,
            "pause-before-rejection",
            PauseAction(
                decision=PauseDecision(
                    decision_id="pause",
                    reason="operator",
                    scope=frozenset({"run"}),
                    authority_ref="authority:lifecycle",
                ),
                runnable_work_remains=False,
            ),
        ).model_copy(update={"request_scope": SCOPE})
    )
    assert paused.status == CommandStatus.ACCEPTED
    with pytest.raises(OperationExecutionInProgress, match="authority changed"):
        await stack.turn()
    assert not stack.journal.claims and not stack.journal.settlements


async def test_fresh_authority_is_verified_but_own_settlement_replay_needs_no_new_reservation() -> (
    None
):
    stack = await rejection_stack()
    authority = stack.lane.boundary._authority
    verified: list[bool] = []

    async def verify_reservation(operation: Any, binding: Any) -> None:
        await authority.verify_continuation(operation, binding)
        assert binding.budget_reservation_id in (await stack.budget()).reservations
        verified.append(True)

    class ReservationAuthority:
        verify_continuation = staticmethod(verify_reservation)

    stack.lane.boundary._authority = ReservationAuthority()
    stack.journal.crash_settlement = True
    with pytest.raises(RuntimeError, match="lost settlement"):
        await stack.turn()
    assert "baseline" not in (await stack.budget()).reservations
    result = await stack.turn()
    assert OperationExecutionResult.model_validate(result.operation_result).status == "failed"
    assert verified == [True], "exact prior rejection authority resumes its own settlement"


async def test_rejection_refuses_changed_admitted_binding_and_wrong_rejection_type() -> None:
    stack = await rejection_stack()
    changed = stack.binding.model_copy(update={"budget_limits": {"tokens.total": 19}})
    stack.lane.bindings._bindings[stack.operation.identity.semantic_key] = changed
    with pytest.raises(IdempotencyConflict, match="admitted binding"):
        await stack.turn()
    stack.lane.bindings._bindings[stack.operation.identity.semantic_key] = stack.binding
    with pytest.raises(ValueError, match="does not match"):
        await stack.lane.boundary.settle_lane_admission_rejection(
            stack.operation, LaneNotQualified("cursor_cloud")
        )
    with pytest.raises(ValueError, match="does not match"):
        await stack.lane.boundary.settle_lane_admission_rejection(
            stack.operation, ValueError("generic failure")
        )
    assert not stack.journal.claims and not stack.journal.settlements

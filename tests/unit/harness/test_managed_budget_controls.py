"""Budget controls prove durable intent, conservative ambiguity and fenced cap increases."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mission_control.adapters.anthropic_managed.harness import _strict_usd_minor_units
from mission_control.application.execution.approvals import ApprovalContextState
from mission_control.application.execution.harness.budget_controls import BudgetControlService, held
from mission_control.application.execution.harness.state import (
    InMemoryLaneExecutionStateStore,
    LaneExecutionUpdate,
)
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
from mission_control.domain.authoring.canonical import stable_json_dump
from mission_control.domain.execution.budget_controls import (
    LaneBudgetControlRequest,
    ManagedBudgetSnapshot,
)
from mission_control.domain.policies.contracts import (
    ManagedBudgetGate,
    PauseAction,
    PauseDecision,
    ResumeAction,
    ResumeDecision,
)
from mission_control.domain.policies.stop_fence import StopFence
from tests.fixtures.lane_turns import DIGEST
from tests.fixtures.managed_lane import managed_binding, managed_operation

NOW = datetime(2026, 10, 14, tzinfo=UTC)


class Authority:
    def __init__(self):
        self.commands = {}
        self.refuse = False

    async def verify_budget_control(self, request):
        if self.refuse:
            raise ValueError("authority changed")
        return self.commands[request.command_id]


class Approvals:
    seal = ApprovalContextState(generation=1, policy_digest=DIGEST, granted=True)

    async def current(self, *args, **kwargs):
        return self.seal


class Provider:
    def __init__(self):
        self.cap, self.spent = 90, 3
        self.boundary = False
        self.evidence = "old-idle"
        self.disposition = "running"
        self.posts = []
        self.fail_after_post = False
        self.unknown = False

    async def read_budget(self, session):
        assert session == "session-1"
        if self.unknown:
            raise ValueError("cost unknown")
        return ManagedBudgetSnapshot(
            cap_minor_units=self.cap,
            spent_minor_units=self.spent,
            boundary_observed=self.boundary,
            evidence=self.evidence,
            disposition=self.disposition,
        )

    async def set_budget(self, session, cap):
        self.posts.append(cap)
        self.cap = cap
        if self.fail_after_post:
            raise TimeoutError("lost provider acknowledgement")


async def stack():
    operation = managed_operation(managed_binding(DIGEST))
    identity = uuid4()
    states = InMemoryLaneExecutionStateStore()
    await states.record(
        operation.request_scope,
        identity,
        LaneExecutionUpdate(native_session_ref="session-1", native_turn_ref="turn-1"),
    )
    owner = await states.claim_owner(
        operation.request_scope,
        identity,
        owner_ref="worker-a",
        generation=1,
        now=NOW,
        lease=timedelta(seconds=30),
    )
    authority, approvals, fences, provider = (
        Authority(),
        Approvals(),
        InMemoryStopFenceRepository(),
        Provider(),
    )
    service = BudgetControlService(
        states=states, authority=authority, approvals=approvals, fences=fences
    )
    return SimpleNamespace(
        operation=operation,
        identity=identity,
        states=states,
        owner=owner,
        authority=authority,
        approvals=approvals,
        fences=fences,
        provider=provider,
        service=service,
    )


async def queue(s, command="hold-1", *, resume=None, target=None):
    gate = ManagedBudgetGate(
        hold_command_id=resume,
        hold_command_issuer="operator" if resume else None,
        target_cap_minor_units=target,
    )
    s.authority.commands.setdefault(
        command,
        SimpleNamespace(
            kind="resume" if resume else "pause",
            action=(
                ResumeAction(
                    decision=ResumeDecision(
                        decision_id=command,
                        pause_decision_id=resume,
                        reason="fixture resume",
                        authority_ref="fixture authority",
                        budget_gate=gate,
                    )
                )
                if resume
                else PauseAction(
                    decision=PauseDecision(
                        decision_id=command,
                        scope=frozenset({"run"}),
                        reason="fixture hold",
                        authority_ref="fixture authority",
                        budget_gate=gate,
                    ),
                    runnable_work_remains=False,
                )
            ),
            payload_digest=DIGEST,
            target_sequence=len(s.authority.commands) + 1,
        ),
    )
    request = LaneBudgetControlRequest(
        operation=s.operation, generation=1, command_id=command, command_issuer="operator"
    )
    return await s.service.enqueue(request, s.identity, NOW)


async def drain(s):
    await s.service.drain(s.operation, s.identity, s.owner, s.provider, NOW)
    return await s.states.load(s.operation.request_scope, s.identity)


async def observed_hold(s):
    record = await queue(s)
    state = await drain(s)
    assert state.budget_controls[record.key].phase == "cap_confirmed"
    s.provider.boundary, s.provider.evidence = True, "new-budget-boundary"
    state = await drain(s)
    assert state.budget_controls[record.key].applied
    return record


async def test_duplicate_concurrent_hold_resume_never_repeats_post():
    s = await stack()
    record = await queue(s)
    assert await queue(s) == record
    await asyncio.gather(drain(s), drain(s))
    assert s.provider.posts == [4]
    assert (await drain(s)).budget_controls[record.key].phase == "cap_confirmed"
    s.provider.boundary, s.provider.evidence = True, "boundary-1"
    assert (await drain(s)).budget_controls[record.key].applied
    resume = await queue(s, "resume-1", resume="hold-1")
    assert (await drain(s)).budget_controls[resume.key].applied
    await queue(s, "resume-1", resume="hold-1")
    assert not held((await drain(s)).budget_controls)
    assert s.provider.posts == [4, 90]


async def test_lost_post_response_is_readback_reconciled_without_retry():
    s = await stack()
    s.provider.fail_after_post = True
    record = await queue(s)
    state = await drain(s)
    assert state.budget_controls[record.key].phase == "cap_confirmed"
    await drain(s)
    assert s.provider.posts == [4]


async def test_restart_after_intent_before_post_never_blindly_sends():
    s = await stack()
    record = await queue(s)
    intended = record.model_copy(
        update={
            "phase": "intended",
            "revision": 2,
            "target_cap_minor_units": 4,
            "prior_cap_minor_units": 90,
        }
    )
    await s.states.update_budget_control(intended, expected_revision=1, owner=s.owner)
    s.owner = await s.states.claim_owner(
        s.operation.request_scope,
        s.identity,
        owner_ref="worker-b",
        generation=1,
        now=NOW + timedelta(minutes=1),
        lease=timedelta(seconds=30),
    )
    s.service = BudgetControlService(
        states=s.states, authority=s.authority, approvals=s.approvals, fences=s.fences
    )
    state = await drain(s)
    assert state.budget_controls[record.key].phase == "in_doubt"
    assert not s.provider.posts and held(state.budget_controls)


async def test_stale_boundary_does_not_qualify_new_hold():
    s = await stack()
    s.provider.boundary = True
    record = await queue(s)
    assert (await drain(s)).budget_controls[record.key].phase == "cap_confirmed"


@pytest.mark.parametrize("disposition", ["requires_action", "terminal"])
async def test_non_budget_idle_is_inspectable_and_retains_liability(disposition):
    s = await stack()
    s.provider.disposition = disposition
    record = await queue(s)
    state = await drain(s)
    receipt = state.budget_controls[record.key]
    assert not receipt.applied and receipt.reason == f"budget_boundary_not_observed:{disposition}"
    assert held(state.budget_controls)


async def test_stop_fence_prevents_resume_without_lifting_held_cap():
    s = await stack()
    await observed_hold(s)
    resume = await queue(s, "resume-1", resume="hold-1")
    await s.fences.persist(
        StopFence(
            request_scope=s.operation.request_scope,
            run_id=s.operation.identity.run_id,
            generation=1,
            command_id="stop-1",
            reason="stop",
            requested_at=NOW,
        )
    )
    state = await drain(s)
    assert state.budget_controls[resume.key].phase == "rejected"
    assert s.provider.posts == [4] and held(state.budget_controls)


@pytest.mark.parametrize("mutation", ["unknown", "approval", "authority", "generation"])
async def test_changed_authority_or_unknown_usage_refuses_without_post(mutation):
    s = await stack()
    record = await queue(s)
    if mutation == "unknown":
        s.provider.unknown = True
    elif mutation == "approval":
        s.approvals.seal = s.approvals.seal.model_copy(
            update={"policy_digest": "sha256:" + "a" * 64}
        )
    elif mutation == "authority":
        s.authority.refuse = True
    else:
        s.owner = await s.states.claim_owner(
            s.operation.request_scope,
            s.identity,
            owner_ref="worker-b",
            generation=2,
            now=NOW + timedelta(minutes=1),
            lease=timedelta(seconds=30),
        )
    if mutation == "generation":
        with pytest.raises(ValueError):
            await drain(s)
    else:
        assert (await drain(s)).budget_controls[record.key].phase == "rejected"
    assert not s.provider.posts


@pytest.mark.parametrize("amount", [None, 0, True, "", "-1", "1.0", "١", "NaN"])
def test_unknown_or_malformed_cost_is_never_zero(amount):
    with pytest.raises(ValueError):
        _strict_usd_minor_units({"currency": "USD", "amount": amount})


def test_legacy_pause_resume_canonical_bytes_omit_new_mode():
    pause = PauseDecision(decision_id="p", scope=frozenset({"run"}), reason="r", authority_ref="a")
    resume = ResumeDecision(decision_id="r", pause_decision_id="p", reason="r", authority_ref="a")
    for decision in (pause, resume):
        assert "budget_gate" not in decision.model_dump(mode="json")
        assert "budget_gate" not in stable_json_dump(decision)


@pytest.mark.parametrize(
    "gate",
    [
        ManagedBudgetGate(target_cap_minor_units=5),
        ManagedBudgetGate(hold_command_id="hold", hold_command_issuer="operator"),
    ],
)
def test_hold_never_silently_ignores_resume_fields(gate):
    with pytest.raises(ValueError, match="resume fields"):
        PauseDecision(
            decision_id="p",
            scope=frozenset({"run"}),
            reason="r",
            authority_ref="a",
            budget_gate=gate,
        )


def test_resume_requires_both_hold_identity_fields():
    with pytest.raises(ValueError, match="hold command"):
        ResumeDecision(
            decision_id="r",
            pause_decision_id="p",
            reason="r",
            authority_ref="a",
            budget_gate=ManagedBudgetGate(hold_command_id="hold"),
        )


async def test_second_hold_after_resume_needs_fresh_boundary():
    s = await stack()
    await observed_hold(s)
    await queue(s, "resume-1", resume="hold-1")
    await drain(s)
    second = await queue(s, "hold-2")
    assert (await drain(s)).budget_controls[second.key].phase == "cap_confirmed"
    s.provider.evidence = "second-held-boundary"
    assert (await drain(s)).budget_controls[second.key].applied
    assert s.provider.posts == [4, 90, 4]


@pytest.mark.parametrize("cap", [4, 91])
async def test_resume_must_raise_held_cap_within_original_ceiling(cap):
    s = await stack()
    await observed_hold(s)
    record = await queue(s, "resume-invalid", resume="hold-1", target=cap)
    state = await drain(s)
    assert state.budget_controls[record.key].phase == "rejected"
    assert s.provider.posts == [4] and held(state.budget_controls)


async def test_overlapping_hold_and_second_resume_cannot_lift_another_hold():
    s = await stack()
    await observed_hold(s)
    overlap = await queue(s, "hold-overlap")
    assert (await drain(s)).budget_controls[overlap.key].phase == "rejected"
    await queue(s, "resume-1", resume="hold-1")
    await drain(s)
    repeated = await queue(s, "resume-again", resume="hold-1")
    assert (await drain(s)).budget_controls[repeated.key].phase == "rejected"
    assert s.provider.posts == [4, 90]


@pytest.mark.parametrize("change", ["approval", "authority", "stop"])
async def test_authority_changes_after_intent_never_send(change):
    s = await stack()
    await observed_hold(s)
    resume = await queue(s, "resume-1", resume="hold-1")
    original_update = s.states.update_budget_control

    async def update(record, **kwargs):
        saved = await original_update(record, **kwargs)
        if record.key == resume.key and record.phase == "intended":
            if change == "approval":
                s.approvals.seal = s.approvals.seal.model_copy(update={"granted": False})
            elif change == "authority":
                s.authority.refuse = True
            else:
                await s.fences.persist(
                    StopFence(
                        request_scope=s.operation.request_scope,
                        run_id=s.operation.identity.run_id,
                        generation=1,
                        command_id="stop-after-intent",
                        reason="stop",
                        requested_at=NOW,
                    )
                )
        return saved

    s.states.update_budget_control = update
    state = await drain(s)
    assert state.budget_controls[resume.key].phase == "in_doubt"
    assert s.provider.posts == [4] and held(state.budget_controls)


@pytest.mark.parametrize(
    "mutation",
    [None, "target", "generation", "scope", "reservation", "pending", "ceiling", "stopping"],
)
async def test_production_authority_checks_exact_target_scope_and_retained_budget(mutation):
    from mission_control.application.execution.operations.operation_execution import (
        RunControlOperationAuthority,
    )
    from mission_control.domain.policies.contracts import (
        BoundaryTarget,
        ExecutionTarget,
        PauseAction,
        ReceiptState,
        ResumeAction,
        RunPhase,
    )

    s = await stack()
    operation = s.operation.model_copy(
        update={"budget_limits": {"currency.estimated_micros": 900_000}}
    )
    target = ExecutionTarget(family="StageGraph", family_workflow_id="family-1")
    boundary = BoundaryTarget(kind="family", target_ref="family-1", family_workflow_id="family-1")
    pause = PauseAction(
        decision=PauseDecision(
            decision_id="pause-1",
            scope=frozenset({"stage:other"} if mutation == "scope" else {"run"}),
            reason="hold",
            authority_ref="authority",
            budget_gate=ManagedBudgetGate(),
        ),
        runnable_work_remains=False,
    )
    resume = ResumeAction(
        decision=ResumeDecision(
            decision_id="resume-1",
            pause_decision_id="pause-1",
            reason="resume",
            authority_ref="authority",
            budget_gate=ManagedBudgetGate(
                hold_command_id="hold-1",
                hold_command_issuer="operator",
                target_cap_minor_units=91 if mutation == "ceiling" else 90,
            ),
        )
    )
    commands = {
        name: SimpleNamespace(
            command=SimpleNamespace(action=action, target=boundary, accepted_run_version=1),
            receipts=[SimpleNamespace(state=ReceiptState.ACCEPTED)],
        )
        for name, action in (("hold-1", pause), ("resume-1", resume))
    }
    if mutation == "target":
        commands["resume-1"].command.target = boundary.model_copy(
            update={"target_ref": "other-family"}
        )
    budget = SimpleNamespace(
        reservations={
            operation.budget_reservation_id: {
                "currency.estimated_micros": 1 if mutation == "reservation" else 900_000
            }
        },
        outstanding_usage_ids={"unknown-cost"} if mutation == "pending" else set(),
        pending_settlement={},
        reserved={"currency.estimated_micros": 900_000},
        consumed={},
        limits=[SimpleNamespace(dimension="currency.estimated_micros", hard_cap=1_000_000)],
    )

    class RunControl:
        async def get_run(self, *args):
            return SimpleNamespace(
                phase=RunPhase.CANCELLING if mutation == "stopping" else RunPhase.PAUSED,
                execution_target=target,
                version=3,
            )

        async def get_boundary_command(self, scope, run, issuer, command_id):
            return commands[command_id]

        async def get_budget(self, *args):
            return budget

    class AuthorityUnderTest(RunControlOperationAuthority):
        async def _verify_bound_authority(self, operation, run):
            # Existing binding verification has its own suite; exercise the new gate.
            pass

    authority = AuthorityUnderTest(RunControl(), None)
    request = LaneBudgetControlRequest(
        operation=operation,
        generation=2 if mutation == "generation" else 1,
        command_id="resume-1",
        command_issuer="operator",
    )
    if mutation is None:
        assert await authority.verify_budget_control(request) is commands["resume-1"].command
    else:
        with pytest.raises(ValueError):
            await authority.verify_budget_control(request)


async def test_native_cancel_after_process_restart_never_lifts_budget(tmp_path):
    from mission_control.domain.execution.lanes import (
        CancelTurnRequest,
        ReattachRequest,
        TurnHandle,
    )
    from tests.fixtures.managed_lane import managed_harness, managed_stack
    from tests.unit.anthropic_managed.test_harness import _fields, _sent, _started

    fixture = managed_stack(tmp_path)
    heid, session = await _started(fixture)
    await fixture.harness.hold_budget(heid, True)
    turn = await _sent(fixture, session)
    successor = managed_harness(fixture.api, fixture.pack, deletions=fixture.deletions)
    successor.stage(heid, fixture.operation)
    attached = await successor.reattach(
        ReattachRequest(
            **_fields(fixture.operation, "reattach"),
            native_session_ref=session.native_session_ref,
            native_turn_ref=turn.native_turn_ref,
        )
    )
    result = await successor.cancel_turn(
        CancelTurnRequest(
            **_fields(fixture.operation, "cancel"),
            turn=TurnHandle(session=attached, turn_no=1, native_turn_ref=turn.native_turn_ref),
            reason="stop",
        )
    )
    assert not result.acknowledged and result.native_status == "budget_reached"
    assert (
        fixture.api.sessions[session.native_session_ref]["budget"]["max_list_cost"]["amount"] == "1"
    )
    assert fixture.api.interrupts() == 0 and not fixture.api.archived()

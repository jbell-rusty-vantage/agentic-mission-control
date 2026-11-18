"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_managed_budget_controls.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from mission_control.application.execution.approvals import ApprovalContextState
from mission_control.application.execution.harness.budget_controls import BudgetControlService
from mission_control.application.execution.harness.state import (
    InMemoryLaneExecutionStateStore,
    LaneExecutionUpdate,
)
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
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
from tests.fixtures.lane_turns import DIGEST
from tests.support.providers.managed_agents import managed_binding, managed_operation

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

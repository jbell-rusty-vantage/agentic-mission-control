"""Builders, constants and fakes that other test files import.

Moved from tests/unit/approvals/test_approval_broker.py.
"""

from __future__ import annotations

from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.approvals_memory import (
    InMemoryApprovalStore,
    StaticApprovalContext,
)
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
from mission_control.application.human_tasks.memory import InMemoryHumanTaskRepository
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.domain.policies.contracts import ActorContext
from tests.support.ids import SCOPE
from tests.unit.approvals.fixtures import POLICY, REVIEWER

OWNER = ActorContext(actor_id=REVIEWER)


def _compose(
    connection_ref: str = "worker-a#1",
    store: InMemoryApprovalStore | None = None,
    context: StaticApprovalContext | None = None,
    fences: InMemoryStopFenceRepository | None = None,
) -> tuple[ApprovalBroker, HumanTaskService, InMemoryApprovalStore, StaticApprovalContext]:
    store = store or InMemoryApprovalStore()
    context = context or StaticApprovalContext(1, POLICY)
    broker = ApprovalBroker(
        store,
        store,
        probe=context,
        connection_ref=connection_ref,
        fences=fences,
        poll_seconds=0.01,
    )
    service = HumanTaskService(
        InMemoryHumanTaskRepository(),
        request_scope=SCOPE,
        approvals=store,
        approval_wake=broker.hub,
    )
    return broker, service, store, context

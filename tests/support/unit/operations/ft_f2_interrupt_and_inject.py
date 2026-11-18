"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_ft_f2_interrupt_and_inject.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.execution.boundary_interventions import BoundaryInterventionService
from mission_control.application.execution.harness.inject import InjectionSettings
from mission_control.application.missions.service import MissionControlService
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.checkpoint_recovery import (
    RecoveryHarness,
    recovery_harness,
)
from tests.support.models import ScriptedChatModel
from tests.support.run_control import actor

FAST = InjectionSettings(poll_seconds=0.01, settle_grace_seconds=0.3, settle_poll_seconds=0.01)


def human_texts(model: ScriptedChatModel) -> list[list[str]]:
    """The text of every human message each call saw."""

    return [[str(item.content) for item in batch if item.type == "human"] for batch in model.seen]


def operator() -> ActorContext:
    source = actor()
    return source.model_copy(
        update={"permissions": source.permissions | {"workflow_run.read", "workflow_run.control"}}
    )


async def harness_with_injections() -> RecoveryHarness:
    return await recovery_harness(injection_settings=FAST)


def facade(harness: RecoveryHarness) -> MissionControlService:
    return MissionControlService(
        harness.run_control,
        BoundaryInterventionService(harness.run_control),
        request_scope="tenant-1",
        mailbox=harness.mailbox,
    )


async def status_of(harness: RecoveryHarness, receipt: Any) -> Any:
    return await harness.run_control.get_boundary_command(
        "tenant-1",
        harness.run_id,
        receipt.delivery.command.idempotency_issuer,
        str(receipt.request_id),
    )


def states(status: Any) -> list[str]:
    return [item.state.value for item in status.receipts]

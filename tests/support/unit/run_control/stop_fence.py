"""Builders, constants and fakes that other test files import.

Moved from tests/unit/run_control/test_stop_fence.py.
"""

from __future__ import annotations

from uuid import uuid4

from mission_control.contracts.contracts import CancelPayload, CommandTarget, MissionCommandRequest
from mission_control.domain.policies.contracts import ActorContext
from tests.support.unit.run_control.mission_control_facade import actor


def _cancel(run_id: str, version: int, urgency: str) -> MissionCommandRequest:
    return MissionCommandRequest(
        request_id=uuid4(),
        expected_version=version,
        expected_generation=1,
        target=CommandTarget(id=run_id),
        kind="cancel",
        payload=CancelPayload(urgency=urgency),  # type: ignore[arg-type]
        reason="wrong repo",
    )


def admin() -> ActorContext:
    source = actor()
    return source.model_copy(update={"permissions": source.permissions | {"workflow_run.admin"}})

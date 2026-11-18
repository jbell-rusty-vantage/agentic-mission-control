"""Builders, constants and fakes that other test files import.

Moved from tests/unit/run_control/test_mission_control_facade.py.
"""

from uuid import uuid4

from mission_control.contracts.contracts import CommandTarget, MissionCommandRequest, PausePayload
from mission_control.domain.policies.contracts import ActorContext
from tests.support.boundary_commands import pause
from tests.support.run_control import actor as control_actor


def actor() -> ActorContext:
    source = control_actor()
    return source.model_copy(update={"permissions": source.permissions | {"workflow_run.read"}})


def pause_request(run_id: str, version: int = 2) -> MissionCommandRequest:
    action = pause()
    return MissionCommandRequest(
        request_id=uuid4(),
        expected_version=version,
        expected_generation=1,
        target=CommandTarget(id=run_id),
        kind="pause",
        payload=PausePayload(
            decision=action.decision, runnable_work_remains=action.runnable_work_remains
        ),
        reason="operator hold",
    )

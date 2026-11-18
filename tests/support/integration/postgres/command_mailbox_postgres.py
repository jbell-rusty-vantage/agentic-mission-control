"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_command_mailbox_postgres.py.
"""

from __future__ import annotations

from uuid import uuid4

from mission_control.contracts.contracts import MissionCommandRequest
from mission_control.domain.policies.contracts import ActorContext
from tests.support.run_control import actor


def operator() -> ActorContext:
    source = actor()
    return source.model_copy(
        update={"permissions": source.permissions | {"workflow_run.read", "workflow_run.control"}}
    )


def _request(
    run_id: str, version: int, kind: str, payload: dict[str, object]
) -> MissionCommandRequest:
    return MissionCommandRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "expected_version": version,
            "expected_generation": 1,
            "target": {"kind": "run", "id": run_id},
            "kind": kind,
            "payload": payload,
            "reason": "operator steering",
        }
    )

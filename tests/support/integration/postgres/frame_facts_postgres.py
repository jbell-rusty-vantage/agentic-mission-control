"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_frame_facts_postgres.py.
"""

from __future__ import annotations

from mission_control.domain.policies.contracts import ActorContext
from tests.support.run_control import ALL_PERMISSIONS, actor


def projector_actor() -> ActorContext:
    return actor().model_copy(
        update={"permissions": ALL_PERMISSIONS | {"workflow_run.apply_frame_facts"}}
    )

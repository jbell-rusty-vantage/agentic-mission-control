"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_continuation_postgres.py.
"""

from __future__ import annotations

from mission_control.domain.policies.contracts import ActorContext
from tests.support.run_control import ALL_PERMISSIONS, actor


def continuation_actor() -> ActorContext:
    return actor().model_copy(
        update={
            "permissions": ALL_PERMISSIONS
            | {
                "workflow_run.record_continuation",
                "workflow_run.request_continuation",
                "workflow_run.read",
            }
        }
    )

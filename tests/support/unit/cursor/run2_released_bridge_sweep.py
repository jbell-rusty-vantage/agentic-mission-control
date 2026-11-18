# ruff: noqa: C408
"""Builders, constants and fakes that other test files import.

Moved from tests/unit/cursor/test_released_bridge_sweep.py.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.application.workspaces.policy import slot_path

SCOPE = "installation/application/tenant"


def lease(root, **updates):
    now = datetime.now(UTC)
    values = dict(
        lease_id=uuid4(),
        request_scope=SCOPE,
        lease_key="cursor:released",
        lane_profile="cursor_local",
        harness_execution_id=uuid4(),
        generation=1,
        run_id="run",
        attempt_no=1,
        path=str(slot_path(root, SCOPE, "slot")),
        base_ref="HEAD",
        base_commit="a" * 40,
        fence=1,
        expires_at=now - timedelta(hours=1),
        released_at=now,
        slot="slot",
        allocator_ref="owner",
        observed_state="released",
    )
    values.update(updates)
    return WorkspaceLease(**values)

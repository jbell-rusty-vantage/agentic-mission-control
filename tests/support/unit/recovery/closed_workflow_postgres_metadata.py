"""Builders, constants and fakes that other test files import.

Moved from tests/unit/recovery/test_closed_workflow_postgres_metadata.py.
"""

from datetime import UTC, datetime

from mission_control.application.execution.harness.dispatch import DispatchRecord


def record():
    return DispatchRecord(
        kind="create",
        idempotency_key="actual-key",
        expected_generation=1,
        instruction_digest="sha256:" + "a" * 64,
        owner_ref="owner",
        owner_epoch=1,
        intended_at=datetime.now(UTC),
        resolved_at=datetime.now(UTC),
        phase="acknowledged",
        native_ref="actual-native",
    )

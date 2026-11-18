"""Builders, constants and fakes that other test files import.

Moved from tests/unit/signals/test_drainer.py.
"""

from datetime import UTC, datetime
from uuid import uuid4

from mission_control.application.signals.drainer import DrainItem


def item(attempts=0):
    return DrainItem(
        uuid4(),
        "scope",
        uuid4(),
        "ai-engineer",
        "signal.test",
        "credential",
        "delivery",
        {},
        datetime.now(UTC),
        generation=1,
        attempts=attempts,
    )

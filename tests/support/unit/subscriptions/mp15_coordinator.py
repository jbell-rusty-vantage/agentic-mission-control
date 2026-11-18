"""Builders, constants and fakes that other test files import.

Moved from tests/unit/subscriptions/test_mp15_coordinator.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.subscriptions.coordinator import (
    CoordinatorProfile,
    JournalEvent,
    classify,
)
from tests.unit.subscriptions.coordinator_fakes import journal_event


def classify_type(event_type: str, profile: CoordinatorProfile | None = None, **facts: Any):
    found = classify(
        JournalEvent(journal_event(1, event_type), facts), profile or CoordinatorProfile()
    )
    return None if found is None else (found.kind, found.actionable, found.public_event_type)

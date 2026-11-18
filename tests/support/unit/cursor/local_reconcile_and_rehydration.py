"""Builders, constants and fakes that other test files import.

Moved from tests/unit/cursor/test_local_reconcile_and_rehydration.py.
"""

from __future__ import annotations

from mission_control.adapters.cursor.local import CursorLocalHarness


def _fresh(stack) -> CursorLocalHarness:  # type: ignore[no-untyped-def]
    """A harness in a 'new process' over the same launcher, leases, hooks and artifacts."""

    source = stack.harness
    return CursorLocalHarness(
        launcher=source._launcher,
        leaser=source._leaser,
        projections=source._projections,
        hooks=source._hooks,
        artifacts=source._artifacts,
        settings=source._settings,
    )

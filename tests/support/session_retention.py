"""Fakes of the hosted session retention ports (HL-18), for lane fakes and conformance.

`RecordingDeletionScheduler` keeps every deletion order by its key (ordering a session again
is the same order); `FakeSessionDeleter` is a provider with a set of live sessions, optionally
failing its first deletions as an outage would.
"""

from __future__ import annotations

from collections.abc import Iterable

from mission_control.application.execution.harness.retention import SessionDeletionOutcome
from mission_control.domain.execution.session_retention import SessionDeletion


class RecordingDeletionScheduler:
    def __init__(self) -> None:
        self.orders: dict[str, SessionDeletion] = {}

    async def schedule(self, deletion: SessionDeletion) -> None:
        self.orders.setdefault(deletion.key, deletion)


class FakeSessionDeleter:
    def __init__(self, live: Iterable[str] = (), *, failures: int = 0) -> None:
        self.live = set(live)
        self.calls: list[str] = []
        self._failures = failures

    async def delete_session(self, session_ref: str) -> SessionDeletionOutcome:
        self.calls.append(session_ref)
        if self._failures:
            self._failures -= 1
            raise ConnectionError("provider unavailable")
        if session_ref not in self.live:
            return "absent"
        self.live.discard(session_ref)
        return "deleted"


__all__ = ["FakeSessionDeleter", "RecordingDeletionScheduler"]

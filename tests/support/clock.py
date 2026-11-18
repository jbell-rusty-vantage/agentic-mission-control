"""The one deterministic test clock.

``Clock`` stands in for the wall clock wherever code takes a ``now`` callable
(``clock=...``, ``now=...``): ``clock()`` returns ``clock.now``. Tests set the time with
``clock.now = at`` or ``clock.set(at)`` and move it with ``clock.advance(delta)``.

A clock built with ``step`` advances by that much after each read, so successive reads
are strictly ordered (``Clock(start, step=SECOND)`` returns ``start``, ``start + 1s``, ...).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

CLOCK_START = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
SECOND = timedelta(seconds=1)


class Clock:
    """A settable, advanceable clock; ``step`` makes it advance on every read."""

    def __init__(self, start: datetime = CLOCK_START, *, step: timedelta = timedelta(0)) -> None:
        self.now = start
        self.step = step

    @classmethod
    def from_wall_time(cls, *, step: timedelta = timedelta(0)) -> Clock:
        """A clock starting at the real current time, for rows compared with database time."""
        return cls(datetime.now(UTC), step=step)

    def __call__(self) -> datetime:
        current = self.now
        self.now = current + self.step
        return current

    def set(self, at: datetime) -> None:
        self.now = at

    def advance(self, delta: timedelta | float) -> datetime:
        """Move the clock forward by ``delta`` (a timedelta, or seconds) and return the time."""
        self.now += delta if isinstance(delta, timedelta) else timedelta(seconds=delta)
        return self.now

"""Ports of the Watcher Evaluator (SPEC-04 §5.3): the journal it reads and the run it acts on."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mission_control.contracts.contracts import MissionCommandReceipt, MissionCommandRequest
from mission_control.domain.policies.contracts import ActorContext, DomainEventEnvelope
from mission_control.domain.programs.watchers import FiringRecord, Observation, WatcherDescriptor


@dataclass(frozen=True)
class WatcherCursor:
    """How far a run's evaluation has read: the journal sequence and the signal frames.

    ``signal_at`` and ``signal_ref`` are the last signal frame read, positioned by the time the
    store inserted it (not the producer's observation time), then by frame id.
    """

    event_seq: int = 0
    signal_at: datetime | None = None
    signal_ref: str | None = None


@dataclass(frozen=True)
class ObservationPage:
    observations: tuple[Observation, ...]
    cursor: WatcherCursor
    exhausted: bool


class WatcherStore(Protocol):
    """The run's compiled watchers, its journal and signals, and the firing records.

    ``observations`` returns committed mission events after the cursor's sequence and ingested
    signal frames after its signal position, merged in time order; ``last_seen`` names the
    latest event (``watcher.*`` excluded), frame and signal time; ``usage`` is the run's
    budget usage by dimension (settled, pending and reserved). ``record`` appends one
    ``watcher.fired`` or ``watcher.failed`` event idempotently and answers False when that
    event id is already in the journal.
    """

    async def descriptors(self, run_id: str) -> tuple[WatcherDescriptor, ...]: ...

    async def observations(
        self, run_id: str, *, after: WatcherCursor, limit: int
    ) -> ObservationPage: ...

    async def history(self, run_id: str) -> tuple[FiringRecord, ...]: ...

    async def last_seen(self, run_id: str) -> Mapping[str, datetime]: ...

    async def usage(self, run_id: str) -> Mapping[str, int]: ...

    async def record(self, run_id: str, event: DomainEventEnvelope) -> bool: ...


class WatcherStartPort(Protocol):
    """Starts a run's Watcher Evaluator (``mc.watchers.v1``); idempotent per run."""

    async def start(self, request_scope: str, run_id: str) -> str: ...


class WatcherWaitView(Protocol):
    @property
    def condition_id(self) -> str: ...


class WatcherProjectionView(Protocol):
    @property
    def active_waits(self) -> Sequence[WatcherWaitView]: ...


class WatcherRunView(Protocol):
    """What the evaluator reads of ``mc.inspection.v1``: the frontier and the active waits a
    ``satisfy_wait`` firing waits for."""

    @property
    def version(self) -> int: ...

    @property
    def execution_generation(self) -> int: ...

    @property
    def lifecycle(self) -> str: ...

    @property
    def phase(self) -> str: ...

    @property
    def execution_outcome(self) -> str | None: ...

    @property
    def projection(self) -> WatcherProjectionView: ...


class WatcherRunGateway(Protocol):
    """The admitted command path (``MissionControlService``): every action is a Command."""

    async def inspect(self, run_id: str, actor: ActorContext) -> WatcherRunView: ...

    async def command(
        self, run_id: str, request: MissionCommandRequest, actor: ActorContext
    ) -> MissionCommandReceipt: ...


__all__ = [
    "ObservationPage",
    "WatcherCursor",
    "WatcherProjectionView",
    "WatcherRunGateway",
    "WatcherRunView",
    "WatcherStartPort",
    "WatcherStore",
    "WatcherWaitView",
]

"""In-memory Watcher Evaluator ports: a journal-backed store and the admitted command path.

The store behaves like the PostgreSQL one: recorded firings join the journal as
``watcher.*`` events (so later passes see them), a record is keyed by its event id, and the
history is read back from the journal. The gateway answers a repeated request id with a
replay receipt, as run control does.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from mission_control.application.watchers.ports import ObservationPage, WatcherCursor
from mission_control.contracts.contracts import (
    MissionCommandReceipt,
    MissionCommandRequest,
    MissionControlRejected,
)
from mission_control.domain.policies.contracts import (
    ActorContext,
    CommandResult,
    CommandStatus,
    DomainEventEnvelope,
    RunPhase,
)
from mission_control.domain.policies.errors import IdempotencyConflict
from mission_control.domain.programs.watchers import (
    WATCHER_EVENTS,
    FiringRecord,
    Observation,
    TrustTier,
    WatcherDescriptor,
    firing_record,
)

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
RUN_ID = "run-1"
DIGEST = "sha256:" + "0" * 64


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


class MemoryWatcherStore:
    def __init__(
        self,
        descriptors: tuple[WatcherDescriptor, ...] = (),
        *,
        usage: Mapping[str, int] | None = None,
    ) -> None:
        self.programs: dict[str, tuple[WatcherDescriptor, ...]] = {RUN_ID: descriptors}
        self.events: list[Observation] = []
        self.signals: list[Observation] = []
        self.frames: list[datetime] = []
        self.recorded: list[DomainEventEnvelope] = []
        self.usage_by_dimension: dict[str, int] = dict(usage or {})
        self.fail_records = 0

    # -- seeding ----------------------------------------------------------------------------

    def event(
        self,
        event_type: str,
        data: Mapping[str, Any] | None = None,
        *,
        when: datetime,
        alias: str | None = None,
        causation_ref: str | None = None,
        node_key: str | None = None,
    ) -> Observation:
        observation = Observation(
            source="event",
            ref=str(uuid4()),
            types=(event_type, alias) if alias else (event_type,),
            at=when,
            seq=len(self.events) + 1,
            causation_ref=causation_ref,
            node_key=node_key,
            data=dict(data or {}),
        )
        self.events.append(observation)
        return observation

    def signal(
        self,
        signal_type: str,
        data: Mapping[str, Any] | None = None,
        *,
        when: datetime,
        trust: TrustTier | None = "run_token",
    ) -> Observation:
        observation = Observation(
            source="signal",
            ref=f"frame-{len(self.signals) + 1:04d}",
            types=(signal_type,),
            at=when,
            data=dict(data or {}),
            trust=trust,
        )
        self.signals.append(observation)
        return observation

    # -- WatcherStore -------------------------------------------------------------------------

    async def descriptors(self, run_id: str) -> tuple[WatcherDescriptor, ...]:
        return self.programs.get(run_id, ())

    async def observations(
        self, run_id: str, *, after: WatcherCursor, limit: int
    ) -> ObservationPage:
        del run_id
        events = [item for item in self.events if (item.seq or 0) > after.event_seq][:limit]
        signals = [
            item
            for item in sorted(self.signals, key=lambda item: (item.at, item.ref))
            if after.signal_at is None or (item.at, item.ref) > (after.signal_at, after.signal_ref)
        ][:limit]
        merged = sorted(
            [*events, *signals],
            key=lambda item: (item.at, item.source != "event", item.seq or 0, item.ref),
        )
        taken = merged[:limit]
        cursor = after
        for item in taken:
            if item.source == "event":
                cursor = WatcherCursor(item.seq or 0, cursor.signal_at, cursor.signal_ref)
            else:
                cursor = WatcherCursor(cursor.event_seq, item.at, item.ref)
        exhausted = len(events) < limit and len(signals) < limit and len(merged) <= limit
        return ObservationPage(tuple(taken), cursor, exhausted)

    async def history(self, run_id: str) -> tuple[FiringRecord, ...]:
        del run_id
        records = (firing_record(item.payload, item.event_type) for item in self.recorded)
        return tuple(record for record in records if record is not None)

    async def last_seen(self, run_id: str) -> Mapping[str, datetime]:
        del run_id
        seen: dict[str, datetime] = {}
        events = [item.at for item in self.events if item.types[0] not in WATCHER_EVENTS]
        for name, moments in (
            ("event", events),
            ("frame", self.frames),
            ("signal", [item.at for item in self.signals]),
        ):
            if moments:
                seen[name] = max(moments)
        return seen

    async def usage(self, run_id: str) -> Mapping[str, int]:
        del run_id
        return dict(self.usage_by_dimension)

    async def record(self, run_id: str, event: DomainEventEnvelope) -> bool:
        del run_id
        if self.fail_records:
            self.fail_records -= 1
            raise ConnectionError("journal unavailable")
        if any(item.event_id == event.event_id for item in self.recorded):
            return False
        self.recorded.append(event)
        self.events.append(
            Observation(
                source="event",
                ref=str(uuid4()),
                types=(event.event_type,),
                at=event.recorded_at,
                seq=len(self.events) + 1,
                data=dict(event.payload),
            )
        )
        return True

    # -- assertions ---------------------------------------------------------------------------

    def fired(self, watcher_id: str | None = None) -> list[dict[str, Any]]:
        return [
            item.payload
            for item in self.recorded
            if watcher_id is None or item.payload["watcher_id"] == watcher_id
        ]


@dataclass(frozen=True)
class Wait:
    condition_id: str


@dataclass
class Projection:
    active_waits: list[Wait] = field(default_factory=list)


@dataclass
class RunView:
    version: int = 3
    execution_generation: int = 1
    lifecycle: str = "running"
    phase: str = "active"
    execution_outcome: str | None = None
    projection: Projection = field(default_factory=Projection)

    def declare(self, *condition_ids: str) -> None:
        """The StageGraph declared these waits (run control holds them as active)."""

        self.projection.active_waits.extend(Wait(item) for item in condition_ids)


@dataclass
class FakeRunGateway:
    """The command path: admits each request id once and replays it afterwards; like the
    reducer, it refuses to release a wait that is not active (``wait_not_found``)."""

    view: RunView = field(default_factory=RunView)
    admitted: dict[str, MissionCommandRequest] = field(default_factory=dict)
    calls: list[MissionCommandRequest] = field(default_factory=list)
    inspections: int = 0
    stale_once: set[str] = field(default_factory=set)
    reject: dict[str, str] = field(default_factory=dict)
    transient: int = 0
    actors: list[ActorContext] = field(default_factory=list)

    async def inspect(self, run_id: str, actor: ActorContext) -> RunView:
        assert run_id == RUN_ID
        self.inspections += 1
        return self.view

    async def command(
        self, run_id: str, request: MissionCommandRequest, actor: ActorContext
    ) -> MissionCommandReceipt:
        self.calls.append(request)
        self.actors.append(actor)
        if self.transient:
            self.transient -= 1
            raise TimeoutError("run control unavailable")
        if request.kind in self.reject:
            raise MissionControlRejected(self.reject[request.kind], "refused by the fake")
        key = str(request.request_id)
        if key in self.stale_once:
            self.stale_once.discard(key)
            self.view.version += 1
            raise MissionControlRejected("stale_version", "run version changed")
        prior = self.admitted.get(key)
        if prior is not None and prior.expected_version != request.expected_version:
            # Run control binds the frontier into the command fingerprint.
            raise IdempotencyConflict("lifecycle command identity was reused with a new payload")
        replay = prior is not None
        if request.kind == "satisfy_wait" and not replay:
            condition_id = request.payload.model_dump()["condition_id"]
            waits = self.view.projection.active_waits
            if Wait(condition_id) not in waits:
                raise MissionControlRejected("wait_not_found", "wait condition is not active")
            waits.remove(Wait(condition_id))
        self.admitted.setdefault(key, request)
        return MissionCommandReceipt(
            request_id=request.request_id,
            replay=replay,
            admission=CommandResult(
                command_id=key,
                idempotency_issuer="fake",
                run_id=run_id,
                command_fingerprint=DIGEST,
                status=CommandStatus.ACCEPTED,
                resulting_run_version=self.view.version,
                phase=RunPhase.ACTIVE,
                reason_code="accepted",
                reason="accepted",
                recorded_at=T0,
            ),
        )

    def kinds(self) -> list[str]:
        return [request.kind for request in self.admitted.values()]

"""FIXTURE: in-memory coordinator inbox store and command gateway for unit tests (no I/O).

Mirrors `PostgresCoordinatorInboxStore` semantics (row lock = one call at a time, open-only
upserts, acknowledged cursor = last inbox_seq before the first pending one). The PostgreSQL
behaviour itself is proven in `tests/integration/postgres/test_mp15_*`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid5

from mission_control.application.subscriptions.coordinator import (
    CoordinatorNotification,
    JournalEvent,
    PlanInput,
)
from mission_control.application.subscriptions.coordinator_ports import (
    AckOutcome,
    CausationOrigin,
    CausationRecord,
    CoordinatorInbox,
    MaterializeResult,
    NewInbox,
    NewObservation,
    Planner,
    PromptRecord,
    PromptState,
    SealedNotice,
    StoredObservation,
)
from mission_control.application.subscriptions.ports import SubscriptionNotFound
from mission_control.contracts.contracts import (
    LaneView,
    MissionCommandReceipt,
    MissionCommandRequest,
    MissionControlRejected,
)
from mission_control.domain.coordinator.attention import (
    MAX_TRANSPORT_OBSERVATIONS,
    DeliveryStage,
    StageObservation,
)
from mission_control.domain.policies.contracts import (
    ActorContext,
    CommandResult,
    CommandStatus,
    RunPhase,
)
from mission_control.domain.subscriptions.contracts import (
    MissionEventEnvelope,
    Subscription,
    SubscriptionState,
    payload_digest,
)
from tests.unit.subscriptions.fakes import MISSION, RUN, SCOPE, T0, InMemoryStore


def journal_event(
    seq: int,
    event_type: str,
    *,
    run_id: UUID | None = RUN,
    causation_ref: str | None = None,
    recorded_at: datetime | None = None,
) -> MissionEventEnvelope:
    moment = recorded_at or T0 + timedelta(seconds=seq)
    return MissionEventEnvelope(
        event_id=uuid5(MISSION, f"journal:{seq}"),
        application_id="biotech",
        mission_id=MISSION,
        run_id=run_id,
        seq=seq,
        event_type=event_type,
        event_version=1,
        actor_ref="actor:system",
        happened_at=moment,
        recorded_at=moment,
        causation_ref=causation_ref,
        payload_ref=f"mc://applications/biotech/missions/{MISSION}/events/{seq}",
        payload_digest=payload_digest({"seq": seq}),
    )


@dataclass
class InMemoryInboxStore:
    subscriptions: InMemoryStore
    facts: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    inboxes: dict[UUID, CoordinatorInbox] = field(default_factory=dict)
    rows: dict[UUID, CoordinatorNotification] = field(default_factory=dict)
    prompts: dict[UUID, PromptRecord] = field(default_factory=dict)
    causations: dict[UUID, CausationRecord] = field(default_factory=dict)
    acked_by: dict[UUID, str] = field(default_factory=dict)

    @property
    def request_scope(self) -> str:
        return SCOPE

    def add(self, envelope: MissionEventEnvelope, **facts: Any) -> MissionEventEnvelope:
        self.subscriptions.events.append(envelope)
        self.facts[envelope.event_id] = facts
        return envelope

    def _view(self, subscription_id: UUID) -> CoordinatorInbox:
        if subscription_id not in self.inboxes:
            raise SubscriptionNotFound(str(subscription_id))
        inbox = self.inboxes[subscription_id]
        subscription = self.subscriptions.subscriptions[subscription_id]
        return inbox.model_copy(
            update={
                "state": subscription.state,
                "cursor_seq": subscription.cursor_seq,
                "target": subscription.target,
            }
        )

    async def create(self, inbox: NewInbox) -> CoordinatorInbox:
        subscription = self.subscriptions.subscriptions[inbox.subscription_id]
        self.inboxes[inbox.subscription_id] = CoordinatorInbox(
            subscription_id=inbox.subscription_id,
            coordinator_ref=inbox.coordinator_ref,
            coordinator_run_ref=inbox.coordinator_run_ref,
            target=subscription.target,
            profile=inbox.profile,
            delivery=inbox.delivery,
            state=subscription.state,
            cursor_seq=subscription.cursor_seq,
            next_inbox_seq=1,
            acked_inbox_seq=0,
            created_at=inbox.now,
            updated_at=inbox.now,
            version=1,
        )
        return self._view(inbox.subscription_id)

    async def get(self, subscription_id: UUID) -> CoordinatorInbox:
        return self._view(subscription_id)

    async def active_inboxes(
        self,
        *,
        delivery: Literal["poll", "mcp_session", "webhook"] | None = None,
        prompting: bool = False,
    ) -> tuple[UUID, ...]:
        found = []
        for subscription_id in self.inboxes:
            view = self._view(subscription_id)
            if view.state is SubscriptionState.CLOSED:
                continue
            if delivery is not None and view.delivery.kind != delivery:
                continue
            if prompting and view.profile.prompt_mode == "off":
                continue
            found.append(subscription_id)
        return tuple(found)

    async def materialize(
        self, subscription_id: UUID, *, planner: Planner, now: datetime, page: int, max_pages: int
    ) -> MaterializeResult:
        inbox = self._view(subscription_id)
        if inbox.state is SubscriptionState.CLOSED:
            return MaterializeResult((), 0, inbox.cursor_seq, 0)
        cursor = inbox.cursor_seq
        next_seq = inbox.next_inbox_seq
        sealed: list[CoordinatorNotification] = []
        suppressed = 0
        pages = 0
        while pages < max_pages:
            envelopes = await self.subscriptions.events_after(inbox.target, cursor, page)
            events = tuple(
                JournalEvent(item, self.facts.get(item.event_id, {})) for item in envelopes
            )
            recent: dict[UUID | None, list[datetime]] = {}
            for row in self.rows.values():
                if (
                    row.subscription_id == subscription_id
                    and row.state in {"pending", "acknowledged"}
                    and row.sealed_at is not None
                    and row.sealed_at > now - inbox.profile.rate_window
                ):
                    recent.setdefault(row.run_id, []).append(row.sealed_at)
            depths = {
                str(record.command_request_id): record.depth for record in self.causations.values()
            }
            result = planner(
                PlanInput(
                    subscription_id=subscription_id,
                    mission_id=inbox.target.mission_id,
                    profile=inbox.profile,
                    cursor_seq=cursor,
                    next_inbox_seq=next_seq,
                    open=tuple(
                        row
                        for row in self.rows.values()
                        if row.subscription_id == subscription_id and row.state == "open"
                    ),
                    recent_sealed={run: tuple(items) for run, items in recent.items()},
                    depths=depths,
                    events=events,
                    now=now,
                )
            )
            for item in result.upserts:
                CoordinatorNotification.model_validate(item.model_dump())
                prior = self.rows.get(item.notification_id)
                if prior is not None and prior.state != "open":
                    continue  # sealed/suppressed rows are never rewritten
                self.rows[item.notification_id] = item
                if item.state == "pending":
                    sealed.append(item)
                elif item.state == "suppressed":
                    suppressed += 1
            pages += 1
            subscription = self.subscriptions.subscriptions[subscription_id]
            self.subscriptions.subscriptions[subscription_id] = subscription.model_copy(
                update={"cursor_seq": max(subscription.cursor_seq, result.cursor_seq)}
            )
            cursor = result.cursor_seq
            next_seq = result.next_inbox_seq
            if len(envelopes) < page:
                break
        self.inboxes[subscription_id] = self.inboxes[subscription_id].model_copy(
            update={"next_inbox_seq": next_seq}
        )
        return MaterializeResult(tuple(sealed), suppressed, cursor, pages)

    async def notifications(
        self, subscription_id: UUID, *, after_inbox_seq: int, limit: int
    ) -> tuple[CoordinatorNotification, ...]:
        found = sorted(
            (
                row
                for row in self.rows.values()
                if row.subscription_id == subscription_id
                and row.state == "pending"
                and row.inbox_seq is not None
                and row.inbox_seq > after_inbox_seq
            ),
            key=lambda row: row.inbox_seq or 0,
        )
        return tuple(found[:limit])

    async def notification(
        self, subscription_id: UUID, notification_id: UUID
    ) -> CoordinatorNotification | None:
        row = self.rows.get(notification_id)
        return row if row is not None and row.subscription_id == subscription_id else None

    async def acknowledge(
        self,
        subscription_id: UUID,
        *,
        notification_ids: tuple[UUID, ...],
        through_inbox_seq: int | None,
        actor_ref: str,
        now: datetime,
    ) -> AckOutcome:
        inbox = self._view(subscription_id)
        newly: list[UUID] = []
        for row in list(self.rows.values()):
            if row.subscription_id != subscription_id or row.state != "pending":
                continue
            assert row.inbox_seq is not None
            if row.notification_id in notification_ids or (
                through_inbox_seq is not None and row.inbox_seq <= through_inbox_seq
            ):
                self.rows[row.notification_id] = row.model_copy(
                    update={"state": "acknowledged", "acknowledged_at": now}
                )
                self.acked_by[row.notification_id] = actor_ref
                newly.append(row.notification_id)
        acknowledged = {
            row.notification_id
            for row in self.rows.values()
            if row.subscription_id == subscription_id and row.state == "acknowledged"
        }
        pending = [
            row.inbox_seq or 0
            for row in self.rows.values()
            if row.subscription_id == subscription_id and row.state == "pending"
        ]
        acked = (min(pending) - 1) if pending else inbox.next_inbox_seq - 1
        acked = max(acked, inbox.acked_inbox_seq)
        self.inboxes[subscription_id] = self.inboxes[subscription_id].model_copy(
            update={"acked_inbox_seq": acked}
        )
        return AckOutcome(
            acknowledged=tuple(newly),
            already=tuple(
                item for item in notification_ids if item in acknowledged and item not in newly
            ),
            unknown=tuple(item for item in notification_ids if item not in acknowledged),
            acked_inbox_seq=acked,
        )

    async def record_causation(self, record: CausationRecord) -> CausationRecord:
        return self.causations.setdefault(record.command_request_id, record)

    async def causations_since(
        self,
        subscription_id: UUID,
        *,
        origin: CausationOrigin,
        since: datetime,
        target_run_ref: str | None = None,
        exclude_request_id: UUID | None = None,
    ) -> int:
        return sum(
            1
            for record in self.causations.values()
            if record.subscription_id == subscription_id
            and record.origin == origin
            and record.recorded_at > since
            and (target_run_ref is None or record.target_run_ref == target_run_ref)
            and record.command_request_id != exclude_request_id
        )

    async def begin_prompt(
        self,
        subscription_id: UUID,
        notification_id: UUID,
        *,
        request_id: UUID,
        request: Mapping[str, Any],
        now: datetime,
    ) -> PromptRecord:
        prior = self.prompts.get(notification_id)
        if prior is None or prior.state == "failed":
            prior = PromptRecord(notification_id, request_id, dict(request), "requested")
            self.prompts[notification_id] = prior
        return prior

    async def finish_prompt(
        self,
        subscription_id: UUID,
        notification_id: UUID,
        *,
        state: PromptState,
        detail: str | None,
        now: datetime,
    ) -> None:
        prior = self.prompts.get(notification_id)
        if prior is not None and prior.state == "admitted":
            return
        self.prompts[notification_id] = PromptRecord(
            notification_id,
            prior.request_id if prior is not None else notification_id,
            dict(prior.request) if prior is not None else {},
            state,
            detail,
        )

    async def prompt_candidates(
        self, subscription_id: UUID, *, limit: int
    ) -> tuple[tuple[CoordinatorNotification, PromptRecord | None], ...]:
        found = []
        for row in sorted(self.rows.values(), key=lambda item: item.inbox_seq or 0):
            if row.subscription_id != subscription_id or row.state != "pending":
                continue
            if not row.actionable:
                continue
            record = self.prompts.get(row.notification_id)
            if record is not None and record.state not in {"requested", "failed"}:
                continue
            found.append((row, record))
        return tuple(found[:limit])

    async def lease_callbacks(
        self, *, now: datetime, owner: str, lease_seconds: int, limit: int
    ) -> tuple[Subscription, ...]:
        due: list[Subscription] = []
        for subscription_id in self.inboxes:
            view = self._view(subscription_id)
            subscription = self.subscriptions.subscriptions[subscription_id]
            if (
                view.delivery.kind == "webhook"
                and subscription.state is SubscriptionState.ACTIVE
                and subscription.next_attempt_at <= now
                and subscription_id not in self.subscriptions.leases
            ):
                self.subscriptions.leases[subscription_id] = owner
                due.append(subscription)
        return tuple(due[:limit])


@dataclass
class InMemoryAttentionStore:
    """FIXTURE: the 0063 observation table over an in-memory inbox (WI-19)."""

    inbox: InMemoryInboxStore
    present: bool = True
    rows: dict[tuple[UUID, str, str], NewObservation] = field(default_factory=dict)

    @property
    def request_scope(self) -> str:
        return SCOPE

    async def installed(self) -> bool:
        return self.present

    def _stage(self, item: NewObservation) -> StageObservation:
        return StageObservation(
            stage=item.stage,
            channel=item.channel,
            observer=item.observer,
            result=item.result,
            received_at=item.received_at,
            observed_at=item.observed_at if item.observer == "host" else None,
            actor_ref=item.actor_ref,
            observation_key=item.observation_key,
            evidence=dict(item.evidence),
            nonce_digest=item.nonce_digest,
            transport_key=item.transport_key,
        )

    async def record(self, observation: NewObservation) -> StoredObservation:
        notification = self.inbox.rows.get(observation.notification_id)
        assert notification is not None and notification.state in {"pending", "acknowledged"}
        key = (observation.notification_id, observation.stage.value, observation.observation_key)
        prior = self.rows.get(key)
        if prior is not None:
            return StoredObservation(self._stage(prior), prior.notice_digest, False)
        self.rows[key] = observation
        return StoredObservation(self._stage(observation), observation.notice_digest, True)

    async def record_transport(
        self,
        subscription_id: UUID,
        notices: tuple[tuple[UUID, str, str], ...],
        *,
        channel: str,
        actor_ref: str,
        at: datetime,
    ) -> tuple[UUID, ...]:
        recorded: list[UUID] = []
        for notification_id, digest, nonce in notices:
            count = sum(
                1
                for (nid, stage, _key), row in self.rows.items()
                if nid == notification_id and stage == "transport" and row.channel == channel
            )
            if count >= MAX_TRANSPORT_OBSERVATIONS:
                continue
            stored = await self.record(
                NewObservation(
                    subscription_id=subscription_id,
                    notification_id=notification_id,
                    stage=DeliveryStage.TRANSPORT,
                    channel=channel,
                    observer="server",
                    result="delivered",
                    observation_key=f"{channel}:{count + 1}",
                    notice_digest=digest,
                    observed_at=at,
                    received_at=at,
                    actor_ref=actor_ref,
                    nonce_digest=nonce,
                )
            )
            if stored.created:
                recorded.append(notification_id)
        return tuple(recorded)

    async def observations(
        self, subscription_id: UUID, notification_ids: tuple[UUID, ...]
    ) -> Mapping[UUID, tuple[StageObservation, ...]]:
        found: dict[UUID, list[StageObservation]] = {}
        for (nid, _stage, _key), row in sorted(
            self.rows.items(), key=lambda item: (item[1].received_at, item[0][2])
        ):
            if nid in notification_ids and row.subscription_id == subscription_id:
                found.setdefault(nid, []).append(self._stage(row))
        return {key: tuple(value) for key, value in found.items()}

    async def sealed(
        self, subscription_id: UUID, *, after_inbox_seq: int, limit: int
    ) -> tuple[SealedNotice, ...]:
        rows = sorted(
            (
                row
                for row in self.inbox.rows.values()
                if row.subscription_id == subscription_id
                and row.state in {"pending", "acknowledged"}
                and (row.inbox_seq or 0) > after_inbox_seq
            ),
            key=lambda row: row.inbox_seq or 0,
        )
        return tuple(
            SealedNotice(row, self.inbox.acked_by.get(row.notification_id)) for row in rows[:limit]
        )

    async def awaiting_transport(
        self, subscription_id: UUID, *, channel: str, limit: int
    ) -> tuple[CoordinatorNotification, ...]:
        delivered = {
            nid
            for (nid, stage, _key), row in self.rows.items()
            if stage == "transport" and row.channel == channel and row.result == "delivered"
        }
        pending = await self.inbox.notifications(subscription_id, after_inbox_seq=0, limit=10_000)
        return tuple(row for row in pending if row.notification_id not in delivered)[:limit]


@dataclass(frozen=True)
class Frontier:
    version: int
    execution_generation: int
    lane: LaneView | None


@dataclass
class FakeGateway:
    """FIXTURE command path: records admitted requests; replays by request id."""

    version: int = 3
    generation: int = 1
    lane_profile: str | None = None
    stale_once: bool = False
    admitted: dict[UUID, MissionCommandRequest] = field(default_factory=dict)
    calls: list[tuple[str, MissionCommandRequest, ActorContext]] = field(default_factory=list)

    async def inspect(self, run_id: str, actor: ActorContext) -> Frontier:
        lane = LaneView(lane_profile=self.lane_profile) if self.lane_profile else None
        return Frontier(self.version, self.generation, lane)

    async def command(
        self, run_id: str, request: MissionCommandRequest, actor: ActorContext
    ) -> MissionCommandReceipt:
        self.calls.append((run_id, request, actor))
        if self.stale_once:
            self.stale_once = False
            self.version += 1
            raise MissionControlRejected("stale_version", "run version changed")
        replay = request.request_id in self.admitted
        self.admitted.setdefault(request.request_id, request)
        return MissionCommandReceipt(
            request_id=request.request_id,
            replay=replay,
            admission=CommandResult(
                command_id=str(request.request_id),
                idempotency_issuer="fixture",
                run_id=run_id,
                command_fingerprint="sha256:" + "0" * 64,
                status=CommandStatus.ACCEPTED,
                resulting_run_version=self.version,
                phase=RunPhase.ACTIVE,
                reason_code="accepted",
                reason="fixture",
                recorded_at=T0,
            ),
        )


__all__ = [
    "MISSION",
    "RUN",
    "T0",
    "FakeGateway",
    "InMemoryAttentionStore",
    "InMemoryInboxStore",
    "journal_event",
]

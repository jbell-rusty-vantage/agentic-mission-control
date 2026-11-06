"""The durable coordinator inbox: subscribe, poll, acknowledge, callbacks and prompts (MP-15).

"Callback" means delivery to a registered transport endpoint or to the coordinator's own
inbox, never a function call inside a provider session (SPEC-04, ADR-0040):

- **Inbox (always).** Notifications are materialized from committed mission events by the
  pure planner (`coordinator.plan`) under the inbox row lock and kept until acknowledged. An
  offline coordinator polls after its acknowledged cursor and receives each pending
  notification once by id; acknowledging is idempotent and only moves the cursor forward.
- **Connected MCP session (qualified only while connected).** After new notifications seal,
  a connected session gets an `InboxHint`. A hint is a wake-up, not a delivery: it never
  acknowledges, and a disconnected client simply polls later.
- **Webhook.** Each sealed notification is POSTed once per attempt, signed with timestamp and
  stable delivery id (`webhook_signing`), in inbox order. A 2xx records a *transport*
  observation of that notification and nothing else (WI-19): it never acknowledges, so the
  notification stays pending until the coordinator acknowledges it. Failures back off on the
  FT-F5 schedule and the twelfth (or an egress rejection) dead-letters the subscription, each
  attempt recorded as a failed or dead-lettered transport. Retries re-send the stored
  notification; they never reach run control or agent work. Webhook delivery needs the
  migration 0063 observation table; without it nothing is posted.
- **Attention (WI-19, OUTPUT-CONTRACTS §12).** Notice, transport, idle-host wake, model-visible
  payload, acknowledgment and content retrieval are six separate observations
  (`domain/coordinator/attention.py`): the server records notice, transport, ack and
  retrieval; the host attests wake and visible (`observe`) by echoing the delivery nonce that
  only the delivered payload carried (never an inspection read), in server receive order.
  `attention` judges each notice; `retrieve` returns bounded excerpts of the exact accepted
  revisions the notice references, under the content grant, the purpose the inbox declared at
  subscribe time and budgets.
- **Prompting a coordinator** goes only through the admitted mailbox: a `queue_instruction`
  or `add_context` Command against the coordinator's own run, through the same
  `MissionControlService.command` path as HTTP (mailbox composition required), one request
  id per notification so a retry is a replay. Never a nested provider send.
- **Waiting** (SPEC-04 §6 wake channels, ADR-0049): `wait` is a server-side long-poll over
  the same pending page, optionally narrowed to some notification kinds. It returns as soon
  as one matching notification is pending (or an empty page at the deadline) and never
  acknowledges; every wake channel (`missionctl wait`, `GET ...?wait=`, MCP
  `coordinator_inbox_wait`) is a cursor over this one durable inbox.
- **Loops.** Commands admitted from a notification (prompts and `command_from_notification`)
  record their request id with depth = notification depth + 1; events those commands cause
  inherit the depth, and above `max_recursion_depth` neither notifications nor commands are
  admitted. Prompts and triggered commands are also capped per window, and notifications per
  run by the planner's rate cap.
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import time
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from mission_control.application.execution.operations.operation_execution import (
    SecretResolutionPort,
)
from mission_control.application.subscriptions.coordinator import (
    INBOX_TICKET_PREFIX,
    CoordinatorContract,
    CoordinatorNotification,
    CoordinatorProfile,
    NotificationKind,
    causation_tag,
    delivery_id,
    plan,
    prompt_request_id,
    render_prompt,
)
from mission_control.application.subscriptions.coordinator_ports import (
    AcceptedOutputs,
    AckOutcome,
    AttentionStore,
    CausationRecord,
    CoordinatorCommandGateway,
    CoordinatorInbox,
    CoordinatorInboxStore,
    InboxDelivery,
    InboxHint,
    InboxNotifier,
    InboxWebhookDelivery,
    KnowledgeExcerptReader,
    MaterializeResult,
    NewInbox,
    NewObservation,
    PollDelivery,
    PromptRecord,
)
from mission_control.application.subscriptions.notice_content import NoticeContentService
from mission_control.application.subscriptions.ports import (
    NewSubscription,
    SubscriptionNotFound,
    SubscriptionStore,
    WebhookDestinationPolicy,
    WebhookEgressRejected,
    WebhookResponse,
    WebhookTransport,
    WebhookTransportError,
    error_class_of,
)
from mission_control.application.subscriptions.webhook_signing import (
    NON_RETRYABLE_ERRORS,
    signed_headers,
)
from mission_control.contracts.contracts import (
    MissionCommandReceipt,
    MissionCommandRequest,
    MissionControlRejected,
)
from mission_control.domain.coordinator.attention import (
    MAX_TOTAL_CHARS,
    RETRIEVAL_CHANNEL,
    AttentionClaim,
    AttentionRefused,
    DeliveryStage,
    ExcerptBundle,
    HostObservation,
    NoticeContent,
    StageObservation,
    attention_claim,
    bind_host_observation,
    nonce_digest,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.subscriptions.contracts import (
    ADMIN_PERMISSION,
    SUBSCRIBE_PERMISSION,
    DeliveryStatus,
    McpSessionChannel,
    StreamTicketChannel,
    Subscription,
    SubscriptionDelivery,
    SubscriptionFilters,
    SubscriptionState,
    WebhookChannel,
    after_failure,
    secret_ref_name,
)

CONTROL_PERMISSION: Final = "workflow_run.control"
INBOX_EVENT_TYPES: Final = ("*",)  # the inbox reads the whole target journal and classifies
MAX_WAIT_SECONDS: Final = 300
WAIT_INTERVAL_SECONDS: Final = 1.0
_STALE_CODES: Final = frozenset({"stale_version", "stale_generation"})
MAX_FUTURE_SKEW_SECONDS: Final = 60
TransportChannel = Literal["http", "mcp"]
AttentionState = Literal["recorded", "attention_unavailable"]
LOGGER = logging.getLogger(__name__)
_WARNED_ATTENTION_UNAVAILABLE: list[bool] = [False]


def _new_nonce() -> str:
    return secrets.token_hex(16)


def referenced_obligations(notification: CoordinatorNotification) -> frozenset[str]:
    """The promises a notice itself references (an output/transfer attention event's fact)."""

    key = notification.facts.get("obligation_key")
    return frozenset({key}) if isinstance(key, str) and key else frozenset()


Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]


class CoordinatorRejected(Exception):
    """Typed refusal: unauthorized, not_found, invalid, closed, egress_rejected,
    recursion_bound, rate_limited, unavailable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CoordinatorSubscribeRequest(CoordinatorContract):
    target: Literal["mission", "run"]
    target_id: UUID
    profile: CoordinatorProfile = Field(default_factory=CoordinatorProfile)
    delivery: InboxDelivery = Field(default_factory=PollDelivery)
    coordinator_run_ref: str | None = Field(default=None, min_length=1, max_length=256)
    after_seq: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _prompt_target(self) -> CoordinatorSubscribeRequest:
        if self.profile.prompt_mode != "off" and self.coordinator_run_ref is None:
            raise ValueError("prompting a coordinator names its own run (coordinator_run_ref)")
        return self


class InboxPage(CoordinatorContract):
    subscription_id: UUID
    notifications: tuple[CoordinatorNotification, ...]
    acked_inbox_seq: int
    high_inbox_seq: int
    has_more: bool
    state: SubscriptionState
    # WI-19: the delivery nonce of each notice this answer carried (it exists only in this
    # delivered payload; a host echoes it to attest wake and visible), whether observations are
    # recorded here at all, and, for an inbox that opted into bounded content, the excerpts of the
    # promises each notice references.
    delivery_nonces: dict[str, str] = Field(default_factory=dict)
    attention: AttentionState = "recorded"
    content: dict[str, ExcerptBundle] = Field(default_factory=dict)


class ContentRequest(CoordinatorContract):
    """An explicit retrieval of bounded content for one notice.

    The purpose is never part of the request: it is the one the inbox declared at subscribe
    time. The obligations must be ones the notice references."""

    obligations: tuple[str, ...] = Field(min_length=1, max_length=32)
    max_excerpt_chars: int = Field(default=1_000, ge=1, le=8_000)
    max_total_chars: int = Field(default=4_000, ge=1, le=MAX_TOTAL_CHARS)
    max_items: int = Field(default=8, ge=1, le=32)

    def policy(self, purpose: str) -> NoticeContent:
        return NoticeContent(
            mode="bounded_excerpts",
            purpose=purpose,
            obligations=self.obligations,
            max_excerpt_chars=min(self.max_excerpt_chars, self.max_total_chars),
            max_total_chars=self.max_total_chars,
            max_items=self.max_items,
        )


class ObservationReceipt(CoordinatorContract):
    subscription_id: UUID
    notification_id: UUID
    stage: DeliveryStage
    observation_key: str
    replay: bool
    claim: AttentionClaim


class RetrievalResult(CoordinatorContract):
    subscription_id: UUID
    notification_id: UUID
    run_id: UUID | None
    observation_key: str
    content: ExcerptBundle


class AttentionReport(CoordinatorContract):
    """`mc.coordinator_attention.v1`: sealed notices of one inbox and their six stages."""

    schema_version: Literal["mc.coordinator_attention.v1"] = "mc.coordinator_attention.v1"
    subscription_id: UUID
    delivery: str
    claims: tuple[AttentionClaim, ...]
    has_more: bool
    next_after_inbox_seq: int


@dataclass
class PromptReport:
    admitted: list[UUID] = field(default_factory=list)
    replayed: list[UUID] = field(default_factory=list)
    skipped: list[tuple[UUID, str]] = field(default_factory=list)
    failed: list[tuple[UUID, str]] = field(default_factory=list)
    deferred: int = 0


@dataclass
class CallbackReport:
    leased: int = 0
    delivered: list[tuple[str, int]] = field(default_factory=list)
    failed: list[tuple[str, int]] = field(default_factory=list)
    dead_lettered: list[str] = field(default_factory=list)


@dataclass
class InboxPassReport:
    callbacks: CallbackReport
    materialized: dict[UUID, int] = field(default_factory=dict)
    prompts: dict[UUID, PromptReport] = field(default_factory=dict)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_read(actor: ActorContext) -> None:
    if SUBSCRIBE_PERMISSION not in actor.permissions:
        raise CoordinatorRejected("unauthorized", f"actor lacks {SUBSCRIBE_PERMISSION}")


def _is_inbox(subscription: Subscription) -> bool:
    channel = subscription.channel
    return isinstance(channel, StreamTicketChannel) and channel.ticket_id.startswith(
        INBOX_TICKET_PREFIX
    )


def _stage_rows(
    notification: CoordinatorNotification, acknowledged_by: str | None
) -> tuple[StageObservation, ...]:
    """The notice and acknowledgment stages, read from the notification row itself."""

    rows: list[StageObservation] = []
    if notification.sealed_at is not None and notification.inbox_seq is not None:
        rows.append(
            StageObservation(
                stage=DeliveryStage.NOTICE,
                channel="inbox",
                observer="server",
                result="observed",
                received_at=notification.sealed_at,
                actor_ref="system:coordinator-inbox",
            )
        )
    if notification.acknowledged_at is not None:
        rows.append(
            StageObservation(
                stage=DeliveryStage.ACK,
                channel="inbox",
                observer="host",
                result="observed",
                received_at=notification.acknowledged_at,
                actor_ref=acknowledged_by or "unknown",
            )
        )
    return tuple(rows)


class CoordinatorInboxService:
    def __init__(
        self,
        subscriptions: SubscriptionStore,
        inbox: CoordinatorInboxStore,
        *,
        commands: CoordinatorCommandGateway | None = None,
        notifier: InboxNotifier | None = None,
        transport: WebhookTransport | None = None,
        secrets: SecretResolutionPort | None = None,
        destinations: WebhookDestinationPolicy | None = None,
        mailbox_semantics: Callable[[str, str], str] | None = None,
        clock: Clock = _utc_now,
        jitter: Callable[[], float] = random.random,
        sleep: Sleep = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        owner: str = "coordinator-inbox",
        page: int = 200,
        max_pages: int = 10,
        lease_seconds: int = 60,
        callback_batch: int = 50,
        wait_interval: float = WAIT_INTERVAL_SECONDS,
        attention: AttentionStore | None = None,
        outputs: AcceptedOutputs | None = None,
        knowledge: KnowledgeExcerptReader | None = None,
        nonces: Callable[[], str] = _new_nonce,
    ) -> None:
        if subscriptions.request_scope != inbox.request_scope:
            raise ValueError("subscription and inbox stores must share one request scope")
        self._subscriptions = subscriptions
        self._inbox = inbox
        self._commands = commands
        self._notifier = notifier
        self._transport = transport
        self._secrets = secrets
        self._destinations = destinations
        # `MailboxDeliveryService.semantics`: a lane that declares `unsupported` is not prompted.
        self._mailbox_semantics = mailbox_semantics
        self._clock = clock
        self._jitter = jitter
        self._sleep = sleep
        self._monotonic = monotonic
        self._owner = owner
        self._page = page
        self._max_pages = max_pages
        self._lease_seconds = lease_seconds
        self._callback_batch = callback_batch
        self._wait_interval = wait_interval
        if attention is not None and attention.request_scope != inbox.request_scope:
            raise ValueError("the attention store must share the inbox's request scope")
        self._attention = attention
        self._nonces = nonces
        self._content = (
            NoticeContentService(outputs, knowledge=knowledge) if outputs is not None else None
        )

    @property
    def request_scope(self) -> str:
        return self._inbox.request_scope

    # -- subscribe / read -------------------------------------------------------------------

    async def subscribe(
        self, request: CoordinatorSubscribeRequest, actor: ActorContext
    ) -> CoordinatorInbox:
        _require_read(actor)
        if request.profile.prompt_mode != "off" and CONTROL_PERMISSION not in actor.permissions:
            raise CoordinatorRejected(
                "unauthorized", f"prompting a coordinator run needs {CONTROL_PERMISSION}"
            )
        delivery = request.delivery
        if isinstance(delivery, WebhookChannel) and self._destinations is not None:
            try:
                await self._destinations.validate(delivery.url)
            except WebhookEgressRejected as rejected:
                raise CoordinatorRejected("egress_rejected", str(rejected)) from None
        try:
            target = await self._subscriptions.resolve_target(request.target, request.target_id)
        except SubscriptionNotFound:
            raise CoordinatorRejected("not_found", "subscription target not found") from None
        cursor = (
            request.after_seq
            if request.after_seq is not None
            else await self._subscriptions.last_seq(target.mission_id)
        )
        now = self._clock()
        subscription = await self._subscriptions.create(
            NewSubscription(
                target=target,
                filters=SubscriptionFilters(event_types=INBOX_EVENT_TYPES),
                channel=StreamTicketChannel(ticket_id=f"{INBOX_TICKET_PREFIX}{uuid4()}"),
                cursor_seq=cursor,
                actor_ref=actor.actor_id,
                now=now,
            )
        )
        return await self._inbox.create(
            NewInbox(
                subscription_id=subscription.subscription_id,
                coordinator_ref=actor.actor_id,
                coordinator_run_ref=request.coordinator_run_ref,
                profile=request.profile,
                delivery=delivery,
                now=now,
            )
        )

    async def inboxes(
        self, actor: ActorContext, *, target: Literal["mission", "run"], target_id: UUID
    ) -> tuple[CoordinatorInbox, ...]:
        """The actor's own open inboxes over one mission or run, oldest first."""

        _require_read(actor)
        try:
            resolved = await self._subscriptions.resolve_target(target, target_id)
        except SubscriptionNotFound:
            raise CoordinatorRejected("not_found", "subscription target not found") from None
        candidates = await self._subscriptions.list(
            mission_id=resolved.mission_id, run_id=resolved.run_id
        )
        return tuple(
            [
                await self._inbox.get(item.subscription_id)
                for item in candidates
                if item.target == resolved
                and item.actor_ref == actor.actor_id
                and item.state is not SubscriptionState.CLOSED
                and _is_inbox(item)
            ]
        )

    async def ensure(
        self, request: CoordinatorSubscribeRequest, actor: ActorContext
    ) -> tuple[CoordinatorInbox, bool]:
        """The actor's open inbox over the target, subscribing only when it has none.

        Returns ``(inbox, created)``; a repeated launch or wait reuses the first inbox, so its
        acknowledged cursor (and nothing else) decides what is still pending.
        """

        existing = await self.inboxes(actor, target=request.target, target_id=request.target_id)
        if existing:
            return existing[0], False
        return await self.subscribe(request, actor), True

    async def _get(self, subscription_id: UUID) -> CoordinatorInbox:
        try:
            return await self._inbox.get(subscription_id)
        except SubscriptionNotFound:
            raise CoordinatorRejected("not_found", "coordinator inbox not found") from None

    async def _owned(self, subscription_id: UUID, actor: ActorContext) -> CoordinatorInbox:
        _require_read(actor)
        inbox = await self._get(subscription_id)
        if inbox.coordinator_ref != actor.actor_id and ADMIN_PERMISSION not in actor.permissions:
            # The same outward answer as an absent inbox: existence is not disclosed.
            raise CoordinatorRejected("not_found", "coordinator inbox not found")
        return inbox

    async def inbox(self, subscription_id: UUID, actor: ActorContext) -> CoordinatorInbox:
        return await self._owned(subscription_id, actor)

    async def materialize(self, subscription_id: UUID) -> MaterializeResult:
        result = await self._inbox.materialize(
            subscription_id,
            planner=plan,
            now=self._clock(),
            page=self._page,
            max_pages=self._max_pages,
        )
        if result.sealed:
            await self._hint(subscription_id)
        return result

    async def _hint(self, subscription_id: UUID) -> None:
        if self._notifier is None:
            return
        inbox = await self._inbox.get(subscription_id)
        delivery = inbox.delivery
        if not isinstance(delivery, McpSessionChannel):
            return
        if not self._notifier.connected(delivery.session_ref):
            return  # the durable inbox keeps everything; the client polls when it returns
        pending = await self._inbox.notifications(
            subscription_id, after_inbox_seq=inbox.acked_inbox_seq, limit=self._page
        )
        await self._notifier.notify_inbox(
            delivery.session_ref,
            InboxHint(
                subscription_id=subscription_id,
                high_inbox_seq=inbox.next_inbox_seq - 1,
                acked_inbox_seq=inbox.acked_inbox_seq,
                pending=len(pending),
            ),
        )

    async def poll(
        self,
        subscription_id: UUID,
        actor: ActorContext,
        *,
        after_inbox_seq: int | None = None,
        limit: int = 50,
        kinds: Collection[NotificationKind] | None = None,
        refresh: bool = True,
        channel: TransportChannel | None = None,
    ) -> InboxPage:
        """Pending notifications after the acknowledged cursor (the polling fallback).

        ``kinds`` narrows the page; notifications of other kinds stay pending, unread here.
        ``channel`` names the transport answering the caller (``http``, ``mcp``): each returned
        notification gets one transport observation; returning it is never acknowledgment.
        """

        if not 1 <= limit <= 500:
            raise CoordinatorRejected("invalid", "limit is 1..500")
        inbox = await self._owned(subscription_id, actor)
        if inbox.state is SubscriptionState.CLOSED:
            raise CoordinatorRejected("closed", "the coordinator inbox is closed")
        if refresh:
            await self.materialize(subscription_id)
            inbox = await self._inbox.get(subscription_id)
        found = await self._pending(
            subscription_id,
            after=max(after_inbox_seq or 0, inbox.acked_inbox_seq),
            limit=limit + 1,
            kinds=frozenset(kinds) if kinds else None,
        )
        returned = found[:limit]
        content = await self._page_content(inbox, returned, actor)
        installed = await self._attention_installed()
        nonces: dict[str, str] = {}
        if channel is not None and returned and installed:
            assert self._attention is not None
            issued = {item.notification_id: self._nonces() for item in returned}
            recorded = await self._attention.record_transport(
                subscription_id,
                tuple(
                    (
                        item.notification_id,
                        item.notice_digest(),
                        nonce_digest(issued[item.notification_id]),
                    )
                    for item in returned
                ),
                channel=channel,
                actor_ref=actor.actor_id,
                at=self._clock(),
            )
            nonces = {str(nid): issued[nid] for nid in recorded}
        return InboxPage(
            subscription_id=subscription_id,
            notifications=returned,
            acked_inbox_seq=inbox.acked_inbox_seq,
            high_inbox_seq=inbox.next_inbox_seq - 1,
            has_more=len(found) > limit,
            state=inbox.state,
            delivery_nonces=nonces,
            attention="recorded" if installed else "attention_unavailable",
            content=content,
        )

    async def _page_content(
        self,
        inbox: CoordinatorInbox,
        notifications: tuple[CoordinatorNotification, ...],
        actor: ActorContext,
    ) -> dict[str, ExcerptBundle]:
        """Opted-in excerpts for a page, under one aggregate budget across the whole page."""

        policy = inbox.profile.content
        if self._content is None or policy.mode != "bounded_excerpts":
            return {}
        assert policy.purpose is not None
        remaining = policy.max_total_chars
        bundles: dict[str, ExcerptBundle] = {}
        for item in notifications:
            if not policy.covers(item.kind.value) or item.run_id is None:
                continue
            referenced = referenced_obligations(item)
            scoped = policy.model_copy(
                update={
                    "obligations": tuple(key for key in policy.obligations if key in referenced)
                }
            )
            if not scoped.obligations:
                continue
            bundle = await self._content.bundle(
                self.request_scope,
                str(item.run_id),
                scoped,
                purpose=policy.purpose,
                actor=actor,
                budget=max(remaining, 0),
            )
            remaining -= bundle.total_chars
            bundles[str(item.notification_id)] = bundle
        return bundles

    async def _pending(
        self,
        subscription_id: UUID,
        *,
        after: int,
        limit: int,
        kinds: frozenset[NotificationKind] | None,
    ) -> tuple[CoordinatorNotification, ...]:
        if kinds is None:
            return await self._inbox.notifications(
                subscription_id, after_inbox_seq=after, limit=limit
            )
        matched: list[CoordinatorNotification] = []
        while len(matched) < limit:
            page = await self._inbox.notifications(
                subscription_id, after_inbox_seq=after, limit=self._page
            )
            matched.extend(item for item in page if item.kind in kinds)
            if len(page) < self._page:
                break
            after = page[-1].inbox_seq or after
        return tuple(matched[:limit])

    async def wait(
        self,
        subscription_id: UUID,
        actor: ActorContext,
        *,
        timeout_seconds: float,
        after_inbox_seq: int | None = None,
        limit: int = 50,
        kinds: Collection[NotificationKind] | None = None,
        channel: TransportChannel | None = None,
    ) -> InboxPage:
        """Long-poll: the first non-empty pending page, or an empty page at the deadline.

        Each round materializes committed journal events, so a wait observes a terminal event
        without any relay running; it never acknowledges (acknowledgement stays explicit).
        """

        if not 0 <= timeout_seconds <= MAX_WAIT_SECONDS:
            raise CoordinatorRejected("invalid", f"wait is 0..{MAX_WAIT_SECONDS} seconds")
        deadline = self._monotonic() + timeout_seconds
        while True:
            page = await self.poll(
                subscription_id,
                actor,
                after_inbox_seq=after_inbox_seq,
                limit=limit,
                kinds=kinds,
                channel=channel,
            )
            remaining = deadline - self._monotonic()
            if page.notifications or remaining <= 0:
                return page
            await self._sleep(min(self._wait_interval, remaining))

    async def ack(
        self,
        subscription_id: UUID,
        actor: ActorContext,
        *,
        notification_ids: tuple[UUID, ...] = (),
        through_inbox_seq: int | None = None,
    ) -> AckOutcome:
        """Acknowledge by id (and/or through an inbox sequence); idempotent, forward only."""

        if not notification_ids and through_inbox_seq is None:
            raise CoordinatorRejected("invalid", "acknowledge names ids or through_inbox_seq")
        inbox = await self._owned(subscription_id, actor)
        if through_inbox_seq is not None and through_inbox_seq >= inbox.next_inbox_seq:
            raise CoordinatorRejected("invalid", "through_inbox_seq is past the inbox head")
        return await self._inbox.acknowledge(
            subscription_id,
            notification_ids=notification_ids,
            through_inbox_seq=through_inbox_seq,
            actor_ref=actor.actor_id,
            now=self._clock(),
        )

    async def close(self, subscription_id: UUID, actor: ActorContext) -> CoordinatorInbox:
        await self._owned(subscription_id, actor)
        await self._subscriptions.set_state(
            subscription_id, SubscriptionState.CLOSED, now=self._clock(), actor_ref=actor.actor_id
        )
        return await self._inbox.get(subscription_id)

    # -- attention: six separate observations (WI-19) ----------------------------------------

    async def _attention_installed(self) -> bool:
        return self._attention is not None and await self._attention.installed()

    async def _require_attention(self) -> AttentionStore:
        if not await self._attention_installed():
            raise CoordinatorRejected(
                "unavailable", "delivery observations need migration 0063 (attention)"
            )
        assert self._attention is not None
        return self._attention

    async def _sealed(
        self, subscription_id: UUID, notification_id: UUID
    ) -> CoordinatorNotification:
        notification = await self._inbox.notification(subscription_id, notification_id)
        if notification is None or notification.state not in {"pending", "acknowledged"}:
            raise CoordinatorRejected("not_found", "no sealed notification with that id")
        return notification

    async def attention_state(self) -> AttentionState:
        """Whether delivery observations are recorded here (migration 0063 present)."""

        return "recorded" if await self._attention_installed() else "attention_unavailable"

    async def _claim(
        self,
        attention: AttentionStore,
        subscription_id: UUID,
        notification: CoordinatorNotification,
        acknowledged_by: str | None,
    ) -> AttentionClaim:
        found = await attention.observations(subscription_id, (notification.notification_id,))
        return attention_claim(
            str(notification.notification_id),
            (
                *_stage_rows(notification, acknowledged_by),
                *found.get(notification.notification_id, ()),
            ),
        )

    async def observe(
        self,
        subscription_id: UUID,
        notification_id: UUID,
        observation: HostObservation,
        actor: ActorContext,
    ) -> ObservationReceipt:
        """Record what the selected host attests: it was woken while idle, or the payload reached
        its model. The report echoes the delivery nonce only the delivered payload carried, binds
        to that delivered transport and is ordered by the server's receive time (visible after
        the wake). Idempotent by key; the host's own times are kept as attested data."""

        inbox = await self._owned(subscription_id, actor)
        if inbox.state is SubscriptionState.CLOSED:
            raise CoordinatorRejected("closed", "the coordinator inbox is closed")
        attention = await self._require_attention()
        notification = await self._sealed(subscription_id, notification_id)
        received = self._clock()
        if (observation.observed_at - received).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
            raise CoordinatorRejected("future_observation", "the attested time is in the future")
        found = await attention.observations(subscription_id, (notification_id,))
        recorded = found.get(notification_id, ())
        prior = next(
            (
                row
                for row in recorded
                if row.stage.value == observation.stage
                and row.observation_key == observation.observation_key
            ),
            None,
        )
        if prior is not None:
            # A replay must hold the same delivery: its nonce digest equals the one of the
            # transport the stored report is bound to (a key alone reveals nothing).
            bound_digest = next(
                (
                    row.nonce_digest
                    for row in recorded
                    if row.stage is DeliveryStage.TRANSPORT
                    and row.observation_key == prior.transport_key
                ),
                None,
            )
            if (
                prior.channel != observation.channel
                or prior.observed_at != observation.observed_at
                or bound_digest != nonce_digest(observation.delivery_nonce)
            ):
                raise CoordinatorRejected(
                    "observation_conflict",
                    "that observation key already records another observation",
                )
            return await self._receipt(attention, notification, observation, replay=True)
        assert notification.sealed_at is not None
        try:
            bound = bind_host_observation(
                observation,
                received_at=received,
                sealed_at=notification.sealed_at,
                recorded=recorded,
            )
        except AttentionRefused as refused:
            raise CoordinatorRejected(refused.code.lower(), str(refused)) from None
        evidence: dict[str, object] = dict(observation.evidence)
        evidence["host_ref"] = observation.host_ref
        evidence["attested_observed_at"] = observation.observed_at.isoformat()
        if observation.idle_since is not None:
            evidence["attested_idle_since"] = observation.idle_since.isoformat()
        stored = await attention.record(
            NewObservation(
                subscription_id=subscription_id,
                notification_id=notification_id,
                stage=DeliveryStage(observation.stage),
                channel=observation.channel,
                observer="host",
                result="observed",
                observation_key=observation.observation_key,
                notice_digest=notification.notice_digest(),
                observed_at=observation.observed_at,
                received_at=received,
                actor_ref=actor.actor_id,
                evidence=evidence,
                transport_key=bound.observation_key,
            )
        )
        return await self._receipt(attention, notification, observation, replay=not stored.created)

    async def _receipt(
        self,
        attention: AttentionStore,
        notification: CoordinatorNotification,
        observation: HostObservation,
        *,
        replay: bool,
    ) -> ObservationReceipt:
        claim = await self._claim(
            attention,
            notification.subscription_id,
            notification,
            await self._acknowledged_by(notification),
        )
        return ObservationReceipt(
            subscription_id=notification.subscription_id,
            notification_id=notification.notification_id,
            stage=DeliveryStage(observation.stage),
            observation_key=observation.observation_key,
            replay=replay,
            claim=claim,
        )

    async def _acknowledged_by(self, notification: CoordinatorNotification) -> str | None:
        if notification.state != "acknowledged" or self._attention is None:
            return None
        assert notification.inbox_seq is not None
        rows = await self._attention.sealed(
            notification.subscription_id, after_inbox_seq=notification.inbox_seq - 1, limit=1
        )
        return rows[0].acknowledged_by if rows else None

    async def attention(
        self,
        subscription_id: UUID,
        actor: ActorContext,
        *,
        after_inbox_seq: int = 0,
        limit: int = 50,
    ) -> AttentionReport:
        """Each sealed notice of the inbox (pending and acknowledged) with its six stages."""

        if not 1 <= limit <= 200:
            raise CoordinatorRejected("invalid", "limit is 1..200")
        inbox = await self._owned(subscription_id, actor)
        attention = await self._require_attention()
        rows = await attention.sealed(
            subscription_id, after_inbox_seq=after_inbox_seq, limit=limit + 1
        )
        page = rows[:limit]
        found = await attention.observations(
            subscription_id, tuple(row.notification.notification_id for row in page)
        )
        claims = tuple(
            attention_claim(
                str(row.notification.notification_id),
                (
                    *_stage_rows(row.notification, row.acknowledged_by),
                    *found.get(row.notification.notification_id, ()),
                ),
            )
            for row in page
        )
        return AttentionReport(
            subscription_id=subscription_id,
            delivery=inbox.delivery.kind,
            claims=claims,
            has_more=len(rows) > limit,
            next_after_inbox_seq=(
                page[-1].notification.inbox_seq or after_inbox_seq if page else after_inbox_seq
            ),
        )

    async def retrieve(
        self,
        subscription_id: UUID,
        notification_id: UUID,
        request: ContentRequest,
        actor: ActorContext,
    ) -> RetrievalResult:
        """Bounded content of the notice's run, explicitly retrieved (stage 6).

        Exact accepted revisions of the named promises only; the result-body grant, the
        coordinator purpose and the budgets bound it, and every gap is a typed omission."""

        inbox = await self._owned(subscription_id, actor)
        if inbox.state is SubscriptionState.CLOSED:
            raise CoordinatorRejected("closed", "the coordinator inbox is closed")
        if self._content is None:
            raise CoordinatorRejected("unavailable", "no output content source is composed")
        attention = await self._require_attention()
        notification = await self._sealed(subscription_id, notification_id)
        if notification.run_id is None:
            raise CoordinatorRejected("invalid", "the notification names no run")
        purpose = inbox.profile.content.purpose
        if purpose is None:
            raise CoordinatorRejected(
                "purpose_undeclared", "the inbox declared no content purpose when subscribing"
            )
        unreferenced = sorted(set(request.obligations) - referenced_obligations(notification))
        if unreferenced:
            raise CoordinatorRejected(
                "not_referenced",
                f"the notification does not reference {', '.join(unreferenced)}",
            )
        bundle = await self._content.bundle(
            self.request_scope,
            str(notification.run_id),
            request.policy(purpose),
            purpose=purpose,
            actor=actor,
        )
        now = self._clock()
        key = f"retrieve:{uuid4().hex[:24]}"
        await attention.record(
            NewObservation(
                subscription_id=subscription_id,
                notification_id=notification_id,
                stage=DeliveryStage.RETRIEVAL,
                channel=RETRIEVAL_CHANNEL,
                observer="server",
                result="delivered" if bundle.excerpts else "refused",
                observation_key=key,
                notice_digest=notification.notice_digest(),
                observed_at=now,
                received_at=now,
                actor_ref=actor.actor_id,
                evidence={
                    "purpose": purpose,
                    "excerpts": len(bundle.excerpts),
                    "omissions": len(bundle.omissions),
                    "total_chars": bundle.total_chars,
                    "revisions": ",".join(item.revision_id for item in bundle.excerpts)[:512],
                },
            )
        )
        return RetrievalResult(
            subscription_id=subscription_id,
            notification_id=notification_id,
            run_id=notification.run_id,
            observation_key=key,
            content=bundle,
        )

    # -- commands caused by notifications ---------------------------------------------------

    async def command_from_notification(
        self,
        subscription_id: UUID,
        notification_id: UUID,
        run_id: str,
        request: MissionCommandRequest,
        actor: ActorContext,
    ) -> MissionCommandReceipt:
        """Admit a command the coordinator issues because of a notification, bounded.

        Depth = notification depth + 1, refused above `max_recursion_depth`; at most
        `rate_limit_per_run` triggered commands per target run and rate window. The request
        id is recorded before admission so the events it causes inherit the depth.
        """

        if self._commands is None:
            raise CoordinatorRejected("unavailable", "no command path is composed")
        inbox = await self._owned(subscription_id, actor)
        notification = await self._inbox.notification(subscription_id, notification_id)
        if notification is None or notification.state in {"open", "suppressed"}:
            raise CoordinatorRejected("not_found", "no delivered notification with that id")
        depth = notification.depth + 1
        profile = inbox.profile
        if depth > profile.max_recursion_depth:
            raise CoordinatorRejected(
                "recursion_bound",
                f"notification depth {notification.depth} is at the recursion bound "
                f"{profile.max_recursion_depth}",
            )
        now = self._clock()
        recent = await self._inbox.causations_since(
            subscription_id,
            origin="triggered",
            since=now - profile.rate_window,
            target_run_ref=run_id,
            exclude_request_id=request.request_id,
        )
        if recent >= profile.rate_limit_per_run:
            raise CoordinatorRejected(
                "rate_limited",
                f"{recent} notification-triggered commands on this run within "
                f"{profile.rate_window_seconds}s",
            )
        await self._inbox.record_causation(
            CausationRecord(
                command_request_id=request.request_id,
                subscription_id=subscription_id,
                notification_id=notification_id,
                origin="triggered",
                target_run_ref=run_id,
                depth=depth,
                recorded_at=now,
            )
        )
        return await self._commands.command(run_id, request, actor)

    # -- prompts through the coordinator's own mailbox ----------------------------------------

    async def dispatch_prompts(self, subscription_id: UUID, *, limit: int = 20) -> PromptReport:
        report = PromptReport()
        inbox = await self._get(subscription_id)
        profile = inbox.profile
        run_ref = inbox.coordinator_run_ref
        if profile.prompt_mode == "off" or run_ref is None or self._commands is None:
            return report
        if inbox.state is SubscriptionState.CLOSED:
            return report
        await self.materialize(subscription_id)
        actor = ActorContext(
            actor_id=inbox.coordinator_ref,
            permissions=frozenset({SUBSCRIBE_PERMISSION, CONTROL_PERMISSION}),
        )
        candidates = await self._inbox.prompt_candidates(subscription_id, limit=limit)
        for notification, record in candidates:
            nid = notification.notification_id
            depth = notification.depth + 1
            now = self._clock()
            if depth > profile.max_recursion_depth:
                await self._inbox.finish_prompt(
                    subscription_id, nid, state="skipped", detail="recursion_bound", now=now
                )
                report.skipped.append((nid, "recursion_bound"))
                continue
            request_id = prompt_request_id(subscription_id, nid)
            if record is None or record.state == "failed":
                prompted = await self._inbox.causations_since(
                    subscription_id,
                    origin="prompt",
                    since=now - profile.rate_window,
                    exclude_request_id=request_id,
                )
                if prompted >= profile.prompt_limit_per_window:
                    report.deferred += 1
                    break
            outcome = await self._prompt(
                inbox,
                notification,
                record,
                actor=actor,
                request_id=request_id,
                depth=depth,
                report=report,
            )
            if outcome == "stop":
                break
        return report

    async def _prompt(
        self,
        inbox: CoordinatorInbox,
        notification: CoordinatorNotification,
        record: PromptRecord | None,
        *,
        actor: ActorContext,
        request_id: UUID,
        depth: int,
        report: PromptReport,
    ) -> Literal["ok", "stop"]:
        assert self._commands is not None and inbox.coordinator_run_ref is not None
        subscription_id = inbox.subscription_id
        nid = notification.notification_id
        run_ref = inbox.coordinator_run_ref
        kind = inbox.profile.prompt_mode
        for _attempt in range(3):
            if record is not None and record.state == "requested" and record.request:
                # A pass died after recording the request: send the identical request again,
                # so run control answers with a replay instead of a second command.
                request = MissionCommandRequest.model_validate(record.request)
            else:
                inspection = await self._commands.inspect(run_ref, actor)
                lane = inspection.lane.lane_profile if inspection.lane is not None else None
                if (
                    lane is not None
                    and self._mailbox_semantics is not None
                    and self._mailbox_semantics(lane, kind) == "unsupported"
                ):
                    await self._inbox.finish_prompt(
                        subscription_id,
                        nid,
                        state="skipped",
                        detail="unsupported_semantics",
                        now=self._clock(),
                    )
                    report.skipped.append((nid, "unsupported_semantics"))
                    return "ok"
                request = MissionCommandRequest.model_validate(
                    {
                        "request_id": str(request_id),
                        "expected_version": inspection.version,
                        "expected_generation": inspection.execution_generation,
                        "target": {"kind": "run", "id": run_ref},
                        "kind": kind,
                        "payload": {
                            "boundary": "next_turn",
                            "content": {"text": render_prompt(notification)},
                        },
                        "reason": f"{causation_tag(nid)} depth={depth}",
                    }
                )
                record = await self._inbox.begin_prompt(
                    subscription_id,
                    nid,
                    request_id=request_id,
                    request=request.model_dump(mode="json"),
                    now=self._clock(),
                )
            await self._inbox.record_causation(
                CausationRecord(
                    command_request_id=request_id,
                    subscription_id=subscription_id,
                    notification_id=nid,
                    origin="prompt",
                    target_run_ref=run_ref,
                    depth=depth,
                    recorded_at=self._clock(),
                )
            )
            try:
                receipt = await self._commands.command(run_ref, request, actor)
            except MissionControlRejected as rejected:
                await self._inbox.finish_prompt(
                    subscription_id, nid, state="failed", detail=rejected.code, now=self._clock()
                )
                if rejected.code in _STALE_CODES:
                    # Nothing was admitted: rebuild the same request id at the new frontier.
                    record = None
                    continue
                report.failed.append((nid, rejected.code))
                return "stop" if rejected.code == "unsupported_control" else "ok"
            await self._inbox.finish_prompt(
                subscription_id,
                nid,
                state="admitted",
                detail=receipt.admission.status.value,
                now=self._clock(),
            )
            (report.replayed if receipt.replay else report.admitted).append(nid)
            return "ok"
        report.failed.append((nid, "stale_version"))
        return "ok"

    # -- the background pass ------------------------------------------------------------------

    async def run_once(self) -> InboxPassReport:
        """One pass (the proposed bootstrap loop): webhook callbacks, MCP hints, prompts."""

        report = InboxPassReport(callbacks=await self.deliver_callbacks())
        for subscription_id in await self._inbox.active_inboxes(delivery="mcp_session"):
            report.materialized[subscription_id] = len(
                (await self.materialize(subscription_id)).sealed
            )
        for subscription_id in await self._inbox.active_inboxes(prompting=True):
            report.prompts[subscription_id] = await self.dispatch_prompts(subscription_id)
        return report

    # -- webhook callbacks ----------------------------------------------------------------------

    async def deliver_callbacks(self, *, limit: int = 20) -> CallbackReport:
        report = CallbackReport()
        if self._transport is None or self._secrets is None:
            return report
        if not await self._attention_installed():
            # A 2xx is transport only (WI-19); without the observation table there is nowhere
            # to record it, so nothing is posted rather than acknowledging by delivery.
            if not _WARNED_ATTENTION_UNAVAILABLE[0]:
                _WARNED_ATTENTION_UNAVAILABLE[0] = True
                LOGGER.warning(
                    "coordinator webhook callbacks are paused: migration 0063 "
                    "(coordinator_delivery_observation) is not applied (attention_unavailable)"
                )
            return report
        leased = await self._inbox.lease_callbacks(
            now=self._clock(), owner=self._owner, lease_seconds=self._lease_seconds, limit=limit
        )
        report.leased = len(leased)
        for subscription in leased:
            try:
                await self._deliver_inbox(subscription, report)
            finally:
                await self._subscriptions.release(subscription, owner=self._owner)
        return report

    async def _deliver_inbox(self, subscription: Subscription, report: CallbackReport) -> None:
        subscription_id = subscription.subscription_id
        await self.materialize(subscription_id)
        inbox = await self._inbox.get(subscription_id)
        channel = inbox.delivery
        if not isinstance(channel, WebhookChannel):
            return
        assert self._attention is not None
        pending = await self._attention.awaiting_transport(
            subscription_id, channel="webhook", limit=self._callback_batch
        )
        current = subscription
        name = str(subscription_id)
        for notification in pending:
            assert notification.inbox_seq is not None
            attempt = (
                await self._subscriptions.attempts(subscription_id, notification.anchor_event_id)
                + 1
            )
            nonce = self._nonces()
            response, error_class = await self._post(channel, inbox, notification, attempt, nonce)
            receipt = SubscriptionDelivery(
                subscription_id=subscription_id,
                event_id=notification.anchor_event_id,
                seq=notification.seq_to,
                attempt=attempt,
                status=DeliveryStatus.DELIVERED,
                response_code=response.status_code if response is not None else None,
                latency_ms=response.latency_ms if response is not None else None,
                recorded_at=self._clock(),
            )
            if response is not None and 200 <= response.status_code < 300:
                current = await self._subscriptions.record_success(
                    current, receipt, owner=self._owner
                )
                await self._webhook_transport(
                    notification, attempt, "delivered", response, None, nonce
                )
                report.delivered.append((name, notification.inbox_seq))
                continue
            decision = after_failure(current.failure_count, self._clock(), self._jitter())
            if error_class in NON_RETRYABLE_ERRORS:
                decision = decision.model_copy(update={"dead_letter": True})
            await self._webhook_transport(
                notification,
                attempt,
                "dead_lettered" if decision.dead_letter else "failed",
                response,
                error_class,
                nonce,
            )
            await self._subscriptions.record_failure(
                current,
                receipt.model_copy(
                    update={
                        "status": DeliveryStatus.DEAD_LETTERED
                        if decision.dead_letter
                        else DeliveryStatus.FAILED,
                        "error_class": error_class
                        or (f"http_{response.status_code}" if response is not None else None),
                    }
                ),
                failure_count=decision.failure_count,
                next_attempt_at=decision.next_attempt_at,
                dead_letter=decision.dead_letter,
                owner=self._owner,
            )
            if decision.dead_letter:
                report.dead_lettered.append(name)
            else:
                report.failed.append((name, notification.inbox_seq))
            return

    async def _webhook_transport(
        self,
        notification: CoordinatorNotification,
        attempt: int,
        result: Literal["delivered", "failed", "dead_lettered"],
        response: WebhookResponse | None,
        error_class: str | None,
        nonce: str,
    ) -> None:
        """One transport observation per webhook attempt: a 2xx is transport, never an ack."""

        assert self._attention is not None
        evidence: dict[str, object] = {
            "delivery_id": str(
                delivery_id(notification.subscription_id, notification.notification_id)
            )
        }
        if response is not None:
            evidence["status_code"] = response.status_code
        if error_class is not None:
            evidence["error_class"] = error_class[:128]
        await self._attention.record(
            NewObservation(
                subscription_id=notification.subscription_id,
                notification_id=notification.notification_id,
                stage=DeliveryStage.TRANSPORT,
                channel="webhook",
                observer="server",
                result=result,
                observation_key=f"webhook:{attempt}",
                notice_digest=notification.notice_digest(),
                observed_at=self._clock(),
                received_at=self._clock(),
                actor_ref=self._owner,
                attempt=attempt,
                evidence=evidence,
                nonce_digest=nonce_digest(nonce),
            )
        )

    async def _post(
        self,
        channel: WebhookChannel,
        inbox: CoordinatorInbox,
        notification: CoordinatorNotification,
        attempt: int,
        nonce: str,
    ) -> tuple[WebhookResponse | None, str | None]:
        assert self._transport is not None and self._secrets is not None
        try:
            resolved = await self._secrets.resolve((channel.secret_ref,))
            secret = resolved[secret_ref_name(channel.secret_ref)].encode("utf-8")
        except (LookupError, KeyError):
            return None, "secret_unavailable"
        body = notification.body(
            summary=isinstance(channel, InboxWebhookDelivery) and channel.payload == "summary",
            delivery_nonce=nonce,
        )
        headers = signed_headers(
            secret,
            body,
            delivery=delivery_id(inbox.subscription_id, notification.notification_id),
            attempt=attempt,
            now=self._clock(),
            extra={
                "X-MC-Subscription-Id": str(inbox.subscription_id),
                "X-MC-Notification-Id": str(notification.notification_id),
                "X-MC-Inbox-Seq": str(notification.inbox_seq),
            },
        )
        try:
            return await self._transport.post(channel.url, body, headers), None
        except WebhookTransportError as error:
            return None, error_class_of(error)


__all__ = [
    "CONTROL_PERMISSION",
    "INBOX_EVENT_TYPES",
    "MAX_WAIT_SECONDS",
    "AttentionReport",
    "AttentionState",
    "CallbackReport",
    "ContentRequest",
    "CoordinatorInboxService",
    "CoordinatorRejected",
    "CoordinatorSubscribeRequest",
    "InboxPage",
    "InboxPassReport",
    "ObservationReceipt",
    "PromptReport",
    "RetrievalResult",
    "TransportChannel",
    "referenced_obligations",
]

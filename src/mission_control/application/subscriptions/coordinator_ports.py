"""Ports and records of the durable coordinator inbox (MP-15).

The inbox hangs off one ordinary `mission_subscription` row (ADR-0032) whose channel is a
`stream_ticket` named `coordinator-inbox:<uuid>`: the FT-F5 relay never leases stream-ticket
rows, so the inbox is the only consumer of that subscription and its `cursor_seq` is the
inbox's materialization cursor. The coordinator-specific state (profile, delivery channel,
acknowledged cursor, notifications, causation records) needs new tables: proposed migration
0033 (see the MP-15 handoff; not allocated here).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field

from mission_control.application.subscriptions.coordinator import (
    CoordinatorContract,
    CoordinatorNotification,
    CoordinatorProfile,
    Plan,
    PlanInput,
)
from mission_control.contracts.contracts import (
    LaneView,
    MissionCommandReceipt,
    MissionCommandRequest,
)
from mission_control.domain.coordinator.attention import (
    DeliveryStage,
    ObservationResult,
    Observer,
    StageObservation,
)
from mission_control.domain.outputs.contracts import ExactOutput
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.subscriptions.contracts import (
    McpSessionChannel,
    Subscription,
    SubscriptionState,
    SubscriptionTarget,
    WebhookChannel,
)


class PollDelivery(CoordinatorContract):
    """No push: the coordinator polls and acknowledges (always available as the fallback)."""

    kind: Literal["poll"] = "poll"


class InboxWebhookDelivery(WebhookChannel):
    """Signed webhook callbacks; ``payload: summary`` adds the rendered summary (SPEC-04 W4)."""

    payload: Literal["reference", "summary"] = "reference"


InboxDelivery = Annotated[
    PollDelivery | McpSessionChannel | InboxWebhookDelivery, Field(discriminator="kind")
]


class CoordinatorInbox(CoordinatorContract):
    """`mc.coordinator_inbox.v1`: one coordinator's durable, acknowledged notification feed."""

    schema_version: Literal["mc.coordinator_inbox.v1"] = "mc.coordinator_inbox.v1"
    subscription_id: UUID
    coordinator_ref: str = Field(min_length=1)
    coordinator_run_ref: str | None = None
    target: SubscriptionTarget
    profile: CoordinatorProfile
    delivery: InboxDelivery
    state: SubscriptionState
    cursor_seq: int = Field(ge=0)
    next_inbox_seq: int = Field(ge=1)
    acked_inbox_seq: int = Field(ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    version: int = Field(ge=1)

    def view(self) -> dict[str, Any]:
        """The JSON every transport answers about an inbox (cursors, profile, delivery kind)."""

        return {
            "subscription_id": str(self.subscription_id),
            "target": self.target.model_dump(mode="json"),
            "state": self.state.value,
            "cursor_seq": self.cursor_seq,
            "acked_inbox_seq": self.acked_inbox_seq,
            "high_inbox_seq": self.next_inbox_seq - 1,
            "profile": self.profile.model_dump(mode="json"),
            "delivery": self.delivery.kind,
        }


@dataclass(frozen=True)
class NewInbox:
    subscription_id: UUID
    coordinator_ref: str
    coordinator_run_ref: str | None
    profile: CoordinatorProfile
    delivery: PollDelivery | McpSessionChannel | WebhookChannel
    now: datetime


@dataclass(frozen=True)
class MaterializeResult:
    sealed: tuple[CoordinatorNotification, ...]
    suppressed: int
    cursor_seq: int
    pages: int


@dataclass(frozen=True)
class AckOutcome:
    acknowledged: tuple[UUID, ...]
    already: tuple[UUID, ...]
    unknown: tuple[UUID, ...]
    acked_inbox_seq: int


CausationOrigin = Literal["prompt", "triggered"]


@dataclass(frozen=True)
class CausationRecord:
    """A command this inbox admitted, by request id: events it causes inherit `depth`."""

    command_request_id: UUID
    subscription_id: UUID
    notification_id: UUID
    origin: CausationOrigin
    target_run_ref: str
    depth: int
    recorded_at: datetime


PromptState = Literal["requested", "admitted", "skipped", "failed"]


@dataclass(frozen=True)
class PromptRecord:
    notification_id: UUID
    request_id: UUID
    request: Mapping[str, Any]
    state: PromptState
    detail: str | None = None


Planner = Callable[[PlanInput], Plan]


class CoordinatorInboxStore(Protocol):
    """Scope-bound persistence for coordinator inboxes (proposed 0033 tables)."""

    @property
    def request_scope(self) -> str: ...

    async def create(self, inbox: NewInbox) -> CoordinatorInbox: ...

    async def get(self, subscription_id: UUID) -> CoordinatorInbox: ...

    async def materialize(
        self, subscription_id: UUID, *, planner: Planner, now: datetime, page: int, max_pages: int
    ) -> MaterializeResult:
        """Under the inbox row lock: read journal pages after the cursor, plan, write."""
        ...

    async def notifications(
        self, subscription_id: UUID, *, after_inbox_seq: int, limit: int
    ) -> tuple[CoordinatorNotification, ...]:
        """Pending (unacknowledged) notifications after `after_inbox_seq`, in inbox order."""
        ...

    async def notification(
        self, subscription_id: UUID, notification_id: UUID
    ) -> CoordinatorNotification | None: ...

    async def acknowledge(
        self,
        subscription_id: UUID,
        *,
        notification_ids: tuple[UUID, ...],
        through_inbox_seq: int | None,
        actor_ref: str,
        now: datetime,
    ) -> AckOutcome: ...

    async def record_causation(self, record: CausationRecord) -> CausationRecord:
        """Idempotent by command request id (the first record wins)."""
        ...

    async def causations_since(
        self,
        subscription_id: UUID,
        *,
        origin: CausationOrigin,
        since: datetime,
        target_run_ref: str | None = None,
        exclude_request_id: UUID | None = None,
    ) -> int: ...

    async def begin_prompt(
        self,
        subscription_id: UUID,
        notification_id: UUID,
        *,
        request_id: UUID,
        request: Mapping[str, Any],
        now: datetime,
    ) -> PromptRecord:
        """Record (or, after a `failed` attempt, replace) the prompt request of a notification.

        A record already `requested` with a request body, `admitted` or `skipped` is returned
        unchanged, so one notification never yields two different prompt commands."""
        ...

    async def finish_prompt(
        self,
        subscription_id: UUID,
        notification_id: UUID,
        *,
        state: PromptState,
        detail: str | None,
        now: datetime,
    ) -> None: ...

    async def prompt_candidates(
        self, subscription_id: UUID, *, limit: int
    ) -> tuple[tuple[CoordinatorNotification, PromptRecord | None], ...]:
        """Sealed actionable notifications whose prompt is not admitted or skipped."""
        ...

    async def lease_callbacks(
        self, *, now: datetime, owner: str, lease_seconds: int, limit: int
    ) -> tuple[Subscription, ...]:
        """Lease due webhook-delivered inbox subscriptions (fenced like the FT-F5 relay)."""
        ...

    async def active_inboxes(
        self,
        *,
        delivery: Literal["poll", "mcp_session", "webhook"] | None = None,
        prompting: bool = False,
    ) -> tuple[UUID, ...]:
        """Non-closed inboxes with that delivery kind, or (prompting) a prompt mode on."""
        ...


@dataclass(frozen=True)
class NewObservation:
    """One delivery-stage observation to append (WI-19): transport, wake, visible or retrieval.

    ``observation_key`` is the idempotency key within (notification, stage): a host report
    names its own; server transport keys are ``<channel>:<n>``."""

    subscription_id: UUID
    notification_id: UUID
    stage: DeliveryStage
    channel: str
    observer: Observer
    result: ObservationResult
    observation_key: str
    notice_digest: str
    observed_at: datetime
    received_at: datetime
    actor_ref: str
    attempt: int | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    nonce_digest: str | None = None
    transport_key: str | None = None


@dataclass(frozen=True)
class StoredObservation:
    observation: StageObservation
    notice_digest: str
    created: bool


@dataclass(frozen=True)
class SealedNotice:
    """A sealed (pending or acknowledged) notification and who acknowledged it."""

    notification: CoordinatorNotification
    acknowledged_by: str | None


class AttentionStore(Protocol):
    """Append-only delivery-stage observations of coordinator notices (migration 0063)."""

    @property
    def request_scope(self) -> str: ...

    async def installed(self) -> bool:
        """Whether the database holds the 0063 observation table."""
        ...

    async def record(self, observation: NewObservation) -> StoredObservation:
        """Insert once per (notification, stage, key); a repeat returns the stored row."""
        ...

    async def record_transport(
        self,
        subscription_id: UUID,
        notices: tuple[tuple[UUID, str, str], ...],
        *,
        channel: str,
        actor_ref: str,
        at: datetime,
    ) -> tuple[UUID, ...]:
        """One server transport observation per (notification id, notice digest, nonce
        digest), keyed ``<channel>:<n>`` and capped per notification; returns the notification
        ids recorded (a capped one carries no nonce)."""
        ...

    async def observations(
        self, subscription_id: UUID, notification_ids: tuple[UUID, ...]
    ) -> Mapping[UUID, tuple[StageObservation, ...]]: ...

    async def sealed(
        self, subscription_id: UUID, *, after_inbox_seq: int, limit: int
    ) -> tuple[SealedNotice, ...]:
        """Pending and acknowledged notifications in inbox order (attention reports)."""
        ...

    async def awaiting_transport(
        self, subscription_id: UUID, *, channel: str, limit: int
    ) -> tuple[CoordinatorNotification, ...]:
        """Pending notifications no ``channel`` transport has delivered yet, in inbox order."""
        ...


class AcceptedOutputs(Protocol):
    """The exact accepted revisions of a run's promises (WI-01 accepted heads)."""

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]: ...


class ExcerptRefused(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class KnowledgeExcerptReader(Protocol):
    """Admitted Knowledge Services retrieval of one exact report revision for a coordinator.

    Raises :class:`ExcerptRefused` with the KS refusal (use denied, purpose not admitted,
    revision changed or erased); never answers another revision."""

    async def read_text(
        self, handle: str, digest: str, *, purpose: str, actor: ActorContext
    ) -> str: ...


class RunFrontier(Protocol):
    """What a prompt needs from `mc.inspection.v1`: the optimistic frontier and the lane."""

    @property
    def version(self) -> int: ...

    @property
    def execution_generation(self) -> int: ...

    @property
    def lane(self) -> LaneView | None: ...


class CoordinatorCommandGateway(Protocol):
    """The admitted command path (`MissionControlService` with its mailbox composition)."""

    async def inspect(self, run_id: str, actor: ActorContext) -> RunFrontier: ...

    async def command(
        self, run_id: str, request: MissionCommandRequest, actor: ActorContext
    ) -> MissionCommandReceipt: ...


@dataclass(frozen=True)
class InboxHint:
    """A wake-up for a connected coordinator; never a delivery and never an acknowledgement."""

    subscription_id: UUID
    high_inbox_seq: int
    acked_inbox_seq: int
    pending: int


class InboxNotifier(Protocol):
    def connected(self, session_ref: str) -> bool: ...

    async def notify_inbox(self, session_ref: str, hint: InboxHint) -> bool: ...


__all__ = [
    "AcceptedOutputs",
    "AckOutcome",
    "AttentionStore",
    "CausationOrigin",
    "CausationRecord",
    "CoordinatorCommandGateway",
    "CoordinatorInbox",
    "CoordinatorInboxStore",
    "ExcerptRefused",
    "InboxDelivery",
    "InboxHint",
    "InboxNotifier",
    "InboxWebhookDelivery",
    "KnowledgeExcerptReader",
    "MaterializeResult",
    "NewInbox",
    "NewObservation",
    "Planner",
    "PollDelivery",
    "PromptRecord",
    "PromptState",
    "RunFrontier",
    "SealedNotice",
    "StoredObservation",
]

"""Coordinator attention: six separate delivery observations and bounded notice content
(OUTPUT-CONTRACTS §12, ADR-0061; Sprint OC WI-19 / OVE-182).

A coordinator notification is only *attended* when six distinct facts are recorded, each on its
own and never inferred from another:

1. ``notice``    the notification sealed into the durable inbox (server, at materialization);
2. ``transport`` a transport handed the payload over: an HTTP or MCP answer that carried it, or
   a signed webhook attempt (server). Each delivery carries a fresh **delivery nonce** that exists
   only inside that delivered payload (the server keeps its digest). A 2xx is transport only,
   never acknowledgment;
3. ``wake``      host-attested: the host says it was idle since ``idle_since`` and was woken
   through ``channel``. The server can verify only that the host echoed the nonce of a delivered
   transport (so it held that delivery) and when the report arrived;
4. ``visible``   host-attested: the host says the payload reached its model, echoing the nonce.
   It proves the reporter held the delivered payload, not that a model read or understood it;
5. ``ack``       the coordinator explicitly acknowledged it (the inbox acknowledgment);
6. ``retrieval`` the coordinator retrieved referenced content (server, at the retrieve call).

Order is judged on **server receive times** (host ``observed_at`` / ``idle_since`` are kept as
attested data only): wake after its delivered transport, visible after the wake, ack after the
visible report. :func:`attention_claim` passes a notice only when all six are present, in that
order, the wake came through an idle-wake channel and the ack is explicit; otherwise each gap
is a typed code. The claim is a consistency verdict over server facts and host attestations; it
is not proof of anything the host did not attest.

Opted-in content (:class:`NoticeContent`) is bounded: :func:`plan_excerpts` selects designated
outputs' exact revisions under a per-excerpt and an aggregate character budget and an item cap,
and every exclusion is a visible omission with a typed code. Default notices carry references.

Pure rules: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from typing import Any, Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.authoring.canonical import canonical_json


class DeliveryStage(StrEnum):
    NOTICE = "notice"
    TRANSPORT = "transport"
    WAKE = "wake"
    VISIBLE = "visible"
    ACK = "ack"
    RETRIEVAL = "retrieval"


STAGE_ORDER: Final = tuple(DeliveryStage)
# Stages a row of `coordinator_delivery_observation` holds; notice and ack live on the
# notification itself (sealed_at, acknowledged_at/by).
OBSERVED_STAGES: Final = frozenset(
    {DeliveryStage.TRANSPORT, DeliveryStage.WAKE, DeliveryStage.VISIBLE, DeliveryStage.RETRIEVAL}
)
HOST_STAGES: Final = frozenset({DeliveryStage.WAKE, DeliveryStage.VISIBLE})

TransportChannel = Literal["webhook", "http", "mcp", "mcp_hint"]
WakeChannel = Literal["background_task_exit", "monitor_event", "session_prompt", "connected_poll"]
VisibleChannel = Literal["tool_result", "task_output", "session_prompt"]
TRANSPORT_CHANNELS: Final = frozenset({"webhook", "http", "mcp", "mcp_hint"})
WAKE_CHANNELS: Final = frozenset(
    {"background_task_exit", "monitor_event", "session_prompt", "connected_poll"}
)
# A host that was idle and is woken by the harness itself (a background task's exit, a monitor
# event, a prompt queued into the idle session). `connected_poll` is a host that was already in
# a turn and polled: supported, but not an idle wake.
IDLE_WAKE_CHANNELS: Final = frozenset({"background_task_exit", "monitor_event", "session_prompt"})
VISIBLE_CHANNELS: Final = frozenset({"tool_result", "task_output", "session_prompt"})
RETRIEVAL_CHANNEL: Final = "retrieve"
CHANNELS: Final = TRANSPORT_CHANNELS | WAKE_CHANNELS | VISIBLE_CHANNELS | {RETRIEVAL_CHANNEL}
LEGACY_CALLBACK_ACTOR: Final = "system:coordinator-callback"
NONCE_PATTERN: Final = r"^[0-9a-f]{32}$"

ObservationResult = Literal["delivered", "failed", "dead_lettered", "observed", "refused"]
Observer = Literal["server", "host"]

MAX_EVIDENCE_KEYS: Final = 16
MAX_EVIDENCE_CHARS: Final = 512
MAX_TRANSPORT_OBSERVATIONS: Final = 64
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_EVIDENCE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SECRET_KEYS: Final = frozenset(
    {"credential", "token", "authorization", "secret", "password", "delivery_nonce"}
)

NOTICE_DIGEST_FIELDS: Final = (
    "schema_version",
    "notification_id",
    "subscription_id",
    "inbox_seq",
    "kind",
    "actionable",
    "mission_id",
    "run_id",
    "seq_from",
    "seq_to",
    "event_count",
    "events",
    "counts",
    "truncated",
    "anchor_event_id",
    "causation_refs",
    "depth",
    "facts",
    "sealed_at",
)


class AttentionRefused(ValueError):
    """A host observation or content request that cannot be recorded; ``code`` is typed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def notice_digest(document: Mapping[str, Any]) -> str:
    """The digest of a sealed notice's immutable fields (state and acknowledgment excluded).

    Server-internal: every observation row records which sealed payload it concerns. It is never
    returned by an inspection read, and a host never proves anything with it.
    """

    if document.get("inbox_seq") is None or document.get("sealed_at") is None:
        raise AttentionRefused("NOT_SEALED", "only a sealed notification has a notice digest")
    subset = {name: document.get(name) for name in NOTICE_DIGEST_FIELDS}
    return "sha256:" + hashlib.sha256(canonical_json(subset)).hexdigest()


def nonce_digest(nonce: str) -> str:
    """What the server keeps of a delivery nonce (the nonce itself lives only in the payload)."""

    return "sha256:" + hashlib.sha256(nonce.encode("ascii")).hexdigest()


def bounded_evidence(evidence: Mapping[str, Any]) -> dict[str, str | int | bool | None]:
    """Host evidence: at most 16 snake_case keys of short scalars, never a credential."""

    if len(evidence) > MAX_EVIDENCE_KEYS:
        raise AttentionRefused("EVIDENCE_TOO_LARGE", f"at most {MAX_EVIDENCE_KEYS} evidence keys")
    bounded: dict[str, str | int | bool | None] = {}
    for key, value in evidence.items():
        if not isinstance(key, str) or not _EVIDENCE_KEY.fullmatch(key):
            raise AttentionRefused("EVIDENCE_INVALID", f"evidence key {key!r} is not snake_case")
        if key in _SECRET_KEYS:
            raise AttentionRefused("EVIDENCE_INVALID", f"evidence never carries a {key}")
        if isinstance(value, str):
            if len(value) > MAX_EVIDENCE_CHARS:
                raise AttentionRefused(
                    "EVIDENCE_TOO_LARGE", f"evidence {key} exceeds {MAX_EVIDENCE_CHARS} chars"
                )
        elif not (value is None or isinstance(value, bool | int)):
            raise AttentionRefused("EVIDENCE_INVALID", f"evidence {key} is not a short scalar")
        bounded[key] = value
    return bounded


class HostObservation(BaseModel):
    """`mc.coordinator_host_observation.v2`: what the selected host attests about one notice.

    Both stages echo the ``delivery_nonce`` of the delivered payload the host holds (it is in that
    payload only). ``wake``: idle since ``idle_since``, woken through ``channel``. ``visible``: the
    payload reached the model through ``channel``. ``observed_at`` and ``idle_since`` are
    attested data; ordering uses the server's receive time. ``observation_key`` is idempotent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.coordinator_host_observation.v2"] = (
        "mc.coordinator_host_observation.v2"
    )
    stage: Literal["wake", "visible"]
    channel: str = Field(min_length=1, max_length=64)
    observation_key: str = Field(min_length=1, max_length=128)
    delivery_nonce: str = Field(pattern=NONCE_PATTERN)
    observed_at: AwareDatetime
    idle_since: AwareDatetime | None = None
    host_ref: str = Field(min_length=1, max_length=256)
    evidence: dict[str, str | int | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> HostObservation:
        if not _KEY.fullmatch(self.observation_key):
            raise ValueError("observation_key is 1..128 of [A-Za-z0-9._:@/-]")
        bounded_evidence(self.evidence)
        if self.stage == "wake":
            if self.channel not in WAKE_CHANNELS:
                raise ValueError(f"a wake channel is one of {sorted(WAKE_CHANNELS)}")
            if self.idle_since is None or self.idle_since > self.observed_at:
                raise ValueError("a wake names when the host went idle, before it was woken")
        else:
            if self.channel not in VISIBLE_CHANNELS:
                raise ValueError(f"a visible channel is one of {sorted(VISIBLE_CHANNELS)}")
            if self.idle_since is not None:
                raise ValueError("idle_since belongs to a wake observation")
        return self


@dataclass(frozen=True)
class StageObservation:
    """One recorded observation of a stage (a notice or acknowledgment row included).

    ``received_at`` is the server's time and orders stages; ``observed_at`` is what a host
    attested (``None`` for server facts). ``nonce_digest`` (transport) and ``transport_key``
    (host stages: the delivered transport whose nonce was echoed) bind a report to a delivery;
    neither is ever returned by an inspection read."""

    stage: DeliveryStage
    channel: str
    observer: Observer
    result: ObservationResult
    received_at: datetime
    actor_ref: str
    observation_key: str = ""
    observed_at: datetime | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    nonce_digest: str | None = None
    transport_key: str | None = None


def bind_host_observation(
    observation: HostObservation,
    *,
    received_at: datetime,
    sealed_at: datetime,
    recorded: Sequence[StageObservation],
) -> StageObservation:
    """The delivered transport a host report is bound to, or a typed refusal.

    The echoed nonce must be one this notification's deliveries carried, of a delivered
    attempt; a visible report must follow a wake report (server receive order)."""

    if received_at < sealed_at:
        raise AttentionRefused("BEFORE_NOTICE", "an observation cannot precede the sealed notice")
    digest = nonce_digest(observation.delivery_nonce)
    bound = next(
        (
            row
            for row in recorded
            if row.stage is DeliveryStage.TRANSPORT and row.nonce_digest == digest
        ),
        None,
    )
    if bound is None:
        raise AttentionRefused(
            "DELIVERY_NONCE_UNKNOWN", "no delivery of this notification carried that nonce"
        )
    if bound.result != "delivered":
        raise AttentionRefused("TRANSPORT_UNDELIVERED", "that delivery attempt was not delivered")
    if observation.stage == "visible" and not any(
        row.stage is DeliveryStage.WAKE and row.received_at <= received_at for row in recorded
    ):
        raise AttentionRefused("STAGE_ORDER_VIOLATED", "visible is reported after the wake")
    return bound


class StageView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: DeliveryStage
    observed: bool
    count: int = Field(ge=0)
    first_at: AwareDatetime | None = None
    last_at: AwareDatetime | None = None
    channels: tuple[str, ...] = ()
    observers: tuple[str, ...] = ()
    failures: int = Field(default=0, ge=0)


class AttentionClaim(BaseModel):
    """`mc.coordinator_attention_claim.v2`: the six stages of one notice and its verdict.

    Times are server receive times. Wake and visible are host attestations bound to a delivered
    payload; the verdict is consistency, not proof beyond what the host attested."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.coordinator_attention_claim.v2"] = (
        "mc.coordinator_attention_claim.v2"
    )
    notification_id: str
    stages: tuple[StageView, ...]
    verdict: Literal["qualified", "blocked"]
    codes: tuple[str, ...] = ()


_MISSING_CODES: Final = {
    DeliveryStage.NOTICE: "NOTICE_UNSEALED",
    DeliveryStage.TRANSPORT: "TRANSPORT_UNOBSERVED",
    DeliveryStage.WAKE: "IDLE_WAKE_UNOBSERVED",
    DeliveryStage.VISIBLE: "VISIBLE_UNOBSERVED",
    DeliveryStage.ACK: "ACK_UNOBSERVED",
    DeliveryStage.RETRIEVAL: "RETRIEVAL_UNOBSERVED",
}


def _counts(stage: DeliveryStage, observation: StageObservation, delivered: frozenset[str]) -> bool:
    """Whether an observation evidences its stage (failures, implicit acks, unbound host
    reports do not)."""

    if observation.result not in {"delivered", "observed"}:
        return False
    if stage is DeliveryStage.ACK:
        return observation.actor_ref != LEGACY_CALLBACK_ACTOR
    if stage in HOST_STAGES and observation.transport_key not in delivered:
        return False
    if stage is DeliveryStage.WAKE:
        return observation.channel in IDLE_WAKE_CHANNELS
    return True


def attention_claim(
    notification_id: str, observations: Iterable[StageObservation]
) -> AttentionClaim:
    """Judge one notification from its stage observations; every gap is a typed code."""

    by_stage: dict[DeliveryStage, list[StageObservation]] = {stage: [] for stage in STAGE_ORDER}
    for observation in observations:
        by_stage[observation.stage].append(observation)
    delivered = frozenset(
        row.observation_key
        for row in by_stage[DeliveryStage.TRANSPORT]
        if row.result == "delivered"
    )
    views: list[StageView] = []
    codes: list[str] = []
    first: dict[DeliveryStage, datetime] = {}
    for stage in STAGE_ORDER:
        rows = sorted(by_stage[stage], key=lambda item: item.received_at)
        counted = [row for row in rows if _counts(stage, row, delivered)]
        views.append(
            StageView(
                stage=stage,
                observed=bool(counted),
                count=len(counted),
                first_at=counted[0].received_at if counted else None,
                last_at=counted[-1].received_at if counted else None,
                channels=tuple(sorted({row.channel for row in rows})),
                observers=tuple(sorted({row.observer for row in rows})),
                failures=sum(1 for row in rows if row.result in {"failed", "dead_lettered"}),
            )
        )
        if counted:
            first[stage] = counted[0].received_at
            continue
        if stage is DeliveryStage.WAKE and rows:
            codes.append("IDLE_WAKE_UNAVAILABLE")
        elif stage is DeliveryStage.ACK and rows:
            codes.append("ACK_NOT_EXPLICIT")
        elif stage is DeliveryStage.TRANSPORT and any(
            row.result == "dead_lettered" for row in rows
        ):
            codes.append("TRANSPORT_DEAD_LETTERED")
        else:
            codes.append(_MISSING_CODES[stage])
    ordered = (
        DeliveryStage.TRANSPORT,
        DeliveryStage.WAKE,
        DeliveryStage.VISIBLE,
        DeliveryStage.ACK,
    )
    for earlier, later in pairwise(ordered):
        if earlier in first and later in first and first[later] < first[earlier]:
            # An ack (e.g. `ack --through`) before the notice's own visible report, a visible
            # before the wake, a wake before any delivery: the order is not the one attended.
            codes.append("STAGE_ORDER_VIOLATED")
            break
    return AttentionClaim(
        notification_id=notification_id,
        stages=tuple(views),
        verdict="blocked" if codes else "qualified",
        codes=tuple(codes),
    )


# ---------------------------------------------------------------- bounded content


ExcerptKind = Literal[
    "review_required",
    "blocked",
    "failed",
    "terminal_result",
    "accepted_output",
    "child_lifecycle",
    "review_closed",
    "progress",
    "rate_limited",
]
COORDINATOR_PURPOSES: Final = frozenset({"coordinator_review", "coordinator_triage"})
MAX_EXCERPT_CHARS: Final = 8_000
MAX_TOTAL_CHARS: Final = 32_000
MAX_ITEMS: Final = 32


class NoticeContent(BaseModel):
    """`mc.notice_content.v1`: the coordinator's opt-in to bounded content.

    The default (``references``) delivers ids, status and gaps only; the coordinator retrieves
    anything else explicitly. ``bounded_excerpts`` attaches excerpts of the designated promises'
    exact revisions to notices of ``kinds``, under a receiving ``purpose`` and the budgets.
    ``purpose`` is declared here, at subscribe time, and is the only purpose any excerpt or
    explicit retrieval of this inbox uses (a request cannot assert another one). Excerpts are
    further restricted to the promises a notice itself references (its ``obligation_key``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["references", "bounded_excerpts"] = "references"
    purpose: str | None = Field(default=None, max_length=64)
    obligations: tuple[str, ...] = Field(default=(), max_length=MAX_ITEMS)
    kinds: tuple[ExcerptKind, ...] = ("accepted_output", "terminal_result")
    max_excerpt_chars: int = Field(default=1_000, ge=1, le=MAX_EXCERPT_CHARS)
    max_total_chars: int = Field(default=4_000, ge=1, le=MAX_TOTAL_CHARS)
    max_items: int = Field(default=8, ge=1, le=MAX_ITEMS)

    @model_validator(mode="after")
    def _opt_in(self) -> NoticeContent:
        if self.purpose is not None and self.purpose not in COORDINATOR_PURPOSES:
            raise ValueError(f"a declared purpose is one of {sorted(COORDINATOR_PURPOSES)}")
        if self.mode == "bounded_excerpts":
            if self.purpose is None:
                raise ValueError(
                    f"bounded excerpts name a purpose of {sorted(COORDINATOR_PURPOSES)}"
                )
            if not self.obligations:
                raise ValueError("bounded excerpts designate the promises they excerpt")
        if self.max_excerpt_chars > self.max_total_chars:
            raise ValueError("one excerpt cannot exceed the aggregate budget")
        return self

    def covers(self, kind: str) -> bool:
        return self.mode == "bounded_excerpts" and kind in self.kinds


@dataclass(frozen=True)
class ExcerptCandidate:
    """One exact output revision a coordinator could see, with its readable text (or why not).

    ``text`` is ``None`` when the content is not readable here; ``refusal`` then names why (an
    access check, a missing grant, a non-textual form...)."""

    obligation_key: str
    deliverable_id: str
    revision_id: str
    revision: int
    form: str
    content_digest: str
    status: Literal["accepted", "submitted"]
    issuer: str
    attribution: str
    text: str | None = None
    refusal: str | None = None


class Excerpt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    obligation_key: str
    deliverable_id: str
    revision_id: str
    revision: int
    form: str
    status: Literal["accepted", "submitted"]
    issuer: str
    attribution: str
    content_digest: str
    purpose: str
    excerpt: str
    excerpt_digest: str
    chars: int = Field(ge=0)
    source_chars: int = Field(ge=0)
    truncated: bool


class Omission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    obligation_key: str
    deliverable_id: str | None = None
    revision_id: str | None = None
    code: str


class ExcerptBundle(BaseModel):
    """`mc.notice_excerpts.v1`: what one notice's bounded content holds and leaves out."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.notice_excerpts.v1"] = "mc.notice_excerpts.v1"
    purpose: str
    excerpts: tuple[Excerpt, ...] = ()
    omissions: tuple[Omission, ...] = ()
    total_chars: int = Field(default=0, ge=0)
    max_total_chars: int = Field(ge=1)


def plan_excerpts(
    candidates: Sequence[ExcerptCandidate],
    policy: NoticeContent,
    *,
    purpose: str,
    budget: int | None = None,
) -> ExcerptBundle:
    """Bounded excerpts of the designated promises, in designation order, within the budgets.

    ``budget`` is what remains of an aggregate budget shared with other notices of one page
    (never more than the policy's own ``max_total_chars``)."""

    excerpts: list[Excerpt] = []
    omissions: list[Omission] = []
    start = (
        policy.max_total_chars if budget is None else max(0, min(budget, policy.max_total_chars))
    )
    remaining = start
    order = {key: index for index, key in enumerate(policy.obligations)}
    designated = sorted(
        (item for item in candidates if item.obligation_key in order),
        key=lambda item: (order[item.obligation_key], item.deliverable_id, item.revision),
    )
    found = {item.obligation_key for item in designated}
    omissions.extend(
        Omission(obligation_key=key, code="NO_ACCEPTED_REVISION")
        for key in policy.obligations
        if key not in found
    )
    for item in designated:
        refusal = item.refusal or (None if item.text is not None else "NOT_TEXTUAL")
        if refusal is None and len(excerpts) >= policy.max_items:
            refusal = "ITEM_LIMIT"
        if refusal is None and remaining <= 0:
            refusal = "BUDGET_EXHAUSTED"
        if refusal is not None:
            omissions.append(
                Omission(
                    obligation_key=item.obligation_key,
                    deliverable_id=item.deliverable_id,
                    revision_id=item.revision_id,
                    code=refusal,
                )
            )
            continue
        assert item.text is not None
        size = min(policy.max_excerpt_chars, remaining)
        text = item.text[:size]
        remaining -= len(text)
        excerpts.append(
            Excerpt(
                obligation_key=item.obligation_key,
                deliverable_id=item.deliverable_id,
                revision_id=item.revision_id,
                revision=item.revision,
                form=item.form,
                status=item.status,
                issuer=item.issuer,
                attribution=item.attribution,
                content_digest=item.content_digest,
                purpose=purpose,
                excerpt=text,
                excerpt_digest="sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                chars=len(text),
                source_chars=len(item.text),
                truncated=len(text) < len(item.text),
            )
        )
    return ExcerptBundle(
        purpose=purpose,
        excerpts=tuple(excerpts),
        omissions=tuple(omissions),
        total_chars=start - remaining,
        max_total_chars=policy.max_total_chars,
    )


__all__ = [
    "CHANNELS",
    "COORDINATOR_PURPOSES",
    "HOST_STAGES",
    "IDLE_WAKE_CHANNELS",
    "LEGACY_CALLBACK_ACTOR",
    "MAX_TRANSPORT_OBSERVATIONS",
    "NONCE_PATTERN",
    "OBSERVED_STAGES",
    "RETRIEVAL_CHANNEL",
    "STAGE_ORDER",
    "TRANSPORT_CHANNELS",
    "VISIBLE_CHANNELS",
    "WAKE_CHANNELS",
    "AttentionClaim",
    "AttentionRefused",
    "DeliveryStage",
    "Excerpt",
    "ExcerptBundle",
    "ExcerptCandidate",
    "HostObservation",
    "NoticeContent",
    "ObservationResult",
    "Observer",
    "Omission",
    "StageObservation",
    "StageView",
    "attention_claim",
    "bind_host_observation",
    "bounded_evidence",
    "nonce_digest",
    "notice_digest",
    "plan_excerpts",
]

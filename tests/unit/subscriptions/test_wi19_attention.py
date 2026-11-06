"""WI-19 / OVE-182: coordinator attention as six separate observations, and bounded content.

Deterministic (in-memory stores, FIXTURE clock and nonces); the PostgreSQL behaviour of the 0063
table is `tests/integration/postgres/test_wi19_attention_postgres.py`. None of this is the
selected host: the host stages here are attested by the test, exactly as a host would attest
them, so these tests prove the server's rules (separation, nonce binding, order, refusal,
idempotency, budgets), not a real wake.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mission_control.application.subscriptions.coordinator import (
    CoordinatorProfile,
    NotificationKind,
)
from mission_control.application.subscriptions.coordinator_ports import ExcerptRefused
from mission_control.application.subscriptions.coordinator_service import (
    ContentRequest,
    CoordinatorInboxService,
    CoordinatorRejected,
    CoordinatorSubscribeRequest,
)
from mission_control.domain.coordinator.attention import (
    LEGACY_CALLBACK_ACTOR,
    DeliveryStage,
    ExcerptCandidate,
    HostObservation,
    NoticeContent,
    StageObservation,
    attention_claim,
    notice_digest,
    plan_excerpts,
)
from mission_control.domain.outputs.contracts import ExactOutput, OutputForm
from mission_control.domain.outputs.rules import text_digest, value_digest
from mission_control.domain.policies.contracts import ActorContext
from tests.unit.subscriptions.coordinator_fakes import (
    RUN,
    InMemoryAttentionStore,
    InMemoryInboxStore,
    journal_event,
)
from tests.unit.subscriptions.fakes import InMemoryStore

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
READ = "workflow_run.read"
CONTENT = "workflow.result.read"
COORDINATOR = ActorContext(actor_id="coordinator-1", permissions=frozenset({READ, CONTENT}))
NO_CONTENT = ActorContext(actor_id="coordinator-1", permissions=frozenset({READ}))
DIGEST = "sha256:" + "0" * 64
FORGED = "f" * 32
PURPOSE = {"purpose": "coordinator_review"}


# ---------------------------------------------------------------- fixtures


def output(
    key: str,
    text: str | None = None,
    *,
    value: Any = None,
    ref: str | None = None,
    revision: int = 1,
    digest: str | None = None,
) -> ExactOutput:
    if text is not None:
        candidate: dict[str, Any] = {"kind": "inline", "text": text}
        form = OutputForm.TEXT
        content_digest = digest or text_digest(text)
    elif value is not None:
        candidate = {"kind": "inline", "value": value}
        form = OutputForm.STRUCTURED
        content_digest = digest or value_digest(value)
    else:
        candidate = {"kind": "handle", "ref": ref}
        form = OutputForm.REFERENCE
        content_digest = digest or DIGEST
    candidate.update(
        {"deliverable_id": f"{key}.main", "form": form.value, "digest": content_digest}
    )
    return ExactOutput(
        revision_id=str(uuid4()),
        run_id=str(RUN),
        obligation_key=key,
        obligation_revision=1,
        deliverable_id=f"{key}.main",
        revision=revision,
        form=form,
        content_digest=content_digest,
        candidate=candidate,
        producer_origin_ref="mission-invocation:producer-1",
    )


class Outputs:
    def __init__(self, *items: ExactOutput) -> None:
        self.items = items

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        return self.items


class Knowledge:
    """FIXTURE admitted KS retrieval: answers one exact revision for one purpose only."""

    def __init__(self, text: str, *, purpose: str = "coordinator_review") -> None:
        self.text = text
        self.purpose = purpose
        self.reads: list[tuple[str, str, str]] = []

    async def read_text(
        self, handle: str, digest: str, *, purpose: str, actor: ActorContext
    ) -> str:
        self.reads.append((handle, digest, purpose))
        if purpose != self.purpose:
            raise ExcerptRefused("PURPOSE_NOT_ADMITTED")
        return self.text


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)  # every server fact is received strictly later
        return self.now


def build(
    *,
    outputs: Outputs | None = None,
    knowledge: Knowledge | None = None,
    present: bool = True,
) -> tuple[CoordinatorInboxService, InMemoryInboxStore, InMemoryAttentionStore, Clock]:
    clock = Clock()
    counter = iter(range(1, 10_000))
    subscriptions = InMemoryStore()
    inbox = InMemoryInboxStore(subscriptions)
    attention = InMemoryAttentionStore(inbox, present=present)
    service = CoordinatorInboxService(
        subscriptions,
        inbox,
        clock=clock,
        attention=attention,
        outputs=outputs,
        knowledge=knowledge,
        sleep=_no_sleep,
        nonces=lambda: f"{next(counter):032x}",
    )
    return service, inbox, attention, clock


async def _no_sleep(_: float) -> None:
    return None


async def subscribe(service: CoordinatorInboxService, **profile: Any) -> UUID:
    created = await service.subscribe(
        CoordinatorSubscribeRequest.model_validate(
            {
                "target": "run",
                "target_id": str(RUN),
                "after_seq": 0,
                "profile": {"batch_window_seconds": 0, **profile},
            }
        ),
        COORDINATOR,
    )
    return created.subscription_id


def finish(inbox: InMemoryInboxStore, seq: int = 1) -> None:
    inbox.add(journal_event(seq, "workflow_run.terminalize"), terminal_outcome="completed")


def fulfilled(inbox: InMemoryInboxStore, key: str, seq: int = 1) -> None:
    """The output store's attention event for a fulfilled promise (WI-19)."""

    inbox.add(
        journal_event(seq, "output.fulfilled"),
        obligation_key=key,
        disposition="fulfilled",
        enforcement="required",
    )


def wake(
    nonce: str, *, key: str = "wake-1", channel: str = "background_task_exit", at: datetime = NOW
) -> HostObservation:
    return HostObservation(
        stage="wake",
        channel=channel,
        observation_key=key,
        delivery_nonce=nonce,
        observed_at=at,
        idle_since=at - timedelta(minutes=5),
        host_ref="claude-code:session-1",
        evidence={"task_id": "bg-7"},
    )


def visible(nonce: str, *, key: str = "visible-1", at: datetime = NOW) -> HostObservation:
    return HostObservation(
        stage="visible",
        channel="task_output",
        observation_key=key,
        delivery_nonce=nonce,
        observed_at=at,
        host_ref="claude-code:session-1",
    )


# ---------------------------------------------------------------- pure rules


def _notice() -> dict[str, Any]:
    return {
        "schema_version": "mc.coordinator_notification.v1",
        "notification_id": str(uuid4()),
        "subscription_id": str(uuid4()),
        "inbox_seq": 1,
        "state": "pending",
        "kind": "terminal_result",
        "facts": {"terminal_outcome": "completed"},
        "sealed_at": NOW.isoformat(),
        "acknowledged_at": None,
    }


def test_notice_digest_covers_the_sealed_payload_not_its_state() -> None:
    notice = _notice()
    digest = notice_digest(notice)
    acked = {**notice, "state": "acknowledged", "acknowledged_at": NOW.isoformat()}
    assert notice_digest(acked) == digest
    assert notice_digest({**notice, "facts": {"terminal_outcome": "failed"}}) != digest
    with pytest.raises(ValueError):
        notice_digest({**notice, "inbox_seq": None})


def _stage(
    stage: DeliveryStage,
    channel: str,
    seconds: int,
    *,
    observer: str = "server",
    result: str = "observed",
    actor: str = "coordinator-1",
    key: str = "",
    transport_key: str | None = None,
) -> StageObservation:
    return StageObservation(
        stage=stage,
        channel=channel,
        observer=observer,  # type: ignore[arg-type]
        result=result,  # type: ignore[arg-type]
        received_at=NOW + timedelta(seconds=seconds),
        actor_ref=actor,
        observation_key=key,
        transport_key=transport_key,
    )


SIX = (
    _stage(DeliveryStage.NOTICE, "inbox", 0),
    _stage(DeliveryStage.TRANSPORT, "http", 1, result="delivered", key="http:1"),
    _stage(DeliveryStage.WAKE, "background_task_exit", 2, observer="host", transport_key="http:1"),
    _stage(DeliveryStage.VISIBLE, "task_output", 3, observer="host", transport_key="http:1"),
    _stage(DeliveryStage.ACK, "inbox", 4, observer="host"),
    _stage(DeliveryStage.RETRIEVAL, "retrieve", 5, result="delivered", key="retrieve:1"),
)


def _without(stage: DeliveryStage) -> list[StageObservation]:
    return [item for item in SIX if item.stage is not stage]


def test_the_claim_needs_six_ordered_bound_observations() -> None:
    claim = attention_claim("n", SIX)
    assert claim.verdict == "qualified" and "notice_digest" not in claim.model_dump()
    for stage in DeliveryStage:
        assert attention_claim("n", _without(stage)).verdict == "blocked", stage
    polled = (
        *_without(DeliveryStage.WAKE),
        _stage(DeliveryStage.WAKE, "connected_poll", 2, observer="host", transport_key="http:1"),
    )
    assert attention_claim("n", polled).codes == ("IDLE_WAKE_UNAVAILABLE",)
    implicit = (
        *_without(DeliveryStage.ACK),
        _stage(DeliveryStage.ACK, "inbox", 4, actor=LEGACY_CALLBACK_ACTOR),
    )
    assert attention_claim("n", implicit).codes == ("ACK_NOT_EXPLICIT",)
    dead = (
        *_without(DeliveryStage.TRANSPORT),
        _stage(DeliveryStage.TRANSPORT, "webhook", 1, result="dead_lettered", key="webhook:1"),
    )
    # Host stages bound to an undelivered transport do not count either.
    assert attention_claim("n", dead).codes[0] == "TRANSPORT_DEAD_LETTERED"
    # S2: an ack (`ack --through`) before the notice's own visible report is out of order.
    early_ack = (
        *_without(DeliveryStage.ACK),
        _stage(DeliveryStage.ACK, "inbox", 2, observer="host"),
    )
    assert attention_claim("n", early_ack).codes == ("STAGE_ORDER_VIOLATED",)
    unbound = (
        *_without(DeliveryStage.VISIBLE),
        _stage(DeliveryStage.VISIBLE, "task_output", 3, observer="host", transport_key="http:9"),
    )
    assert attention_claim("n", unbound).codes == ("VISIBLE_UNOBSERVED",)


def test_host_observations_are_closed_and_bounded() -> None:
    nonce = "a" * 32
    with pytest.raises(ValidationError):
        wake(nonce, channel="task_output")
    with pytest.raises(ValidationError):
        HostObservation(  # no idle_since
            stage="wake",
            channel="background_task_exit",
            observation_key="k",
            delivery_nonce=nonce,
            observed_at=NOW,
            host_ref="h",
        )
    with pytest.raises(ValidationError):
        visible(DIGEST)  # a notice digest is not a delivery nonce
    with pytest.raises(ValidationError):
        HostObservation(
            stage="visible",
            channel="tool_result",
            observation_key="k",
            delivery_nonce=nonce,
            observed_at=NOW,
            host_ref="h",
            evidence={"delivery_nonce": nonce},
        )


def _candidate(
    key: str, text: str | None, *, refusal: str | None = None, revision: int = 1
) -> ExcerptCandidate:
    return ExcerptCandidate(
        obligation_key=key,
        deliverable_id=f"{key}.main",
        revision_id=f"rev-{key}-{revision}",
        revision=revision,
        form="text",
        content_digest=DIGEST,
        status="accepted",
        issuer="mission-control",
        attribution="producer",
        text=text,
        refusal=refusal,
    )


def test_excerpts_follow_designation_and_both_budgets() -> None:
    policy = NoticeContent(
        mode="bounded_excerpts",
        purpose="coordinator_review",
        obligations=("summary", "verdict", "missing", "blob"),
        max_excerpt_chars=10,
        max_total_chars=15,
        max_items=8,
    )
    bundle = plan_excerpts(
        [
            _candidate("verdict", "pass: all checks"),
            _candidate("summary", "0123456789abcdef"),
            _candidate("blob", None, refusal="NOT_TEXTUAL"),
            _candidate("undesignated", "never read"),
        ],
        policy,
        purpose="coordinator_review",
    )
    assert [(item.obligation_key, item.excerpt, item.truncated) for item in bundle.excerpts] == [
        ("summary", "0123456789", True),
        ("verdict", "pass:", True),
    ]
    assert bundle.total_chars == 15
    assert {(item.obligation_key, item.code) for item in bundle.omissions} == {
        ("missing", "NO_ACCEPTED_REVISION"),
        ("blob", "NOT_TEXTUAL"),
    }
    exhausted = plan_excerpts([_candidate("summary", "abc")], policy, purpose="x", budget=0)
    assert [i.code for i in exhausted.omissions if i.obligation_key == "summary"] == [
        "BUDGET_EXHAUSTED"
    ]
    capped = plan_excerpts(
        [_candidate("summary", "a"), _candidate("verdict", "b")],
        policy.model_copy(update={"max_items": 1}),
        purpose="x",
    )
    assert [i.code for i in capped.omissions if i.obligation_key == "verdict"] == ["ITEM_LIMIT"]


def test_bounded_content_is_opt_in_with_a_declared_coordinator_purpose() -> None:
    assert CoordinatorProfile().content.mode == "references"
    assert NoticeContent(purpose="coordinator_triage").mode == "references"  # declared only
    with pytest.raises(ValidationError):
        NoticeContent(mode="bounded_excerpts", obligations=("a",))  # no purpose
    with pytest.raises(ValidationError):
        NoticeContent(purpose="exfiltrate")
    with pytest.raises(ValidationError):
        NoticeContent(mode="bounded_excerpts", purpose="coordinator_review")  # nothing designated
    with pytest.raises(ValidationError):
        ContentRequest.model_validate({"obligations": ["a"], "purpose": "training"})


# ---------------------------------------------------------------- the service


async def test_six_stages_are_recorded_separately_in_order_and_only_then_qualify() -> None:
    outputs = Outputs(output("report.summary", "The summary of the exact report."))
    service, inbox, attention, _clock = build(outputs=outputs)
    sid = await subscribe(service, content=PURPOSE)
    fulfilled(inbox, "report.summary")
    page = await service.wait(sid, COORDINATOR, timeout_seconds=0, channel="http")
    (notice,) = page.notifications
    nid = notice.notification_id
    nonce = page.delivery_nonces[str(nid)]
    assert page.attention == "recorded"
    report = await service.attention(sid, COORDINATOR)
    (claim,) = report.claims
    assert claim.codes == (
        "IDLE_WAKE_UNOBSERVED",
        "VISIBLE_UNOBSERVED",
        "ACK_UNOBSERVED",
        "RETRIEVAL_UNOBSERVED",
    )
    # S2: visible before the wake is out of order.
    with pytest.raises(CoordinatorRejected) as refused:
        await service.observe(sid, nid, visible(nonce), COORDINATOR)
    assert refused.value.code == "stage_order_violated"
    receipt = await service.observe(sid, nid, wake(nonce), COORDINATOR)
    assert receipt.replay is False and "IDLE_WAKE_UNOBSERVED" not in receipt.claim.codes
    receipt = await service.observe(sid, nid, visible(nonce), COORDINATOR)
    assert receipt.claim.codes == ("ACK_UNOBSERVED", "RETRIEVAL_UNOBSERVED")
    await service.ack(sid, COORDINATOR, notification_ids=(nid,))
    retrieved = await service.retrieve(
        sid, nid, ContentRequest(obligations=("report.summary",)), COORDINATOR
    )
    (excerpt,) = retrieved.content.excerpts
    assert excerpt.excerpt == "The summary of the exact report."
    assert excerpt.revision_id == outputs.items[0].revision_id
    assert excerpt.purpose == "coordinator_review"  # the inbox's declared purpose
    (final,) = (await service.attention(sid, COORDINATOR)).claims
    assert final.verdict == "qualified" and final.codes == ()
    stored = {key[1]: row for key, row in attention.rows.items()}
    assert stored["wake"].transport_key == "http:1"
    assert stored["wake"].evidence["attested_idle_since"]  # attested data, kept as such


async def test_visible_cannot_be_forged_from_inspection_output() -> None:
    """B1: attention reads and receipts carry no nonce or digest; a script that only reads
    them (after a webhook 2xx or a poll it did not keep) cannot attest visible."""

    service, inbox, attention, _clock = build()
    sid = await subscribe(service)
    finish(inbox)
    page = await service.poll(sid, COORDINATOR, channel="http")
    (notice,) = page.notifications
    nid = notice.notification_id
    real = page.delivery_nonces[str(nid)]
    receipt = await service.observe(sid, nid, wake(real), COORDINATOR)
    report = await service.attention(sid, COORDINATOR)
    exposed = json.dumps(report.model_dump(mode="json")) + json.dumps(
        receipt.model_dump(mode="json")
    )
    assert real not in exposed and notice.notice_digest() not in exposed
    assert "sha256:" not in exposed
    for guess in (FORGED, notice.notice_digest()[7:39]):
        with pytest.raises(CoordinatorRejected) as refused:
            await service.observe(sid, nid, visible(guess, key="forged"), COORDINATOR)
        assert refused.value.code == "delivery_nonce_unknown"
    # A nonce of another notification's delivery does not bind either.
    finish(inbox, seq=2)
    other = await service.poll(sid, COORDINATOR, channel="http")
    other_nonce = next(v for k, v in other.delivery_nonces.items() if k != str(nid))
    with pytest.raises(CoordinatorRejected) as refused:
        await service.observe(sid, nid, visible(other_nonce, key="crossed"), COORDINATOR)
    assert refused.value.code == "delivery_nonce_unknown"
    assert {key[2] for key in attention.rows if key[1] == "visible"} == set()


async def test_host_reports_are_ordered_on_receipt_and_idempotent() -> None:
    service, inbox, _attention, clock = build()
    sid = await subscribe(service)
    finish(inbox)
    page = await service.poll(sid, COORDINATOR, channel="mcp")
    (pending,) = page.notifications
    nonce = page.delivery_nonces[str(pending.notification_id)]
    nid = pending.notification_id
    # S3: the attested time may lie in the past (it is data); a future one is refused.
    old = await service.observe(sid, nid, wake(nonce, at=NOW - timedelta(days=1)), COORDINATOR)
    assert old.replay is False
    with pytest.raises(CoordinatorRejected) as refused:
        await service.observe(
            sid, nid, visible(nonce, at=clock.now + timedelta(hours=1)), COORDINATOR
        )
    assert refused.value.code == "future_observation"
    first = await service.observe(sid, nid, visible(nonce), COORDINATOR)
    again = await service.observe(sid, nid, visible(nonce), COORDINATOR)
    assert (first.replay, again.replay) == (False, True)
    # N2: replaying a stored key needs the same delivery's nonce; a guessed one, or the nonce of
    # another (real) delivery, is a conflict and the answer reveals nothing.
    redelivered = await service.poll(sid, COORDINATOR, channel="mcp")
    other_nonce = redelivered.delivery_nonces[str(nid)]
    for wrong in (FORGED, other_nonce):
        with pytest.raises(CoordinatorRejected) as refused:
            await service.observe(sid, nid, visible(wrong), COORDINATOR)
        assert refused.value.code == "observation_conflict"
    with pytest.raises(CoordinatorRejected) as refused:
        await service.observe(sid, nid, visible(nonce, at=NOW + timedelta(seconds=5)), COORDINATOR)
    assert refused.value.code == "observation_conflict"
    other = ActorContext(actor_id="coordinator-2", permissions=frozenset({READ, CONTENT}))
    with pytest.raises(CoordinatorRejected) as refused:
        await service.observe(sid, nid, visible(nonce, key="x"), other)
    assert refused.value.code == "not_found"


async def test_ack_through_does_not_qualify_a_notice_without_its_own_visible() -> None:
    service, inbox, _attention, _clock = build()
    sid = await subscribe(service)
    finish(inbox, 1)
    finish(inbox, 2)
    page = await service.poll(sid, COORDINATOR, channel="http")
    first, second = page.notifications
    nonce = page.delivery_nonces[str(first.notification_id)]
    await service.observe(sid, first.notification_id, wake(nonce), COORDINATOR)
    await service.observe(sid, first.notification_id, visible(nonce), COORDINATOR)
    await service.ack(sid, COORDINATOR, through_inbox_seq=2)
    claims = {
        item.notification_id: item for item in (await service.attention(sid, COORDINATOR)).claims
    }
    assert "ACK_UNOBSERVED" not in claims[str(first.notification_id)].codes
    assert "VISIBLE_UNOBSERVED" in claims[str(second.notification_id)].codes


async def test_disconnect_replays_duplicate_ack_is_idempotent_and_cancel_closes() -> None:
    service, inbox, attention, _clock = build()
    sid = await subscribe(service)
    finish(inbox)
    first = await service.wait(sid, COORDINATOR, timeout_seconds=0, channel="http")
    second = await service.wait(sid, COORDINATOR, timeout_seconds=0, channel="http")
    assert first.notifications == second.notifications
    nid = first.notifications[0].notification_id
    # Each delivery has its own nonce; both bind (the host may hold either).
    assert first.delivery_nonces[str(nid)] != second.delivery_nonces[str(nid)]
    keys = sorted(key[2] for key in attention.rows if key[0] == nid)
    assert keys == ["http:1", "http:2"]
    once = await service.ack(sid, COORDINATOR, notification_ids=(nid,))
    twice = await service.ack(sid, COORDINATOR, notification_ids=(nid,))
    assert (once.acknowledged, twice.already) == ((nid,), (nid,))
    await service.close(sid, COORDINATOR)
    with pytest.raises(CoordinatorRejected) as refused:
        await service.wait(sid, COORDINATOR, timeout_seconds=0)
    assert refused.value.code == "closed"
    with pytest.raises(CoordinatorRejected) as refused:
        await service.observe(sid, nid, wake(first.delivery_nonces[str(nid)]), COORDINATOR)
    assert refused.value.code == "closed"
    (claim,) = (await service.attention(sid, COORDINATOR)).claims
    assert "ACK_UNOBSERVED" not in claim.codes


async def test_opted_in_pages_carry_bounded_excerpts_of_referenced_promises_only() -> None:
    outputs = Outputs(
        output("report.summary", "S" * 50),
        output("report.verdict", value={"result": "pass", "checks": 3}),
        output("report.body", ref="kh:binding/report/r-1@3"),
        output("report.bad", "tampered", digest="sha256:" + "1" * 64),
    )
    knowledge = Knowledge("Exact KS report body", purpose="coordinator_triage")
    service, inbox, _attention, _clock = build(outputs=outputs, knowledge=knowledge)
    designated = ["report.summary", "report.verdict", "report.body", "report.bad"]
    sid = await subscribe(
        service,
        content={
            "mode": "bounded_excerpts",
            "purpose": "coordinator_review",
            "obligations": designated,
            "kinds": ["accepted_output", "terminal_result"],
            "max_excerpt_chars": 20,
            "max_total_chars": 40,
        },
    )
    for seq, key in enumerate(designated, start=1):
        fulfilled(inbox, key, seq)
    finish(inbox, seq=9)  # a terminal notice references no promise: no excerpt
    page = await service.poll(sid, COORDINATOR, channel="http")
    by_key = {
        str(item.facts.get("obligation_key")): page.content.get(str(item.notification_id))
        for item in page.notifications
    }
    assert by_key["None"] is None
    assert by_key["report.summary"].excerpts[0].chars == 20
    assert by_key["report.verdict"].excerpts[0].chars == 20
    assert by_key["report.body"].omissions[0].code in {"PURPOSE_NOT_ADMITTED", "BUDGET_EXHAUSTED"}
    assert by_key["report.bad"].omissions[0].code == "DIGEST_MISMATCH"
    assert sum(bundle.total_chars for bundle in page.content.values()) == 40
    assert all(read[2] == "coordinator_review" for read in knowledge.reads)
    terminal = next(
        item for item in page.notifications if item.kind is NotificationKind.TERMINAL_RESULT
    )
    # S4: explicit retrieval is limited to promises the notice references.
    with pytest.raises(CoordinatorRejected) as refused:
        await service.retrieve(
            sid,
            terminal.notification_id,
            ContentRequest(obligations=("report.summary",)),
            COORDINATOR,
        )
    assert refused.value.code == "not_referenced"
    page = await service.poll(sid, NO_CONTENT)
    summary = next(
        i for i in page.notifications if i.facts.get("obligation_key") == "report.summary"
    )
    bundle = page.content[str(summary.notification_id)]
    assert bundle.excerpts == () and {item.code for item in bundle.omissions} == {"GRANT_MISSING"}


async def test_retrieval_needs_a_declared_purpose_and_ks_an_admitted_reader() -> None:
    outputs = Outputs(output("report.body", ref="kh:binding/report/r-1@3"))
    service, inbox, _attention, _clock = build(outputs=outputs)
    undeclared = await subscribe(service)
    fulfilled(inbox, "report.body")
    page = await service.poll(undeclared, COORDINATOR, channel="http")
    nid = page.notifications[0].notification_id
    with pytest.raises(CoordinatorRejected) as refused:
        await service.retrieve(
            undeclared, nid, ContentRequest(obligations=("report.body",)), COORDINATOR
        )
    assert refused.value.code == "purpose_undeclared"
    service, inbox, _attention, _clock = build(outputs=outputs)
    sid = await subscribe(service, content=PURPOSE)
    fulfilled(inbox, "report.body")
    page = await service.poll(sid, COORDINATOR, channel="http")
    assert page.content == {}  # references by default
    nid = page.notifications[0].notification_id
    result = await service.retrieve(
        sid, nid, ContentRequest(obligations=("report.body",)), COORDINATOR
    )
    assert [item.code for item in result.content.omissions] == ["KNOWLEDGE_ACCESS_UNAVAILABLE"]
    (claim,) = (await service.attention(sid, COORDINATOR)).claims
    assert next(v for v in claim.stages if v.stage == "retrieval").observed is False


async def test_without_migration_0063_attention_is_unavailable_but_polling_works() -> None:
    service, inbox, attention, _clock = build(present=False)
    sid = await subscribe(service)
    finish(inbox)
    page = await service.poll(sid, COORDINATOR, channel="http")
    assert len(page.notifications) == 1 and attention.rows == {}
    assert page.attention == "attention_unavailable" and page.delivery_nonces == {}
    assert await service.attention_state() == "attention_unavailable"
    with pytest.raises(CoordinatorRejected) as refused:
        await service.attention(sid, COORDINATOR)
    assert refused.value.code == "unavailable"

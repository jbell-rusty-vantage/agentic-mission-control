"""HL-17: Managed Agents and Agents API webhooks enter Signal Ingress as wake signals.

Signed fixture deliveries (tests/fixtures/provider_webhooks.py) are verified with Standard
Webhooks, reduced to a `ProviderWake` and recorded once per `webhook-id`; forged, stale and
replayed deliveries record nothing. The same deliveries pass the OpenAI SDK's own Standard
Webhooks verifier, so the fixtures are signed the way providers sign. The PostgreSQL proof is
in tests/integration/postgres/test_signal_ingress_postgres.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from mission_control.adapters.remote_session.wake import SessionWake
from mission_control.application.signals.contracts import IngressRejected, ProviderWake
from mission_control.application.signals.ports import InboxItem
from mission_control.application.signals.service import IngressKeys, SignalIngressService
from mission_control.application.signals.wake import provider_wake
from mission_control.interfaces.http.ingress import create_ingress_app
from tests.fixtures.provider_webhooks import (
    ANTHROPIC_SESSION_IDLED,
    ANTHROPIC_TEST_SECRET,
    OPENAI_ACTION_REQUIRED,
    OPENAI_SESSION_CREATED,
    OPENAI_TEST_SECRET,
    delivery_body,
    standard_headers,
)
from tests.unit.remote_session.support import PROFILE, ScriptedRemoteLane, staged_lane
from tests.unit.signals.test_ingress_service import FakeStore

SECRETS = {"anthropic": ANTHROPIC_TEST_SECRET, "openai": OPENAI_TEST_SECRET}


@dataclass
class DedupingStore(FakeStore):
    """Records webhook items once per (provider, delivery id), as `ingress_webhook` does."""

    items: list[InboxItem] = field(default_factory=list)
    webhook_calls: int = 0

    async def webhook(self, provider: str, route_ref: str | None, item: InboxItem) -> str:
        self.webhook_calls += 1
        key = (item.kind, item.dedupe_key)
        if key in {(seen.kind, seen.dedupe_key) for seen in self.items}:
            return "duplicate"
        self.items.append(item)
        return "accepted"


def ingress(store: DedupingStore, clock: float | None = None) -> SignalIngressService:
    return SignalIngressService(
        store,
        keys=IngressKeys(webhook_secrets=SECRETS),
        clock=(lambda: clock) if clock is not None else time.time,
    )


async def refusal(call: Any) -> str:
    with pytest.raises(IngressRejected) as refused:
        await call
    return refused.value.code


# --- the envelope rules ------------------------------------------------------------------------


def test_each_provider_names_its_event_and_resource_where_it_documents_them() -> None:
    assert provider_wake("anthropic", ANTHROPIC_SESSION_IDLED) == ProviderWake(
        event_type="session.status_idled",
        resource_ref="sesn_011CTnB7fixture",
        event_id="wevt_011CTnB7d1xE2fixture",
    )
    assert provider_wake("openai", OPENAI_ACTION_REQUIRED) == ProviderWake(
        event_type="agent.session.action_required",
        resource_ref="sess_fixture123",
        event_id="evt_fixture_action",
    )


@pytest.mark.parametrize(
    ("provider", "envelope"),
    [
        # The inner Managed Agents shape at the top level: `type` there is always `event`.
        ("anthropic", {"type": "session.status_idled", "id": "sesn_1"}),
        ("anthropic", {"type": "event", "id": "wevt_1", "data": {"type": "session.x"}}),
        ("anthropic", {"type": "event", "data": {"type": "session.x", "id": 7}}),
        ("openai", {"id": "evt_1", "type": "agent.session.idle", "data": "sess_1"}),
        ("openai", {"id": "evt_1", "data": {"id": "sess_1"}}),
        ("openai", {"type": "Agent Session!", "data": {"id": "sess_1"}}),
    ],
)
def test_an_envelope_that_names_no_event_or_resource_is_refused(
    provider: str, envelope: dict[str, Any]
) -> None:
    with pytest.raises(IngressRejected) as refused:
        provider_wake(provider, envelope)
    assert (refused.value.status_code, refused.value.code) == (422, "invalid_body")
    with pytest.raises(ValueError, match="not reduced"):
        provider_wake("github", envelope)


# --- signed fixture deliveries are accepted, as wakes only ---------------------------------------


@pytest.mark.parametrize(
    ("provider", "envelope"),
    [
        ("anthropic", ANTHROPIC_SESSION_IDLED),
        ("openai", OPENAI_ACTION_REQUIRED),
        ("openai", OPENAI_SESSION_CREATED),
    ],
)
async def test_a_signed_fixture_delivery_is_recorded_as_its_wake_and_nothing_else(
    provider: str, envelope: dict[str, Any]
) -> None:
    body = delivery_body(envelope)
    headers = standard_headers(SECRETS[provider], body, "msg_fixture_1")
    # The provider's own Standard Webhooks verifier accepts the fixture as signed.
    OpenAI(api_key="unused").webhooks.verify_signature(body, headers, secret=SECRETS[provider])
    store = DedupingStore()

    assert await ingress(store).webhook(provider, body, headers) == "accepted"

    (item,) = store.items
    assert (item.kind, item.dedupe_key) == (f"webhook.{provider}", "msg_fixture_1")
    assert item.payload == provider_wake(provider, envelope).model_dump(exclude_none=True)
    assert item.payload["schema_version"] == "mc.provider_wake.v1"
    stored = repr(item.payload)
    for untrusted in ("organization_id", "required_action", "connect", "untrusted.invalid"):
        assert untrusted not in stored
    assert item.body_sha256.startswith("sha256:")


async def test_the_router_answers_204_for_a_wake_and_a_typed_401_for_a_forgery() -> None:
    store = DedupingStore()
    client = TestClient(create_ingress_app([ingress(store)]))
    body = delivery_body(OPENAI_ACTION_REQUIRED)
    route = "/v1/ingress/biotech/provider/openai"
    headers = standard_headers(OPENAI_TEST_SECRET, body, "msg_router")
    for _attempt in range(2):
        reply = client.post(route, content=body, headers=headers)
        assert (reply.status_code, reply.content) == (204, b"")
    forged = standard_headers(ANTHROPIC_TEST_SECRET, body, "msg_forged")
    reply = client.post(route, content=body, headers=forged)
    assert (reply.status_code, reply.json()) == (401, {"detail": {"code": "invalid_signature"}})
    assert [item.dedupe_key for item in store.items] == ["msg_router"]


# --- forged and replayed deliveries record nothing ----------------------------------------------


async def test_forged_deliveries_are_refused_before_the_store() -> None:
    store = DedupingStore()
    service = ingress(store)
    body = delivery_body(ANTHROPIC_SESSION_IDLED)
    good = standard_headers(ANTHROPIC_TEST_SECRET, body, "msg_1")
    tampered = body.replace(b"sesn_011CTnB7fixture", b"sesn_011CTnB7attacker")
    forgeries: list[tuple[bytes, dict[str, str]]] = [
        (body, standard_headers(OPENAI_TEST_SECRET, body, "msg_1")),  # another secret
        (tampered, good),  # the body changed after signing
        (body, good | {"webhook-id": "msg_2"}),  # a new id to slip past dedupe
        (body, good | {"webhook-timestamp": str(int(good["webhook-timestamp"]) + 1)}),
        (body, good | {"webhook-signature": good["webhook-signature"].replace("v1,", "v1a,")}),
        (body, good | {"webhook-signature": "v1,AAAA"}),
        (body, {key: value for key, value in good.items() if key != "webhook-signature"}),
        (body, {key: value for key, value in good.items() if key != "webhook-id"}),
    ]
    for forged_body, headers in forgeries:
        assert await refusal(service.webhook("anthropic", forged_body, headers)) == (
            "invalid_signature"
        )
    # A delivery signed for one provider is refused on the other's route.
    assert await refusal(service.webhook("openai", body, good)) == "invalid_signature"
    assert store.webhook_calls == 0


async def test_replayed_deliveries_are_refused_or_recorded_once() -> None:
    store = DedupingStore()
    now = time.time()
    service = ingress(store, clock=now)
    body = delivery_body(OPENAI_ACTION_REQUIRED)
    headers = standard_headers(OPENAI_TEST_SECRET, body, "msg_1", timestamp=int(now))

    assert await service.webhook("openai", body, headers) == "accepted"
    # The same signed delivery again (a provider retry or a replay inside the tolerance).
    assert await service.webhook("openai", body, headers) == "duplicate"
    # A provider retry is re-signed with a new timestamp but keeps its `webhook-id`.
    later = standard_headers(OPENAI_TEST_SECRET, body, "msg_1", timestamp=int(now) + 60)
    assert await ingress(store, clock=now + 60).webhook("openai", body, later) == "duplicate"
    # A captured delivery replayed after the 5-minute tolerance, or stamped in the future.
    assert await refusal(ingress(store, clock=now + 301).webhook("openai", body, headers)) == (
        "stale_timestamp"
    )
    early = standard_headers(OPENAI_TEST_SECRET, body, "msg_3", timestamp=int(now) + 301)
    assert await refusal(service.webhook("openai", body, early)) == "stale_timestamp"

    assert [item.dedupe_key for item in store.items] == ["msg_1"]
    assert store.webhook_calls == 3


async def test_a_verified_delivery_naming_no_resource_records_nothing() -> None:
    store = DedupingStore()
    body = delivery_body({"id": "evt_1", "object": "event", "type": "agent.session.idle"})
    headers = standard_headers(OPENAI_TEST_SECRET, body, "msg_1")
    assert await refusal(ingress(store).webhook("openai", body, headers)) == "invalid_body"
    unconfigured = SignalIngressService(DedupingStore(), keys=IngressKeys())
    assert await refusal(unconfigured.webhook("openai", body, headers)) == "webhook_unconfigured"
    assert store.webhook_calls == 0


# --- the worker re-reads what the wake names ---------------------------------------------------


async def test_a_stored_wake_names_the_staged_execution_the_lane_re_reads() -> None:
    store = DedupingStore()
    body = delivery_body(ANTHROPIC_SESSION_IDLED)
    await ingress(store).webhook(
        "anthropic", body, standard_headers(ANTHROPIC_TEST_SECRET, body, "msg_1")
    )
    (item,) = store.items
    wake = ProviderWake.model_validate(item.payload)
    lane = ScriptedRemoteLane()
    staged_lane(lane)
    lane._sessions["heid-1"].session_ref = wake.resource_ref
    session_wake = SessionWake(PROFILE, item.dedupe_key, wake.event_type, wake.resource_ref)
    assert lane.wake_target(session_wake) == "heid-1"

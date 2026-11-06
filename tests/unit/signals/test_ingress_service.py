"""The Signal Ingress service and router over an in-memory store: tier selection, caps,
redaction, nonce handling, rejection mapping and the loopback mount. The SQL decisions
themselves are proved on PostgreSQL in tests/integration/postgres/test_signal_ingress_postgres.py.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from mission_control.application.capabilities.bundle_custody import SignedUpload
from mission_control.application.execution.harness.hook_callbacks import (
    HookCallbackService,
    InMemoryHookIntentLedger,
    InMemoryHookTokenStore,
)
from mission_control.application.secrets.minting import token_digest
from mission_control.application.signals.contracts import IngressRejected, TrustTier
from mission_control.application.signals.ports import (
    AcceptOutcome,
    ArtifactSlotOutcome,
    GateCall,
    GateOutcome,
    InboxItem,
    OidcIdentity,
    Principal,
    RequestOutcome,
    RequestStatusOutcome,
)
from mission_control.application.signals.service import (
    IngressKeys,
    IngressLimits,
    SignalIngressService,
)
from mission_control.application.signals.verification import (
    ENVIRONMENT_KEY_PURPOSE,
    derive_secret,
)
from mission_control.interfaces.http.hook_callback import create_hook_callback_app
from mission_control.interfaces.http.ingress import create_ingress_app

TOKEN = "mct_" + "t" * 43
MASTER = b"env-master"


@dataclass
class FakeStore:
    application_id: str = "biotech"
    outcome: str = "accepted"
    calls: list[tuple[str, Principal, Any]] = field(default_factory=list)

    async def accept(self, principal: Principal, items: Sequence[InboxItem]) -> AcceptOutcome:
        self.calls.append(("accept", principal, list(items)))
        return AcceptOutcome(self.outcome, len(items) if self.outcome == "accepted" else 0, 0)

    async def gate(self, principal: Principal, call: GateCall) -> GateOutcome:
        self.calls.append(("gate", principal, call))
        if self.outcome != "accepted":
            return GateOutcome(self.outcome)
        return GateOutcome("decided", "deny", "disallowed_tool")

    async def webhook(self, provider: str, route_ref: str | None, item: InboxItem) -> str:
        self.calls.append(("webhook", Principal(TrustTier.PROVIDER_SIGNED, provider), item))
        return self.outcome

    async def prepare_artifact(
        self, principal: Principal, artifact_upload_id: UUID, **declared: Any
    ) -> ArtifactSlotOutcome:
        self.calls.append(("prepare", principal, declared))
        return ArtifactSlotOutcome(
            "prepared", artifact_upload_id, "biotech/run/abc", datetime(2026, 10, 13, tzinfo=UTC)
        )

    async def commit_artifact(
        self, principal: Principal, ingress_id: UUID, artifact_upload_id: UUID
    ) -> RequestOutcome:
        return RequestOutcome("committed", ingress_id)

    async def request_mission(
        self, principal: Principal, item: InboxItem, *, manifest_ref: str
    ) -> RequestOutcome:
        self.calls.append(("request", principal, item))
        return RequestOutcome(self.outcome, item.ingress_id)

    async def mission_request_status(
        self, principal: Principal, request_id: UUID
    ) -> RequestStatusOutcome:
        return RequestStatusOutcome("found", "refused", None, "spawn_grant_missing", None)


class Oidc:
    async def verify(self, token: str) -> OidcIdentity:
        if token != "eyJ.cursor.jwt":
            raise IngressRejected(401, "invalid_token")
        return OidcIdentity(provider="cursor", session_id="bc-1")


class Uploads:
    async def signed_upload(self, storage_key: str) -> SignedUpload:
        return SignedUpload(path=storage_key, url=f"https://storage.test/{storage_key}")


def service(store: FakeStore, **kwargs: Any) -> SignalIngressService:
    return SignalIngressService(
        store,
        keys=IngressKeys(environment_key_master=MASTER, webhook_secrets={"github": "gh"}),
        oidc=Oidc(),
        uploads=Uploads(),
        **kwargs,
    )


def bearer(token: str = TOKEN) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def body(*signals: dict[str, Any]) -> bytes:
    return json.dumps({"signals": list(signals)}).encode()


async def code(call: Any) -> str:
    with pytest.raises(IngressRejected) as refusal:
        await call
    return refusal.value.code


async def test_the_bearer_shape_selects_the_run_token_or_the_oidc_tier() -> None:
    store = FakeStore()
    ingress = service(store)
    await ingress.signals(body({"signal_id": "a", "type": "milestone"}), bearer())
    await ingress.signals(body({"signal_id": "b", "type": "milestone"}), bearer("eyJ.cursor.jwt"))
    tiers = [(call[1].tier, call[1].credential) for call in store.calls]
    assert tiers == [
        (TrustTier.RUN_TOKEN, token_digest(TOKEN)),
        (TrustTier.PROVIDER_OIDC, "bc-1"),
    ]
    assert TOKEN not in repr(store.calls)
    assert await code(ingress.signals(body(), bearer("eyJ.forged"))) == "invalid_token"


async def test_signals_are_redacted_and_one_signal_or_a_batch_is_accepted() -> None:
    store = FakeStore()
    ingress = service(store)
    single = json.dumps(
        {
            "signal_id": "s-1",
            "type": "artifact.ready",
            "seq": 4,
            "data": {"api_key": "sk-abcdefghijklmnop", "note": "ok"},
        }
    ).encode()
    receipt = await ingress.signals(single, bearer())
    assert (receipt.accepted, receipt.duplicates) == (1, 0)
    item = store.calls[0][2][0]
    assert (item.kind, item.dedupe_key, item.seq) == ("signal.artifact.ready", "s-1", 4)
    assert item.payload["data"] == {"api_key": "[REDACTED]", "note": "ok"}
    assert item.body_sha256.startswith("sha256:")

    assert await code(ingress.signals(b"{not json", bearer())) == "invalid_body"
    assert await code(ingress.signals(body({"signal_id": "x", "type": "Bad Type"}), bearer())) == (
        "invalid_body"
    )
    too_many = body(*({"signal_id": f"n{i}", "type": "milestone"} for i in range(101)))
    assert await code(ingress.signals(too_many, bearer())) == "invalid_body"


async def test_payload_caps_apply_to_the_batch_and_to_each_signal() -> None:
    ingress = service(FakeStore(), limits=IngressLimits(max_signal_bytes=200, max_batch_bytes=400))
    big = body({"signal_id": "big", "type": "milestone", "data": {"x": "y" * 250}})
    assert await code(ingress.signals(big, bearer())) == "payload_too_large"
    huge = body(*({"signal_id": f"s{i}", "type": "milestone"} for i in range(20)))
    with pytest.raises(IngressRejected) as refusal:
        await ingress.signals(huge, bearer())
    assert (refusal.value.status_code, refusal.value.code) == (413, "payload_too_large")


async def test_the_signal_cap_measures_the_payload_as_sql_stores_it() -> None:
    store = FakeStore()
    wide = body({"signal_id": "w", "type": "milestone", "data": {f"k{i}": i for i in range(40)}})
    await service(store).signals(wide, bearer())
    payload = store.calls[0][2][0].payload
    compact = len(json.dumps(payload, separators=(",", ":")))
    stored = len(json.dumps(payload))  # jsonb text: a space after every `:` and `,`
    assert compact < stored
    capped = service(FakeStore(), limits=IngressLimits(max_signal_bytes=compact))
    assert await code(capped.signals(wide, bearer())) == "payload_too_large"
    assert (
        await service(FakeStore(), limits=IngressLimits(max_signal_bytes=stored)).signals(
            wide, bearer()
        )
    ).accepted == 1


def _environment_headers(payload: bytes, environment: str = "env_1") -> dict[str, str]:
    key = derive_secret(MASTER, ENVIRONMENT_KEY_PURPOSE, f"biotech/claude/{environment}")
    stamp = str(int(time.time()))
    signature = hmac.new(key, stamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
    return {
        "x-mc-provider": "claude",
        "x-mc-environment": environment,
        "x-mc-session": "sess-1",
        "x-mc-timestamp": stamp,
        "x-mc-signature": f"v1={signature}",
    }


async def test_the_run_nonce_is_hashed_for_binding_and_never_stored() -> None:
    store = FakeStore()
    ingress = service(store)
    started = body(
        {
            "signal_id": "e-1",
            "type": "session.started",
            "data": {"run_nonce": "nonce-1", "branch": "mc/run"},
        }
    )
    await ingress.signals(started, _environment_headers(started))
    _kind, principal, items = store.calls[0]
    assert principal == Principal(
        TrustTier.ENVIRONMENT_KEY,
        "sess-1",
        provider="claude",
        environment_ref="env_1",
        nonce_hash=token_digest("nonce-1"),
    )
    assert items[0].payload["data"] == {"branch": "mc/run"}
    gate = json.dumps(
        {"signal_id": "g", "hook_event": "before_tool", "effect_ref": "c", "effect_kind": "file"}
    ).encode()
    assert await code(ingress.gate(gate, _environment_headers(gate))) == "tier_not_allowed"
    unconfigured = SignalIngressService(FakeStore(), keys=IngressKeys())
    with pytest.raises(IngressRejected) as refusal:
        await unconfigured.signals(started, _environment_headers(started))
    assert refusal.value.status_code == 503


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        ("unknown", 401),
        ("revoked", 401),
        ("unbound_session", 401),
        ("wrong_purpose", 403),
        ("insufficient_scope", 403),
        ("rate_limited", 429),
        ("dedupe_conflict", 409),
        ("invalid_item", 422),
        ("surprise", 500),
    ],
)
async def test_store_outcomes_map_to_typed_http_rejections(outcome: str, status: int) -> None:
    ingress = service(FakeStore(outcome=outcome))
    with pytest.raises(IngressRejected) as refusal:
        await ingress.signals(body({"signal_id": "a", "type": "milestone"}), bearer())
    assert (refusal.value.code, refusal.value.status_code) == (outcome, status)


async def test_the_gate_digests_the_tool_input_and_returns_the_sql_decision() -> None:
    store = FakeStore()
    ingress = service(store)
    gate = json.dumps(
        {
            "signal_id": "g-1",
            "hook_event": "before_shell",
            "effect_ref": "call-1",
            "effect_kind": "shell",
            "tool": "Shell",
            "tool_input": {"command": "rm -rf /"},
        }
    ).encode()
    answer = await ingress.gate(gate, bearer())
    assert (answer.decision, answer.reason) == ("deny", "disallowed_tool")
    call = store.calls[0][2]
    assert (call.hook_event, call.effect_ref, call.effect_kind, call.tool) == (
        "before_shell",
        "call-1",
        "shell",
        "Shell",
    )
    assert call.input_digest.startswith("sha256:") and "rm -rf" not in repr(call)


async def test_oversized_webhooks_keep_only_their_scalar_identity() -> None:
    store = FakeStore()
    ingress = service(store, limits=IngressLimits(max_signal_bytes=300))
    push = json.dumps({"ref": "refs/heads/x", "after": "abc", "commits": ["c" * 400]}).encode()
    signature = "sha256=" + hmac.new(b"gh", push, hashlib.sha256).hexdigest()
    await ingress.webhook(
        "github",
        push,
        {"x-hub-signature-256": signature, "x-github-delivery": "d-1", "x-github-event": "push"},
    )
    item = store.calls[0][2]
    assert item.dedupe_key == "d-1" and item.kind == "webhook.github"
    assert item.payload["event"] == "push"
    assert item.payload["source_signal"]["data"] == {"ref": "refs/heads/x", "after": "abc"}
    assert item.payload["source_signal"]["signal_type"] == "github.push"
    assert "commits" not in json.dumps(item.payload)
    assert await code(ingress.webhook("gitlab", push, {})) == "unknown_provider"


async def test_launch_requests_need_a_minted_token_and_report_typed_refusals() -> None:
    store = FakeStore()
    ingress = service(store)
    request = json.dumps(
        {"idempotency_key": "k-1", "manifest_ref": "m@1", "inputs": {"topic": "x"}}
    ).encode()
    request_id = await ingress.request_mission(request, bearer())
    principal, item = store.calls[0][1], store.calls[0][2]
    assert principal.tier is TrustTier.LAUNCH_TOKEN and item.ingress_id == request_id
    assert item.payload["inputs_digest"].startswith("sha256:")
    assert await code(ingress.request_mission(request, bearer("eyJ.cursor.jwt"))) == (
        "invalid_token"
    )
    status = await ingress.mission_request_status(uuid4(), bearer())
    assert (status.state, status.reason) == ("refused", "spawn_grant_missing")


def test_the_router_serves_every_route_with_typed_codes_and_no_redirects() -> None:
    store = FakeStore()
    client = TestClient(create_ingress_app([service(store)]))
    base = "/v1/ingress/biotech"
    accepted = client.post(
        f"{base}/signals", content=body({"signal_id": "a", "type": "m"}), headers=bearer()
    )
    assert (accepted.status_code, accepted.json()) == (202, {"accepted": 1, "duplicates": 0})
    gate = json.dumps(
        {"signal_id": "g", "hook_event": "before_tool", "effect_ref": "c", "effect_kind": "file"}
    ).encode()
    gated = client.post(f"{base}/signals?gate=1", content=gate, headers=bearer())
    assert (gated.status_code, gated.json()) == (
        200,
        {"decision": "deny", "reason": "disallowed_tool"},
    )
    prepared = client.post(
        f"{base}/artifacts:prepare",
        content=json.dumps(
            {
                "artifact_ref": "r.pdf",
                "sha256": "sha256:" + "a" * 64,
                "size_bytes": 10,
                "media_type": "application/pdf",
            }
        ),
        headers=bearer(),
    )
    assert prepared.status_code == 200
    assert prepared.json()["upload_url"] == "https://storage.test/biotech/run/abc"
    committed = client.post(
        f"{base}/artifacts:commit",
        content=json.dumps({"artifact_upload_id": str(uuid4())}),
        headers=bearer(),
    )
    assert committed.status_code == 202
    assert client.post(f"{base}/provider/cursor", content=b"{}").status_code == 404
    unauthorized = client.post(f"{base}/signals", content=b"{}")
    assert (unauthorized.status_code, unauthorized.json()) == (
        401,
        {"detail": {"code": "missing_credential"}},
    )
    oversized = client.post(f"{base}/signals?gate=1", content=b"x" * 262_145, headers=bearer())
    assert oversized.status_code == 413
    assert client.post("/v1/ingress/unknown/signals", content=b"{}").status_code == 404
    slash = client.post(f"{base}/signals/", content=b"{}", follow_redirects=False)
    assert slash.status_code == 404
    assert client.get("/docs").status_code == 404


def test_the_loopback_listener_serves_the_same_ingress_handlers() -> None:
    callbacks = HookCallbackService(
        tokens=InMemoryHookTokenStore(),
        intents=InMemoryHookIntentLedger(),
        mapper=object(),  # type: ignore[arg-type]
    )
    store = FakeStore()
    loopback = TestClient(create_hook_callback_app(callbacks, ingress=[service(store)]))
    reply = loopback.post(
        "/v1/ingress/biotech/signals",
        content=body({"signal_id": "a", "type": "m"}),
        headers=bearer(),
    )
    assert reply.status_code == 202 and store.calls[0][0] == "accept"
    alone = TestClient(create_hook_callback_app(callbacks))
    assert alone.post("/v1/ingress/biotech/signals", content=b"{}").status_code == 404

"""MO-40 Signal Ingress on a disposable PostgreSQL 17 (migration 0035; SPEC-10; ADR-0045).

The edge connects as a login that is a member of `mission_control_ingress` only, through a pool
with the statement cache off (the transaction-pooler shape), and reaches the database solely
through the SECURITY DEFINER functions. The worker side (minting, session binding, revocation,
the drainer's claim and settle) runs as `mission_control_runtime` under forced RLS.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.ingress import (
    PostgresIngressStore,
    PostgresMintedCredentialStore,
    PostgresSessionBindings,
)
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.postgres.scope import apply_scope
from mission_control.application.capabilities.bundle_custody import SignedUpload
from mission_control.application.secrets.minting import (
    MINT_PURPOSES,
    CredentialBinding,
    CredentialMinter,
    LaunchBinding,
    MintPurpose,
    token_digest,
)
from mission_control.application.signals.contracts import IngressRejected, TrustTier
from mission_control.application.signals.ports import (
    InboxItem,
    OidcIdentity,
    Principal,
    SessionBinding,
)
from mission_control.application.signals.service import (
    IngressKeys,
    SignalIngressService,
)
from mission_control.application.signals.verification import (
    CURSOR_WEBHOOK_PURPOSE,
    ENVIRONMENT_KEY_PURPOSE,
    derive_secret,
)
from mission_control.domain.policies.stop_fence import StopFence
from mission_control.interfaces.http.ingress import create_ingress_app
from tests.fixtures.mission_control_common_db import CommonDatabase, ingress_login
from tests.fixtures.provider_webhooks import (
    ANTHROPIC_SESSION_IDLED,
    ANTHROPIC_TEST_SECRET,
    OPENAI_ACTION_REQUIRED,
    OPENAI_SESSION_CREATED,
    OPENAI_TEST_SECRET,
    delivery_body,
    standard_headers,
)
from tests.fixtures.scoped_api_stack import serve_loopback
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

pytestmark = pytest.mark.common_db

ENV_MASTER = b"environment-key-master-for-disposable-tests"
CURSOR_MASTER = b"cursor-webhook-master-for-disposable-tests"
GITHUB_SECRET = "github-webhook-secret"
HARNESS_EXECUTION = "0192a4f0-0000-7000-8000-0000000000e1"
GATE_CONTEXT = {
    "harness_execution_id": HARNESS_EXECUTION,
    "lane_profile": "cursor_cloud",
    "disallowed_tools": ["WebFetch"],
}


class FakeOidc:
    """Stands in for `CursorOidcVerifier` (proved on its own against signed JWTs)."""

    async def verify(self, token: str) -> OidcIdentity:
        if not token.startswith("oidc:"):
            raise IngressRejected(401, "invalid_token")
        return OidcIdentity(provider="cursor", session_id=token.removeprefix("oidc:"))


class FakeUploads:
    async def signed_upload(self, storage_key: str) -> SignedUpload:
        return SignedUpload(path=storage_key, url=f"https://storage.test/{storage_key}", token="t")


@dataclass
class Ingress:
    db: CommonDatabase
    runtime: asyncpg.Pool
    edge: asyncpg.Pool
    scope: str
    run_key: str
    unit_key: str
    minter: CredentialMinter
    sessions: PostgresSessionBindings
    store: PostgresIngressStore
    service: SignalIngressService

    @property
    def binding(self) -> CredentialBinding:
        return CredentialBinding(self.scope, self.run_key, self.unit_key, 1)

    async def owner(self, query: str, *args: Any) -> list[asyncpg.Record]:
        connection = await asyncpg.connect(self.db.owner_dsn)
        try:
            return list(await connection.fetch(query, *args))
        finally:
            await connection.close()

    async def inbox(self, kind: str | None = None) -> list[asyncpg.Record]:
        return await self.owner(
            "SELECT * FROM mission_control.ingress_inbox "
            "WHERE $1::text IS NULL OR kind = $1 ORDER BY received_at, ingress_id",
            kind,
        )


@pytest_asyncio.fixture
async def ingress(common_db: CommonDatabase) -> AsyncIterator[Ingress]:  # noqa: F811
    runtime = await common_db.pool("mission_control_runtime")
    edge = await asyncpg.create_pool(
        await ingress_login(common_db), min_size=1, max_size=4, statement_cache_size=0
    )
    try:
        admitted = await admit_unit_attempt(runtime, common_db)
        scope = common_db.scope()
        store = PostgresIngressStore(
            edge, installation_id=common_db.installation_id, application_id="biotech"
        )
        service = SignalIngressService(
            store,
            keys=IngressKeys(
                environment_key_master=ENV_MASTER,
                cursor_webhook_master=CURSOR_MASTER,
                webhook_secrets={
                    "anthropic": ANTHROPIC_TEST_SECRET,
                    "openai": OPENAI_TEST_SECRET,
                    "github": GITHUB_SECRET,
                },
            ),
            oidc=FakeOidc(),
            uploads=FakeUploads(),
        )
        yield Ingress(
            db=common_db,
            runtime=runtime,
            edge=edge,
            scope=scope,
            run_key=admitted.run_key,
            unit_key=admitted.unit.unit_key,
            minter=CredentialMinter(PostgresMintedCredentialStore(runtime, scope)),
            sessions=PostgresSessionBindings(runtime),
            store=store,
            service=service,
        )
    finally:
        await edge.close()
        await runtime.close()


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def signal(signal_id: str, kind: str = "milestone", **data: Any) -> dict[str, Any]:
    return {"signal_id": signal_id, "type": kind, "seq": 1, "data": data}


def batch(*signals: dict[str, Any]) -> bytes:
    return json.dumps({"signals": list(signals)}).encode()


def gate_body(signal_id: str, effect_ref: str, tool: str = "Shell", **extra: Any) -> bytes:
    return json.dumps(
        {
            "signal_id": signal_id,
            "hook_event": "before_shell",
            "effect_ref": effect_ref,
            "effect_kind": "shell",
            "tool": tool,
            "tool_input": {"command": "pytest -q"},
            **extra,
        }
    ).encode()


async def rejected(call: Any) -> str:
    with pytest.raises(IngressRejected) as refusal:
        await call
    return refusal.value.code


async def test_run_token_signals_are_accepted_once_redacted_and_notified(ingress: Ingress) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    listener = await asyncpg.connect(ingress.db.owner_dsn)
    notified: asyncio.Queue[str] = asyncio.Queue()
    await listener.add_listener("mc_ingress", lambda *args: notified.put_nowait(args[-1]))
    try:
        leaked = "mct_" + "A" * 43
        body = batch(signal("s-1", note=f"token {leaked}"), signal("s-2", "session.started"))
        receipt = await ingress.service.signals(body, bearer(token.value))
        assert (receipt.accepted, receipt.duplicates) == (2, 0)
        again = await ingress.service.signals(body, bearer(token.value))
        assert (again.accepted, again.duplicates) == (0, 2)

        rows = await ingress.inbox()
        assert [row["kind"] for row in rows] == ["signal.milestone", "signal.session.started"]
        first = rows[0]
        assert first["trust_tier"] == "run_token" and first["state"] == "pending"
        assert first["credential_ref"] == f"credential:{token.record.credential_id}"
        assert (first["run_key"], first["unit_key"], first["generation"]) == (
            ingress.run_key,
            ingress.unit_key,
            1,
        )
        assert first["tenant_id"] == ingress.db.tenants["tenant-1"]
        assert leaked not in first["payload"] and "[REDACTED]" in first["payload"]
        assert token.value not in json.dumps([dict(row) for row in rows], default=str)

        hint = json.loads(await asyncio.wait_for(notified.get(), 5))
        assert hint == {
            "scope": ingress.scope,
            "ingress_id": str(first["ingress_id"]),
            "kind": "signal.milestone",
        }
    finally:
        await listener.close()

    assert await rejected(ingress.service.signals(body, bearer("mct_" + "x" * 43))) == "unknown"
    assert await rejected(ingress.service.signals(body, {})) == "missing_credential"
    # The same token presented to another application's ingress names nothing there.
    other_app = SignalIngressService(
        PostgresIngressStore(
            ingress.edge, installation_id=ingress.db.installation_id, application_id="ai-engineer"
        ),
        keys=IngressKeys(),
    )
    assert await rejected(other_app.signals(body, bearer(token.value))) == "unknown"


async def test_payload_batch_and_rate_limits_are_enforced(ingress: Ingress) -> None:
    limited = MintPurpose(
        "signal_token", ("signal:write",), timedelta(hours=1), rate_limit_per_minute=3
    )
    minter = CredentialMinter(
        PostgresMintedCredentialStore(ingress.runtime, ingress.scope),
        purposes={**MINT_PURPOSES, "signal_token": limited},
    )
    token = await minter.mint("signal_token", ingress.binding)
    headers = bearer(token.value)

    oversized = batch(signal("big", blob="x" * 270_000))
    assert await rejected(ingress.service.signals(oversized, headers)) == "payload_too_large"
    # The SQL bounds hold even for a caller that skips the service's checks.
    principal_item = InboxItem(
        uuid4(), "signal.milestone", "raw", "sha256:" + "0" * 64, {"blob": "x" * 270_000}
    )
    principal = Principal(TrustTier.RUN_TOKEN, token_digest(token.value))
    assert (await ingress.store.accept(principal, [principal_item])).outcome == (
        "payload_too_large"
    )
    # Under the cap as compact JSON, over it as stored jsonb text (a space after `:` and `,`).
    wide = {f"k{index:05d}": 1 for index in range(21_000)}
    assert len(json.dumps(wide, separators=(",", ":"))) < 262_144 < len(json.dumps(wide))
    wide_signal = batch(signal("wide", **wide))
    assert await rejected(ingress.service.signals(wide_signal, headers)) == "payload_too_large"
    wide_item = InboxItem(uuid4(), "signal.milestone", "wide", "sha256:" + "0" * 64, wide)
    assert (await ingress.store.accept(principal, [wide_item])).outcome == "payload_too_large"
    many = [
        InboxItem(uuid4(), "signal.milestone", f"k{index}", "sha256:" + "0" * 64, {})
        for index in range(101)
    ]
    assert (await ingress.store.accept(principal, many)).outcome == "invalid_batch"
    bad_kind = InboxItem(uuid4(), "gate.decision", "k", "sha256:" + "0" * 64, {})
    assert (await ingress.store.accept(principal, [bad_kind])).outcome == "invalid_item"

    body = batch(signal("r-1"), signal("r-2"), signal("r-3"))
    assert (await ingress.service.signals(body, headers)).accepted == 3
    assert await rejected(ingress.service.signals(batch(signal("r-4")), headers)) == "rate_limited"
    # A new 60 s window admits the caller again.
    await ingress.owner(
        "UPDATE mission_control.ingress_credential "
        "SET rate_window_started_at = rate_window_started_at - interval '61 seconds' "
        "WHERE credential_hash = $1",
        token.record.digest,
    )
    assert (await ingress.service.signals(batch(signal("r-4")), headers)).accepted == 1
    assert len(await ingress.inbox()) == 4


async def test_the_gate_writes_the_intent_before_allow_and_answers_replays_alike(
    ingress: Ingress,
) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    headers = bearer(token.value)

    answer = await ingress.service.gate(gate_body("g-1", "call-1"), headers)
    assert (answer.decision, answer.reason) == ("allow", None)
    intent = (await ingress.owner("SELECT * FROM mission_control.hook_effect_intent"))[0]
    decision = (await ingress.inbox("gate.decision"))[0]
    assert intent["effect_ref"] == "call-1" and intent["run_key"] == ingress.run_key
    assert str(intent["harness_execution_id"]) == HARNESS_EXECUTION
    assert intent["lane_profile"] == "cursor_cloud" and intent["hook_event"] == "before_shell"
    # Intent before allow: it is recorded first, in the same transaction as the answer.
    assert intent["recorded_at"] <= decision["received_at"]
    assert decision["payload"] and json.loads(decision["payload"])["decision"] == "allow"
    admission = await ingress.owner(
        "SELECT decision, reason_code FROM mission_control.stop_fence_effect_admission"
    )
    assert [tuple(row) for row in admission] == [("allow", None)]

    replay = await ingress.service.gate(gate_body("g-1", "call-1"), headers)
    assert replay == answer
    assert len(await ingress.owner("SELECT 1 FROM mission_control.hook_effect_intent")) == 1
    assert len(await ingress.inbox("gate.decision")) == 1

    denied = await ingress.service.gate(gate_body("g-2", "call-2", tool="WebFetch"), headers)
    assert (denied.decision, denied.reason) == ("deny", "disallowed_tool")
    assert len(await ingress.owner("SELECT 1 FROM mission_control.hook_effect_intent")) == 1

    bare = await ingress.minter.mint("signal_token", ingress.binding)
    blind = await ingress.service.gate(gate_body("g-3", "call-3"), bearer(bare.value))
    assert (blind.decision, blind.reason) == ("deny", "gate_context_missing")


async def test_the_gate_answers_stop_under_a_fence_and_after_revocation(ingress: Ingress) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    headers = bearer(token.value)
    assert (await ingress.service.gate(gate_body("f-0", "before"), headers)).decision == "allow"

    await PostgresStopFenceRepository(ingress.runtime).persist(
        StopFence(
            request_scope=ingress.scope,
            run_id=ingress.run_key,
            generation=1,
            command_id="cancel-1",
            reason="operator stop",
            requested_at=datetime.now(UTC),
        )
    )
    fenced = await ingress.service.gate(gate_body("f-1", "after"), headers)
    assert (fenced.decision, fenced.reason) == ("stop", "stop_fenced")
    # The effect admitted before the fence stays admitted (same ledger as the loopback path).
    assert (await ingress.service.gate(gate_body("f-0", "before"), headers)).decision == "allow"
    ledger = await ingress.owner(
        "SELECT effect_ref, decision, reason_code FROM "
        "mission_control.stop_fence_effect_admission ORDER BY decided_at"
    )
    assert [tuple(row) for row in ledger] == [
        ("before", "allow", None),
        ("after", "deny", "STOP_FENCED"),
    ]
    assert [
        row["effect_ref"]
        for row in await ingress.owner("SELECT effect_ref FROM mission_control.hook_effect_intent")
    ] == ["before"]

    await ingress.minter.revoke_run(ingress.scope, ingress.run_key)
    revoked = await ingress.service.gate(gate_body("f-2", "later"), headers)
    assert (revoked.decision, revoked.reason) == ("stop", "credential_revoked")
    assert await rejected(ingress.service.signals(batch(signal("f-3")), headers)) == "revoked"


async def test_a_reused_gate_id_never_carries_its_decision_to_another_effect(
    ingress: Ingress,
) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    headers = bearer(token.value)
    assert (await ingress.service.gate(gate_body("g-1", "call-1"), headers)).decision == "allow"
    await PostgresStopFenceRepository(ingress.runtime).persist(
        StopFence(
            request_scope=ingress.scope,
            run_id=ingress.run_key,
            generation=1,
            command_id="cancel-1",
            reason="operator stop",
            requested_at=datetime.now(UTC),
        )
    )
    other = ingress.service.gate(gate_body("g-1", "call-other", tool="WebFetch"), headers)
    with pytest.raises(IngressRejected) as refusal:
        await other
    assert (refusal.value.status_code, refusal.value.code) == (409, "dedupe_conflict")
    # Same effect, different body: still not the recorded call.
    altered = gate_body("g-1", "call-1", tool_input={"command": "rm -rf /"})
    assert await rejected(ingress.service.gate(altered, headers)) == "dedupe_conflict"
    # The exact repeat answers its recorded decision, as the admission ledger does.
    assert (await ingress.service.gate(gate_body("g-1", "call-1"), headers)).decision == "allow"

    await ingress.minter.revoke_run(ingress.scope, ingress.run_key)
    third = gate_body("g-1", "call-third")
    assert await rejected(ingress.service.gate(third, headers)) == "dedupe_conflict"
    assert [
        row["effect_ref"]
        for row in await ingress.owner("SELECT effect_ref FROM mission_control.hook_effect_intent")
    ] == ["call-1"]
    ledger = await ingress.owner(
        "SELECT effect_ref, decision FROM mission_control.stop_fence_effect_admission"
    )
    assert [tuple(row) for row in ledger] == [("call-1", "allow")]
    assert len(await ingress.inbox("gate.decision")) == 1


async def test_each_kind_dedupes_in_its_own_space(ingress: Ingress) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    headers = bearer(token.value)
    # A hook records an event and gates it under one id, in either order.
    assert (await ingress.service.signals(batch(signal("tool-1")), headers)).accepted == 1
    gated = await ingress.service.gate(gate_body("tool-1", "call-1"), headers)
    assert (gated.decision, gated.reason) == ("allow", None)
    assert (await ingress.service.gate(gate_body("tool-2", "call-2"), headers)).decision == "allow"
    receipt = await ingress.service.signals(batch(signal("tool-2")), headers)
    assert (receipt.accepted, receipt.duplicates) == (1, 0)
    rows = await ingress.owner(
        "SELECT dedupe_space, dedupe_key FROM mission_control.ingress_inbox "
        "ORDER BY dedupe_key, dedupe_space"
    )
    assert [tuple(row) for row in rows] == [
        ("gate.decision", "tool-1"),
        ("signal", "tool-1"),
        ("gate.decision", "tool-2"),
        ("signal", "tool-2"),
    ]

    # A signal named like an artifact commit cannot take the commit's key.
    declared = json.dumps(
        {
            "artifact_ref": "reports/r.pdf",
            "sha256": "sha256:" + "ef" * 32,
            "size_bytes": 10,
            "media_type": "application/pdf",
        }
    ).encode()
    slot = await ingress.service.prepare_artifact(declared, headers)
    squat = signal(f"artifact:{slot.artifact_upload_id}")
    assert (await ingress.service.signals(batch(squat), headers)).accepted == 1
    commit = json.dumps({"artifact_upload_id": str(slot.artifact_upload_id)}).encode()
    committed = await ingress.service.commit_artifact(commit, headers)
    assert (await ingress.inbox("artifact.committed"))[0]["ingress_id"] == committed


async def test_an_unregistered_lane_profile_is_a_typed_deny(ingress: Ingress) -> None:
    context = {**GATE_CONTEXT, "lane_profile": "no_such_profile"}
    token = await ingress.minter.mint("signal_token", ingress.binding, context=context)
    answer = await ingress.service.gate(gate_body("lp-1", "call-lp"), bearer(token.value))
    assert (answer.decision, answer.reason) == ("deny", "gate_context_missing")
    assert await ingress.owner("SELECT 1 FROM mission_control.hook_effect_intent") == []


async def test_a_revoked_token_answers_stop_but_writes_only_within_its_rate_window(
    ingress: Ingress,
) -> None:
    limited = MintPurpose(
        "signal_token", ("signal:write",), timedelta(hours=1), rate_limit_per_minute=3
    )
    minter = CredentialMinter(
        PostgresMintedCredentialStore(ingress.runtime, ingress.scope),
        purposes={**MINT_PURPOSES, "signal_token": limited},
    )
    token = await minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    headers = bearer(token.value)
    for index in range(3):
        answer = await ingress.service.gate(gate_body(f"w-{index}", f"call-{index}"), headers)
        assert answer.decision == "allow"
    assert await rejected(ingress.service.gate(gate_body("w-3", "call-3"), headers)) == (
        "rate_limited"
    )

    await ingress.minter.revoke_run(ingress.scope, ingress.run_key)
    for index in range(20):
        revoked = await ingress.service.gate(gate_body(f"x-{index}", f"later-{index}"), headers)
        assert (revoked.decision, revoked.reason) == ("stop", "credential_revoked")
    assert len(await ingress.inbox("gate.decision")) == 3
    # A new window records the revoked decision again, still bounded by the limit.
    await ingress.owner(
        "UPDATE mission_control.ingress_credential "
        "SET rate_window_started_at = rate_window_started_at - interval '61 seconds' "
        "WHERE credential_hash = $1",
        token.record.digest,
    )
    for index in range(5):
        await ingress.service.gate(gate_body(f"y-{index}", f"again-{index}"), headers)
    decisions = await ingress.inbox("gate.decision")
    assert [json.loads(row["payload"])["reason"] for row in decisions[3:]] == [
        "credential_revoked"
    ] * 3


async def _until_waiting(ingress: Ingress, waiters: int) -> None:
    """Wait until `waiters` edge transactions are blocked on a lock."""

    for _ in range(200):
        blocked = await ingress.owner(
            "SELECT count(*) FROM pg_catalog.pg_stat_activity "
            "WHERE datname = current_database() AND wait_event_type = 'Lock'"
        )
        if blocked[0][0] >= waiters:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{waiters} edge calls never blocked")


async def _racing(ingress: Ingress, lock: str, *args: Any, calls: list[Any]) -> list[Any]:
    """Run `calls` concurrently while the owner holds `lock`, so each one passes its
    duplicate check before any of them records; then release it."""

    holder = await asyncpg.connect(ingress.db.owner_dsn)
    try:
        transaction = holder.transaction()
        await transaction.start()
        await holder.execute(lock, *args)
        tasks = [asyncio.create_task(call) for call in calls]
        await _until_waiting(ingress, len(tasks))
        await transaction.commit()
        return list(await asyncio.gather(*tasks))
    finally:
        await holder.close()


async def test_concurrent_repeats_answer_the_first_record_never_an_error(
    ingress: Ingress,
) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    headers = bearer(token.value)
    # A hook retrying after its timeout: both calls queue on the gate's per-run lock, and the
    # second answers the decision the first recorded.
    answers = await _racing(
        ingress,
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"mc.stop_fence:{ingress.scope}:{ingress.run_key}",
        calls=[ingress.service.gate(gate_body("race-1", "call-race"), headers) for _ in range(2)],
    )
    assert {(answer.decision, answer.reason) for answer in answers} == {("allow", None)}
    assert len(await ingress.inbox("gate.decision")) == 1

    lock_credential = (
        "SELECT 1 FROM mission_control.ingress_credential WHERE credential_hash = $1 FOR UPDATE"
    )
    declared = json.dumps(
        {
            "artifact_ref": "reports/r.pdf",
            "sha256": "sha256:" + "cd" * 32,
            "size_bytes": 10,
            "media_type": "application/pdf",
        }
    ).encode()
    slots = await _racing(
        ingress,
        lock_credential,
        token.record.digest,
        calls=[ingress.service.prepare_artifact(declared, headers) for _ in range(2)],
    )
    assert len({slot.artifact_upload_id for slot in slots}) == 1

    launch = await ingress.minter.mint("mission_request", LaunchBinding(ingress.scope))
    request = json.dumps({"idempotency_key": "race-launch", "manifest_ref": "m@1"}).encode()
    request_ids = await _racing(
        ingress,
        lock_credential,
        launch.record.digest,
        calls=[ingress.service.request_mission(request, bearer(launch.value)) for _ in range(2)],
    )
    assert len(set(request_ids)) == 1
    assert len(await ingress.inbox("mission_request")) == 1


async def test_a_new_generation_revokes_the_old_token_at_the_edge(ingress: Ingress) -> None:
    first = await ingress.minter.mint("signal_token", ingress.binding)
    assert (await ingress.service.signals(batch(signal("n-1")), bearer(first.value))).accepted
    second = CredentialBinding(ingress.scope, ingress.run_key, ingress.unit_key, 2)
    newer = await ingress.minter.mint("signal_token", second)
    assert await ingress.minter.revoke_superseded(second) == 1
    assert (
        await rejected(ingress.service.signals(batch(signal("n-2")), bearer(first.value)))
        == "revoked"
    )
    accepted = await ingress.service.signals(batch(signal("n-2")), bearer(newer.value))
    assert accepted.accepted == 1
    assert (await ingress.inbox())[-1]["generation"] == 2


def _signed(
    body: bytes, *, environment: str, session: str, provider: str = "claude"
) -> dict[str, str]:
    key = derive_secret(ENV_MASTER, ENVIRONMENT_KEY_PURPOSE, f"biotech/{provider}/{environment}")
    stamp = str(int(time.time()))
    signature = hmac.new(key, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {
        "x-mc-provider": provider,
        "x-mc-environment": environment,
        "x-mc-session": session,
        "x-mc-timestamp": stamp,
        "x-mc-signature": f"v1={signature}",
    }


async def test_an_environment_key_session_binds_once_on_the_run_nonce(ingress: Ingress) -> None:
    expires = datetime.now(UTC) + timedelta(hours=1)
    await ingress.sessions.register(
        SessionBinding(
            request_scope=ingress.scope,
            tier=TrustTier.ENVIRONMENT_KEY,
            provider="claude",
            run_key=ingress.run_key,
            unit_key=ingress.unit_key,
            generation=1,
            expires_at=expires,
            nonce_hash=token_digest("run-nonce-1"),
            environment_ref="env_1",
        ),
        uuid4(),
    )
    plain = batch(signal("e-0"))
    assert (
        await rejected(
            ingress.service.signals(plain, _signed(plain, environment="env_1", session="sess-1"))
        )
        == "unbound_session"
    )

    started = batch(signal("e-1", "session.started", run_nonce="run-nonce-1", branch="mc/x"))
    receipt = await ingress.service.signals(
        started, _signed(started, environment="env_1", session="sess-1")
    )
    assert receipt.accepted == 1
    row = (await ingress.inbox())[0]
    assert row["trust_tier"] == "environment_key" and row["run_key"] == ingress.run_key
    assert "run-nonce-1" not in row["payload"] and "run_nonce" not in row["payload"]
    bound = (await ingress.owner("SELECT * FROM mission_control.ingress_session_binding"))[0]
    assert bound["session_id"] == "sess-1" and bound["bound_at"] is not None

    later = batch(signal("e-2"))
    assert (
        await ingress.service.signals(later, _signed(later, environment="env_1", session="sess-1"))
    ).accepted == 1
    # The nonce binds one session only; another session presenting it is refused.
    replayed = batch(signal("e-3", "session.started", run_nonce="run-nonce-1"))
    assert (
        await rejected(
            ingress.service.signals(
                replayed, _signed(replayed, environment="env_1", session="sess-2")
            )
        )
        == "unbound_session"
    )
    assert (
        await rejected(
            ingress.service.signals(later, _signed(later, environment="env_2", session="sess-1"))
        )
        == "wrong_environment"
    )
    forged = _signed(later, environment="env_1", session="sess-1")
    forged["x-mc-signature"] = "v1=" + "0" * 64
    assert await rejected(ingress.service.signals(later, forged)) == "invalid_signature"
    gate = gate_body("e-4", "call-1")
    assert (
        await rejected(
            ingress.service.gate(gate, _signed(gate, environment="env_1", session="sess-1"))
        )
        == "tier_not_allowed"
    )


async def test_a_provider_oidc_session_must_be_bound_by_the_worker(ingress: Ingress) -> None:
    assert (
        await rejected(ingress.service.signals(batch(signal("o-0")), bearer("oidc:bc-agent-1")))
        == "unbound_session"
    )
    await ingress.sessions.register(
        SessionBinding(
            request_scope=ingress.scope,
            tier=TrustTier.PROVIDER_OIDC,
            provider="cursor",
            run_key=ingress.run_key,
            unit_key=ingress.unit_key,
            generation=1,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            session_id="bc-agent-1",
            context=GATE_CONTEXT,
        ),
        uuid4(),
    )
    receipt = await ingress.service.signals(batch(signal("o-1")), bearer("oidc:bc-agent-1"))
    assert receipt.accepted == 1
    answer = await ingress.service.gate(gate_body("o-2", "call-9"), bearer("oidc:bc-agent-1"))
    assert answer.decision == "allow"
    assert {row["trust_tier"] for row in await ingress.inbox()} == {"provider_oidc"}
    await ingress.sessions.revoke(ingress.scope, ingress.run_key, at=datetime.now(UTC))
    stopped = await ingress.service.gate(gate_body("o-3", "call-10"), bearer("oidc:bc-agent-1"))
    assert (stopped.decision, stopped.reason) == ("stop", "credential_revoked")


def _standard(body: bytes, delivery: str) -> dict[str, str]:
    return standard_headers(ANTHROPIC_TEST_SECRET, body, delivery)


def _hex(secret: bytes, body: bytes) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


async def test_provider_webhooks_are_tenantless_wakeups_deduped_on_delivery(
    ingress: Ingress,
) -> None:
    body = delivery_body(ANTHROPIC_SESSION_IDLED)
    await ingress.service.webhook("anthropic", body, _standard(body, "msg_1"))
    await ingress.service.webhook("anthropic", body, _standard(body, "msg_1"))
    forged = _standard(body, "msg_2") | {"webhook-signature": "v1,AAAA"}
    assert await rejected(ingress.service.webhook("anthropic", body, forged)) == (
        "invalid_signature"
    )
    stale = _standard(body, "msg_3") | {"webhook-timestamp": str(int(time.time()) - 900)}
    assert await rejected(ingress.service.webhook("anthropic", body, stale)) == "stale_timestamp"

    push = json.dumps({"ref": "refs/heads/mc/run", "after": "abc"}).encode()
    await ingress.service.webhook(
        "github",
        push,
        {
            "x-hub-signature-256": _hex(GITHUB_SECRET.encode(), push),
            "x-github-delivery": "gh-1",
            "x-github-event": "push",
        },
    )
    status = json.dumps({"event": "statusChange", "id": "bc-1", "status": "FINISHED"}).encode()
    run_secret = derive_secret(CURSOR_MASTER, CURSOR_WEBHOOK_PURPOSE, "biotech/run-ref-1")
    await ingress.service.webhook(
        "cursor",
        status,
        {"x-webhook-signature": _hex(run_secret.hex().encode(), status), "x-webhook-id": "cw-1"},
        route_ref="run-ref-1",
    )
    other_run = derive_secret(CURSOR_MASTER, CURSOR_WEBHOOK_PURPOSE, "biotech/run-ref-2")
    assert (
        await rejected(
            ingress.service.webhook(
                "cursor",
                status,
                {
                    "x-webhook-signature": _hex(other_run.hex().encode(), status),
                    "x-webhook-id": "cw-2",
                },
                route_ref="run-ref-1",
            )
        )
        == "invalid_signature"
    )

    rows = await ingress.inbox()
    assert [(row["kind"], row["credential_ref"], row["dedupe_key"]) for row in rows] == [
        ("webhook.anthropic", "webhook:anthropic", "msg_1"),
        ("webhook.github", "webhook:github", "gh-1"),
        ("webhook.cursor", "webhook:cursor:run-ref-1", "cw-1"),
    ]
    assert all(row["tenant_id"] is None and row["run_key"] is None for row in rows)
    assert json.loads(rows[1]["payload"])["event"] == "push"
    assert json.loads(rows[1]["payload"])["source_signal"]["signal_type"] == "github.push"
    assert json.loads(rows[2]["payload"])["source_signal"]["signal_type"] == "cursor.status_change"
    # Every tenant scope of the application sees an unresolved wake-up.
    for tenant in ("tenant-1", "tenant-2"):
        async with ingress.runtime.acquire() as connection, connection.transaction():
            await apply_scope(connection, ingress.db.scope(tenant))
            assert (
                await connection.fetchval("SELECT count(*) FROM mission_control.ingress_inbox") == 3
            )


async def test_signed_provider_fixtures_wake_once_and_forged_or_replayed_ones_record_nothing(
    ingress: Ingress,
) -> None:
    """HL-17: signed fixture deliveries become `mc.provider_wake.v1` rows (the event type and
    resource id only, never the payload's state); forged and replayed deliveries add no row
    and no notification."""

    listener = await asyncpg.connect(ingress.db.owner_dsn)
    notified: asyncio.Queue[str] = asyncio.Queue()
    await listener.add_listener("mc_ingress", lambda *args: notified.put_nowait(args[-1]))
    try:
        deliveries = [
            ("anthropic", ANTHROPIC_TEST_SECRET, ANTHROPIC_SESSION_IDLED, "msg_ma_1"),
            ("openai", OPENAI_TEST_SECRET, OPENAI_SESSION_CREATED, "msg_oa_1"),
            ("openai", OPENAI_TEST_SECRET, OPENAI_ACTION_REQUIRED, "msg_oa_2"),
        ]
        signed: list[tuple[str, bytes, dict[str, str]]] = []
        for provider, secret, envelope, delivery in deliveries:
            body = delivery_body(envelope)
            headers = standard_headers(secret, body, delivery)
            assert await ingress.service.webhook(provider, body, headers) == "accepted"
            signed.append((provider, body, headers))
        hints = [json.loads(await asyncio.wait_for(notified.get(), 5)) for _ in deliveries]
        assert [hint["kind"] for hint in hints] == [
            "webhook.anthropic",
            "webhook.openai",
            "webhook.openai",
        ]

        # Replays: the same signed delivery again, and a provider retry re-signed later.
        for provider, body, headers in signed:
            assert await ingress.service.webhook(provider, body, headers) == "duplicate"
        _provider, body, headers = signed[2]
        retry = standard_headers(
            OPENAI_TEST_SECRET,
            body,
            headers["webhook-id"],
            timestamp=int(headers["webhook-timestamp"]) + 30,
        )
        assert await ingress.service.webhook("openai", body, retry) == "duplicate"
        # A delivery captured more than five minutes ago (never received) is refused.
        stale = standard_headers(
            OPENAI_TEST_SECRET, body, "msg_oa_3", timestamp=int(time.time()) - 301
        )
        replayed = ingress.service.webhook("openai", body, stale)
        assert await rejected(replayed) == "stale_timestamp"
        # Forgeries: another provider's secret, a body changed after signing, a fresh id on
        # captured headers, and a signature that was never computed.
        anthropic_body = signed[0][1]
        cross = standard_headers(ANTHROPIC_TEST_SECRET, body, "msg_oa_4")
        tampered = anthropic_body.replace(b"sesn_011CTnB7fixture", b"sesn_011CTnB7attacker")
        for provider, forged_body, forged_headers in [
            ("openai", body, cross),
            ("anthropic", tampered, signed[0][2]),
            ("anthropic", anthropic_body, signed[0][2] | {"webhook-id": "msg_ma_2"}),
            ("openai", body, headers | {"webhook-signature": "v1,AAAA"}),
        ]:
            forged = ingress.service.webhook(provider, forged_body, forged_headers)
            assert await rejected(forged) == "invalid_signature"
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(notified.get(), 0.5)
    finally:
        await listener.close()

    rows = await ingress.inbox()
    assert [(row["kind"], row["dedupe_key"], row["trust_tier"]) for row in rows] == [
        ("webhook.anthropic", "msg_ma_1", "provider_signed"),
        ("webhook.openai", "msg_oa_1", "provider_signed"),
        ("webhook.openai", "msg_oa_2", "provider_signed"),
    ]
    assert [json.loads(row["payload"]) for row in rows] == [
        {
            "schema_version": "mc.provider_wake.v1",
            "event_type": "session.status_idled",
            "resource_ref": "sesn_011CTnB7fixture",
            "event_id": "wevt_011CTnB7d1xE2fixture",
        },
        {
            "schema_version": "mc.provider_wake.v1",
            "event_type": "agent.session.created",
            "resource_ref": "sess_fixture123",
            "event_id": "evt_fixture_created",
        },
        {
            "schema_version": "mc.provider_wake.v1",
            "event_type": "agent.session.action_required",
            "resource_ref": "sess_fixture123",
            "event_id": "evt_fixture_action",
        },
    ]
    assert all(row["state"] == "pending" and row["run_key"] is None for row in rows)
    assert "untrusted.invalid" not in json.dumps([dict(row) for row in rows], default=str)


async def test_artifact_uploads_are_prepared_once_and_committed_into_the_inbox(
    ingress: Ingress,
) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding)
    headers = bearer(token.value)
    digest = "sha256:" + "ab" * 32
    declared = json.dumps(
        {
            "artifact_ref": "reports/r.pdf",
            "sha256": digest,
            "size_bytes": 9_000_000,
            "media_type": "application/pdf",
        }
    ).encode()
    slot = await ingress.service.prepare_artifact(declared, headers)
    again = await ingress.service.prepare_artifact(declared, headers)
    assert again.artifact_upload_id == slot.artifact_upload_id
    run_id = (
        await ingress.owner(
            "SELECT run_id FROM mission_control.mission_run WHERE run_key = $1", ingress.run_key
        )
    )[0][0]
    assert slot.upload_url == (
        f"https://storage.test/biotech/{run_id}/{'ab' * 32}/{slot.artifact_upload_id}"
    )
    # Another generation of the run uploads the same bytes into a slot of its own.
    newer = await ingress.minter.mint(
        "signal_token", CredentialBinding(ingress.scope, ingress.run_key, ingress.unit_key, 2)
    )
    retried = await ingress.service.prepare_artifact(declared, bearer(newer.value))
    assert retried.artifact_upload_id != slot.artifact_upload_id

    commit = json.dumps({"artifact_upload_id": str(slot.artifact_upload_id)}).encode()
    committed = await ingress.service.commit_artifact(commit, headers)
    assert await ingress.service.commit_artifact(commit, headers) == committed
    assert await rejected(ingress.service.prepare_artifact(declared, headers)) == (
        "artifact_already_committed"
    )
    row = (await ingress.inbox("artifact.committed"))[0]
    assert row["ingress_id"] == committed
    payload = json.loads(row["payload"])
    assert payload["sha256"] == digest and payload["size_bytes"] == 9_000_000
    upload = (
        await ingress.owner(
            "SELECT * FROM mission_control.ingress_artifact_upload WHERE artifact_upload_id = $1",
            slot.artifact_upload_id,
        )
    )[0]
    assert upload["state"] == "committed" and upload["committed_at"] is not None

    unknown = json.dumps({"artifact_upload_id": str(uuid4())}).encode()
    assert await rejected(ingress.service.commit_artifact(unknown, headers)) == "not_found"
    with pytest.raises(asyncpg.PostgresError, match="cannot move"):
        await ingress.owner(
            "UPDATE mission_control.ingress_artifact_upload SET state = 'prepared', "
            "committed_at = NULL"
        )


async def test_mission_requests_need_a_launch_credential_and_dedupe_on_idempotency(
    ingress: Ingress,
) -> None:
    launch = await ingress.minter.mint(
        "mission_request",
        LaunchBinding(ingress.scope),
        context={"manifest_refs": ["mission:report@1"]},
    )
    headers = bearer(launch.value)
    request = json.dumps(
        {
            "idempotency_key": "launch-1",
            "manifest_ref": "mission:report@1",
            "inputs": {"topic": "kinase", "api_key": "sk-shouldnotpersist"},
        }
    ).encode()
    request_id = await ingress.service.request_mission(request, headers)
    assert await ingress.service.request_mission(request, headers) == request_id
    row = (await ingress.inbox("mission_request"))[0]
    assert row["trust_tier"] == "launch_token" and row["run_key"] is None
    payload = json.loads(row["payload"])
    assert payload["manifest_ref"] == "mission:report@1" and payload["inputs_digest"]
    assert "sk-shouldnotpersist" not in row["payload"]
    assert (await ingress.service.mission_request_status(request_id, headers)).state == "queued"

    other = json.dumps({"idempotency_key": "launch-2", "manifest_ref": "mission:other@1"})
    assert (
        await rejected(ingress.service.request_mission(other.encode(), headers))
        == "manifest_not_allowed"
    )
    signal_token = await ingress.minter.mint("signal_token", ingress.binding)
    assert (
        await rejected(ingress.service.request_mission(request, bearer(signal_token.value)))
        == "wrong_purpose"
    )
    assert await rejected(ingress.service.signals(batch(signal("l-1")), headers)) == "wrong_purpose"
    assert await rejected(ingress.service.mission_request_status(uuid4(), headers)) == "not_found"

    # The drainer settles it (row contract): admitted with the mission id, or refused.
    mission_id = (
        await ingress.owner(
            "SELECT mission_id FROM mission_control.mission_run WHERE run_key = $1", ingress.run_key
        )
    )[0][0]
    async with ingress.runtime.acquire() as connection, connection.transaction():
        await apply_scope(connection, ingress.scope)
        await connection.execute(
            "UPDATE mission_control.ingress_inbox SET state = 'drained', drained_at = now(), "
            "outcome = $2::jsonb WHERE ingress_id = $1",
            request_id,
            json.dumps({"mission_id": str(mission_id)}),
        )
    status = await ingress.service.mission_request_status(request_id, headers)
    assert (status.state, status.mission_id) == ("admitted", mission_id)
    assert status.lifecycle in {"admitted", "active"}

    refused_id = await ingress.service.request_mission(
        request.replace(b"launch-1", b"launch-3"), headers
    )
    async with ingress.runtime.acquire() as connection, connection.transaction():
        await apply_scope(connection, ingress.scope)
        await connection.execute(
            "UPDATE mission_control.ingress_inbox SET state = 'rejected', drained_at = now(), "
            'outcome = \'{"reason": "spawn_grant_missing"}\'::jsonb WHERE ingress_id = $1',
            refused_id,
        )
    refused = await ingress.service.mission_request_status(refused_id, headers)
    assert (refused.state, refused.reason) == ("refused", "spawn_grant_missing")


async def test_least_privilege_and_the_drainer_row_contract(ingress: Ingress) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding)
    await ingress.service.signals(batch(*(signal(f"d-{i}") for i in range(4))), bearer(token.value))

    async with ingress.edge.acquire() as connection:
        for statement in (
            "SELECT * FROM mission_control.ingress_inbox",
            "SELECT * FROM mission_control.ingress_credential",
            "SELECT * FROM mission_control.stop_fence",
            "SELECT mission_control.ingress_bind_scope(NULL, NULL, NULL)",
            "SELECT mission_control.ingress_definer()",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(statement)
    async with ingress.runtime.acquire() as connection:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.execute(
                "SELECT mission_control.ingress_webhook($1, 'biotech', 'github', NULL, $2, 'x', "
                "$3, '{}'::jsonb)",
                ingress.db.installation_id,
                uuid4(),
                "sha256:" + "0" * 64,
            )

    claim = (
        "SELECT ingress_id FROM mission_control.ingress_inbox WHERE state = 'pending' "
        "ORDER BY received_at, ingress_id FOR UPDATE SKIP LOCKED LIMIT 2"
    )
    first = await ingress.runtime.acquire()
    second = await ingress.runtime.acquire()
    try:
        one, two = first.transaction(), second.transaction()
        await one.start()
        await two.start()
        await apply_scope(first, ingress.scope)
        await apply_scope(second, ingress.scope)
        claimed_a = {row[0] for row in await first.fetch(claim)}
        claimed_b = {row[0] for row in await second.fetch(claim)}
        assert len(claimed_a) == len(claimed_b) == 2 and not claimed_a & claimed_b
        await first.execute(
            "UPDATE mission_control.ingress_inbox SET state = 'drained', drained_at = now() "
            "WHERE ingress_id = ANY($1::uuid[])",
            list(claimed_a),
        )
        await second.execute(
            "UPDATE mission_control.ingress_inbox SET attempts = attempts + 1, "
            "last_error = 'frame store unavailable' WHERE ingress_id = ANY($1::uuid[])",
            list(claimed_b),
        )
        await one.commit()
        await two.commit()
    finally:
        await ingress.runtime.release(first)
        await ingress.runtime.release(second)

    states = {row["state"]: row["attempts"] for row in await ingress.inbox()}
    assert states == {"drained": 0, "pending": 1}
    drained = next(row for row in await ingress.inbox() if row["state"] == "drained")
    async with ingress.runtime.acquire() as connection:
        async with connection.transaction():
            await apply_scope(connection, ingress.scope)
            with pytest.raises(asyncpg.PostgresError, match="does not move"):
                await connection.execute(
                    "UPDATE mission_control.ingress_inbox SET state = 'dead' WHERE ingress_id = $1",
                    drained["ingress_id"],
                )
        async with connection.transaction():
            await apply_scope(connection, ingress.scope)
            with pytest.raises(asyncpg.CheckViolationError):
                await connection.execute(
                    "UPDATE mission_control.ingress_inbox SET state = 'rejected', "
                    "drained_at = now() WHERE state = 'pending'"
                )
        async with connection.transaction():
            await apply_scope(connection, ingress.scope)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute("UPDATE mission_control.ingress_inbox SET payload = '{}'")
        async with connection.transaction():
            await apply_scope(connection, ingress.scope)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute("DELETE FROM mission_control.ingress_inbox")
        async with connection.transaction():
            await apply_scope(connection, ingress.db.scope("tenant-2"))
            assert (
                await connection.fetchval("SELECT count(*) FROM mission_control.ingress_inbox") == 0
            )
    with pytest.raises(asyncpg.PostgresError, match="bound to its digest"):
        await ingress.owner("UPDATE mission_control.ingress_credential SET generation = 2")


async def test_the_minted_credential_store_round_trips_digests_only(ingress: Ingress) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    store = PostgresMintedCredentialStore(ingress.runtime, ingress.scope)
    record = await store.by_digest(token.record.digest)
    assert record == token.record
    assert record is not None and record.context == GATE_CONTEXT
    verified = await ingress.minter.verify(
        token.value, purpose="signal_token", binding=ingress.binding, scope="signal:write"
    )
    assert verified.credential_id == token.record.credential_id
    stored = await ingress.owner(
        "SELECT row_to_json(c)::text FROM mission_control.ingress_credential c"
    )
    assert token.value not in stored[0][0]
    other = PostgresMintedCredentialStore(ingress.runtime, ingress.db.scope("tenant-2"))
    assert await other.by_digest(token.record.digest) is None
    with pytest.raises(ValueError, match="another request scope"):
        await other.insert(token.record)


async def test_the_local_http_edge_round_trips_through_postgres(ingress: Ingress) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    launch = await ingress.minter.mint("mission_request", LaunchBinding(ingress.scope))
    app = create_ingress_app([ingress.service])
    async with serve_loopback(app) as origin, httpx.AsyncClient(base_url=origin) as client:
        base = "/v1/ingress/biotech"
        assert (await client.get("/health/live")).json() == {"status": "live"}
        accepted = await client.post(
            f"{base}/signals", content=batch(signal("h-1")), headers=bearer(token.value)
        )
        assert (accepted.status_code, accepted.json()) == (202, {"accepted": 1, "duplicates": 0})
        gated = await client.post(
            f"{base}/signals?gate=1", content=gate_body("h-2", "c-1"), headers=bearer(token.value)
        )
        assert (gated.status_code, gated.json()) == (200, {"decision": "allow", "reason": None})
        body = delivery_body(ANTHROPIC_SESSION_IDLED)
        hook = await client.post(
            f"{base}/provider/anthropic", content=body, headers=_standard(body, "msg_9")
        )
        assert hook.status_code == 204 and hook.content == b""
        requested = await client.post(
            f"{base}/missions:request",
            content=json.dumps({"idempotency_key": "h-3", "manifest_ref": "m@1"}).encode(),
            headers=bearer(launch.value),
        )
        assert requested.status_code == 202
        request_id = requested.json()["request_id"]
        status = await client.get(
            f"{base}/missions:request/{request_id}", headers=bearer(launch.value)
        )
        assert (status.status_code, status.json()) == (200, {"state": "queued"})

        refused = await client.post(f"{base}/signals", content=batch(signal("h-4")))
        assert (refused.status_code, refused.json()) == (
            401,
            {"detail": {"code": "missing_credential"}},
        )
        too_big = await client.post(
            f"{base}/signals", content=b"x" * 1_048_577, headers=bearer(token.value)
        )
        assert too_big.status_code == 413
        assert (await client.post("/v1/ingress/other/signals", content=b"{}")).status_code == 404
        slash = await client.post(f"{base}/signals/", content=batch(signal("h-5")))
        assert slash.status_code == 404  # never a redirect: providers disable redirecting hooks
    assert len(await ingress.inbox()) == 4

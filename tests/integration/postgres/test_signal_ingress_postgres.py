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
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest

from mission_control.adapters.postgres.ingress import (
    PostgresIngressStore,
    PostgresMintedCredentialStore,
)
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.postgres.scope import apply_scope
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
from tests.support.integration.postgres.signal_ingress_postgres import (
    CURSOR_MASTER,
    ENV_MASTER,
    GATE_CONTEXT,
    GITHUB_SECRET,
    HARNESS_EXECUTION,
    Ingress,
    batch,
    bearer,
    gate_body,
    ingress,  # noqa: F401
    signal,
)
from tests.support.provider_webhooks import (
    ANTHROPIC_SESSION_IDLED,
    ANTHROPIC_TEST_SECRET,
    OPENAI_ACTION_REQUIRED,
    OPENAI_SESSION_CREATED,
    OPENAI_TEST_SECRET,
    delivery_body,
    standard_headers,
)
from tests.support.stack import serve_loopback

pytestmark = pytest.mark.common_db


async def rejected(call: Any) -> str:
    with pytest.raises(IngressRejected) as refusal:
        await call
    return refusal.value.code


async def test_run_token_signals_are_accepted_once_redacted_and_notified(ingress: Ingress) -> None:  # noqa: F811
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


async def test_payload_batch_and_rate_limits_are_enforced(ingress: Ingress) -> None:  # noqa: F811
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
    ingress: Ingress,  # noqa: F811
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


async def test_the_gate_answers_stop_under_a_fence_and_after_revocation(ingress: Ingress) -> None:  # noqa: F811
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
    ingress: Ingress,  # noqa: F811
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


async def test_each_kind_dedupes_in_its_own_space(ingress: Ingress) -> None:  # noqa: F811
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


async def test_an_unregistered_lane_profile_is_a_typed_deny(ingress: Ingress) -> None:  # noqa: F811
    context = {**GATE_CONTEXT, "lane_profile": "no_such_profile"}
    token = await ingress.minter.mint("signal_token", ingress.binding, context=context)
    answer = await ingress.service.gate(gate_body("lp-1", "call-lp"), bearer(token.value))
    assert (answer.decision, answer.reason) == ("deny", "gate_context_missing")
    assert await ingress.owner("SELECT 1 FROM mission_control.hook_effect_intent") == []


async def test_a_revoked_token_answers_stop_but_writes_only_within_its_rate_window(
    ingress: Ingress,  # noqa: F811
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


async def _until_waiting(ingress: Ingress, waiters: int) -> None:  # noqa: F811
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


async def _racing(ingress: Ingress, lock: str, *args: Any, calls: list[Any]) -> list[Any]:  # noqa: F811
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
    ingress: Ingress,  # noqa: F811
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


async def test_a_new_generation_revokes_the_old_token_at_the_edge(ingress: Ingress) -> None:  # noqa: F811
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


async def test_an_environment_key_session_binds_once_on_the_run_nonce(ingress: Ingress) -> None:  # noqa: F811
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


async def test_a_provider_oidc_session_must_be_bound_by_the_worker(ingress: Ingress) -> None:  # noqa: F811
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
    ingress: Ingress,  # noqa: F811
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
    ingress: Ingress,  # noqa: F811
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
    ingress: Ingress,  # noqa: F811
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
    ingress: Ingress,  # noqa: F811
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


MISSION_REQUEST_FUNCTION = (
    "mission_control.ingress_mission_request(uuid,text,text,uuid,text,text,text,jsonb)"
)


def mission_request(key: str, *, manifest: str = "fixture:first", value: str = "original") -> bytes:
    return json.dumps(
        {"idempotency_key": key, "manifest_ref": manifest, "inputs": {"topic": value}}
    ).encode()


async def launch_credential(ingress: Ingress, *, scope: str | None = None) -> Any:  # noqa: F811
    scope = scope or ingress.scope
    return await CredentialMinter(PostgresMintedCredentialStore(ingress.runtime, scope)).mint(
        "mission_request",
        LaunchBinding(scope),
        context={"manifest_refs": ["fixture:first", "fixture:second"]},
    )


async def test_a_mission_request_key_binds_its_body_digest_tenant_and_application(
    ingress: Ingress,  # noqa: F811
) -> None:
    """0044: the idempotency key replays only the same body; the definer recomputes nothing a
    direct caller supplies, and a key never crosses its tenant or application."""

    (function,) = await ingress.owner(
        "SELECT prosecdef, proconfig FROM pg_proc WHERE oid = $1::regprocedure",
        MISSION_REQUEST_FUNCTION,
    )
    assert function["prosecdef"] and "search_path=pg_catalog" in function["proconfig"]
    token = await launch_credential(ingress)
    headers = bearer(token.value)
    request = mission_request("bound-key")
    original_id = await ingress.service.request_mission(request, headers)
    original = dict((await ingress.inbox("mission_request"))[0])
    assert await ingress.service.request_mission(request, headers) == original_id
    for conflicting in (
        mission_request("bound-key", manifest="fixture:second"),
        mission_request("bound-key", value="changed"),
    ):
        with pytest.raises(IngressRejected) as failure:
            await ingress.service.request_mission(conflicting, headers)
        assert (failure.value.status_code, failure.value.code) == (409, "dedupe_conflict")
    # A direct SQL caller supplying the original digest with a different payload is refused.
    changed_payload = json.loads(original["payload"])
    changed_payload["inputs"]["topic"] = "forged-digest"
    async with ingress.edge.acquire() as connection:
        forged = await connection.fetchrow(
            "SELECT * FROM mission_control.ingress_mission_request($1,$2,$3,$4,$5,$6,$7,$8::jsonb)",
            ingress.db.installation_id,
            ingress.db.application_id,
            token.record.digest,
            uuid4(),
            "bound-key",
            "fixture:first",
            original["body_sha256"],
            json.dumps(changed_payload),
        )
    assert dict(forged) == {"outcome": "dedupe_conflict", "request_id": None}
    assert dict((await ingress.inbox("mission_request"))[0]) == original
    assert (await ingress.service.mission_request_status(original_id, headers)).state == "queued"
    # Credentials bind their own tenant: the same key cannot expose or mutate its sibling.
    other = await launch_credential(ingress, scope=ingress.db.scope("tenant-2"))
    other_id = await ingress.service.request_mission(request, bearer(other.value))
    assert other_id != original_id
    assert (
        await rejected(ingress.service.mission_request_status(original_id, bearer(other.value)))
        == "not_found"
    )
    wrong_application = SignalIngressService(
        PostgresIngressStore(
            ingress.edge, installation_id=ingress.db.installation_id, application_id="ai-engineer"
        ),
        keys=ingress.service._keys,
    )
    with pytest.raises(IngressRejected) as wrong_scope:
        await wrong_application.request_mission(request, headers)
    assert wrong_scope.value.status_code == 401


@pytest.mark.parametrize("conflicting", [False, True])
async def test_concurrent_mission_requests_check_the_winning_digest(
    ingress: Ingress,  # noqa: F811
    conflicting: bool,
) -> None:
    """Two requests with one key pass the absent-row lookup together and meet the INSERT
    conflict branch: the loser replays the winner, or is refused when its body differs."""

    token = await launch_credential(ingress)
    headers = bearer(token.value)
    first = mission_request("simultaneous")
    second = mission_request("simultaneous", value="changed") if conflicting else first
    owner = await asyncpg.connect(ingress.db.owner_dsn)
    tasks: list[asyncio.Task[Any]] = []
    try:
        async with owner.transaction():
            # Both calls pass the initial absent-row lookup, then block in ingress_take_rate.
            # Releasing this existing credential lock forces the INSERT conflict branch.
            await owner.fetchval(
                "SELECT credential_id FROM mission_control.ingress_credential "
                "WHERE credential_id=$1::uuid FOR UPDATE",
                UUID(token.record.credential_id),
            )
            tasks = [
                asyncio.create_task(ingress.service.request_mission(payload, headers))
                for payload in (first, second)
            ]
            async with asyncio.timeout(5):
                while True:
                    # Statistics snapshots are cached for this barrier transaction.
                    await owner.execute("SELECT pg_stat_clear_snapshot()")
                    waiting = await owner.fetchval(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND wait_event_type='Lock' AND pid<>pg_backend_pid() "
                        "AND query LIKE '%ingress_mission_request(%'",
                    )
                    if waiting == 2:
                        break
                    await asyncio.sleep(0.02)
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await owner.close()
    rows = await ingress.inbox("mission_request")
    assert len(rows) == 1
    winner = rows[0]
    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    if conflicting:
        assert successes == [winner["ingress_id"]]
        assert len(failures) == 1 and isinstance(failures[0], IngressRejected)
        assert (failures[0].status_code, failures[0].code) == (409, "dedupe_conflict")
    else:
        assert successes == [winner["ingress_id"], winner["ingress_id"]] and not failures
    winner_body = json.loads(winner["payload"])
    matching = mission_request("simultaneous", value=winner_body["inputs"]["topic"])
    assert await ingress.service.request_mission(matching, headers) == winner["ingress_id"]
    assert dict((await ingress.inbox("mission_request"))[0]) == dict(winner)


async def test_least_privilege_and_the_drainer_row_contract(ingress: Ingress) -> None:  # noqa: F811
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


async def test_the_minted_credential_store_round_trips_digests_only(ingress: Ingress) -> None:  # noqa: F811
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


async def test_the_local_http_edge_round_trips_through_postgres(ingress: Ingress) -> None:  # noqa: F811
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

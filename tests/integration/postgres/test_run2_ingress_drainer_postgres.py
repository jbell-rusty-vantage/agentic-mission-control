# ruff: noqa: F811
"""Restricted-role production claims and frame replay; disposable PG17 only."""

import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.ingress_drainer import PostgresIngressDrainStore
from mission_control.application.frames.writer import FrameWriter
from mission_control.application.secrets.minting import CredentialBinding
from mission_control.application.signals.drainer import IngressDrainer, write_signal
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_signal_ingress_postgres import (
    GATE_CONTEXT,
    Ingress,
    batch,
    bearer,
    gate_body,
    ingress,  # noqa: F401
    signal,
)

pytestmark = pytest.mark.common_db


async def enqueue(value: Ingress, *keys: str):
    token = await value.minter.mint("signal_token", value.binding, context=GATE_CONTEXT)
    await value.service.signals(batch(*(signal(key) for key in keys)), bearer(token.value))
    return token


async def test_claims_skip_locked_are_disjoint_and_rollback_releases(ingress: Ingress):
    await enqueue(ingress, "first", "second")
    pool = await ingress.db.pool("mission_control_runtime", max_size=3)
    try:
        store = PostgresIngressDrainStore(pool, ingress.scope)
        with pytest.raises(RuntimeError, match="rollback"):
            async with store.claim_batch(1) as first:
                assert len(first.items) == 1
                async with store.claim_batch(1) as second:
                    assert len(second.items) == 1
                    assert first.items[0].ingress_id != second.items[0].ingress_id
                    await second.settle(second.items[0], "drained", {})
                raise RuntimeError("rollback")
        async with store.claim_batch(10) as retried:
            assert [item.ingress_id for item in retried.items] == [first.items[0].ingress_id]
            assert retried.items[0].attempts == 0
        other = PostgresIngressDrainStore(pool, ingress.db.scope("tenant-2"))
        async with other.claim_batch(10) as isolated:
            assert not isolated.items
    finally:
        await pool.close()


async def test_persist_before_wake_retries_one_frame_and_distinct_dedupe_spaces(ingress: Ingress):
    admitted = await admit_unit_attempt(ingress.runtime, ingress.db)
    binding = CredentialBinding(ingress.scope, admitted.run_key, admitted.unit.unit_key, 1)
    token = await ingress.minter.mint("signal_token", binding, context=GATE_CONTEXT)
    headers = bearer(token.value)
    await ingress.service.signals(batch(signal("same-key")), headers)
    await ingress.service.gate(gate_body("same-key", "effect-1"), headers)
    frames = PostgresFrameRepository(ingress.runtime)
    handle = await frames.open_execution(admitted.start())
    writer = FrameWriter(frames, handle)

    class Effects:
        wakes = 0

        async def persist(self, item):
            return await write_signal(item, writer)

        async def wake(self, item):
            self.wakes += 1
            if self.wakes <= 2:
                raise RuntimeError("simulated failure after durable frame")

    pool = await ingress.db.pool("mission_control_runtime", max_size=2)
    try:
        drainer = IngressDrainer(PostgresIngressDrainStore(pool, ingress.scope), Effects())
        assert await drainer.drain_once() == 2
        assert await drainer.drain_once() == 2
        stored = await frames.frames_for_execution(ingress.scope, handle.harness_execution_id, 1)
        assert len(stored) == 2
        assert len({frame.provider_key for frame in stored}) == 2
        rows = await ingress.inbox()
        assert {row["state"] for row in rows} == {"drained"}
        assert {row["attempts"] for row in rows} == {2}
    finally:
        await pool.close()


async def test_attempt_cap_is_durable_and_sanitized(ingress: Ingress):
    await enqueue(ingress, "fails")

    class Failure:
        async def persist(self, item):
            raise RuntimeError("private-provider-body")

        async def wake(self, item):
            pytest.fail("wake before persist")

    pool = await ingress.db.pool("mission_control_runtime", max_size=2)
    try:
        drainer = IngressDrainer(
            PostgresIngressDrainStore(pool, ingress.scope), Failure(), max_attempts=2
        )
        assert await drainer.drain_once() == 1
        assert await drainer.drain_once() == 1
        assert await drainer.drain_once() == 0
        row = (await ingress.inbox())[0]
        assert (row["state"], row["attempts"], row["last_error"]) == ("dead", 2, "delivery_failed")
        assert "private-provider-body" not in str(dict(row))
    finally:
        await pool.close()


@pytest.mark.parametrize(
    "authority_loss", [None, "revoked", "expired", "race", "pre_replay_revoked", "takeover"]
)
async def test_webhook_history_receipt_waits_for_owner_and_survives_revoked_binding(
    ingress: Ingress, authority_loss, monkeypatch
):
    import asyncio
    import json
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from mission_control.adapters.postgres.lanes.execution_state import (
        PostgresLaneExecutionStateStore,
    )
    from mission_control.application.execution.harness.state import LaneExecutionUpdate
    from mission_control.application.signals.contracts import TrustTier
    from mission_control.application.signals.ports import SessionBinding
    from mission_control.bootstrap.ingress_drainer import ProductionIngressEffects
    from mission_control.contracts.identities import mission_operation_id
    from mission_control.domain.execution.history_reconciliation import (
        HistoryDeferred,
        HistoryRequest,
    )
    from mission_control.domain.frames.contracts import FrameKind, FrameObservation, LaneProfile
    from tests.fixtures.provider_webhooks import (
        ANTHROPIC_SESSION_IDLED,
        ANTHROPIC_TEST_SECRET,
        delivery_body,
        standard_headers,
    )

    admitted = await admit_unit_attempt(ingress.runtime, ingress.db)
    session_ref = ANTHROPIC_SESSION_IDLED["data"]["id"]
    frames = PostgresFrameRepository(ingress.runtime)
    handle = await frames.open_execution(
        admitted.start(lane=LaneProfile.CLAUDE_MANAGED, native_session_ref=session_ref)
    )
    states = PostgresLaneExecutionStateStore(ingress.runtime)
    owner = await states.claim_owner(
        ingress.scope,
        handle.harness_execution_id,
        owner_ref="fixture-owner",
        generation=1,
        now=datetime.now(UTC),
        lease=timedelta(minutes=5),
    )
    await states.record(
        ingress.scope,
        handle.harness_execution_id,
        LaneExecutionUpdate(native_session_ref=session_ref, native_turn_ref="native-turn"),
    )
    workflow = mission_operation_id(ingress.scope, admitted.run_key, "attempt")
    binding_expires = datetime.now(UTC) + timedelta(
        seconds=5 if authority_loss == "expired" else 3600
    )
    await ingress.sessions.register(
        SessionBinding(
            request_scope=ingress.scope,
            tier=TrustTier.PROVIDER_OIDC,
            provider="anthropic",
            run_key=admitted.run_key,
            unit_key=admitted.unit.unit_key,
            generation=1,
            expires_at=binding_expires,
            session_id=session_ref,
            context={
                "product": "claude_managed",
                "pins": {"schema": "fixture"},
                "harness_execution_id": str(handle.harness_execution_id),
                "operation_workflow_id": workflow,
            },
        ),
        uuid4(),
    )
    body = delivery_body(ANTHROPIC_SESSION_IDLED)
    headers = standard_headers(ANTHROPIC_TEST_SECRET, body, "history-hint")
    assert await ingress.service.webhook("anthropic", body, headers) == "accepted"
    assert await ingress.service.webhook("anthropic", body, headers) == "duplicate"
    signal = AsyncMock(side_effect=[RuntimeError("wake process crashed"), None])
    client = SimpleNamespace(get_workflow_handle=lambda name: SimpleNamespace(signal=signal))
    effects = ProductionIngressEffects(ingress.runtime, None, client, (ingress.scope,))
    claim_pool = await ingress.db.pool("mission_control_runtime", max_size=2)
    try:
        drainer = IngressDrainer(PostgresIngressDrainStore(claim_pool, ingress.scope), effects)
        drained = await drainer.drain_once()
        row = (await ingress.inbox("webhook.anthropic"))[0]
        assert drained == 0, (row["state"], row["outcome"], row["last_error"])
        assert row["state"] == "pending" and row["attempts"] == 0
        assert signal.await_count == 0
        outcome = json.loads(row["outcome"]) if isinstance(row["outcome"], str) else row["outcome"]
        request = HistoryRequest.model_validate(outcome["reconciliation_request"])
        state = await states.load(ingress.scope, handle.harness_execution_id)
        assert state.history_reconciliation.pending
        # Offline owners retain the hint without failure attempts or an immediate retry loop.
        assert await drainer.drain_once() == 0
        with pytest.raises(HistoryDeferred):
            await states.close_history_window(
                ingress.scope,
                handle.harness_execution_id,
                owner=owner,
                native_turn_ref="native-turn",
            )
        writer = FrameWriter(frames, handle)
        native = FrameObservation(
            provider_key="native-history-1",
            raw_kind="status",
            kind=FrameKind.STATUS,
            body={"status": "running"},
            native_session_ref=session_ref,
            native_turn_ref="native-turn",
        )
        assert (await writer.write([native])).new == 1
        if authority_loss in {"revoked", "expired", "pre_replay_revoked", "takeover"}:
            from mission_control.application.execution.harness.dispatch import StaleSessionOwner

            if authority_loss == "takeover":
                stale_owner = owner
                await frames.open_execution(
                    admitted.start(
                        lane=LaneProfile.CLAUDE_MANAGED,
                        native_session_ref=session_ref,
                        generation=2,
                    )
                )
                owner = await states.claim_owner(
                    ingress.scope,
                    handle.harness_execution_id,
                    owner_ref="takeover-owner",
                    generation=2,
                    now=datetime.now(UTC),
                    lease=timedelta(minutes=5),
                )
                with pytest.raises(ValueError):
                    await states.refresh_history_authority(
                        request,
                        owner=stale_owner,
                        at=datetime.now(UTC),
                    )
                with pytest.raises(ValueError):
                    await states.acknowledge_history(
                        request,
                        owner=owner,
                        cursor="unseen",
                        at=datetime.now(UTC),
                    )
            elif authority_loss != "expired":
                await ingress.sessions.revoke(ingress.scope, admitted.run_key, at=datetime.now(UTC))
            else:
                # Binding expiry is immutable; let the original short-lived authority expire.
                await asyncio.sleep(
                    max(0, (binding_expires - datetime.now(UTC)).total_seconds()) + 0.05
                )
            with pytest.raises(StaleSessionOwner):
                await states.refresh_history_authority(
                    request,
                    owner=owner.model_copy(update={"owner_ref": "stale-owner"}),
                    at=datetime.now(UTC),
                )
            if authority_loss in {"pre_replay_revoked", "takeover"}:
                rejected = await states.refresh_history_authority(
                    request, owner=owner, at=datetime.now(UTC)
                )
            else:
                rejected = await states.acknowledge_history(
                    request, owner=owner, cursor="native-history-1", at=datetime.now(UTC)
                )
            assert rejected.rejects(request) and not rejected.covers(request)
            assert not rejected.pending and not rejected.acknowledgments
            # A crash/retry after storing rejection neither creates success nor blocks closure.
            assert (
                await states.refresh_history_authority(request, owner=owner, at=datetime.now(UTC))
                == rejected
            )
            if authority_loss == "takeover":
                with pytest.raises(ValueError):
                    await states.acknowledge_history(
                        request, owner=owner, cursor="unseen", at=datetime.now(UTC)
                    )
            else:
                assert (
                    await states.acknowledge_history(
                        request, owner=owner, cursor="native-history-1", at=datetime.now(UTC)
                    )
                    == rejected
                )
            await states.close_history_window(
                ingress.scope,
                handle.harness_execution_id,
                owner=owner,
                native_turn_ref="native-turn",
            )
            await ingress.owner(
                "UPDATE mission_control.ingress_inbox "
                "SET outcome=outcome - 'reconciliation_retry_after' "
                "WHERE ingress_id=$1 RETURNING ingress_id",
                row["ingress_id"],
            )
            assert await drainer.drain_once() == 1
            rejected_inbox = (await ingress.inbox("webhook.anthropic"))[0]
            audit = json.loads(rejected_inbox["outcome"])
            assert rejected_inbox["state"] == "rejected" and signal.await_count == 0
            assert audit["reconciliation_request"] == request.model_dump(mode="json")
            # An explicitly superseding native session with a fresh valid binding may continue.
            next_session, next_binding = session_ref + "-next", uuid4()
            await states.record(
                ingress.scope,
                handle.harness_execution_id,
                LaneExecutionUpdate(
                    native_session_ref=next_session,
                    supersedes_session_ref=session_ref,
                    native_turn_ref="next-turn",
                    supersedes_turn_ref="native-turn",
                ),
            )
            await ingress.sessions.register(
                SessionBinding(
                    request_scope=ingress.scope,
                    tier=TrustTier.PROVIDER_OIDC,
                    provider="anthropic",
                    run_key=admitted.run_key,
                    unit_key=admitted.unit.unit_key,
                    generation=owner.generation,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                    session_id=next_session,
                    context={
                        "product": "claude_managed",
                        "pins": {"schema": "fixture"},
                        "harness_execution_id": str(handle.harness_execution_id),
                        "operation_workflow_id": workflow,
                    },
                ),
                next_binding,
            )
            following = request.model_copy(
                update={
                    "generation": owner.generation,
                    "session_binding_id": next_binding,
                    "native_session_ref": next_session,
                    "native_turn_ref": "next-turn",
                    "ingress_id": uuid4(),
                    "received_at": datetime.now(UTC),
                }
            )
            assert (await states.request_history(following)).pending
            return
        if authority_loss == "race":
            checked, release = asyncio.Event(), asyncio.Event()
            merge = states._merge_identity

            async def pause_after_binding_lock(*args, **kwargs):
                checked.set()
                await release.wait()
                return await merge(*args, **kwargs)

            monkeypatch.setattr(states, "_merge_identity", pause_after_binding_lock)
            acknowledging = asyncio.create_task(
                states.acknowledge_history(
                    request, owner=owner, cursor="native-history-1", at=datetime.now(UTC)
                )
            )
            await asyncio.wait_for(checked.wait(), 5)
            revoking = asyncio.create_task(
                ingress.sessions.revoke(ingress.scope, admitted.run_key, at=datetime.now(UTC))
            )
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(revoking), 0.1)
            finally:
                release.set()
                await acknowledging
                await revoking
                monkeypatch.setattr(states, "_merge_identity", merge)
        else:
            await states.acknowledge_history(
                request, owner=owner, cursor="native-history-1", at=datetime.now(UTC)
            )
        await states.close_history_window(
            ingress.scope, handle.harness_execution_id, owner=owner, native_turn_ref="native-turn"
        )
        await ingress.owner(
            "UPDATE mission_control.ingress_inbox "
            "SET outcome=outcome - 'reconciliation_retry_after' "
            "WHERE ingress_id=$1 RETURNING ingress_id",
            row["ingress_id"],
        )
        assert await drainer.drain_once() == 1  # persisted acknowledgment, failed wake
        assert signal.await_count == 1
        await ingress.sessions.revoke(ingress.scope, admitted.run_key, at=datetime.now(UTC))
        assert await drainer.drain_once() == 1  # exact original receipt survives revocation
        final = (await ingress.inbox("webhook.anthropic"))[0]
        assert final["state"] == "drained" and final["attempts"] == 2
        assert signal.await_count == 2
        assert (
            len(await frames.frames_for_execution(ingress.scope, handle.harness_execution_id, 1))
            == 1
        )
        fresh = request.model_copy(update={"ingress_id": uuid4(), "received_at": datetime.now(UTC)})
        with pytest.raises(ValueError):
            await states.request_history(fresh)
    finally:
        await claim_pool.close()

"""The `/missions` namespace over a real uvicorn server and python-socketio clients.

The stream source is the in-memory FIXTURE (`tests/unit/streams/fakes.py`) and the
credential resolver is a fake keyed by fixture tokens; real JWT verification, the real
registry check and real PostgreSQL replay are proven in
`tests/integration/postgres/test_mission_socket_postgres.py`.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
import socketio

from mission_control.interfaces.socketio.app import (
    MOUNTED_STATE,
    MissionSocketConfig,
    mount_mission_socketio,
)
from tests.support.unit.socketio.mission_socket import (
    ORIGIN,
    FixtureResolver,
    Lifecycle,
    auth,
    build,
)
from tests.unit.socketio.harness import MissionClient, serve
from tests.unit.streams.fakes import RUN_KEY, FakeStreamSource


def subscribe_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "request_id": "req-1",
        "application_id": "biotech",
        "target": {"kind": "run", "id": RUN_KEY},
        "streams": ["mission_events"],
    }
    body.update(overrides)
    return body


def cursor(seq: int) -> dict[str, Any]:
    return {"stream": "mission_events", "position": str(seq), "generation": None}


async def test_lifespan_runs_once_and_the_hub_closes_before_shutdown() -> None:
    lifecycle, resolver, source = Lifecycle(), FixtureResolver(), FakeStreamSource()
    app, asgi = build(lifecycle, resolver, source)
    with pytest.raises(RuntimeError, match="already mounted"):
        mount_mission_socketio(app, MissionSocketConfig(allowed_origins=(ORIGIN,)))
    client = MissionClient()
    async with serve(asgi) as (url, _server):
        assert (lifecycle.api_started, lifecycle.mcp_started) == (1, 1)
        mounted = getattr(app.state, MOUNTED_STATE)
        assert mounted.started == 1
        await client.connect(url, auth(resolver.grant("viewer")))
        ack = await client.call("subscribe", subscribe_body())
        assert ack["ok"] is True
    assert (lifecycle.api_stopped, lifecycle.mcp_stopped) == (1, 1)
    assert (mounted.started, mounted.stopped) == (1, 1)
    assert mounted.namespace.connections == 0
    await client.close()


async def test_connect_requires_a_live_credential_and_an_allowed_origin() -> None:
    lifecycle, resolver, source = Lifecycle(), FixtureResolver(), FakeStreamSource()
    _app, asgi = build(lifecycle, resolver, source)
    async with serve(asgi) as (url, _server):
        for credentials in (
            None,
            {"application_id": "biotech"},
            auth("not-a-token"),
            auth(resolver.grant("expired", exp=time.time() - 5)),
            auth(resolver.grant("viewer"), application_id="other-app"),
        ):
            client = MissionClient()
            with pytest.raises(socketio.exceptions.ConnectionError):
                await client.connect(url, credentials or {})
            await client.close()
        hostile = MissionClient()
        with pytest.raises(socketio.exceptions.ConnectionError):
            await hostile.connect(
                url, auth(resolver.grant("viewer")), headers={"Origin": "http://evil.test"}
            )
        await hostile.close()
        allowed = MissionClient()
        await allowed.connect(url, auth(resolver.grant("viewer")), headers={"Origin": ORIGIN})
        await allowed.close()


async def test_reconnect_with_acknowledged_cursor_loses_nothing_across_commits() -> None:
    lifecycle, resolver, source = Lifecycle(), FixtureResolver(), FakeStreamSource()
    source.commit_events(3)
    _app, asgi = build(lifecycle, resolver, source)
    token = resolver.grant("viewer")
    async with serve(asgi) as (url, _server):
        first = MissionClient()
        await first.connect(url, auth(token))
        ack = await first.call("subscribe", subscribe_body())
        assert ack["replay_from"] == [cursor(3)] and ack["gap"] is False
        assert first.order[0][0] == "subscribed"
        assert first.events["snapshot"][0]["reason"] == "no_cursor"
        source.commit_events(2)
        await first.wait_for(lambda: first.seqs() == [4, 5])
        acked = await first.call(
            "ack", {"subscription_id": ack["subscription_id"], "cursors": [cursor(5)]}
        )
        assert acked["acked"] == {"mission_events": 5}
        await first.close()
        source.commit_events(4)  # committed while no client is connected
        second = MissionClient()
        await second.connect(url, auth(token))
        resumed = await second.call("subscribe", subscribe_body(cursors=[cursor(5)]))
        assert resumed["replay_from"] == [cursor(5)] and resumed["high_watermarks"] == [cursor(9)]
        source.commit_events(1)
        await second.wait_for(lambda: second.seqs() == [6, 7, 8, 9, 10])
        await second.close()


async def test_forged_scope_cursor_and_subscription_are_typed_errors() -> None:
    lifecycle, resolver, source = Lifecycle(), FixtureResolver(), FakeStreamSource()
    source.commit_events(2)
    _app, asgi = build(lifecycle, resolver, source)
    async with serve(asgi) as (url, _server):
        client = MissionClient()
        await client.connect(url, auth(resolver.grant("viewer")))
        cases = {
            "SCOPE_MISMATCH": subscribe_body(application_id="other-app"),
            "CURSOR_AHEAD": subscribe_body(cursors=[cursor(99)]),
            "TARGET_NOT_FOUND": subscribe_body(target={"kind": "run", "id": "run-of-another"}),
            "UNSUPPORTED_FILTER": subscribe_body(room="mc-presence:anything"),
        }
        for code, body in cases.items():
            reply = await client.call("subscribe", body)
            assert reply["ok"] is False and reply["error"]["code"] == code, (code, reply)
        reply = await client.call("ack", {"subscription_id": "sub_forged", "cursors": [cursor(1)]})
        assert reply["error"]["code"] == "TARGET_NOT_FOUND"
        ok = await client.call("subscribe", subscribe_body(cursors=[cursor(0)]))
        await client.wait_for(lambda: client.seqs() == [1, 2])
        reply = await client.call(
            "ack", {"subscription_id": ok["subscription_id"], "cursors": [cursor(7)]}
        )
        assert reply["error"]["code"] == "CURSOR_AHEAD"
        reply = await client.call("resolve_human_task", {"request_id": "r"})
        assert reply["error"]["code"] == "COMMAND_CONFLICT"
        # MP-10: a well-formed resolution on a deployment without Human Tasks composed.
        reply = await client.call(
            "resolve_human_task",
            {
                "request_id": "r",
                "application_id": "biotech",
                "human_task_id": "task-1",
                "expected_task_version": 1,
                "decision": "approve",
                "reviewed_packet_digest": "sha256:" + "0" * 64,
            },
        )
        assert reply["error"]["code"] == "UNSUPPORTED_OPERATION"
        codes = [error["code"] for error in client.events["stream_error"]]
        assert codes.count("SCOPE_MISMATCH") == 1 and "UNAUTHORIZED" not in codes
        for error in client.events["stream_error"]:
            assert set(error) == {"code", "retryable", "request_id", "subscription_id", "detail"}
        await client.close()


async def test_permissionless_actor_cannot_read() -> None:
    lifecycle, resolver, source = Lifecycle(), FixtureResolver(), FakeStreamSource()
    source.commit_events(2)
    _app, asgi = build(lifecycle, resolver, source)
    async with serve(asgi) as (url, _server):
        client = MissionClient()
        await client.connect(url, auth(resolver.grant("nobody", read=False)))
        reply = await client.call("subscribe", subscribe_body(cursors=[cursor(0)]))
        assert reply["error"]["code"] == "UNAUTHORIZED"
        await asyncio.sleep(0.3)
        assert client.events["mission_event"] == []
        await client.close()


async def test_credential_expiry_detaches_and_disconnects_and_renewal_extends() -> None:
    lifecycle, resolver, source = Lifecycle(), FixtureResolver(), FakeStreamSource()
    _app, asgi = build(lifecycle, resolver, source)
    async with serve(asgi) as (url, _server):
        renewing, expiring, hijacker = MissionClient(), MissionClient(), MissionClient()
        for client in (renewing, expiring, hijacker):
            await client.connect(url, auth(resolver.grant("viewer", exp=time.time() + 2)))
            assert (await client.call("subscribe", subscribe_body(cursors=[cursor(0)])))["ok"]
        renewed = await renewing.call("reauthenticate", {"token": resolver.grant("viewer")})
        assert renewed["ok"] is True
        # A revoked connection is closed at once: the typed error arrives, the ack may not.
        await hijacker.sio.emit(
            "reauthenticate", {"token": resolver.grant("someone")}, namespace="/missions"
        )
        await hijacker.wait_for(lambda: not hijacker.sio.connected, within=5)
        assert [e["code"] for e in hijacker.events["stream_error"]] == ["UNAUTHORIZED"]
        await expiring.wait_for(lambda: not expiring.sio.connected, within=10)
        source.commit_events(2)
        await renewing.wait_for(lambda: renewing.seqs() == [1, 2])
        assert renewing.sio.connected
        await asyncio.sleep(0.3)
        assert expiring.events["mission_event"] == [] == hijacker.events["mission_event"]
        assert [e["code"] for e in expiring.events["stream_error"]] == ["UNAUTHORIZED"]
        for client in (renewing, expiring, hijacker):
            await client.close()


async def test_a_slow_socket_consumer_is_resynced_and_detached() -> None:
    lifecycle, resolver, source = Lifecycle(), FixtureResolver(), FakeStreamSource()
    source.commit_events(500)
    _app, asgi = build(lifecycle, resolver, source, max_connection_queue_bytes=65_536)
    async with serve(asgi) as (url, _server):
        client = MissionClient()
        await client.connect(url, auth(resolver.grant("viewer")))
        await client.call("subscribe", subscribe_body(cursors=[cursor(0)]))
        await client.wait_for(lambda: bool(client.events["resync_required"]), within=10)
        notice = client.events["resync_required"][0]
        assert notice["code"] == "SLOW_CONSUMER" and notice["detached"] is True
        assert notice["replay_from"] == [cursor(0)]
        assert 0 < len(client.events["mission_event"]) < 500
        assert client.sio.connected  # detached, not disconnected
        await client.close()


async def test_message_floods_are_rate_limited() -> None:
    lifecycle, resolver, source = Lifecycle(), FixtureResolver(), FakeStreamSource()
    _app, asgi = build(lifecycle, resolver, source, messages_per_second=1.0, message_burst=2)
    async with serve(asgi) as (url, _server):
        client = MissionClient()
        await client.connect(url, auth(resolver.grant("viewer")))
        replies = [await client.call("unsubscribe", {"subscription_id": "x"}) for _ in range(4)]
        codes = [reply["error"]["code"] for reply in replies]
        assert codes[:2] == ["TARGET_NOT_FOUND", "TARGET_NOT_FOUND"]
        assert "RATE_LIMITED" in codes[2:]
        await client.close()

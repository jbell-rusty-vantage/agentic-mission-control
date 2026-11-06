"""`tests/fixtures/tcp_proxy.py` (FX-TR-REMOTE's saver proxy) against an asyncio echo server:
bytes pass through unchanged, `delay_seconds` is applied to each client chunk, and
`set_closed(True)` severs open pairs and refuses new ones until `set_closed(False)`."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from tests.fixtures.tcp_proxy import SaverProxy


async def _echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


@asynccontextmanager
async def echo_server() -> AsyncIterator[tuple[str, int]]:
    server = await asyncio.start_server(_echo, host="127.0.0.1", port=0)
    try:
        yield "127.0.0.1", server.sockets[0].getsockname()[1]
    finally:
        server.close()
        # 3.12's `wait_closed` waits for every connection; never let a leak hang the test.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(server.wait_closed(), timeout=10)


async def _round_trip(port: int, payload: bytes) -> tuple[bytes, float]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        started = time.perf_counter()
        writer.write(payload)
        await writer.drain()
        echoed = await asyncio.wait_for(reader.readexactly(len(payload)), timeout=10)
        return echoed, time.perf_counter() - started
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def _reads_eof(port: int) -> bool:
    """A connection to `port` is accepted and closed (or reset) without data."""

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        return True
    try:
        data = await asyncio.wait_for(reader.read(16), timeout=10)
    except (OSError, asyncio.IncompleteReadError):
        return True
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    return data == b""


@pytest.mark.asyncio
async def test_proxy_forwards_delays_and_cuts() -> None:
    async with echo_server() as (host, port):
        proxy = SaverProxy(host, port)
        await proxy.start()
        try:
            assert proxy.port > 0
            payload = b"\x00\x00\x00\x08\x04\xd2\x16\x2f" + bytes(range(256))
            echoed, elapsed = await _round_trip(proxy.port, payload)
            assert echoed == payload
            assert elapsed < 1.0
            proxy.delay_seconds = 0.3
            echoed, elapsed = await _round_trip(proxy.port, b"delayed")
            assert echoed == b"delayed"
            assert elapsed >= 0.3, elapsed
            proxy.delay_seconds = 0.0
            # An open pair is severed by the cut: the client reads EOF (or a reset).
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
            writer.write(b"before-cut")
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(10), timeout=10) == b"before-cut"
            proxy.set_closed(True)
            assert proxy.closed
            try:
                rest = await asyncio.wait_for(reader.read(16), timeout=10)
            except OSError:
                rest = b""
            assert rest == b""
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            # New connections are accepted and closed at once while cut.
            assert await _reads_eof(proxy.port)
            assert proxy.connections_refused >= 1
            # Restored service echoes again.
            proxy.set_closed(False)
            echoed, _elapsed = await _round_trip(proxy.port, b"restored")
            assert echoed == b"restored"
            assert proxy.connections_served >= 3
        finally:
            await proxy.stop()
        # Stopped: nothing listens any more (refused, or accepted by nobody).
        with pytest.raises((OSError, asyncio.TimeoutError)):
            await asyncio.wait_for(asyncio.open_connection("127.0.0.1", proxy.port), timeout=5)


@pytest.mark.asyncio
async def test_proxy_requires_an_upstream_and_starts_once() -> None:
    proxy = SaverProxy()
    with pytest.raises(ValueError):
        await proxy.start()
    async with echo_server() as (host, port):
        await proxy.start(host, port)
        try:
            with pytest.raises(RuntimeError):
                await proxy.start()
        finally:
            await proxy.stop()
        await proxy.stop()  # idempotent

"""A dumb loopback TCP proxy for one upstream, driven from the test's own event loop.

FX-TR-REMOTE (TRACING-PROPOSAL §P9, WP-TR-5) points the LangGraph saver DSN at this proxy
instead of at a `toxiproxy`/`socat` delay: `delay_seconds` is slept before every chunk
forwarded from the client to the upstream (so every saver query is delayed by at least that
much), and `set_closed(True)` severs every open connection pair and makes the proxy accept
and immediately close new ones (the "saver unreachable" condition); `set_closed(False)`
restores service. Bytes are forwarded unchanged in both directions, so PostgreSQL's wire
protocol (including the `SSLRequest` / `N` negotiation) passes through untouched.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

CHUNK = 65536


@dataclass(eq=False)  # identity-hashed: pairs live in a set
class _Pair:
    """One accepted client connection and its upstream connection."""

    client: asyncio.StreamWriter
    upstream: asyncio.StreamWriter
    pumps: list[asyncio.Task[None]] = field(default_factory=list)

    def sever(self) -> None:
        for writer in (self.client, self.upstream):
            with contextlib.suppress(Exception):
                writer.close()
        for pump in self.pumps:
            pump.cancel()


class SaverProxy:
    """Forward 127.0.0.1:`port` to `upstream_host`:`upstream_port` with mutable delay and cut.

    Attributes
    ----------
    port
        The bound loopback port, known after `start()`.
    delay_seconds
        Slept before each chunk is forwarded from a client to the upstream (0 by default).
        Mutable at any time; the next chunk reads the new value.
    closed
        When True, open pairs have been severed and new connections are accepted and closed
        at once. Change it through `set_closed` so open pairs are severed too.
    connections_served, connections_refused
        Counters for evidence: pairs opened, and connections refused while closed.

    The upstream may be given at construction or to `start()` (the scoped stack learns the
    saver's host and port only after the disposable database exists).
    """

    def __init__(self, upstream_host: str = "", upstream_port: int = 0) -> None:
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.port: int = 0
        self.delay_seconds: float = 0.0
        self.closed: bool = False
        self.connections_served = 0
        self.connections_refused = 0
        self._server: asyncio.AbstractServer | None = None
        self._pairs: set[_Pair] = set()

    async def start(
        self, upstream_host: str | None = None, upstream_port: int | None = None
    ) -> None:
        """Bind a free loopback port; forward to the upstream (optionally given here)."""

        if upstream_host is not None:
            self.upstream_host = upstream_host
        if upstream_port is not None:
            self.upstream_port = upstream_port
        if not self.upstream_host or not self.upstream_port:
            raise ValueError("SaverProxy needs an upstream host and port before start()")
        if self._server is not None:
            raise RuntimeError("SaverProxy is already started")
        self._server = await asyncio.start_server(self._accept, host="127.0.0.1", port=0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Sever every pair and stop listening; idempotent."""

        for pair in list(self._pairs):
            pair.sever()
        self._pairs.clear()
        server, self._server = self._server, None
        if server is not None:
            server.close()
            # 3.12's `wait_closed` waits for every connection handler; pairs are severed above.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(server.wait_closed(), timeout=10)

    def set_closed(self, closed: bool) -> None:
        """Cut (True) or restore (False) the proxied service; cutting severs open pairs."""

        self.closed = closed
        if closed:
            for pair in list(self._pairs):
                pair.sever()
            self._pairs.clear()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.closed:
            self.connections_refused += 1
            await _close(writer)
            return
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                self.upstream_host, self.upstream_port
            )
        except OSError:
            self.connections_refused += 1
            await _close(writer)
            return
        pair = _Pair(client=writer, upstream=upstream_writer)
        self._pairs.add(pair)
        self.connections_served += 1
        pair.pumps = [
            asyncio.create_task(self._pump(reader, upstream_writer, delayed=True)),
            asyncio.create_task(self._pump(upstream_reader, writer, delayed=False)),
        ]
        try:
            await asyncio.gather(*pair.pumps, return_exceptions=True)
        finally:
            self._pairs.discard(pair)
            await _close(writer)
            await _close(upstream_writer)

    async def _pump(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, delayed: bool
    ) -> None:
        """Copy chunks from `reader` to `writer` until EOF or an error; closes `writer` after."""

        try:
            while True:
                data = await reader.read(CHUNK)
                if not data:
                    break
                if delayed and self.delay_seconds > 0:
                    await asyncio.sleep(self.delay_seconds)
                writer.write(data)
                await writer.drain()
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            await _close(writer)


async def _close(writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(Exception):
        writer.close()
        await writer.wait_closed()


class ConnectProxy(SaverProxy):
    """An HTTP `CONNECT` tunnel on loopback for FX-TR-DISCONNECT (tracing Stage 2 §4c).

    The provider endpoint is HTTPS, so the proxy cannot sit in front of it as a plain TCP
    forward (the TLS name would not match); a client that honours `HTTPS_PROXY` (httpx, so
    the OpenAI SDK) asks for a tunnel instead. Each `CONNECT host:port` opens its own
    upstream; the bytes stay opaque. `sever_open()` cuts every open tunnel once (the
    "connection cut during a model turn") while new tunnels keep being served, and
    `tunnels` records the host and byte counts of every tunnel for the evidence.
    """

    def __init__(self) -> None:
        super().__init__("connect-proxy", 1)
        self.tunnels: list[dict[str, object]] = []
        self.severed: list[dict[str, object]] = []

    async def start(
        self, upstream_host: str | None = None, upstream_port: int | None = None
    ) -> None:
        del upstream_host, upstream_port
        self._server = await asyncio.start_server(self._accept, host="127.0.0.1", port=0)
        self.port = self._server.sockets[0].getsockname()[1]

    def sever_open(self) -> int:
        """Cut every open tunnel now; returns how many were cut."""

        cut = 0
        for pair in list(self._pairs):
            pair.sever()
            cut += 1
        self.severed.append({"tunnels": cut})
        self._pairs.clear()
        return cut

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, OSError):
            await _close(writer)
            return
        request = head.split(b"\r\n", 1)[0].decode("latin-1").split()
        if len(request) < 2 or request[0].upper() != "CONNECT" or ":" not in request[1]:
            writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            await _close(writer)
            return
        host, _, port = request[1].rpartition(":")
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(host, int(port))
        except OSError:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await _close(writer)
            return
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        tunnel: dict[str, object] = {"host": host, "port": int(port), "severed": False}
        self.tunnels.append(tunnel)
        pair = _Pair(client=writer, upstream=upstream_writer)
        self._pairs.add(pair)
        self.connections_served += 1
        pair.pumps = [
            asyncio.create_task(self._pump(reader, upstream_writer, delayed=False)),
            asyncio.create_task(self._pump(upstream_reader, writer, delayed=False)),
        ]
        try:
            await asyncio.gather(*pair.pumps, return_exceptions=True)
        finally:
            if pair not in self._pairs:
                tunnel["severed"] = True
            self._pairs.discard(pair)
            await _close(writer)
            await _close(upstream_writer)

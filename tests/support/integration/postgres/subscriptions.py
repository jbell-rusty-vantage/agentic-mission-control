"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_subscriptions.py.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mission_control.domain.policies.contracts import ActorContext

SECRET_ENV = "MCFT_SUBSCRIPTION_TEST_SECRET"
SECRET_VALUE = "disposable-local-signing-key"
READER = ActorContext(actor_id="actor:subscriber", permissions=frozenset({"workflow_run.read"}))


@dataclass
class Receiver:
    """A local HTTP endpoint that records raw bodies and answers with scripted statuses."""

    status: int = 204
    received: list[tuple[dict[str, str], bytes]] = field(default_factory=list)
    server: asyncio.AbstractServer | None = None

    async def start(self) -> str:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/hook"

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readline()
            headers: dict[str, str] = {}
            while (line := await reader.readline()) not in (b"\r\n", b""):
                name, _, value = line.decode("latin-1").partition(":")
                headers[name.strip().lower()] = value.strip()
            body = await reader.readexactly(int(headers.get("content-length", "0")))
            self.received.append((headers, body))
            status_line = f"HTTP/1.1 {self.status} X\r\n"
            writer.write((status_line + "content-length: 0\r\nconnection: close\r\n\r\n").encode())
            await writer.drain()
        finally:
            writer.close()


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

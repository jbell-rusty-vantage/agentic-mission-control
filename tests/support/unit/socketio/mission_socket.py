"""Builders, constants and fakes that other test files import.

Moved from tests/unit/socketio/test_mission_socket.py.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from mission_control.application.streams.pump import PumpSettings
from mission_control.application.streams.service import MissionStreamService
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.http.mission_control import MissionPrincipal
from mission_control.interfaces.socketio.app import MissionSocketConfig, mount_mission_socketio
from mission_control.interfaces.socketio.auth import SocketAuthRejected, token_expiry
from mission_control.interfaces.socketio.server import STREAM_SERVICES, MissionSocketLimits
from tests.fixtures.provider_frames import INSTALLATION, SCOPE, TENANT
from tests.unit.socketio.harness import fixture_token
from tests.unit.streams.fakes import FakeStreamSource

ORIGIN = "http://dashboard.test"


class Lifecycle:
    def __init__(self) -> None:
        self.api_started = self.api_stopped = 0
        self.mcp_started = self.mcp_stopped = 0


class FixtureResolver:
    """Fake verifier: a token is valid while registered and before its `exp`."""

    def __init__(self) -> None:
        self.tokens: dict[str, ActorContext] = {}
        self.calls = 0

    def grant(self, actor_id: str, *, exp: float | None = None, read: bool = True) -> str:
        token = fixture_token(actor_id, exp=exp)
        permissions = frozenset({"workflow_run.read"}) if read else frozenset()
        self.tokens[token] = ActorContext(actor_id=actor_id, permissions=permissions)
        return token

    def __call__(self, application_id: str, token: str) -> MissionPrincipal:
        self.calls += 1
        actor = self.tokens.get(token)
        expiry = token_expiry(token)
        if actor is None or expiry is None or expiry <= time.time():
            raise SocketAuthRejected("invalid_token")
        if application_id != "biotech":
            raise SocketAuthRejected("application_scope_denied")
        return MissionPrincipal(
            installation_id=INSTALLATION,
            application_id="biotech",
            tenant_id=TENANT,
            issuer="https://issuer.invalid",
            audiences=frozenset({"authenticated"}),
            actor=actor,
        )


def build(
    lifecycle: Lifecycle, resolver: FixtureResolver, source: FakeStreamSource, **limits: Any
) -> tuple[FastAPI, Any]:
    mcp = FastAPI()

    @asynccontextmanager
    async def mcp_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        lifecycle.mcp_started += 1
        yield
        lifecycle.mcp_stopped += 1

    mcp.router.lifespan_context = mcp_lifespan

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Like bootstrap/technical_api.py: the MCP sub-app lifespan runs inside the API's.
        lifecycle.api_started += 1
        async with mcp.router.lifespan_context(mcp):
            yield
        lifecycle.api_stopped += 1

    app = FastAPI(lifespan=lifespan)
    app.mount("/mcp", mcp)
    settings = PumpSettings(page_size=50, poll_interval=0.05, slow_consumer_grace=0.5)
    config = MissionSocketConfig(
        allowed_origins=(ORIGIN,),
        limits=MissionSocketLimits(pump=settings, **limits),
    )
    asgi = mount_mission_socketio(app, config, resolver=resolver)
    getattr(app.state, STREAM_SERVICES)[(INSTALLATION, "biotech", TENANT)] = MissionStreamService(
        source, request_scope=SCOPE
    )
    return app, asgi


def auth(token: str, application_id: str = "biotech") -> dict[str, str]:
    return {"application_id": application_id, "token": token}

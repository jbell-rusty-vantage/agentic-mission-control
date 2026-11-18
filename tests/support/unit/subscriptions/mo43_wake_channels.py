"""Builders, constants and fakes that other test files import.

Moved from tests/unit/subscriptions/test_mo43_wake_channels.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
)
from mission_control.application.subscriptions.coordinator_service import (
    CoordinatorInboxService,
    CoordinatorSubscribeRequest,
)
from mission_control.application.subscriptions.service import SubscriptionService
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.cli import main as cli
from mission_control.interfaces.http.coordinator_inbox import router as inbox_router
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from mission_control.interfaces.http.missions import router as missions_router
from mission_control.interfaces.mcp.operator_server import (
    OPERATOR_MCP_PATH,
    BearerPrincipalGate,
    create_operator_server,
)
from tests.unit.subscriptions.coordinator_fakes import RUN, InMemoryInboxStore, journal_event

INSTALLATION = UUID("00000000-0000-7000-8000-0000000000aa")
TENANT = UUID("00000000-0000-7000-8000-0000000000bb")
KEY = (INSTALLATION, "biotech", TENANT)
READ = frozenset({"workflow_run.read"})
LAUNCHER = ActorContext(
    actor_id="coordinator-1", permissions=READ | {"workflow_run.start", "mission.start"}
)


async def run_inbox(service: CoordinatorInboxService, actor: ActorContext = LAUNCHER) -> UUID:
    created = await service.subscribe(
        CoordinatorSubscribeRequest(target="run", target_id=RUN, after_seq=0), actor
    )
    return created.subscription_id


def terminal(inbox: InMemoryInboxStore, seq: int = 2) -> None:
    inbox.add(journal_event(seq, "workflow_run.terminalize"), terminal_outcome="completed")


def _registry() -> ApplicationRegistry:
    registry = ApplicationRegistry(
        (
            ApplicationBinding.seal(
                application_id="biotech",
                installation_id=INSTALLATION,
                binding_version="1",
                supabase_project_ref="project",
                database_secret_ref="TEST_DATABASE_URL",
                accepted_issuers={"https://issuer.invalid"},
                accepted_audiences={"authenticated"},
                required_component_version="1",
            ),
        )
    )
    registry.observe(
        "biotech", InstallationObservation(INSTALLATION, "biotech", "project", frozenset({"1"}))
    )
    return registry


def _principal() -> MissionPrincipal:
    return MissionPrincipal(
        installation_id=INSTALLATION,
        application_id="biotech",
        tenant_id=TENANT,
        issuer="https://issuer.invalid",
        audiences=frozenset({"authenticated"}),
        actor=LAUNCHER,
    )


def inbox_app(service: CoordinatorInboxService, manifests: Any = None) -> FastAPI:
    app = FastAPI()
    app.include_router(inbox_router)
    app.include_router(missions_router)
    app.state.mission_control_registry = _registry()
    app.state.mission_control_coordinator_inbox_services = {KEY: service}
    app.state.mission_control_manifest_services = {KEY: manifests} if manifests else {}
    app.dependency_overrides[get_mission_principal] = _principal
    return app


@asynccontextmanager
async def operator_client(
    service: CoordinatorInboxService, token: str | None
) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    app = FastAPI()
    app.state.mission_control_registry = _registry()
    for name in (
        "transcript_services",
        "transcript_search_services",
        "run_list_services",
        "chain_services",
        "manifest_services",
        "services",
        "runtime_services",
        "human_task_services",
        "governed_effect_services",
    ):
        setattr(app.state, f"mission_control_{name}", {})
    app.state.mission_control_coordinator_inbox_services = {KEY: service}
    app.state.mission_control_subscription_services = {
        KEY: SubscriptionService(service._subscriptions)
    }

    def authenticate(application_id: str, authorization: str | None) -> MissionPrincipal:
        if authorization != "Bearer good":
            raise HTTPException(status_code=401, detail={"code": "bearer_token_required"})
        return _principal()

    mcp = create_operator_server(app.state).http_app(
        path="/", transport="streamable-http", stateless_http=True, json_response=True
    )
    app.mount(OPERATOR_MCP_PATH, BearerPrincipalGate(mcp, authenticate))
    headers = {"accept": "application/json, text/event-stream"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    async with (
        mcp.router.lifespan_context(mcp),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=headers
        ) as http,
    ):
        yield http, app


@pytest.fixture
def missionctl(monkeypatch: pytest.MonkeyPatch) -> Any:
    def bind(app: FastAPI) -> None:
        real_client = httpx.Client
        test_client = TestClient(app)

        class Bridge(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                response = test_client.request(
                    request.method,
                    str(request.url),
                    headers=dict(request.headers),
                    content=request.content,
                )
                return httpx.Response(
                    response.status_code, headers=response.headers, content=response.content
                )

        def factory(*args: Any, **kwargs: Any) -> httpx.Client:
            kwargs["transport"] = Bridge()
            return real_client(*args, **kwargs)

        monkeypatch.setattr(cli.httpx, "Client", factory)

    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "token")
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION_ID", "biotech")
    return bind

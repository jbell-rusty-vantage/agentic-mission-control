"""Builders, constants and fakes that other test files import.

Moved from tests/unit/frames/test_transcript_interfaces.py.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mission_control.application.frames.transcript import TranscriptService
from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from mission_control.interfaces.http.transcript import router
from tests.support.ids import INSTALLATION, SCOPE, TENANT
from tests.support.transcripts import (
    SECRET_VALUE,
    InMemoryMissionEvents,
    StaticFrames,
    transcript_events,
    transcript_frames,
)


def transcript_service() -> TranscriptService:
    frames = transcript_frames()
    return TranscriptService(
        InMemoryMissionEvents(transcript_events(frames)),
        StaticFrames(frames),  # type: ignore[arg-type]
        request_scope=SCOPE,
        secret_values=(SECRET_VALUE,),
    )


def http_app(permissions: frozenset[str] = frozenset({"workflow_run.read"})) -> FastAPI:
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
    app = FastAPI()
    app.include_router(router)
    app.state.mission_control_registry = registry
    app.state.mission_control_transcript_services = {
        (INSTALLATION, "biotech", TENANT): transcript_service()
    }
    app.dependency_overrides[get_mission_principal] = lambda: MissionPrincipal(
        installation_id=INSTALLATION,
        application_id="biotech",
        tenant_id=TENANT,
        issuer="https://issuer.invalid",
        audiences=frozenset({"authenticated"}),
        actor=ActorContext(actor_id="reader", permissions=permissions),
    )
    return app


def _cli_transport(app: FastAPI) -> Any:
    real_client = httpx.Client

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = _ASGIBridge(app)
        return real_client(*args, **kwargs)

    return factory


class _ASGIBridge(httpx.BaseTransport):
    """Synchronous transport into a FastAPI app through its TestClient."""

    def __init__(self, app: FastAPI) -> None:
        self._client = TestClient(app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._client.request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            content=request.content,
        )
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )

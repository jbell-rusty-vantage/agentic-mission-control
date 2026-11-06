"""The coordinator-facing model listing (OC-D201, OC-R6 / OVE-200).

`GET /v1/applications/{app}/models` and `missionctl model list|describe` return every Model
Profile with vendor, id, window, cost and each lane profile's route verdict; a lane profile
without a package registration is `unregistered`. `lane describe` carries `model_routes`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.application.resolution.model_listing import describe_model, list_models
from mission_control.application.resolution.registries import (
    LaneRegistry,
    ModelCatalog,
)
from mission_control.bootstrap.lanes import (
    SESSION_LANES,
    bound_lane_profiles,
    describe_only_registry,
)
from mission_control.domain.execution.lanes import LANE_PROFILES
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.cli.main import main as missionctl
from mission_control.interfaces.http import lanes as lanes_http
from mission_control.interfaces.http import models as models_http
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    get_mission_principal,
)
from tests.conformance.lanes.compile.stub import NARROW_DECLARATION
from tests.conformance.resolution.test_resolver_conformance import _registration
from tests.fixtures.models import checked_in_catalog


def _registry() -> LaneRegistry:
    """What the API publishes: Deep Agents' package registration, a bound Cursor lane without
    one (runtime-only describe), plus a narrow anthropic-only stub registration."""

    registry = describe_only_registry(
        bound=bound_lane_profiles(cursor=True),
        allow_unqualified=False,
        registrations=(deep_agents_lane(None),),
    )
    registry.register(_registration(NARROW_DECLARATION))
    return registry


def _app(catalog: ModelCatalog | None, registry: LaneRegistry) -> FastAPI:
    app = FastAPI()
    app.include_router(models_http.router)
    app.include_router(lanes_http.router)
    app.state.mission_control_lanes = registry
    app.state.mission_control_model_catalogs = {} if catalog is None else {"biotech": catalog}
    app.dependency_overrides[get_mission_principal] = lambda: MissionPrincipal(
        installation_id=uuid.uuid4(),
        application_id="biotech",
        tenant_id=uuid.uuid4(),
        issuer="https://issuer.invalid",
        audiences={"authenticated"},
        actor=ActorContext(actor_id="operator"),
    )
    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(models_http, "authorize_application", lambda *args: None)
    monkeypatch.setattr(lanes_http, "authorize_application", lambda *args: None)
    return TestClient(_app(checked_in_catalog(), _registry()))


def test_the_listing_reports_every_profile_with_each_lanes_route(client: TestClient) -> None:
    listed = client.get("/v1/applications/biotech/models")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["schema_version"] == "mc.model_listing.v1"
    rows = {row["profile"]: row for row in body["models"]}
    assert set(rows) == set(checked_in_catalog().profiles())
    producer = rows["producer.default"]
    assert {key: producer[key] for key in ("vendor", "model_id", "context_window_tokens")} == {
        "vendor": "anthropic",
        "model_id": "claude-sonnet-5-5",
        "context_window_tokens": 1_000_000,
    }
    assert (producer["cost_per_million_input"], producer["cost_per_million_output"]) == (2, 10)
    # Every lane profile of the vocabulary has a verdict; only package registrations decide.
    assert set(producer["routes"]) == set(LANE_PROFILES)
    assert producer["routes"]["deep_agents"] == "native"
    assert producer["routes"]["claude_agent_sdk"] == "native"  # the narrow stub registration
    assert producer["routes"]["cursor_local"] == "unregistered"  # runtime-only describe
    assert producer["routes"]["codex"] == "unbound"  # no credential bound: absent
    judge = rows["judge.default"]
    assert (judge["vendor"], judge["routes"]["claude_agent_sdk"]) == ("openai", "unsupported")


def test_describe_returns_each_lanes_mechanism_and_refuses_an_unknown_profile(
    client: TestClient,
) -> None:
    described = client.get("/v1/applications/biotech/models/judge.default")
    assert described.status_code == 200, described.text
    lanes = {row["lane_profile"]: row for row in described.json()["lanes"]}
    assert lanes["deep_agents"] == {
        "lane_profile": "deep_agents",
        "verdict": "native",
        "mechanism": "chat_openai_factory",
    }
    assert lanes["claude_agent_sdk"]["verdict"] == "unsupported"
    assert lanes["cursor_cloud"] == {
        "lane_profile": "cursor_cloud",
        "verdict": "unregistered",  # bound, runtime-only describe
        "mechanism": None,
    }
    missing = client.get("/v1/applications/biotech/models/frontier.default")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "model_profile_not_in_catalog"


def test_the_listing_is_unavailable_without_a_composed_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models_http, "authorize_application", lambda *args: None)
    unavailable = TestClient(_app(None, _registry())).get("/v1/applications/biotech/models")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "models_unavailable"


def test_lane_describe_carries_its_model_routes(client: TestClient) -> None:
    deep = client.get("/v1/applications/biotech/lanes/deep_agents").json()
    # W1 D16: each route lists the structured-output strategies the lane realizes.
    strategies = ["tool_forced", "provider_native", "tool_auto"]
    assert deep["model_routes"] == [
        {
            "vendor": "anthropic",
            "verdict": "native",
            "mechanism": "chat_anthropic_factory",
            "structured_output": strategies,
        },
        {
            "vendor": "openai",
            "verdict": "native",
            "mechanism": "chat_openai_factory",
            "structured_output": strategies,
        },
    ]
    # A runtime-only describe declares no routes this process can read.
    assert client.get("/v1/applications/biotech/lanes/cursor_local").json()["model_routes"] is None


def test_the_handler_is_the_same_projection_the_routes_serve() -> None:
    catalog, registry = checked_in_catalog(), _registry()
    listed = list_models(catalog, registry)
    assert [row.profile for row in listed.models] == sorted(catalog.profiles())
    assert (
        listed.models[0].routes
        == describe_model(catalog, registry, listed.models[0].profile).routes
    )


def test_missionctl_model_list_and_describe(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []
    listing = list_models(checked_in_catalog(), _registry()).model_dump(mode="json")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=listing)
        return httpx.Response(404, json={"detail": {"code": "model_profile_not_in_catalog"}})

    real_client = httpx.Client

    def client_factory(**kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "token-never-printed")
    assert missionctl(["model", "list", "--application", "biotech"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert {row["profile"] for row in printed["models"]} == set(checked_in_catalog().profiles())
    assert missionctl(["model", "describe", "unknown.default", "--application", "biotech"]) != 0
    assert seen == [
        "/v1/applications/biotech/models",
        "/v1/applications/biotech/models/unknown.default",
    ]
    assert "token-never-printed" not in capsys.readouterr().out


def test_an_installation_binding_only_deep_agents_lists_only_deep_agents() -> None:
    """OC-R3: every lane package is offered to the registry, but an unbound lane is absent from
    `lane list` and `unbound` in the model listing; only Deep Agents routes are reported."""

    registry = describe_only_registry(
        bound=bound_lane_profiles(),
        allow_unqualified=False,
        registrations=(deep_agents_lane(None), *SESSION_LANES.values()),
    )
    assert registry.profiles() == ("deep_agents",)
    (producer,) = [
        row
        for row in list_models(checked_in_catalog(), registry).models
        if row.profile == "producer.default"
    ]
    assert producer.routes["deep_agents"] == "native"
    assert {verdict for lane, verdict in producer.routes.items() if lane != "deep_agents"} == {
        "unbound"
    }


def test_a_bound_lane_package_is_listed_with_its_declared_routes() -> None:
    registry = describe_only_registry(
        bound=bound_lane_profiles(codex=True),
        allow_unqualified=False,
        registrations=(deep_agents_lane(None), *SESSION_LANES.values()),
    )
    assert registry.profiles() == ("codex", "codex_cloud", "deep_agents")
    (producer,) = [
        row
        for row in list_models(checked_in_catalog(), registry).models
        if row.profile == "producer.default"
    ]
    assert producer.routes["codex"] == "unsupported"  # an anthropic model on an OpenAI lane
    assert producer.routes["cursor_local"] == "unbound"

"""FT-E3: submit and start on HTTP, MCP and CLI map one handler with the same grants.

The lifecycle behind them is a deterministic fake; the persisted effects are proven in
tests/integration/postgres/test_manifest_submit.py.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    MissionManifestService,
    require_any,
)
from mission_control.application.authoring.manifest_submit import (
    START_GRANTS,
    SUBMIT_GRANTS,
    ManifestBlocked,
    ManifestIdempotencyConflict,
    ManifestStartReceipt,
    ManifestSubmissionReceipt,
    SubmitRequest,
    SubmittedMission,
)
from mission_control.contracts.contracts import MissionCommandRequest
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import ManifestErrorCode, ManifestIssue
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.cli import main as cli
from mission_control.interfaces.mcp.coordinator_server import (
    CoordinatorPrincipal,
    _call,
    _principal_call,
)
from mission_control.interfaces.mcp.mission_tools import (
    REQUEST_ID_NOT_UUID,
    START_TOOL,
    SUBMIT_TOOL,
    ScopedManifests,
    register_manifest_tools,
)
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.provider_frames import SCOPE
from tests.unit.authoring.test_manifest_compile import MINIMAL, http_app

MISSION_ID = UUID("01920000-0000-7000-8000-00000000a001")
REVISION_ID = UUID("01920000-0000-7000-8000-00000000a002")


def receipt(request_id: str, *, unchanged: bool = False) -> ManifestSubmissionReceipt:
    return ManifestSubmissionReceipt(
        request_id=request_id,
        manifest_digest="sha256:" + "a" * 64,
        unchanged=unchanged,
        missions=(
            SubmittedMission(
                mission_key="minimal-sweep",
                mission_id=MISSION_ID,
                revision_id=REVISION_ID,
                revision_no=1,
                family="StageGraph",
                effective_configuration_digest="sha256:" + "b" * 64,
                run_id="run-1",
            ),
        ),
    )


class FakeLifecycle:
    """Grants are enforced exactly as ``ManifestSubmitService`` enforces them."""

    request_scope = SCOPE

    def __init__(self) -> None:
        self.submitted: dict[str, str] = {}
        self.started: list[tuple[str, dict[str, Any] | None]] = []

    async def submit(self, request: SubmitRequest) -> tuple[ManifestSubmissionReceipt, bool]:
        require_any(request.actor.permissions, SUBMIT_GRANTS, "manifest submit")
        if "BLOCK" in request.manifest_yaml:
            raise ManifestBlocked(
                None,
                (
                    ManifestIssue(
                        code=ManifestErrorCode.INVALID_DEFINITION,
                        pointer="/mission",
                        message="blocked",
                    ),
                ),
            )
        key = str(request.request_id)
        prior = self.submitted.get(key)
        if prior is not None:
            if prior != request.manifest_yaml:
                raise ManifestIdempotencyConflict("conflict")
            return receipt(key), True
        self.submitted[key] = request.manifest_yaml
        return receipt(key, unchanged="UNCHANGED" in request.manifest_yaml), False

    async def start(
        self, run_id: str, actor: ActorContext, *, family_input: dict[str, Any] | None = None
    ) -> ManifestStartReceipt:
        require_any(actor.permissions, START_GRANTS, "run start")
        self.started.append((run_id, family_input))
        return ManifestStartReceipt(
            run_id=run_id,
            mission_id=MISSION_ID,
            family="StageGraph",
            workflow_id=f"wf:{run_id}",
            semantic_input_binding_ref="semantic-input:x",
            accepted_run_version=1,
        )

    async def head_run(self, mission_id: Any) -> str | None:
        return "run-1" if mission_id == MISSION_ID else None


async def manifests(lifecycle: FakeLifecycle) -> MissionManifestService:
    definitions, search = await fast_track_catalog()
    return MissionManifestService(
        compiler=ManifestCompileService(
            definitions=definitions,
            search=search,
            programs=ManifestProgramCompiler(
                definitions, ExtensionRegistry(), InMemoryPayloadStore()
            ),
        ),
        request_scope=SCOPE,
        lifecycle=lifecycle,  # type: ignore[arg-type]
    )


AUTHOR = frozenset({"workflow_run.admit", "workflow_run.start", "workflow_run.read"})


@pytest.mark.asyncio
async def test_http_submit_statuses_and_start_aliases() -> None:
    lifecycle = FakeLifecycle()
    client = TestClient(http_app(await manifests(lifecycle), AUTHOR))
    base = "/v1/applications/biotech"
    request_id = str(uuid4())
    created = client.post(
        f"{base}/missions:submit", json={"manifest_yaml": "m: 1", "request_id": request_id}
    )
    assert created.status_code == 201, created.text
    assert created.json()["missions"][0]["run_id"] == "run-1"
    replay = client.post(
        f"{base}/missions:submit", json={"manifest_yaml": "m: 1", "request_id": request_id}
    )
    assert replay.status_code == 200
    conflict = client.post(
        f"{base}/missions:submit", json={"manifest_yaml": "m: 2", "request_id": request_id}
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    unchanged = client.post(
        f"{base}/missions:submit", json={"manifest_yaml": "UNCHANGED", "request_id": str(uuid4())}
    )
    assert unchanged.status_code == 200 and unchanged.json()["unchanged"] is True
    blocked = client.post(
        f"{base}/missions:submit", json={"manifest_yaml": "BLOCK", "request_id": str(uuid4())}
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["blockers"][0]["code"] == "INVALID_DEFINITION"
    mismatch = client.post(
        f"{base}/missions:submit",
        json={"manifest_yaml": "m: 3", "request_id": str(uuid4())},
        headers={"Idempotency-Key": "other"},
    )
    assert mismatch.status_code == 409
    started = client.post(f"{base}/missions:start", json={"run_id": "run-1"})
    assert started.status_code == 202 and started.json()["workflow_id"] == "wf:run-1"
    head = client.post(f"{base}/missions/{MISSION_ID}/runs", json={})
    assert head.status_code == 202 and head.json()["run_id"] == "run-1"
    assert client.post(f"{base}/missions/{uuid4()}/runs", json={}).status_code == 404
    reader = TestClient(
        http_app(await manifests(FakeLifecycle()), frozenset({"workflow_run.read"}))
    )
    denied = reader.post(
        f"{base}/missions:submit", json={"manifest_yaml": "m", "request_id": str(uuid4())}
    )
    assert denied.status_code == 403
    assert reader.post(f"{base}/missions:start", json={"run_id": "run-1"}).status_code == 403


def principal(permissions: frozenset[str]) -> CoordinatorPrincipal:
    return CoordinatorPrincipal(
        actor_id="coordinator",
        tenant_scope=SCOPE,
        roles=frozenset(),
        permissions=permissions,
        request_scope=SCOPE,
    )


class Principals:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.permissions = permissions

    async def resolve(self, context: Any) -> CoordinatorPrincipal:
        del context
        return principal(self.permissions)


@pytest.mark.asyncio
async def test_mcp_submit_and_start_are_consequential_and_need_their_grants() -> None:
    for permissions, allowed in (
        (frozenset({"mission.author", "mission.start"}), True),
        (frozenset({"workflow_run.read", "catalog.read"}), False),
    ):
        lifecycle = FakeLifecycle()
        server = FastMCP("manifest-lifecycle-test")
        register_manifest_tools(
            server,
            ScopedManifests(
                {SCOPE: await manifests(lifecycle)},
                sponsorship_refs=frozenset({"sponsorship:coordinator"}),
            ),
            Principals(permissions),
            call=_principal_call,
        )
        for name in (SUBMIT_TOOL, START_TOOL):
            tool = await server.get_tool(name)
            assert tool is not None and "consequential" in tool.tags
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            for name in (SUBMIT_TOOL, START_TOOL):
                annotations = tools[name].annotations
                assert annotations is not None and annotations.readOnlyHint is False
            submitted = await client.call_tool(
                SUBMIT_TOOL, {"manifest_yaml": "m: 1", "request_id": str(uuid4())}
            )
            started = await client.call_tool(START_TOOL, {"run_id": "run-1"})
            for result in (submitted, started):
                envelope = result.structured_content
                assert envelope is not None and envelope["ok"] is allowed
                if not allowed:
                    assert envelope["error"]["code"] == "FORBIDDEN"
            if allowed:
                assert submitted.structured_content["data"]["replayed"] is False  # type: ignore[index]
                assert lifecycle.started == [("run-1", None)]


def test_cli_submit_and_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    lifecycle = FakeLifecycle()
    app = http_app(asyncio.run(manifests(lifecycle)), AUTHOR)
    real_client = httpx.Client

    class Bridge(httpx.BaseTransport):
        def __init__(self) -> None:
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

    def factory(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = Bridge()
        return real_client(*args, **kwargs)

    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "token")
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION_ID", "biotech")
    monkeypatch.setattr(cli.httpx, "Client", factory)
    request_id = str(uuid4())
    assert cli.main(["mission", "submit", str(MINIMAL), "--request-id", request_id]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["request_id"] == request_id
    blocked = tmp_path / "blocked.yml"
    blocked.write_text("BLOCK", encoding="utf-8")
    assert cli.main(["mission", "submit", str(blocked)]) == 2
    capsys.readouterr()
    other = tmp_path / "other.yml"
    other.write_text("changed", encoding="utf-8")
    assert cli.main(["mission", "submit", str(other), "--request-id", request_id]) == 4
    capsys.readouterr()
    family = tmp_path / "family.json"
    family.write_text(json.dumps({"run_id": "run-1"}), encoding="utf-8")
    assert cli.main(["mission", "start", "run-1", "--request-file", str(family)]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["workflow_id"] == "wf:run-1"
    assert lifecycle.started[-1] == ("run-1", {"run_id": "run-1"})
    # A request id that is not a UUID is refused before any request, in words that say so.
    admitted = len(lifecycle.submitted)
    assert cli.main(["mission", "submit", str(MINIMAL), "--request-id", "proof-1"]) == 2
    refused = json.loads(capsys.readouterr().err)
    assert refused["error"].startswith("--request-id must be a UUID (for example ")
    assert len(lifecycle.submitted) == admitted
    assert cli.request_uuid(request_id) == request_id
    assert str(UUID(cli.request_uuid(None))) != request_id


@pytest.mark.asyncio
async def test_a_submit_request_id_is_published_as_a_uuid_and_refused_in_those_words() -> None:
    lifecycle = FakeLifecycle()
    # HTTP: the body model publishes the format and its refusal names the field.
    app = http_app(await manifests(lifecycle), AUTHOR)
    published = app.openapi()["components"]["schemas"]["SubmitBody"]["properties"]["request_id"]
    assert (published["type"], published["format"]) == ("string", "uuid")
    over_http = TestClient(app).post(
        "/v1/applications/biotech/missions:submit",
        json={"manifest_yaml": "m: 1", "request_id": "proof-1"},
    )
    assert over_http.status_code == 422
    (detail,) = over_http.json()["detail"]
    assert detail["loc"] == ["body", "request_id"] and "valid UUID" in detail["msg"]
    # MCP: the same format in `tools/list`, and the envelope says what to send.
    server = FastMCP("manifest-request-id-test")
    register_manifest_tools(
        server,
        ScopedManifests({SCOPE: await manifests(lifecycle)}),
        Principals(frozenset({"mission.author", "mission.start"})),
        call=_principal_call,
    )
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert tools[SUBMIT_TOOL].inputSchema["properties"]["request_id"] == {
            "format": "uuid",
            "type": "string",
        }
        assert "`request_id` is a UUID you choose" in (tools[SUBMIT_TOOL].description or "")
        refused = await client.call_tool(
            SUBMIT_TOOL, {"manifest_yaml": "m: 1", "request_id": "proof-1"}
        )
    envelope = refused.structured_content
    assert envelope is not None and envelope["ok"] is False
    error = envelope["error"]
    assert (error["code"], error["message"]) == ("INVALID_ARGUMENT", REQUEST_ID_NOT_UUID)
    assert error["details"] == {"argument": "request_id", "expected": "uuid"}
    assert REQUEST_ID_NOT_UUID.startswith("request_id must be a UUID (for example ")
    assert lifecycle.submitted == {}


@pytest.mark.asyncio
async def test_a_request_model_that_refuses_a_request_id_names_the_field() -> None:
    async def command() -> object:
        return MissionCommandRequest.model_validate(
            {
                "request_id": "proof run superseded",
                "expected_version": 9,
                "expected_generation": 1,
                "target": {"kind": "run", "id": "run-1"},
                "kind": "cancel",
                "payload": {"urgency": "normal"},
                "reason": "proof run superseded",
            }
        )

    async def other() -> object:
        return MissionCommandRequest.model_validate({"request_id": str(uuid4())})

    refused = await _call(command)
    assert refused["error"] == {
        "code": "INVALID_ARGUMENT",
        "message": "request arguments are invalid: request_id must be a UUID",
        "retryable": False,
        "details": {"argument": "request_id", "expected": "uuid"},
    }
    # Any other refusal keeps its one line and echoes nothing the caller wrote.
    assert (await _call(other))["error"] == {
        "code": "INVALID_ARGUMENT",
        "message": "request arguments are invalid",
        "retryable": False,
        "details": {},
    }

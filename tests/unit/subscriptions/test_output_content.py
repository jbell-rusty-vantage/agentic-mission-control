"""The text of one promised output, read without a notification (the bounded content read).

`OutputInspectionService.content` reuses the reader behind the coordinator inbox's content
retrieval (`NoticeContentService`): the exact accepted revision, the same grant
(`workflow.result.read`), digest check, budgets and typed omissions. Where a promise has no
accepted revision yet, it answers the latest finalized submitted one and says so. HTTP,
`missionctl outputs content` and the operator MCP tool return the same document. FIXTURE
stores, in-process ASGI; no network, no model.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, Context, FastMCP

from mission_control.application.outputs.inspection import (
    InspectionRejected,
    OutputInspectionService,
)
from mission_control.application.subscriptions.notice_content import NoticeContentService
from mission_control.contracts.contracts import RunCostView
from mission_control.domain.outputs.contracts import ExactOutput
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.cli import main as cli
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    get_mission_principal,
)
from mission_control.interfaces.http.output_inspection import router as outputs_router
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal, _call
from mission_control.interfaces.mcp.subscriptions import (
    OUTPUT_CONTENT_TOOL,
    McpSessionHub,
    McpSubscriptionBridge,
    register_subscription_tools,
)
from tests.support.unit.subscriptions.attention_surfaces import FakeReader
from tests.support.unit.subscriptions.coordinator_attention import Outputs, output
from tests.support.unit.subscriptions.inbox_wake_channels import (
    INSTALLATION,
    KEY,
    TENANT,
    _registry,
    missionctl,  # noqa: F401
)
from tests.unit.subscriptions.coordinator_fakes import RUN
from tests.unit.subscriptions.fakes import SCOPE

KEY_NAME = "report.summary"
TEXT = "A Mission Manifest declares goals. It is compiled, submitted and started. " * 4
READ = frozenset({"workflow_run.read"})
READER = ActorContext(actor_id="coordinator-1", permissions=READ | {"workflow.result.read"})


class Finalized:
    """FIXTURE: the finalized submitted revisions of the run, oldest first."""

    def __init__(self, *items: ExactOutput) -> None:
        self.items = items

    async def finalized_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        return self.items


class Cost:
    async def run_cost(self, request_scope: str, run_id: str) -> RunCostView:
        return RunCostView(
            disposition="estimated",
            estimated_micros=1_872,
            estimated_usd="0.001872",
            model_calls=2,
            input_tokens=14_143,
            output_tokens=915,
        )


def service(
    *accepted: ExactOutput, submitted: tuple[ExactOutput, ...] = (), composed: bool = True
) -> OutputInspectionService:
    return OutputInspectionService(
        FakeReader(),  # type: ignore[arg-type]
        request_scope=SCOPE,
        content=NoticeContentService(Outputs(*accepted)) if composed else None,
        submitted=Finalized(*submitted),
        cost=Cost(),
    )


async def test_the_accepted_revision_is_read_bounded_and_exact() -> None:
    accepted = output(KEY_NAME, TEXT)
    read = await service(accepted).content(str(RUN), KEY_NAME, READER, max_chars=60)

    assert read.schema_version == "mc.output_content.v1" and read.status == "accepted"
    (excerpt,) = read.content.excerpts
    assert excerpt.excerpt == TEXT[:60] and excerpt.truncated is True
    assert excerpt.source_chars == len(TEXT) and excerpt.status == "accepted"
    assert excerpt.revision_id == accepted.revision_id
    assert excerpt.content_digest == accepted.content_digest
    assert read.content.purpose == "coordinator_review"
    whole = await service(accepted).content(str(RUN), KEY_NAME, READER)
    assert whole.content.excerpts[0].excerpt == TEXT and not whole.content.excerpts[0].truncated


async def test_a_promise_without_an_accepted_revision_answers_the_latest_submitted() -> None:
    older = output(KEY_NAME, "first draft", revision=1)
    newer = output(KEY_NAME, "second draft", revision=2)
    other = output("report.sources", "another promise", revision=5)

    read = await service(submitted=(older, newer, other)).content(str(RUN), KEY_NAME, READER)
    nothing = await service().content(str(RUN), KEY_NAME, READER)

    assert read.status == "submitted"
    assert [item.excerpt for item in read.content.excerpts] == ["second draft"]
    assert read.content.excerpts[0].status == "submitted"
    assert nothing.status == "none" and nothing.content.excerpts == ()
    assert [item.code for item in nothing.content.omissions] == ["NO_ACCEPTED_REVISION"]


async def test_a_content_whose_digest_does_not_match_is_an_omission_never_a_substitute() -> None:
    tampered = output(KEY_NAME, TEXT, digest="sha256:" + "0" * 64)

    read = await service(tampered).content(str(RUN), KEY_NAME, READER)

    assert read.status == "accepted" and read.content.excerpts == ()
    assert [item.code for item in read.content.omissions] == ["DIGEST_MISMATCH"]


async def test_the_refusals_name_what_was_required() -> None:
    composed = service(output(KEY_NAME, TEXT))

    with pytest.raises(InspectionRejected) as no_grant:
        await composed.content(
            str(RUN), KEY_NAME, ActorContext(actor_id="reader", permissions=READ)
        )
    with pytest.raises(InspectionRejected) as no_read:
        await composed.content(
            str(RUN),
            KEY_NAME,
            ActorContext(actor_id="reader", permissions=frozenset({"workflow.result.read"})),
        )
    with pytest.raises(InspectionRejected) as unknown:
        await composed.content(str(RUN), "report.nothing", READER)
    with pytest.raises(InspectionRejected) as too_long:
        await composed.content(str(RUN), KEY_NAME, READER, max_chars=8_001)
    with pytest.raises(InspectionRejected) as uncomposed:
        await service(composed=False).content(str(RUN), KEY_NAME, READER)

    assert no_grant.value.code == "unauthorized" and "workflow.result.read" in str(no_grant.value)
    assert no_read.value.code == "unauthorized" and "workflow_run.read" in str(no_read.value)
    assert unknown.value.code == "not_found" and "it promises: report.summary" in str(unknown.value)
    assert too_long.value.code == "invalid" and "1..8000" in str(too_long.value)
    assert uncomposed.value.code == "unavailable"


async def test_outputs_report_the_runs_estimated_cost() -> None:
    view = await service(output(KEY_NAME, TEXT)).outputs(str(RUN), READER)
    plain = await OutputInspectionService(FakeReader(), request_scope=SCOPE).outputs(  # type: ignore[arg-type]
        str(RUN), READER
    )

    assert view.cost is not None and view.cost.estimated_micros == 1_872
    assert view.model_dump(mode="json")["cost"]["estimated_usd"] == "0.001872"
    # Without a price source the section is left out of the document.
    assert "cost" not in plain.model_dump(mode="json")


# ---------------------------------------------------------------- transports


def _principal() -> MissionPrincipal:
    return MissionPrincipal(
        installation_id=INSTALLATION,
        application_id="biotech",
        tenant_id=TENANT,
        issuer="https://issuer.invalid",
        audiences=frozenset({"authenticated"}),
        actor=READER,
    )


def outputs_app(inspection: OutputInspectionService) -> FastAPI:
    app = FastAPI()
    app.include_router(outputs_router)
    app.state.mission_control_registry = _registry()
    app.state.mission_control_output_inspection_services = {KEY: inspection}
    app.dependency_overrides[get_mission_principal] = _principal
    return app


class _Resolver:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.principal = CoordinatorPrincipal(
            actor_id="coordinator-1",
            tenant_scope=SCOPE,
            roles=frozenset(),
            permissions=permissions,
            request_scope=SCOPE,
        )

    async def resolve(self, _context: Context) -> CoordinatorPrincipal:
        return self.principal


def _server(inspection: OutputInspectionService, permissions: frozenset[str]) -> FastMCP:
    server = FastMCP("outputs test")
    register_subscription_tools(
        server,
        McpSubscriptionBridge({}, McpSessionHub(), inspections={SCOPE: inspection}),
        _Resolver(permissions).resolve,
        _call,
        session_push=False,
    )
    return server


async def test_http_missionctl_and_mcp_return_one_document(
    missionctl: Any,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inspection = service(output(KEY_NAME, TEXT))
    app = outputs_app(inspection)
    path = f"/v1/applications/biotech/runs/{RUN}/outputs/{KEY_NAME}/content"

    from_http = TestClient(app).get(path, params={"max_chars": 80})
    assert from_http.status_code == 200, from_http.text
    document = from_http.json()
    assert document["status"] == "accepted" and document["application_id"] == "biotech"
    assert document["content"]["excerpts"][0]["excerpt"] == TEXT[:80]

    missionctl(app)
    assert cli.main(["outputs", "content", str(RUN), KEY_NAME, "--max-chars", "80"]) == 0
    assert json.loads(capsys.readouterr().out) == document

    async with Client(_server(inspection, READER.permissions)) as mcp:
        tools = {tool.name for tool in await mcp.list_tools()}
        from_mcp = await mcp.call_tool(
            OUTPUT_CONTENT_TOOL,
            {"run_id": str(RUN), "obligation_key": KEY_NAME, "max_chars": 80},
        )
        refused = await mcp.call_tool(
            OUTPUT_CONTENT_TOOL, {"run_id": str(RUN), "obligation_key": "report.nothing"}
        )
    async with Client(_server(inspection, READ)) as mcp:
        ungranted = await mcp.call_tool(
            OUTPUT_CONTENT_TOOL, {"run_id": str(RUN), "obligation_key": KEY_NAME}
        )

    assert OUTPUT_CONTENT_TOOL in tools
    envelope = from_mcp.structured_content
    assert envelope is not None and envelope["ok"] is True
    assert envelope["data"] == {k: v for k, v in document.items() if k != "application_id"}
    assert refused.structured_content["error"]["code"] == "NOT_FOUND"  # type: ignore[index]
    assert ungranted.structured_content["error"]["code"] == "FORBIDDEN"  # type: ignore[index]
    assert "workflow.result.read" in ungranted.structured_content["error"]["message"]  # type: ignore[index]

    # The route's own typed refusals.
    client = TestClient(app)
    assert client.get(path.replace(KEY_NAME, "report.nothing")).status_code == 404
    assert client.get(path, params={"max_chars": 9_000}).status_code == 422
    unavailable = TestClient(outputs_app(service(composed=False))).get(path)
    assert unavailable.status_code == 503 and unavailable.json()["detail"]["code"] == "unavailable"

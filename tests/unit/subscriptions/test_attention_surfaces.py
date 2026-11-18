"""WI-19 / OVE-182: the attention and inspection surfaces agree across HTTP, missionctl and the
operator MCP (FIXTURE stores, in-process ASGI; no network, no model).

The missionctl walk is the deterministic rehearsal of the C14 host procedure
(`docs/knowledge/coordinator-attention.md`): wait (transport) -> report wake -> report visible
with the printed digest -> ack -> retrieve -> attention. A test reporting host stages is not
the selected host: it proves the commands and the server rules, not a real idle wake.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mission_control.application.outputs.inspection import (
    OutputInspectionService,
)
from mission_control.application.subscriptions.coordinator_service import (
    CoordinatorInboxService,
    CoordinatorSubscribeRequest,
)
from mission_control.interfaces.cli import main as cli
from mission_control.interfaces.http.mission_control import get_mission_principal
from mission_control.interfaces.http.output_inspection import router as outputs_router
from mission_control.interfaces.mcp.coordinator_http_client import (
    CoordinatorStreamableHttpClient,
)
from tests.support.unit.subscriptions.attention_surfaces import FakeReader
from tests.support.unit.subscriptions.inbox_wake_channels import (
    KEY,
    LAUNCHER,
    _principal,
    _registry,
    inbox_app,
    missionctl,  # noqa: F401
    operator_client,
    run_inbox,
    terminal,
)
from tests.unit.subscriptions.coordinator_fakes import (
    RUN,
    InMemoryAttentionStore,
    InMemoryInboxStore,
    journal_event,
)
from tests.unit.subscriptions.fakes import SCOPE, InMemoryStore


def attention_service() -> tuple[CoordinatorInboxService, InMemoryInboxStore]:
    subscriptions = InMemoryStore()
    inbox = InMemoryInboxStore(subscriptions)
    service = CoordinatorInboxService(
        subscriptions,
        inbox,
        wait_interval=0.05,
        attention=InMemoryAttentionStore(inbox),
        outputs=_NoOutputs(),
    )
    return service, inbox


class _NoOutputs:
    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[Any, ...]:
        return ()


async def test_missionctl_records_each_stage_separately(
    missionctl: Any,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    service, inbox = attention_service()
    missionctl(inbox_app(service))
    # The coordinator declared its content purpose when subscribing (S4).
    created = await service.subscribe(
        CoordinatorSubscribeRequest.model_validate(
            {
                "target": "run",
                "target_id": str(RUN),
                "after_seq": 0,
                "profile": {"content": {"purpose": "coordinator_review"}},
            }
        ),
        LAUNCHER,
    )
    sid = str(created.subscription_id)
    inbox.add(
        journal_event(2, "output.fulfilled"),
        obligation_key="report.summary",
        disposition="fulfilled",
        enforcement="required",
    )
    assert cli.main(["wait", "--inbox", sid, "--kinds", "accepted_output"]) == 0
    line = json.loads(capsys.readouterr().out.splitlines()[0])
    nid, nonce = line["notification_id"], line["delivery_nonce"]
    assert "notice_digest" not in line
    now = datetime.now(UTC)
    common = ["inbox", "observe", sid, "--id", nid, "--nonce", nonce]
    # A wake without --idle-since is refused locally (exit 2), nothing is recorded.
    assert cli.main([*common, "--stage", "wake"]) == 2
    capsys.readouterr()
    idle = (now - timedelta(minutes=2)).isoformat()
    assert (
        cli.main([*common, "--stage", "wake", "--idle-since", idle, "--evidence", "task=bg-1"]) == 0
    )
    woke = json.loads(capsys.readouterr().out)
    assert woke["stage"] == "wake" and woke["replay"] is False
    # A nonce the delivery did not carry is refused by the server.
    wrong = ["inbox", "observe", sid, "--id", nid, "--nonce", "f" * 32, "--stage", "visible"]
    assert cli.main(wrong) != 0
    assert "delivery_nonce_unknown" in capsys.readouterr().out
    assert cli.main([*common, "--stage", "visible"]) == 0
    assert json.loads(capsys.readouterr().out)["claim"]["codes"] == [
        "ACK_UNOBSERVED",
        "RETRIEVAL_UNOBSERVED",
    ]
    assert cli.main(["inbox", "ack", sid, "--id", nid]) == 0
    capsys.readouterr()
    # The launcher holds no result-body grant: the retrieval is recorded, every promise omitted.
    assert cli.main(["inbox", "content", sid, "--id", nid, "--obligation", "report.summary"]) == 0
    content = json.loads(capsys.readouterr().out)["content"]
    assert content["excerpts"] == [] and content["omissions"][0]["code"] == "GRANT_MISSING"
    assert content["purpose"] == "coordinator_review"
    assert cli.main(["inbox", "attention", sid]) == 0
    attention_out = capsys.readouterr().out
    assert nonce not in attention_out
    (claim,) = json.loads(attention_out)["claims"]
    assert claim["codes"] == ["RETRIEVAL_UNOBSERVED"] and claim["verdict"] == "blocked"
    observed = {view["stage"]: view for view in claim["stages"]}
    assert observed["transport"]["channels"] == ["http"]
    assert observed["wake"]["channels"] == ["background_task_exit"]
    assert cli.main(["inbox", "list", "--run", str(RUN)]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] == "recorded"


async def test_operator_mcp_offers_attention_tools_and_records_mcp_transport() -> None:
    service, inbox = attention_service()
    path = "/v1/applications/biotech/mcp/"
    async with operator_client(service, "good") as (http, _app):
        client = CoordinatorStreamableHttpClient(http, path)
        await client.initialize()
        names = {tool.name for tool in await client.list_tools()}
        assert {
            "coordinator_inbox_observe",
            "coordinator_inbox_content",
            "coordinator_inbox_attention",
        } <= names
        assert "mission_run_outputs" not in names  # no inspection service composed here
        sid = await run_inbox(service)
        terminal(inbox)
        waited = await client.call_tool(
            "coordinator_inbox_wait", {"subscription_id": str(sid), "wait_seconds": 1}
        )
        page = waited.data["data"]
        (notice,) = page["notifications"]
        nonce = page["delivery_nonces"][notice["notification_id"]]
        at = datetime.now(UTC)
        for stage, channel in (("wake", "connected_poll"), ("visible", "tool_result")):
            observation: dict[str, Any] = {
                "stage": stage,
                "channel": channel,
                "observation_key": f"{stage}-1",
                "delivery_nonce": nonce,
                "observed_at": at.isoformat(),
                "host_ref": "claude-code:fixture",
            }
            if stage == "wake":
                observation["idle_since"] = (at - timedelta(seconds=30)).isoformat()
            seen = await client.call_tool(
                "coordinator_inbox_observe",
                {
                    "subscription_id": str(sid),
                    "notification_id": notice["notification_id"],
                    "observation": observation,
                },
            )
            assert seen.data["ok"] is True, seen.data
        report = await client.call_tool(
            "coordinator_inbox_attention", {"subscription_id": str(sid)}
        )
        (claim,) = report.data["data"]["claims"]
        stages = {view["stage"]: view for view in claim["stages"]}
        assert stages["transport"]["channels"] == ["mcp"] and stages["visible"]["observed"]
        # The MCP host was in a turn: a connected poll is not an idle wake.
        assert "IDLE_WAKE_UNAVAILABLE" in claim["codes"]


# ---------------------------------------------------------------- output inspection


def outputs_app() -> FastAPI:
    app = FastAPI()
    app.include_router(outputs_router)
    app.state.mission_control_registry = _registry()
    app.state.mission_control_output_inspection_services = {
        KEY: OutputInspectionService(FakeReader(), request_scope=SCOPE)
    }
    app.dependency_overrides[get_mission_principal] = _principal
    return app


def test_output_inspection_http_and_missionctl_agree(
    missionctl: Any,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = outputs_app()
    client = TestClient(app)
    base = f"/v1/applications/biotech/runs/{RUN}"
    view = client.get(f"{base}/outputs").json()
    assert view["schema_version"] == "mc.run_outputs.v1"
    assert {item["code"] for item in view["actionable"]} == {
        "OBLIGATION_UNMET",
        "ASSESSMENT_HELD",
        "INPUT_DELIVERY_REFUSED",
    }
    first = client.get(f"{base}/outputs/report.summary/revisions", params={"limit": 1}).json()
    assert [item["revision"] for item in first["revisions"]] == [1] and first["next_cursor"]
    rest = client.get(
        f"{base}/outputs/report.summary/revisions", params={"cursor": first["next_cursor"]}
    ).json()
    assert [item["revision"] for item in rest["revisions"]] == [2]
    assert (
        client.get(
            f"{base}/outputs/report.summary/revisions", params={"cursor": "bogus"}
        ).status_code
        == 422
    )
    assert client.get("/v1/applications/biotech/runs/not-a-run/outputs").status_code == 422
    missing = client.get("/v1/applications/biotech/transfer-plans/" + str(uuid4()))
    assert missing.status_code == 404
    missionctl(app)
    assert cli.main(["outputs", "show", str(RUN)]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == str(RUN)
    assert cli.main(["outputs", "events", str(RUN), "--limit", "2"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert len(events["events"]) == 2 and events["next_cursor"]
    assert cli.main(["outputs", "events", str(RUN), "--cursor", events["next_cursor"]]) == 0
    assert [item["ref"] for item in json.loads(capsys.readouterr().out)["events"]] == ["e-2"]
    assert cli.main(["outputs", "plan", "00000000-0000-4000-8000-0000000000aa"]) == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["summary"]["latest_receipt"]["result"] == "refused"
    assert cli.main(["outputs", "plans", str(RUN)]) == 0
    assert len(json.loads(capsys.readouterr().out)["transfer_plans"]) == 1

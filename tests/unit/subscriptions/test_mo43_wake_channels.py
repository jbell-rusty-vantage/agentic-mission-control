"""MO-43 (SPEC-04 §6): wake channels over the one durable coordinator inbox.

The inbox wait (service, HTTP ``?wait=``, MCP ``coordinator_inbox_wait``, ``missionctl wait``),
the launcher's auto-subscribe, the authenticated operator MCP gate and the ``payload: summary``
webhook body, over FIXTURE stores (`coordinator_fakes`). The real stack proof (local PostgreSQL
and Temporal, a background ``missionctl wait`` woken by ``run.completed``) is
`tests/acceptance/mission_control/test_wake_channels.py`.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from mission_control.application.authoring.manifest_service import MissionManifestService
from mission_control.application.subscriptions.coordinator import (
    NotificationKind,
    render_prompt,
    render_summary,
)
from mission_control.application.subscriptions.coordinator_service import (
    MAX_WAIT_SECONDS,
    CoordinatorInboxService,
    CoordinatorRejected,
    CoordinatorSubscribeRequest,
)
from mission_control.application.subscriptions.launcher import subscribe_launcher
from mission_control.application.subscriptions.service import SubscriptionService
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.subscriptions.contracts import (
    StreamTicketChannel,
    SubscriptionState,
)
from mission_control.interfaces.cli import main as cli
from mission_control.interfaces.mcp.coordinator_http_client import CoordinatorStreamableHttpClient
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal, _principal_call
from mission_control.interfaces.mcp.mission_tools import (
    START_TOOL,
    ScopedManifests,
    register_manifest_tools,
)
from mission_control.interfaces.mcp.subscriptions import (
    SUBSCRIBE_TOOL,
    WAIT_TOOL,
    McpSessionHub,
    McpSubscriptionBridge,
)
from tests.support.manifests.interfaces import FakeLifecycle
from tests.support.unit.coordinator.coordinator_mcp_read_surface import FakeFacade
from tests.support.unit.subscriptions.mo43_wake_channels import (
    LAUNCHER,
    READ,
    inbox_app,
    missionctl,  # noqa: F401
    operator_client,
    run_inbox,
    terminal,
)
from tests.unit.subscriptions.coordinator_fakes import (
    MISSION,
    RUN,
    InMemoryAttentionStore,
    InMemoryInboxStore,
    journal_event,
)
from tests.unit.subscriptions.fakes import SCOPE, FakeWebhook, InMemoryStore, StaticSecrets

OTHER = ActorContext(actor_id="someone-else", permissions=READ)


class FakeTime:
    """Monotonic seconds and an asyncio.sleep stand-in that may land events while asleep."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.on_sleep: list[Any] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep.pop(0)()


def compose(*, page: int = 200) -> tuple[CoordinatorInboxService, InMemoryInboxStore, FakeTime]:
    subscriptions = InMemoryStore()
    inbox = InMemoryInboxStore(subscriptions)
    clock = FakeTime()
    service = CoordinatorInboxService(
        subscriptions,
        inbox,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        page=page,
    )
    return service, inbox, clock


# -- the application service ------------------------------------------------------------------


async def test_wait_returns_at_once_when_a_matching_notification_is_pending() -> None:
    service, inbox, clock = compose()
    sid = await run_inbox(service)
    terminal(inbox)
    page = await service.wait(sid, LAUNCHER, timeout_seconds=30, kinds={"terminal_result"})  # type: ignore[arg-type]
    assert [item.kind for item in page.notifications] == [NotificationKind.TERMINAL_RESULT]
    (notification,) = page.notifications
    assert notification.events[0].event_type == "run.completed"
    assert notification.facts == {"terminal_outcome": "completed"}
    assert clock.sleeps == []


async def test_wait_sleeps_until_the_terminal_event_is_committed_and_never_acknowledges() -> None:
    service, inbox, clock = compose()
    sid = await run_inbox(service)
    clock.on_sleep = [lambda: None, lambda: terminal(inbox)]
    page = await service.wait(sid, LAUNCHER, timeout_seconds=30)
    assert [item.kind for item in page.notifications] == [NotificationKind.TERMINAL_RESULT]
    assert clock.sleeps == [1.0, 1.0]
    assert page.acked_inbox_seq == 0
    again = await service.poll(sid, LAUNCHER)
    assert again.notifications == page.notifications  # acknowledgement stays explicit


async def test_wait_returns_an_empty_page_at_the_deadline() -> None:
    service, _inbox, clock = compose()
    sid = await run_inbox(service)
    page = await service.wait(sid, LAUNCHER, timeout_seconds=2.5)
    assert page.notifications == () and page.has_more is False
    assert clock.sleeps == [1.0, 1.0, 0.5]
    with pytest.raises(CoordinatorRejected) as refused:
        await service.wait(sid, LAUNCHER, timeout_seconds=MAX_WAIT_SECONDS + 1)
    assert refused.value.code == "invalid"


async def test_kinds_filter_skips_other_kinds_across_store_pages() -> None:
    service, inbox, _clock = compose(page=2)
    sid = await run_inbox(service)
    for seq in range(1, 6):
        inbox.add(journal_event(seq, "human_task.created"), human_task_id=f"t-{seq}")
    terminal(inbox, seq=6)
    page = await service.wait(
        sid, LAUNCHER, timeout_seconds=0, kinds={NotificationKind.TERMINAL_RESULT}
    )
    assert [item.inbox_seq for item in page.notifications] == [6]
    everything = await service.poll(sid, LAUNCHER, limit=10)
    assert len(everything.notifications) == 6  # the reviews stay pending for whoever reads them


async def test_inboxes_lists_only_the_actors_open_inboxes_on_the_target() -> None:
    service, inbox, _clock = compose()
    mine = await run_inbox(service)
    await run_inbox(service, OTHER)
    closed = await run_inbox(service)
    await service.close(closed, LAUNCHER)
    on_mission = await service.subscribe(
        CoordinatorSubscribeRequest(target="mission", target_id=MISSION), LAUNCHER
    )
    # An ordinary stream subscription of the same actor is not an inbox.
    raw = await SubscriptionService(inbox.subscriptions).subscribe(_raw_request(), LAUNCHER)
    assert isinstance(raw.channel, StreamTicketChannel)
    found = await service.inboxes(LAUNCHER, target="run", target_id=RUN)
    assert [item.subscription_id for item in found] == [mine]
    missions = await service.inboxes(LAUNCHER, target="mission", target_id=MISSION)
    assert [item.subscription_id for item in missions] == [on_mission.subscription_id]
    with pytest.raises(CoordinatorRejected) as absent:
        await service.inboxes(LAUNCHER, target="run", target_id=uuid4())
    assert absent.value.code == "not_found"


def _raw_request() -> Any:
    from mission_control.domain.subscriptions.contracts import SubscriptionRequest

    return SubscriptionRequest(
        target="run",
        target_id=RUN,
        events=("run.completed",),
        channel=StreamTicketChannel(ticket_id="client-ticket"),
    )


async def test_launcher_is_subscribed_once_and_can_opt_out() -> None:
    service, inbox, _clock = compose()
    first = await subscribe_launcher(service, str(RUN), LAUNCHER)
    assert first.status == "subscribed" and first.subscription_id is not None
    again = await subscribe_launcher(service, str(RUN), LAUNCHER)
    assert again.status == "existing" and again.subscription_id == first.subscription_id
    assert (await subscribe_launcher(service, str(RUN), LAUNCHER, notify="none")).status == "off"
    absent = await subscribe_launcher(None, str(RUN), LAUNCHER)
    assert absent.status == "unavailable" and absent.subscription_id is None
    assert (await subscribe_launcher(service, "run-1", LAUNCHER)).reason == (
        "the run id is not a run uuid"
    )
    blind = ActorContext(actor_id="starter", permissions=frozenset({"workflow_run.start"}))
    refused = await subscribe_launcher(service, str(RUN), blind)
    assert refused.status == "unavailable" and refused.reason == "unauthorized"
    # Subscribed before the launch: the run's terminal event lands after the cursor.
    terminal(inbox)
    assert first.subscription_id is not None
    page = await service.poll(first.subscription_id, LAUNCHER)
    assert [item.kind for item in page.notifications] == [NotificationKind.TERMINAL_RESULT]


async def test_summary_webhook_payload_carries_the_redacted_summary() -> None:
    subscriptions = InMemoryStore()
    inbox = InMemoryInboxStore(subscriptions)
    hook = FakeWebhook()
    service = CoordinatorInboxService(
        subscriptions,
        inbox,
        transport=hook,
        secrets=StaticSecrets({"environment:MC_HOOK": "s3cr3t"}),
        attention=InMemoryAttentionStore(inbox),
    )
    for payload in ("summary", "reference"):
        await service.subscribe(
            CoordinatorSubscribeRequest.model_validate(
                {
                    "target": "run",
                    "target_id": str(RUN),
                    "after_seq": 0,
                    "delivery": {
                        "kind": "webhook",
                        "url": f"https://hooks.example/{payload}",
                        "secret_ref": "environment:MC_HOOK",
                        "payload": payload,
                    },
                }
            ),
            LAUNCHER,
        )
    terminal(inbox)
    await service.deliver_callbacks()
    bodies = {item.url.rsplit("/", 1)[1]: json.loads(item.body) for item in hook.received}
    summary = bodies["summary"]["summary"]
    assert "terminal_result, actionable" in summary and "terminal_outcome=completed" in summary
    assert "summary" not in bodies["reference"]
    assert "s3cr3t" not in json.dumps(bodies)


async def test_prompt_is_the_summary_plus_the_acknowledgement_instruction() -> None:
    service, inbox, _clock = compose()
    sid = await run_inbox(service)
    terminal(inbox)
    (notification,) = (await service.poll(sid, LAUNCHER)).notifications
    assert render_prompt(notification).startswith(render_summary(notification) + "\n")
    assert "acknowledge" not in render_summary(notification)


# -- HTTP ---------------------------------------------------------------------------------------


async def test_http_long_poll_list_and_kinds() -> None:
    service, inbox, _clock = compose()
    client = TestClient(inbox_app(service))
    base = "/v1/applications/biotech/coordinator-inboxes"
    created = client.post(
        base,
        json={
            "target": "run",
            "target_id": str(RUN),
            "after_seq": 0,
            "delivery": "webhook",
            "webhook_url": "https://hooks.example/cb",
            "secret_ref": "environment:MC_HOOK",
            "webhook_payload": "summary",
        },
    )
    assert created.status_code == 201, created.text
    sid = created.json()["subscription_id"]
    assert created.json()["delivery"] == "webhook"
    assert (await service.inbox(UUID(sid), LAUNCHER)).delivery.payload == "summary"  # type: ignore[union-attr]
    listed = client.get(base, params={"target": "run", "target_id": str(RUN)})
    assert [item["subscription_id"] for item in listed.json()["inboxes"]] == [sid]
    inbox.add(journal_event(1, "human_task.created"), human_task_id="t-1")
    terminal(inbox)
    waited = client.get(
        f"{base}/{sid}/notifications", params={"wait": 0.2, "kinds": "terminal_result"}
    )
    assert waited.status_code == 200, waited.text
    assert [item["kind"] for item in waited.json()["notifications"]] == ["terminal_result"]
    bad = client.get(f"{base}/{sid}/notifications", params={"wait": 1, "kinds": "finished"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid"
    too_long = client.get(f"{base}/{sid}/notifications", params={"wait": MAX_WAIT_SECONDS + 1})
    assert too_long.status_code == 422


async def test_http_manifest_start_subscribes_the_launcher_before_launching() -> None:
    service, inbox, _clock = compose()
    lifecycle = LaunchObserver(service)
    manifests = MissionManifestService(
        compiler=None,  # type: ignore[arg-type]
        request_scope=SCOPE,
        lifecycle=lifecycle,  # type: ignore[arg-type]
    )
    client = TestClient(inbox_app(service, manifests))
    started = client.post("/v1/applications/biotech/missions:start", json={"run_id": str(RUN)})
    assert started.status_code == 202, started.text
    receipt = started.json()["coordinator_inbox"]
    assert receipt["status"] == "subscribed"
    assert lifecycle.inboxes_at_start == [receipt["subscription_id"]]
    replay = client.post("/v1/applications/biotech/missions:start", json={"run_id": str(RUN)})
    assert replay.json()["coordinator_inbox"] == {**receipt, "status": "existing"}
    quiet = client.post(
        "/v1/applications/biotech/missions:start",
        params={"notify": "none"},
        json={"run_id": str(RUN)},
    )
    assert quiet.json()["coordinator_inbox"]["status"] == "off"
    assert len(inbox.inboxes) == 1


class LaunchObserver(FakeLifecycle):
    """Records which launcher inboxes already existed when the launch happened."""

    request_scope = SCOPE

    def __init__(self, service: CoordinatorInboxService) -> None:
        super().__init__()
        self.service = service
        self.inboxes_at_start: list[str] = []

    async def start(self, run_id: str, actor: ActorContext, **kwargs: Any) -> Any:
        found = await self.service.inboxes(actor, target="run", target_id=UUID(run_id))
        self.inboxes_at_start = [str(item.subscription_id) for item in found]
        return await super().start(run_id, actor, **kwargs)


# -- MCP ----------------------------------------------------------------------------------------


class Resolver:
    def __init__(self, request_scope: str = SCOPE) -> None:
        self.principal = CoordinatorPrincipal(
            actor_id=LAUNCHER.actor_id,
            tenant_scope="tenant-a",
            roles=frozenset(),
            permissions=LAUNCHER.permissions,
            request_scope=request_scope,
        )

    async def resolve(self, _context: Any) -> CoordinatorPrincipal:
        return self.principal


async def test_mcp_inbox_wait_returns_the_notification_as_the_tool_result() -> None:
    from mission_control.interfaces.mcp.coordinator_server import create_coordinator_server

    service, inbox, _clock = compose()
    sid = await run_inbox(service)
    server = create_coordinator_server(
        FakeFacade(),
        Resolver(),
        subscriptions=McpSubscriptionBridge(
            {SCOPE: SubscriptionService(inbox.subscriptions)},
            McpSessionHub(),
            inboxes={SCOPE: service},
        ),
    )
    terminal(inbox)
    async with Client(server) as client:
        listed = await client.call_tool(
            "coordinator_inbox_list", {"target": "run", "target_id": str(RUN)}
        )
        assert listed.data["data"]["inboxes"][0]["subscription_id"] == str(sid)
        waited = await client.call_tool(
            WAIT_TOOL,
            {"subscription_id": str(sid), "wait_seconds": 5, "kinds": ["terminal_result"]},
        )
        assert waited.data["ok"] is True, waited.data
        (notification,) = waited.data["data"]["notifications"]
        assert notification["kind"] == "terminal_result"
        bad = await client.call_tool(WAIT_TOOL, {"subscription_id": str(sid), "kinds": ["x"]})
        assert bad.data["ok"] is False and bad.data["error"]["code"] == "INVALID_ARGUMENT"


async def test_mcp_run_start_subscribes_the_launcher() -> None:
    service, _inbox, _clock = compose()
    lifecycle = LaunchObserver(service)
    manifests = MissionManifestService(
        compiler=None,  # type: ignore[arg-type]
        request_scope=SCOPE,
        lifecycle=lifecycle,  # type: ignore[arg-type]
    )
    server = FastMCP("operator-start-test")
    register_manifest_tools(
        server,
        ScopedManifests({SCOPE: manifests}, inboxes={SCOPE: service}),
        Resolver(),
        call=_principal_call,
    )
    async with Client(server) as client:
        started = await client.call_tool(START_TOOL, {"run_id": str(RUN)})
        data = started.data["data"]
        assert data["coordinator_inbox"]["status"] == "subscribed"
        assert lifecycle.inboxes_at_start == [data["coordinator_inbox"]["subscription_id"]]
        quiet = await client.call_tool(START_TOOL, {"run_id": str(RUN), "notify": "none"})
        assert quiet.data["data"]["coordinator_inbox"]["status"] == "off"


async def test_operator_mcp_authenticates_every_request_and_unifies_the_surface() -> None:
    service, inbox, _clock = compose()
    path = "/v1/applications/biotech/mcp/"
    async with operator_client(service, None) as (http, _app):
        refused = await http.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert refused.status_code == 401
        assert refused.json()["detail"]["code"] == "bearer_token_required"
    async with operator_client(service, "good") as (http, _app):
        client = CoordinatorStreamableHttpClient(http, path)
        await client.initialize()
        names = {tool.name for tool in await client.list_tools()}
        assert {
            WAIT_TOOL,
            "coordinator_inbox_list",
            "coordinator_inbox_ack",
            "mission_run_transcript",
            "mission_manifest_submit",
            START_TOOL,
            "mission_command_send",
            "mission_run_fork",
            "mission_human_task_resolve",
        } <= names
        assert SUBSCRIBE_TOOL not in names  # deprecated push is not offered (ADR-0049)
        assert "launch_workflow" not in names  # the catalog facade is not composed here
        sid = await run_inbox(service)
        terminal(inbox)
        waited = await client.call_tool(
            WAIT_TOOL, {"subscription_id": str(sid), "kinds": ["terminal_result"]}
        )
        assert isinstance(waited.data, dict) and waited.data["ok"] is True, waited.data
        (notification,) = waited.data["data"]["notifications"]
        assert notification["kind"] == "terminal_result"
        # The gate's principal (not a request field) owns the inbox: another actor sees none.
        assert (await service.inbox(sid, LAUNCHER)).coordinator_ref == LAUNCHER.actor_id


# -- missionctl ---------------------------------------------------------------------------------


async def test_missionctl_wait_wakes_on_terminal_result_and_times_out_with_6(
    missionctl: Any,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    subscriptions = InMemoryStore()
    inbox = InMemoryInboxStore(subscriptions)
    service = CoordinatorInboxService(subscriptions, inbox, wait_interval=0.05)
    missionctl(inbox_app(service))
    timed_out = cli.main(["wait", "--run", str(RUN), "--kinds", "terminal_result", "--wait", "0.3"])
    captured = capsys.readouterr()
    assert timed_out == 6 and captured.out == ""
    created = json.loads(captured.err.splitlines()[0])
    assert created["created"] is True  # no launcher inbox existed: one was registered at seq 0
    terminal(inbox)
    woken = cli.main(["wait", "--run", str(RUN), "--kinds", "terminal_result,blocked"])
    captured = capsys.readouterr()
    assert woken == 0
    (line,) = captured.out.splitlines()
    notification = json.loads(line)
    assert notification["kind"] == "terminal_result"
    assert notification["events"][0]["event_type"] == "run.completed"
    assert json.loads(captured.err.splitlines()[0]) == {
        "inbox": created["inbox"],
        "created": False,
    }
    # Not acknowledged: the next wait prints it again until `inbox ack` (or --ack).
    assert cli.main(["wait", "--inbox", created["inbox"], "--ack"]) == 0
    assert json.loads(capsys.readouterr().out)["notification_id"] == notification["notification_id"]
    assert cli.main(["wait", "--inbox", created["inbox"], "--wait", "0.2"]) == 6
    capsys.readouterr()
    inbox.add(journal_event(3, "human_task.created"), human_task_id="t-9")
    assert cli.main(["inbox", "list", "--run", str(RUN)]) == 0
    assert json.loads(capsys.readouterr().out)["inboxes"][0]["high_inbox_seq"] == 1
    assert cli.main(["wait", "--inbox", created["inbox"], "--follow", "--wait", "0.3"]) == 0
    (review,) = capsys.readouterr().out.splitlines()
    assert json.loads(review)["kind"] == "review_required"
    assert cli.main(["inbox", "ack", created["inbox"], "--through", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["acked_inbox_seq"] == 2
    assert cli.main(["inbox", "ack", created["inbox"]]) == 2
    assert (await service.inbox(UUID(created["inbox"]), LAUNCHER)).state is (
        SubscriptionState.ACTIVE
    )

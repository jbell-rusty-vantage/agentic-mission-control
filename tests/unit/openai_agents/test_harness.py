"""Agents API lifecycle, recovery and terminal truth against a stateful HTTP fake."""

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from mission_control.adapters.openai_agents.harness import CodexAgentsHarness
from mission_control.adapters.openai_agents.pack import load_pack
from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer
from mission_control.adapters.remote_session.errors import RemoteSessionError
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.application.execution.harness.retention import SessionRetentionService
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.lanes import (
    CancelTurnRequest,
    ObserveRequest,
    PrepareRequest,
    SendTurnRequest,
    StartRequest,
)
from tests.support.providers.openai_agents import (
    SHIPPED_PACK,
    AgentsStack,
    SessionsApi,
    agents_stack,
)


@dataclass
class LaggingTurnIndex(SessionsApi):
    """The Agents API while its root-turn index lags: listing a session's turns returns none,
    and a session running a turn reports that turn as its one required action. `readback`
    changes the action turn's own readback; `extra_actions` adds further required actions."""

    readback: dict[str, Any] = field(default_factory=dict)
    extra_actions: int = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.removeprefix("/v1").strip("/").split("/")
        if request.method != "GET" or parts[:2] != ["agents", "sessions"]:
            return super().handle(request)
        if len(parts) == 4 and parts[3] == "turns":
            super().handle(request)  # recorded like any other read
            return self._page([], dict(request.url.params))
        response = super().handle(request)
        if len(parts) == 3:
            running = [turn for turn in self.turn_store.values() if turn["session_id"] == parts[2]]
            if running:
                action = {"type": "function_call", "turn_id": running[0]["id"], "call_id": "call"}
                return httpx.Response(
                    200,
                    json={
                        **response.json(),
                        "status": "requires_action",
                        "required_actions": [action] * (1 + self.extra_actions),
                    },
                )
        if len(parts) == 5 and parts[3] == "turns":
            return httpx.Response(200, json={**response.json(), **self.readback})
        return response


def stack_over(
    tmp_path: Path,
    api: SessionsApi | None = None,
    *,
    scripts: tuple[str, ...] = ("full",),
    **options: Any,
) -> AgentsStack:
    """`agents_stack` over `api` (default: a plain SessionsApi) and a harness composed with
    `options` (CodexAgentsHarness constructor settings)."""

    stack = agents_stack(tmp_path, scripts)
    api = api or SessionsApi(scripts=list(scripts))
    client = api.client()
    harness = CodexAgentsHarness(
        client=client,
        preparer=CodexAgentsPreparer(
            client,
            WorkerEnvironmentSource({"MC_GITHUB_READONLY_TOKEN": "test-readonly-token"}),
        ),
        pack=load_pack(SHIPPED_PACK),
        artifacts=stack.artifacts,
        retention=SessionRetentionService(stack.deletions),
        poll_interval_s=0.001,
        **options,
    )
    return replace(stack, harness=harness, api=api)


def fields(stack: AgentsStack, key: str) -> dict:
    identity = LaneExecutionIdentity.of(stack.operation, "codex_agents", 1)
    return {
        "scope": harness_scope(identity.request_scope),
        "lane_profile": "codex_agents",
        "harness_execution_id": str(identity.harness_execution_id),
        "generation": 1,
        "binding_digest": ProviderExecutionBinding.carried_by(stack.operation).binding_digest,
        "idempotency_key": key,
    }


async def start(stack: AgentsStack):
    identity = LaneExecutionIdentity.of(stack.operation, "codex_agents", 1)
    stack.harness.stage(str(identity.harness_execution_id), stack.operation)
    prepared = await stack.harness.prepare(
        PrepareRequest(
            **fields(stack, "prepare"),
            run_id=identity.run_key,
            operation_id=identity.activation_key,
            attempt_no=1,
        )
    )
    return await stack.harness.start(StartRequest(**fields(stack, "create"), prepared=prepared))


async def send(stack: AgentsStack, session, number: int = 1):
    return await stack.harness.send_turn(
        SendTurnRequest(
            **fields(stack, f"send{number}"),
            session=session,
            turn_no=number,
            instruction_ref="initial",
        )
    )


async def observe(stack: AgentsStack, turn, after=None):
    return [
        frame
        async for frame in stack.harness.observe(
            ObserveRequest(**fields(stack, "observe"), turn=turn, after=after)
        )
    ]


async def test_cancel_retries_a_conflict_until_the_turn_closes_cancelled(tmp_path: Path) -> None:
    # The busy half of this test is the conformance send-while-busy scenario.
    stack = agents_stack(tmp_path, ("held",))
    session = await start(stack)
    turn = await send(stack, session)
    stack.api.cancel_conflicts = 1
    cancel = await stack.harness.cancel_turn(
        CancelTurnRequest(**fields(stack, "cancel"), turn=turn, reason="owner stop")
    )
    assert cancel.acknowledged and stack.api.cancel_count == 2
    final = (await observe(stack, turn))[-1]
    assert stack.harness.closing_facts(turn, final).native_status == "cancelled"


@pytest.mark.parametrize("status", ["suspended", "expired", "reset"])
async def test_environment_events_do_not_terminalize_root_turn(tmp_path: Path, status: str) -> None:
    from mission_control.adapters.remote_session.sse import SseEvent

    stack = agents_stack(tmp_path)
    kind = "agent.session.environment." + status
    assert stack.harness._classify(SseEvent(event=kind, data="{}"), {"type": kind}).role == "frame"


@pytest.mark.parametrize("with_input", [False, True])
async def test_instruction_only_turn_has_nonempty_trigger(tmp_path: Path, with_input: bool):
    from mission_control.domain.execution.contracts import PromptTrustClass

    stack = agents_stack(tmp_path)
    authored = stack.operation.prompt_segments[0].model_copy(
        update={"trust_class": PromptTrustClass.AUTHORED_INSTRUCTION}
    )
    segments = (authored,)
    if with_input:
        segments += (authored.model_copy(update={"trust_class": PromptTrustClass.ADMITTED_INPUT}),)
    stack.operation = stack.operation.model_copy(update={"prompt_segments": segments})
    session = await start(stack)
    await send(stack, session)
    created = stack.api.sessions_store[session.native_session_ref]
    assert authored.content in created["agent"]["instructions"]
    import json

    message = json.loads(stack.api.sends[-1][1])[0]["content"][0]["text"]
    assert message == (
        authored.content.strip() if with_input else "Execute the admitted operation instructions."
    )


async def test_recovery_items_use_exact_turn_endpoint(tmp_path: Path):
    stack = agents_stack(tmp_path)
    session = await start(stack)
    turn = await send(stack, session)
    await observe(stack, turn)
    requests = [row for row in stack.api.requests if row.path.endswith("/items")]
    assert requests and all(
        row.path
        == f"/agents/sessions/{session.native_session_ref}/turns/{turn.native_turn_ref}/items"
        for row in requests
    )
    assert all("turn_id" not in row.params for row in requests)


@pytest.mark.parametrize("turn_id", [None, "root-turn"])
async def test_items_cursor_and_unscoped_endpoint_are_preserved(turn_id):
    import httpx
    from pydantic import SecretStr

    from mission_control.adapters.openai_agents.client import AgentsApiClient

    def serve(request):
        expected = (
            "/v1/agents/sessions/session/items"
            if turn_id is None
            else "/v1/agents/sessions/session/turns/root-turn/items"
        )
        assert request.url.path == expected
        assert request.url.params["after"] == "item-before"
        assert "turn_id" not in request.url.params
        return httpx.Response(200, json={"data": [], "has_more": False})

    client = AgentsApiClient(SecretStr("fixture-key"), transport=httpx.MockTransport(serve))
    try:
        assert [
            item async for item in client.items("session", turn_id=turn_id, after="item-before")
        ] == []
    finally:
        await client.aclose()


@pytest.mark.parametrize("bad", [None, "subagent", "wrong_session", "old_turn", "multi_action"])
async def test_initial_action_exact_root_readback(tmp_path, bad):
    readback = {
        None: {},
        "subagent": {"subagent_id": "child"},
        "wrong_session": {"session_id": "other"},
        "old_turn": {"status": "completed"},
        "multi_action": {},
    }[bad]
    api = LaggingTurnIndex(
        scripts=["held"], readback=readback, extra_actions=int(bad == "multi_action")
    )
    stack = stack_over(tmp_path, api, poll_limit=1)
    session = await start(stack)
    if bad is None:
        turn = await send(stack, session)
        assert turn.native_turn_ref == next(iter(stack.api.turn_store))
    else:
        with pytest.raises(RemoteSessionError, match="no unambiguous turn"):
            await send(stack, session)
    await stack.harness._close_stream(
        stack.harness._session(
            SendTurnRequest(
                **fields(stack, "close"), session=session, turn_no=1, instruction_ref="initial"
            )
        )
    )


@pytest.mark.parametrize("number", [1, 2])
async def test_empty_turn_index_adopts_exact_initial_action_only(tmp_path, number):
    stack = stack_over(tmp_path, LaggingTurnIndex(scripts=["held"]), poll_limit=1)
    session = await start(stack)
    if number == 1:
        turn = await send(stack, session, number)
        assert turn.native_turn_ref == next(iter(stack.api.turn_store))
    else:
        with pytest.raises(RemoteSessionError, match="no unambiguous turn"):
            await send(stack, session, number)
    await stack.harness._close_stream(
        stack.harness._session(
            SendTurnRequest(
                **fields(stack, "close"), session=session, turn_no=number, instruction_ref="initial"
            )
        )
    )


async def test_finite_history_replay_has_native_boundary_and_bound(tmp_path):
    from mission_control.domain.execution.history_reconciliation import (
        HistoryReplayComplete,
        HistoryReplayIncomplete,
    )

    stack = agents_stack(tmp_path)
    session = await start(stack)
    turn = await send(stack, session)
    request = ObserveRequest(**fields(stack, "history"), turn=turn)
    before = len(stack.api.requests)
    replay = [frame async for frame in stack.harness.reconcile_history(request)]
    assert isinstance(replay[-1], HistoryReplayComplete)
    assert any(getattr(frame, "terminal", False) for frame in replay)
    assert all(record.method == "GET" for record in stack.api.requests[before:])
    bounded = stack_over(tmp_path, max_history_frames=1)
    turn = await send(bounded, await start(bounded))
    request = ObserveRequest(**fields(bounded, "history"), turn=turn)
    with pytest.raises(HistoryReplayIncomplete):
        _ = [frame async for frame in bounded.harness.reconcile_history(request)]


async def test_history_recovers_earlier_item_that_finishes_after_persisted_later_item(tmp_path):
    from mission_control.domain.execution.history_reconciliation import HistoryReplayComplete
    from mission_control.domain.execution.lanes import LaneFrame

    stack = agents_stack(tmp_path, ("held",))
    session = await start(stack)
    turn = await send(stack, session)
    earlier = {
        "id": "item_a",
        "turn_id": turn.native_turn_ref,
        "type": "message",
        "role": "assistant",
        "status": "in_progress",
        "content": [],
    }
    later = {
        "id": "item_b",
        "turn_id": turn.native_turn_ref,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [],
    }
    stack.api.item_store[turn.native_turn_ref] = [earlier, later]
    request = ObserveRequest(**fields(stack, "history-first"), turn=turn)
    first = [frame async for frame in stack.harness.reconcile_history(request)]
    assert isinstance(first[-1], HistoryReplayComplete)
    (persisted_later,) = [frame for frame in first if isinstance(frame, LaneFrame)]
    assert persisted_later.body["item"]["id"] == "item_b"

    earlier["status"] = "completed"
    second = [
        frame
        async for frame in stack.harness.reconcile_history(
            ObserveRequest(**fields(stack, "history-next"), turn=turn, after=persisted_later.cursor)
        )
    ]
    assert isinstance(second[-1], HistoryReplayComplete)
    recovered = [frame for frame in second if isinstance(frame, LaneFrame)]
    assert [frame.body["item"]["id"] for frame in recovered] == ["item_a", "item_b"]
    assert recovered[1].provider_key == persisted_later.provider_key
    assert recovered[1].digest == persisted_later.digest
    assert recovered[0].provider_key != persisted_later.provider_key
    assert len(stack.api.sends) == 1
    await stack.harness._close_stream(stack.harness._session(request))

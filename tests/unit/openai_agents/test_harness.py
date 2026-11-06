"""Agents API lifecycle, recovery and terminal truth against a stateful HTTP fake."""

from pathlib import Path

import pytest

from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.lanes import (
    CancelTurnRequest,
    EndSessionRequest,
    ObserveRequest,
    PrepareRequest,
    ReattachRequest,
    SendTurnRequest,
    StartRequest,
)
from tests.fixtures.agents_lane import AgentsStack, agents_stack


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


async def test_start_observe_settle_and_custody_before_retention(tmp_path: Path) -> None:
    stack = agents_stack(tmp_path)
    session = await start(stack)
    turn = await send(stack, session)
    events = await observe(stack, turn)
    final = events[-1]
    assert final.terminal
    facts = stack.harness.closing_facts(turn, final)
    assert facts.native_status == "finished"
    assert facts.result_excerpt == "Completed answer."
    assert facts.usage.total_tokens == 10
    assert facts.cost_disposition == "unknown"
    paths = [r.path for r in stack.api.requests]
    assert paths.index(f"/agents/sessions/{session.native_session_ref}/events") < next(
        i
        for i, r in enumerate(stack.api.requests)
        if r.method == "POST" and r.path.endswith("/events")
    )
    receipt = await stack.harness.end_session(
        EndSessionRequest(**fields(stack, "end"), session=session, reason="done")
    )
    assert receipt.released and receipt.artifact_refs and stack.deletions.orders
    assert session.native_session_ref in stack.api.sessions_store


async def test_busy_does_not_steer_and_cancel_retries_conflict(tmp_path: Path) -> None:
    stack = agents_stack(tmp_path, ("held",))
    session = await start(stack)
    turn = await send(stack, session)
    assert (await send(stack, session, 2)).status == "busy"
    assert len(stack.api.sends) == 1
    stack.api.cancel_conflicts = 1
    cancel = await stack.harness.cancel_turn(
        CancelTurnRequest(**fields(stack, "cancel"), turn=turn, reason="owner stop")
    )
    assert cancel.acknowledged and stack.api.cancel_count == 2
    final = (await observe(stack, turn))[-1]
    assert stack.harness.closing_facts(turn, final).native_status == "cancelled"


async def test_reattach_after_worker_loss_recovers_final_items_with_stable_keys(
    tmp_path: Path,
) -> None:
    stack = agents_stack(tmp_path, ("held",))
    session = await start(stack)
    turn = await send(stack, session)
    stack.api.release()
    original = await observe(stack, turn)
    # Lose every process-local summary and item. The provider history survives.
    stack.harness._sessions.clear()
    identity = LaneExecutionIdentity.of(stack.operation, "codex_agents", 1)
    stack.harness.stage(str(identity.harness_execution_id), stack.operation)
    await stack.harness.reattach(
        ReattachRequest(
            **fields(stack, "reattach"),
            native_session_ref=session.native_session_ref,
            native_turn_ref=turn.native_turn_ref,
        )
    )
    restored = await observe(stack, turn, original[-2].cursor)
    assert restored[-1].provider_key == original[-1].provider_key
    assert stack.harness.final_text(turn, restored[-1]) == "Completed answer."
    assert len(stack.api.sends) == 1


async def test_unknown_turn_usage_stays_unknown(tmp_path: Path) -> None:
    stack = agents_stack(tmp_path, ("no_usage",))
    final = (await observe(stack, await send(stack, await start(stack))))[-1]
    assert final.body["turn"]["usage"] is None
    assert stack.harness.closing_facts(None, final).usage.disposition == "unknown"


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
async def test_initial_action_exact_root_readback(tmp_path, monkeypatch, bad):
    stack = agents_stack(tmp_path)
    session = await start(stack)
    ref = session.native_session_ref
    action = {"turn_id": "turn-new", "type": "function_call"}
    state = {"status": "requires_action", "required_actions": [action]}
    turn = {"id": "turn-new", "session_id": ref, "subagent_id": None, "status": "waiting"}
    if bad == "subagent":
        turn["subagent_id"] = "child"
    elif bad == "wrong_session":
        turn["session_id"] = "other"
    elif bad == "old_turn":
        turn["status"] = "completed"
    elif bad == "multi_action":
        state["required_actions"].append(dict(action))

    async def retrieve_session(_):
        return state

    async def retrieve_turn(*_):
        return turn

    monkeypatch.setattr(stack.harness._client, "retrieve_session", retrieve_session)
    monkeypatch.setattr(stack.harness._client, "retrieve_turn", retrieve_turn)
    assert await stack.harness._initial_action_turn(ref) == ("turn-new" if bad is None else None)


@pytest.mark.parametrize("number", [1, 2])
async def test_empty_turn_index_adopts_exact_initial_action_only(tmp_path, monkeypatch, number):
    from mission_control.adapters.remote_session.errors import RemoteSessionError

    stack = agents_stack(tmp_path, ("held",))
    session = await start(stack)
    retrieve = stack.harness._client.retrieve_session

    async def state(ref):
        row = await retrieve(ref)
        if stack.api.turn_store:
            turn = next(iter(stack.api.turn_store.values()))
            return {
                **row,
                "status": "requires_action",
                "required_actions": [
                    {"type": "function_call", "turn_id": turn["id"], "call_id": "call-current"}
                ],
            }
        return row

    async def empty(_):
        return []

    monkeypatch.setattr(stack.harness._client, "retrieve_session", state)
    monkeypatch.setattr(stack.harness, "_root_turns", empty)
    stack.harness._poll_limit = 1
    stack.harness._poll_interval_s = 0
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


async def test_finite_history_replay_has_native_boundary_and_bound(tmp_path, monkeypatch):
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
    monkeypatch.setattr("mission_control.adapters.openai_agents.harness.MAX_HISTORY_FRAMES", 1)
    with pytest.raises(HistoryReplayIncomplete):
        _ = [frame async for frame in stack.harness.reconcile_history(request)]


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

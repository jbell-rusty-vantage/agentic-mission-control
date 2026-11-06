"""Offline pinned-wire bootstrap regression; no SDK subprocess or provider calls."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from claude_agent_sdk.types import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    UserMessage,
)

from mission_control.adapters.claude.session import BOOTSTRAP_TEXT, LiveSession, SessionEnded
from tests.unit.claude.bootstrap_usage_fixture import zero_bootstrap_usage


def result(**changes: Any) -> ResultMessage:
    return replace(
        ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=0,
            is_error=False,
            num_turns=0,
            session_id="observed-native",
            total_cost_usd=0,
            usage=zero_bootstrap_usage(),
            result="",
            origin={"kind": "unclassified"},
        ),
        **changes,
    )


class Client:
    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.inputs: list[dict[str, Any]] = []
        self.disconnected = False
        self.readers = 0
        self.queried = asyncio.Event()

    async def connect(self) -> None:
        pass  # Actual pinned connect alone does not emit system/init.

    async def query(self, prompt: Any) -> None:
        self.inputs.extend([item async for item in prompt])
        self.queried.set()
        if len(self.inputs) == 1:
            await self.queue.put(SystemMessage("init", {"session_id": "observed-native"}))
            if self.reply is not None:
                await self.queue.put(self.reply)

    async def receive_messages(self) -> Any:
        self.readers += 1
        while True:
            item = await self.queue.get()
            if isinstance(item, BaseException):
                raise item
            if item is StopAsyncIteration:
                return
            yield item

    async def disconnect(self) -> None:
        self.disconnected = True


class Factory:
    versions = {"claude_agent_sdk": "0.2.165", "claude_code_bundled": "2.1.294"}

    def __init__(self, client: Client) -> None:
        self.client = client

    def create(self, *args: Any, **kwargs: Any) -> Client:
        return self.client


def session(client: Client) -> LiveSession:
    return LiveSession(
        Factory(client),
        ClaudeAgentOptions(),
        {},
        harness_execution_id="fixture",
        generation=1,
        init_timeout_s=0.05,
    )


async def test_bootstrap_drains_before_first_business_turn() -> None:
    client = Client(result())
    live = session(client)
    try:
        assert await live.start() == "observed-native"
        bootstrap = client.inputs[0]
        assert bootstrap["message"]["content"] == BOOTSTRAP_TEXT
        assert bootstrap["shouldQuery"] is False
        assert bootstrap["client_composed"] is True
        assert bootstrap["isSynthetic"] is True
        assert not live.turns and not live.sent and live.state.last_result is None
        await live.send("actual admitted instruction", turn_ref="business", idempotency_key="send")
        assert live.active is not None and live.active.turn_ref == "business"
        assert client.inputs[1]["uuid"] == "business"
        assert "shouldQuery" not in client.inputs[1]
        await client.queue.put(result(num_turns=1, result="business output", origin=None))
        for _ in range(20):
            if live.active is None:
                break
            await asyncio.sleep(0)
        assert live.turns["business"].terminal_index is not None
        assert client.readers == 1
    finally:
        await live.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"num_turns": 1},
        {"usage": None},
        {"usage": {"input_tokens": 1, "output_tokens": 0}},
        {"usage": {"input_tokens": 0, "output_tokens": 0, "unknown": "0"}},
        {"total_cost_usd": 0.001},
        {"duration_api_ms": 1},
        {"session_id": "wrong"},
        {"result": "normal answer"},
        {"permission_denials": [{"tool": "Bash"}]},
        {"is_error": True},
        {"model_usage": {"unexpected": {}}},
    ],
)
async def test_unsafe_bootstrap_refuses_and_disconnects(changes: dict[str, Any]) -> None:
    client = Client(result(**changes))
    live = session(client)
    with pytest.raises(SessionEnded, match="unsafe result"):
        await live.start()
    assert client.disconnected and not live.turns and live.session_id is None


@pytest.mark.parametrize("reply", [None, RuntimeError("process died"), StopAsyncIteration])
async def test_incomplete_bootstrap_disconnects(reply: Any) -> None:
    client = Client(reply)
    live = session(client)
    with pytest.raises((SessionEnded, RuntimeError)):
        await live.start()
    assert client.disconnected and not live.turns


@pytest.mark.parametrize(
    "reply",
    [
        AssistantMessage(content=[], model="unexpected"),
        SystemMessage("init", {"session_id": "second-native"}),
        SystemMessage("hook_response", {"hook_event": "unexpected"}),
    ],
)
async def test_other_native_messages_fail_closed(reply: Any) -> None:
    client = Client(reply)
    live = session(client)
    with pytest.raises(SessionEnded, match="unexpected message"):
        await live.start()
    assert client.disconnected and live.session_id is None


async def test_resume_identity_must_match_requested_native_session() -> None:
    client = Client(result())
    live = session(client)
    live.configure(ClaudeAgentOptions(resume="expected-native"))
    with pytest.raises(SessionEnded, match="native identity"):
        await live.start()
    assert client.disconnected


async def test_connect_is_also_bounded_and_disconnected() -> None:
    client = Client(result())

    async def hang() -> None:
        await asyncio.Event().wait()

    client.connect = hang  # type: ignore[method-assign]
    live = session(client)
    with pytest.raises(SessionEnded, match="timeout"):
        await live.start()
    assert client.disconnected and not client.inputs


async def test_version_mismatch_refuses_before_client_creation() -> None:
    client = Client(result())
    factory = Factory(client)
    factory.versions = {**factory.versions, "claude_code_bundled": "future"}
    live = LiveSession(
        factory, ClaudeAgentOptions(), {}, harness_execution_id="fixture", generation=1
    )
    with pytest.raises(SessionEnded, match="pinned SDK"):
        await live.start()
    assert not client.inputs


async def test_cancellation_disconnects_during_bootstrap() -> None:
    client = Client(None)
    live = session(client)
    task = asyncio.create_task(live.start())
    await client.queried.wait()
    with pytest.raises(SessionEnded, match="not connected"):
        await live.send("too early", turn_ref="business", idempotency_key="send")
    assert len(client.inputs) == 1 and not live.turns
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.disconnected and live.session_id is None


async def test_duplicate_optional_echo_is_refused() -> None:
    client = Client(None)
    live = session(client)
    task = asyncio.create_task(live.start())
    await client.queried.wait()
    echo = UserMessage(
        content=BOOTSTRAP_TEXT, uuid=client.inputs[0]["uuid"], origin={"kind": "unclassified"}
    )
    await client.queue.put(echo)
    await client.queue.put(echo)
    await client.queue.put(result())
    with pytest.raises(SessionEnded, match="unexpected user input"):
        await task
    assert client.disconnected


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("service_tier", "priority"),
        ("speed", "fast"),
        ("inference_geo", "us"),
        ("fallback_credit", 0),
        ("iterations", [{}]),
        ("unknown", 0),
        ("input_tokens", False),
        ("output_tokens", 0.0),
        ("output_tokens_details", {"thinking_tokens": 1}),
        ("server_tool_use", {"web_search_requests": 0, "web_fetch_requests": 1}),
        ("cache_creation", {"ephemeral_1h_input_tokens": 1, "ephemeral_5m_input_tokens": 0}),
        (
            "cache_creation",
            {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0, "unknown": 0},
        ),
    ],
)
async def test_exact_pinned_usage_defaults_only(key: str, value: Any) -> None:
    usage = zero_bootstrap_usage()
    usage[key] = value
    client = Client(result(usage=usage))
    with pytest.raises(SessionEnded, match="unsafe result"):
        await session(client).start()
    assert client.disconnected


async def test_missing_usage_metadata_is_not_silently_stripped() -> None:
    usage = zero_bootstrap_usage()
    del usage["service_tier"]
    client = Client(result(usage=usage))
    with pytest.raises(SessionEnded, match="unsafe result"):
        await session(client).start()


@pytest.mark.parametrize(
    "origin",
    [
        None,
        {"kind": "human"},
        {"kind": "peer"},
        {"kind": "channel"},
        {"kind": "unclassified", "from": "unexpected"},
        {"kind": "future"},
        {},
    ],
)
async def test_only_exact_synthetic_origin_is_accepted(origin: Any) -> None:
    client = Client(result(origin=origin))
    with pytest.raises(SessionEnded, match="unsafe result"):
        await session(client).start()
    assert client.disconnected

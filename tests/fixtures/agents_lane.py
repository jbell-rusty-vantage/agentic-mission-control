"""Stateful Agents API session fake, sharing HL-11's resource preparation fake."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from tests.fixtures.cursor_local import MemoryArtifacts
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.lane_turns import DIGEST, SCOPE
from tests.fixtures.session_retention import RecordingDeletionScheduler
from tests.unit.openai_agents.support import SHIPPED_PACK, FakeAgentsApi, Recorded

from mission_control.adapters.openai_agents.describe import CODEX_AGENTS_DESCRIBE
from mission_control.adapters.openai_agents.harness import CodexAgentsHarness
from mission_control.adapters.openai_agents.pack import load_pack
from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.execution.harness.retention import SessionRetentionService
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest


class EventStream(httpx.AsyncByteStream):
    def __init__(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.queue = queue

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        while True:
            event = await self.queue.get()
            yield f"data: {json.dumps(event)}\n\n".encode()


@dataclass
class SessionsApi(FakeAgentsApi):
    scripts: list[str] = field(default_factory=lambda: ["full"])
    sessions_store: dict[str, dict[str, Any]] = field(default_factory=dict)
    turn_store: dict[str, dict[str, Any]] = field(default_factory=dict)
    item_store: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = field(default_factory=dict)
    sends: list[tuple[str, str]] = field(default_factory=list)
    event_keys: dict[str, str] = field(default_factory=dict)
    held: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_count: int = 0
    cancel_conflicts: int = 0
    no_usage: set[str] = field(default_factory=set)
    # Turns held open by the `held` script (steerable until released), and the turns a
    # mid-turn input steered.
    holding: set[str] = field(default_factory=set)
    steers: list[str] = field(default_factory=list)

    def emit(self, session_id: str, kind: str, **fields: Any) -> None:
        event = {"type": kind, "event_id": self._id("ev"), "session_id": session_id, **fields}
        for queue in self.queues.get(session_id, []):
            queue.put_nowait(event)

    def finish(self, turn_id: str, status: str = "completed") -> None:
        turn = self.turn_store[turn_id]
        self.holding.discard(turn_id)
        turn.update(
            status=status,
            usage=None
            if turn_id in self.no_usage
            else {
                "input_tokens": 7,
                "output_tokens": 3,
                "total_tokens": 10,
            },
        )
        session_id = turn["session_id"]
        if status == "completed":
            for _ in range(3):
                self.item_store[turn_id].append(
                    {
                        "id": self._id("cmd"),
                        "type": "command_execution",
                        "status": "completed",
                        "turn_id": turn_id,
                        "command": "echo evidence",
                        "exit_code": 0,
                    }
                )
            item = {
                "id": self._id("msg"),
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "phase": "final_answer",
                "turn_id": turn_id,
                "content": [{"type": "output_text", "text": "Completed answer."}],
            }
            self.item_store[turn_id].append(item)
            self.emit(session_id, "agent.session.turn.item.done", turn_id=turn_id, item=item)
        self.emit(session_id, "agent.session.turn." + status, turn_id=turn_id, turn=dict(turn))
        self.sessions_store[session_id]["status"] = "idle"

    def release(self) -> None:
        for turn in self.turn_store.values():
            if turn["status"] == "in_progress":
                self.finish(turn["id"])

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1")
        parts = path.strip("/").split("/")
        if parts[:2] != ["agents", "sessions"]:
            return super().handle(request)
        params = dict(request.url.params)
        body = json.loads(request.content) if request.content else {}
        self.requests.append(Recorded(request.method, path, params, request.headers, body))
        match (request.method, parts):
            case ("POST", ["agents", "sessions"]):
                record = {"id": self._id("sess"), "status": "idle", "required_actions": [], **body}
                self.sessions_store[record["id"]] = record
                return httpx.Response(200, json=record)
            case ("GET", ["agents", "sessions"]):
                return self._page(
                    [
                        s
                        for s in self.sessions_store.values()
                        if s["agent_id"] == params["agent_id"]
                    ],
                    params,
                )
            case ("GET", ["agents", "sessions", session_id]):
                return httpx.Response(200, json=self.sessions_store[session_id])
            case ("DELETE", ["agents", "sessions", session_id]):
                self.sessions_store.pop(session_id, None)
                return httpx.Response(204)
            case ("GET", ["agents", "sessions", session_id, "turns"]):
                return self._page(
                    [t for t in self.turn_store.values() if t["session_id"] == session_id], params
                )
            case ("GET", ["agents", "sessions", _, "turns", turn_id]):
                return httpx.Response(200, json=self.turn_store[turn_id])
            case ("GET", ["agents", "sessions", _, "turns", turn_id, "items"]):
                return self._page(self.item_store[turn_id], params)
            case ("GET", ["agents", "sessions", session_id, "events"]):
                queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
                self.queues.setdefault(session_id, []).append(queue)
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"}, stream=EventStream(queue)
                )
            case ("POST", ["agents", "sessions", session_id, "events"]):
                event = body["events"][0]
                if event["type"] == "agent.session.input.cancel":
                    self.cancel_count += 1
                    if self.cancel_conflicts:
                        self.cancel_conflicts -= 1
                        return httpx.Response(409, json={"error": {"code": "conflict_error"}})
                    for turn in list(self.turn_store.values()):
                        if turn["session_id"] == session_id and turn["status"] not in {
                            "completed",
                            "cancelled",
                            "failed",
                        }:
                            self.finish(turn["id"], "cancelled")
                    return httpx.Response(202)
                key = request.headers["Idempotency-Key"]
                if key in self.event_keys:
                    return httpx.Response(202)
                if self.sessions_store[session_id]["status"] != "idle":
                    held = [
                        turn
                        for turn in self.turn_store.values()
                        if turn["session_id"] == session_id
                        and turn["status"] == "in_progress"
                        and turn["id"] in self.holding
                    ]
                    if not held:
                        return httpx.Response(
                            409, json={"error": {"code": "active_turn_not_steerable"}}
                        )
                    # HL-23: input during a turn lands as a `message:user` item of that
                    # turn, before its final answer; no new turn starts.
                    turn_id = held[-1]["id"]
                    self.event_keys[key] = turn_id
                    self.sends.append((session_id, json.dumps(event["input"])))
                    item = {
                        "id": self._id("msg"),
                        "type": "message",
                        "role": "user",
                        "status": "completed",
                        "turn_id": turn_id,
                        "content": [
                            {"type": "input_text", "text": part.get("text", "")}
                            for message in event["input"]
                            for part in message.get("content", [])
                        ],
                    }
                    self.item_store[turn_id].append(item)
                    self.emit(
                        session_id, "agent.session.turn.item.done", turn_id=turn_id, item=item
                    )
                    self.steers.append(turn_id)
                    return httpx.Response(202)
                script = self.scripts.pop(0) if self.scripts else "full"
                turn_id = self._id("turn")
                self.event_keys[key] = turn_id
                self.sends.append((session_id, json.dumps(event["input"])))
                turn = {
                    "id": turn_id,
                    "session_id": session_id,
                    "subagent_id": None,
                    "status": "in_progress",
                    "usage": None,
                }
                self.turn_store[turn_id], self.item_store[turn_id] = turn, []
                self.sessions_store[session_id]["status"] = "in_progress"
                self.emit(
                    session_id, "agent.session.turn.created", turn_id=turn_id, turn=dict(turn)
                )
                self.emit(session_id, "agent.session.environment.ready", turn_id=turn_id)
                self.emit(
                    session_id, "agent.session.turn.in_progress", turn_id=turn_id, turn=dict(turn)
                )
                self.emit(
                    session_id,
                    "agent.session.turn.output_text.delta",
                    turn_id=turn_id,
                    item_id="pending-message",
                    delta="Working",
                )
                if script == "no_usage":
                    self.no_usage.add(turn_id)
                if script == "held":
                    self.holding.add(turn_id)
                    self.held.set()
                else:
                    self.finish(turn_id)
                return httpx.Response(202)
        return httpx.Response(404, json={"error": {"code": "not_found"}})


@dataclass
class AgentsStack:
    harness: CodexAgentsHarness
    api: SessionsApi
    operation: OperationExecutionRequest
    artifacts: MemoryArtifacts
    deletions: RecordingDeletionScheduler


def agents_stack(
    root: Path, scripts: tuple[str, ...] = ("full",), **operation_changes: Any
) -> AgentsStack:
    del root
    from tests.unit.operations.test_operation_execution import operation_request

    pack = load_pack(SHIPPED_PACK)
    api = SessionsApi(scripts=list(scripts))
    artifacts, deletions = MemoryArtifacts(), RecordingDeletionScheduler()
    binding = ProviderExecutionBinding.sealed(
        lane_profile="codex_agents",
        model={"profile": "hosted.default", "model_id": "gpt-6.1-sol"},
        auth={"profile": "codex_agents.api", "billing_mode": "api"},
        environment={
            "kind": "provider_hosted",
            "provider": "openai",
            "environment_ref": "ai-engineer-knowledge",
            "expected_revision": "pack-v1",
        },
        workspace_policy={
            "mode": "provider_workspace",
            "reuse": "none",
            "dirty_input": "reject",
            "cleanup": "retain",
        },
        materialization_digest=pack.digest,
        requirements={"describe_digest": CODEX_AGENTS_DESCRIBE.digest},
        policy_digest=DIGEST,
        pins={"sdk.openai": "3.29.0"},
        provider_options={"provider": "codex_agents"},
        budgets={"max_turns": 4, "max_segments": 16, "wall_clock_s": 3600},
        task_queue="mc-ai-engineer-lane-hosted",
    )
    operation = OperationExecutionRequest.model_validate(
        {
            **operation_request(prompt="Summarize the release notes.").model_dump(mode="python"),
            "request_scope": SCOPE,
            "execution_runtime": "codex",
            "lane_profile": "codex_agents",
            **lane_fields(None),
            **lane_fields(binding),
            "native_placement": None,
            "budget_limits": {"model.turns": 4, "tokens.total": 100_000},
            **operation_changes,
        }
    )
    harness = agents_harness(api, artifacts, deletions)
    return AgentsStack(harness, api, operation, artifacts, deletions)


def agents_harness(
    api: SessionsApi, artifacts: MemoryArtifacts, deletions: RecordingDeletionScheduler
) -> CodexAgentsHarness:
    client = api.client()
    return CodexAgentsHarness(
        client=client,
        preparer=CodexAgentsPreparer(
            client,
            WorkerEnvironmentSource(
                {"MC_AI_ENGINEER_GITHUB_READONLY_TOKEN": "test-readonly-token"}
            ),
        ),
        pack=load_pack(SHIPPED_PACK),
        artifacts=artifacts,
        retention=SessionRetentionService(deletions),
        poll_interval_s=0.001,
    )

"""The one Codex app-server fake: the FIXTURE app-server, its hook engine and the codex lane stack.

Formerly `tests/unit/codex/fixture_app_server.py`:

FIXTURE app-server: an in-process stand-in for `codex app-server` (MP-08 tests).

FIXTURE ONLY. Nothing here is Codex. It speaks the pinned app-server protocol v2 shapes
(`tests/fixtures/provider_frames/codex/schema/`) over an in-memory message channel so the
transport, the harness and `lane.turn` are exercised end to end without a CLI, a login or a
model turn. Scripts under `tests/fixtures/provider_frames/codex/scripts/*.jsonl` (first line
`"_fixture"`) describe what one turn emits; the server persists threads and turns to a shared
`Disk` so a relaunch (`FixtureLauncher`) can `thread/resume` and `thread/read` history the
way the real server loads a thread from disk.

Behaviours the tests switch on:

- `lose_response`: the server does the work but never answers that request (lost receipt);
- `capacity_refusals`: `turn/start` is refused with `codexErrorInfo: usageLimitExceeded`;
- `complete_before_steer`: the active turn completes right before a `turn/steer` arrives, so
  the steer is refused (`expectedTurnId` no longer active): deterministic stale target;
- a `turn/start` while a turn is active is recorded in `steer_by_turn_start` (the real
  server treats it as a steer; the lane must never cause it);
- a `disconnect` script step closes the channel mid-turn while the turn finishes "offline"
  (the fixture process keeps writing the disk the way a surviving Codex process would);
- `hooks/list` and a `tool` script step go through the FIXTURE hook engine
  (the hook engine below): the launch's `CODEX_HOME` decides which projected hooks are trusted,
  and a trusted `PreToolUse` hook that refuses blocks the tool (`declined`);
- `thread/fork` (cross-provider control) copies the source thread's turns through
  `lastTurnId` (inclusive; every turn when absent) into a new thread on the shared disk, so
  a later launch can `thread/resume` the fork; `forks` records each request. An in-progress
  `lastTurnId` is refused as the real server documents.

Formerly `tests/unit/codex/fixture_hooks.py`:

FIXTURE stand-in for Codex's command-hook engine (MO-03 tests). Nothing here is Codex.

What the fixture app-server does with the projected `.codex/hooks.json`, modelled on the
pinned facts (research/codex.md "Hooks"; `adapters/codex/hook_trust.py`):

- the project layer loads only for a project trusted in `CODEX_HOME/config.toml`
  (`[projects."<path>"]`, the path in the host's form); `-c` overrides are ignored, as
  codex-cli 0.162.1 ignored them for hooks when probed;
- `hooks/list` reports each handler's key, current hash and trust status from the home's
  `[hooks.state]` (the hash is the production `hook_hash`, whose formula is pinned against
  the real 0.162.1 app-server by `tests/fixtures/provider_frames/codex/hooks_list/`);
- `PreToolUse` runs every enabled, trusted handler whose matcher matches the tool, as a
  subprocess in the workspace with the Codex payload on stdin; exit 2 or
  `permissionDecision: deny` blocks the tool;
- `skills/list` and `config/read` (MO-34) answer in the shapes the real 0.162.1 server
  recorded (`tests/fixtures/projections/discovery/codex.recorded.json`): the workspace's
  `.agents/skills` as `repo` skills, and the trusted project's `.codex/config.toml` MCP servers.

Formerly `tests/unit/codex/support.py`:

Shared builders for the MP-08 codex lane tests (FIXTURES: nothing here is a provider).

A sealed `mc.execution_binding.v2` for the `codex` profile, the operation that carries it,
a static Host Projection (digest-pinned by the binding), a temporary-directory workspace
leaser, an in-memory artifact sink, a static auth admission (secret-free) and an approval
rig: MP-11's in-memory approval store (FIXTURE semantics of `adapters/postgres/approvals`)
behind a real `ApprovalBroker`, with a scripted reviewer that resolves each task through the
real `HumanTaskService` as soon as it is persisted. `codex_stack` composes the harness over
the fixture app-server launcher and `tests.fixtures.lane_turns.lane_stack`'s governed
in-memory boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from mission_control.adapters.codex.harness import CodexLocalHarness, CodexLocalSettings
from mission_control.adapters.codex.hook_trust import HOOKS_FILE, hook_hash
from mission_control.adapters.codex.launcher import LaunchedAppServer, LaunchSpec
from mission_control.adapters.codex.protocol import PINNED_CODEX_CLI_VERSION, PINNED_SCHEMA_SHA256
from mission_control.adapters.codex.transport import AppServerConnection, MessageChannel
from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.environments.mission_layer import MissionLayerService
from mission_control.application.execution.approvals import (
    ApprovalResolutionRequest,
    ApprovalTaskPacket,
    ApprovalTaskView,
)
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.approvals_memory import (
    InMemoryApprovalStore,
    StaticApprovalContext,
)
from mission_control.application.execution.auth_admission import AuthAdmission
from mission_control.application.execution.child_environment import provider_child_environment
from mission_control.application.execution.harness.hook_callbacks import HookCallbackService
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.application.human_tasks.memory import InMemoryHumanTaskRepository
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.application.secrets.delivery import ProcessSecretDelivery
from mission_control.domain.agentic_components.projection import (
    HostProjection,
    ProjectedFile,
    ProjectionReport,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding, WorkspacePolicyPin
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lane_turns import CleanupOutcome, LaneTurnRequest
from mission_control.domain.frames.contracts import LaneProfile
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.lane_turns import LANE_QUEUE, SCOPE, LaneStack, lane_stack
from tests.support.artifacts import MemoryArtifacts

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "provider_frames" / "codex"
SCRIPTS = FIXTURE_ROOT / "scripts"
FIXTURE_VERSION = f"codex-cli {PINNED_CODEX_CLI_VERSION} (FIXTURE app-server, not Codex)"
_EOF = object()


def load_script(name: str) -> list[dict[str, Any]]:
    """The steps of one scripted turn (the `_fixture` header line is checked, not replayed)."""

    lines = (SCRIPTS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    assert rows and rows[0].get("_fixture"), f"{name}: the first line labels the fixture"
    assert rows[0].get("recorded") is False, f"{name}: a fixture is never claimed recorded"
    return rows[1:]


class MemoryChannel:
    """One side of an in-process duplex channel (dicts in queues; `None` is EOF)."""

    def __init__(self, inbox: asyncio.Queue[Any], outbox: asyncio.Queue[Any]) -> None:
        self._inbox = inbox
        self._outbox = outbox
        self.closed = False
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: Mapping[str, Any]) -> None:
        if self.closed:
            raise ConnectionError("channel closed")
        copy = json.loads(json.dumps(dict(message)))  # wire-faithful: JSON values only
        self.sent.append(copy)
        await self._outbox.put(copy)

    async def receive(self) -> dict[str, Any] | None:
        if self.closed:
            return None
        item = await self._inbox.get()
        if item is _EOF:
            self.closed = True
            return None
        return dict(item)

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            await self._outbox.put(_EOF)
            await self._inbox.put(_EOF)


def channel_pair() -> tuple[MemoryChannel, MemoryChannel]:
    a_to_b: asyncio.Queue[Any] = asyncio.Queue()
    b_to_a: asyncio.Queue[Any] = asyncio.Queue()
    return MemoryChannel(b_to_a, a_to_b), MemoryChannel(a_to_b, b_to_a)


@dataclass
class Disk:
    """FIXTURE: what the real server persists under CODEX_HOME (threads and their turns)."""

    threads: dict[str, dict[str, Any]] = field(default_factory=dict)
    usage_totals: dict[str, dict[str, int]] = field(default_factory=dict)
    counter: int = 0

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter:04d}"


@dataclass
class FixtureAppServer:
    disk: Disk
    scripts: list[list[dict[str, Any]]]
    lose_response: set[str] = field(default_factory=set)
    capacity_refusals: int = 0
    complete_before_steer: bool = False
    records: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    steer_by_turn_start: int = 0
    steers: list[dict[str, Any]] = field(default_factory=list)
    interrupts: list[str] = field(default_factory=list)
    approvals: list[tuple[str, Any]] = field(default_factory=list)
    compactions: int = 0
    forks: list[dict[str, Any]] = field(default_factory=list)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    held: asyncio.Event = field(default_factory=asyncio.Event)
    steer_received: asyncio.Event = field(default_factory=asyncio.Event)
    offline: bool = False
    active: dict[str, str] = field(default_factory=dict)  # thread -> active turn
    # The launch that started this process (its CODEX_HOME holds the hook trust).
    spec: LaunchSpec | None = None
    hook_runs: list[HookRun] = field(default_factory=list)
    _channel: MessageChannel | None = None
    _next_server_id: int = 1
    _answers: dict[int, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    _interrupted: dict[str, asyncio.Event] = field(default_factory=dict)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)

    # --- wire ---------------------------------------------------------------------------------

    async def serve(self, channel: MessageChannel) -> None:
        self._channel = channel
        try:
            while True:
                message = await channel.receive()
                if message is None:
                    return
                await self._handle(message)
        finally:
            self.offline = True

    async def _send(self, message: dict[str, Any]) -> None:
        if self.offline or self._channel is None:
            return
        with suppress(ConnectionError):
            await self._channel.send(message)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _respond(self, request_id: Any, result: dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def _error(
        self, request_id: Any, code: int, message: str, data: dict[str, Any] | None = None
    ) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        await self._send({"jsonrpc": "2.0", "id": request_id, "error": error})

    async def server_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a server-originated request and wait for the client's answer."""

        request_id = self._next_server_id
        self._next_server_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._answers[request_id] = future
        await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return await future

    async def _handle(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method is None and "id" in message:
            future = self._answers.pop(message["id"], None)
            if future is not None and not future.done():
                if "error" in message:
                    future.set_result({"error": message["error"]})
                else:
                    future.set_result({"result": message.get("result")})
            return
        if "id" not in message:
            self.records.append((str(method), dict(message.get("params") or {})))
            return  # client notification (`initialized`)
        request_id = message["id"]
        params = dict(message.get("params") or {})
        self.records.append((str(method), params))
        lose = method in self.lose_response
        if lose:
            self.lose_response.discard(str(method))

        async def reply(result: dict[str, Any]) -> None:
            if not lose:
                await self._respond(request_id, result)

        if method == "initialize":
            await reply(
                {
                    "userAgent": FIXTURE_VERSION,
                    "platformOs": "fixture",
                    "platformFamily": "unix",
                    "codexHome": "/fixture/codex-home",
                }
            )
        elif method == "account/login/start":
            if params.get("apiKey") == "fixture-rejected-key":
                await self._error(request_id, -32000, "fixture-rejected-key must never escape")
                return
            await reply({"type": "apiKey"})
        elif method == "account/read":
            await reply({"account": {"type": "apiKey"}, "requiresOpenaiAuth": True})
        elif method == "thread/start":
            thread = self._new_thread(params)
            await reply(
                {
                    "thread": self._thread_view(thread["id"], include_turns=False),
                    "model": params.get("model") or "fixture-model",
                    "approvalPolicy": params.get("approvalPolicy") or "on-request",
                    "approvalsReviewer": "user",
                    "cwd": params.get("cwd") or "/fixture",
                    "modelProvider": "openai",
                    "sandbox": {"type": "workspaceWrite"},
                }
            )
            await self.notify("thread/started", {"thread": self._thread_view(thread["id"], False)})
        elif method == "thread/resume":
            thread_id = str(params.get("threadId"))
            if thread_id not in self.disk.threads:
                await self._error(request_id, -32602, f"unknown thread {thread_id}")
                return
            await reply(
                {
                    "thread": self._thread_view(thread_id, include_turns=True),
                    "model": params.get("model") or "fixture-model",
                    "approvalPolicy": "on-request",
                    "approvalsReviewer": "user",
                    "cwd": params.get("cwd") or "/fixture",
                    "modelProvider": "openai",
                    "sandbox": {"type": "workspaceWrite"},
                }
            )
        elif method == "thread/read":
            thread_id = str(params.get("threadId"))
            if thread_id not in self.disk.threads:
                await self._error(request_id, -32602, f"unknown thread {thread_id}")
                return
            await reply({"thread": self._thread_view(thread_id, bool(params.get("includeTurns")))})
        elif method == "thread/fork":
            thread_id = str(params.get("threadId"))
            if thread_id not in self.disk.threads:
                await self._error(request_id, -32602, f"unknown thread {thread_id}")
                return
            last_turn = params.get("lastTurnId")
            source_turns = self.disk.threads[thread_id]["turns"]
            if last_turn is not None:
                ids = [turn["id"] for turn in source_turns]
                if last_turn not in ids:
                    await self._error(request_id, -32602, f"unknown turn {last_turn}")
                    return
                if self.active.get(thread_id) == last_turn:
                    await self._error(request_id, -32602, "lastTurnId is in progress")
                    return
                source_turns = source_turns[: ids.index(last_turn) + 1]
            forked = self._new_thread(params)
            forked["turns"] = json.loads(json.dumps(source_turns))
            forked["forkedFromId"] = thread_id
            self.forks.append(dict(params))
            await reply(
                {
                    "thread": self._thread_view(forked["id"], include_turns=False),
                    "model": params.get("model") or "fixture-model",
                    "approvalPolicy": params.get("approvalPolicy") or "on-request",
                    "approvalsReviewer": "user",
                    "cwd": params.get("cwd") or "/fixture",
                    "modelProvider": "openai",
                    "sandbox": {"type": "workspaceWrite"},
                }
            )
            await self.notify("thread/started", {"thread": self._thread_view(forked["id"], False)})
        elif method == "turn/start":
            thread_id = str(params.get("threadId"))
            if thread_id not in self.disk.threads:
                await self._error(request_id, -32602, f"unknown thread {thread_id}")
                return
            if thread_id in self.active:
                # The real server steers an active turn on `turn/start`; the lane must not.
                self.steer_by_turn_start += 1
                await reply({"turn": self._turn_view(thread_id, self.active[thread_id], True)})
                return
            if self.capacity_refusals > 0:
                self.capacity_refusals -= 1
                await self._error(
                    request_id,
                    -32000,
                    "usage limit reached",
                    {"codexErrorInfo": "usageLimitExceeded"},
                )
                return
            turn = self._new_turn(thread_id, params)
            await reply({"turn": self._turn_view(thread_id, turn["id"], True)})
            self._tasks.append(asyncio.create_task(self._run_turn(thread_id, turn["id"])))
        elif method == "turn/steer":
            thread_id = str(params.get("threadId"))
            expected = str(params.get("expectedTurnId"))
            if self.complete_before_steer and self.active.get(thread_id) == expected:
                await self._complete_turn(thread_id, expected, "completed")
            if self.active.get(thread_id) != expected:
                await self._error(request_id, -32602, "expectedTurnId is not the active turn")
                return
            self.steers.append(params)
            text = "".join(
                str(item.get("text", ""))
                for item in params.get("input", [])
                if isinstance(item, dict)
            )
            item = {
                "type": "userMessage",
                "id": self.disk.next_id("item"),
                "content": [{"type": "text", "text": text}],
                "clientId": params.get("clientUserMessageId"),
            }
            self._append_item(thread_id, expected, item)
            await self.notify(
                "item/completed",
                {
                    "threadId": thread_id,
                    "turnId": expected,
                    "item": item,
                    "completedAtMs": 1760000000000,
                },
            )
            self.steer_received.set()
            await reply({"turnId": expected})
        elif method == "turn/interrupt":
            thread_id, turn_id = str(params.get("threadId")), str(params.get("turnId"))
            self.interrupts.append(turn_id)
            if self.active.get(thread_id) != turn_id:
                await self._error(request_id, -32602, "turn is not active")
                return
            await reply({})
            self._interrupted.setdefault(turn_id, asyncio.Event()).set()
            self.release.set()
        elif method == "hooks/list":
            cwds = [str(cwd) for cwd in params.get("cwds") or ()]
            home = self.spec.codex_home if self.spec is not None else None
            await reply(await asyncio.to_thread(hooks_list, cwds, home))
        elif method == "skills/list":
            cwds = [str(cwd) for cwd in params.get("cwds") or ()]
            await reply(await asyncio.to_thread(skills_list, cwds))
        elif method == "config/read":
            home = self.spec.codex_home if self.spec is not None else None
            await reply(await asyncio.to_thread(config_read, str(params.get("cwd")), home))
        elif method == "thread/compact/start":
            thread_id = str(params.get("threadId"))
            self.compactions += 1
            await reply({})
            turn_id = self.active.get(thread_id) or "compaction"
            item = {"type": "contextCompaction", "id": self.disk.next_id("item")}
            await self.notify(
                "item/started",
                {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": item,
                    "startedAtMs": 1760000000000,
                },
            )
            await self.notify(
                "item/completed",
                {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": item,
                    "completedAtMs": 1760000000001,
                },
            )
            await self.notify("thread/compacted", {"threadId": thread_id, "turnId": turn_id})
        else:
            await self._error(request_id, -32601, f"method not found: {method}")

    # --- disk and views ---------------------------------------------------------------------

    def _new_thread(self, params: dict[str, Any]) -> dict[str, Any]:
        thread_id = self.disk.next_id("thr")
        self.disk.threads[thread_id] = {
            "id": thread_id,
            "cwd": params.get("cwd") or "/fixture",
            "model": params.get("model") or "fixture-model",
            "turns": [],
        }
        return self.disk.threads[thread_id]

    def _new_turn(self, thread_id: str, params: dict[str, Any]) -> dict[str, Any]:
        turn_id = self.disk.next_id("turn")
        text = "".join(
            str(item.get("text", "")) for item in params.get("input", []) if isinstance(item, dict)
        )
        user = {
            "type": "userMessage",
            "id": self.disk.next_id("item"),
            "content": [{"type": "text", "text": text}],
            "clientId": params.get("clientUserMessageId"),
        }
        turn = {
            "id": turn_id,
            "status": "inProgress",
            "items": [user],
            "error": None,
            "startedAt": 1760000000,
        }
        self.disk.threads[thread_id]["turns"].append(turn)
        self.active[thread_id] = turn_id
        return turn

    def _turn_record(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        for turn in self.disk.threads[thread_id]["turns"]:
            if turn["id"] == turn_id:
                return turn
        raise KeyError(turn_id)

    def _append_item(self, thread_id: str, turn_id: str, item: dict[str, Any]) -> None:
        turn = self._turn_record(thread_id, turn_id)
        existing = [index for index, old in enumerate(turn["items"]) if old["id"] == item["id"]]
        if existing:
            turn["items"][existing[0]] = item
        else:
            turn["items"].append(item)

    def _turn_view(self, thread_id: str, turn_id: str, full: bool) -> dict[str, Any]:
        turn = self._turn_record(thread_id, turn_id)
        return {
            "id": turn["id"],
            "status": turn["status"],
            "items": list(turn["items"]) if full else [],
            "error": turn.get("error"),
            "startedAt": turn.get("startedAt"),
            "completedAt": turn.get("completedAt"),
            "durationMs": turn.get("durationMs"),
        }

    def _thread_view(self, thread_id: str, include_turns: bool) -> dict[str, Any]:
        thread = self.disk.threads[thread_id]
        active = self.active.get(thread_id)
        status: dict[str, Any] = (
            {"type": "active", "activeFlags": []} if active else {"type": "idle"}
        )
        return {
            "id": thread_id,
            "cliVersion": FIXTURE_VERSION,
            "createdAt": 1760000000,
            "updatedAt": 1760000000,
            "cwd": thread["cwd"],
            "ephemeral": False,
            "model": thread["model"],
            "modelProvider": "openai",
            "preview": "",
            "projectId": None,
            "sessionId": f"sess-{thread_id}",
            "forkedFromId": thread.get("forkedFromId"),
            "path": None,
            "source": "appServer",
            "status": status,
            "turns": (
                [self._turn_view(thread_id, turn["id"], True) for turn in thread["turns"]]
                if include_turns
                else []
            ),
        }

    # --- the scripted turn --------------------------------------------------------------------

    async def _run_turn(self, thread_id: str, turn_id: str) -> None:
        script: list[dict[str, Any]] = (
            self.scripts.pop(0) if self.scripts else [{"step": "complete"}]
        )
        await self.notify(
            "turn/started",
            {"threadId": thread_id, "turn": self._turn_view(thread_id, turn_id, False)},
        )
        interrupted = self._interrupted.setdefault(turn_id, asyncio.Event())
        for step in script:
            if interrupted.is_set():
                break
            kind = step.get("step")
            if kind == "item":
                item = dict(step["item"])
                item.setdefault("id", self.disk.next_id("item"))
                started = {**item, "status": "inProgress"} if "status" in item else dict(item)
                await self.notify(
                    "item/started",
                    {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": started,
                        "startedAtMs": 1760000000000,
                    },
                )
                self._append_item(thread_id, turn_id, item)
                await self.notify(
                    "item/completed",
                    {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": item,
                        "completedAtMs": 1760000000001,
                    },
                )
            elif kind == "delta":
                await self.notify(
                    step.get("method", "item/agentMessage/delta"),
                    {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "itemId": step["item_id"],
                        "delta": step["delta"],
                    },
                )
            elif kind == "usage":
                usage = {
                    "inputTokens": step["input"],
                    "cachedInputTokens": step.get("cached_input", 0),
                    "cacheWriteInputTokens": step.get("cache_write_input", 0),
                    "outputTokens": step["output"],
                    "reasoningOutputTokens": 0,
                    "totalTokens": step["input"] + step["output"],
                }
                total = self.disk.usage_totals.setdefault(thread_id, dict.fromkeys(usage, 0))
                for name, value in usage.items():
                    total[name] += value
                await self.notify(
                    "thread/tokenUsage/updated",
                    {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "tokenUsage": {
                            "last": usage,
                            "total": dict(total),
                            "modelContextWindow": step.get("window", 272000),
                        },
                    },
                )
            elif kind == "notify":
                await self.notify(
                    step["method"],
                    {"threadId": thread_id, "turnId": turn_id, **dict(step.get("params") or {})},
                )
            elif kind == "approval":
                item_id = self.disk.next_id("item")
                params = {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "itemId": item_id,
                    "startedAtMs": 1760000000000,
                    **dict(step.get("params") or {}),
                }
                answer = await self.server_request(step["method"], params)
                self.approvals.append((step["method"], answer))
                await self.notify(
                    "serverRequest/resolved",
                    {"threadId": thread_id, "requestId": self._next_server_id - 1},
                )
                decision = (
                    (answer.get("result") or {}).get("decision") if "result" in answer else None
                )
                status = "completed" if decision in {"accept", "acceptForSession"} else "declined"
                item = {
                    "type": step.get("item_type", "commandExecution"),
                    "id": item_id,
                    "command": params.get("command", ""),
                    "cwd": "/fixture",
                    "commandActions": [],
                    "status": status,
                    "exitCode": 0 if status == "completed" else None,
                }
                self._append_item(thread_id, turn_id, item)
                await self.notify(
                    "item/completed",
                    {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": item,
                        "completedAtMs": 1760000000002,
                    },
                )
            elif kind == "tool":
                await self._run_tool(thread_id, turn_id, step)
            elif kind == "hold":
                self.held.set()
                waiter = asyncio.create_task(self.release.wait())
                stop = asyncio.create_task(interrupted.wait())
                await asyncio.wait({waiter, stop}, return_when=asyncio.FIRST_COMPLETED)
                for task in (waiter, stop):
                    task.cancel()
            elif kind == "wait_steer":
                self.held.set()
                waiter = asyncio.create_task(self.steer_received.wait())
                stop = asyncio.create_task(interrupted.wait())
                await asyncio.wait({waiter, stop}, return_when=asyncio.FIRST_COMPLETED)
                for task in (waiter, stop):
                    task.cancel()
            elif kind == "disconnect":
                self.held.set()
                assert self._channel is not None
                await self._channel.close()
                self.offline = True
            elif kind == "fail":
                info = step.get("codexErrorInfo", "other")
                await self.notify(
                    "error",
                    {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "error": {
                            "message": step.get("message", "fixture failure"),
                            "codexErrorInfo": info,
                        },
                        "willRetry": False,
                    },
                )
                await self._complete_turn(
                    thread_id,
                    turn_id,
                    "failed",
                    error={
                        "message": step.get("message", "fixture failure"),
                        "codexErrorInfo": info,
                    },
                )
                return
            elif kind == "complete":
                await self._complete_turn(thread_id, turn_id, step.get("status", "completed"))
                return
        if interrupted.is_set():
            await self._complete_turn(thread_id, turn_id, "interrupted")
        elif self.active.get(thread_id) == turn_id:
            await self._complete_turn(thread_id, turn_id, "completed")

    async def _run_tool(self, thread_id: str, turn_id: str, step: dict[str, Any]) -> None:
        """A shell tool call gated by the trusted `PreToolUse` hooks (run off the loop, so a
        hook may call back into this process's event loop)."""

        thread = self.disk.threads[thread_id]
        payload = {
            "session_id": thread_id,
            "turn_id": turn_id,
            "model": thread["model"],
            "transcript_path": None,
            "tool_name": step.get("tool_name", "Bash"),
            "tool_input": dict(step.get("tool_input") or {}),
            "tool_use_id": step["tool_use_id"],
        }
        home = self.spec.codex_home if self.spec is not None else None
        runs = await asyncio.to_thread(run_pre_tool_use, Path(thread["cwd"]), home, payload)
        self.hook_runs.extend(runs)
        blocked = any(run.blocked for run in runs)
        item = {
            "type": "commandExecution",
            "id": self.disk.next_id("item"),
            "command": str(payload["tool_input"].get("command", "")),
            "cwd": thread["cwd"],
            "commandActions": [],
            "status": "declined" if blocked else "completed",
            "exitCode": None if blocked else 0,
        }
        self._append_item(thread_id, turn_id, item)
        await self.notify(
            "item/completed",
            {
                "threadId": thread_id,
                "turnId": turn_id,
                "item": item,
                "completedAtMs": 1760000000003,
            },
        )

    async def _complete_turn(
        self, thread_id: str, turn_id: str, status: str, *, error: dict[str, Any] | None = None
    ) -> None:
        turn = self._turn_record(thread_id, turn_id)
        if turn["status"] in {"completed", "interrupted", "failed"}:
            return
        turn["status"] = status
        turn["error"] = error
        turn["completedAt"] = 1760000010
        turn["durationMs"] = 10_000
        if self.active.get(thread_id) == turn_id:
            del self.active[thread_id]
        await self.notify(
            "turn/completed",
            {"threadId": thread_id, "turn": self._turn_view(thread_id, turn_id, True)},
        )
        await self.notify(
            "thread/status/changed", {"threadId": thread_id, "status": {"type": "idle"}}
        )


@dataclass
class FixtureLaunch:
    server: FixtureAppServer
    client: MemoryChannel
    spec: LaunchSpec
    task: asyncio.Task[None]
    connection: AppServerConnection


@dataclass
class FixtureLauncher:
    """`AppServerLauncher` FIXTURE: each launch is a fresh fixture server over the shared disk."""

    scripts: list[Sequence[dict[str, Any]]] = field(default_factory=list)
    # Per launch index (0 = first app-server): the scripts that process runs instead.
    launch_scripts: dict[int, list[Sequence[dict[str, Any]]]] = field(default_factory=dict)
    disk: Disk = field(default_factory=Disk)
    lose_response: set[str] = field(default_factory=set)
    capacity_refusals: int = 0
    complete_before_steer: bool = False
    request_timeout_s: float = 2.0
    launches: list[FixtureLaunch] = field(default_factory=list)
    fail_launch: bool = False
    launched: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def versions(self) -> Mapping[str, str]:
        return {"codex_cli": PINNED_CODEX_CLI_VERSION, "fixture": "true"}

    @property
    def server(self) -> FixtureAppServer:
        return self.launches[-1].server

    async def launch(self, spec: LaunchSpec) -> LaunchedAppServer:
        if self.fail_launch:
            raise OSError("fixture launcher refused to start")
        client, remote = channel_pair()
        server = FixtureAppServer(
            disk=self.disk,
            scripts=[
                list(script) for script in self.launch_scripts.get(len(self.launches), self.scripts)
            ],
            lose_response=set(self.lose_response),
            capacity_refusals=self.capacity_refusals,
            complete_before_steer=self.complete_before_steer,
            spec=spec,
        )
        self.lose_response = set()
        self.capacity_refusals = 0
        task = asyncio.create_task(server.serve(remote), name="fixture-app-server")
        connection = AppServerConnection(client, request_timeout_s=self.request_timeout_s)
        await connection.open()
        self.launches.append(FixtureLaunch(server, client, spec, task, connection))
        self.launched.set()
        return LaunchedAppServer(connection=connection, versions=dict(self.versions))

    async def shutdown(self) -> None:
        for launch in self.launches:
            launch.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await launch.task


_EVENT_LABEL = re.compile(r"(?<!^)(?=[A-Z])")


@dataclass(frozen=True)
class HookRun:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def blocked(self) -> bool:
        if self.exit_code == 2:
            return True
        try:
            out = json.loads(self.stdout or "{}")
        except ValueError:
            return False
        specific = out.get("hookSpecificOutput") or {}
        return specific.get("permissionDecision") == "deny" or out.get("decision") == "block"


def _config(codex_home: Path | None) -> dict[str, Any]:
    path = None if codex_home is None else codex_home / "config.toml"
    if path is None or not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _handlers(cwd: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Every handler of the trusted project's hooks file, with Codex's listing fields."""

    project = (config.get("projects") or {}).get(str(cwd)) or {}
    source = cwd / HOOKS_FILE
    if project.get("trust_level") != "trusted" or not source.is_file():
        return []
    states = (config.get("hooks") or {}).get("state") or {}
    document = json.loads(source.read_text(encoding="utf-8"))
    handlers: list[dict[str, Any]] = []
    for event, groups in (document.get("hooks") or {}).items():
        label = _EVENT_LABEL.sub("_", event).lower()
        for group_index, group in enumerate(groups or ()):
            matcher = group.get("matcher")
            for handler_index, handler in enumerate(group.get("hooks") or ()):
                key = f"{source}:{label}:{group_index}:{handler_index}"
                current = hook_hash(event, matcher, handler)
                state = states.get(key) or {}
                trusted = state.get("trusted_hash")
                status = (
                    "untrusted"
                    if trusted is None
                    else ("trusted" if trusted == current else "modified")
                )
                handlers.append(
                    {
                        "key": key,
                        "eventName": event[0].lower() + event[1:],
                        "nativeEvent": event,
                        "handlerType": "command",
                        "command": handler.get("command"),
                        "matcher": matcher,
                        "sourcePath": str(source),
                        "source": "project",
                        "isManaged": False,
                        "enabled": state.get("enabled", True),
                        "currentHash": current,
                        "trustStatus": status,
                    }
                )
    return handlers


def hooks_list(cwds: list[str], codex_home: Path | None) -> dict[str, Any]:
    """The `hooks/list` result (`HooksListResponse`) for `cwds`."""

    config = _config(codex_home)
    data = []
    for cwd in cwds:
        listed = [
            {key: value for key, value in handler.items() if key != "nativeEvent"}
            for handler in _handlers(Path(cwd), config)
        ]
        data.append({"cwd": cwd, "hooks": listed, "warnings": [], "errors": []})
    return {"data": data}


def skills_list(cwds: list[str]) -> dict[str, Any]:
    """The `skills/list` result for `cwds` (repo skills only; no user or system skills)."""

    data = []
    for cwd in cwds:
        root = Path(cwd) / ".agents" / "skills"
        skills = [
            {
                "name": entry.name,
                "description": "",
                "path": str(entry / "SKILL.md"),
                "scope": "repo",
                "enabled": True,
                "pluginId": None,
            }
            for entry in (sorted(root.iterdir()) if root.is_dir() else ())
            if (entry / "SKILL.md").is_file()
        ]
        data.append({"cwd": cwd, "skills": skills, "errors": []})
    return {"data": data}


def config_read(cwd: str, codex_home: Path | None) -> dict[str, Any]:
    """The `config/read` result's MCP slice: the project layer loads only when trusted."""

    project = (_config(codex_home).get("projects") or {}).get(cwd) or {}
    source = Path(cwd) / ".codex" / "config.toml"
    servers: dict[str, Any] = {}
    if project.get("trust_level") == "trusted" and source.is_file():
        layer = tomllib.loads(source.read_text(encoding="utf-8")).get("mcp_servers") or {}
        servers = {name: {**server, "enabled": True} for name, server in layer.items()}
    return {"config": {"mcp_servers": servers}, "origins": {}}


def _matches(matcher: str | None, tool_name: str) -> bool:
    if matcher in {None, "", "*"}:
        return True
    return re.fullmatch(str(matcher), tool_name) is not None


def run_pre_tool_use(cwd: Path, codex_home: Path | None, payload: dict[str, Any]) -> list[HookRun]:
    """Run the trusted `PreToolUse` handlers matching `payload["tool_name"]` (blocking)."""

    runs: list[HookRun] = []
    for handler in _handlers(cwd, _config(codex_home)):
        if handler["nativeEvent"] != "PreToolUse" or not _matches(
            handler["matcher"], str(payload.get("tool_name", ""))
        ):
            continue
        if handler["trustStatus"] != "trusted" or handler["enabled"] is False:
            continue
        argv = shlex.split(str(handler["command"]))
        if argv and argv[0] == "python":
            argv[0] = sys.executable
        completed = subprocess.run(
            argv,
            input=json.dumps({**payload, "cwd": str(cwd), "hook_event_name": "PreToolUse"}),
            capture_output=True,
            text=True,
            cwd=cwd,
            env=dict(os.environ),
            timeout=60,
            check=False,
        )
        runs.append(
            HookRun(
                command=str(handler["command"]),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        )
    return runs


DIGEST = "sha256:" + "c" * 64
PROFILE = "codex"
REVIEWER = "owner"
FIXTURE_OBSERVATION_DIGEST = "sha256:" + hashlib.sha256(b"codex fixture observation").hexdigest()


FIXTURE_INSTRUCTIONS = "# Mission\n\nUse only the exact bound capabilities.\n"


def static_projection() -> HostProjection:
    """A small codex Host Projection: `.codex/config.toml`, `.codex/hooks.json` and the
    mission overlay as `developer_instructions` (MO-02: no AGENTS.md is written)."""

    return HostProjection(
        profile=LaneProfile.CODEX,
        files=(
            ProjectedFile(
                path=".codex/config.toml",
                content=(
                    b"# Generated by Mission Control Host Projection (FIXTURE).\n"
                    b'[mcp_servers."mc-fixture"]\ncommand = "fixture-mcp"\nenabled = true\n'
                ),
            ),
            ProjectedFile(
                path=".codex/hooks.json",
                content=b'{"hooks": {"PreToolUse": []}}\n',
            ),
        ),
        report=ProjectionReport(requires_trust=("mcp.fixture",)),
        send_options={"developer_instructions": FIXTURE_INSTRUCTIONS},
    )


class StaticProjectionSource:
    def __init__(self, projection: HostProjection | None = None) -> None:
        self.projection = projection or static_projection()
        self.calls = 0

    async def project(
        self, operation: OperationExecutionRequest, *, profile: str, packet_index: str | None
    ) -> HostProjection:
        del operation, packet_index
        assert profile == PROFILE
        self.calls += 1
        return self.projection


def codex_binding(**changes: Any) -> ProviderExecutionBinding:
    fields: dict[str, Any] = {
        "lane_profile": PROFILE,
        "model": {"profile": "codex.default", "model_id": "gpt-5-codex"},
        "auth": {"profile": "codex.owner", "billing_mode": "subscription"},
        "environment": {"kind": "local_workspace", "host_profile": "worker.linux.wsl"},
        "workspace_policy": {
            "mode": "managed_worktree",
            "reuse": "within_run",
            "dirty_input": "reject",
            "cleanup": "retain_until_artifacts_registered",
        },
        "materialization_digest": projection_digest(static_projection()),
        "requirements": {"controls": ["cancel"], "describe_digest": DIGEST},
        "policy_digest": DIGEST,
        "pins": {
            "cli.codex": PINNED_CODEX_CLI_VERSION,
            "schema.app_server_v2": PINNED_SCHEMA_SHA256,
        },
        "provider_options": {
            "provider": "codex_app_server",
            "approval_policy": "on-request",
            "sandbox_mode": "workspace-write",
            "app_server_schema_version": f"v2@{PINNED_CODEX_CLI_VERSION}",
        },
        "budgets": {"max_turns": 4, "max_segments": 8, "wall_clock_s": 3600},
        "task_queue": LANE_QUEUE,
    }
    fields.update(changes)
    return ProviderExecutionBinding.sealed(**fields)


def codex_operation(
    binding: ProviderExecutionBinding | None = None, *, prompt: str | None = None, **changes: Any
) -> OperationExecutionRequest:
    from tests.support.operations import operation_request

    request = operation_request() if prompt is None else operation_request(prompt=prompt)
    payload = request.model_dump(mode="python")
    payload.update(
        request_scope=SCOPE,
        execution_runtime=PROFILE,
        native_placement=None,
        lane_profile=PROFILE,
        **lane_fields(None),
        **lane_fields(binding or codex_binding()),
        budget_limits={"model.turns": 2, "tokens.total": 100_000},
    )
    payload.update(changes)
    return OperationExecutionRequest.model_validate(payload)


@dataclass(frozen=True)
class FakePatch:
    diff: bytes
    untracked: tuple[str, ...] = ()


@dataclass
class TmpLeaser:
    """FIXTURE workspace leaser: one temporary directory per lease, no git."""

    root: Path
    leases: dict[UUID, WorkspaceLease] = field(default_factory=dict)
    released: list[tuple[UUID, str | None, str | None]] = field(default_factory=list)
    remove_on_release: bool = False

    async def acquire(
        self,
        *,
        request_scope: str,
        lane_profile: str,
        harness_execution_id: UUID,
        generation: int,
        run_id: str,
        attempt_no: int,
        repository: str | None,
        base_ref: str,
        policy: WorkspacePolicyPin,
    ) -> WorkspaceLease:
        del policy
        for lease in self.leases.values():
            if lease.harness_execution_id == harness_execution_id and not lease.released:
                return lease
        path = self.root / f"lease-{harness_execution_id.hex[:12]}-g{generation}"
        path.mkdir(parents=True, exist_ok=True)
        lease = WorkspaceLease(
            lease_id=uuid4(),
            request_scope=request_scope,
            lease_key=f"{lane_profile}:{harness_execution_id}:{generation}",
            lane_profile=lane_profile,
            harness_execution_id=harness_execution_id,
            generation=generation,
            run_id=run_id,
            attempt_no=attempt_no,
            path=str(path),
            repository=repository,
            base_ref=base_ref,
            base_commit="0" * 40,
            fence=generation,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self.leases[lease.lease_id] = lease
        return lease

    async def find(
        self,
        *,
        request_scope: str,
        lane_profile: str,
        harness_execution_id: UUID,
        generation: int,
    ) -> WorkspaceLease | None:
        del request_scope, lane_profile
        for lease in self.leases.values():
            if lease.harness_execution_id == harness_execution_id and lease.generation == (
                generation
            ):
                return lease
        return None

    async def capture_patch(self, lease: WorkspaceLease, *, exclude: Sequence[str] = ()) -> Any:
        return await asyncio.to_thread(self._capture, Path(lease.path), tuple(exclude))

    @staticmethod
    def _capture(root: Path, exclude: tuple[str, ...]) -> FakePatch:
        files = sorted(
            item.relative_to(root).as_posix()
            for item in root.rglob("*")
            if item.is_file()
            and not any(item.relative_to(root).as_posix().startswith(e) for e in exclude)
        )
        return FakePatch(diff="\n".join(files).encode("utf-8"), untracked=tuple(files))

    async def outputs(self, lease: WorkspaceLease) -> list[tuple[str, bytes]]:
        root = Path(lease.path) / "outputs"
        if not root.is_dir():
            return []
        return [
            (item.relative_to(Path(lease.path)).as_posix(), item.read_bytes())
            for item in sorted(root.rglob("*"))
            if item.is_file()
        ]

    async def release(
        self,
        lease: WorkspaceLease,
        *,
        patch_artifact_ref: str | None,
        snapshot_ref: str | None = None,
        exclude: Sequence[str] = (),
    ) -> WorkspaceLease:
        del exclude
        released = lease.model_copy(
            update={
                "released_at": datetime.now(UTC),
                "patch_artifact_ref": patch_artifact_ref,
                "snapshot_ref": snapshot_ref,
            }
        )
        self.leases[lease.lease_id] = released
        self.released.append((lease.lease_id, patch_artifact_ref, snapshot_ref))
        if self.remove_on_release:
            shutil.rmtree(lease.path, ignore_errors=True)
        return released

    async def cleanup(
        self,
        *,
        request_scope: str,
        lane_profile: str,
        harness_execution_id: UUID,
        generation: int,
    ) -> CleanupOutcome:
        lease = await self.find(
            request_scope=request_scope,
            lane_profile=lane_profile,
            harness_execution_id=harness_execution_id,
            generation=generation,
        )
        if lease is None or not lease.released:
            return "not_required"
        shutil.rmtree(lease.path, ignore_errors=True)
        return "removed"


def admission(route: str = "owner_cli_login", **changes: Any) -> AuthAdmission:
    """A secret-free `mc.auth_admission.v1` for the codex profile (FIXTURE)."""

    fields: dict[str, Any] = {
        "profile_id": "codex.owner",
        "lane_profile": PROFILE,
        "route": route,
        "route_support": "documented",
        "billing_mode": "subscription" if route == "owner_cli_login" else "api",
        "credential_ref": None if route == "owner_cli_login" else "env:OPENAI_API_KEY",
        "env_unset": ("OPENAI_API_KEY", "CODEX_API_KEY") if route == "owner_cli_login" else (),
        "observation_digest": FIXTURE_OBSERVATION_DIGEST,
        "observation_source": "fixture",
        "fixture": True,
        "admitted_at": datetime.now(UTC),
    }
    fields.update(changes)
    return AuthAdmission.model_validate(fields)


@dataclass
class StaticAuth:
    record: AuthAdmission = field(default_factory=admission)
    calls: int = 0

    async def admit(self, binding: ProviderExecutionBinding) -> AuthAdmission:
        assert binding.auth.profile == self.record.profile_id
        self.calls += 1
        return self.record


# --- MP-11 approvals: the real broker over the in-memory FIXTURE stores ----------------------


Decision = str | Mapping[str, Any]


class ReviewingStore(InMemoryApprovalStore):
    """FIXTURE `InMemoryApprovalStore` that records the persist order and, when a reviewer is
    attached, schedules the reviewer as soon as a task is persisted (never before)."""

    def __init__(self) -> None:
        super().__init__()
        self.order: list[tuple[str, str]] = []
        self.reviewer: ScriptedReviewer | None = None

    async def open_task(self, packet: ApprovalTaskPacket, *, actor_ref: str) -> ApprovalTaskView:
        view = await super().open_task(packet, actor_ref=actor_ref)
        self.order.append(("persisted", view.human_task_id))
        if self.reviewer is not None and view.lifecycle == "open":
            self.reviewer.schedule(view)
        return view


@dataclass
class ScriptedReviewer:
    """FIXTURE reviewer: resolves each new approval task through `HumanTaskService` with the
    next scripted decision (`approve`, `deny`, `cancel`, or a full body mapping)."""

    service: HumanTaskService
    store: ReviewingStore
    decisions: list[Decision] = field(default_factory=lambda: ["approve"])
    resolved: list[tuple[str, str]] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)
    _tasks: set[asyncio.Task[None]] = field(default_factory=set)

    def schedule(self, task: ApprovalTaskView) -> None:
        if task.human_task_id in self._seen:
            return
        self._seen.add(task.human_task_id)
        decision = self.decisions.pop(0) if self.decisions else "deny"
        job = asyncio.get_running_loop().create_task(self._resolve(task, decision))
        self._tasks.add(job)
        job.add_done_callback(self._tasks.discard)

    async def _resolve(self, task: ApprovalTaskView, decision: Decision) -> None:
        await asyncio.sleep(0)
        body: dict[str, Any] = {
            "request_id": f"fixture-review:{task.human_task_id}",
            "expected_task_version": task.version,
            "reviewed_digest": task.packet.review_digest,
        }
        if isinstance(decision, str):
            body["decision"] = decision
            if decision == "approve" and task.origin == "provider_question":
                body["answer"] = "fixture answer"
            if decision == "approve" and task.packet.elicitation is not None:
                if task.packet.elicitation.mode == "form":
                    body["elicitation_content"] = dict.fromkeys(
                        task.packet.elicitation.property_names(), "fixture"
                    )
        else:
            body.update(decision)
        await self.service.resolve_approval(
            task.human_task_id,
            ApprovalResolutionRequest.model_validate(body),
            ActorContext(actor_id=REVIEWER),
        )
        self.store.order.append(("resolved", task.human_task_id))
        self.resolved.append((task.human_task_id, str(body["decision"])))


@dataclass
class ApprovalRig:
    store: ReviewingStore
    context: StaticApprovalContext
    broker: ApprovalBroker
    service: HumanTaskService
    reviewer: ScriptedReviewer | None

    def tasks(self) -> list[ApprovalTaskView]:
        return [view for (_scope, _id), view in self.store._tasks.items()]


def approval_rig(
    policy_digest: str,
    *,
    decisions: list[Decision] | None = None,
    review: bool = True,
    connection_ref: str = "worker-a#1",
    generation: int = 1,
) -> ApprovalRig:
    """MP-11 in-memory stores + the real broker; the probe's policy is `policy_digest`."""

    store = ReviewingStore()
    context = StaticApprovalContext(generation, policy_digest)
    broker = ApprovalBroker(
        store, store, probe=context, connection_ref=connection_ref, poll_seconds=0.01
    )
    service = HumanTaskService(
        InMemoryHumanTaskRepository(),
        request_scope=SCOPE,
        approvals=store,
        approval_wake=broker.hub,
    )
    reviewer = None
    if review:
        reviewer = ScriptedReviewer(
            service, store, decisions=list(decisions) if decisions is not None else ["approve"]
        )
        store.reviewer = reviewer
    return ApprovalRig(store, context, broker, service, reviewer)


FAKE_WORKER_ENV: Mapping[str, str] = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/home/worker",
    "OPENAI_API_KEY": "fixture-codex-api-credential",
    "ANTHROPIC_API_KEY": "sk-ant-fixture-not-a-real-key-000000",
    "CURSOR_API_KEY": "key_fixturefixturefixturefixture",
    "MC_FIXTURE_TOKEN": "fixture-token-value",
    "TAVILY_API_KEY": "tvly-fixture",
}


@dataclass
class CodexStack:
    harness: CodexLocalHarness
    launcher: FixtureLauncher
    leaser: TmpLeaser
    artifacts: MemoryArtifacts
    auth: StaticAuth
    rig: ApprovalRig | None
    operation: OperationExecutionRequest
    lanes: LaneStack

    @property
    def identity(self) -> LaneExecutionIdentity:
        return LaneExecutionIdentity.of(self.operation, PROFILE, 1)

    @property
    def heid(self) -> str:
        return str(self.identity.harness_execution_id)

    @property
    def send_key(self) -> str:
        return f"{self.identity.harness_execution_id}:1:turn:1"

    def turn(self, **changes: Any) -> LaneTurnRequest:
        return LaneTurnRequest.model_validate(
            {
                "operation": self.operation,
                "lane_profile": PROFILE,
                "generation": 1,
                **changes,
            }
        )

    def frames(self) -> list[Any]:
        execution = self.lanes.frames._executions.get(self.identity.harness_execution_id)
        if execution is None:
            return []
        return sorted(execution.frames.values(), key=lambda frame: frame.arrival_ordinal)


def fixture_settings(tmp_path: Path, **changes: Any) -> CodexLocalSettings:
    values: dict[str, Any] = {
        "lease_root": tmp_path / "leases",
        "interrupt_settle_s": 5.0,
        "status_timeout_s": 5.0,
        "compaction_timeout_s": 5.0,
        "approval_wait_seconds": 5.0,
        "approval_reviewers": (REVIEWER,),
        "worker_environ": FAKE_WORKER_ENV,
    }
    values.update(changes)
    return CodexLocalSettings(**values)


def build_harness(
    tmp_path: Path,
    launcher: FixtureLauncher,
    *,
    broker: ApprovalBroker | None = None,
    auth: StaticAuth | None = None,
    settings: CodexLocalSettings | None = None,
    projections: StaticProjectionSource | None = None,
    rows: Any = None,
    hooks: HookCallbackService | None = None,
    secrets: ProcessSecretDelivery | None = None,
    mission_layer: MissionLayerService | None = None,
    artifacts: MemoryArtifacts | None = None,
    inputs: Any = None,
) -> tuple[CodexLocalHarness, TmpLeaser, MemoryArtifacts, StaticAuth]:
    leaser = TmpLeaser(tmp_path / "leases")
    artifacts = artifacts if artifacts is not None else MemoryArtifacts()
    settings = settings or fixture_settings(tmp_path)
    auth = auth or StaticAuth(
        admission() if settings.codex_home_mode == "owner" else admission("api_key")
    )
    harness = CodexLocalHarness(
        launcher=launcher,
        leaser=leaser,
        projections=projections or StaticProjectionSource(),
        artifacts=artifacts,
        auth=auth,
        settings=settings,
        child_environment=provider_child_environment,
        inputs=inputs,
        rows=rows,
        broker=broker,
        hooks=hooks,
        secrets=secrets,
        mission_layer=mission_layer,
    )
    return harness, leaser, artifacts, auth


def codex_stack(
    tmp_path: Path,
    *scripts: str,
    launcher: FixtureLauncher | None = None,
    decisions: list[Decision] | None = None,
    approvals: bool = True,
    review: bool = True,
    operation: OperationExecutionRequest | None = None,
    settings: CodexLocalSettings | None = None,
    artifacts: MemoryArtifacts | None = None,
    inputs: Any = None,
    **launcher_changes: Any,
) -> CodexStack:
    """The harness over the FIXTURE app-server; `approvals=False` composes no broker.
    `artifacts`/`inputs` share one custody between a source and a derived (forked) stack."""

    launcher = launcher or FixtureLauncher(
        scripts=[load_script(name) for name in scripts], **launcher_changes
    )
    operation = operation or codex_operation()
    rig = (
        approval_rig(operation.effective_configuration_digest, decisions=decisions, review=review)
        if approvals
        else None
    )
    harness, leaser, artifacts, auth = build_harness(
        tmp_path,
        launcher,
        broker=rig.broker if rig else None,
        settings=settings,
        artifacts=artifacts,
        inputs=inputs,
    )
    lanes = lane_stack(harness, operation=operation)
    return CodexStack(
        harness=harness,
        launcher=launcher,
        leaser=leaser,
        artifacts=artifacts,
        auth=auth,
        rig=rig,
        operation=operation,
        lanes=lanes,
    )


__all__ = [
    "DIGEST",
    "FAKE_WORKER_ENV",
    "FIXTURE_INSTRUCTIONS",
    "FIXTURE_ROOT",
    "FIXTURE_VERSION",
    "PROFILE",
    "REVIEWER",
    "SCRIPTS",
    "ApprovalRig",
    "CodexStack",
    "Disk",
    "FakePatch",
    "FixtureAppServer",
    "FixtureLaunch",
    "FixtureLauncher",
    "HookRun",
    "MemoryChannel",
    "ReviewingStore",
    "ScriptedReviewer",
    "StaticAuth",
    "StaticProjectionSource",
    "TmpLeaser",
    "admission",
    "approval_rig",
    "build_harness",
    "channel_pair",
    "codex_binding",
    "codex_operation",
    "codex_stack",
    "config_read",
    "fixture_settings",
    "hooks_list",
    "load_script",
    "run_pre_tool_use",
    "skills_list",
    "static_projection",
]

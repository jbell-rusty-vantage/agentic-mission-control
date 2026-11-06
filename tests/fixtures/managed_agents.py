"""HL-07/HL-08 fixtures: an in-memory Managed Agents API behind `httpx.MockTransport`.

`FakeManagedAgentsApi` answers the agent, environment, skill, vault and credential endpoints in
the shapes of the pinned `anthropic` 1.13.0 source and the HL-23 live smoke
(research/provider-smoke-2026-10.md section 2.1): `?beta=true` plus `anthropic-beta:
managed-agents-2026-04-01` on Managed Agents paths and neither on `/v1/skills`; `{data,
next_page}` pages (two items per page, so listings page); agents versioned with a `409` on a
stale `version`, archived and never deleted; metadata patches where `null` deletes a key; skills
created from a multipart `files[]` upload with no metadata. Credential values are kept apart
from the resources (`secret_values`) and never appear in a response, as at the provider.

Sessions and their events (HL-08) follow the same sources: a session is created idle; each
`user.message` runs the next of `turn_scripts` (`full`, `held`, `no_usage`) as the HL-23 event
sequence (status running, the processed message, model request spans with `model_usage`, a
cumulative `session.usage`, then `session.status_idle{end_turn}`); a client event is streamed
queued, then processed; the event list is ordered by `processed_at` and filtered on it
(`created_at[gte]`/`[lt]`, `types[]`, `order`, `limit`); the SSE stream delivers only what
happens after it connects. A `held` turn stops after a running tool until `release()`, or until
an interrupt ends it with `end_turn`; a message sent while a turn runs or after a budget pause
is refused `400`, as is archiving or deleting a running session; lowering the budget to the
spend pauses the turn with `budget_reached` and raising it resumes.

Every request is recorded (`requests`) so a test can count creates and check headers. Nothing
touches the network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any, Final

import httpx
from pydantic import SecretStr

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.remote_session.sse import SseEvent, render_sse

API_KEY: Final = "fake-anthropic-key-for-tests"
PAGE_SIZE: Final = 2
BETA: Final = "managed-agents-2026-04-01"
# What one model request of a fixture turn reports, and what each closed turn adds to the
# session's `list_cost` (USD minor units).
MODEL_USAGE: Final = {
    "input_tokens": 12,
    "output_tokens": 30,
    "cache_read_input_tokens": 100,
    "cache_creation_input_tokens": 8,
}
TURN_LIST_COST: Final = 2
_EVENT_EPOCH: Final = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Recorded:
    method: str
    path: str
    headers: httpx.Headers
    beta_query: bool
    body: Any


@dataclass
class FakeManagedAgentsApi:
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    environments: dict[str, dict[str, Any]] = field(default_factory=dict)
    skills: dict[str, dict[str, Any]] = field(default_factory=dict)
    skill_files: dict[str, list[tuple[str, bytes]]] = field(default_factory=dict)
    vaults: dict[str, dict[str, Any]] = field(default_factory=dict)
    credentials: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    secret_values: dict[tuple[str, str], str] = field(default_factory=dict)
    requests: list[Recorded] = field(default_factory=list)
    # HL-08 sessions: the script each `user.message` runs, in order (the last one repeats).
    turn_scripts: list[str] = field(default_factory=lambda: ["full"])
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    held: asyncio.Event = field(default_factory=asyncio.Event)
    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    stream_opens: int = 0
    _turns: dict[str, dict[str, Any]] = field(default_factory=dict)
    _started: list[dict[str, Any]] = field(default_factory=list)
    _subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = field(default_factory=dict)
    _ids: count[int] = field(default_factory=lambda: count(1))
    _ticks: count[int] = field(default_factory=lambda: count(1))

    def client(self) -> ManagedAgentsClient:
        return ManagedAgentsClient(SecretStr(API_KEY), transport=httpx.MockTransport(self.handle))

    def creates(self, path: str) -> int:
        return sum(1 for r in self.requests if r.method == "POST" and r.path == path)

    def writes(self) -> list[Recorded]:
        return [r for r in self.requests if r.method in {"POST", "DELETE"}]

    # -- dispatch ---------------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = self._body(request)
        path = request.url.path
        self.requests.append(
            Recorded(
                request.method,
                path,
                request.headers,
                request.url.params.get("beta") == "true",
                body,
            )
        )
        if request.headers.get("x-api-key") != API_KEY:
            return _error(401, "authentication_error")
        parts = path.strip("/").split("/")[1:]
        managed = parts[0] != "skills"
        if managed and (
            request.headers.get("anthropic-beta") != BETA
            or request.url.params.get("beta") != "true"
        ):
            return _error(400, "invalid_request_error")
        if not managed and "anthropic-beta" in request.headers:
            return _error(400, "invalid_request_error")
        handler = getattr(self, f"_{parts[0]}")
        result: httpx.Response = handler(request.method, parts[1:], body, request)
        return result

    # -- agents -----------------------------------------------------------------------------------

    def _agents(
        self, method: str, rest: list[str], body: Any, request: httpx.Request
    ) -> httpx.Response:
        if not rest:
            if method == "GET":
                return self._page(self.agents, request)
            created = {**body, "id": self._id("agent"), "type": "agent", "version": 1}
            created["model"] = {"id": body["model"], "speed": "standard"}
            return self._store(self.agents, created)
        agent = self.agents.get(rest[0])
        if agent is None:
            return _error(404, "not_found_error")
        if rest[1:] == ["archive"]:
            agent["archived_at"] = _now()
            return httpx.Response(200, json=agent)
        if method == "GET":
            return httpx.Response(200, json=agent)
        if "version" in body and body["version"] != agent["version"]:
            return _error(409, "invalid_request_error")
        update = {key: value for key, value in body.items() if key not in {"version", "metadata"}}
        if "model" in update:
            update["model"] = {"id": update["model"], "speed": "standard"}
        changed = any(agent.get(key) != value for key, value in update.items())
        metadata = _patched(agent.get("metadata") or {}, body.get("metadata") or {})
        if changed or metadata != agent.get("metadata"):
            agent.update(update, metadata=metadata, version=agent["version"] + 1)
        return httpx.Response(200, json=agent)

    # -- environments -----------------------------------------------------------------------------

    def _environments(
        self, method: str, rest: list[str], body: Any, request: httpx.Request
    ) -> httpx.Response:
        if not rest:
            if method == "GET":
                return self._page(self.environments, request)
            return self._store(
                self.environments, {**body, "id": self._id("env"), "type": "environment"}
            )
        if rest[0] not in self.environments:
            return _error(404, "not_found_error")
        if method == "DELETE":
            del self.environments[rest[0]]
            return httpx.Response(200, json={"id": rest[0], "type": "environment_deleted"})
        return httpx.Response(200, json=self.environments[rest[0]])

    # -- skills -----------------------------------------------------------------------------------

    def _skills(
        self, method: str, rest: list[str], body: Any, request: httpx.Request
    ) -> httpx.Response:
        if not rest:
            if method == "GET":
                return self._page(self.skills, request)
            fields, parts = body
            if any(name != "files[]" for name, _, _ in parts):
                return _error(400, "invalid_request_error")
            files = [(filename, content) for _, filename, content in parts]
            skill_id = self._id("skill")
            self.skill_files[skill_id] = files
            return self._store(
                self.skills,
                {
                    "id": skill_id,
                    "type": "skill",
                    "display_name": fields["display_name"],
                    "latest_version_id": self._id("skillver"),
                    "source": "custom",
                },
            )
        if rest[0] not in self.skills:
            return _error(404, "not_found_error")
        if method == "DELETE":
            del self.skills[rest[0]]
            return httpx.Response(200, json={"id": rest[0], "type": "skill_deleted"})
        return httpx.Response(200, json=self.skills[rest[0]])

    # -- vaults and credentials -------------------------------------------------------------------

    def _vaults(
        self, method: str, rest: list[str], body: Any, request: httpx.Request
    ) -> httpx.Response:
        if not rest:
            if method == "GET":
                return self._page(self.vaults, request)
            vault = self._store(self.vaults, {**body, "id": self._id("vlt"), "type": "vault"})
            self.credentials[vault.json()["id"]] = {}
            return vault
        vault_id = rest[0]
        if vault_id not in self.vaults:
            return _error(404, "not_found_error")
        if rest[1:2] == ["credentials"]:
            return self._credentials(method, vault_id, rest[2:], body, request)
        if method == "DELETE":
            del self.vaults[vault_id]
            return httpx.Response(200, json={"id": vault_id, "type": "vault_deleted"})
        return httpx.Response(200, json=self.vaults[vault_id])

    def _credentials(
        self, method: str, vault_id: str, rest: list[str], body: Any, request: httpx.Request
    ) -> httpx.Response:
        held = self.credentials[vault_id]
        if not rest:
            if method == "GET":
                return self._page(held, request)
            auth = dict(body["auth"])
            credential_id = self._id("vcrd")
            self.secret_values[(vault_id, auth["secret_name"])] = auth.pop("secret_value")
            return self._store(
                held, {**body, "auth": auth, "id": credential_id, "type": "credential"}
            )
        credential = held.get(rest[0])
        if credential is None:
            return _error(404, "not_found_error")
        if method == "DELETE":
            del held[rest[0]]
            return httpx.Response(200, json={"id": rest[0], "type": "credential_deleted"})
        if method == "POST":
            auth = dict(body.get("auth") or {})
            if "secret_name" in auth:
                return _error(400, "invalid_request_error")  # secret_name is immutable
            name = credential["auth"]["secret_name"]
            if "secret_value" in auth:
                self.secret_values[(vault_id, name)] = auth.pop("secret_value")
            credential["auth"] = {**credential["auth"], **auth}
        return httpx.Response(200, json=credential)

    # -- sessions (HL-08) -------------------------------------------------------------------------

    def messages(self) -> list[tuple[str, str]]:
        """`(session id, text)` of every `user.message` the sessions received, in order."""

        return [
            (session_id, "".join(block.get("text", "") for block in event["content"]))
            for session_id, event in self.sent
            if event["type"] == "user.message"
        ]

    def interrupts(self) -> int:
        return sum(1 for _session, event in self.sent if event["type"] == "user.interrupt")

    def archived(self) -> list[str]:
        return [key for key, value in self.sessions.items() if value.get("archived_at")]

    def release(self) -> None:
        """Let every held turn run to its close."""

        for session_id, turn in list(self._turns.items()):
            if turn.get("holding"):
                turn["holding"] = False
                self._finish_turn(session_id, tool_result=True)

    def _sessions(
        self, method: str, rest: list[str], body: Any, request: httpx.Request
    ) -> httpx.Response:
        if not rest:
            if method == "GET":
                agent_id = request.url.params.get("agent_id")
                listed = {
                    key: value
                    for key, value in self.sessions.items()
                    if agent_id is None or value["agent"]["id"] == agent_id
                }
                return self._page(listed, request)
            return self._create_session(body)
        session = self.sessions.get(rest[0])
        if session is None:
            return _error(404, "not_found_error")
        tail = rest[1:]
        if tail == ["archive"]:
            if session["status"] == "running":
                return _error(400, "invalid_request_error")
            session["archived_at"] = self._tick()
            return httpx.Response(200, json=session)
        if tail == ["events"]:
            if method == "GET":
                return self._event_page(session["id"], request)
            return self._send(session, body["events"])
        if tail == ["events", "stream"]:
            return self._stream(session["id"])
        if method == "DELETE":
            if session["status"] == "running":
                return _error(400, "invalid_request_error")
            del self.sessions[rest[0]]
            return httpx.Response(200, json={"id": rest[0], "type": "session_deleted"})
        if method == "POST":
            return self._update_session(session, body)
        return httpx.Response(200, json=session)

    def _create_session(self, body: dict[str, Any]) -> httpx.Response:
        agent = body["agent"]
        if agent["id"] not in self.agents or body["environment_id"] not in self.environments:
            return _error(400, "invalid_request_error")
        session_id = self._id("sesn")
        self.sessions[session_id] = {
            "id": session_id,
            "type": "session",
            "status": "idle",
            "agent": dict(agent),
            "environment_id": body["environment_id"],
            "vault_ids": list(body.get("vault_ids") or ()),
            "budget": body.get("budget"),
            "metadata": dict(body.get("metadata") or {}),
            "title": body.get("title"),
            "usage": {"input_tokens": 0, "output_tokens": 0, "list_cost": _cost(0)},
            "created_at": self._tick(),
            "archived_at": None,
        }
        self.events[session_id] = []
        return httpx.Response(200, json=self.sessions[session_id])

    def _update_session(self, session: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
        if "budget" in body:
            cap = int(body["budget"]["max_list_cost"]["amount"])
            if cap <= _spent(session):
                return _error(400, "invalid_request_error")
            session["budget"] = body["budget"]
            turn = self._turns.get(session["id"])
            if turn is not None and turn.get("paused"):
                turn["paused"] = False
                self._finish_turn(session["id"], tool_result=False)
        return httpx.Response(200, json=session)

    def _send(self, session: dict[str, Any], events: list[dict[str, Any]]) -> httpx.Response:
        session_id = session["id"]
        turn = self._turns.get(session_id)
        echoes: list[dict[str, Any]] = []
        for event in events:
            kind = event["type"]
            steering = (
                kind == "user.message"
                and session["status"] == "running"
                and turn is not None
                and turn.get("holding")
                and not turn.get("paused")
            )
            if (
                kind == "user.message"
                and not steering
                and (session["status"] != "idle" or (turn is not None and turn.get("paused")))
            ):
                return _error(400, "invalid_request_error")
            echo = {**event, "id": self._id("sevt"), "processed_at": None}
            self.sent.append((session_id, event))
            echoes.append(echo)
            if steering:
                # Q-M1 (HL-23): a message sent while the turn runs is consumed at the next
                # model request of the current turn; no new turn starts.
                assert turn is not None
                self._publish(session_id, echo)
                self._append(session_id, {**echo, "processed_at": self._tick()})
                turn.setdefault("steers", []).append(echo["id"])
            elif kind == "user.message":
                self._publish(session_id, echo)
                self._start_turn(session, echo)
            elif kind in {"user.custom_tool_result", "user.tool_confirmation"}:
                self._append(session_id, {**echo, "processed_at": self._tick()})
                if turn is not None and turn["script"] == "approval":
                    self._approval_step(session_id)
            elif kind == "user.interrupt" and turn is not None and not turn.get("paused"):
                self._append(session_id, {**echo, "processed_at": self._tick()})
                if turn.pop("holding", False):
                    # The running tool is stopped and reports it.
                    self._append(
                        session_id,
                        {
                            "type": "agent.tool_result",
                            "tool_use_id": turn["tool_use"],
                            "is_error": True,
                        },
                    )
                self._close_turn(session_id, model_request_open=True)
        return httpx.Response(200, json={"data": echoes})

    def _start_turn(self, session: dict[str, Any], message: dict[str, Any]) -> None:
        session_id = session["id"]
        script = self.turn_scripts[min(len(self._started), len(self.turn_scripts) - 1)]
        turn = {"script": script, "message": message["id"]}
        self._started.append(turn)
        self._turns[session_id] = turn
        session["status"] = "running"
        self._append(session_id, {"type": "session.status_running"})
        self._append(session_id, {**message, "processed_at": self._tick()})
        self._append(session_id, {"type": "span.model_request_start"})
        if script == "approval":
            turn["approval_step"] = 0
            self._approval_step(session_id)
            return
        if script == "held":
            self._append(
                session_id,
                {
                    "type": "agent.tool_use",
                    "name": "read",
                    "input": {"file_path": "/workspace/notes.md"},
                    "evaluated_permission": "allow",
                },
            )
            turn["holding"] = True
            turn["tool_use"] = self.events[session_id][-1]["id"]
            self.held.set()
            return
        self._finish_turn(session_id, tool_result=False)

    def _approval_step(self, session_id: str) -> None:
        """Native requires_action lifecycle: prepare, readiness, then human permission."""
        turn = self._turns[session_id]
        step = turn["approval_step"]
        turn["approval_step"] += 1
        if step == 3:
            self._finish_turn(session_id, tool_result=True)
            return
        name, arguments = (
            ("mc_prepare", {}),
            ("mc_signal", {"name": "env.prepared"}),
            ("bash", {"command": "echo bounded"}),
        )[step]
        event = {
            "type": "agent.tool_use" if step == 2 else "agent.custom_tool_use",
            "name": name,
            "input": arguments,
        }
        if step == 2:
            event["evaluated_permission"] = "ask"
        self._append(session_id, event)
        call_id = self.events[session_id][-1]["id"]
        turn["tool_use"] = call_id
        self.sessions[session_id]["status"] = "idle"
        self._append(
            session_id,
            {
                "type": "session.status_idle",
                "stop_reason": {"type": "requires_action", "event_ids": [call_id]},
            },
        )

    def _finish_turn(self, session_id: str, *, tool_result: bool) -> None:
        turn = self._turns[session_id]
        if tool_result:
            self._append(
                session_id,
                {"type": "agent.tool_result", "tool_use_id": turn["tool_use"], "is_error": False},
            )
            self._model_request_end(session_id)
            self._append(session_id, {"type": "span.model_request_start"})
        session = self.sessions[session_id]
        cap = _cap(session)
        if cap is not None and _spent(session) + TURN_LIST_COST > cap:
            # The budget gate: every thread stops before its next model request.
            turn["paused"] = True
            self._append(session_id, {"type": "session.usage", "usage": session["usage"]})
            self._idle(session_id, "budget_reached")
            return
        self._append(
            session_id,
            {"type": "agent.message", "content": [{"type": "text", "text": "Done: report.md"}]},
        )
        self._close_turn(session_id, model_request_open=True)

    def _close_turn(self, session_id: str, *, model_request_open: bool) -> None:
        turn = self._turns.pop(session_id)
        if model_request_open:
            self._model_request_end(session_id, script=turn["script"])
        self._append(session_id, {"type": "session.thread_status_idle"})
        session = self.sessions[session_id]
        if turn["script"] != "no_usage":
            usage = session["usage"]
            usage["list_cost"] = _cost(_spent(session) + TURN_LIST_COST)
            self._append(session_id, {"type": "session.usage", "usage": dict(usage)})
        self._idle(session_id, "end_turn")

    def _model_request_end(self, session_id: str, *, script: str = "full") -> None:
        end: dict[str, Any] = {"type": "span.model_request_end", "is_error": False}
        if script != "no_usage":
            end["model_usage"] = dict(MODEL_USAGE)
            usage = self.sessions[session_id]["usage"]
            usage["input_tokens"] += MODEL_USAGE["input_tokens"]
            usage["output_tokens"] += MODEL_USAGE["output_tokens"]
        self._append(session_id, end)

    def _idle(self, session_id: str, reason: str) -> None:
        self._append(session_id, {"type": "session.status_idle", "stop_reason": {"type": reason}})
        self.sessions[session_id]["status"] = "idle"

    def _append(self, session_id: str, event: dict[str, Any]) -> None:
        stored = {"id": self._id("sevt"), "processed_at": self._tick(), **event}
        self.events[session_id].append(stored)
        self._publish(session_id, stored)

    def _publish(self, session_id: str, event: dict[str, Any]) -> None:
        for queue in self._subscribers.get(session_id, ()):
            queue.put_nowait(event)

    def _event_page(self, session_id: str, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        types = set(params.get_list("types[]"))
        since, before = params.get("created_at[gte]"), params.get("created_at[lt]")
        listed = [
            event
            for event in self.events[session_id]
            if (not types or event["type"] in types)
            and (since is None or _at(event) >= _parse(since))
            and (before is None or _at(event) < _parse(before))
        ]
        if params.get("order") == "desc":
            listed.reverse()
        if params.get("limit"):
            listed = listed[: int(params["limit"])]
        table = {str(index): event for index, event in enumerate(listed)}
        return self._page(table, request)

    def _stream(self, session_id: str) -> httpx.Response:
        self.stream_opens += 1
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(session_id, []).append(queue)
        subscribers = self._subscribers[session_id]

        async def chunks() -> AsyncIterator[bytes]:
            try:
                while True:
                    event = await queue.get()
                    rendered = SseEvent(event=event["type"], data=json.dumps(event))
                    yield render_sse([rendered]).encode("utf-8")
            finally:
                subscribers.remove(queue)

        return httpx.Response(
            200, headers={"Content-Type": "text/event-stream"}, stream=_EventStream(chunks())
        )

    def _tick(self) -> str:
        moment = _EVENT_EPOCH + timedelta(milliseconds=next(self._ticks))
        return moment.isoformat().replace("+00:00", "Z")

    # -- helpers ----------------------------------------------------------------------------------

    def _id(self, prefix: str) -> str:
        return f"{prefix}_{next(self._ids):04d}"

    def _store(self, table: dict[str, dict[str, Any]], item: dict[str, Any]) -> httpx.Response:
        item.setdefault("metadata", {})
        item.update(created_at=_now(), archived_at=None)
        table[item["id"]] = item
        return httpx.Response(200, json=item)

    def _page(self, table: dict[str, dict[str, Any]], request: httpx.Request) -> httpx.Response:
        items = list(table.values())
        start = int(request.url.params.get("page") or 0)
        page = items[start : start + PAGE_SIZE]
        following = start + PAGE_SIZE
        return httpx.Response(
            200,
            json={"data": page, "next_page": str(following) if following < len(items) else None},
        )

    @staticmethod
    def _body(request: httpx.Request) -> Any:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            return _multipart(request)
        return json.loads(request.content) if request.content else None


class _EventStream(httpx.AsyncByteStream):
    def __init__(self, chunks: AsyncIterator[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        aclose = getattr(self._chunks, "aclose", None)
        if aclose is not None:
            await aclose()


def _cost(minor_units: int) -> dict[str, str]:
    return {"amount": str(minor_units), "currency": "USD"}


def _spent(session: dict[str, Any]) -> int:
    return int(session["usage"]["list_cost"]["amount"])


def _cap(session: dict[str, Any]) -> int | None:
    budget = session.get("budget")
    return int(budget["max_list_cost"]["amount"]) if budget else None


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _at(event: dict[str, Any]) -> datetime:
    return _parse(event["processed_at"])


_clock = count(1)


def _now() -> str:
    """A strictly increasing ISO timestamp, so `created_at` orders like the provider's."""

    return f"2026-10-13T00:00:{next(_clock):06d}Z"


def _patched(metadata: dict[str, str], patch: dict[str, str | None]) -> dict[str, str]:
    merged = {**metadata, **patch}
    return {key: value for key, value in merged.items() if value is not None}


def _error(status: int, kind: str) -> httpx.Response:
    return httpx.Response(status, json={"type": "error", "error": {"type": kind, "message": kind}})


def _multipart(request: httpx.Request) -> tuple[dict[str, str], list[tuple[str, str, bytes]]]:
    """The form fields and the file parts (field name, file name, content) of a multipart body."""

    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    fields: dict[str, str] = {}
    files: list[tuple[str, str, bytes]] = []
    for part in request.content.split(b"--" + boundary)[1:-1]:
        head, _, content = part[2:-2].partition(b"\r\n\r\n")
        disposition = head.decode().split("\r\n")[0]
        name = disposition.split('name="')[1].split('"')[0]
        if 'filename="' in disposition:
            files.append((name, disposition.split('filename="')[1].split('"')[0], content))
        else:
            fields[name] = content.decode()
    return fields, files


__all__ = ["API_KEY", "MODEL_USAGE", "TURN_LIST_COST", "FakeManagedAgentsApi", "Recorded"]

"""MO-41 on a disposable PostgreSQL 17: the Telemetry Hook Pack and `signal_emit` into the
real Signal Ingress (migration 0035; SPEC-04 section 4).

The projected `cursor_cloud` hooks run as the Cursor VM runs them (`.cursor/hooks.json`
commands as subprocesses in the workspace, the native payload on stdin; the fixture engine in
`tests/fixtures/cursor_cloud.run_cursor_hooks`) with a run token minted for an admitted run,
against the ingress app served over real HTTP on 127.0.0.1 through the edge login. The inbox
rows are what the IngressDrainer (MO-75) will turn into frames. `signal_emit` reaches the same
store through the signals MCP server with the same credential.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from mission_control.application.agentic_components.telemetry import SIGNAL_SCRIPT
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.interfaces.http.ingress import create_ingress_app
from mission_control.interfaces.mcp.coordinator_http_client import CoordinatorStreamableHttpClient
from mission_control.interfaces.mcp.signal_tools import SIGNAL_EMIT_TOOL, mount_signal_tools
from tests.fixtures.cursor_cloud import cloud_rows, run_cursor_hooks
from tests.fixtures.projections.rows import INSTRUCTION
from tests.fixtures.scoped_api_stack import serve_loopback
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_signal_ingress_postgres import (  # noqa: F401
    Ingress,
    ingress,
)

pytestmark = pytest.mark.common_db

# One Cursor cloud turn as its hook engine fires it: no `sessionStart` on cloud.
TURN: list[tuple[str, dict[str, Any]]] = [
    ("preToolUse", {"conversation_id": "bc-1", "tool_name": "Shell", "tool_use_id": "t-1"}),
    ("postToolUse", {"conversation_id": "bc-1", "tool_name": "Shell", "tool_use_id": "t-1"}),
    ("subagentStart", {"conversation_id": "bc-1", "subagent_type": "verifier"}),
    ("subagentStop", {"conversation_id": "bc-1", "subagent_type": "verifier"}),
    ("afterAgentResponse", {"conversation_id": "bc-1"}),
    ("stop", {"conversation_id": "bc-1", "status": "completed", "loop_count": 0}),
]
TURN_SIGNALS = [
    "signal.session.started",
    "signal.materialization.observed",
    "signal.tool.started",
    "signal.tool.completed",
    "signal.subagent.started",
    "signal.subagent.stopped",
    "signal.agent.responded",
    "signal.stop",
]


def place(root: Path) -> Path:
    projection = HOST_PROJECTORS.render(
        cloud_rows(), LaneProfile.CURSOR_CLOUD, INSTRUCTION, None, ()
    )
    for item in projection.files:
        target = root / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.content)
    return root


async def signal_rows(stack: Ingress) -> list[dict[str, Any]]:
    rows = await stack.owner(
        "SELECT * FROM mission_control.ingress_inbox WHERE kind LIKE 'signal.%' "
        "ORDER BY received_at, ingress_id"
    )
    return [dict(row) for row in rows]


def assert_ordered_without_gaps(rows: list[dict[str, Any]], stack: Ingress) -> None:
    seqs = [row["seq"] for row in rows]
    assert seqs == list(range(1, len(rows) + 1)), f"arrival order is seq order, no gap: {seqs}"
    spool = {json.loads(row["payload"])["signal_id"].rsplit("-", 1)[0] for row in rows}
    assert len(spool) == 1, "one session"
    for row in rows:
        assert (row["run_key"], row["unit_key"], row["generation"]) == (
            stack.run_key,
            stack.unit_key,
            1,
        )
        assert row["trust_tier"] == "run_token" and row["state"] == "pending"


async def test_projected_cursor_cloud_hooks_deliver_the_session_in_order_without_gaps(
    ingress: Ingress,  # noqa: F811
    tmp_path: Path,
) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding)
    app = create_ingress_app([ingress.service])
    async with serve_loopback(app) as origin:
        env = {
            "MC_SIGNAL_URL": f"{origin}/v1/ingress/biotech/signals",
            "MC_SIGNAL_TOKEN": token.value,
        }
        root = await asyncio.to_thread(place, tmp_path / "vm")
        runs = await asyncio.to_thread(run_cursor_hooks, root, TURN, env)

        assert all(run.exit_code == 0 for run in runs), runs
        pack = [run for run in runs if SIGNAL_SCRIPT in run.command]
        assert len(pack) == len(TURN), "one pack hook per fired event"
        rows = await signal_rows(ingress)
        assert [row["kind"] for row in rows] == TURN_SIGNALS
        assert_ordered_without_gaps(rows, ingress)
        observed = json.loads(rows[1]["payload"])["data"]
        assert set(observed["files"]) == {".cursor/hooks.json", ".cursor/rules/mc-mission.mdc"}
        assert all(str(digest).startswith("sha256:") for digest in observed["files"].values())
        assert "mc-signals" in observed["skills"]
        assert token.value not in json.dumps(rows, default=str)

        # A resend of the whole spool (a lost acknowledgement) is dropped as duplicates.
        state = root / ".mission/state/signals/state.json"
        reset = {**json.loads(state.read_text(encoding="utf-8")), "sent": 0}
        state.write_text(json.dumps(reset), encoding="utf-8")
        runs = await asyncio.to_thread(run_cursor_hooks, root, TURN[-1:], env)
        assert all(run.exit_code == 0 for run in runs)

    rows = await signal_rows(ingress)
    assert [row["kind"] for row in rows] == [*TURN_SIGNALS, "signal.stop"]
    assert_ordered_without_gaps(rows, ingress)


async def test_signal_emit_records_into_the_real_ingress_with_the_run_token(
    ingress: Ingress,  # noqa: F811
) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding)
    app = create_ingress_app([ingress.service])
    mcp = mount_signal_tools(app, [ingress.service])
    headers = {
        "accept": "application/json, text/event-stream",
        "authorization": f"Bearer {token.value}",
    }
    async with (
        mcp.router.lifespan_context(mcp),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=headers
        ) as http,
    ):
        client = CoordinatorStreamableHttpClient(http, "/v1/ingress/biotech/mcp/")
        await client.initialize()
        arguments = {
            "type": "artifact.ready",
            "message": "report drafted",
            "data": {"path": "outputs/report.md"},
            "signal_id": "emit-1",
        }
        first = await client.call_tool(SIGNAL_EMIT_TOOL, arguments)
        again = await client.call_tool(SIGNAL_EMIT_TOOL, arguments)

    assert first.data == {"ok": True, "signal_id": "emit-1", "accepted": 1, "duplicates": 0}
    assert again.data == {"ok": True, "signal_id": "emit-1", "accepted": 0, "duplicates": 1}
    (row,) = await signal_rows(ingress)
    assert row["kind"] == "signal.artifact.ready" and row["dedupe_key"] == "emit-1"
    assert row["run_key"] == ingress.run_key and row["trust_tier"] == "run_token"
    assert json.loads(row["payload"])["data"] == {
        "path": "outputs/report.md",
        "message": "report drafted",
        "source": "mcp",
    }

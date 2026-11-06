"""MO-30: cursor_cloud re-sends the projection's inline options with every request that takes them.

Cloud ignores `.cursor/mcp.json` and keeps no inline MCP servers across runs, so the
projection's `mcpServers` travel on every create and every follow-up run (a run's list
replaces the agent's); `customSubagents` travel on every create, continuation creates included,
since a run takes none (FIXTURE Cloud API).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mission_control.application.agentic_components.placement import operating_contract
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.projection import ResolvedCapability
from tests.fixtures.cursor_cloud import CloudStack, cloud_rows, cloud_stack
from tests.fixtures.cursor_controls import started_session
from tests.fixtures.projections.rows import verifier_row
from tests.unit.cursor.support import heid_of, lanes_for, send_request, signals, turn

PROFILE = "cursor_cloud"


def _inline_verifier() -> ResolvedCapability:
    """The fixture verifier without `readonly`: Cursor can carry it as an inline subagent."""

    row = verifier_row()
    profile = row.definition.profile.model_copy(update={"readonly": False})  # type: ignore[union-attr]
    return row.model_copy(
        update={"definition": row.definition.model_copy(update={"profile": profile})}
    )


def _send_options(stack: CloudStack, rows: tuple[ResolvedCapability, ...]) -> dict[str, Any]:
    projection = HOST_PROJECTORS.render(
        rows, PROFILE, operating_contract(stack.operation), None, ()
    )
    return projection.send_options


def _run_bodies(stack: CloudStack) -> list[dict[str, Any]]:
    return [
        json.loads(request.content)
        for request in stack.api.requests
        if request.method == "POST" and request.url.path.endswith("/runs")
    ]


async def _send_follow_ups(stack: CloudStack, heid: str, agent_id: str, *turns: int) -> None:
    for turn_no in turns:
        stack.api.runs[stack.api.agents[agent_id]["latestRunId"]]["status"] = "FINISHED"
        sent = await stack.harness.send_turn(send_request(stack, PROFILE, heid, agent_id, turn_no))
        assert sent.status == "accepted"


async def test_inline_mcp_servers_ride_the_create_and_every_follow_up_run(tmp_path: Path) -> None:
    stack = cloud_stack(tmp_path)
    heid, session = await started_session(stack)
    servers = _send_options(stack, cloud_rows())["mcp_servers"]
    assert [item["name"] for item in servers] == ["mc-tavily"]
    assert stack.api.creates[0]["mcpServers"] == servers
    # The verifier is read-only, so it travels as the committed `.cursor/agents` file only.
    assert "customSubagents" not in stack.api.creates[0]

    agent_id = str(session.native_session_ref)
    await _send_follow_ups(stack, heid, agent_id, 2, 3)
    runs = _run_bodies(stack)
    assert len(runs) == 2
    assert all(body["mcpServers"] == servers for body in runs)
    assert all(set(body) == {"prompt", "mcpServers"} for body in runs), "a run takes no subagents"


async def test_a_worker_that_did_not_prepare_the_session_still_sends_them(tmp_path: Path) -> None:
    stack = cloud_stack(tmp_path)
    lanes = lanes_for(stack)
    assert (await lanes.service.turn(turn(stack, PROFILE), signals(lanes, stack, PROFILE))).done
    # The session ended in this process; a later send renders the binding's projection again.
    heid, agent_id = heid_of(stack, PROFILE), next(iter(stack.api.agents))
    stack.harness.stage(heid, stack.operation)
    await _send_follow_ups(stack, heid, agent_id, 2)
    (run,) = _run_bodies(stack)
    assert run["mcpServers"] == _send_options(stack, cloud_rows())["mcp_servers"]


async def test_custom_subagents_ride_every_create_including_a_continuation(
    tmp_path: Path,
) -> None:
    rows = (*cloud_rows()[:2], _inline_verifier())
    stack = cloud_stack(tmp_path, rows=rows)
    heid, session = await started_session(stack)
    options = _send_options(stack, rows)
    assert [item["name"] for item in options["agents"]] == ["verifier"]
    first = stack.api.creates[0]
    assert first["customSubagents"] == options["agents"]
    assert first["mcpServers"] == options["mcp_servers"]

    agent_id = str(session.native_session_ref)
    hydrated, _ = await stack.harness.hydrate_agent(
        heid,
        transfer_id="transfer-1",
        files=[(".mission/continuation.md", b"carry on\n")],
        prompt="Continue from .mission/continuation.md.",
        source_session_ref=agent_id,
    )
    assert hydrated != agent_id
    continuation = stack.api.creates[-1]
    assert continuation["customSubagents"] == options["agents"]
    assert continuation["mcpServers"] == options["mcp_servers"]

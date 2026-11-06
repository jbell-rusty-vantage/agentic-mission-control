"""MO-43 acceptance (SPEC-04 §6): a background `missionctl wait` is woken by `run.completed`.

The signed scoped stack (`tests/fixtures/scoped_api_stack.py`): the configured API on a fresh
common database (restricted logins, forced RLS) and a local Temporal dev server, production
workers with deterministic DeepAgents cognition (no provider call), served over real loopback
HTTP. A GoalDirected run is launched through `POST /runs/{id}/launch`, which subscribes the
launcher's coordinator inbox first; `missionctl wait --run` then runs as a separate process, the
way a Claude Code session runs it in the background, blocks while the run works and exits 0 with
the `terminal_result` notification of the run's real `workflow_run.terminalize`. The same inbox
answers the authenticated operator MCP's `coordinator_inbox_wait`, and nothing is acknowledged
until `missionctl inbox ack`.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from tests.fixtures.scoped_api_stack import inspect, prepare_run, scoped_stack, serve_loopback

from mission_control.interfaces.mcp.coordinator_http_client import CoordinatorStreamableHttpClient

pytestmark = pytest.mark.common_db

WAKE_KINDS = "terminal_result,blocked,review_required"


def missionctl(url: str, token: str, *args: str) -> subprocess.Popen[bytes]:
    """A separate `missionctl` process (the Windows selector loop cannot spawn asyncio ones)."""

    return subprocess.Popen(
        [sys.executable, "-m", "mission_control.interfaces.cli", *args],
        env={
            **os.environ,
            "MISSION_CONTROL_URL": url,
            "MISSION_CONTROL_APPLICATION_ID": "biotech",
            "MISSION_CONTROL_TOKEN": token,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


async def finished(process: subprocess.Popen[bytes], seconds: float) -> tuple[str, str]:
    stdout, stderr = await asyncio.to_thread(process.communicate, timeout=seconds)
    return stdout.decode(), stderr.decode()


@pytest.mark.asyncio
async def test_background_missionctl_wait_wakes_on_run_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with (
        scoped_stack(tmp_path, monkeypatch) as stack,
        serve_loopback(stack.application) as url,
    ):
        run_id, launch = await prepare_run(stack, "GoalDirected")
        launched = await stack.http.post(
            f"/v1/applications/biotech/runs/{run_id}/launch", json=launch
        )
        assert launched.status_code == 202, launched.text
        inbox = launched.json()["coordinator_inbox"]
        assert inbox["status"] == "subscribed", inbox

        waiter = missionctl(
            url, stack.token, "wait", "--run", run_id, "--kinds", WAKE_KINDS, "--wait", "600"
        )
        started = await inspect(stack, run_id)
        print(f"WAKE E2E: waiting from lifecycle={started['lifecycle']}", flush=True)
        stdout, stderr = await finished(waiter, 660)
        assert waiter.returncode == 0, stderr
        assert json.loads(stderr.splitlines()[0]) == {
            "inbox": inbox["subscription_id"],
            "created": False,
        }
        (line,) = stdout.splitlines()
        notification = json.loads(line)
        assert notification["kind"] == "terminal_result" and notification["actionable"] is True
        listed = await stack.http.get(
            "/v1/applications/biotech/coordinator-inboxes",
            params={"target": "run", "target_id": run_id},
        )
        (target,) = [item["target"] for item in listed.json()["inboxes"]]
        assert notification["run_id"] == target["run_id"]  # the journal's row id of the run
        assert [ref["event_type"] for ref in notification["events"]] == ["run.completed"]
        assert notification["facts"]["terminal_outcome"] == "completed"
        terminal = await inspect(stack, run_id)
        assert terminal["lifecycle"] == "completed", terminal
        assert terminal["execution_outcome"] == "completed", terminal
        print(f"WAKE E2E: woken by {notification['notification_id']}", flush=True)

        # W2: the authenticated operator MCP answers from the same inbox, same principal.
        async with httpx.AsyncClient(
            base_url=url,
            headers={
                "authorization": f"Bearer {stack.token}",
                "accept": "application/json, text/event-stream",
            },
            timeout=60,
        ) as http:
            unauthenticated = await http.post(
                "/v1/applications/biotech/mcp/",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"authorization": ""},
            )
            assert unauthenticated.status_code == 401
            client = CoordinatorStreamableHttpClient(http, "/v1/applications/biotech/mcp")
            await client.initialize()
            waited = await client.call_tool(
                "coordinator_inbox_wait",
                {
                    "subscription_id": inbox["subscription_id"],
                    "kinds": ["terminal_result"],
                    "wait_seconds": 5,
                },
            )
            assert isinstance(waited.data, dict) and waited.data["ok"] is True, waited.data
            (again,) = waited.data["data"]["notifications"]
            assert again["notification_id"] == notification["notification_id"]

        acked = missionctl(
            url,
            stack.token,
            "inbox",
            "ack",
            inbox["subscription_id"],
            "--id",
            notification["notification_id"],
        )
        out, err = await finished(acked, 60)
        assert acked.returncode == 0, err
        assert notification["notification_id"] in json.loads(out)["acknowledged"]
        quiet = missionctl(
            url, stack.token, "wait", "--run", run_id, "--kinds", "terminal_result", "--wait", "2"
        )
        await finished(quiet, 60)
        assert quiet.returncode == 6  # acknowledged: nothing terminal is pending any more

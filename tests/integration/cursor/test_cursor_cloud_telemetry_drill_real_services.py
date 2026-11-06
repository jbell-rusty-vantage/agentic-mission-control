"""MO-41 cursor_cloud drill on FIXTURES: Telemetry Hook Pack signals reach the real Signal
Ingress ordered and without gaps, driven by the real local Temporal server (127.0.0.1:7233)
and a disposable PostgreSQL 17 (`MISSION_CONTROL_TEST_ADMIN_DSN`).

The real `OperationWorkflow` drives the real `cursor_cloud` harness over the fixture Cloud
Agents API (`tests/fixtures/cursor_cloud.FakeCloudApi`): `prepare` pushes the run branch with
the Host Projection (`.cursor/hooks.json`, `.mission/hooks/signal`, the policy and the
`mc-signals` skill); `start` creates the agent with the run's launch `envVars`
(`MC_SIGNAL_TOKEN`, a `signal_token` minted for the admitted run, and `MC_SIGNAL_URL`). The
fake VM then clones that branch and fires one turn of Cursor cloud hooks through the projected
`.cursor/hooks.json` (no `sessionStart` on cloud), and the pack posts to the ingress, served
over HTTP from its own thread and event loop through the edge login (the deployed edge is its
own process). Nothing calls Cursor; this is not the live drill (blocked for MO-41: no Cursor
budget), and it qualifies nothing.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

import asyncpg
import pytest
import uvicorn

from mission_control.adapters.cursor.workspace import git
from mission_control.adapters.postgres.ingress import (
    PostgresIngressStore,
    PostgresMintedCredentialStore,
)
from mission_control.adapters.temporal.operation_activities import parse_operation_result
from mission_control.application.agentic_components.telemetry import SIGNAL_SCRIPT
from mission_control.application.secrets.minting import CredentialBinding, CredentialMinter
from mission_control.application.signals.service import IngressKeys, SignalIngressService
from mission_control.interfaces.http.ingress import create_ingress_app
from tests.fixtures.mission_control_common_db import CommonDatabase, ingress_login
from tests.fixtures.scoped_api_stack import until
from tests.integration.cursor.test_mp09_cloud_segment_loop_real_services import (
    _client,
    _run,
    pg_cloud_unit,
)
from tests.integration.postgres.runtime_common import common_db  # noqa: F401

APPLICATION = "biotech"
ENV_VARS_CLOUD = {"env_vars_ref": "environment:MC_LAUNCH", "client_agent_id": False}
# One Cursor cloud turn as the VM's hook engine fires it.
TURN: list[tuple[str, dict[str, Any]]] = [
    ("preToolUse", {"conversation_id": "conv-1", "tool_name": "Shell", "tool_use_id": "t-1"}),
    ("postToolUse", {"conversation_id": "conv-1", "tool_name": "Shell", "tool_use_id": "t-1"}),
    ("afterAgentResponse", {"conversation_id": "conv-1"}),
    ("stop", {"conversation_id": "conv-1", "status": "completed", "loop_count": 0}),
]


class ThreadedIngress:
    """The ingress app on 127.0.0.1 in its own thread and event loop, over the edge login."""

    def __init__(self, dsn: str, installation_id: Any) -> None:
        self._dsn = dsn
        self._installation_id = installation_id
        self._ready = threading.Event()
        self._server: uvicorn.Server | None = None
        self._failure: BaseException | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self.url = ""

    def _serve(self) -> None:
        try:
            asyncio.run(self._main())
        except BaseException as error:  # surfaced to the test thread
            self._failure = error
            self._ready.set()

    async def _main(self) -> None:
        edge = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4, statement_cache_size=0)
        try:
            store = PostgresIngressStore(
                edge, installation_id=self._installation_id, application_id=APPLICATION
            )
            app = create_ingress_app([SignalIngressService(store, keys=IngressKeys())])
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
            )
            self._server = server
            serving = asyncio.create_task(server.serve())

            async def started() -> bool:
                if serving.done():
                    serving.result()  # surface a failed bind instead of waiting it out
                return server.started

            await until(started, seconds=30)
            port = server.servers[0].sockets[0].getsockname()[1]
            self.url = f"http://127.0.0.1:{port}/v1/ingress/{APPLICATION}/signals"
            self._ready.set()
            await serving
        finally:
            await edge.close()

    def __enter__(self) -> Self:
        self._thread.start()
        assert self._ready.wait(60), "the ingress did not start"
        if self._failure is not None:
            raise self._failure
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.should_exit = True
        self._thread.join(timeout=30)


@pytest.mark.common_db
async def test_cursor_cloud_hook_pack_signals_arrive_ordered_without_gaps(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
) -> None:
    client = await _client()
    lane_queue, workflow_queue = f"mo41-lane-{uuid4().hex[:8]}", f"mo41-wf-{uuid4().hex[:8]}"
    pool = await common_db.pool("mission_control_runtime")
    dsn = await ingress_login(common_db)
    try:
        with ThreadedIngress(dsn, common_db.installation_id) as ingress:
            # The resolver reads this mapping at `start`, after the token below is minted.
            launch_env = {"MC_SIGNAL_URL": ingress.url}
            unit = await pg_cloud_unit(
                pool,
                common_db,
                tmp_path,
                task_queue=lane_queue,
                api_changes={"vm": TURN},
                cloud_changes=ENV_VARS_CLOUD,
                env_vars=launch_env,
            )
            operation = unit.operation
            assert operation.runtime_unit is not None
            run_key, unit_key = operation.identity.run_id, operation.runtime_unit.unit_key
            minter = CredentialMinter(PostgresMintedCredentialStore(pool, common_db.scope()))
            token = await minter.mint(
                "signal_token",
                CredentialBinding(common_db.scope(), run_key, unit_key, 1),
            )
            launch_env["MC_SIGNAL_TOKEN"] = token.value

            result, _history = await _run(unit, client, lane_queue, workflow_queue, "mo41-drill")
    finally:
        await pool.close()

    api = unit.cloud.api
    assert result.disposition == "completed"
    assert parse_operation_result(result.result).status == "completed"
    (create,) = api.creates
    assert set(create["envVars"]) == {"MC_SIGNAL_URL", "MC_SIGNAL_TOKEN"}
    assert api.hook_runs and all(run.exit_code == 0 for run in api.hook_runs), api.hook_runs
    pack = [run for run in api.hook_runs if SIGNAL_SCRIPT in run.command]
    assert [run.native_event for run in pack] == [event for event, _payload in TURN]

    owner = await asyncpg.connect(common_db.owner_dsn)
    try:
        rows = [
            dict(row)
            for row in await owner.fetch(
                "SELECT * FROM mission_control.ingress_inbox WHERE kind LIKE 'signal.%' "
                "ORDER BY received_at, ingress_id"
            )
        ]
    finally:
        await owner.close()
    assert [row["kind"] for row in rows] == [
        "signal.session.started",
        "signal.materialization.observed",
        "signal.tool.started",
        "signal.tool.completed",
        "signal.agent.responded",
        "signal.stop",
    ]
    assert [row["seq"] for row in rows] == [1, 2, 3, 4, 5, 6], "ordered, no gaps"
    payloads = [json.loads(row["payload"]) for row in rows]
    assert len({payload["signal_id"].rsplit("-", 1)[0] for payload in payloads}) == 1
    assert all(
        (row["run_key"], row["unit_key"], row["generation"], row["trust_tier"])
        == (run_key, unit_key, 1, "run_token")
        for row in rows
    )
    assert payloads[0]["data"]["hook"] == "before_tool", "the first fired hook opens the session"
    observed = payloads[1]["data"]
    assert set(observed["files"]) == {".cursor/hooks.json", ".cursor/rules/mc-mission.mdc"}
    assert "mc-signals" in observed["skills"]
    assert token.value not in json.dumps(rows, default=str)

    # The spool ignores itself: the agent's `git add --all` commit does not carry it.
    branch = next(repo["startingRef"] for repo in create["repos"])
    listed = git("ls-tree", "-r", "--name-only", branch, cwd=api.remote)
    assert ".mission/hooks/signal" in listed and ".mission/state/" not in listed

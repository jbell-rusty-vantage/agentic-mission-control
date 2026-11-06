"""MO-03 (G11) on a disposable PostgreSQL 17: the `codex` lane's Kernel Hooks through the
worker's production hook callback composition.

Mission Control side, all production code: `compose_hook_callbacks` (the one service the
worker serves for `cursor_local` and `codex`, here with the `CodexHookMapper`),
`PostgresHookTokenStore`, `PostgresHookIntentLedger`, `PostgresStopFenceRepository` behind
`KernelHookFenceGate`, `PostgresFrameRepository`, the loopback callback app on a real uvicorn
listener, and the codex harness writing `kernel.py`, `context.json`, the token and the hook
trust. The app-server and its hook engine are the MO-03 FIXTURE
(`tests/unit/codex/fixture_hooks.py`): the projected kernel hooks run as subprocesses the
way Codex runs command hooks. No Codex runs, nothing is paid.

Proves on real rows: the task token is stored as a digest bound to the codex execution; an
allowed shell call writes its Operation Intent once and `hook.invoked` / `hook.result` frames
of that execution; after a Stop Fence the kernel `before_tool` hook refuses (Codex's JSON
`permissionDecision: deny`) and the tool is declined; `end_session` revokes the token.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
import uvicorn

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.temporal.deployment_composition import compose_hook_callbacks
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
)
from mission_control.domain.execution.lanes import EndSessionRequest
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.policies.stop_fence import StopFence
from mission_control.interfaces.http.hook_callback import create_hook_callback_app
from tests.fixtures.lane_turns import lane_stack
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db, owner_rows  # noqa: F401
from tests.unit.codex.drive import fields, started
from tests.unit.codex.fixture_app_server import FixtureLauncher, load_script
from tests.unit.codex.support import (
    CodexStack,
    StaticProjectionSource,
    build_harness,
    fixture_settings,
)
from tests.unit.codex.test_kernel_hooks import (
    command_statuses,
    kernel_operation,
    kernel_projection,
    run_turn,
)

pytestmark = pytest.mark.common_db


@asynccontextmanager
async def _serve(app: object) -> AsyncIterator[str]:
    """`app` on a loopback port the OS chooses; yields its base URL."""

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    finally:
        server.should_exit = True
        await serving


async def _codex_operation(pool: asyncpg.Pool, db: CommonDatabase) -> OperationExecutionRequest:
    admitted = await admit_unit_attempt(pool, db)
    unit = admitted.unit
    payload = kernel_operation(kernel_projection()).model_dump(mode="python")
    payload.update(
        request_scope=unit.request_scope,
        identity=OperationAttemptIdentity(
            run_id=admitted.run_key,
            operation_id=unit.semantic_operation_id,
            operation_attempt=unit.semantic_attempt,
        ),
        runtime_unit=unit,
        idempotency_key=f"mo-03-kernel-hooks:{unit.unit_key}",
    )
    return OperationExecutionRequest.model_validate(payload)


async def test_codex_kernel_hooks_persist_and_deny_a_fenced_tool_on_real_rows(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
) -> None:
    pool = await common_db.pool("mission_control_runtime", max_size=8)
    try:
        operation = await _codex_operation(pool, common_db)
        hooks = compose_hook_callbacks(pool)
        async with _serve(create_hook_callback_app(hooks)) as url:
            launcher = FixtureLauncher(
                scripts=[load_script("turn_tool_hook_1"), load_script("turn_tool_hook_2")]
            )
            harness, leaser, artifacts, auth = build_harness(
                tmp_path,
                launcher,
                settings=fixture_settings(tmp_path, hook_callback_base_url=url),
                projections=StaticProjectionSource(kernel_projection()),
                hooks=hooks,
            )
            stack = CodexStack(
                harness=harness,
                launcher=launcher,
                leaser=leaser,
                artifacts=artifacts,
                auth=auth,
                rig=None,
                operation=operation,
                lanes=lane_stack(harness, operation=operation),
            )
            identity = stack.identity
            scope = identity.request_scope
            session = await started(stack)
            root = Path(harness.lease_path(stack.heid))
            token = (root / ".mission/bin/.token").read_text(encoding="utf-8")
            tokens = await owner_rows(
                common_db,
                "SELECT token_hash, context::text AS context, revoked_at "
                "FROM mission_control.hook_task_token",
            )
            assert len(tokens) == 1 and token not in tokens[0]["token_hash"]
            assert token not in tokens[0]["context"]
            context = json.loads(tokens[0]["context"])
            assert context["lane_profile"] == "codex"
            assert context["harness_execution_id"] == stack.heid

            await run_turn(stack, session, 1)
            intents = await owner_rows(
                common_db,
                "SELECT effect_ref, effect_kind, lane_profile "
                "FROM mission_control.hook_effect_intent",
            )
            assert [tuple(row) for row in intents] == [("tool_use:call-1", "shell", "codex")]

            await PostgresStopFenceRepository(pool).persist(
                StopFence(
                    request_scope=scope,
                    run_id=identity.run_key,
                    generation=1,
                    command_id="cancel-mo-03-pg",
                    reason="operator stop",
                    requested_at=datetime.now(UTC),
                )
            )
            await run_turn(stack, session, 2)
            assert command_statuses(stack) == ["completed", "declined"]
            fenced = [
                run
                for run in launcher.server.hook_runs
                if "before_tool mc.stop_fence" in run.command
            ]
            assert [run.blocked for run in fenced] == [False, True]

            recorded = await PostgresFrameRepository(pool).frames_for_execution(
                scope, identity.harness_execution_id, 1
            )
            hook_results = [frame for frame in recorded if frame.kind == FrameKind.HOOK_RESULT]
            assert {frame.lane_profile for frame in hook_results} == {"codex"}
            results = [json.loads(frame.body_excerpt) for frame in hook_results]
            denied = [
                body
                for body in results
                if body["decision"] == "deny" and body["kernel_hook_id"] == "mc.stop_fence"
            ]
            assert denied and denied[0]["effect_ref"] == "tool_use:call-2"
            assert any(body["intent"] == "tool_use:call-1" for body in results if "intent" in body)

            await harness.end_session(
                EndSessionRequest(**fields(stack, "end"), session=session, reason="done")
            )
            revoked = await owner_rows(
                common_db, "SELECT revoked_at FROM mission_control.hook_task_token"
            )
            assert revoked[0]["revoked_at"] is not None
    finally:
        await pool.close()

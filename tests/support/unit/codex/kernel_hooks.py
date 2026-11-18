"""Builders, constants and fakes that other test files import.

Moved from tests/unit/codex/test_kernel_hooks.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn

from mission_control.adapters.codex.hooks_callback import CodexHookMapper
from mission_control.adapters.cursor.hooks_callback import CursorHookMapper
from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.execution.harness.hook_callbacks import (
    HookCallbackService,
    InMemoryHookIntentLedger,
    InMemoryHookTokenStore,
)
from mission_control.application.execution.stop_fence import (
    InMemoryStopFenceRepository,
    KernelHookFenceGate,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.projection import HostProjection
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import SessionHandle
from mission_control.interfaces.http.hook_callback import create_hook_callback_app
from tests.fixtures.lane_turns import lane_stack
from tests.support.providers.codex import (
    CodexStack,
    FixtureLauncher,
    StaticProjectionSource,
    build_harness,
    codex_binding,
    codex_operation,
    fixture_settings,
    load_script,
)
from tests.unit.codex.drive import observed, sent


def kernel_projection() -> HostProjection:
    """The real codex Host Projection of no capability rows: the four Kernel Hooks only."""

    return HOST_PROJECTORS.render([], "codex", "Run the mission; never deploy.")


def kernel_operation(projection: HostProjection) -> OperationExecutionRequest:
    return codex_operation(codex_binding(materialization_digest=projection_digest(projection)))


@dataclass
class HookRig:
    service: HookCallbackService
    tokens: InMemoryHookTokenStore
    intents: InMemoryHookIntentLedger
    fences: InMemoryStopFenceRepository
    url: str


def memory_hooks() -> tuple[
    HookCallbackService,
    InMemoryHookTokenStore,
    InMemoryHookIntentLedger,
    InMemoryStopFenceRepository,
]:
    """The worker's hook callback service (both command-hook lanes) over in-memory stores."""

    tokens, intents = InMemoryHookTokenStore(), InMemoryHookIntentLedger()
    fences = InMemoryStopFenceRepository()
    service = HookCallbackService(
        tokens=tokens,
        intents=intents,
        mapper=CursorHookMapper(),
        lane_mappers={"codex": CodexHookMapper()},
        fences=KernelHookFenceGate(fences),
    )
    return service, tokens, intents, fences


@pytest.fixture
async def hook_rig() -> AsyncIterator[HookRig]:
    """The worker's hook callback service on a real loopback listener (port chosen by the OS)."""

    service, tokens, intents, fences = memory_hooks()
    server = uvicorn.Server(
        uvicorn.Config(
            create_hook_callback_app(service), host="127.0.0.1", port=0, log_level="warning"
        )
    )
    serving = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        yield HookRig(service, tokens, intents, fences, f"http://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        await serving


def kernel_stack(
    tmp_path: Path,
    *scripts: str,
    hooks: HookCallbackService | None = None,
    callback_url: str = "http://127.0.0.1:9",
    codex_home_mode: str = "isolated",
) -> CodexStack:
    projection = kernel_projection()
    operation = kernel_operation(projection)
    launcher = FixtureLauncher(scripts=[load_script(name) for name in scripts])
    settings = fixture_settings(
        tmp_path,
        codex_home_mode=codex_home_mode,
        owner_codex_home=tmp_path / "owner-home",
        hook_callback_base_url=callback_url,
    )
    harness, leaser, artifacts, auth = build_harness(
        tmp_path,
        launcher,
        settings=settings,
        projections=StaticProjectionSource(projection),
        hooks=hooks,
    )
    return CodexStack(
        harness=harness,
        launcher=launcher,
        leaser=leaser,
        artifacts=artifacts,
        auth=auth,
        rig=None,
        operation=operation,
        lanes=lane_stack(harness, operation=operation),
    )


async def run_turn(stack: CodexStack, session: SessionHandle, turn_no: int) -> None:
    turn = await sent(stack, session, key=f"turn:{turn_no}", turn_no=turn_no)
    frames = await observed(stack, turn)
    assert frames and frames[-1].terminal


def command_statuses(stack: CodexStack) -> list[object]:
    """The status of every shell call the FIXTURE app-server ran, in turn order."""

    threads = stack.launcher.disk.threads.values()
    turns = [turn for thread in threads for turn in thread["turns"]]
    return [
        item["status"]
        for turn in turns
        for item in turn["items"]
        if item["type"] == "commandExecution"
    ]

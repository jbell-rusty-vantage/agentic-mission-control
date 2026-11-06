"""MO-03 (G11, Q-X2): the `codex` lane backs its Kernel Hooks and handles Codex hook trust.

The harness runs over the FIXTURE app-server, whose FIXTURE hook engine
(`fixture_hooks.py`) lists and runs the projected `.codex/hooks.json` the way Codex does:
trusted only by the isolated home's `[hooks.state]`, a `PreToolUse` refusal blocking the tool.
The hooks are the real `.mission/hooks/kernel.py` the lane wrote, run as subprocesses against
a real uvicorn loopback listener serving the production callback app over the in-memory
stores. No Codex runs and nothing is paid; the live CLI drill is the owner's (S0).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
import uvicorn

from mission_control.adapters.codex.harness import CODEX_HOME_DIR
from mission_control.adapters.codex.hooks_callback import CodexHookMapper
from mission_control.adapters.cursor.hooks_callback import CursorHookMapper, kernel_hook_script
from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.agentic_components.placement import LaneProjectionError
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
from mission_control.domain.capabilities.hooks import HOOK_EVENT_MAPPING
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import (
    EndSessionRequest,
    PrepareRequest,
    SessionHandle,
    StartRequest,
)
from mission_control.domain.policies.stop_fence import StopFence
from mission_control.interfaces.http.hook_callback import create_hook_callback_app
from tests.fixtures.lane_turns import lane_stack
from tests.unit.codex.drive import fields, observed, sent, started
from tests.unit.codex.fixture_app_server import FixtureLauncher, load_script
from tests.unit.codex.support import (
    CodexStack,
    StaticProjectionSource,
    build_harness,
    codex_binding,
    codex_operation,
    fixture_settings,
)

KERNEL_FILES = (".mission/hooks/kernel.py", ".mission/hooks/context.json", ".mission/bin/.token")


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


async def test_the_lane_writes_kernel_files_and_trust_before_any_thread(
    tmp_path: Path, hook_rig: HookRig
) -> None:
    stack = kernel_stack(tmp_path, hooks=hook_rig.service, callback_url=hook_rig.url)
    session = await started(stack)
    root = Path(stack.harness.lease_path(stack.heid))

    assert (root / ".mission/hooks/kernel.py").read_bytes() == kernel_hook_script()
    hooks_json = json.loads((root / ".codex/hooks.json").read_text(encoding="utf-8"))
    commands = [
        handler["command"]
        for groups in hooks_json["hooks"].values()
        for group in groups
        for handler in group["hooks"]
    ]
    kernel = [command for command in commands if ".mission/hooks/kernel.py" in command]
    assert kernel and set(commands) - set(kernel) == {
        "python .mission/hooks/signal hook stop",
        "python .mission/hooks/signal hook subagent_stop",
    }, "the Telemetry Hook Pack is the only other entry"
    config = (root / CODEX_HOME_DIR / "config.toml").read_text(encoding="utf-8")
    assert config.count("trusted_hash") == len(commands)
    # Trust is confirmed through `hooks/list` before the thread exists.
    methods = [method for method, _params in stack.launcher.server.records]
    assert methods[:6] == [
        "initialize",
        "initialized",
        "account/login/start",
        "account/read",
        "hooks/list",
        "thread/start",
    ]
    assert session.native_details["hooks_trusted"] == str(len(commands))

    context = json.loads((root / ".mission/hooks/context.json").read_text(encoding="utf-8"))
    assert context["lane_profile"] == "codex"
    assert context["harness_execution_id"] == stack.heid
    assert context["callback"]["url"].startswith(hook_rig.url + "/v1/applications/")
    token = (root / ".mission/bin/.token").read_text(encoding="utf-8")
    assert token and token not in json.dumps(context)
    (stored,) = hook_rig.tokens._tokens.values()
    assert stored.context.lane_profile == "codex"
    assert stored.context.execution_start is not None
    assert stored.context.execution_start.native_session_ref == session.native_session_ref
    assert token not in stored.token_hash


async def test_kernel_before_tool_denies_a_fenced_shell_call_end_to_end(
    tmp_path: Path, hook_rig: HookRig
) -> None:
    stack = kernel_stack(
        tmp_path,
        "turn_tool_hook_1",
        "turn_tool_hook_2",
        hooks=hook_rig.service,
        callback_url=hook_rig.url,
    )
    session = await started(stack)
    server = stack.launcher.server

    await run_turn(stack, session, 1)
    assert server.hook_runs and all(run.exit_code == 0 for run in server.hook_runs)
    assert command_statuses(stack) == ["completed"]
    # `before_tool` and `before_shell` gate the same call: one Operation Intent.
    (intent,) = hook_rig.intents.intents()
    assert (intent.effect_ref, intent.effect_kind, intent.lane_profile) == (
        "tool_use:call-1",
        "shell",
        "codex",
    )

    identity = stack.identity
    await hook_rig.fences.persist(
        StopFence(
            request_scope=identity.request_scope,
            run_id=identity.run_key,
            generation=1,
            command_id="cancel-mo-03",
            reason="operator stop",
            requested_at=datetime.now(UTC),
        )
    )
    server.hook_runs.clear()
    await run_turn(stack, session, 2)
    assert command_statuses(stack) == ["completed", "declined"]
    fenced = [run for run in server.hook_runs if "mc.stop_fence" in run.command]
    # Codex's JSON refusal (exit 0): its Windows PowerShell hook shell would turn exit 2 into a
    # failed, non-blocking hook.
    assert fenced and all(run.blocked and run.exit_code == 0 for run in fenced)
    denied = json.loads(fenced[0].stdout)["hookSpecificOutput"]
    assert denied["hookEventName"] == "PreToolUse"
    assert denied["permissionDecision"] == "deny"
    reason = "run is stop-fenced by immediate cancel cancel-mo-03"
    assert denied["permissionDecisionReason"] == reason
    assert [intent.effect_ref for intent in hook_rig.intents.intents()] == ["tool_use:call-1"]


async def test_end_session_revokes_the_token_and_keeps_kernel_files_out_of_the_patch(
    tmp_path: Path, hook_rig: HookRig
) -> None:
    stack = kernel_stack(tmp_path, hooks=hook_rig.service, callback_url=hook_rig.url)
    session = await started(stack)
    root = Path(stack.harness.lease_path(stack.heid))
    receipt = await stack.harness.end_session(
        EndSessionRequest(**fields(stack, "end"), session=session, reason="done")
    )
    assert receipt.patch_ref is not None
    patch = stack.artifacts.stored[receipt.patch_ref].decode("utf-8").splitlines()
    assert not set(KERNEL_FILES) & set(patch)
    (stored,) = hook_rig.tokens._tokens.values()
    assert stored.revoked_at is not None
    # A hook that still fires after the end is refused by the callback: fail closed.
    completed = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, ".mission/hooks/kernel.py", "before_tool", "mc.stop_fence"],
        input=json.dumps({"tool_name": "Bash", "tool_use_id": "late", "tool_input": {}}),
        capture_output=True,
        text=True,
        cwd=root,
        timeout=60,
        check=False,
    )
    late = json.loads(completed.stdout)["hookSpecificOutput"]
    assert completed.returncode == 0 and late["permissionDecision"] == "deny"
    assert "callback failed" in late["permissionDecisionReason"]


async def test_codex_untrusted_hooks_refuse_the_start(tmp_path: Path, hook_rig: HookRig) -> None:
    stack = kernel_stack(tmp_path, hooks=hook_rig.service, callback_url=hook_rig.url)
    harness = stack.harness
    harness.stage(stack.heid, stack.operation)
    values = fields(stack)
    prepared = await harness.prepare(
        PrepareRequest(
            **values,
            run_id=stack.operation.identity.run_id,
            operation_id=stack.operation.identity.operation_id,
            attempt_no=1,
        )
    )
    # The agent-writable home lost one trust record: Codex would skip that Kernel Hook.
    config = Path(harness.lease_path(stack.heid)) / CODEX_HOME_DIR / "config.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("trusted_hash", "stale_hash", 1), encoding="utf-8")
    with pytest.raises(LaneProjectionError) as refused:
        await harness.start(StartRequest(**values, prepared=prepared))
    assert refused.value.code == "HOOK_TRUST_UNVERIFIED"
    assert "untrusted" in str(refused.value)
    methods = [method for method, _params in stack.launcher.server.records]
    assert "thread/start" not in methods
    assert stack.launcher.server.offline


async def test_kernel_hooks_are_refused_where_they_cannot_run(tmp_path: Path) -> None:
    without_service = kernel_stack(tmp_path / "a")
    with pytest.raises(LaneProjectionError) as refused:
        await started(without_service)
    assert refused.value.code == "UNSUPPORTED_BEHAVIOR"
    assert "no hook callback service" in str(refused.value)

    owner_home = kernel_stack(tmp_path / "b", hooks=memory_hooks()[0], codex_home_mode="owner")
    with pytest.raises(LaneProjectionError) as refused:
        await started(owner_home)
    assert refused.value.code == "HOOK_TRUST_UNVERIFIED"
    assert "isolated CODEX_HOME" in str(refused.value)
    assert owner_home.launcher.launches == []


def test_the_kernel_script_names_the_codex_events_of_the_hook_mapping() -> None:
    namespace: dict[str, object] = {}
    exec(compile(kernel_hook_script(), "kernel.py", "exec"), namespace)  # noqa: S102
    mapping = HOOK_EVENT_MAPPING[LaneProfile.CODEX]
    assert namespace["CODEX_EVENTS"] == {
        event.value: native.native_event for event, native in mapping.items()
    }

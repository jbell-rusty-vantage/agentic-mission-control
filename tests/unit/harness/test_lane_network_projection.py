"""MO-15: each lane projects the resolved network policy its binding seals, and records it.

A binding carrying a resolved policy (declared hosts, kit egress and the Signal Ingress host)
drives each lane through its own path; only the spawn boundary is replaced:

- `codex`: the workspace-write sandbox's `network_access` reaches `codex app-server` as a
  `-c` override (captured from the production launcher's argv); allowlists are advisory there;
- `claude_agent_sdk`: the policy becomes `ClaudeAgentOptions.sandbox`, which the production
  transport hands the CLI in `--settings` (captured); Bash-only confinement is advisory;
- `cursor_local` and `cursor_cloud`: nothing Mission Control writes restricts their egress yet,
  so they record `unsupported` (no sandbox) and `advisory` (the bound environment);

and every lane records the policy digest, its enforcement and the delivery with its native
session identity, a continuation target too. A binding without a policy changes nothing.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.claude.host import host_gate as claude_host_gate
from mission_control.adapters.claude.transport import SdkClientFactory
from mission_control.adapters.codex import launcher as codex_launcher
from mission_control.adapters.codex.harness import network_overrides, network_projection
from mission_control.adapters.codex.launcher import SubprocessAppServerLauncher
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.domain.execution.bindings import (
    CodexAppServerOptions,
    ProviderExecutionBinding,
)
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import (
    CursorExecutionBinding,
    PrepareRequest,
    SessionHandle,
    StartRequest,
)
from mission_control.domain.execution.network_policy import ResolvedNetworkPolicy
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.cursor_controls import started_session
from tests.fixtures.cursor_local import local_stack
from tests.fixtures.lane_bindings import lane_fields
from tests.unit.claude.fixtures import (
    base_operation,
    claude_binding,
    claude_operation,
    claude_stack,
    materialization_digest_for,
)
from tests.unit.codex.drive import started
from tests.unit.codex.fixture_app_server import FixtureLauncher, load_script
from tests.unit.codex.support import codex_binding, codex_operation, codex_stack

INGRESS = "mc-ingress.vercel.app"
POLICY = ResolvedNetworkPolicy(
    mode="allowlist",
    hosts=("api.firecrawl.dev", INGRESS, "pypi.org"),
    signal_ingress=INGRESS,
)
CLOSED = ResolvedNetworkPolicy(mode="none")


def _environment(host_profile: str, policy: ResolvedNetworkPolicy) -> dict[str, Any]:
    return {
        "kind": "local_workspace",
        "host_profile": host_profile,
        "network": policy,
        "network_policy_ref": policy.digest,
    }


def _recorded(handle: SessionHandle, policy: ResolvedNetworkPolicy, enforcement: str) -> None:
    details = handle.native_details
    assert details["network_policy_ref"] == policy.digest
    assert details["network_enforcement"] == enforcement


# --- codex --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("policy", "override", "enforcement"),
    [
        (POLICY, "sandbox_workspace_write.network_access=true", "advisory"),
        (CLOSED, "sandbox_workspace_write.network_access=false", "enforced"),
    ],
)
async def test_codex_app_server_launches_with_the_sandbox_network_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: ResolvedNetworkPolicy,
    override: str,
    enforcement: str,
) -> None:
    operation = codex_operation(codex_binding(environment=_environment("worker.linux.wsl", policy)))
    stack = codex_stack(tmp_path, "turn_full", operation=operation)
    try:
        handle = await started(stack)
    finally:
        await stack.launcher.shutdown()
    spec = stack.launcher.launches[0].spec
    assert override in spec.config_overrides
    _recorded(handle, policy, enforcement)
    assert handle.native_details["network_delivery"] == "session_options"

    argv: list[str] = []

    class _Spawned(Exception):
        pass

    async def spawn(*args: Any, **kwargs: Any) -> Any:
        argv.extend(args)
        raise _Spawned

    monkeypatch.setattr(codex_launcher, "subprocess_supported", lambda: (True, "test"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    production = SubprocessAppServerLauncher("codex", probe_version=False)
    with pytest.raises(_Spawned):
        await production.launch(spec)
    assert argv[argv.index(override) - 1] == "-c"


async def test_a_codex_continuation_target_records_the_same_policy(tmp_path: Path) -> None:
    launcher = FixtureLauncher(
        scripts=[load_script("turn_full")], launch_scripts={1: [load_script("turn_full")]}
    )
    operation = codex_operation(codex_binding(environment=_environment("worker.linux.wsl", POLICY)))
    stack = codex_stack(tmp_path, launcher=launcher, approvals=False, operation=operation)
    try:
        source = await started(stack)
        handover = await stack.harness.hydrate_session(
            stack.heid,
            transfer_id="t-1",
            prompt_text="continue",
            source_session_ref=source.native_session_ref,
        )
    finally:
        await stack.launcher.shutdown()
    target = launcher.launches[1].spec
    assert "sandbox_workspace_write.network_access=true" in target.config_overrides
    _recorded(handover.session, POLICY, "advisory")


def test_a_codex_binding_without_a_policy_projects_nothing() -> None:
    binding = codex_binding()
    options = binding.provider_options
    assert isinstance(options, CodexAppServerOptions)
    assert network_projection(binding, options) is None
    assert network_overrides(None) == ()
    read_only = options.model_copy(update={"sandbox_mode": "read-only"})
    bound = codex_binding(environment=_environment("worker.linux.wsl", POLICY))
    projection = network_projection(bound, read_only)
    assert projection is not None and projection.observation_degraded
    # The read-only sandbox has no network to switch: no override is sent.
    assert network_overrides(projection) == ()


# --- claude_agent_sdk -----------------------------------------------------------------------------


class _ClaudeProcess:
    stdin = None
    stdout = None
    stderr = None


async def _claude_start(tmp_path: Path, operation: OperationExecutionRequest) -> Any:
    stack = claude_stack(tmp_path, operation=operation)
    identity = LaneExecutionIdentity.of(stack.operation, "claude_agent_sdk", 1)
    heid = str(identity.harness_execution_id)
    assert ProviderExecutionBinding.carried_by(stack.operation) is not None
    fields = {
        "scope": harness_scope(identity.request_scope),
        "lane_profile": "claude_agent_sdk",
        "harness_execution_id": heid,
        "binding_digest": ProviderExecutionBinding.carried_by(stack.operation).binding_digest,
        "idempotency_key": f"{heid}:1:start",
        "generation": 1,
    }
    stack.harness.stage(heid, stack.operation)
    prepared = await stack.harness.prepare(
        PrepareRequest(
            **fields,
            run_id=stack.operation.identity.run_id,
            operation_id=stack.operation.identity.operation_id,
            attempt_no=1,
        )
    )
    handle = await stack.harness.start(StartRequest(**fields, prepared=prepared))
    return stack, handle


def _claude_operation(policy: ResolvedNetworkPolicy | None) -> OperationExecutionRequest:
    environment: dict[str, Any] = (
        _environment("worker.linux.default", policy)
        if policy is not None
        else {"kind": "local_workspace", "host_profile": "worker.linux.default"}
    )
    return claude_operation(
        binding=claude_binding(
            materialization_digest=materialization_digest_for(base_operation()),
            environment=environment,
        )
    )


async def test_the_claude_cli_runs_bash_in_a_sandbox_limited_to_the_policy(
    tmp_path: Path,
) -> None:
    stack, handle = await _claude_start(tmp_path, _claude_operation(POLICY))
    options = stack.factory.last.options
    assert options.sandbox == {
        "enabled": True,
        "autoAllowBashIfSandboxed": False,
        "allowUnsandboxedCommands": False,
        "network": {"allowedDomains": list(POLICY.hosts)},
    }
    _recorded(handle, POLICY, "advisory")

    commands: list[list[str]] = []

    async def spawn(cmd: list[str], **_kwargs: Any) -> _ClaudeProcess:
        commands.append(cmd)
        return _ClaudeProcess()

    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    linux = claude_host_gate(system="Linux", release="6.8.0", event_loop="none")
    production = SdkClientFactory(spawn=spawn, gate=lambda: linux)
    client = production.create(
        replace(options, cli_path=str(cli)), environment=stack.factory.last.environment
    )
    await client._custom_transport.connect()
    command = commands[-1]
    settings = json.loads(command[command.index("--settings") + 1])
    assert settings["sandbox"]["network"]["allowedDomains"] == list(POLICY.hosts)
    assert settings["sandbox"]["autoAllowBashIfSandboxed"] is False


async def test_without_a_policy_the_claude_sandbox_stays_off(tmp_path: Path) -> None:
    stack, handle = await _claude_start(tmp_path, _claude_operation(None))
    assert stack.factory.last.options.sandbox is None
    assert "network_enforcement" not in handle.native_details


# --- cursor -------------------------------------------------------------------------------------


def _with_network(binding: CursorExecutionBinding) -> CursorExecutionBinding:
    fields = binding.model_dump(exclude={"binding_digest"})
    return CursorExecutionBinding.sealed(**{**fields, "network": POLICY})


async def test_cursor_local_records_that_nothing_restricts_its_egress(tmp_path: Path) -> None:
    stack = local_stack(tmp_path, binding_changes={"network": POLICY})
    _, handle = await started_session(stack)
    _recorded(handle, POLICY, "unsupported")
    assert handle.native_details["network_delivery"] == "none"


async def test_cursor_cloud_records_the_bound_environment_as_advisory(tmp_path: Path) -> None:
    stack = cloud_stack(tmp_path)
    assert CursorExecutionBinding.carried_by(stack.operation) is not None
    binding = _with_network(CursorExecutionBinding.carried_by(stack.operation))
    stack.operation = OperationExecutionRequest.model_validate(
        {**stack.operation.model_dump(mode="python"), **lane_fields(binding)}
    )
    heid, handle = await started_session(stack)
    _recorded(handle, POLICY, "advisory")
    # A continuation's fresh agent runs in the same bound environment.
    await stack.harness.hydrate_agent(
        heid,
        transfer_id="t-1",
        files=[(".mission/context.md", b"# continuation\n")],
        prompt="continue",
        source_session_ref=handle.native_session_ref,
    )
    handover = await stack.harness.pending_handover(heid)
    assert handover is not None
    _recorded(handover.session, POLICY, "advisory")

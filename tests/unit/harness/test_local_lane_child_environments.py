"""MO-04 acceptance: only allowlisted names reach each local provider child process.

A worker environment seeded with sentinel values (the application and test DSNs, other
providers' keys, a GitHub token, cloud credentials, an unrelated setting) drives each local
lane through its own environment path; only the spawn boundary is replaced:

- `claude_agent_sdk`: stage, prepare and start over the FIXTURE client factory; the production
  `SdkClientFactory` then builds the CLI transport from the options and environment the
  harness produced, and `connect()` spawns the `claude -v` probe and the CLI (captured);
- `codex`: stage, prepare and start over the FIXTURE app-server launcher; the production
  `SubprocessAppServerLauncher` hands `LaunchSpec.env` to `codex app-server` (captured at
  `asyncio.create_subprocess_exec`);
- `cursor_local`: stage, prepare and start over the replaying bridge launcher; the production
  `launch_bridge_client` spawns that environment as a real Python child standing in for
  `cursor-sdk-bridge`, which reports the environment it actually received.

Each child receives exactly the inherited platform names present on the worker, the admitted
route's credential, the variables the projected MCP configuration reads, the lane's own
values and its SDK's markers; no sentinel value reaches any of them. MO-11: with the Secret
Broker composed, the binding's declared agent-phase secrets join that set with the broker's
values (a minted signal token bound to the attempt included), and nothing else does.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.claude.host import host_gate as claude_host_gate
from mission_control.adapters.claude.transport import SdkClientFactory
from mission_control.adapters.codex import launcher as codex_launcher
from mission_control.adapters.codex.launcher import SubprocessAppServerLauncher
from mission_control.adapters.cursor.bridge_spawn import launch_bridge_client
from mission_control.adapters.secrets.minted import InMemoryMintedCredentialStore
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.application.secrets.broker import SecretBroker, SecretUnavailable
from mission_control.application.secrets.delivery import ProcessSecretDelivery
from mission_control.application.secrets.minting import CredentialBinding, CredentialMinter
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import PrepareRequest, StartRequest
from tests.fixtures.cursor_controls import started_session
from tests.fixtures.cursor_local import local_stack
from tests.fixtures.lane_turns import lane_stack
from tests.fixtures.projections.rows import firecrawl_row, tavily_row
from tests.unit.claude.fixtures import (
    claude_binding,
    claude_operation,
    claude_stack,
    fixture_admission,
)
from tests.unit.codex.drive import started
from tests.unit.codex.fixture_app_server import FixtureLauncher, load_script
from tests.unit.codex.support import (
    CodexStack,
    StaticAuth,
    StaticProjectionSource,
    admission,
    build_harness,
    codex_binding,
    codex_operation,
    fixture_settings,
)
from tests.unit.codex.test_kernel_hooks import memory_hooks

SENTINEL = "mo04-sentinel-value"
WORKER: dict[str, str] = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/home/worker",
    "LANG": "C.UTF-8",
    "CLAUDE_CONFIG_DIR": "/home/worker/.claude",
    "CODEX_HOME": "/home/worker/.codex",
    "TAVILY_API_KEY": "tvly-declared-by-the-projection",
    "FIRECRAWL_API_KEY": "fc-declared-by-the-projection",
    "ANTHROPIC_API_KEY": "sk-ant-worker-key",
    "OPENAI_API_KEY": "sk-openai-worker-key",
    "ANTHROPIC_AUTH_TOKEN": SENTINEL,
    "CURSOR_API_KEY": SENTINEL,
    "MISSION_CONTROL_DATABASE_URL": f"postgresql://{SENTINEL}@127.0.0.1:55432/mc",
    "MISSION_CONTROL_TEST_ADMIN_DSN": f"postgresql://{SENTINEL}@127.0.0.1:55433/postgres",
    "SUPABASE_SERVICE_ROLE_KEY": SENTINEL,
    "GITHUB_TOKEN": SENTINEL,
    "AWS_SECRET_ACCESS_KEY": SENTINEL,
    "UNRELATED_SETTING": SENTINEL,
}
PLATFORM = {"PATH", "HOME", "LANG"}
CLAUDE_SDK_MARKERS = {
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_AGENT_SDK_VERSION",
    "CLAUDE_CODE_SDK_READS_SESSION_STATE",
    "PWD",
}
CURSOR_SDK_MARKERS = {"CURSOR_SDK_CLIENT_LANGUAGE", "CURSOR_SDK_PYTHON_VERSION"}


def _no_sentinel(environment: Mapping[str, str]) -> None:
    assert not [name for name, value in environment.items() if SENTINEL in value]


# --- claude_agent_sdk -----------------------------------------------------------------------


class _ClaudeProcess:
    """What the capturing spawn returns: no streams, so `connect()` wires nothing further."""

    stdin = None
    stdout = None
    stderr = None


async def _claude_spawns(
    tmp_path: Path,
    route: str,
    *,
    operation: OperationExecutionRequest | None = None,
    secrets: ProcessSecretDelivery | None = None,
) -> tuple[list[dict[str, Any]], Any]:
    """Every environment the production transport spawned with (the `claude -v` probe, then
    the CLI) for the options and environment the harness produced at `start`."""

    unset = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if route == "owner_cli_login" else ()
    stack = claude_stack(
        tmp_path,
        operation=operation,
        admission=fixture_admission(route=route, env_unset=unset),
        environ=WORKER,
        secrets=secrets,
    )
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
    await stack.harness.start(StartRequest(**fields, prepared=prepared))
    harnessed = stack.factory.last
    spawns: list[dict[str, Any]] = []

    async def spawn(cmd: list[str], **kwargs: Any) -> _ClaudeProcess:
        spawns.append(kwargs["env"])
        return _ClaudeProcess()

    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    linux = claude_host_gate(system="Linux", release="6.8.0", event_loop="none")
    production = SdkClientFactory(spawn=spawn, gate=lambda: linux)
    options = replace(harnessed.options, cli_path=str(cli))
    client = production.create(options, environment=harnessed.environment)
    await client._custom_transport.connect()
    return spawns, stack


@pytest.mark.parametrize(
    ("route", "admitted"),
    [("owner_cli_login", set()), ("api_key", {"ANTHROPIC_API_KEY"})],
)
async def test_the_claude_cli_receives_only_the_allowlist(
    tmp_path: Path, route: str, admitted: set[str]
) -> None:
    (probe, spawned), stack = await _claude_spawns(tmp_path, route)
    assert probe == spawned, "the version probe runs with the same explicit environment"
    expected = PLATFORM | admitted | {"TAVILY_API_KEY", "CLAUDE_CONFIG_DIR"} | CLAUDE_SDK_MARKERS
    assert set(spawned) == expected
    assert spawned["TAVILY_API_KEY"] == WORKER["TAVILY_API_KEY"]
    if route == "owner_cli_login":
        assert spawned["CLAUDE_CONFIG_DIR"] == WORKER["CLAUDE_CONFIG_DIR"], "the owner's sign-in"
    else:
        assert spawned["ANTHROPIC_API_KEY"] == WORKER["ANTHROPIC_API_KEY"]
        (lease,) = stack.workspace.registry.values()
        assert spawned["CLAUDE_CONFIG_DIR"].startswith(lease.path), "relocated under the lease"
    _no_sentinel(spawned)


# --- codex ----------------------------------------------------------------------------------


async def _codex_launch(
    tmp_path: Path,
    route: str,
    *,
    secret_refs: tuple[str, ...] = (),
    secrets: ProcessSecretDelivery | None = None,
) -> tuple[Mapping[str, str], Path]:
    # Owner homes cannot receive generated hook trust; exercise MCP secrets there.
    # The isolated API route retains the default Kernel Hooks projection.
    projection = HOST_PROJECTORS.render(
        (tavily_row(), firecrawl_row()),
        "codex",
        "Mission.",
        **({"kernel_hooks": (), "telemetry": False} if route == "owner_cli_login" else {}),
    )
    environment = {"kind": "local_workspace", "host_profile": "worker.linux.wsl"}
    operation = codex_operation(
        codex_binding(
            materialization_digest=projection_digest(projection),
            environment={**environment, "secret_refs": secret_refs},
        )
    )
    launcher = FixtureLauncher(scripts=[load_script("turn_full")])
    harness, leaser, artifacts, auth = build_harness(
        tmp_path,
        launcher,
        auth=StaticAuth(admission(route)),
        settings=fixture_settings(
            tmp_path,
            worker_environ=WORKER,
            **(
                {"codex_home_mode": "owner", "owner_codex_home": tmp_path / "owner-codex"}
                if route == "owner_cli_login"
                else {}
            ),
        ),
        projections=StaticProjectionSource(projection),
        # The projection runs the Kernel Hooks: the worker's hook service answers them (MO-03).
        hooks=memory_hooks()[0],
        secrets=secrets,
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
    try:
        await started(stack)
    finally:
        await launcher.shutdown()
    spec = launcher.launches[0].spec
    return spec.env, spec.codex_home


@pytest.mark.parametrize(
    ("route", "admitted"),
    [("owner_cli_login", set()), ("api_key", {"OPENAI_API_KEY"})],
)
async def test_codex_app_server_receives_only_the_allowlist_and_its_mcp_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str, admitted: set[str]
) -> None:
    environment, codex_home = await _codex_launch(tmp_path, route)
    # The projected `.codex/config.toml` forwards these to its MCP servers (`env_vars`,
    # `bearer_token_env_var`), so the app-server must hold them (gap G12).
    assert set(environment) == PLATFORM | admitted | {
        "TAVILY_API_KEY",
        "FIRECRAWL_API_KEY",
        "CODEX_HOME",
    }
    assert environment["FIRECRAWL_API_KEY"] == WORKER["FIRECRAWL_API_KEY"]
    assert environment["CODEX_HOME"] == str(codex_home) != WORKER["CODEX_HOME"]
    if route == "owner_cli_login":
        assert codex_home == tmp_path / "owner-codex"
    else:
        assert codex_home != tmp_path / "owner-codex"
    _no_sentinel(environment)

    spawned: dict[str, Any] = {}

    class _Spawned(Exception):
        pass

    async def spawn(*argv: Any, **kwargs: Any) -> Any:
        spawned.update(kwargs)
        raise _Spawned

    monkeypatch.setattr(codex_launcher, "subprocess_supported", lambda: (True, "test"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    production = SubprocessAppServerLauncher("codex", probe_version=False)
    with pytest.raises(_Spawned):
        await production.launch(
            codex_launcher.LaunchSpec(cwd=tmp_path, env=environment, codex_home=codex_home)
        )
    assert spawned["env"] == dict(environment)


# --- MO-11: broker-delivered secrets ---------------------------------------------------------

DELIVERED = "fc-delivered-by-the-broker-0011"
SECRET_REFS = (
    "FIRECRAWL_API_KEY=secret:firecrawl/api_key",
    "MC_SIGNAL_TOKEN=mint:signal_token;agent",
    "SETUP_ONLY=secret:firecrawl/api_key;setup",
)


class _StoreFixture:
    """The installation's secret store (FIXTURE): the owner's value for one path."""

    async def read(self, key: str) -> str | None:
        return DELIVERED if key == "firecrawl/api_key" else None


def _broker_delivery() -> tuple[ProcessSecretDelivery, InMemoryMintedCredentialStore]:
    minted = InMemoryMintedCredentialStore()
    broker = SecretBroker(
        environment=WorkerEnvironmentSource(WORKER),
        store=_StoreFixture(),
        minter=CredentialMinter(minted),
    )
    return ProcessSecretDelivery(broker), minted


async def test_the_claude_cli_receives_the_brokers_declared_secrets_and_nothing_else(
    tmp_path: Path,
) -> None:
    default = claude_operation()
    assert ProviderExecutionBinding.carried_by(default) is not None
    binding = claude_binding(
        materialization_digest=ProviderExecutionBinding.carried_by(default).materialization_digest,
        environment={
            "kind": "local_workspace",
            "host_profile": "worker.linux.default",
            "secret_refs": SECRET_REFS,
        },
    )
    delivery, minted = _broker_delivery()
    (_probe, spawned), stack = await _claude_spawns(
        tmp_path,
        "owner_cli_login",
        operation=claude_operation(binding=binding),
        secrets=delivery,
    )
    expected = PLATFORM | {"TAVILY_API_KEY", "CLAUDE_CONFIG_DIR"} | CLAUDE_SDK_MARKERS
    assert set(spawned) == expected | {"FIRECRAWL_API_KEY", "MC_SIGNAL_TOKEN"}
    assert spawned["FIRECRAWL_API_KEY"] == DELIVERED, "from the store, not the worker"
    (record,) = minted._records.values()
    identity = LaneExecutionIdentity.of(stack.operation, "claude_agent_sdk", 1)
    assert record.binding == CredentialBinding(
        identity.request_scope, identity.run_key, identity.activation_key, 1
    )
    _no_sentinel(spawned)


class _UnavailableOnceStore:
    """A store whose first read fails (the owner keyring locked, a refused Vault read)."""

    def __init__(self) -> None:
        self.reads = 0

    async def read(self, key: str) -> str | None:
        self.reads += 1
        if self.reads == 1:
            raise SecretUnavailable("the owner keyring is not available on this worker")
        return DELIVERED


async def test_a_retried_claude_start_resolves_the_brokers_secrets_again(
    tmp_path: Path,
) -> None:
    default = claude_operation()
    assert ProviderExecutionBinding.carried_by(default) is not None
    binding = claude_binding(
        materialization_digest=ProviderExecutionBinding.carried_by(default).materialization_digest,
        environment={
            "kind": "local_workspace",
            "host_profile": "worker.linux.default",
            "secret_refs": ("FIRECRAWL_API_KEY=secret:firecrawl/api_key",),
        },
    )
    store = _UnavailableOnceStore()
    broker = SecretBroker(environment=WorkerEnvironmentSource(WORKER), store=store)
    stack = claude_stack(
        tmp_path,
        operation=claude_operation(binding=binding),
        admission=fixture_admission(route="owner_cli_login"),
        environ=WORKER,
        secrets=ProcessSecretDelivery(broker),
    )
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
    with pytest.raises(SecretUnavailable):
        await stack.harness.start(StartRequest(**fields, prepared=prepared))
    assert stack.factory.clients == [], "no CLI is launched without its declared secret"

    # The activity's retry on the same worker: the environment is built again, not skipped.
    await stack.harness.start(StartRequest(**fields, prepared=prepared))
    (client,) = stack.factory.clients
    environment = client.environment
    assert store.reads == 2
    assert environment["FIRECRAWL_API_KEY"] == DELIVERED
    assert set(environment) >= PLATFORM
    _no_sentinel(environment)


async def test_codex_app_server_receives_the_brokers_values_over_the_workers(
    tmp_path: Path,
) -> None:
    delivery, _minted = _broker_delivery()
    environment, codex_home = await _codex_launch(
        tmp_path, "owner_cli_login", secret_refs=SECRET_REFS, secrets=delivery
    )
    assert set(environment) == PLATFORM | {
        "TAVILY_API_KEY",
        "FIRECRAWL_API_KEY",
        "MC_SIGNAL_TOKEN",
        "CODEX_HOME",
    }
    assert environment["FIRECRAWL_API_KEY"] == DELIVERED != WORKER["FIRECRAWL_API_KEY"]
    assert environment["CODEX_HOME"] == str(codex_home)
    _no_sentinel(environment)


# --- cursor_local ---------------------------------------------------------------------------

# Stands in for `cursor-sdk-bridge`: reports its environment, announces itself on stderr and
# serves until the client's shutdown request arrives.
_REPORTER = """
import http.server, json, os, sys, threading
with open(sys.argv[1], "w", encoding="utf-8") as report:
    json.dump(dict(os.environ), report)
class Shutdown(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()
        threading.Thread(target=server.shutdown).start()
    def log_message(self, *args):
        pass
server = http.server.HTTPServer(("127.0.0.1", 0), Shutdown)
discovery = {"schemaVersion": 1, "transport": "tcp", "protocol": "connect",
             "url": f"http://127.0.0.1:{server.server_port}", "authToken": "fixture-token"}
sys.stderr.write("cursor-sdk-bridge ready " + json.dumps(discovery) + "\\n")
sys.stderr.flush()
server.serve_forever()
"""


async def test_the_cursor_bridge_process_receives_only_the_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real child process needs the host's own SYSTEMROOT on Windows (an inherited name).
    worker = {**WORKER, **{k: v for k, v in os.environ.items() if k.upper() == "SYSTEMROOT"}}
    stack = local_stack(tmp_path, settings_changes={"worker_environ": worker})
    await started_session(stack)
    (environment,) = stack.launcher.environments
    expected = {name.upper() for name in environment}
    # The API key travels in agent options, never in the bridge environment.
    assert expected - {"SYSTEMROOT"} == PLATFORM | {"TAVILY_API_KEY"}
    _no_sentinel(environment)

    import httpx

    from mission_control.adapters.cursor import bridge_spawn

    class Client:
        def __init__(self, url):
            self.url = url

        async def ping(self):
            return {}

        async def get_version(self):
            return {"version": "fixture"}

        async def aclose(self):
            pass

        async def shutdown(self, grace_seconds=0):
            async with httpx.AsyncClient() as http:
                await http.post(self.url)

    monkeypatch.setattr(
        bridge_spawn.AsyncClient, "connect", lambda url, *args, **kwargs: Client(url)
    )

    report = tmp_path / "bridge-environment.json"
    client = await launch_bridge_client(
        [sys.executable, "-c", _REPORTER, str(report)],
        workspace=tmp_path,
        state_root=tmp_path / "bridge-state",
        environment=environment,
        discovery_timeout_s=60,
    )
    await client.aclose()
    # Closing a transport leaves the detached sidecar alive; cleanup is explicit.
    await bridge_spawn.shutdown_bridge(tmp_path / "bridge-state", workspace=tmp_path)
    received: dict[str, str] = json.loads(report.read_text(encoding="utf-8"))
    from_worker = {name.upper() for name in received} & {name.upper() for name in worker}
    assert from_worker == expected
    assert {name.upper() for name in received} >= CURSOR_SDK_MARKERS
    assert received.get("TAVILY_API_KEY") == WORKER["TAVILY_API_KEY"]
    _no_sentinel(received)

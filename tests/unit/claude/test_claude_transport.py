"""MP-07: the production client factory spawns the CLI with the allowlisted child environment
(MO-04; nothing inherited), the SDK command line and the `stdio` permission prompt tool. MO-73:
it gives the transcript mirror the child's config dir, and a resume restores the stored session
into that config dir before the CLI starts. The spawn is a FIXTURE: no Claude Code runs here."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import pytest
from claude_agent_sdk import project_key_for_directory
from claude_agent_sdk._errors import CLIConnectionError
from claude_agent_sdk._internal.session_resume import build_mirror_batcher
from claude_agent_sdk.client import ClaudeSDKClient
from claude_agent_sdk.types import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    SessionKey,
    SessionStoreEntry,
    _configure_can_use_tool,
)

from mission_control.adapters.claude.host import (
    LANE_UNSUPPORTED_OS,
    HostGate,
    HostUnsupported,
    host_gate,
)
from mission_control.adapters.claude.transport import (
    ExplicitEnvironmentCliTransport,
    SdkClientFactory,
    cli_config_dir,
    restore_resume_session,
)
from mission_control.adapters.claude.workspace import StateRootSessionStore
from mission_control.application.execution.child_environment import provider_child_environment
from tests.unit.claude.fixtures import FIXTURE_ENVIRON, fixture_admission

SESSION: Final = "7c1f0a52-9d3e-4b6a-8f21-5e0c9a7b3d14"
MAIN: Final = (
    {"type": "user", "uuid": "u-1", "message": {"role": "user", "content": "first"}},
    {"type": "assistant", "uuid": "a-1", "parentUuid": "u-1"},
)
AGENT: Final = (
    {"type": "assistant", "uuid": "s-1", "isSidechain": True},
    {"type": "agent_metadata", "agentType": "general-purpose"},
)


class _FakeProcess:
    stdin = None
    stdout = None
    stderr = None


@pytest.fixture
def spawned() -> dict[str, Any]:
    return {}


def _spawn(spawned: dict[str, Any]) -> Any:
    async def spawn(cmd: list[str], **kwargs: Any) -> _FakeProcess:
        spawned["cmd"] = cmd
        spawned["kwargs"] = kwargs
        return _FakeProcess()

    return spawn


def _linux() -> HostGate:
    return host_gate(system="Linux", release="6.6.87.2-microsoft-standard-WSL2", event_loop="none")


async def _can_use_tool(*_args: Any) -> PermissionResultAllow:
    return PermissionResultAllow()


async def _ignore_mirror_error(_key: Any, _error: str) -> None:
    return None


async def test_the_spawn_environment_is_the_admitted_child_environment_only(
    tmp_path: Path, spawned: dict[str, Any]
) -> None:
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    environment = provider_child_environment(
        FIXTURE_ENVIRON, fixture_admission(), extra={"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
    )
    options = ClaudeAgentOptions(
        cwd=str(tmp_path),
        cli_path=str(cli),
        setting_sources=["project"],
        resume="sess-fixture-claude-0001",
        env={"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "1000"},
    )
    transport = ExplicitEnvironmentCliTransport(
        options, environment=environment, spawn=_spawn(spawned), check_version=False
    )
    await transport.connect()
    env = spawned["kwargs"]["env"]
    assert env == transport.spawn_environment()
    # The allowlist plus the SDK's markers and `options.env`: no worker credential reaches it.
    assert set(env) == {
        "PATH",
        "HOME",
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_AGENT_SDK_VERSION",
        "CLAUDE_CODE_SDK_READS_SESSION_STATE",
        "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS",
        "PWD",
    }
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "cfg")
    assert env["CLAUDE_CODE_ENTRYPOINT"] == "sdk-py"
    assert env["CLAUDE_AGENT_SDK_VERSION"] == "0.2.165"
    assert env["CLAUDE_CODE_SDK_READS_SESSION_STATE"] == "1"
    assert env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "1000", "options.env still applies"
    assert env["PWD"] == str(tmp_path)
    assert "CLAUDECODE" not in env
    cmd = spawned["cmd"]
    assert cmd[0] == str(cli)
    assert "--resume=sess-fixture-claude-0001" in cmd
    assert "--setting-sources=project" in cmd
    assert cmd[-2:] == ["--input-format", "stream-json"]
    assert spawned["kwargs"]["cwd"] == str(tmp_path)
    assert transport.is_ready()


def test_the_factory_routes_permission_prompts_over_stdio_and_keeps_the_transport(
    tmp_path: Path, spawned: dict[str, Any]
) -> None:
    factory = SdkClientFactory(spawn=_spawn(spawned), check_version=False, gate=_linux)
    assert factory.versions == {"claude_agent_sdk": "0.2.165", "claude_code_bundled": "2.1.294"}
    options = ClaudeAgentOptions(cwd=str(tmp_path), can_use_tool=_can_use_tool)
    client = factory.create(options, environment={"PATH": "/usr/bin"})
    assert isinstance(client, ClaudeSDKClient)
    transport = client._custom_transport
    assert isinstance(transport, ExplicitEnvironmentCliTransport)
    # The transport was built from the configured copy (the client's own copy never reaches
    # it), so the CLI gets `--permission-prompt-tool stdio`; the client keeps the options as
    # given, because `connect` configures them again and both settings together raise.
    assert transport._options.permission_prompt_tool_name == "stdio"
    assert client.options.permission_prompt_tool_name is None
    assert _configure_can_use_tool(client.options).permission_prompt_tool_name == "stdio"
    assert transport.spawn_environment()["CLAUDE_AGENT_SDK_VERSION"] == "0.2.165"
    assert "ANTHROPIC_API_KEY" not in transport.spawn_environment()


def test_the_factory_gives_the_transcript_mirror_the_child_config_dir(tmp_path: Path) -> None:
    factory = SdkClientFactory(spawn=_spawn({}), check_version=False, gate=_linux)
    relocated = str(tmp_path / "cfg")
    options = ClaudeAgentOptions(cwd=str(tmp_path), env={"CLAUDE_CODE_MAX_RETRIES": "1"})
    client = factory.create(options, environment={"CLAUDE_CONFIG_DIR": relocated})
    # `build_mirror_batcher` resolves the projects dir from the client's `options.env`: the
    # same dir the CLI writes under, or every `transcript_mirror` frame would be dropped.
    assert client.options.env == {"CLAUDE_CODE_MAX_RETRIES": "1", "CLAUDE_CONFIG_DIR": relocated}
    projects = build_mirror_batcher(
        StateRootSessionStore(tmp_path), None, client.options.env, _ignore_mirror_error
    ).projects_dir
    assert Path(projects) == Path(relocated) / "projects"
    unchanged = factory.create(options, environment={"PATH": "/usr/bin"})
    assert unchanged.options.env == {"CLAUDE_CODE_MAX_RETRIES": "1"}


# --- the store-backed resume restore ----------------------------------------------------------


async def _stored_session(tmp_path: Path, cwd: Path) -> StateRootSessionStore:
    store = StateRootSessionStore(tmp_path / "state")
    key: SessionKey = {"project_key": project_key_for_directory(str(cwd)), "session_id": SESSION}
    await store.append(key, [dict(entry) for entry in MAIN])
    await store.append({**key, "subpath": "subagents/agent-a1"}, [dict(entry) for entry in AGENT])
    return store


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def test_a_resume_restores_the_stored_session_into_the_cli_config_dir(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    store = await _stored_session(tmp_path, cwd)
    config = tmp_path / "cfg"
    options = ClaudeAgentOptions(cwd=str(cwd), resume=SESSION, session_store=store)
    restored = await restore_resume_session(options, config)
    project = config / "projects" / project_key_for_directory(str(cwd))
    assert restored == project / f"{SESSION}.jsonl"
    assert _jsonl(restored) == list(MAIN)
    # Subagent transcripts land where the CLI reads them, their metadata in the sidecar.
    agent = project / SESSION / "subagents" / "agent-a1.jsonl"
    assert _jsonl(agent) == [AGENT[0]]
    sidecar = json.loads(agent.with_name("agent-a1.meta.json").read_text(encoding="utf-8"))
    assert sidecar == {"agentType": "general-purpose"}
    assert not (config / ".credentials.json").exists(), "no credential is ever copied"


async def test_the_cli_own_transcript_is_never_overwritten(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    store = await _stored_session(tmp_path, cwd)
    config = tmp_path / "cfg"
    own = config / "projects" / project_key_for_directory(str(cwd)) / f"{SESSION}.jsonl"
    own.parent.mkdir(parents=True)
    own.write_text('{"type": "user", "uuid": "u-local"}\n', encoding="utf-8")
    options = ClaudeAgentOptions(cwd=str(cwd), resume=SESSION, session_store=store)
    assert await restore_resume_session(options, config) is None
    assert _jsonl(own) == [{"type": "user", "uuid": "u-local"}]


@pytest.mark.parametrize(
    "changes",
    [
        {"session_store": None},
        {"resume": None},
        {"resume": "sess-not-a-uuid"},
        {"resume": "0b5c3c55-0000-4000-8000-000000000000"},
    ],
    ids=["no-store", "no-resume", "non-uuid", "unknown-session"],
)
async def test_nothing_is_restored_without_a_stored_session(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    store = await _stored_session(tmp_path, cwd)
    options = replace(
        ClaudeAgentOptions(cwd=str(cwd), resume=SESSION, session_store=store), **changes
    )
    assert await restore_resume_session(options, tmp_path / "cfg") is None
    assert not (tmp_path / "cfg").exists()


async def test_the_transport_restores_before_it_spawns_the_cli(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    store = await _stored_session(tmp_path, cwd)
    config = tmp_path / "cfg"
    transcript = config / "projects" / project_key_for_directory(str(cwd)) / f"{SESSION}.jsonl"
    seen: dict[str, Any] = {}

    async def spawn(cmd: list[str], **kwargs: Any) -> _FakeProcess:
        seen["restored"] = transcript.is_file()
        seen["cmd"] = cmd
        return _FakeProcess()

    options = ClaudeAgentOptions(
        cwd=str(cwd), cli_path=str(tmp_path / "claude"), resume=SESSION, session_store=store
    )
    transport = ExplicitEnvironmentCliTransport(
        options, environment={"CLAUDE_CONFIG_DIR": str(config)}, spawn=spawn, check_version=False
    )
    await transport.connect()
    assert seen["restored"], "the transcript was in place when the CLI started"
    assert f"--resume={SESSION}" in seen["cmd"] and "--session-mirror" in seen["cmd"]


async def test_a_store_failure_refuses_the_connection_before_anything_spawns(
    tmp_path: Path, spawned: dict[str, Any]
) -> None:
    class BrokenStore(StateRootSessionStore):
        async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
            raise OSError("state root unreadable")

    options = ClaudeAgentOptions(
        cwd=str(tmp_path),
        cli_path=str(tmp_path / "claude"),
        resume=SESSION,
        session_store=BrokenStore(tmp_path / "state"),
    )
    transport = ExplicitEnvironmentCliTransport(
        options,
        environment={"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")},
        spawn=_spawn(spawned),
        check_version=False,
    )
    with pytest.raises(CLIConnectionError, match=f"restore session {SESSION}"):
        await transport.connect()
    assert spawned == {}, "nothing was spawned"


def test_the_cli_config_dir_follows_the_child_environment(tmp_path: Path) -> None:
    assert cli_config_dir({"CLAUDE_CONFIG_DIR": str(tmp_path), "HOME": "/home/mc"}) == tmp_path
    assert cli_config_dir({"HOME": str(tmp_path)}) == tmp_path / ".claude"
    assert cli_config_dir({}) == Path.home() / ".claude"


# --- the host gate (injected platform facts) ------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "release", "loop", "wsl"),
    [
        ("Linux", "6.6.87.2-microsoft-standard-WSL2", "SelectorEventLoop", True),
        ("Linux", "6.8.0-45-generic", "_UnixSelectorEventLoop", False),
        ("Darwin", "24.1.0", "none", False),
    ],
)
def test_linux_wsl_and_macos_hosts_are_supported(
    system: str, release: str, loop: str, wsl: bool
) -> None:
    gate = host_gate(system=system, release=release, event_loop=loop)
    assert gate.supported and gate.code is None and gate.wsl is wsl
    assert gate.require() is gate


@pytest.mark.parametrize("loop", ["SelectorEventLoop", "ProactorEventLoop", "none"])
def test_a_windows_host_is_refused_whatever_the_loop(loop: str) -> None:
    gate = host_gate(system="Windows", release="11", event_loop=loop)
    assert not gate.supported and gate.code == LANE_UNSUPPORTED_OS
    assert "SelectorEventLoop" in gate.reason and "WSL 2 or Linux" in gate.remedy
    with pytest.raises(HostUnsupported) as refused:
        gate.require()
    assert refused.value.code == LANE_UNSUPPORTED_OS
    assert str(refused.value).startswith(LANE_UNSUPPORTED_OS)
    if loop == "ProactorEventLoop":
        assert "UNVERIFIED" in gate.reason


def test_an_unknown_system_is_refused() -> None:
    gate = host_gate(system="FreeBSD", release="14.1", event_loop="none")
    assert not gate.supported and "not a qualified lane host" in gate.reason


def test_the_factory_never_builds_a_client_on_an_unsupported_host(
    tmp_path: Path, spawned: dict[str, Any]
) -> None:
    factory = SdkClientFactory(
        spawn=_spawn(spawned),
        check_version=False,
        gate=lambda: host_gate(system="Windows", release="11", event_loop="SelectorEventLoop"),
    )
    with pytest.raises(HostUnsupported):
        factory.create(ClaudeAgentOptions(cwd=str(tmp_path)), environment={"PATH": "/usr/bin"})
    assert spawned == {}, "nothing was spawned"

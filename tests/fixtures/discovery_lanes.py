"""MO-34 fixtures: one Discovery Proof scenario per lane that discovers (SPEC-02 section 6).

Each scenario is what that lane's prepare returns (its sealed binding, the `PreparedSession` with
its discovery expectation) and the report its mechanism produces, built from the strongest
evidence available without a model turn or a paid call:

- `claude_agent_sdk` and `codex`: the RECORDED local discovery fixtures (`system/init` of
  Claude Code 2.1.296; `skills/list`, `hooks/list`, `config/read` of codex-cli 0.162.1);
- `cursor_local`: the SDK read-back report over a workspace holding the placed files;
- `cursor_cloud`: the `materialization.observed` signal data (MO-41's contract) read from the
  committed files;
- `claude_managed` and `codex_agents`: the API read-back against the stateful fake APIs (HL-07
  and HL-11 shapes) after a real prepare sync of the shipped hosted packs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from tests.fixtures.lane_turns import cursor_binding
from tests.fixtures.managed_agents import FakeManagedAgentsApi
from tests.fixtures.projections.discovery import claude_cli, codex_cli
from tests.unit.claude.fixtures import claude_binding
from tests.unit.codex.support import codex_binding
from tests.unit.harness.test_hosted_agent_api_profiles import AGENTS, MANAGED, _hosted_binding
from tests.unit.openai_agents.support import SHIPPED_PACK, FakeAgentsApi

from mission_control.adapters.anthropic_managed import discovery as managed_discovery
from mission_control.adapters.anthropic_managed.pack import load_pack as load_managed_pack
from mission_control.adapters.anthropic_managed.pack import render_pack
from mission_control.adapters.anthropic_managed.prepare import ClaudeManagedPrepare
from mission_control.adapters.claude.discovery import init_report
from mission_control.adapters.codex.discovery import app_server_report
from mission_control.adapters.cursor.bridge import AgentReadback
from mission_control.adapters.cursor.discovery import setting_readback_report
from mission_control.adapters.openai_agents import discovery as agents_discovery
from mission_control.adapters.openai_agents.pack import load_pack as load_agents_pack
from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.agentic_components.layering import LayeringReceipt
from mission_control.application.environments.discovery import (
    discovery_expectation,
    materialization_signal_report,
)
from mission_control.application.secrets.broker import SecretBroker
from mission_control.application.signals.contracts import Signal
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.discovery import (
    DiscoveryExpectation,
    DiscoveryItem,
    DiscoveryReport,
)
from mission_control.domain.execution.lanes import CursorExecutionBinding, PreparedSession

DIGEST: Final = "sha256:" + "d" * 64
HEAD: Final = "e" * 40
OVERLAY: Final = ".cursor/rules/mc-mission.mdc"
HOOKS: Final = ".cursor/hooks.json"
MANAGED_PACK: Final = (
    Path(__file__).resolve().parents[2] / "deployments/hosted-packs/ai-engineer/claude_managed"
)
DISCOVERING_LANES: Final = (
    "claude_agent_sdk",
    "codex",
    "cursor_local",
    "cursor_cloud",
    "claude_managed",
    "codex_agents",
)


@dataclass(frozen=True)
class Attempt:
    """A `PreparingAttempt` (what the gate knows of one harness execution generation)."""

    request_scope: str
    lane_profile: str
    run_key: str = "run-discovery"
    attempt_no: int = 1
    harness_execution_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class Scenario:
    binding: ProviderExecutionBinding | CursorExecutionBinding
    prepared: PreparedSession
    report: DiscoveryReport


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _prepared(
    lane: str, expectation: DiscoveryExpectation | None, *, workspace_ref: str, receipt: str
) -> PreparedSession:
    return PreparedSession(
        lane_profile=lane,
        harness_execution_id=str(uuid4()),
        generation=1,
        workspace_ref=workspace_ref,
        projection_digests={"projection_digest": DIGEST},
        materialization_ref=receipt,
        discovery=expectation,
    )


def _local(lane: str, expectation: DiscoveryExpectation | None) -> PreparedSession:
    return _prepared(lane, expectation, workspace_ref="workspace_lease:lease-1", receipt=DIGEST)


def _recording(module: object) -> dict[str, object]:
    path = module.RECORDING  # type: ignore[attr-defined]
    document: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return document


def claude_scenario() -> Scenario:
    recording = _recording(claude_cli)
    layering = LayeringReceipt.model_validate(recording["layering"])
    discovered = recording["discovered"]
    assert isinstance(discovered, dict)
    init = {key: discovered[key] for key in ("skills", "agents", "mcp_servers")}
    return Scenario(
        claude_binding(materialization_digest=DIGEST),
        _local("claude_agent_sdk", discovery_expectation("claude_agent_sdk", layering, {})),
        init_report(init, source="system/init:recording"),
    )


def codex_scenario() -> Scenario:
    recording = _recording(codex_cli)
    layering = LayeringReceipt.model_validate(recording["layering"])
    placed = recording["placed"]
    answers = recording["answers"]
    assert isinstance(placed, dict) and isinstance(answers, dict)
    return Scenario(
        codex_binding(),
        _local("codex", discovery_expectation("codex", layering, placed)),
        app_server_report(
            answers["skills_list"],
            answers["hooks_list"],
            answers["config_read"],
            source="app_server:recording",
        ),
    )


def cursor_local_scenario(workspace: Path) -> Scenario:
    overlay = b"---\nalwaysApply: true\n---\nMission overlay.\n"
    hooks = b'{"version": 1, "hooks": {}}\n'
    (workspace / ".cursor/rules").mkdir(parents=True, exist_ok=True)
    (workspace / OVERLAY).write_bytes(overlay)
    (workspace / HOOKS).write_bytes(hooks)
    (workspace / ".cursor/skills/agent-browser").mkdir(parents=True, exist_ok=True)
    (workspace / ".cursor/skills/agent-browser/SKILL.md").write_text("---\nname: agent-browser\n")
    expectation = DiscoveryExpectation(
        mechanism="setting_readback",
        items=(DiscoveryItem(kind="skill", name="agent-browser"),),
        digests={OVERLAY: _digest(overlay), HOOKS: _digest(hooks)},
    )
    return Scenario(
        cursor_binding("cursor_local"),
        _local("cursor_local", expectation),
        setting_readback_report(AgentReadback("agent-1", "local", str(workspace)), workspace),
    )


def cursor_cloud_scenario() -> Scenario:
    committed = {OVERLAY: b"mission overlay\n", HOOKS: b'{"version": 1}\n'}
    expectation = DiscoveryExpectation(
        mechanism="materialization_signal",
        items=(DiscoveryItem(kind="skill", name="agent-browser"),),
        digests={path: _digest(content) for path, content in committed.items()},
    )
    signal = Signal(
        signal_id="spool-2",
        type="materialization.observed",
        seq=2,
        data={
            "files": {path: _digest(content) for path, content in committed.items()},
            "skills": ["agent-browser", "repo-notes"],
        },
    )
    report = materialization_signal_report("cursor_cloud", signal)
    assert report is not None
    return Scenario(
        cursor_binding("cursor_cloud"),
        _prepared(
            "cursor_cloud",
            expectation,
            workspace_ref=f"branch:mc/run-discovery@{HEAD}",
            receipt=HEAD,
        ),
        report,
    )


def _hosted(lane: str, expectation: DiscoveryExpectation, agent: str) -> PreparedSession:
    return _prepared(
        lane, expectation, workspace_ref="provider_environment:env_1", receipt=f"agent:{agent}@1"
    )


async def claude_managed_scenario(scratch: Path) -> Scenario:
    pack_dir = scratch / "pack"
    shutil.copytree(MANAGED_PACK, pack_dir)
    repo = scratch / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# Repo rules\n")
    rendered = render_pack(
        load_managed_pack(pack_dir),
        installation_id="local",
        repo_root=repo,
        ingress_host="ingress.test",
    )
    api = FakeManagedAgentsApi()
    broker = SecretBroker(
        environment=WorkerEnvironmentSource({"FIRECRAWL_API_KEY": "fc-test-value-0123456789"})
    )
    synced = await ClaudeManagedPrepare(api.client(), broker, installation_id="local").sync(
        rendered
    )
    return Scenario(
        ProviderExecutionBinding.sealed(**_hosted_binding("claude_managed", MANAGED)),
        _hosted(
            "claude_managed",
            managed_discovery.discovery_expectation(rendered),
            synced.agent.agent_id,
        ),
        await managed_discovery.read_back(api.client(), synced),
    )


async def codex_agents_scenario() -> Scenario:
    api, pack = FakeAgentsApi(), load_agents_pack(SHIPPED_PACK)
    worker = WorkerEnvironmentSource(
        {"MC_AI_ENGINEER_GITHUB_READONLY_TOKEN": "github-readonly-test-value-7f3a"}
    )
    synced = await CodexAgentsPreparer(api.client(), worker).sync(pack)
    return Scenario(
        ProviderExecutionBinding.sealed(**_hosted_binding("codex_agents", AGENTS)),
        _hosted("codex_agents", agents_discovery.discovery_expectation(pack), synced.agent.id),
        await agents_discovery.read_back(api.client(), synced),
    )


async def scenario(lane: str, scratch: Path) -> Scenario:
    """The scenario of `lane` (one of `DISCOVERING_LANES`); `scratch` is a private directory."""

    builders = {
        "claude_agent_sdk": claude_scenario,
        "codex": codex_scenario,
        "cursor_cloud": cursor_cloud_scenario,
    }
    if lane in builders:
        return builders[lane]()
    if lane == "cursor_local":
        workspace = scratch / "lease"
        workspace.mkdir(parents=True, exist_ok=True)
        return cursor_local_scenario(workspace)
    if lane == "claude_managed":
        return await claude_managed_scenario(scratch)
    if lane == "codex_agents":
        return await codex_agents_scenario()
    raise ValueError(f"{lane} has no discovery mechanism")


__all__ = ["DISCOVERING_LANES", "Attempt", "Scenario", "scenario"]

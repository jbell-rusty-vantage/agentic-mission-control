"""MO-02 acceptance (SPEC-02 §4 and §9): the three local lanes launch over a repository that
owns its own ``AGENTS.md``, ``.claude/skills`` skill and ``.cursor/hooks.json``.

Each lane prepares its workspace (the projection layered over the repository), starts its
native session (the mission overlay through the lane's additive channel) and ends it. The
repository's instruction files and skill are never touched, the config files it shares with
Mission Control are merged (repository entries kept, Mission Control's marked), discovery
reports the repository's and the mission's items, and the repository files are byte-identical
after the run. Conflicts follow the binding's ``materialization`` policy. FIXTURE transports:
the Cursor bridge replays, the Claude client and the Codex app-server are scripted; no
provider runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import pytest

from mission_control.adapters.codex.hooks_callback import CodexHookMapper
from mission_control.adapters.cursor.hooks_callback import CursorHookMapper
from mission_control.adapters.cursor.workspace import git
from mission_control.application.agentic_components.layering import (
    LAYERING_RECORD_PATH,
    MATERIALIZATION_CONFLICT,
    LayeringReceipt,
)
from mission_control.application.agentic_components.materialization import (
    ProjectionMaterialization,
    projection_digest,
)
from mission_control.application.agentic_components.placement import (
    LaneProjectionError,
    operating_contract,
)
from mission_control.application.execution.harness.hook_callbacks import (
    HookCallbackService,
    InMemoryHookIntentLedger,
    InMemoryHookTokenStore,
)
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.application.execution.stop_fence import (
    InMemoryStopFenceRepository,
    KernelHookFenceGate,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.layering import (
    ConflictPolicy,
    MaterializationPolicy,
)
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import (
    CleanupReceipt,
    CursorExecutionBinding,
    EndSessionRequest,
    PreparedSession,
    PrepareRequest,
    SessionHandle,
    StartRequest,
)
from tests.fixtures.cursor_local import LocalStack, local_stack
from tests.fixtures.lane_turns import lane_stack
from tests.fixtures.layering_repo import REPO_FILES, repository_bytes, write_repository_files
from tests.fixtures.projections.rows import hook_row, skill_row, tavily_row, verifier_row
from tests.unit.claude.fixtures import (
    ClaudeStack,
    base_operation,
    claude_binding,
    claude_operation,
    claude_stack,
    materialization_digest_for,
)
from tests.unit.codex.fixture_app_server import FixtureLauncher, load_script
from tests.unit.codex.support import (
    CodexStack,
    StaticProjectionSource,
    build_harness,
    codex_binding,
    codex_operation,
)

MISSION_WINS = MaterializationPolicy(conflicts=ConflictPolicy.MISSION_WINS)
REFUSE = MaterializationPolicy(conflicts=ConflictPolicy.REFUSE)
CONTRACT_LINE = "Mission context: read .mission/context.md"
REPO_SKILL = b"---\nname: agent-browser\ndescription: The repository's own browser skill.\n---\n"


class _Harness(Protocol):
    def stage(self, harness_execution_id: str, operation: OperationExecutionRequest) -> None: ...

    async def prepare(self, request: PrepareRequest) -> PreparedSession: ...

    async def start(self, request: StartRequest) -> SessionHandle: ...

    async def end_session(self, request: EndSessionRequest) -> CleanupReceipt: ...


@dataclass
class Lane:
    """One local lane over the fixture repository: its harness and how to look inside."""

    profile: str
    harness: _Harness
    operation: OperationExecutionRequest
    binding_digest: str
    root: Path
    stack: Any

    @property
    def heid(self) -> str:
        identity = LaneExecutionIdentity.of(self.operation, self.profile, 1)
        return str(identity.harness_execution_id)

    def fields(self, key: str) -> dict[str, Any]:
        identity = LaneExecutionIdentity.of(self.operation, self.profile, 1)
        return {
            "scope": harness_scope(identity.request_scope),
            "lane_profile": self.profile,
            "harness_execution_id": self.heid,
            "binding_digest": self.binding_digest,
            "idempotency_key": f"{self.heid}:1:{key}",
            "generation": 1,
        }

    async def prepare(self) -> PreparedSession:
        self.harness.stage(self.heid, self.operation)
        return await self.harness.prepare(
            PrepareRequest(
                **self.fields("prepare"),
                run_id=self.operation.identity.run_id,
                operation_id=self.operation.identity.operation_id,
                attempt_no=1,
            )
        )

    async def start(self, prepared: PreparedSession) -> SessionHandle:
        return await self.harness.start(StartRequest(**self.fields("start"), prepared=prepared))

    async def end(self, session: SessionHandle) -> CleanupReceipt:
        return await self.harness.end_session(
            EndSessionRequest(**self.fields("end"), session=session, reason="completed")
        )

    def materialization(self) -> ProjectionMaterialization:
        if self.profile == "claude_agent_sdk":
            execution = self.stack.harness.execution_view(self.heid)
            materialization: ProjectionMaterialization = execution.materialization
        else:
            materialization = self.stack.harness._sessions[self.heid].materialization
        assert materialization is not None
        return materialization

    def receipt(self) -> LayeringReceipt:
        receipt = self.materialization().layering
        assert receipt is not None
        return receipt


def _commit(repo: Path, message: str) -> None:
    git("add", "--all", cwd=repo)
    identity = ("-c", "user.name=Fixture", "-c", "user.email=fixture@localhost")
    git(*identity, "commit", "--quiet", "-m", message, cwd=repo)


def cursor_lane(
    tmp_path: Path,
    policy: MaterializationPolicy | None = None,
    extra: dict[str, bytes] | None = None,
) -> Lane:
    changes = {"materialization": policy} if policy is not None else None
    stack: LocalStack = local_stack(tmp_path, binding_changes=changes)
    repo = tmp_path / "repo"
    write_repository_files(repo, {**REPO_FILES, **(extra or {})})
    _commit(repo, "the repository's own cognition")
    binding = CursorExecutionBinding.carried_by(stack.operation)
    assert binding is not None
    return Lane("cursor_local", stack.harness, stack.operation, binding.binding_digest, repo, stack)


def claude_lane(
    tmp_path: Path,
    policy: MaterializationPolicy | None = None,
    extra: dict[str, bytes] | None = None,
) -> Lane:
    binding = claude_binding(
        materialization_digest=materialization_digest_for(base_operation()),
        materialization=policy,
    )
    stack: ClaudeStack = claude_stack(tmp_path, operation=claude_operation(binding=binding))
    lane = Lane(
        "claude_agent_sdk", stack.harness, stack.operation, binding.binding_digest, tmp_path, stack
    )
    # The FIXTURE allocator leases `<root>/<execution>-g<generation>`: seed it as a checkout.
    lane.root = tmp_path / "leases" / f"{lane.heid}-g1"
    write_repository_files(lane.root, {**REPO_FILES, **(extra or {})})
    return lane


def codex_lane(
    tmp_path: Path,
    policy: MaterializationPolicy | None = None,
    extra: dict[str, bytes] | None = None,
) -> Lane:
    rows = (skill_row(), tavily_row(), hook_row(), verifier_row())
    projection = HOST_PROJECTORS.render(rows, "codex", operating_contract(codex_operation()), None)
    operation = codex_operation(
        codex_binding(materialization_digest=projection_digest(projection), materialization=policy)
    )
    launcher = FixtureLauncher(scripts=[load_script("turn_full")])
    # The projection runs the Kernel Hooks, so the worker composes its hook callback service.
    hooks = HookCallbackService(
        tokens=InMemoryHookTokenStore(),
        intents=InMemoryHookIntentLedger(),
        mapper=CursorHookMapper(),
        lane_mappers={"codex": CodexHookMapper()},
        fences=KernelHookFenceGate(InMemoryStopFenceRepository()),
    )
    harness, leaser, artifacts, auth = build_harness(
        tmp_path, launcher, projections=StaticProjectionSource(projection), hooks=hooks
    )
    lanes = lane_stack(harness, operation=operation)
    stack = CodexStack(harness, launcher, leaser, artifacts, auth, None, operation, lanes)
    lane = Lane(
        "codex", harness, operation, operation.effective_configuration_digest, tmp_path, stack
    )
    # The FIXTURE leaser leases `<root>/lease-<execution>-g<generation>`: seed it.
    lane.root = tmp_path / "leases" / f"lease-{UUID(lane.heid).hex[:12]}-g1"
    write_repository_files(lane.root, {**REPO_FILES, **(extra or {})})
    return lane


LANES = {"cursor_local": cursor_lane, "claude_agent_sdk": claude_lane, "codex": codex_lane}


async def _workspace(lane: Lane) -> tuple[Path, PreparedSession]:
    prepared = await lane.prepare()
    if lane.profile == "cursor_local":
        (lease,) = lane.stack.leases._leases.values()
        return Path(lease.path), prepared
    return lane.root, prepared


def _json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _assert_overlay(lane: Lane, root: Path) -> None:
    """The mission overlay reached the provider through the lane's additive channel."""

    if lane.profile == "cursor_local":
        rule = (root / ".cursor/rules/mc-mission.mdc").read_text(encoding="utf-8")
        assert "alwaysApply: true" in rule and CONTRACT_LINE in rule
        assert lane.stack.launcher.created[0].setting_sources == ("project",)
    elif lane.profile == "claude_agent_sdk":
        options = lane.stack.factory.last.options
        assert options.system_prompt["type"] == "preset"
        assert options.system_prompt["preset"] == "claude_code"
        assert CONTRACT_LINE in options.system_prompt["append"]
        assert options.setting_sources == ["project"]
    else:
        records = lane.stack.launcher.server.records
        (params,) = [params for method, params in records if method == "thread/start"]
        assert CONTRACT_LINE in params["developerInstructions"]


@pytest.mark.parametrize("profile", sorted(LANES))
async def test_a_repository_with_its_own_cognition_launches_and_stays_byte_identical(
    tmp_path: Path, profile: str
) -> None:
    lane = LANES[profile](tmp_path)
    root, prepared = await _workspace(lane)

    # The repository's own instructions and skill load unchanged; nothing replaces them.
    for path in ("AGENTS.md", ".claude/skills/repo-notes/SKILL.md"):
        assert (root / path).read_bytes() == REPO_FILES[path], path
    assert not (root / "CLAUDE.md").exists()
    cursor_hooks = root / ".cursor/hooks.json"
    if profile == "cursor_local":
        shell = _json(cursor_hooks)["hooks"]["beforeShellExecution"]
        assert shell[-1] == {"command": "./scripts/audit.sh"}, "the repository hook is kept"
        assert any(".mission/hooks/kernel.py" in entry["command"] for entry in shell[:-1])
    else:
        assert cursor_hooks.read_bytes() == REPO_FILES[".cursor/hooks.json"]
    if profile == "claude_agent_sdk":
        settings = _json(root / ".claude/settings.json")
        assert settings["permissions"] == {"allow": ["Bash(make test)"]}
        assert settings["hooks"]["PreToolUse"][-1]["hooks"][0]["command"] == "./scripts/audit.sh"
        assert set(_json(root / ".mcp.json")["mcpServers"]) == {"repo-docs", "mc-tavily"}
    if profile == "codex":
        config = (root / ".codex/config.toml").read_text(encoding="utf-8")
        assert config.startswith(REPO_FILES[".codex/config.toml"].decode())
        assert '[mcp_servers."mc-tavily"]' in config

    # The receipt lists the merged keys and discovery reports both origins.
    receipt = lane.receipt()
    assert receipt.merged and not receipt.conflicts
    assert all(item.mission_keys for item in receipt.merged)
    repo_items = {(item.kind, item.name) for item in receipt.discovered("repo")}
    mission_items = {(item.kind, item.name) for item in receipt.discovered("mission")}
    assert ("instructions", "AGENTS.md") in repo_items
    assert {("instructions", "mission overlay"), ("skill", "agent-browser")} <= mission_items
    # The repository's own config entries beside Mission Control's hooks in the same files.
    assert {kind for kind, _name in repo_items} & {"hook", "mcp_server"}
    assert any(kind == "hook" for kind, _name in mission_items)
    if profile == "claude_agent_sdk":
        assert ("skill", "repo-notes") in repo_items
    assert "materialization_digest" in prepared.projection_digests

    session = await lane.start(prepared)
    _assert_overlay(lane, root)
    await lane.end(session)

    # After the run every repository file holds the repository's bytes again.
    assert repository_bytes(root) == dict(REPO_FILES)
    assert not (root / LAYERING_RECORD_PATH).exists()
    if profile == "cursor_local":
        repo = tmp_path / "repo"
        assert git("status", "--porcelain", cwd=repo) == ""
        assert repository_bytes(repo) == dict(REPO_FILES)


async def test_cursor_local_refuses_a_conflict_the_policy_refuses(tmp_path: Path) -> None:
    extra = {".cursor/skills/agent-browser/SKILL.md": REPO_SKILL}
    lane = cursor_lane(tmp_path, REFUSE, extra)
    with pytest.raises(LaneProjectionError) as refused:
        await lane.prepare()
    assert refused.value.code == MATERIALIZATION_CONFLICT
    assert ".cursor/skills/agent-browser/" in str(refused.value)
    assert lane.stack.launcher.launches == [], "nothing launches after a refused conflict"
    (lease,) = lane.stack.leases._leases.values()
    root = Path(lease.path)
    assert (root / ".cursor/skills/agent-browser/SKILL.md").read_bytes() == REPO_SKILL
    assert not (root / ".cursor/rules/mc-mission.mdc").exists(), "nothing is placed"


async def test_claude_mission_wins_places_the_mission_skill_and_restores_the_repository(
    tmp_path: Path,
) -> None:
    skill = ".claude/skills/agent-browser/SKILL.md"
    lane = claude_lane(tmp_path, MISSION_WINS, {skill: REPO_SKILL})
    root, prepared = await _workspace(lane)
    assert (root / skill).read_bytes().startswith(b"---\nname: agent-browser\n")
    (conflict,) = lane.receipt().conflicts
    assert conflict.resolution is ConflictPolicy.MISSION_WINS
    session = await lane.start(prepared)
    await lane.end(session)
    assert (root / skill).read_bytes() == REPO_SKILL
    assert repository_bytes(root) == dict(REPO_FILES)


async def test_codex_keeps_a_same_named_repository_skill_by_default(tmp_path: Path) -> None:
    skill = ".agents/skills/agent-browser/SKILL.md"
    lane = codex_lane(tmp_path, extra={skill: REPO_SKILL})
    root, prepared = await _workspace(lane)
    assert (root / skill).read_bytes() == REPO_SKILL
    receipt = lane.receipt()
    (conflict,) = receipt.conflicts
    assert conflict.resolution is ConflictPolicy.REPO_WINS and skill in receipt.skipped
    assert ("skill", "agent-browser", "repo") in {
        (item.kind, item.name, item.origin) for item in receipt.discovery
    }
    session = await lane.start(prepared)
    await lane.end(session)
    assert (root / skill).read_bytes() == REPO_SKILL


async def test_codex_trusts_the_hooks_file_as_layered_over_the_repository(tmp_path: Path) -> None:
    """MO-02 x MO-03: layering merges the Kernel Hooks into the repository's own
    `.codex/hooks.json`, shifting the handler keys Codex derives; the hash trust covers the
    placed file, so `hooks/list` reports every handler trusted and the thread starts."""

    audit = {"type": "command", "command": "./scripts/audit.sh"}
    repo_hooks = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [audit]}]}}
    extra = {".codex/hooks.json": json.dumps(repo_hooks).encode("utf-8")}
    lane = codex_lane(tmp_path, extra=extra)
    root, prepared = await _workspace(lane)
    placed = _json(root / ".codex/hooks.json")["hooks"]["PreToolUse"]
    assert placed[-1] == repo_hooks["hooks"]["PreToolUse"][0], "the repository hook is kept"
    assert any(".mission/hooks/kernel.py" in str(group) for group in placed[:-1])
    session = await lane.start(prepared)
    records = lane.stack.launcher.server.records
    assert [method for method, _params in records].count("hooks/list") == 1
    await lane.end(session)
    assert (root / ".codex/hooks.json").read_bytes() == extra[".codex/hooks.json"]

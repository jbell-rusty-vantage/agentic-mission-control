"""MO-05 FIXTURES: each local lane's harness over a real `WorkspaceAllocator` (real git
repositories, in-memory lease ledger and artifact custody), driven generation by generation
through the harness protocol's `prepare`, `end_session` and `cleanup_workspace`. No provider
session is started.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.fixtures.cursor_local import local_stack
from tests.unit.claude.fixtures import (
    FIXTURE_ENVIRON,
    FixtureClientFactory,
    FixtureScript,
    base_operation,
    claude_binding,
    claude_operation,
    fixture_admission,
    materialization_digest_for,
    projection_rows,
)
from tests.unit.codex.fixture_app_server import FixtureLauncher
from tests.unit.codex.support import (
    MemoryArtifacts,
    StaticAuth,
    StaticProjectionSource,
    admission,
    codex_binding,
    codex_operation,
    fixture_settings,
)
from tests.unit.workspaces.workspace_fixtures import commit, git, policy

from mission_control.adapters.claude.harness import (
    ClaudeAgentSdkHarness,
    ClaudeLaneSettings,
    StaticAuthAdmitter,
)
from mission_control.adapters.claude.workspace import AllocatedWorkspace
from mission_control.adapters.codex.harness import CodexLocalHarness
from mission_control.adapters.cursor.workspace import GitWorktreeLeaser
from mission_control.adapters.workspaces.git_workspaces import GitWorkspaceBackend
from mission_control.application.agentic_components.placement import (
    RenderedProjectionSource,
    static_rows,
)
from mission_control.application.execution.child_environment import provider_child_environment
from mission_control.application.execution.harness.hook_callbacks import InMemoryHookIntentLedger
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.application.execution.harness.leases import (
    InMemoryWorkspaceLeaseStore,
    WorkspaceLease,
    lease_identity,
)
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
from mission_control.application.workspaces.service import WorkspaceAllocator
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.execution.bindings import WorkspacePolicyPin
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import (
    CursorExecutionBinding,
    EndSessionRequest,
    PrepareRequest,
    SessionHandle,
)

WITHIN_RUN = policy(reuse="within_run")
SHARED = policy(mode="shared_checkout", reuse="within_run")


def _repository(root: Path) -> Path:
    """The target repository: tracked source, no instruction files of its own."""

    root.mkdir(parents=True)
    git("init", "--quiet", "--initial-branch=main", cwd=root)
    (root / "README.md").write_text("# target\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("VALUE = 0\n", encoding="utf-8")
    git("add", "--all", cwd=root)
    commit(root, "base")
    return root


@dataclass
class LaneDriver:
    """One local lane's harness over a real allocator, driven generation by generation."""

    profile: str
    harness: Any
    operation: OperationExecutionRequest
    ledger: InMemoryWorkspaceLeaseStore
    artifacts: Any

    def another_unit(self, operation_id: str) -> LaneDriver:
        """Another unit of the same run on the same harness, ledger and custody."""

        identity = self.operation.identity.model_copy(update={"operation_id": operation_id})
        operation = self.operation.model_copy(update={"identity": identity})
        return LaneDriver(self.profile, self.harness, operation, self.ledger, self.artifacts)

    def identity(self, generation: int) -> LaneExecutionIdentity:
        return LaneExecutionIdentity.of(self.operation, self.profile, generation)

    def _fields(self, generation: int, kind: str) -> dict[str, Any]:
        identity = self.identity(generation)
        binding = CursorExecutionBinding.carried_by(self.operation)
        digest = (
            binding.binding_digest
            if binding is not None
            else self.operation.effective_configuration_digest
        )
        return {
            "scope": harness_scope(identity.request_scope),
            "lane_profile": self.profile,
            "harness_execution_id": str(identity.harness_execution_id),
            "binding_digest": digest,
            "idempotency_key": f"{identity.harness_execution_id}:{generation}:{kind}",
            "generation": generation,
        }

    async def prepare(self, generation: int) -> Path:
        fields = self._fields(generation, "prepare")
        self.harness.stage(fields["harness_execution_id"], self.operation)
        await self.harness.prepare(
            PrepareRequest(
                **fields,
                run_id=self.operation.identity.run_id,
                operation_id=self.operation.identity.operation_id,
                attempt_no=generation,
            )
        )
        return Path(self.harness.lease_path(fields["harness_execution_id"]))

    async def end(self, generation: int) -> bool:
        fields = self._fields(generation, "end")
        receipt = await self.harness.end_session(
            EndSessionRequest(
                **fields,
                session=SessionHandle(
                    lane_profile=self.profile,
                    harness_execution_id=fields["harness_execution_id"],
                    generation=generation,
                ),
                reason="finished",
            )
        )
        return receipt.released

    async def lease(self, generation: int) -> WorkspaceLease | None:
        identity = self.identity(generation)
        lease_id, _key = lease_identity(self.profile, identity.harness_execution_id, generation)
        return await self.ledger.get(identity.request_scope, lease_id)

    async def cleanup(self, generation: int) -> str:
        identity = self.identity(generation)
        return await self.harness.cleanup_workspace(
            request_scope=identity.request_scope,
            harness_execution_id=str(identity.harness_execution_id),
            generation=generation,
        )


def claude_lane(tmp_path: Path, workspace_policy: WorkspacePolicyPin) -> LaneDriver:
    repository = _repository(tmp_path / "repo")
    binding = claude_binding(
        materialization_digest=materialization_digest_for(base_operation()),
        workspace_policy=workspace_policy.model_dump(),
        repo_url=str(repository),
        repo_ref="main",
    )
    operation = claude_operation(binding=binding)
    ledger = InMemoryWorkspaceLeaseStore()
    artifacts = MemoryArtifacts()
    root = tmp_path / "leases"
    allocator = WorkspaceAllocator(
        ledger=ledger,
        backend=GitWorkspaceBackend(root),
        root=root,
        allocator_ref="worker:fixture",
    )
    harness = ClaudeAgentSdkHarness(
        clients=FixtureClientFactory(FixtureScript.load("full_run")),
        workspaces=AllocatedWorkspace(allocator, ledger, artifacts),
        projections=RenderedProjectionSource(
            static_rows(projection_rows()), projectors=HOST_PROJECTORS
        ),
        auth=StaticAuthAdmitter(fixture_admission()),
        child_environment=provider_child_environment,
        environ=dict(FIXTURE_ENVIRON),
        fences=InMemoryStopFenceRepository(),
        intents=InMemoryHookIntentLedger(),
        settings=ClaudeLaneSettings(require_executables=False),
    )
    return LaneDriver("claude_agent_sdk", harness, operation, ledger, artifacts)


def codex_lane(tmp_path: Path, workspace_policy: WorkspacePolicyPin) -> LaneDriver:
    repository = _repository(tmp_path / "repo")
    operation = codex_operation(
        codex_binding(
            workspace_policy=workspace_policy.model_dump(),
            repo_url=str(repository),
            repo_ref="main",
        )
    )
    ledger = InMemoryWorkspaceLeaseStore()
    artifacts = MemoryArtifacts()
    root = tmp_path / "leases"
    harness = CodexLocalHarness(
        launcher=FixtureLauncher(),
        leaser=GitWorktreeLeaser(ledger, lease_root=root, artifacts=artifacts),
        projections=StaticProjectionSource(),
        artifacts=artifacts,
        auth=StaticAuth(admission("api_key")),
        settings=fixture_settings(tmp_path, lease_root=root),
        child_environment=provider_child_environment,
    )
    return LaneDriver("codex", harness, operation, ledger, artifacts)


def cursor_lane(tmp_path: Path, workspace_policy: WorkspacePolicyPin) -> LaneDriver:
    stack = local_stack(tmp_path, binding_changes={"policy": workspace_policy.model_dump()})
    return LaneDriver("cursor_local", stack.harness, stack.operation, stack.leases, stack.artifacts)


LANES: dict[str, Callable[[Path, WorkspacePolicyPin], LaneDriver]] = {
    "claude_agent_sdk": claude_lane,
    "codex": codex_lane,
    "cursor_local": cursor_lane,
}


__all__ = [
    "LANES",
    "SHARED",
    "WITHIN_RUN",
    "LaneDriver",
    "claude_lane",
    "codex_lane",
    "cursor_lane",
]

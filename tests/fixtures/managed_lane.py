"""HL-08 fixtures: the real `claude_managed` harness over the fake Managed Agents API.

`managed_stack` renders the checked-in AI Engineer pack (a scratch target repository supplies
its AGENTS.md), syncs it through the real `ClaudeManagedPrepare` into `FakeManagedAgentsApi`
and composes `ClaudeManagedHarness` with in-memory artifacts and a recording retention
scheduler. `managed_operation` is a bound operation whose sealed `claude_managed` binding pins
that pack's materialization digest. No Anthropic API is called.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from tests.fixtures.cursor_local import MemoryArtifacts
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.lane_turns import DIGEST, SCOPE
from tests.fixtures.managed_agents import FakeManagedAgentsApi
from tests.fixtures.session_retention import RecordingDeletionScheduler

from mission_control.adapters.anthropic_managed.describe import CLAUDE_MANAGED_DESCRIBE
from mission_control.adapters.anthropic_managed.harness import ClaudeManagedHarness
from mission_control.adapters.anthropic_managed.pack import RenderedPack, load_pack, render_pack
from mission_control.adapters.anthropic_managed.prepare import ClaudeManagedPrepare
from mission_control.adapters.anthropic_managed.tools import ManagedTools
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.execution.harness.retention import SessionRetentionService
from mission_control.application.secrets.broker import SecretBroker
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest

PROFILE: Final = "claude_managed"
LANE_QUEUE: Final = "mc-ai-engineer-lane-hosted"
REPO_ROOT: Final = Path(__file__).resolve().parents[2]
AI_ENGINEER_PACK: Final = REPO_ROOT / "deployments/hosted-packs/ai-engineer/claude_managed"
# The pack's vault credential, as the worker environment would hold it (never a real key).
WORKER_ENVIRONMENT: Final = {"FIRECRAWL_API_KEY": "fc-test-value-0123456789"}
MAX_LIST_COST: Final = 90


def rendered_pack(root: Path, pack_dir: Path = AI_ENGINEER_PACK) -> RenderedPack:
    """The pack rendered for installation `local` against a scratch target repository."""

    repo = root / "target-repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "AGENTS.md").write_text("# Repository rules\n\nCite every source.\n", "utf-8")
    return render_pack(
        load_pack(pack_dir),
        installation_id="local",
        repo_root=repo,
        ingress_host="ingress.example.com",
    )


def managed_binding(
    materialization_digest: str, *, task_queue: str = LANE_QUEUE, **changes: Any
) -> ProviderExecutionBinding:
    fields: dict[str, Any] = {
        "lane_profile": PROFILE,
        "model": {"profile": "hosted.default", "model_id": "claude-haiku-5-5"},
        "auth": {"profile": "claude_managed.api", "billing_mode": "api"},
        "environment": {
            "kind": "provider_hosted",
            "provider": "anthropic",
            "environment_ref": "ai-engineer-knowledge",
            "expected_revision": "pack-v1",
        },
        "workspace_policy": {
            "mode": "provider_workspace",
            "reuse": "none",
            "dirty_input": "reject",
            "cleanup": "retain",
        },
        "materialization_digest": materialization_digest,
        "requirements": {"describe_digest": CLAUDE_MANAGED_DESCRIBE.digest},
        "policy_digest": DIGEST,
        "pins": {"sdk.anthropic": "1.13.0"},
        "provider_options": {"provider": PROFILE, "max_list_cost_minor_units": MAX_LIST_COST},
        "budgets": {"max_turns": 4, "max_segments": 16, "wall_clock_s": 3600},
        "task_queue": task_queue,
    }
    fields.update(changes)
    return ProviderExecutionBinding.sealed(**fields)


def managed_operation(
    binding: ProviderExecutionBinding, *, prompt: str = "Summarize the release notes."
) -> OperationExecutionRequest:
    from tests.unit.operations.test_operation_execution import operation_request

    payload = operation_request(prompt=prompt).model_dump(mode="python")
    payload.update(
        request_scope=SCOPE,
        execution_runtime="claude",
        lane_profile=PROFILE,
        **lane_fields(None),
        **lane_fields(binding),
        native_placement=None,
        budget_limits={"model.turns": 4, "tokens.total": 100_000},
    )
    return OperationExecutionRequest.model_validate(payload)


@dataclass
class ManagedStack:
    harness: ClaudeManagedHarness
    api: FakeManagedAgentsApi
    artifacts: MemoryArtifacts
    deletions: RecordingDeletionScheduler
    operation: OperationExecutionRequest
    pack: RenderedPack


def managed_harness(
    api: FakeManagedAgentsApi,
    pack: RenderedPack,
    *,
    artifacts: MemoryArtifacts | None = None,
    deletions: RecordingDeletionScheduler | None = None,
    labels: Mapping[str, str] | None = None,
    tools: ManagedTools | None = None,
) -> ClaudeManagedHarness:
    """A fresh harness process over `api` (a reattach after a lost worker builds another)."""

    return ClaudeManagedHarness(
        client=api.client(),
        preparer=ClaudeManagedPrepare(
            api.client(),
            SecretBroker(environment=WorkerEnvironmentSource(WORKER_ENVIRONMENT)),
            installation_id="local",
            labels=labels,
        ),
        pack=pack,
        artifacts=artifacts or MemoryArtifacts(),
        retention=SessionRetentionService(deletions or RecordingDeletionScheduler()),
        labels=labels,
        idle_poll_interval_s=0.01,
        tools=tools,
    )


def managed_stack(
    root: Path,
    *,
    scripts: Sequence[str] = ("full",),
    operation_changes: Mapping[str, Any] | None = None,
    binding_changes: Mapping[str, Any] | None = None,
    task_queue: str = LANE_QUEUE,
) -> ManagedStack:
    pack = rendered_pack(root)
    api = FakeManagedAgentsApi(turn_scripts=list(scripts))
    artifacts, deletions = MemoryArtifacts(), RecordingDeletionScheduler()
    changes = dict(binding_changes or {})
    digest = changes.pop("materialization_digest", pack.materialization_digest)
    binding = managed_binding(digest, task_queue=task_queue, **changes)
    operation = managed_operation(binding)
    if operation_changes:
        operation = OperationExecutionRequest.model_validate(
            {**operation.model_dump(mode="python"), **operation_changes}
        )
    harness = managed_harness(api, pack, artifacts=artifacts, deletions=deletions)
    return ManagedStack(harness, api, artifacts, deletions, operation, pack)


__all__ = [
    "AI_ENGINEER_PACK",
    "LANE_QUEUE",
    "MAX_LIST_COST",
    "PROFILE",
    "WORKER_ENVIRONMENT",
    "ManagedStack",
    "managed_binding",
    "managed_harness",
    "managed_operation",
    "managed_stack",
    "rendered_pack",
]

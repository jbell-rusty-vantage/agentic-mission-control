"""MO-11 on `cursor_cloud` (FIXTURE Cloud API, real local git remote).

The binding's launch `envVars` resolve through the Secret Broker once per process, before the
run branch is published, so Mission Control's commit is scanned against them; Cursor's launch
limits refuse before any create; a fresh worker that reattaches resolves them again, so its
redaction and commit scan know them too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.adapters.cursor.cloud import CursorCloudHarness
from mission_control.adapters.cursor.scm import GitBranchPublisher
from mission_control.adapters.cursor.secrets import CursorSecretRefused
from mission_control.adapters.cursor.workspace import git
from mission_control.application.secrets.commit_scan import SecretInCommit
from mission_control.domain.execution.lanes import ReattachRequest
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.cursor_controls import harness_fields, started_session

PROFILE = "cursor_cloud"
VALUE = "mo11-launch-value-5e2b"
ENV_VARS_CLOUD = {"env_vars_ref": "environment:MC_LAUNCH", "client_agent_id": False}


class CountingResolver:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.calls = 0

    async def __call__(self, ref: str) -> dict[str, str]:
        self.calls += 1
        return dict(self.values)


async def test_launch_env_vars_resolve_once_and_guard_the_published_commit(
    tmp_path: Path,
) -> None:
    resolver = CountingResolver({"MC_LAUNCH": VALUE})
    stack = cloud_stack(tmp_path, cloud_changes=ENV_VARS_CLOUD, env_resolver=resolver)
    await started_session(stack)
    (create,) = stack.api.creates
    assert create["envVars"] == {"MC_LAUNCH": VALUE}
    assert resolver.calls == 1, "prepare resolves; start reuses the process's values"

    # A resolved value that a projection file carries (here: text of the verifier subagent)
    # refuses the publish before anything reaches the remote or the provider.
    leaking = cloud_stack(
        tmp_path / "leaking",
        cloud_changes=ENV_VARS_CLOUD,
        env_resolver=CountingResolver({"MC_LAUNCH": "You are a skeptical validator"}),
    )
    with pytest.raises(SecretInCommit, match="verifier.md"):
        await started_session(leaking)
    assert leaking.api.creates == []
    assert git("branch", "--list", "mc/*", cwd=leaking.remote).strip() == ""


async def test_cursor_launch_limits_refuse_before_any_create(tmp_path: Path) -> None:
    stack = cloud_stack(
        tmp_path,
        cloud_changes=ENV_VARS_CLOUD,
        env_resolver=CountingResolver({"CURSOR_LAUNCH": VALUE}),
    )
    with pytest.raises(CursorSecretRefused, match="CURSOR_"):
        await started_session(stack)
    assert stack.api.creates == []


async def test_a_fresh_worker_resolves_the_runs_env_vars_again_on_reattach(
    tmp_path: Path,
) -> None:
    stack = cloud_stack(
        tmp_path, cloud_changes=ENV_VARS_CLOUD, env_resolver=CountingResolver({"MC_LAUNCH": VALUE})
    )
    heid, handle = await started_session(stack)
    assert handle.native_session_ref is not None
    resolver = CountingResolver({"MC_LAUNCH": VALUE})
    fresh = CursorCloudHarness(
        client=stack.client,
        publisher=GitBranchPublisher(tmp_path / "mirrors-2"),
        projections=stack.harness._projections,
        artifacts=stack.artifacts,
        workspaces=stack.workspaces,
        env_resolver=resolver,
    )
    fresh.stage(heid, stack.operation)
    await fresh.reattach(
        ReattachRequest(
            **harness_fields(stack.operation, heid, PROFILE),
            native_session_ref=handle.native_session_ref,
            native_turn_ref=stack.api.run_id,
        )
    )
    assert "env_vars" in fresh.rehydration_receipt(heid)
    assert resolver.calls == 1

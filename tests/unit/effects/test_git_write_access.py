"""MO-14 worktree-scoped write access on real git: a lease from the MO-05 WorkspaceAllocator,
a local bare repository as the target remote, the Mission Control-owned pre-push guard and
the scoped credential helper. No network: the https target is only ever asked for a
credential through `git credential fill`, never pushed to."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from mission_control.adapters.workspaces.git_workspaces import GitCommandError
from mission_control.adapters.workspaces.git_write import (
    CREDENTIAL_FILE,
    PUBLISH_REMOTE,
    WorktreeWriteAccess,
)
from mission_control.application.execution.harness.leases import WorkspaceLease
from tests.unit.effects.support import (
    APP_TOKEN,
    REPOSITORY,
    StaticCredentials,
    make_remote,
    remote_head,
)
from tests.unit.workspaces.workspace_fixtures import (
    Stack,
    commit,
    git,
    porcelain,
    request,
    stack,
    within,
)

SCOPED_HELPER = "credential.https://github.com.helper"


def _work(lease: WorkspaceLease, name: str = "change.txt") -> tuple[Path, str]:
    path = Path(lease.path)
    (path / name).write_bytes(b"mission work\n")
    git("add", "--all", cwd=path)
    return path, commit(path, "mission work")


def _credential_fill(path: Path) -> str:
    completed = subprocess.run(
        ["git", "credential", "fill"],
        input=b"protocol=https\nhost=github.com\npath=jbell-rusty-vantage/mission-control\n\n",
        cwd=path,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        timeout=60,
        check=True,
    )
    return completed.stdout.decode()


def _config(cwd: Path | str, *args: str) -> tuple[int, str]:
    completed = subprocess.run(["git", "config", *args], cwd=cwd, capture_output=True, check=False)
    return completed.returncode, completed.stdout.decode()


def _tree_text(root: Path) -> str:
    return "".join(p.read_text("utf-8", "replace") for p in root.rglob("*") if p.is_file())


def _exists(path: Path | str) -> bool:
    return Path(path).exists()


async def _leased(tmp_path: Path) -> tuple[Stack, Path, WorkspaceLease]:
    remote = make_remote(tmp_path / "github")
    s = stack(tmp_path, primary=remote)
    return s, remote, await s.allocator.allocate(request(remote, run_id="run-1"))


async def test_the_pre_push_guard_refuses_every_ref_outside_the_runs_mission_branches(
    tmp_path: Path,
) -> None:
    s, remote, lease = await _leased(tmp_path)
    access = WorktreeWriteAccess(s.backend, StaticCredentials())
    grant = await access.grant(lease, unit="u1", remote_url=str(remote))
    path, head = _work(lease)
    main = remote_head(remote, "main")

    for refspec in (
        "HEAD:refs/heads/main",
        "HEAD:refs/heads/feature",
        "HEAD:refs/heads/mc/run-2/u1",
        f"HEAD:refs/heads/{lease.branch}",
        "HEAD:refs/tags/v1",
    ):
        with pytest.raises(GitCommandError) as refused:
            git("push", PUBLISH_REMOTE, refspec, cwd=path)
        assert "mission control: push to" in refused.value.stderr
        assert "only refs/heads/mc/run-1/* is allowed" in refused.value.stderr

    # Nothing reached the remote: main is untouched and no other ref appeared.
    assert remote_head(remote, "main") == main
    assert git("for-each-ref", "--format=%(refname)", cwd=remote).split() == ["refs/heads/main"]

    # A plain `git push` from the agent lands on the mission branch through the guard.
    git("push", "--quiet", cwd=path)
    assert grant.mission_branch == "mc/run-1/u1"
    assert remote_head(remote, "mc/run-1/u1") == head


async def test_mission_control_publishes_the_lease_branch_and_reads_the_head_back(
    tmp_path: Path,
) -> None:
    s, remote, lease = await _leased(tmp_path)
    access = WorktreeWriteAccess(s.backend, StaticCredentials())
    grant = await access.grant(lease, unit="u1", remote_url=str(remote))
    _, head = _work(lease)

    pushed = await access.push(grant)

    assert (pushed.branch, pushed.head_sha) == ("mc/run-1/u1", head)
    assert remote_head(remote, "mc/run-1/u1") == head
    # A rewritten history is never forced over the published branch.
    path = Path(lease.path)
    git("reset", "--quiet", "--hard", "HEAD~1", cwd=path)
    _work(lease, "other.txt")
    with pytest.raises(GitCommandError):
        await access.push(grant)
    assert remote_head(remote, "mc/run-1/u1") == head


async def test_the_write_settings_live_in_the_worktree_config_only(tmp_path: Path) -> None:
    s, remote, lease = await _leased(tmp_path)
    sibling = await s.allocator.allocate(request(remote, run_id="run-2"))
    access = WorktreeWriteAccess(s.backend, StaticCredentials())
    grant = await access.grant(lease, unit="u1", remote_url=str(remote))
    path = Path(lease.path)
    clone = (path / git("rev-parse", "--git-common-dir", cwd=path).strip()).resolve()

    origin = git("config", "--show-origin", "--get", "core.hooksPath", cwd=path).split("\t")[0]
    assert origin.endswith("/config.worktree")
    assert within(grant.admin, clone) and not within(grant.admin, path)
    assert _exists(grant.admin / "mc-hooks" / "pre-push")
    # Neither the dedicated clone nor a sibling worktree of it sees any of it.
    for elsewhere in (clone, Path(sibling.path)):
        for key in ("core.hooksPath", f"remote.{PUBLISH_REMOTE}.url", "remote.pushDefault"):
            assert _config(elsewhere, "--get", key)[0] == 1, (elsewhere, key)
    assert git("rev-parse", "--is-bare-repository", cwd=clone).strip() == "true"
    assert git("rev-parse", "--is-bare-repository", cwd=path).strip() == "false"
    # Granting wrote nothing into the worktree itself.
    assert porcelain(path) == []


async def test_an_https_target_gets_a_worktree_scoped_credential_that_revoke_removes(
    tmp_path: Path,
) -> None:
    s, remote, lease = await _leased(tmp_path)
    sibling = await s.allocator.allocate(request(remote, run_id="run-2"))
    credentials = StaticCredentials()
    access = WorktreeWriteAccess(s.backend, credentials)
    grant = await access.grant(lease, unit="u1", remote_url=REPOSITORY)
    path = Path(lease.path)

    assert credentials.calls == [REPOSITORY]
    assert grant.credential_source == "github_app_installation"
    filled = _credential_fill(path)
    assert "username=x-access-token\n" in filled and f"password={APP_TOKEN}\n" in filled
    # The token lives in the clone's admin directory, never in the worktree or its status.
    assert _exists(grant.admin / CREDENTIAL_FILE)
    assert porcelain(path) == []
    assert APP_TOKEN not in _tree_text(path)
    # Inherited helpers are reset in this worktree; the sibling keeps none of ours.
    assert git("config", "--worktree", "--get-all", "credential.helper", cwd=path) == "\n"
    assert CREDENTIAL_FILE not in _config(sibling.path, "--get-all", SCOPED_HELPER)[1]

    await access.revoke(grant)
    assert not _exists(grant.admin / CREDENTIAL_FILE)
    assert _config(path, "--worktree", "--get-all", SCOPED_HELPER)[0] == 1
    # Still reset: a revoked worktree never falls back to the owner's ambient login.
    assert git("config", "--worktree", "--get-all", "credential.helper", cwd=path) == "\n"


async def test_cleanup_removes_the_grant_with_the_worktree(tmp_path: Path) -> None:
    s, _, lease = await _leased(tmp_path)
    access = WorktreeWriteAccess(s.backend, StaticCredentials())
    grant = await access.grant(lease, unit="u1", remote_url=REPOSITORY)

    await s.backend.remove(lease)

    assert not _exists(grant.admin) and not _exists(lease.path)

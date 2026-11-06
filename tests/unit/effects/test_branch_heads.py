"""MO-14 mission branch grammar and head SHA artifacts (the `Claude-Session:` trailer
correlation read through the GitHub commits API of a FIXTURE GitHub over a local remote)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mission_control.adapters.github.client import GitHubRestClient
from mission_control.adapters.workspaces.git_workspaces import run_git
from mission_control.application.effects.branch_heads import (
    MissionBranchHead,
    claude_session_head,
    commit_trailers,
    record_branch_head,
)
from mission_control.application.effects.mission_branches import (
    is_mission_branch,
    mission_branch,
)
from tests.unit.effects.support import API, REPOSITORY, FakeGitHub, StaticCredentials, make_remote
from tests.unit.workspaces.workspace_fixtures import MemoryArtifacts

SESSION = "https://claude.ai/code/session_01FixtureSession"
IDENTITY = ("-c", "user.name=Claude", "-c", "user.email=claude@localhost")


def test_mission_branches_are_mc_run_unit_and_nothing_else() -> None:
    assert mission_branch("run-1", "u1") == "mc/run-1/u1"
    assert is_mission_branch("mc/run-1/u1", "run-1")
    assert is_mission_branch("mc/run-1/u1-f2", "run-1")
    for branch in ("main", "mc/run-2/u1", "mc/run-1/", "mc/run-1/../main", "mc/ws/abc", "mc/run-1"):
        assert not is_mission_branch(branch, "run-1"), branch
    for run, unit in (("run 1", "u1"), ("run-1", "../main"), ("run-1", "x.lock"), ("-r", "u")):
        with pytest.raises(ValueError):
            mission_branch(run, unit)


def test_trailers_come_from_the_last_paragraph_only() -> None:
    message = (
        "Fix the parser\n\nClaude-Session: in the body is not a trailer\n\n"
        f"Co-Authored-By: Claude <noreply@anthropic.com>\r\nClaude-Session: {SESSION}\n"
    )
    trailers = commit_trailers(message)
    assert trailers["claude-session"] == (SESSION,)
    assert commit_trailers("subject only\n") == {}


def _commit(remote: Path, work: Path, message: str) -> str:
    (work / "notes.md").write_text(message, encoding="utf-8")
    run_git("add", "--all", cwd=work)
    run_git(*IDENTITY, "commit", "--quiet", "-m", message, cwd=work)
    run_git("push", "--quiet", str(remote), "HEAD:refs/heads/mc/run-1/u1", cwd=work)
    return run_git("rev-parse", "HEAD", cwd=work).decode().strip()


async def test_the_claude_session_trailer_names_the_sessions_head_and_is_recorded(
    tmp_path: Path,
) -> None:
    remote = make_remote(tmp_path / "github")
    work = tmp_path / "cloud-session"
    run_git("clone", "--quiet", str(remote), str(work), cwd=tmp_path)
    session_head = _commit(remote, work, f"Session work\n\nClaude-Session: {SESSION}\n")
    _commit(remote, work, "A later human commit\n")
    github = FakeGitHub(remote)
    host = GitHubRestClient(github.client(), StaticCredentials(), api_url=API)

    commits = await host.branch_commits(REPOSITORY, "mc/run-1/u1")
    head = claude_session_head(commits, SESSION)

    assert head == session_head and commits[0].sha != session_head
    assert claude_session_head(commits, "https://claude.ai/code/session_other") is None
    artifacts = MemoryArtifacts()
    ref = await record_branch_head(
        artifacts,
        MissionBranchHead(
            run_id="run-1",
            lane_profile="claude_cloud",
            repository=REPOSITORY,
            branch="mc/run-1/u1",
            head_sha=head,
            source="claude_session_trailer",
            session_ref=SESSION,
            observed_at=datetime(2026, 10, 13, 12, tzinfo=UTC),
        ),
        request_scope="scope/fixture",
    )
    recorded = MissionBranchHead.model_validate_json(artifacts.staged[ref])
    assert recorded.head_sha == session_head and recorded.source == "claude_session_trailer"
    assert await host.branch_commits(REPOSITORY, "mc/run-1/missing") == ()


def test_canonical_runtime_unit_keys_have_stable_git_safe_mission_branches():
    first = mission_branch("run-1", "bl-unit-v1:" + "a" * 64)
    assert first == "mc/run-1/bl-unit-v1-" + "a" * 64
    assert is_mission_branch(first, "run-1")
    assert first != mission_branch("run-1", "bl-unit-v1:" + "b" * 64)
    with pytest.raises(ValueError):
        mission_branch("run-1", "bl-unit-v1:../../escape")

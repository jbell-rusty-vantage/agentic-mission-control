"""Repo-free knowledge work reaches a distinct initialized local research lease."""

from pathlib import Path

from mission_control.adapters.cursor.workspace import GitWorktreeLeaser, git
from tests.fixtures.cursor_controls import started_session
from tests.fixtures.cursor_local import local_stack


async def test_repo_free_local_session_prepares_an_initialized_research_workspace(
    tmp_path: Path,
) -> None:
    stack = local_stack(tmp_path, repository=False)
    _, handle = await started_session(stack)
    lease = next(iter(stack.leases._leases.values()))
    root = Path(lease.path)
    assert lease.repository is None
    assert (root / ".git").exists()
    assert git("rev-parse", "HEAD", cwd=root).strip() == lease.base_commit
    assert (root / ".mission/operating-contract.md").is_file()
    assert handle.native_session_ref is not None


async def test_branch_output_collection_commits_and_reads_back_only_output_files(
    tmp_path: Path,
) -> None:
    stack = local_stack(tmp_path, repository=False)
    await started_session(stack)
    lease = next(iter(stack.leases._leases.values()))
    root = Path(lease.path)
    (root / "outputs/report.txt").write_bytes(b"knowledge report")
    (root / "unrelated.txt").write_text("keep uncommitted")
    git("add", "unrelated.txt", cwd=root)
    files = GitWorktreeLeaser._commit_outputs(root)
    assert ("outputs/report.txt", b"knowledge report") in files
    assert git("show", "HEAD:outputs/report.txt", cwd=root) == "knowledge report"
    assert "unrelated.txt" in git("diff", "--cached", "--name-only", cwd=root)

"""Real git bundle custody using temporary local bare remotes; no network credential."""

from pathlib import Path

import pytest

from mission_control.adapters.workspaces.bundle_publication import GitBundlePublisher
from mission_control.adapters.workspaces.git_workspaces import run_git
from mission_control.application.secrets.commit_scan import SecretInCommit

BRANCH = "mc/run-a/unit-a"


class NoCredential:
    async def credential(self, repository):
        raise AssertionError("a local test never obtains a network credential")


def repository(root: Path):
    source, remote = root / "source", root / "remote.git"
    source.mkdir()
    remote.mkdir()
    run_git("init", "--quiet", "-b", "main", cwd=source)
    run_git("config", "user.name", "Fixture", cwd=source)
    run_git("config", "user.email", "fixture@example.invalid", cwd=source)
    (source / "readme.txt").write_text("base\n")
    run_git("add", ".", cwd=source)
    run_git("commit", "--quiet", "-m", "base", cwd=source)
    base = run_git("rev-parse", "HEAD", cwd=source).decode().strip()
    run_git("init", "--bare", "--quiet", cwd=remote)
    run_git("push", "--quiet", str(remote), "main", cwd=source)
    run_git("checkout", "--quiet", "-b", BRANCH, cwd=source)
    return source, remote, base


def bundle(source: Path, base: str, *, secret: str | None = None):
    (source / "result.txt").write_text(secret or "verified evidence\n")
    run_git("add", ".", cwd=source)
    run_git("commit", "--quiet", "-m", "result", cwd=source)
    output = source.parent / "result.bundle"
    run_git("bundle", "create", str(output), BRANCH, f"^{base}", cwd=source)
    return output.read_bytes(), run_git("rev-parse", "HEAD", cwd=source).decode().strip()


async def test_verified_bundle_push_is_scoped_and_repeated_push_is_stable(tmp_path: Path) -> None:
    source, remote, base = repository(tmp_path)
    content, head = bundle(source, base)
    publisher = GitBundlePublisher(tmp_path / "custody", NoCredential())
    for _ in range(2):
        assert (
            await publisher.publish(
                repository=str(remote),
                run_id="run-a",
                branch=BRANCH,
                base_commit=base,
                bundle=content,
            )
            == head
        )
    assert run_git("rev-parse", "refs/heads/main", cwd=remote).decode().strip() == base
    assert run_git("rev-parse", f"refs/heads/{BRANCH}", cwd=remote).decode().strip() == head


async def test_extra_bundle_refs_are_refused_before_push(tmp_path: Path) -> None:
    source, remote, base = repository(tmp_path)
    bundle(source, base)
    output = tmp_path / "all.bundle"
    run_git("bundle", "create", str(output), "--all", cwd=source)
    with pytest.raises(ValueError, match="advertise only"):
        await GitBundlePublisher(tmp_path / "custody", NoCredential()).publish(
            repository=str(remote),
            run_id="run-a",
            branch=BRANCH,
            base_commit=base,
            bundle=output.read_bytes(),
        )
    assert BRANCH not in run_git("for-each-ref", "--format=%(refname)", cwd=remote).decode()


async def test_removed_secret_in_intermediate_commit_is_still_refused(tmp_path: Path) -> None:
    source, remote, base = repository(tmp_path)
    secret = "fixture-private-secret-12345"
    bundle(source, base, secret=secret)
    content, _head = bundle(source, base)
    with pytest.raises(SecretInCommit):
        await GitBundlePublisher(tmp_path / "custody", NoCredential()).publish(
            repository=str(remote),
            run_id="run-a",
            branch=BRANCH,
            base_commit=base,
            bundle=content,
            secret_values=(secret,),
        )
    assert BRANCH not in run_git("for-each-ref", "--format=%(refname)", cwd=remote).decode()


async def test_wrong_run_branch_refuses_without_creating_git_repository(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="admitted mission branch"):
        await GitBundlePublisher(tmp_path / "custody", NoCredential()).publish(
            repository=str(tmp_path),
            run_id="run-b",
            branch=BRANCH,
            base_commit="a" * 40,
            bundle=b"untrusted",
        )
    assert not (tmp_path / "custody").exists()

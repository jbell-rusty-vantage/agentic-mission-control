"""Builders, constants and fakes that other test files import.

Moved from tests/unit/effects/test_hosted_bundle_publication.py.
"""

from pathlib import Path

from mission_control.adapters.workspaces.git_workspaces import run_git

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

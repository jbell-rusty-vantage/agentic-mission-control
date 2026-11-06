"""Worktree-scoped git write access for a local lease (SPEC-01 section 6; MO-14).

A local lane's lease works on its slot branch (`mc/ws/<digest>`) in a worktree of Mission
Control's dedicated clone. `WorktreeWriteAccess.grant` lets that one worktree publish to the
mission branch `mc/{run}/{unit}` of the target repository and nothing else:

- **Worktree config only.** The clone gets `extensions.worktreeConfig`; every setting below is
  written with `git config --worktree` into `<clone>/worktrees/<id>/config.worktree`, never to
  the clone's shared config, the user's global config or the developer's checkout. Sibling
  worktrees of the clone see none of it.
- **Publish remote.** `mc-publish` points at the target repository URL (a lease's `origin` may
  be the developer's local checkout) with the push refspec
  `refs/heads/<lease branch>:refs/heads/mc/{run}/{unit}`, and is the worktree's push default, so
  a plain `git push` from the agent lands on the mission branch.
- **Pre-push guard.** `core.hooksPath` names a Mission Control-owned hooks directory in the
  worktree's admin directory (inside the clone, outside the agent's worktree). Its `pre-push`
  refuses every remote ref outside `refs/heads/mc/{run}/`. A hook is a client-side guard: an
  agent that runs `git push --no-verify` bypasses it, so the credential itself is restricted
  to the target repository (and server-side branch protection remains the owner's control).
- **Scoped credential.** For an `https://` target, the inherited helpers are reset and one
  helper scoped to that host answers from a credential file in the admin directory: a GitHub
  App installation token restricted to the target repository, or the owner's `gh` login as the
  attested fallback (DECISIONS R26). The token never enters the worktree, a frame or a log;
  Mission Control refreshes it before each push it performs, and the file goes with the
  worktree's admin directory at cleanup (or at `revoke`).

`push` is Mission Control's own publication of the lease branch: through the same guard and
credential, without force, then read back from the remote as the branch's head SHA.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from mission_control.adapters.workspaces.git_workspaces import GitWorkspaceBackend, run_git
from mission_control.application.effects.mission_branches import (
    mission_branch,
    mission_branch_prefix,
)
from mission_control.application.effects.ports import (
    CredentialSourceKind,
    GitCredential,
    GitCredentialSource,
)
from mission_control.application.execution.harness.leases import WorkspaceLease
from mission_control.application.workspaces.errors import (
    WORKSPACE_PATH_ESCAPE,
    WORKSPACE_PUBLISH_REFUSED,
    WorkspaceError,
)
from mission_control.application.workspaces.policy import contained

PUBLISH_REMOTE: Final = "mc-publish"
HOOKS_DIR: Final = "mc-hooks"
CREDENTIAL_FILE: Final = "mc-credential"
_GUARD: Final = """#!/bin/sh
# Mission Control pre-push guard (MO-14): this worktree may push only {allowed}*.
allowed='{allowed}'
status=0
while read -r local_ref local_sha remote_ref remote_sha; do
  case "$remote_ref" in
    "$allowed"?*) ;;
    *)
      echo "mission control: push to $remote_ref refused; only $allowed* is allowed" >&2
      status=1
      ;;
  esac
done
exit $status
"""


@dataclass(frozen=True)
class WriteGrant:
    """One worktree's write access: which lease branch publishes to which mission branch."""

    path: Path
    admin: Path
    remote_url: str
    local_branch: str
    mission_branch: str
    credential_source: CredentialSourceKind | None

    @property
    def remote_ref(self) -> str:
        return f"refs/heads/{self.mission_branch}"


@dataclass(frozen=True)
class PushedBranch:
    branch: str
    head_sha: str


def _https_origin(remote_url: str) -> str | None:
    parts = urlsplit(remote_url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    return f"https://{parts.hostname}"


def _write_private(path: Path, content: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
    path.chmod(mode)


def _credential_lines(credential: GitCredential) -> bytes:
    secret = credential.secret.get_secret_value()
    if any(character in secret + credential.username for character in "\r\n\0"):
        raise ValueError("a git credential carries no line breaks")
    return f"username={credential.username}\npassword={secret}\n".encode()


class WorktreeWriteAccess:
    """Grants, refreshes and revokes a lease worktree's scoped write path."""

    def __init__(self, backend: GitWorkspaceBackend, credentials: GitCredentialSource) -> None:
        self._backend = backend
        self._credentials = credentials

    async def grant(self, lease: WorkspaceLease, *, unit: str, remote_url: str) -> WriteGrant:
        if lease.branch is None:
            raise WorkspaceError(
                WORKSPACE_PUBLISH_REFUSED, "a detached lease has no branch to publish"
            )
        target = mission_branch(lease.run_id, unit)
        origin = _https_origin(remote_url)
        credential = await self._credentials.credential(remote_url) if origin else None
        return await asyncio.to_thread(
            self._grant, lease, lease.branch, target, remote_url, origin, credential
        )

    def _locate(self, lease: WorkspaceLease) -> tuple[Path, Path, Path]:
        path = contained(self._backend.root, Path(lease.path))
        admin = contained(
            self._backend.root,
            Path(run_git("rev-parse", "--absolute-git-dir", cwd=path).decode().strip()),
        )
        common = Path(run_git("rev-parse", "--git-common-dir", cwd=path).decode().strip())
        clone = contained(self._backend.root, common if common.is_absolute() else path / common)
        if "'" in admin.as_posix():
            raise WorkspaceError(WORKSPACE_PATH_ESCAPE, f"{admin} cannot be quoted for git")
        return path, admin, clone

    def _grant(
        self,
        lease: WorkspaceLease,
        local_branch: str,
        target: str,
        remote_url: str,
        origin: str | None,
        credential: GitCredential | None,
    ) -> WriteGrant:
        path, admin, clone = self._locate(lease)
        self._backend.enable_worktree_config(clone)
        hooks = admin / HOOKS_DIR
        hooks.mkdir(exist_ok=True)
        guard = _GUARD.format(allowed=f"refs/heads/{mission_branch_prefix(lease.run_id)}")
        _write_private(hooks / "pre-push", guard.encode("utf-8"), 0o755)

        def config(*args: str) -> None:
            run_git("config", "--worktree", *args, cwd=path)

        config("core.hooksPath", hooks.as_posix())
        config(f"remote.{PUBLISH_REMOTE}.url", remote_url)
        config(
            "--replace-all",
            f"remote.{PUBLISH_REMOTE}.push",
            f"refs/heads/{local_branch}:refs/heads/{target}",
        )
        config("remote.pushDefault", PUBLISH_REMOTE)
        if origin is not None and credential is not None:
            credential_file = admin / CREDENTIAL_FILE
            _write_private(credential_file, _credential_lines(credential), 0o600)
            # An empty helper resets every inherited one (system, global, the clone's), so the
            # owner's ambient login is never offered; the scoped helper only answers `get`.
            config("--replace-all", "credential.helper", "")
            config(
                "--replace-all",
                f"credential.{origin}.helper",
                f"!f() {{ test \"$1\" = get && cat '{credential_file.as_posix()}'; }}; f",
            )
        return WriteGrant(
            path=path,
            admin=admin,
            remote_url=remote_url,
            local_branch=local_branch,
            mission_branch=target,
            credential_source=credential.source if credential is not None else None,
        )

    async def refresh(self, grant: WriteGrant) -> None:
        """Re-issue the grant's credential (an installation token lives one hour)."""

        if grant.credential_source is None:
            return
        credential = await self._credentials.credential(grant.remote_url)
        await asyncio.to_thread(
            _write_private, grant.admin / CREDENTIAL_FILE, _credential_lines(credential), 0o600
        )

    async def push(self, grant: WriteGrant) -> PushedBranch:
        """Publish the lease branch to its mission branch (no force) and read the head back."""

        await self.refresh(grant)
        return await asyncio.to_thread(self._push, grant)

    def _push(self, grant: WriteGrant) -> PushedBranch:
        local = run_git("rev-parse", f"refs/heads/{grant.local_branch}", cwd=grant.path)
        run_git(
            "push",
            "--quiet",
            PUBLISH_REMOTE,
            f"refs/heads/{grant.local_branch}:{grant.remote_ref}",
            cwd=grant.path,
        )
        listed = run_git("ls-remote", PUBLISH_REMOTE, grant.remote_ref, cwd=grant.path).split()
        head = listed[0].decode() if listed else ""
        if head != local.decode().strip():
            raise WorkspaceError(
                WORKSPACE_PUBLISH_REFUSED,
                f"{grant.mission_branch} reads back {head or 'nothing'} after the push",
            )
        return PushedBranch(branch=grant.mission_branch, head_sha=head)

    async def revoke(self, grant: WriteGrant) -> None:
        """Drop the credential and its scoped helper. The reset of inherited helpers, the
        guard and the publish remote stay, so a revoked worktree cannot fall back to the
        owner's ambient login."""

        await asyncio.to_thread(self._revoke, grant)

    @staticmethod
    def _revoke(grant: WriteGrant) -> None:
        (grant.admin / CREDENTIAL_FILE).unlink(missing_ok=True)
        origin = _https_origin(grant.remote_url)
        if origin is not None:
            run_git(
                "config",
                "--worktree",
                "--unset-all",
                f"credential.{origin}.helper",
                cwd=grant.path,
                check=False,
            )


__all__ = [
    "CREDENTIAL_FILE",
    "HOOKS_DIR",
    "PUBLISH_REMOTE",
    "PushedBranch",
    "WorktreeWriteAccess",
    "WriteGrant",
]

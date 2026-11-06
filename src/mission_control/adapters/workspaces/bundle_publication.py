"""Verify an untrusted hosted git bundle and publish one admitted mission branch.

Git runs only in a temporary bare staging repository, with hooks disabled. The
worker's scoped credential never reaches the provider sandbox or an artifact.
"""

from __future__ import annotations

import asyncio
import shlex
import tempfile
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

from mission_control.adapters.workspaces.git_workspaces import GitCommandError, run_git
from mission_control.adapters.workspaces.git_write import _credential_lines, _write_private
from mission_control.application.effects.mission_branches import is_mission_branch
from mission_control.application.effects.ports import GitCredential, GitCredentialSource
from mission_control.application.secrets.commit_scan import scan_commit

MAX_BUNDLE_BYTES = 32 * 1024 * 1024
MAX_SCAN_BYTES = 128 * 1024 * 1024
MAX_COMMITS = 256


class GitBundlePublisher:
    def __init__(self, root: Path, credentials: GitCredentialSource) -> None:
        self._root, self._credentials = root, credentials

    async def publish(
        self,
        *,
        repository: str,
        run_id: str,
        branch: str,
        base_commit: str,
        bundle: bytes,
        secret_values: Iterable[str] = (),
    ) -> str:
        if not is_mission_branch(branch, run_id) or not 0 < len(bundle) <= MAX_BUNDLE_BYTES:
            raise ValueError("publication needs an admitted mission branch and a bounded bundle")
        target = urlsplit(repository)
        if target.scheme == "https" and (
            target.username or target.password or target.query or target.fragment
        ):
            raise ValueError("repository URLs cannot carry credentials or query strings")
        credential = (
            await self._credentials.credential(repository) if target.scheme == "https" else None
        )
        if credential is not None and credential.repository != repository:
            raise ValueError("publication credential is scoped to another repository")
        self._root.mkdir(parents=True, exist_ok=True)
        try:
            return await asyncio.to_thread(
                self._publish,
                repository,
                branch,
                base_commit,
                bundle,
                tuple(secret_values),
                credential,
            )
        except GitCommandError:
            raise ValueError("git bundle verification or publication failed") from None

    def _publish(
        self,
        repository: str,
        branch: str,
        base_commit: str,
        bundle: bytes,
        secrets: tuple[str, ...],
        credential: GitCredential | None,
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="hosted-bundle-", dir=self._root) as temporary:
            root = Path(temporary)
            run_git("init", "--bare", "--quiet", cwd=root)
            run_git("config", "core.hooksPath", str(root / "disabled-hooks"), cwd=root)
            run_git("config", "protocol.ext.allow", "never", cwd=root)
            run_git("config", "credential.helper", "", cwd=root)
            if credential is not None:
                path = root / "mc-credential"
                _write_private(path, _credential_lines(credential), 0o600)
                target = urlsplit(repository)
                origin = f"{target.scheme}://{target.netloc}"
                helper = f'!f() {{ test "$1" = get && cat {shlex.quote(path.as_posix())}; }}; f'
                run_git("config", f"credential.{origin}.helper", helper, cwd=root)
            run_git("fetch", "--quiet", "--no-tags", repository, base_commit, cwd=root)
            base = run_git("rev-parse", "FETCH_HEAD^{commit}", cwd=root).decode().strip()
            if base != base_commit:
                raise ValueError("publication base does not equal its sealed commit")
            bundle_path = root / "provider.bundle"
            bundle_path.write_bytes(bundle)
            run_git("bundle", "verify", str(bundle_path), cwd=root)
            refs = run_git("bundle", "list-heads", str(bundle_path), cwd=root).decode().splitlines()
            expected_ref = f"refs/heads/{branch}"
            if len(refs) != 1 or refs[0].split(maxsplit=1)[-1] != expected_ref:
                raise ValueError("bundle must advertise only the admitted mission branch")
            run_git(
                "fetch",
                "--quiet",
                str(bundle_path),
                f"{expected_ref}:refs/heads/verified",
                cwd=root,
            )
            head = run_git("rev-parse", "refs/heads/verified^{commit}", cwd=root).decode().strip()
            run_git("merge-base", "--is-ancestor", base, head, cwd=root)
            self._scan(root, base, head, secrets)
            # No force, no wildcard refspec, and no agent-provided remote or target.
            run_git("push", "--quiet", repository, f"{head}:{expected_ref}", cwd=root)
            readback = run_git("ls-remote", "--heads", repository, expected_ref, cwd=root).split()
            if not readback or readback[0].decode() != head:
                raise ValueError("published branch did not read back at its verified head")
            return head

    @staticmethod
    def _scan(root: Path, base: str, head: str, secrets: tuple[str, ...]) -> None:
        commits = run_git("rev-list", head, f"^{base}", cwd=root).decode().splitlines()
        if len(commits) > MAX_COMMITS:
            raise ValueError("bundle exceeds the commit custody bound")
        scanned: set[str] = set()
        size = 0
        for commit in commits:
            message = run_git("show", "-s", "--format=%B", commit, cwd=root).decode(
                "utf-8", "replace"
            )
            scan_commit((), message=message, secret_values=secrets)
            for entry in run_git("ls-tree", "-r", "-z", commit, cwd=root).split(b"\0"):
                if not entry:
                    continue
                metadata, raw_path = entry.split(b"\t", 1)
                _mode, kind, object_id = metadata.decode().split()
                path = raw_path.decode("utf-8", "surrogateescape")
                if Path(path).name == ".env" or ".scratch" in Path(path).parts:
                    raise ValueError("bundle carries excluded private working material")
                if kind != "blob" or object_id in scanned:
                    continue
                scanned.add(object_id)
                blob_size = int(run_git("cat-file", "-s", object_id, cwd=root))
                size += blob_size
                if size > MAX_SCAN_BYTES:
                    raise ValueError("bundle exceeds the secret scan custody bound")
                scan_commit(
                    [(path, run_git("cat-file", "blob", object_id, cwd=root))],
                    secret_values=secrets,
                )

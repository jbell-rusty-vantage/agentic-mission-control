"""Ports of the git write path (SPEC-01 section 6; MO-14).

`GitCredentialSource` issues the per-run push credential: a Mission Control GitHub App
installation token restricted to the target repository, or the owner's `gh` login as the
owner-attested fallback (DECISIONS R26). It is the seam the Secret Broker (MO-11) takes over;
the secret is a `SecretStr` and never enters a log, frame or receipt.

`RepositoryHost` is what Mission Control reads and writes at the repository host itself:
branch heads, pull requests and the commits of a branch.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

CredentialSourceKind = Literal["github_app_installation", "owner_gh"]
OBJECT_ID = r"^[0-9a-f]{40,64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GitCredential(_Strict):
    """One push credential for one repository; `secret` is never rendered."""

    repository: str = Field(min_length=1)
    username: str = Field(min_length=1, max_length=256)
    secret: SecretStr
    source: CredentialSourceKind
    expires_at: AwareDatetime | None = None


class GitCredentialSource(Protocol):
    async def credential(self, repository: str) -> GitCredential:
        """A credential that can push to `repository` (and, for the App, only to it)."""
        ...


class PullRequest(_Strict):
    number: int = Field(ge=1)
    url: str = Field(min_length=1, max_length=2_048)
    head_branch: str = Field(min_length=1, max_length=256)
    head_sha: str = Field(pattern=OBJECT_ID)
    base: str = Field(min_length=1, max_length=256)
    draft: bool
    state: str = Field(min_length=1, max_length=32)


class BranchCommit(_Strict):
    sha: str = Field(pattern=OBJECT_ID)
    message: str


class RepositoryHost(Protocol):
    async def branch_head(self, repository: str, branch: str) -> str | None:
        """The branch's head commit at the host, or None when the branch does not exist."""
        ...

    async def find_pull_request(
        self, repository: str, *, head: str, base: str
    ) -> PullRequest | None:
        """The pull request from `head` into `base` (any state), if one exists."""
        ...

    async def create_pull_request(
        self, repository: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> PullRequest: ...

    async def branch_commits(
        self, repository: str, branch: str, *, limit: int = 30
    ) -> tuple[BranchCommit, ...]:
        """The newest commits reachable from the branch head, newest first."""
        ...


__all__ = [
    "OBJECT_ID",
    "BranchCommit",
    "CredentialSourceKind",
    "GitCredential",
    "GitCredentialSource",
    "PullRequest",
    "RepositoryHost",
]

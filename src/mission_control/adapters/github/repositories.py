"""GitHub repository identity and REST conventions shared by the GitHub adapters (MO-14)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

GITHUB_HOST: Final = "github.com"
GITHUB_API: Final = "https://api.github.com"
API_HEADERS: Final = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
_NAME: Final = r"[A-Za-z0-9_.-]+"
_HTTPS: Final = re.compile(rf"^https://{re.escape(GITHUB_HOST)}/({_NAME})/({_NAME}?)(?:\.git)?/?$")
_SSH: Final = re.compile(rf"^git@{re.escape(GITHUB_HOST)}:({_NAME})/({_NAME}?)(?:\.git)?$")


class GitHubError(RuntimeError):
    """A GitHub call failed; the message names the call and status, never a credential."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    name: str

    @classmethod
    def parse(cls, repository: str) -> GitHubRepository:
        """`https://github.com/<owner>/<repo>[.git]` or `git@github.com:<owner>/<repo>.git`."""

        match = _HTTPS.fullmatch(repository) or _SSH.fullmatch(repository)
        if match is None:
            raise GitHubError(f"{repository} is not a GitHub repository URL")
        return cls(owner=match.group(1), name=match.group(2))

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


__all__ = ["API_HEADERS", "GITHUB_API", "GITHUB_HOST", "GitHubError", "GitHubRepository"]

"""GitHub adapters of the git write path (SPEC-01 section 6; MO-14).

`credentials` issues push credentials (Mission Control GitHub App installation tokens
restricted to the target repository, or the owner-attested `gh` fallback); `client`
implements `application.effects.ports.RepositoryHost` over the GitHub REST API; `repositories`
holds the shared repository identity and REST conventions. No webhook is registered here.
"""

from __future__ import annotations

from mission_control.adapters.github.client import GitHubRestClient
from mission_control.adapters.github.credentials import (
    GitHubAppInstallationTokens,
    GitHubCredentialError,
    OwnerGhCredentials,
    github_credentials,
)
from mission_control.adapters.github.repositories import GitHubError, GitHubRepository

__all__ = [
    "GitHubAppInstallationTokens",
    "GitHubCredentialError",
    "GitHubError",
    "GitHubRepository",
    "GitHubRestClient",
    "OwnerGhCredentials",
    "github_credentials",
]

"""Read-only GitHub polling fallback, using repository-scoped credentials."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from urllib.parse import quote

from mission_control.adapters.github.client import GitHubRestClient
from mission_control.adapters.github.repositories import GitHubRepository
from mission_control.application.watchers.sources import SourceSignal, github_signal


class GitHubSignalPoller:
    def __init__(self, client: GitHubRestClient, repository: str) -> None:
        self._client = client
        self._repository = repository

    async def sample(self, *, ref: str, now: datetime) -> tuple[SourceSignal, ...]:
        response = await self._client._request(
            "GET",
            self._repository,
            f"/commits/{quote(ref, safe='')}/check-suites",
            params={"per_page": 100},
            timeout=5,
            follow_redirects=False,
        )
        document = self._client._require(response, "check suite poll")
        result = []
        for suite in document.get("check_suites", []):
            payload = {
                "action": "completed" if suite.get("status") == "completed" else "requested",
                "check_suite": suite,
                "repository": {"full_name": GitHubRepository.parse(self._repository).full_name},
            }
            identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            result.append(
                github_signal(
                    "check_suite", payload, delivery_id=f"poll:{identity}", observed_at=now
                )
            )
        return tuple(result)

    async def pull_request(self, number: int, *, now: datetime) -> SourceSignal:
        if number < 1:
            raise ValueError("positive pull request number required")
        response = await self._client._request(
            "GET", self._repository, f"/pulls/{number}", timeout=5, follow_redirects=False
        )
        pull = self._client._require(response, "pull request poll")
        payload = {
            "action": "closed" if pull.get("state") == "closed" else "opened",
            "pull_request": pull,
            "repository": {"full_name": GitHubRepository.parse(self._repository).full_name},
        }
        identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return github_signal(
            "pull_request", payload, delivery_id=f"poll:{identity}", observed_at=now
        )

"""`RepositoryHost` over the GitHub REST API (SPEC-01 section 6; MO-14).

Every call authenticates with the credential the `GitCredentialSource` issues for that
repository (an App installation token restricted to it, or the owner's `gh` login):

- branch head: `GET /repos/{owner}/{repo}/git/ref/heads/{branch}` (404 is "no such branch");
- pull requests: `GET /repos/{owner}/{repo}/pulls?head={owner}:{branch}&base=...&state=all`
  and `POST /repos/{owner}/{repo}/pulls` with `draft`;
- branch commits: `GET /repos/{owner}/{repo}/commits?sha={branch}` (newest first), which is
  where a Claude cloud session's `Claude-Session:` trailer is read.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from mission_control.adapters.github.repositories import (
    API_HEADERS,
    GITHUB_API,
    GitHubError,
    GitHubRepository,
)
from mission_control.application.effects.ports import (
    BranchCommit,
    GitCredentialSource,
    PullRequest,
)


def _pull_request(body: dict[str, Any]) -> PullRequest:
    return PullRequest(
        number=int(body["number"]),
        url=str(body["html_url"]),
        head_branch=str(body["head"]["ref"]),
        head_sha=str(body["head"]["sha"]),
        base=str(body["base"]["ref"]),
        draft=bool(body.get("draft", False)),
        state=str(body["state"]),
    )


class GitHubRestClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        credentials: GitCredentialSource,
        *,
        api_url: str = GITHUB_API,
    ) -> None:
        self._http = http
        self._credentials = credentials
        self._api = api_url.rstrip("/")

    async def _request(
        self, method: str, repository: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        target = GitHubRepository.parse(repository)
        credential = await self._credentials.credential(repository)
        headers = {
            **API_HEADERS,
            "Authorization": f"Bearer {credential.secret.get_secret_value()}",
        }
        return await self._http.request(
            method,
            f"{self._api}/repos/{target.owner}/{target.name}{path}",
            headers=headers,
            **kwargs,
        )

    @staticmethod
    def _require(response: httpx.Response, what: str, *expected: int) -> Any:
        if response.status_code not in (expected or (200,)):
            raise GitHubError(
                f"{what} failed ({response.status_code})", status=response.status_code
            )
        return response.json()

    async def branch_head(self, repository: str, branch: str) -> str | None:
        response = await self._request(
            "GET", repository, f"/git/ref/heads/{quote(branch, safe='/')}"
        )
        if response.status_code == 404:
            return None
        body = self._require(response, f"branch lookup of {branch}")
        return str(body["object"]["sha"])

    async def find_pull_request(
        self, repository: str, *, head: str, base: str
    ) -> PullRequest | None:
        owner = GitHubRepository.parse(repository).owner
        response = await self._request(
            "GET",
            repository,
            "/pulls",
            params={"head": f"{owner}:{head}", "base": base, "state": "all", "per_page": "10"},
        )
        listed = self._require(response, f"pull request lookup of {head}")
        matches = [item for item in listed if item.get("head", {}).get("ref") == head]
        return _pull_request(matches[0]) if matches else None

    async def create_pull_request(
        self, repository: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> PullRequest:
        response = await self._request(
            "POST",
            repository,
            "/pulls",
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
        )
        return _pull_request(self._require(response, f"pull request from {head}", 201))

    async def branch_commits(
        self, repository: str, branch: str, *, limit: int = 30
    ) -> tuple[BranchCommit, ...]:
        response = await self._request(
            "GET", repository, "/commits", params={"sha": branch, "per_page": str(limit)}
        )
        if response.status_code in {404, 409}:
            return ()
        listed = self._require(response, f"commits of {branch}")
        return tuple(
            BranchCommit(sha=str(item["sha"]), message=str(item["commit"]["message"]))
            for item in listed
        )

    async def find_comment(self, repository: str, number: int, marker: str) -> str | None:
        for page in range(1, 11):
            response = await self._request(
                "GET",
                repository,
                f"/issues/{number}/comments",
                params={"per_page": "100", "page": str(page)},
            )
            items = self._require(response, "mission PR comment lookup")
            for item in items:
                if marker in str(item.get("body") or ""):
                    return str(item["html_url"])
            if len(items) < 100:
                return None
        raise GitHubError("mission PR comment lookup exceeds reconciliation bound")

    async def create_comment(self, repository: str, number: int, body: str) -> str:
        response = await self._request(
            "POST", repository, f"/issues/{number}/comments", json={"body": body}
        )
        return str(self._require(response, "mission PR comment", 201)["html_url"])


__all__ = ["GitHubRestClient"]

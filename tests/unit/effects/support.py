"""FIXTURE GitHub for the MO-14 git write path: a local bare repository stands in for the
GitHub remote and an `httpx.MockTransport` serves the REST calls Mission Control makes
against it (installation tokens, branch refs, pull requests, branch commits). Nothing leaves
the machine; no GitHub App, webhook or real pull request exists.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey
from pydantic import SecretStr

from mission_control.adapters.workspaces.git_workspaces import GitCommandError, run_git
from mission_control.adapters.workspaces.git_write import PUBLISH_REMOTE, WorktreeWriteAccess
from mission_control.application.effects.ports import GitCredential
from tests.unit.workspaces.workspace_fixtures import commit, request, stack

OWNER = "Overton77"
NAME = "mission-control"
REPOSITORY = f"https://github.com/{OWNER}/{NAME}"
APP_ID = "424242"
INSTALLATION_ID = "777"
APP_TOKEN = "ghs_fixture_installation_token"
API = "https://api.github.test"


def make_remote(root: Path) -> Path:
    """A bare repository with `main` (one commit): the stand-in for the GitHub remote."""

    seed = root / "seed"
    seed.mkdir(parents=True)
    run_git("init", "--quiet", "--initial-branch=main", cwd=seed)
    (seed / "README.md").write_bytes(b"# fixture\n")
    run_git("add", "--all", cwd=seed)
    run_git(
        "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost",
        "commit", "--quiet", "-m", "base", cwd=seed,
    )  # fmt: skip
    remote = root / "remote.git"
    run_git("init", "--quiet", "--bare", "--initial-branch=main", str(remote), cwd=root)
    run_git("push", "--quiet", str(remote), "main:refs/heads/main", cwd=seed)
    return remote


def remote_head(remote: Path, branch: str) -> str | None:
    listed = run_git(
        "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=remote, check=False
    )
    return listed.decode().strip() or None


class StaticCredentials:
    """FIXTURE `GitCredentialSource` returning one fixed token; counts its calls."""

    def __init__(self, token: str = APP_TOKEN, *, username: str = "x-access-token") -> None:
        self.token = token
        self.username = username
        self.calls: list[str] = []

    async def credential(self, repository: str) -> GitCredential:
        self.calls.append(repository)
        return GitCredential(
            repository=repository,
            username=self.username,
            secret=SecretStr(self.token),
            source="github_app_installation",
        )


@dataclass
class FakeGitHub:
    """The REST surface Mission Control uses, answered from the bare remote."""

    remote: Path
    app_key: RSAKey | None = None
    token: str = APP_TOKEN
    pulls: list[dict[str, Any]] = field(default_factory=list)
    token_requests: list[dict[str, Any]] = field(default_factory=list)
    requests: list[tuple[str, str]] = field(default_factory=list)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        self.requests.append((request.method, path))
        if path == f"/app/installations/{INSTALLATION_ID}/access_tokens":
            return self._token(request)
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        prefix = f"/repos/{OWNER}/{NAME}"
        if not path.startswith(prefix):
            return httpx.Response(404, json={"message": "Not Found"})
        rest = path.removeprefix(prefix)
        if request.method == "GET" and rest.startswith("/git/ref/heads/"):
            head = remote_head(self.remote, rest.removeprefix("/git/ref/heads/"))
            if head is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"ref": f"refs/{rest[9:]}", "object": {"sha": head}})
        if rest == "/pulls" and request.method == "GET":
            return httpx.Response(200, json=self._listed(request.url.params))
        if rest == "/pulls" and request.method == "POST":
            return self._create(json.loads(request.content))
        if rest == "/commits" and request.method == "GET":
            return self._commits(request.url.params)
        return httpx.Response(404, json={"message": "Not Found"})

    def _token(self, request: httpx.Request) -> httpx.Response:
        assert self.app_key is not None
        bearer = request.headers["Authorization"].removeprefix("Bearer ")
        try:
            claims = jwt.decode(bearer, self.app_key, algorithms=["RS256"]).claims
        except JoseError:
            return httpx.Response(401, json={"message": "A JSON web token could not be decoded"})
        body = json.loads(request.content)
        self.token_requests.append({"claims": claims, "body": body})
        if claims.get("iss") != APP_ID:
            return httpx.Response(401, json={"message": "wrong app"})
        return httpx.Response(
            201,
            json={
                "token": self.token,
                "expires_at": "2026-10-13T13:00:00Z",
                "permissions": body["permissions"],
                "repository_selection": "selected",
                "repositories": [{"full_name": f"{OWNER}/{name}"} for name in body["repositories"]],
            },
        )

    def _listed(self, params: Mapping[str, str]) -> list[dict[str, Any]]:
        head = params.get("head", "").removeprefix(f"{OWNER}:")
        base = params.get("base")
        return [
            pull
            for pull in self.pulls
            if pull["head"]["ref"] == head and (base is None or pull["base"]["ref"] == base)
        ]

    def _create(self, body: dict[str, Any]) -> httpx.Response:
        head = remote_head(self.remote, body["head"])
        if head is None:
            return httpx.Response(422, json={"message": "head does not exist"})
        number = len(self.pulls) + 1
        pull = {
            "number": number,
            "html_url": f"https://github.com/{OWNER}/{NAME}/pull/{number}",
            "state": "open",
            "draft": bool(body.get("draft", False)),
            "title": body["title"],
            "body": body.get("body", ""),
            "head": {"ref": body["head"], "sha": head},
            "base": {"ref": body["base"]},
        }
        self.pulls.append(pull)
        return httpx.Response(201, json=pull)

    def _commits(self, params: Mapping[str, str]) -> httpx.Response:
        branch = params["sha"]
        if remote_head(self.remote, branch) is None:
            return httpx.Response(404, json={"message": "Not Found"})
        raw = run_git(
            "log", f"--max-count={params.get('per_page', '30')}", "--format=%H%x00%B%x1e",
            f"refs/heads/{branch}", cwd=self.remote,
        ).decode("utf-8")  # fmt: skip
        listed = []
        for record in raw.split("\x1e"):
            sha, _, message = record.strip("\n").partition("\x00")
            if sha:
                listed.append({"sha": sha, "commit": {"message": message}})
        return httpx.Response(200, json=listed)


async def published_mission_branch(
    tmp_path: Path, *, run_id: str = "run-1", unit: str = "u1"
) -> tuple[Path, str]:
    """A real local lease (MO-05 WorkspaceAllocator) whose agent commits work, then the
    Mission Control push of the lease branch to `mc/<run>/<unit>` on the bare remote; the
    agent's own push to `main` is refused by the guard on the way."""

    remote = make_remote(tmp_path / "github")
    s = stack(tmp_path, primary=remote)
    lease = await s.allocator.allocate(request(remote, run_id=run_id))
    access = WorktreeWriteAccess(s.backend, StaticCredentials())
    grant = await access.grant(lease, unit=unit, remote_url=str(remote))
    path = Path(lease.path)
    (path / "fix.py").write_bytes(b"print('fixed')\n")
    run_git("add", "--all", cwd=path)
    commit(path, "fix the bug")
    main = remote_head(remote, "main")
    with pytest.raises(GitCommandError) as refused:
        run_git("push", PUBLISH_REMOTE, "HEAD:refs/heads/main", cwd=path)
    assert f"only refs/heads/mc/{run_id}/* is allowed" in refused.value.stderr
    assert remote_head(remote, "main") == main
    pushed = await access.push(grant)
    return remote, pushed.head_sha

"""A stateful fake of the Agents API resources prepare touches (HL-11).

It serves the request shapes of the pinned `openai` 3.29.0 source: cursor pages (`data`,
`has_more`, `after`), vault metadata filters, `Idempotency-Key` on environment creates. Every
request is recorded so tests can prove what a sync sent and that a reuse sent no create.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from mission_control.adapters.openai_agents.client import AgentsApiClient

API_KEY = "sk-test-not-a-real-key"
SHIPPED_PACK = (
    Path(__file__).resolve().parents[3] / "deployments" / "hosted-packs" / "ai-engineer"
) / "codex_agents"


@dataclass
class Recorded:
    method: str
    path: str
    params: dict[str, str]
    headers: httpx.Headers
    body: Any


@dataclass
class FakeAgentsApi:
    page_size: int = 100
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    templates: dict[str, dict[str, Any]] = field(default_factory=dict)
    vaults: dict[str, dict[str, Any]] = field(default_factory=dict)
    credentials: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    environments: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotent: dict[str, str] = field(default_factory=dict)
    requests: list[Recorded] = field(default_factory=list)
    fail: dict[tuple[str, str], httpx.Response] = field(default_factory=dict)
    _ids: count[int] = field(default_factory=lambda: count(1))

    def client(self) -> AgentsApiClient:
        return AgentsApiClient(SecretStr(API_KEY), transport=httpx.MockTransport(self.handle))

    def creates(self) -> list[str]:
        return [request.path for request in self.requests if request.method == "POST"]

    def _id(self, prefix: str) -> str:
        return f"{prefix}_{next(self._ids):04d}"

    def _page(self, items: list[dict[str, Any]], params: dict[str, str]) -> httpx.Response:
        if "after" in params:
            ids = [item["id"] for item in items]
            items = items[ids.index(params["after"]) + 1 :]
        page = items[: self.page_size]
        return httpx.Response(200, json={"data": page, "has_more": len(items) > len(page)})

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1")
        params = dict(request.url.params)
        body = json.loads(request.content) if request.content else None
        self.requests.append(Recorded(request.method, path, params, request.headers, body))
        failure = self.fail.get((request.method, path))
        if failure is not None:
            return failure
        parts = path.strip("/").split("/")
        match (request.method, parts):
            case ("GET", ["agents"]):
                return self._page(list(self.agents.values()), params)
            case ("POST", ["agents"]):
                agent = {"id": self._id("agent"), "object": "agent", **body}
                self.agents[agent["id"]] = agent
                return httpx.Response(200, json=agent)
            case ("DELETE", ["agents", agent_id]):
                self.agents.pop(agent_id)
                return httpx.Response(200, json={"id": agent_id, "deleted": True})
            case ("GET", ["agents", "environments", "templates"]):
                return self._page(list(self.templates.values()), params)
            case ("POST", ["agents", "environments", "templates"]):
                return self._idempotent(request, self.templates, "envtpl", body)
            case ("DELETE", ["agents", "environments", "templates", template_id]):
                self.templates.pop(template_id)
                return httpx.Response(200, json={"id": template_id, "deleted": True})
            case ("POST", ["agents", "environments"]):
                return self._idempotent(
                    request, self.environments, "env", {**body, "status": "pending"}
                )
            case ("GET", ["vaults"]):
                wanted = {
                    key.removeprefix("metadata[").removesuffix("]"): value
                    for key, value in params.items()
                    if key.startswith("metadata[")
                }
                matching = [
                    vault
                    for vault in self.vaults.values()
                    if all(vault["metadata"].get(key) == value for key, value in wanted.items())
                ]
                return self._page(matching, params)
            case ("POST", ["vaults"]):
                vault = {"id": self._id("vault"), "object": "vault", **body}
                self.vaults[vault["id"]] = vault
                self.credentials[vault["id"]] = {}
                return httpx.Response(200, json=vault)
            case ("DELETE", ["vaults", vault_id]):
                self.vaults.pop(vault_id)
                return httpx.Response(200, json={"id": vault_id, "deleted": True})
            case ("GET", ["vaults", vault_id, "credentials"]):
                listed = [
                    {**credential, "auth": _without_value(credential["auth"])}
                    for credential in self.credentials[vault_id].values()
                ]
                return self._page(listed, params)
            case ("POST", ["vaults", vault_id, "credentials"]):
                credential = {"id": self._id("credential"), "vault_id": vault_id, **body}
                self.credentials[vault_id][credential["id"]] = credential
                return httpx.Response(
                    200, json={**credential, "auth": _without_value(body["auth"])}
                )
        return httpx.Response(404, json={"error": {"code": "not_found"}})

    def _idempotent(
        self,
        request: httpx.Request,
        store: dict[str, dict[str, Any]],
        prefix: str,
        body: dict[str, Any],
    ) -> httpx.Response:
        key = request.headers.get("Idempotency-Key")
        if key is not None and key in self.idempotent:
            return httpx.Response(200, json=store[self.idempotent[key]])
        resource = {"id": self._id(prefix), **body}
        store[resource["id"]] = resource
        if key is not None:
            self.idempotent[key] = resource["id"]
        return httpx.Response(200, json=resource)


def _without_value(auth: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in auth.items() if key != "secret_value"}


def copy_pack(destination: Path) -> Path:
    """A writable copy of the shipped AI Engineer pack."""

    return Path(shutil.copytree(SHIPPED_PACK, destination / "codex_agents"))

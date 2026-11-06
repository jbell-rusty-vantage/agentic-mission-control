"""MO-13 FIXTURE: Cursor's `/v1/environments` and environment secrets behind `httpx.MockTransport`.

The shapes follow what the MO-13 drill observed on 2026-10-14 (research/cursor.md section 1.5):
`POST` answers `201` without the configuration, a taken name is `409
environment_name_conflict` with the existing `environmentId`, `GET` carries `versionId` but
not `environmentJson`, the configuration is the version-history entry with `current: true`,
`PATCH` answers `204` and adds an `updated` entry, secrets list `{id, name, type, repos}` and
an unknown secret deletes as `404 secret_not_found`. `dashboard_edit` changes a configuration
the way a person in the dashboard would. Values are kept only to assert what was written.
`kit_in_custody` publishes a kit whose base-layer bytes the lane reads back from custody.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pydantic import SecretStr
from tests.fixtures.environment_kits import kit_files, published_kit

from mission_control.adapters.capabilities.local_bundle_store import (
    FilesystemBundleFetcher,
    FilesystemBundleObjectStore,
)
from mission_control.adapters.cursor.environments import (
    CursorEnvironments,
    CursorEnvironmentsClient,
)
from mission_control.adapters.cursor.secrets import CursorSecretsClient
from mission_control.application.capabilities.bundle_custody import (
    BundleCustodyService,
    BundleMaterializer,
)
from mission_control.domain.authoring.contracts import PublishedDefinition
from mission_control.domain.capabilities.bundles import build_bundle_manifest

API_KEY = "cursor-test-key-not-real"


@dataclass
class FakeEnvironmentsApi:
    environments: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    secrets: dict[str, dict[str, str]] = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)
    # A repository the account's Git integration does not grant (`400 repository_access`).
    inaccessible: set[str] = field(default_factory=set)
    # Configurations the provider stores differently from what it was sent (read-back drift).
    rewrite: dict[str, str] = field(default_factory=dict)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def writes(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path in self.requests if method != "GET"]

    @staticmethod
    def _error(status: int, code: str, **extra: Any) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": code, "message": code, **extra}})

    def _version(self, environment_id: str, config: str, *, kind: str, source: str) -> None:
        for entry in self.history[environment_id]:
            entry["current"] = False
        self.history[environment_id].insert(
            0,
            {
                "id": str(uuid4()),
                "kind": kind,
                "source": source,
                "current": True,
                "environmentJson": self.rewrite.get(config, config),
            },
        )
        self.environments[environment_id]["versionId"] = str(uuid4())

    def dashboard_edit(self, environment_id: str, config: str) -> None:
        self._version(environment_id, config, kind="updated", source="dashboard")

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        self.requests.append((request.method, request.url.path))
        parts = request.url.path.strip("/").split("/")
        method = request.method
        if parts == ["v1", "environments"]:
            return self._create(request) if method == "POST" else self._list(request)
        environment_id = parts[2]
        environment = self.environments.get(environment_id)
        if environment is None:
            return self._error(404, "environment_not_found")
        rest = parts[3:]
        if not rest:
            if method == "GET":
                return httpx.Response(200, json=environment)
            if method == "PATCH":
                body = json.loads(request.content)
                self._version(environment_id, body["environmentJson"], kind="updated", source="api")
                return httpx.Response(204)
            if method == "DELETE":
                del self.environments[environment_id]
                return httpx.Response(200, json={"id": environment_id})
        if rest == ["history"]:
            return httpx.Response(200, json={"items": self.history[environment_id]})
        stored = self.secrets.setdefault(environment_id, {})
        if rest == ["secrets"]:
            items = [
                {"id": f"secv_{name}", "name": name, "type": "runtime_secret", "repos": []}
                for name in stored
            ]
            return httpx.Response(200, json={"items": items, "nextCursor": None})
        if rest[0] == "secrets" and len(rest) == 2:
            name = rest[1]
            if method == "PUT":
                body = json.loads(request.content)
                assert body["type"] == "runtime_secret"
                stored[name] = body["value"]
                return httpx.Response(201, json={"id": f"secv_{name}", "name": name})
            if method == "DELETE":
                if name not in stored:
                    return self._error(404, "secret_not_found")
                del stored[name]
                return httpx.Response(200, json={"name": name})
        return self._error(404, "route_not_found")

    def _create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        for existing in self.environments.values():
            if existing["name"] == body["name"] and existing["owner"] == body["owner"]:
                return self._error(409, "environment_name_conflict", environmentId=existing["id"])
        for repo in body["repos"]:
            if repo["url"] in self.inaccessible:
                return self._error(400, "repository_access")
        environment_id = str(uuid4())
        self.environments[environment_id] = {
            "id": environment_id,
            "name": body["name"],
            "owner": body["owner"],
            "repos": body["repos"],
        }
        self.history[environment_id] = []
        self._version(environment_id, body["environmentJson"], kind="created", source="api")
        created = {
            key: value
            for key, value in self.environments[environment_id].items()
            if key != "versionId"
        }
        return httpx.Response(201, json=created)

    def _list(self, request: httpx.Request) -> httpx.Response:
        items = [
            {key: value for key, value in item.items() if key != "versionId"}
            for item in self.environments.values()
        ]
        # One item per page, so the client's paging is exercised.
        start = int(request.url.params.get("cursor") or 0)
        page = items[start : start + 1]
        cursor = str(start + 1) if start + 1 < len(items) else None
        return httpx.Response(200, json={"items": page, "nextCursor": cursor})


def cursor_environments(api: FakeEnvironmentsApi) -> CursorEnvironments:
    transport = api.transport()
    return CursorEnvironments(
        CursorEnvironmentsClient(SecretStr(API_KEY), transport=transport),
        CursorSecretsClient(SecretStr(API_KEY), transport=transport),
    )


async def kit_in_custody(
    root: Path, document: dict[str, Any], *files: tuple[str, bytes]
) -> tuple[PublishedDefinition, BundleMaterializer]:
    """A published kit whose bundle bytes are in a filesystem custody store, and the
    materializer that reads them back verified (what `prepare` uses for the base layer)."""

    published = published_kit(document, *files)
    store = FilesystemBundleObjectStore(root)
    manifest = build_bundle_manifest(
        kit_files(document, *files),
        application_id="biotech",
        kind="environment_kit",
        capability_id=document["id"],
        version=document["version"],
    )
    await BundleCustodyService(store=store).upload(manifest, kit_files(document, *files))
    return published, BundleMaterializer(store, FilesystemBundleFetcher(store))

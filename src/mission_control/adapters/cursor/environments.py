"""Cursor cloud environments: the `/v1/environments` REST adapter and the rendered base layer
(SPEC-01 section 7; research/cursor.md sections 1.1-1.5; MO-13).

`CursorEnvironmentsClient` covers create, list, get, update (`PATCH`, a whole-config replace),
delete and the version history. Shapes observed on 2026-10-14 (MO-13 drill, recorded in
research/cursor.md section 1.5):

- `POST` answers `201 {id, name, owner, repos, createdAt, updatedAt}`; a taken name is
  `409 environment_name_conflict` carrying the existing `environmentId`; a repository the
  account's Git integration does not grant is `400 repository_access`;
- `GET /v1/environments/{id}` carries `versionId` and `repos` (`[{url}]`) but **not**
  `environmentJson`; the current configuration is the history entry with `current: true`
  (`environmentJson` verbatim, `source` `api`/`dashboard`/...), so a read-back is `GET` plus
  `GET .../history`;
- `PATCH` answers `204` and adds an `updated` history entry; `DELETE` answers `200 {id}`; an
  unknown id is `404 environment_not_found`.

`CursorEnvironments` is the application's `ProviderEnvironmentApi` over the client and the
environment secrets of `CursorSecretsClient`. `render_environment_json` renders a kit's base
layer as the `environmentJson` Mission Control owns: the kit marker as `name`, the kit's base
install script as `install`, the bootstrap entrypoint as `start`, the projected egress fields,
and `agentCanUpdateSnapshot: false` so no agent rewrites the shared base. Messages never carry
the API key, a configuration or provider prose.

`CursorEnvironmentProvisioner` is the `cursor_cloud` lane's environment step at `prepare`: it
checks the committed `.cursor/environment.json` on the repository's default branch (the one
Cursor's Builds use) against the kit's rendering, applies the binding's strategy (a synced
environment covers the target repository, whose URL is part of its name) and renders the kit's
mission layer for the run branch. A launch never names the environment: Cursor refuses
`env.name` together with `repos` (`400 validation_error`, MO-13 drill), and the agent must
start on the run branch, so Cursor resolves the environment from the repository (its committed
file, then the repository's saved environments). Every refusal on the way (the provider's, a
missing secret, a kit whose bytes are not in custody) is a `ProviderEnvironmentRefused`.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal
from urllib.parse import quote

import httpx
from pydantic import JsonValue, SecretStr

from mission_control.adapters.cursor.cloud_api import CLOUD_API_BASE, api_client
from mission_control.adapters.cursor.projection import network_projection
from mission_control.adapters.cursor.secrets import (
    CursorEnvironmentSecrets,
    CursorSecretRefused,
    CursorSecretsClient,
)
from mission_control.adapters.remote_session.errors import ErrorRule, error_code, raise_for_response
from mission_control.application.capabilities.bundle_custody import BundleCustodyUnavailable
from mission_control.application.capabilities.catalog import CapabilityNotFound
from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.environments.provider_environments import (
    PROVIDER_ENVIRONMENT_REFUSED,
    AppliedEnvironment,
    ProviderEnvironment,
    ProviderEnvironmentExists,
    ProviderEnvironmentRefused,
    ProviderEnvironmentService,
    check_environment_file,
    config_digest,
    environment_file_marker,
    kit_marker,
)
from mission_control.application.secrets.broker import SecretUnavailable
from mission_control.application.secrets.delivery import ProviderHeldSecretMissing
from mission_control.domain.authoring.contracts import EnvironmentKitDefinition
from mission_control.domain.authoring.environment_kits import (
    EnvironmentKitManifest,
    RenderedMissionLayer,
    entrypoint_command,
    render_mission_layer,
)
from mission_control.domain.capabilities.bundles import CapabilityDrift
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.lanes import CursorExecutionBinding

# The committed file Cursor resolves before any saved environment (research/cursor.md 1.2).
ENVIRONMENT_FILE: Final = ".cursor/environment.json"
LIST_PAGE_LIMIT: Final = 50
EnvironmentOwner = Literal["personal", "team"]


class CursorEnvironmentRefused(ValueError):
    """Cursor refused an environment request (access, validation or key type)."""


class CursorEnvironmentNotFound(CursorEnvironmentRefused, LookupError):
    """`404`: no environment has this id."""


# What can refuse a provisioning after the preflight: the provider (an environment or secret
# request), the Secret Broker (a required declaration without a value) and bundle custody (the
# kit's base install bytes).
_PROVISIONING_REFUSALS: Final = (
    CursorEnvironmentRefused,
    CursorSecretRefused,
    SecretUnavailable,
    ProviderHeldSecretMissing,
    BundleCustodyUnavailable,
    CapabilityNotFound,
    CapabilityDrift,
)


ENVIRONMENTS_ERRORS: Final[tuple[ErrorRule, ...]] = (
    ErrorRule(
        400,
        CursorEnvironmentRefused,
        "a repository is not accessible to the account's Git integration",
        code="repository_access",
    ),
    ErrorRule(
        400,
        CursorEnvironmentRefused,
        "the provider refused the environment configuration",
        code="validation_error",
    ),
    ErrorRule(403, CursorEnvironmentRefused, "this key cannot manage environments"),
    ErrorRule(404, CursorEnvironmentNotFound, "the environment does not exist"),
)


def _raise(response: httpx.Response, operation: str) -> None:
    raise_for_response(response, operation, ENVIRONMENTS_ERRORS, fallback=CursorEnvironmentRefused)


def _path(environment_id: str, *rest: str) -> str:
    return "/".join(("/v1/environments", quote(environment_id, safe=""), *rest))


class EnvironmentNameConflict(CursorEnvironmentRefused):
    """`409 environment_name_conflict`: the owner already has an environment by that name."""

    def __init__(self, environment_id: str) -> None:
        super().__init__("create environment: an environment with this name exists")
        self.environment_id = environment_id


class CursorEnvironmentsClient:
    """The environments endpoints of the Cursor API (an HTTP fake in tests)."""

    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = CLOUD_API_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 30,
    ) -> None:
        self._client = api_client(
            api_key, base_url=base_url, transport=transport, timeout=timeout_s
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create(
        self,
        *,
        name: str,
        environment_json: str,
        owner: EnvironmentOwner = "personal",
        repositories: Sequence[str] = (),
    ) -> dict[str, Any]:
        response = await self._client.post(
            "/v1/environments",
            json={
                "owner": owner,
                "name": name,
                "repos": [{"url": url} for url in repositories],
                "environmentJson": environment_json,
            },
        )
        if response.status_code == 409 and error_code(response) == "environment_name_conflict":
            error = response.json().get("error") or {}
            raise EnvironmentNameConflict(str(error.get("environmentId") or ""))
        _raise(response, "create environment")
        result: dict[str, Any] = response.json()
        return result

    async def list_environments(self) -> list[dict[str, Any]]:
        """Every environment the key can see, across pages (`nextCursor`)."""

        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, str | int] = {"limit": LIST_PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            response = await self._client.get("/v1/environments", params=params)
            _raise(response, "list environments")
            body = response.json()
            items += [dict(item) for item in body.get("items") or () if isinstance(item, Mapping)]
            cursor = body.get("nextCursor")
            if not cursor:
                return items

    async def get(self, environment_id: str) -> dict[str, Any]:
        response = await self._client.get(_path(environment_id))
        _raise(response, "get environment")
        result: dict[str, Any] = response.json()
        return result

    async def history(self, environment_id: str) -> list[dict[str, Any]]:
        response = await self._client.get(_path(environment_id, "history"))
        _raise(response, "environment history")
        return [
            dict(item) for item in response.json().get("items") or () if isinstance(item, Mapping)
        ]

    async def update(self, environment_id: str, *, environment_json: str) -> None:
        response = await self._client.patch(
            _path(environment_id), json={"environmentJson": environment_json}
        )
        _raise(response, "update environment")

    async def delete(self, environment_id: str) -> None:
        response = await self._client.delete(_path(environment_id))
        _raise(response, "delete environment")


class CursorEnvironments:
    """`ProviderEnvironmentApi` over Cursor's environments and environment secrets."""

    def __init__(
        self,
        client: CursorEnvironmentsClient,
        secrets: CursorSecretsClient,
        *,
        owner: EnvironmentOwner = "personal",
    ) -> None:
        self._client = client
        self._secrets = secrets
        self._owner = owner

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._secrets.aclose()

    async def create(
        self, name: str, config: str, *, repositories: Sequence[str]
    ) -> ProviderEnvironment:
        try:
            created = await self._client.create(
                name=name, environment_json=config, owner=self._owner, repositories=repositories
            )
        except EnvironmentNameConflict as conflict:
            raise ProviderEnvironmentExists(conflict.environment_id) from conflict
        except CursorEnvironmentRefused as error:
            raise ProviderEnvironmentRefused(PROVIDER_ENVIRONMENT_REFUSED, str(error)) from error
        return await self.read(str(created["id"]))

    async def read(self, environment_id: str) -> ProviderEnvironment:
        """The environment and its current version, read back from the version history."""

        environment = await self._client.get(environment_id)
        current = next(
            (item for item in await self._client.history(environment_id) if item.get("current")),
            {},
        )
        config = current.get("environmentJson")
        repos = environment.get("repos")
        return ProviderEnvironment(
            environment_id=str(environment["id"]),
            name=str(environment.get("name") or ""),
            version_id=environment.get("versionId"),
            config=config if isinstance(config, str) else None,
            source=current.get("source"),
            repositories=(
                tuple(
                    str(repo["url"])
                    for repo in repos
                    if isinstance(repo, Mapping) and repo.get("url")
                )
                if isinstance(repos, list)
                else None
            ),
        )

    async def find(self, name: str) -> ProviderEnvironment | None:
        for item in await self._client.list_environments():
            if item.get("name") == name:
                return await self.read(str(item["id"]))
        return None

    async def replace(self, environment_id: str, config: str) -> ProviderEnvironment:
        await self._client.update(environment_id, environment_json=config)
        return await self.read(environment_id)

    def secrets(self, environment_id: str) -> CursorEnvironmentSecrets:
        return CursorEnvironmentSecrets(self._secrets, environment_id)


def render_environment_json(
    kit: EnvironmentKitManifest,
    *,
    install: bytes | None,
    egress: Mapping[str, JsonValue] | None = None,
) -> str:
    """The `environmentJson` of a kit's synced environment: deterministic, so one kit and
    policy always render (and name) the same environment. `install` is the kit's base install
    script (its bundle bytes), run through `bash -c` at Build time; `start` is the bootstrap
    entrypoint, which runs the mission branch's `.mission/setup/run` when it carries one."""

    if kit.base.services:
        raise ProviderEnvironmentRefused(
            PROVIDER_ENVIRONMENT_REFUSED,
            f"{kit.id} declares base services, which a synced Cursor environment does not run",
        )
    config: dict[str, JsonValue] = {
        "name": kit_marker(kit.id, kit.version),
        "start": entrypoint_command(LaneProfile.CURSOR_CLOUD),
        "agentCanUpdateSnapshot": False,
        **(egress or {}),
    }
    if install is not None:
        config["install"] = "bash -c " + shlex.quote(install.decode("utf-8"))
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ProvisionedEnvironment:
    """The environment a `cursor_cloud` agent will run in, and the mission-layer files the run
    branch carries for its bootstrap entrypoint."""

    applied: AppliedEnvironment
    mission_layer: RenderedMissionLayer | None = None

    def files(self) -> list[tuple[str, bytes]]:
        if self.mission_layer is None:
            return []
        return [(path, text.encode("utf-8")) for path, text in self.mission_layer.files.items()]

    def digests(self) -> dict[str, str]:
        """What the prepared session records beside its projection digests: the mission
        layer's script and the configuration the agent's environment carries, under
        `provider_environment_digest` for the synced or bound environment as read back, else
        `provider_environment_file_digest` for the committed file (one digest scheme)."""

        digests: dict[str, str] = {}
        if self.mission_layer is not None:
            digests["setup_digest"] = self.mission_layer.setup_digest
        environment = self.applied.environment
        if environment is not None and environment.config_digest is not None:
            digests["provider_environment_digest"] = environment.config_digest
        elif self.applied.file.digest is not None:
            digests["provider_environment_file_digest"] = self.applied.file.digest
        return digests


class CursorEnvironmentProvisioner:
    """The `cursor_cloud` lane's provider environment step (SPEC-01 section 7)."""

    def __init__(self, service: ProviderEnvironmentService, kits: EnvironmentKitCatalog) -> None:
        self._service = service
        self._kits = kits

    async def provision(
        self, binding: CursorExecutionBinding, committed: bytes | None
    ) -> ProvisionedEnvironment:
        """Apply the binding's strategy against `committed` (the repository's
        `.cursor/environment.json` on its default branch, None when absent)."""

        try:
            return await self._provision(binding, committed)
        except _PROVISIONING_REFUSALS as error:
            raise ProviderEnvironmentRefused(PROVIDER_ENVIRONMENT_REFUSED, str(error)) from error

    async def _provision(
        self, binding: CursorExecutionBinding, committed: bytes | None
    ) -> ProvisionedEnvironment:
        assert binding.cloud is not None and binding.cloud.provider_environment is not None
        options = binding.cloud.provider_environment
        definition = await self._kit(options.kit_pin)
        marker = (
            None if definition is None else kit_marker(definition.kit.id, definition.kit.version)
        )
        # The kit's rendering: what `sync` provisions when no file is committed, and what a
        # committed file carrying the kit's marker must equal to be mc-owned.
        config: str | None = None
        if definition is not None and (
            environment_file_marker(committed) == marker
            or (options.strategy == "sync" and committed is None)
        ):
            config = await self._config(binding, definition)
        file = check_environment_file(
            ENVIRONMENT_FILE,
            committed,
            expected_marker=marker,
            expected_digest=None if config is None else config_digest(config),
        )
        applied = await self._service.apply(
            strategy=options.strategy,
            file=file,
            ref=options.ref,
            kit_id=None if definition is None else definition.kit.id,
            config=config,
            secret_refs=options.secret_refs,
            repositories=tuple(url for url in (binding.workspace.repo_url,) if url),
        )
        layer = (
            None
            if definition is None or options.kit_pin is None
            else render_mission_layer(definition.kit, pin=options.kit_pin)
        )
        return ProvisionedEnvironment(applied, layer)

    async def _kit(self, pin: str | None) -> EnvironmentKitDefinition | None:
        if pin is None:
            return None
        definition = await self._kits.resolve(pin)
        if definition is None:
            raise ProviderEnvironmentRefused(
                PROVIDER_ENVIRONMENT_REFUSED, f"environment kit {pin} is not published"
            )
        return definition

    async def _config(
        self, binding: CursorExecutionBinding, definition: EnvironmentKitDefinition
    ) -> str:
        network = network_projection(binding)
        return render_environment_json(
            definition.kit,
            install=await self._kits.base_install(definition),
            egress=None if network is None else network.settings,
        )


__all__ = [
    "ENVIRONMENTS_ERRORS",
    "ENVIRONMENT_FILE",
    "CursorEnvironmentNotFound",
    "CursorEnvironmentProvisioner",
    "CursorEnvironmentRefused",
    "CursorEnvironments",
    "CursorEnvironmentsClient",
    "EnvironmentNameConflict",
    "EnvironmentOwner",
    "ProvisionedEnvironment",
    "render_environment_json",
]

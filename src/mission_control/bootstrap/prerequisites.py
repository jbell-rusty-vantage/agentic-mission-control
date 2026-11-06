"""Compose trusted owner verification using installation configuration and restricted pools."""

from contextlib import AsyncExitStack

import asyncpg

from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.prerequisites import PostgresOwnerPrerequisiteRepository
from mission_control.adapters.prerequisites.probes import ProviderOwnerProbeExecutor
from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindings
from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.application.prerequisites.oauth import CatalogOAuthRequirements
from mission_control.application.prerequisites.preflight import (
    BoundLocalPrerequisiteIdentity,
    PrerequisitePreflight,
)
from mission_control.application.prerequisites.probes import (
    ConfiguredOwnerProbes,
    OwnerProbeConfiguration,
)
from mission_control.application.prerequisites.setup import ProbeResult, ProbeUnavailable
from mission_control.bootstrap.bundle_custody import compose_bundle_materializer
from mission_control.bootstrap.common_installation import inspect_common_installation
from mission_control.bootstrap.settings import Settings
from mission_control.bootstrap.signals import configured_network_hosts
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord


class InstallationOwnerProbes:
    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None:
        self._settings, self._pool = settings, pool

    async def verify(self, request_scope: str, record: OwnerPrerequisiteRecord) -> ProbeResult:
        # Re-read reviewed bindings and secret sources on each request; stale setup cannot
        # reuse an old definition. The same broker factory supplies the actual worker lanes.
        from mission_control.adapters.temporal.deployment_composition import compose_secret_broker

        try:
            path = self._settings.mission_control_owner_probes_path
            configuration = (
                OwnerProbeConfiguration.load(path) if path else OwnerProbeConfiguration()
            )
            async with AsyncExitStack() as resources:
                broker = await compose_secret_broker(self._settings, resources, self._pool)
                probes = ConfiguredOwnerProbes(
                    configuration, ProviderOwnerProbeExecutor(broker, self._pool)
                )
                return await probes.verify(request_scope, record)
        except ProbeUnavailable:
            raise
        except Exception as error:
            raise ProbeUnavailable(
                f"trusted probe configuration unavailable ({type(error).__name__})"
            ) from None


class FreshInstallationCheck:
    def __init__(self, pool: asyncpg.Pool, binding: ApplicationBinding | None):
        self._pool, self._binding = pool, binding

    async def __call__(self) -> tuple[str, ...]:
        if self._binding is None:
            return ("installer readiness needs the trusted application deployment binding",)
        try:
            await inspect_common_installation(self._pool, self._binding)
        except Exception as error:
            return (f"fresh installer readiness failed ({type(error).__name__})",)
        return ()


def compose_prerequisite_preflight(
    pool: asyncpg.Pool,
    *,
    binding: ApplicationBinding | None,
    settings: Settings | None = None,
) -> PrerequisitePreflight:
    """One complete guard for API, worker chain relays and trusted direct launchers."""
    bundles = compose_bundle_materializer(settings) if settings else None
    bindings = (
        ManifestLaunchBindings.load(settings.manifest_launch_bindings_path)
        if settings and settings.manifest_launch_bindings_path
        else None
    )
    repository = bindings.knowledge_workspace_repository if bindings else None
    scope = f"mc/{binding.installation_id}/{binding.application_id}/catalog" if binding else ""
    if settings and settings.mission_control_catalog_scope:
        scope = settings.mission_control_catalog_scope
    seed_urls: frozenset[str] = frozenset()
    managed = (
        getattr(bindings.providers, "claude_managed", None)
        if bindings and bindings.providers
        else None
    )
    projection = getattr(managed, "hosted_projection", None)
    if isinstance(projection, dict):
        seed_urls = frozenset(
            item["url"] for item in projection.get("agent", {}).get("mcp_servers", [])
        )
    return PrerequisitePreflight(
        PostgresOwnerPrerequisiteRepository(pool),
        kits=EnvironmentKitCatalog(
            PostgresDefinitionRepository(pool, catalog_scope=scope), bundles=bundles
        ),
        bundles=bundles,
        network_hosts=configured_network_hosts(settings),
        installation_check=FreshInstallationCheck(pool, binding),
        knowledge_repository=repository.model_dump(mode="json") if repository else None,
        oauth_requirements=CatalogOAuthRequirements(
            PostgresDefinitionRepository(pool, catalog_scope=scope), seed_urls=seed_urls
        ),
        native_identity=BoundLocalPrerequisiteIdentity(bindings) if bindings else None,
    )

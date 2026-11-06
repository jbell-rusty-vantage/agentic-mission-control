"""Environment Kits read from the catalog, and the compile-time environment inputs (ADR-0042).

A manifest pins a kit exactly (``envkit.<name>@<version>#sha256:<definition digest>``, the
catalog's Capability Pin), so a kit resolves to exactly one published ``environment_kit`` row
or to nothing. With bundle custody composed, the catalog also reads a kit's base install
script, verified against its pin, for the provider environment Mission Control syncs (MO-13).
:class:`CatalogEnvironmentInputs` is the production ``EnvironmentInputsPort`` of
``ManifestCompileService``: it reads a kit's ``requires`` and the installation's configuration
values offline, without contacting a provider.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.application.capabilities.catalog import (
    CapabilityNotFound,
    bundle_files,
    find_published_by_pin,
)
from mission_control.domain.authoring.contracts import (
    EnvironmentKitDefinition,
    PublishedDefinition,
)
from mission_control.domain.authoring.mission_environment import KitRequirements
from mission_control.domain.capabilities.bundles import normalize_bundle_path
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.capabilities.pins import CapabilityPin, CapabilityPinError


class PublishedDefinitionsPort(Protocol):
    async def list_published_definitions(self) -> tuple[PublishedDefinition, ...]: ...


class EnvironmentKitCatalog:
    """Exact-pin lookup of published Environment Kits; a retired row never resolves."""

    def __init__(
        self, definitions: PublishedDefinitionsPort, *, bundles: BundleMaterializer | None = None
    ) -> None:
        self._definitions = definitions
        self._bundles = bundles

    async def resolve(self, pin: str) -> EnvironmentKitDefinition | None:
        try:
            parsed = CapabilityPin.parse(pin)
        except CapabilityPinError:
            return None
        published = await find_published_by_pin(self._definitions, parsed)
        if (
            published is None
            or published.retired_at is not None
            or capability_pin(published) != parsed
            or not isinstance(published.definition, EnvironmentKitDefinition)
        ):
            return None
        return published.definition

    async def base_install(self, definition: EnvironmentKitDefinition) -> bytes | None:
        """The kit's base install script from custody (None when the kit declares none);
        without bundle custody composed this raises ``BundleCustodyUnavailable``, and a
        bundle without the declared script ``CapabilityNotFound``."""

        path = definition.kit.base.install
        if path is None:
            return None
        files = {item.path: item.content for item in await bundle_files(definition, self._bundles)}
        content = files.get(normalize_bundle_path(path))
        if content is None:
            raise CapabilityNotFound(f"{definition.logical_id} bundle carries no {path}")
        return content


class CatalogEnvironmentInputs:
    """``EnvironmentInputsPort`` over the catalog and installation configuration.

    ``config`` holds the installation's non-secret configuration values that ``value_ref:
    config:<key>`` names; a key outside it is unresolved, which compile reports as a blocker.
    """

    def __init__(
        self, kits: EnvironmentKitCatalog, config: Mapping[str, str] | None = None
    ) -> None:
        self._kits = kits
        self._config = dict(config or {})

    async def kit_requirements(self, pin: str) -> KitRequirements | None:
        kit = await self._kits.resolve(pin)
        return None if kit is None else kit.kit.requires

    async def config_value(self, key: str) -> str | None:
        return self._config.get(key)


__all__ = [
    "CatalogEnvironmentInputs",
    "EnvironmentKitCatalog",
    "PublishedDefinitionsPort",
]

"""Environment Kit test support (MO-12): kit rows as the catalog publishes them, and a
mission-layer service over an in-memory catalog and the real bash runner."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from typing import Any

from mission_control.adapters.workspaces.mission_setup import BashMissionSetupRunner
from mission_control.application.capabilities.bundle_custody import bundle_definition
from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.environments.mission_layer import MissionLayerService
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    DefinitionLifecycleStatus,
    EnvironmentKitDefinition,
    ExactDefinitionRef,
    PublishedDefinition,
)
from mission_control.domain.capabilities.bundles import build_bundle_manifest
from mission_control.domain.capabilities.catalog_entry import capability_pin

BASH = shutil.which("bash")
PUBLISHED_AT = datetime(2026, 10, 13, tzinfo=UTC)


def kit_document(**changes: Any) -> dict[str, Any]:
    """A small kit whose mission layer needs only bash and coreutils."""

    document: dict[str, Any] = {
        "schema_version": "mc.environment_kit.v1",
        "id": "envkit.fixture",
        "version": "1",
        "title": "Fixture kit",
        "description": "Writes a marker file and checks it (FIXTURE).",
        "mission": {
            "steps": [
                {
                    "name": "marker",
                    "run": "echo ready > marker.txt",
                    "when": "!exists('marker.txt')",
                },
                {"name": "lockfile", "run": "exit 7", "when": "exists('never.lock')"},
            ],
            "health": [{"name": "marker", "run": "test -f marker.txt"}],
            "timeout_s": 60,
        },
        "requires": {"secrets": ["FIXTURE_SETUP_TOKEN?"], "egress": ["pypi.org"]},
        "host_support": {"local": "full", "cursor_cloud": "full", "claude_cloud": "base_via_owner"},
    }
    document.update(changes)
    return document


def kit_files(document: dict[str, Any], *extra: tuple[str, bytes]) -> list[tuple[str, bytes]]:
    return [("kit.json", json.dumps(document).encode("utf-8")), *extra]


def published_kit(
    document: dict[str, Any] | None = None,
    *extra: tuple[str, bytes],
    application_id: str = "biotech",
    retired: bool = False,
) -> PublishedDefinition:
    """The catalog row a kit bundle publishes as (revision 1, exact digest)."""

    document = document or kit_document()
    files = kit_files(document, *extra)
    manifest = build_bundle_manifest(
        files,
        application_id=application_id,
        kind="environment_kit",
        capability_id=document["id"],
        version=document["version"],
    )
    definition = bundle_definition(manifest, files, {})
    assert isinstance(definition, EnvironmentKitDefinition)
    return PublishedDefinition(
        ref=ExactDefinitionRef(
            kind=definition.kind,
            logical_id=definition.logical_id,
            revision=1,
            digest=sha256_digest(definition),
            lifecycle_status=(
                DefinitionLifecycleStatus.RETIRED
                if retired
                else DefinitionLifecycleStatus.PUBLISHED
            ),
        ),
        definition=definition,
        published_at=PUBLISHED_AT,
        published_by="fixture:environment-kits",
        retired_at=PUBLISHED_AT if retired else None,
    )


def kit_pin(published: PublishedDefinition) -> str:
    return capability_pin(published).render()


class StaticDefinitions:
    """FIXTURE catalog: the published rows given, listed as the repository lists them."""

    def __init__(self, *published: PublishedDefinition) -> None:
        self._published = published

    async def list_published_definitions(self) -> tuple[PublishedDefinition, ...]:
        return self._published


def mission_layer_service(*published: PublishedDefinition) -> MissionLayerService:
    return MissionLayerService(
        EnvironmentKitCatalog(StaticDefinitions(*published)), BashMissionSetupRunner()
    )


def setup_environ(**extra: str) -> dict[str, str]:
    """The worker environment a setup child inherits from: the host's PATH and platform
    names only (bash and coreutils must resolve), plus ``extra``."""

    names = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "HOME", "USERPROFILE")
    environ = {name: os.environ[name] for name in names if name in os.environ}
    environ.update(extra)
    return environ


__all__ = [
    "BASH",
    "StaticDefinitions",
    "kit_document",
    "kit_files",
    "kit_pin",
    "mission_layer_service",
    "published_kit",
    "setup_environ",
]

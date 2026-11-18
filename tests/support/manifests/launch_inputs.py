"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_manifest_launch_inputs.py.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    ManifestLaunchBindings,
    ManifestLaunchResolver,
    ServedComponents,
)
from mission_control.application.authoring.manifest_service import (
    CompiledMission,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.mission_definition import MissionDefinition
from tests.fixtures.applications import installed_applications
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.models import bindings_catalog
from tests.support.ids import canonical_scope
from tests.unit.authoring.manifest_launch_fixture import (
    deep_agents_chain,
    fixture_bindings,
    fixture_served,
    pubmed_bound,
)

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"
MISSION_2 = (
    ROOT / "tests/fixtures/manifests/fast-track/02-research-ingestion-cursor-cloud-chain.yml"
)


SCOPE = canonical_scope("tenant-1")
SECRETS = {"openai": "OPENAI_API_KEY"}


async def compile_programs(
    manifest_yaml: str, scope: str = SCOPE
) -> tuple[list[MissionDefinition], list[Any]]:
    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    compilation = await service.compile(
        manifest_yaml,
        ManifestScope(request_scope=scope, actor_id="owner", at=datetime(2026, 10, 8, tzinfo=UTC)),
    )
    assert compilation.ok, [item.message for item in compilation.report.blockers]
    return list(compilation.definitions), list(compilation.programs)


def admitted(
    program: CompiledMission, run_id: str = "run-mp02", scope: str = SCOPE
) -> AdmittedLaunch:
    return AdmittedLaunch.from_configuration(scope, run_id, program.configuration)


def resolver(
    bindings: ManifestLaunchBindings | None = None,
    *,
    served: ServedComponents | None = None,
    secrets: dict[str, str] | None = None,
) -> ManifestLaunchResolver:
    bindings = bindings or fixture_bindings()
    return compose_manifest_launch_resolver(
        bindings,
        served or fixture_served(bindings),
        applications=installed_applications(),
        models=bindings_catalog(bindings),
        provider_secret_env=SECRETS if secrets is None else secrets,
    )


def served_with_mcp(bindings: ManifestLaunchBindings) -> ServedComponents:
    """FIXTURE served set: the fixture components plus the bound MCP servers."""

    servers = {
        item.mcp_server.ref.digest
        for item in bindings.capabilities.values()
        if item.mcp_server is not None
    }
    return replace(fixture_served(bindings), mcp_servers=frozenset(servers))


def pubmed_resolver(
    definition: MissionDefinition,
    bindings: ManifestLaunchBindings | None = None,
    *,
    served: ServedComponents | None = None,
    secrets: dict[str, str] | None = None,
) -> ManifestLaunchResolver:
    bound = pubmed_bound(bindings or fixture_bindings(), pubmed_digest(definition))
    if served is not None:
        served = replace(served, mcp_servers=served_with_mcp(bound).mcp_servers)
    return resolver(bound, served=served or served_with_mcp(bound), secrets=secrets)


@pytest.fixture(scope="module")
def chain() -> tuple[list[MissionDefinition], list[CompiledMission]]:
    return asyncio.run(compile_programs(deep_agents_chain(MISSION_2.read_text(encoding="utf-8"))))


def pubmed_digest(definition: MissionDefinition) -> str:
    (capability,) = [item for item in definition.capabilities if item.alias == "pubmed"]
    assert capability.resolved is not None and capability.resolved.digest is not None
    return capability.resolved.digest

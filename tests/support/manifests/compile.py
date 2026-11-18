"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_manifest_compile.py.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.application.authoring.manifest_service import (
    ManifestCompilation,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
    MissionManifestService,
)
from mission_control.application.capabilities.capability_search import (
    CapabilitySearchResponse,
    CapabilitySearchService,
)
from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.coordinator.contracts import CapabilitySearchRequest
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from mission_control.interfaces.http.missions import router
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.fixtures.provider_frames import INSTALLATION, TENANT

ROOT = Path(__file__).resolve().parents[3]


MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"
AT = datetime(2026, 10, 8, 12, tzinfo=UTC)


class RecordingSearch:
    """The real search service, with every request recorded."""

    def __init__(self, inner: CapabilitySearchService) -> None:
        self.inner = inner
        self.requests: list[CapabilitySearchRequest] = []

    async def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResponse:
        self.requests.append(request)
        return await self.inner.search(request)

    def max_fused_score(self, mode: Any) -> float:
        return self.inner.max_fused_score(mode)


async def service(
    mutate: Callable[[InMemoryDefinitionRepository], Any] | None = None,
) -> tuple[ManifestCompileService, InMemoryDefinitionRepository, RecordingSearch]:
    definitions, search = await fast_track_catalog()
    if mutate is not None:
        await mutate(definitions)
    recording = RecordingSearch(search)
    compile_service = ManifestCompileService(
        definitions=definitions,
        search=recording,  # type: ignore[arg-type]
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    return compile_service, definitions, recording


def scope(application: str = "biotech") -> ManifestScope:
    return ManifestScope(
        request_scope=canonical_scope("tenant-1", application), actor_id="owner", at=AT
    )


def minimal() -> dict[str, Any]:
    return load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))


def text(document: dict[str, Any]) -> str:
    return canonical_manifest_bytes(document).decode("utf-8")


def reasons(compilation: ManifestCompilation, *, warnings: bool = False) -> set[tuple[str, str]]:
    issues = compilation.report.warnings if warnings else compilation.report.blockers
    return {(issue.pointer, issue.reason or "") for issue in issues}


def http_app(manifests: MissionManifestService, permissions: frozenset[str]) -> FastAPI:
    registry = ApplicationRegistry(
        (
            ApplicationBinding.seal(
                application_id="biotech",
                installation_id=INSTALLATION,
                binding_version="1",
                supabase_project_ref="project",
                database_secret_ref="TEST_DATABASE_URL",
                accepted_issuers={"https://issuer.invalid"},
                accepted_audiences={"authenticated"},
                required_component_version="1",
            ),
        )
    )
    registry.observe(
        "biotech", InstallationObservation(INSTALLATION, "biotech", "project", frozenset({"1"}))
    )
    app = FastAPI()
    app.include_router(router)
    app.state.mission_control_registry = registry
    app.state.mission_control_manifest_services = {(INSTALLATION, "biotech", TENANT): manifests}
    app.dependency_overrides[get_mission_principal] = lambda: MissionPrincipal(
        installation_id=INSTALLATION,
        application_id="biotech",
        tenant_id=TENANT,
        issuer="https://issuer.invalid",
        audiences=frozenset({"authenticated"}),
        actor=ActorContext(actor_id="owner", permissions=permissions),
    )
    return app

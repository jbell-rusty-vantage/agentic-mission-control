"""OVE-204 slice 6: compile mounts the application's knowledge charter on knowledge missions.

The Application Profile names one charter skill (`[knowledge] charter_skill`); a mission that
resolves a knowledge capability (the knowledge cognition plugins or a knowledge tool other than
`submit_output`) takes that skill's latest admitted row, provenance `application:charter`,
through the ordinary pin resolution, dedupe and conflict checks. The catalog is the seeded fixture
catalog, which carries the agent-skill seed 1.0.4 charter rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    CHARTER_PROVENANCE,
    ManifestCompilation,
    ManifestCompileService,
    ManifestProgramCompiler,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import load_manifest_yaml
from mission_control.domain.capabilities.catalog_entry import capability_pin
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.unit.authoring.test_manifest_compile import minimal, scope, text

ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE = ROOT / "tests/fixtures/manifests/knowledge-tools-stage-graph.yml"
CHARTERS = {
    "biotech": "skill.biotech-knowledge-charter",
    "ai-engineer": "skill.ai-engineer-knowledge-charter",
}


async def _service(
    charters: dict[str, str] | None = CHARTERS,
) -> tuple[ManifestCompileService, Any]:
    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
        charter_skills=charters,
    )
    return service, definitions


def _knowledge(application: str = "ai-engineer") -> dict[str, Any]:
    document = load_manifest_yaml(KNOWLEDGE.read_text(encoding="utf-8"))
    document["mission"]["application"] = application
    return document


def _charters(compilation: ManifestCompilation) -> list[Any]:
    assert compilation.resolution is not None
    return [
        item
        for item in compilation.resolution.resolved
        if item.result is not None and item.result.capability_id in set(CHARTERS.values())
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("application", ["ai-engineer", "biotech"])
async def test_a_knowledge_mission_mounts_its_application_charter(application: str) -> None:
    service, definitions = await _service()
    compilation = await service.compile(text(_knowledge(application)), scope(application))

    assert compilation.ok, compilation.report.blockers
    (charter,) = _charters(compilation)
    assert charter.provenance == CHARTER_PROVENANCE
    assert charter.role == "skill"
    assert charter.pointer == "/mission/application"
    assert charter.request == {"kind": "skill", "pin": f"{CHARTERS[application]}@latest"}
    rows = [
        item
        for item in await definitions.list_published_definitions()
        if item.ref.logical_id == CHARTERS[application]
    ]
    latest = max(rows, key=lambda item: item.ref.revision)
    assert charter.result is not None
    assert charter.result.pin == capability_pin(latest).render()
    assert charter.result.version == "0.1.0"


@pytest.mark.asyncio
async def test_a_mission_without_knowledge_capabilities_mounts_no_charter() -> None:
    service, _ = await _service()
    compilation = await service.compile(text(minimal()), scope("biotech"))

    assert compilation.resolution is not None
    assert _charters(compilation) == []


@pytest.mark.asyncio
async def test_a_service_without_profiles_mounts_no_charter() -> None:
    service, _ = await _service(None)
    compilation = await service.compile(text(_knowledge()), scope("ai-engineer"))

    assert compilation.ok, compilation.report.blockers
    assert _charters(compilation) == []


@pytest.mark.asyncio
async def test_an_authored_charter_pin_is_kept_and_not_mounted_twice() -> None:
    service, _ = await _service()
    document = _knowledge()
    document["mission"]["environment"]["capabilities"].append(
        {"pin": f"{CHARTERS['ai-engineer']}@latest", "as": "charter"}
    )
    compilation = await service.compile(text(document), scope("ai-engineer"))

    assert compilation.ok, compilation.report.blockers
    (charter,) = _charters(compilation)
    assert charter.alias == "charter" and charter.provenance is None


@pytest.mark.asyncio
async def test_an_unavailable_charter_blocks_at_the_mission_application() -> None:
    service, _ = await _service({"ai-engineer": "skill.missing-knowledge-charter"})
    compilation = await service.compile(text(_knowledge()), scope("ai-engineer"))

    found = {
        (issue.pointer, issue.code.value, issue.reason) for issue in compilation.report.blockers
    }
    assert ("/mission/application", "CAPABILITY_UNAVAILABLE", "pin_not_found") in found

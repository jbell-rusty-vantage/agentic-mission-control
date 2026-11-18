"""Builders, constants and fakes that other test files import.

Moved from tests/unit/coordinator/test_coordinator_facade.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from biotech_mission_adapters.domain.coordinator.web_capability_fixtures import (
    web_capability_definitions,
)
from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.application.capabilities.capability_search import CapabilitySearchService
from mission_control.application.capabilities.capability_search_repository import (
    InMemoryCatalogSearchRepository,
)
from mission_control.application.capabilities.catalog_projection import CatalogProjector
from mission_control.application.coordinator.coordinator_facade import (
    BlueprintRuntimeStatus,
    CoordinatorFeatureFlags,
    InMemoryCoordinatorAuditSink,
    ProductionCoordinatorFacade,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    CatalogPayloadRef,
    DefinitionSelector,
    PromptDefinition,
    PromptVariable,
    SkillCompatibility,
    SkillDefinition,
    SkillFileManifestEntry,
    SourceProvenance,
)
from mission_control.domain.coordinator.launch import BlueprintFamily
from tests.fixtures.capability_search_catalog import DeterministicEmbeddings

NOW = datetime(2026, 7, 25, 20, 0, tzinfo=UTC)
DIGEST = f"sha256:{'a' * 64}"


def _keyword_vector(text: str) -> tuple[float, ...]:
    normalized = text.casefold()
    return (
        1.0 if "web" in normalized else 0.0,
        1.0 if "research" in normalized else 0.0,
        1.0 if "browser" in normalized else 0.0,
    )


class ReadyRuntimes:
    async def snapshot(self) -> tuple[BlueprintRuntimeStatus, ...]:
        return (
            BlueprintRuntimeStatus(
                family=BlueprintFamily.STAGE_GRAPH,
                executable=True,
                reason="registered experiment worker passed preflight",
                evidence_ref="worker-preflight:stagegraph:test",
            ),
            BlueprintRuntimeStatus(
                family=BlueprintFamily.GOAL_DIRECTED,
                executable=True,
                reason="registered experiment worker passed preflight",
                evidence_ref="worker-preflight:goal-directed:test",
            ),
        )


def coordinator_skill() -> SkillDefinition:
    file_entry = SkillFileManifestEntry(
        path="SKILL.md",
        digest=DIGEST,
        size_bytes=512,
    )
    return SkillDefinition(
        logical_id="skill.mission-control-coordinator",
        title="BellLabs Workflow Coordinator",
        description="Search exact governed capabilities and prepare admitted workflows.",
        skill_name="mission-control-coordinator",
        frontmatter={"name": "mission-control-coordinator"},
        body_summary="Use the coordinator MCP surface progressively.",
        bundle_ref=CatalogPayloadRef(
            uri="s3://catalog/skills/mission-control-coordinator.tar",
            digest=DIGEST,
            media_type="application/x-tar",
            size_bytes=1_024,
        ),
        manifest_digest=sha256_digest((file_entry.model_dump(mode="json"),)),
        file_manifest=(file_entry,),
        compatibility=SkillCompatibility(runtimes=frozenset({"codex"})),
        source_provenance=SourceProvenance(
            source="belllabs",
            locator="catalog://skills/mission-control-coordinator",
            upstream_identity="mission-control-coordinator",
            upstream_version="1",
        ),
        review_status="approved",
    )


def propose_prompt() -> PromptDefinition:
    return PromptDefinition(
        logical_id="prompt.coordinator.propose-workflow",
        title="Propose governed workflow",
        description="Normalize an objective before catalog search and preparation.",
        format="markdown",
        template_engine="format",
        variables=(
            PromptVariable(
                name="objective",
                description="The operator's requested outcome.",
            ),
        ),
        body="Normalize this objective, then search Workflow Types first: {objective}",
        trust_class="reviewed",
    )


async def concrete_facade() -> tuple[
    ProductionCoordinatorFacade,
    InMemoryCoordinatorAuditSink,
]:
    definitions = InMemoryDefinitionRepository()
    search_index = InMemoryCatalogSearchRepository()
    embeddings = DeterministicEmbeddings(3, "text-embedding-3-small", vector=_keyword_vector)
    projector = CatalogProjector(
        definitions=definitions,
        search=search_index,
        embeddings=embeddings,
        embedding_model_id="text-embedding-3-small",
        embedding_dimensions=3,
        projection_generation="facade-test-1",
        clock=lambda: NOW,
    )
    records = []
    for definition in (*web_capability_definitions(), coordinator_skill(), propose_prompt()):
        record = await definitions.publish(
            definition,
            actor_id="publisher-1",
            published_at=NOW,
            expected_head_revision=0,
        )
        records.append(record)
        await projector.project(record.ref)
    skill_record = records[-2]
    prompt_record = records[-1]
    audit = InMemoryCoordinatorAuditSink()
    service = CapabilitySearchService(
        search=search_index,
        definitions=definitions,
        embeddings=embeddings,
        embedding_model_id="text-embedding-3-small",
        embedding_dimensions=3,
    )
    facade = ProductionCoordinatorFacade(
        definitions=definitions,
        catalog_index=search_index,
        search=service,
        readiness=ReadyRuntimes(),
        coordinator_skill=DefinitionSelector(exact=skill_record.ref),
        prompt_bindings={"propose_workflow": prompt_record.ref},
        flags=CoordinatorFeatureFlags(
            capability_search_enabled=True,
            external_discovery_enabled=False,
            coordinator_launch_enabled=False,
        ),
        audit=audit,
        clock=lambda: NOW,
    )
    return facade, audit

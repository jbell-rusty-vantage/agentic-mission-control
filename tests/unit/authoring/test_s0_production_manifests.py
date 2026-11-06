"""S0 templates compile using only actual production and qualification seed records."""

import json
from pathlib import Path

import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.completion_support import completion_support_issues
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.application.capabilities.capability_search import CapabilitySearchService
from mission_control.application.capabilities.catalog_projection import CatalogProjectionInput
from mission_control.domain.authoring.contracts import PublishedDefinition
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from tests.fixtures.capability_search_catalog import NOW, SEEDS, build_catalog
from tests.fixtures.mission_control_common_db import canonical_scope

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "tests/fixtures/manifests/materialization-observation"
DIRECTORIES = ("common", "ai-engineer", "qualification")
SLUGS = ("claude-agent-sdk", "codex", "cursor-local")


def committed_production_records():
    records = {}
    for directory in DIRECTORIES:
        for path in sorted((SEEDS / directory).glob("*.json")):
            for record in json.loads(path.read_bytes())["records"]:
                manifest = record["fields"].get("manifest", {})
                if record["kind"] != "asset_version" or "definition" not in manifest:
                    continue
                row = PublishedDefinition.model_validate(manifest)
                key = (row.ref.kind.value, row.ref.logical_id, row.ref.revision)
                if key in records:
                    assert records[key].ref.digest == row.ref.digest, (
                        "conflicting committed authority"
                    )
                records[key] = row
    return tuple(records[key] for key in sorted(records))


async def production_compiler():
    definitions, index, projector = await build_catalog(directories=DIRECTORIES)
    heads = {
        (row.ref.kind.value, row.ref.logical_id): row.ref.revision
        for row in await definitions.list_published_definitions()
    }
    for row in committed_production_records():
        key = (row.ref.kind.value, row.ref.logical_id)
        current = heads.get(key, 0)
        if row.ref.revision <= current:
            assert (await definitions.get(row.ref)).ref.digest == row.ref.digest
            continue
        assert row.ref.revision == current + 1, "no invented revisions to fill a seed gap"
        published = await definitions.publish(
            row.definition, row.published_by, row.published_at, current
        )
        assert published.ref == row.ref
        heads[key] = row.ref.revision
    await projector.project_many(
        tuple(CatalogProjectionInput(ref=row.ref) for row in committed_production_records())
    )
    search = CapabilitySearchService(search=index, definitions=definitions)
    compiler = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    return compiler, definitions


def scope():
    return ManifestScope(
        request_scope=canonical_scope("s0-test", "ai-engineer"), actor_id="offline-reviewer", at=NOW
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", SLUGS)
async def test_s0_templates_compile_on_production_seeds_without_added_catalog_rows(slug):
    compiler, definitions = await production_compiler()
    before = await definitions.list_published_definitions()
    assert {row.ref.digest for row in before} == {
        row.ref.digest for row in committed_production_records()
    }
    result = await compiler.compile((EXAMPLES / f"s0-{slug}.mission.yml").read_text(), scope())
    assert result.ok, result.report.blockers
    assert result.report.blockers == ()
    assert len(result.programs) == 1
    program = result.programs[0]
    assert completion_support_issues(result.definitions[0], program.lowered.blueprint) == ()
    slot = program.lowered.blueprint.stages[0].output_slots[0]
    assert slot.required
    assert slot.validation_schema.schema_ref == "schema.s0-probe-report@1"
    assert await definitions.list_published_definitions() == before, "compile is read-only"


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", SLUGS)
async def test_missing_required_schema_remains_a_fresh_start_blocker(slug):
    compiler, _ = await production_compiler()
    document = load_manifest_yaml((EXAMPLES / f"s0-{slug}.mission.yml").read_text())
    document["mission"]["program"]["nodes"][0]["outputs"][0]["schema"] = "schema.absent@1"
    result = await compiler.compile(canonical_manifest_bytes(document).decode(), scope())
    assert result.programs
    issues = completion_support_issues(result.definitions[0], result.programs[0].lowered.blueprint)
    assert any(issue.reason == "output_schema_validator_unavailable" for issue in issues)


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", SLUGS)
async def test_unsupported_required_hard_pause_refuses_during_compile(slug):
    compiler, _ = await production_compiler()
    document = load_manifest_yaml((EXAMPLES / f"s0-{slug}.mission.yml").read_text())
    document["mission"]["environment"]["requires"]["controls"] = ["hard_pause"]
    result = await compiler.compile(canonical_manifest_bytes(document).decode(), scope())
    assert not result.ok
    assert result.report.blockers

"""Offline compile proof for the real fixture graph and its exact local capabilities."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest_v2 import parse_manifest_yaml_versioned
from mission_control.domain.capabilities.host_support import LaneProfile
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog, publish_output_schemas
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.fixtures.qualia_full_manifest import full_manifest
from tests.fixtures.qualia_interventions import Interventions
from tests.fixtures.qualia_knowledge import build_qualia_knowledge_tools
from tests.fixtures.qualia_runtime import SpendLedger
from tests.fixtures.qualia_stagegraph import RECORD_SCHEMA
from tests.fixtures.qualia_web_tools import build_qualia_web_tools


@pytest.mark.parametrize(("vendor", "interventions"), [("firecrawl", True), ("tavily", False)])
async def test_full_qualia_manifest_compiles_seven_goals_with_exact_capabilities(
    tmp_path: Path,
    vendor: str,
    interventions: bool,
) -> None:
    web = build_qualia_web_tools(tmp_path / "web", environment={})
    ready = {
        "ready": True,
        "roles": {
            role: {"subject": role, "invocationId": role, "applicationId": "biotech"}
            for role in ("producer", "judge", "auditor")
        },
    }
    knowledge = build_qualia_knowledge_tools(
        None,
        ready=ready,
        evidence_dir=tmp_path / "web",
        ledger=SpendLedger(tmp_path / "spend"),
    )
    checkpoint_definition, checkpoint_component, _, _ = Interventions().capability()
    components = [*knowledge.components, checkpoint_component]
    text = full_manifest(web, components, vendor=vendor, interventions=interventions)
    parsed, document = parse_manifest_yaml_versioned(text)
    assert parsed is not None and document["manifest"] == "mission/v2"
    goals = document["mission"]["goals"]
    assert len(goals) == 7
    assert {goal["key"] for goal in goals} == set(document["mission"]["program"]["objectives"])
    stages = document["mission"]["program"]["nodes"]
    assert len(stages) == 7
    synthesis = next(stage for stage in stages if stage["key"] == "synthesize")
    assert synthesis["release_groups"][0]["join"] == {"quorum": 2}
    background = next(item for item in synthesis["inputs"] if item["name"] == "background")
    assert background["from"] == "discover.optional_background" and background["required"] is False
    for skill in web.skills:
        definition = web.definitions[skill.ref.logical_id]
        assert definition.host_support.supports(LaneProfile.DEEP_AGENTS)
        web.registry_skill_bundles[skill.bundle_digest].verify(
            skill_md_digest=skill.skill_md_digest
        )

    definitions, search = await fast_track_catalog()
    at = datetime(2026, 10, 30, tzinfo=UTC)
    for definition in [
        *web.definitions.values(),
        *knowledge.definitions.values(),
        checkpoint_definition,
    ]:
        await definitions.publish(definition, "qualia-offline-compile", at, 0)
    await publish_output_schemas(definitions, {"qualia_record@1": RECORD_SCHEMA})
    compiler = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    result = await compiler.compile(
        text,
        ManifestScope(
            request_scope=canonical_scope("tenant-1", "biotech"),
            actor_id="fixture-reviewer",
            at=at,
        ),
    )
    assert result.report.blockers == (), result.report.blockers
    assert result.ok and len(result.programs) == 1
    assert result.programs[0].configuration.digest.startswith("sha256:")
    assert result.programs[0].configuration.output_promises is not None
    assert not list((tmp_path / "web").glob("*.response.bin"))  # No acquisition or paid calls.

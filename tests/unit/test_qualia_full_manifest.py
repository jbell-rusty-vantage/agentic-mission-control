"""The full fixture compiles with stage-specific tool grants for either web vendor."""

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
from mission_control.domain.authoring.manifest import load_manifest_yaml
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog, publish_output_schemas
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.fixtures.qualia_full_manifest import full_manifest, native_probe_manifest
from tests.fixtures.qualia_interventions import Interventions
from tests.fixtures.qualia_knowledge import build_qualia_knowledge_tools
from tests.fixtures.qualia_runtime import SpendLedger
from tests.fixtures.qualia_stagegraph import RECORD_SCHEMA
from tests.fixtures.qualia_web_tools import build_qualia_web_tools
from tests.unit.test_qualia_knowledge import ready


@pytest.mark.parametrize(("vendor", "controls"), [("firecrawl", True), ("tavily", False)])
async def test_full_graph_compiles_with_scoped_tools(
    tmp_path: Path, vendor: str, controls: bool
) -> None:
    web = build_qualia_web_tools(tmp_path / "web", environment={})
    knowledge = build_qualia_knowledge_tools(
        None,  # type: ignore[arg-type]  # Offline catalog creation never invokes IPC.
        ready=ready(),
        evidence_dir=tmp_path / "web",
        ledger=SpendLedger(tmp_path / "budget"),
    )
    checkpoint, component, _, _ = Interventions().capability()
    manifest = full_manifest(
        web, [*knowledge.components, component], vendor=vendor, interventions=controls
    )
    nodes = load_manifest_yaml(manifest)["mission"]["program"]["nodes"]
    tools = {
        node["key"]: {
            entry["as"] for entry in node["environment"]["capabilities"] if entry["kind"] == "tool"
        }
        for node in nodes
    }
    assert tools["discover"] == {"submit_output", vendor + "_search"}
    assert tools["finalize"] == {"submit_output"}
    for stage, selected in tools.items():
        assert ("agent_browser_page" in selected) is (stage == "formulations")
        assert ("verify_evidence" in selected) is (stage == "verify")
        assert ("biotech_ingest" in selected) is (stage == "ingest")
        assert ("fixture_checkpoint" in selected) is (
            controls and stage in {"formulations", "studies"}
        )
        assert not any(
            name.startswith("tavily_" if vendor == "firecrawl" else "firecrawl_")
            for name in selected
        )
    definitions, search = await fast_track_catalog()
    for definition in [*web.definitions.values(), *knowledge.definitions.values(), checkpoint]:
        await definitions.publish(definition, "fixture", datetime.now(UTC), 0)
    await publish_output_schemas(definitions, {"qualia_record@1": RECORD_SCHEMA})
    compiler = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    compiled = await compiler.compile(
        manifest,
        ManifestScope(request_scope=canonical_scope(), actor_id="owner", at=datetime.now(UTC)),
    )
    assert compiled.ok, compiled.report.blockers


async def test_native_probe_compiles_with_real_knowledge_tool_contracts(tmp_path: Path) -> None:
    web = build_qualia_web_tools(tmp_path / "web", environment={})
    knowledge = build_qualia_knowledge_tools(
        None,  # type: ignore[arg-type]  # Offline catalog creation never invokes IPC.
        ready=ready(),
        evidence_dir=tmp_path / "web",
        ledger=SpendLedger(tmp_path / "budget"),
    )
    manifest = native_probe_manifest(web, knowledge.components, vendor="firecrawl")
    mission = load_manifest_yaml(manifest)["mission"]
    assert len(mission["program"]["nodes"]) == 1
    assert {"verify_evidence", "evidence_report_read", "biotech_ingest", "biotech_schema"} <= {
        capability["as"] for capability in mission["environment"]["capabilities"]
    }
    definitions, search = await fast_track_catalog()
    for definition in [*web.definitions.values(), *knowledge.definitions.values()]:
        await definitions.publish(definition, "fixture", datetime.now(UTC), 0)
    await publish_output_schemas(definitions, {"qualia_record@1": RECORD_SCHEMA})
    compiler = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    compiled = await compiler.compile(
        manifest,
        ManifestScope(request_scope=canonical_scope(), actor_id="owner", at=datetime.now(UTC)),
    )
    assert compiled.ok, compiled.report.blockers

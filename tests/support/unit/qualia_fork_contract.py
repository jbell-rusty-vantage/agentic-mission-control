"""Builders, constants and fakes that other test files import.

Moved from tests/unit/test_qualia_fork_contract.py.
"""

from datetime import UTC, datetime
from pathlib import Path

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import ManifestCompileService
from mission_control.domain.authoring.extensions import ExtensionRegistry
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog, publish_output_schemas
from tests.fixtures.manifest_runtime import AUTHOR
from tests.fixtures.qualia_fork_contract import QualiaForkPrograms
from tests.fixtures.qualia_full_manifest import full_manifest
from tests.fixtures.qualia_interventions import Interventions
from tests.fixtures.qualia_knowledge import build_qualia_knowledge_tools
from tests.fixtures.qualia_runtime import SpendLedger
from tests.fixtures.qualia_stagegraph import RECORD_SCHEMA
from tests.fixtures.qualia_web_tools import build_qualia_web_tools

AT = datetime(2026, 10, 31, tzinfo=UTC)


async def fixture(root: Path):
    web = build_qualia_web_tools(root / "web", environment={})
    knowledge = build_qualia_knowledge_tools(
        None,
        ready={
            "ready": True,
            "roles": {
                role: {"subject": role, "invocationId": role, "applicationId": "biotech"}
                for role in ("producer", "judge", "auditor")
            },
        },
        evidence_dir=root / "web",
        ledger=SpendLedger(root / "spend"),
    )
    definition, component, _, _ = Interventions().capability()
    components = [*knowledge.components, component]
    texts = (
        full_manifest(web, components, vendor="firecrawl", interventions=True),
        full_manifest(web, components, vendor="tavily", interventions=False),
    )
    repository, search = await fast_track_catalog()
    for item in [*web.definitions.values(), *knowledge.definitions.values(), definition]:
        await repository.publish(item, AUTHOR.actor_id, AT, 0)
    await publish_output_schemas(repository, {"qualia_record@1": RECORD_SCHEMA})
    payloads, extensions = InMemoryPayloadStore(), ExtensionRegistry()
    programs = QualiaForkPrograms(repository, extensions, payloads)
    compiler = ManifestCompileService(definitions=repository, search=search, programs=programs)
    return repository, payloads, extensions, programs, compiler, texts

"""Offline real authoring/F1 verification of the fixture's fixed fork contract."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestScope,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.execution.service import (
    F1RunConfigurationVerifier,
    RunControlService,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.policies.errors import ConfigurationVerificationFailed
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog, publish_output_schemas
from tests.fixtures.manifest_runtime import AUTHOR
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.fixtures.qualia_fork_contract import QualiaForkPrograms
from tests.fixtures.qualia_full_manifest import full_manifest
from tests.fixtures.qualia_interventions import Interventions
from tests.fixtures.qualia_knowledge import build_qualia_knowledge_tools
from tests.fixtures.qualia_runtime import SpendLedger
from tests.fixtures.qualia_stagegraph import RECORD_SCHEMA
from tests.fixtures.qualia_web_tools import build_qualia_web_tools
from tests.unit.run_control.test_run_control import request

AT = datetime(2026, 10, 31, tzinfo=UTC)
SCOPE = canonical_scope("tenant-1", "biotech")


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


async def test_two_exact_prepared_variants_share_type_but_not_runtime_capabilities(tmp_path):
    repository, payloads, extensions, programs, compiler, texts = await fixture(tmp_path)
    proof = await programs.prepare(
        compiler, texts, request_scope=SCOPE, actor_id=AUTHOR.actor_id, at=AT
    )
    assert all(len(refs) == 2 for refs in proof["allowed_refs"].values())
    compiled = []
    for index, text in enumerate(texts):
        result = await compiler.compile(
            text,
            ManifestScope(
                request_scope=SCOPE, actor_id=AUTHOR.actor_id, at=AT + timedelta(seconds=30 + index)
            ),
        )
        assert result.ok, result.report.blockers
        (program,) = result.programs
        config, ref = await programs.compile(
            program.lowered,
            request_scope=SCOPE,
            actor_id=AUTHOR.actor_id,
            at=AT + timedelta(seconds=60 + index),
            persist=True,
            compilation_suffix=f"admit-{index}",
        )
        assert ref == programs.workflow_ref
        verifier = F1RunConfigurationVerifier(ControlPlaneService(repository, extensions, payloads))
        candidate = request(request_scope=SCOPE).model_copy(
            update={
                "effective_configuration_digest": config.digest,
                "workflow_type_ref": ref,
                "input_manifest": config.input_manifest,
            }
        )
        verified = await verifier.verify(candidate)
        RunControlService._validate_configuration_binding(candidate, verified)
        prior_type = next(
            ref
            for config in programs.variants.values()
            for ref in config.source_refs
            if ref.kind.value == "workflow_type"
        )
        with pytest.raises(ConfigurationVerificationFailed, match="Workflow Type exact reference"):
            RunControlService._validate_configuration_binding(
                candidate.model_copy(update={"workflow_type_ref": prior_type}), verified
            )
        with pytest.raises(ConfigurationVerificationFailed, match="authority subject"):
            await verifier.verify(
                candidate.model_copy(
                    update={
                        "actor": candidate.actor.model_copy(update={"actor_id": "other-operator"})
                    }
                )
            )
        compiled.append((config, ref))
    source, target = compiled
    assert source[1] == target[1]
    source_tools = {r.logical_id for r in source[0].runtime_profile.operation_binding_refs}
    target_tools = {r.logical_id for r in target[0].runtime_profile.operation_binding_refs}
    assert (
        "tool.qualia.firecrawl_search" in source_tools
        and "tool.qualia.tavily_search" not in source_tools
    )
    assert (
        "tool.qualia.tavily_search" in target_tools
        and "tool.qualia.firecrawl_search" not in target_tools
    )
    # The shared profile catalog is not the per-stage tool selection. The target
    # manifest explicitly omits the control tool from every admitted stage binding.
    target_nodes = yaml.safe_load(texts[1])["mission"]["program"]["nodes"]
    assert all(
        "fixture_checkpoint" not in {entry["as"] for entry in node["environment"]["capabilities"]}
        for node in target_nodes
    )
    assert source[0].effective_authority == target[0].effective_authority
    assert source[0].output_promises == target[0].output_promises
    assert not list((tmp_path / "web").glob("*.response.bin"))


async def test_unprepared_third_variant_cannot_enter_shared_contract(tmp_path):
    _, _, _, programs, compiler, texts = await fixture(tmp_path)
    await programs.prepare(compiler, texts, request_scope=SCOPE, actor_id=AUTHOR.actor_id, at=AT)
    changed = yaml.safe_load(texts[1])
    changed["mission"]["program"]["nodes"][0]["instruction"] += " Unprepared third variant."
    with pytest.raises(AssertionError, match="unprepared fixture variant"):
        await compiler.compile(
            yaml.safe_dump(changed),
            ManifestScope(request_scope=SCOPE, actor_id=AUTHOR.actor_id, at=AT),
        )


async def test_different_budget_cannot_broaden_shared_authority(tmp_path):
    _, _, _, programs, compiler, texts = await fixture(tmp_path)
    changed = yaml.safe_load(texts[1])
    changed["mission"]["environment"]["budget"]["usd"] = 36
    with pytest.raises(AssertionError, match="protected Workflow Type contract"):
        await programs.prepare(
            compiler,
            (texts[0], yaml.safe_dump(changed)),
            request_scope=SCOPE,
            actor_id=AUTHOR.actor_id,
            at=AT,
        )
    assert programs.workflow_ref is None


async def test_reopening_fixture_reuses_exact_published_contract(tmp_path):
    repository, payloads, extensions, programs, compiler, texts = await fixture(tmp_path)
    first = await programs.prepare(
        compiler, texts, request_scope=SCOPE, actor_id=AUTHOR.actor_id, at=AT
    )
    reopened = QualiaForkPrograms(repository, extensions, payloads)
    later = ManifestCompileService(definitions=repository, search=None, programs=reopened)
    # Capability selections are exact pins, so a search adapter is unnecessary on reopen.
    second = await reopened.prepare(
        later, texts, request_scope=SCOPE, actor_id=AUTHOR.actor_id, at=AT + timedelta(minutes=5)
    )
    assert second["workflow_type_ref"] == first["workflow_type_ref"]
    assert reopened.workflow_ref == programs.workflow_ref

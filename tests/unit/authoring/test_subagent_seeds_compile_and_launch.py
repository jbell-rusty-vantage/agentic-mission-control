"""P1 subagents, end to end below the runtime: a manifest selects the two explicit child shapes
on a Deep Agents node; compile discriminates the profiles and pins the seeded child's own
Skill and MCP server as its capability requests; the production launch resolver routes them
to the child (never the parent) and the lane adapter seals and receipts them.

Catalog: the fast-track fixture (`subagent.seeded-researcher` seeds `skill.biotech-literature-
review` and `mcp.pubmed`; `subagent.general` inherits). Deployment: the fixture launch
bindings plus a served component per seed.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_launch_inputs import (
    CapabilityComponentBinding,
    ManifestLaunchBindingError,
)
from mission_control.application.authoring.manifest_service import (
    ManifestCompilation,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.application.authoring.subagent_discriminator import (
    is_subagent_seed,
    seed_owner,
)
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.domain.agentic_components.projection import ResolvedCapability
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.capabilities.pins import CapabilityPin as CatalogPin
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    DeepAgentSkillComponent,
)
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture
from tests.fixtures.applications import installed_applications
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.fixtures.models import bindings_catalog
from tests.unit.authoring.manifest_launch_fixture import (
    fixture_bindings,
    fixture_served,
    pubmed_bound,
)
from tests.unit.authoring.test_manifest_launch_inputs import MINIMAL, admitted

SCOPE = canonical_scope("tenant-1")
SECRETS = {"openai": "OPENAI_API_KEY"}


def _manifest(lane: str = "deep_agents", *, agents: list[dict[str, object]]) -> str:
    document = load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))
    environment = document["mission"]["environment"]
    environment["lane"] = lane
    environment["agents"] = agents
    return canonical_manifest_bytes(document).decode("utf-8")


async def _compile(manifest_yaml: str) -> ManifestCompilation:
    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    return await service.compile(
        manifest_yaml,
        ManifestScope(request_scope=SCOPE, actor_id="owner", at=datetime(2026, 10, 20, tzinfo=UTC)),
    )


SEEDED = {"search": "seeded researcher subagent", "kind": "subagent_profile", "as": "researcher"}
GENERAL = {"search": "general inheriting subagent", "kind": "subagent_profile", "as": "general"}


@pytest.fixture(scope="module")
def compiled() -> ManifestCompilation:
    return asyncio.run(_compile(_manifest(agents=[SEEDED, GENERAL])))


def test_compile_pins_the_seeded_childs_own_capabilities_under_its_entry(
    compiled: ManifestCompilation,
) -> None:
    assert compiled.ok, [item.message for item in compiled.report.blockers]
    (definition,) = compiled.definitions
    seeds = [item for item in definition.capabilities if is_subagent_seed(item)]
    assert {(item.pointer, item.role) for item in seeds} == {
        ("/mission/environment/agents/0/seeds/skills/0", "skill"),
        ("/mission/environment/agents/0/seeds/mcp_servers/0", "capability"),
    }
    assert all(seed_owner(item) == "seeded-researcher" for item in seeds)
    assert all(item.is_exact for item in seeds)
    assert {item.attributes["provenance"] for item in seeds} == {"subagent:seeded-researcher"}
    # The resolution report names the seeds' lanes as the selecting node's lane.
    assert compiled.resolution is not None
    seed_rows = [
        item for item in compiled.resolution.resolved if item.pointer.split("/")[-3] == "seeds"
    ]
    assert seed_rows and all(item.lanes == ("deep_agents",) for item in seed_rows)
    # Neither child shape degrades anything on this lane: no subagent warnings.
    assert not [item for item in compiled.report.warnings if "subagent" in item.message]


def _seed_bindings(definition, bindings):
    """FIXTURE: serve the seeded child's Skill and MCP server beside the fixture components."""

    literature = next(
        item
        for item in definition.capabilities
        if item.resolved is not None
        and item.resolved.capability_id == "skill.biotech-literature-review"
    )
    pubmed = next(
        item
        for item in definition.capabilities
        if item.resolved is not None and item.resolved.capability_id == "mcp.pubmed"
    )
    probe, _profile, _bundle = exact_fixture()
    (probe_skill,) = probe.skills
    skill = DeepAgentSkillComponent(
        **{
            **probe_skill.model_dump(mode="python"),
            "skill_name": "biotech-literature-review",
            "mount_root": "/skills/children/biotech-literature-review",
            "attachment_target": "agent.subagent.seeded-researcher",
        }
    )
    assert pubmed.resolved is not None and pubmed.resolved.digest is not None
    assert literature.resolved is not None and literature.resolved.digest is not None
    bound = pubmed_bound(bindings, pubmed.resolved.digest)
    bound = bound.model_copy(
        update={
            "capabilities": {
                **bound.capabilities,
                "skill.biotech-literature-review": CapabilityComponentBinding(
                    catalog_digest=literature.resolved.digest, kind="skill", skill=skill
                ),
            }
        }
    )
    served = fixture_served(bound)
    served = replace(
        served,
        mcp_servers=frozenset(
            item.mcp_server.ref.digest
            for item in bound.capabilities.values()
            if item.mcp_server is not None
        ),
        skills=frozenset({skill.bundle_digest}),
    )
    return bound, served, skill


def test_launch_routes_seeds_to_the_child_and_receipts_them(compiled: ManifestCompilation) -> None:
    (definition,) = compiled.definitions
    (program,) = compiled.programs
    bound, served, skill = _seed_bindings(definition, fixture_bindings())
    resolver = compose_manifest_launch_resolver(
        bound,
        served,
        applications=installed_applications(),
        models=bindings_catalog(bound),
        provider_secret_env=SECRETS,
        async_result_policy_refs=frozenset(),
    )
    templates = resolver.stage_templates(definition, admitted(program), rows=_rows(definition))
    request = next(iter(templates.values()))
    binding = DeepAgentExecutionBinding.carried_by(request)
    assert binding is not None
    # The parent keeps only what it selected itself (pubmed through the manifest).
    assert [item.server_name for item in binding.mcp_servers] == ["qualification"]
    assert binding.skills == ()
    by_name = {child.name: child for child in binding.sync_subagents}
    assert set(by_name) == {"seeded-researcher", "general"}
    researcher = by_name["seeded-researcher"]
    assert researcher.inherits_parent is False
    assert [item.skill_name for item in researcher.seeded_skills] == ["biotech-literature-review"]
    # The child seeded `mcp.pubmed`, which the parent also selects: one exact component, so
    # the child narrows to the parent's loaded server instead of connecting a second one.
    assert researcher.seeded_mcp_servers == ()
    assert [ref.logical_id for ref in researcher.mcp_server_refs] == [
        binding.mcp_servers[0].ref.logical_id
    ]
    general = by_name["general"]
    assert general.inherits_parent and general.tool_refs == () and general.system_prompt
    assert general.system_prompt_ref.digest == sha256_digest(general.system_prompt)
    receipt = binding.materialization_receipt
    assert receipt is not None
    rows = {(item.kind, item.name): item.verdict for item in receipt.items}
    assert rows[("subagent", "general")] == "native"
    assert rows[("subagent", "seeded-researcher")] == "native"
    assert rows[("skill", "seeded-researcher/biotech-literature-review")] == "native"
    assert skill.bundle_digest in {item.digest for item in receipt.items}


def test_a_seed_without_a_served_component_fails_at_its_pointer(
    compiled: ManifestCompilation,
) -> None:
    (definition,) = compiled.definitions
    (program,) = compiled.programs
    bound, served, _skill = _seed_bindings(definition, fixture_bindings())
    unserved = bound.model_copy(
        update={
            "capabilities": {
                name: item
                for name, item in bound.capabilities.items()
                if name != "skill.biotech-literature-review"
            }
        }
    )
    resolver = compose_manifest_launch_resolver(
        unserved,
        served,
        applications=installed_applications(),
        models=bindings_catalog(unserved),
        provider_secret_env=SECRETS,
    )
    with pytest.raises(ManifestLaunchBindingError) as refused:
        resolver.stage_templates(definition, admitted(program), rows=_rows(definition))
    assert refused.value.pointer == "/mission/environment/agents/0/seeds/skills/0"


def _rows(definition):
    """The catalog rows the resolver reads subagent profile bodies from (profiles only)."""

    async def build() -> dict[str, ResolvedCapability]:
        definitions, _search = await fast_track_catalog()
        rows: dict[str, ResolvedCapability] = {}
        for item in definition.capabilities:
            if item.role != "agent" or is_subagent_seed(item):
                continue
            pin = item.resolved or item.pin
            assert pin is not None and pin.digest is not None
            text = f"{pin.capability_id}@{pin.version}#{pin.digest}"
            row = await definitions.get(
                ExactDefinitionRef(
                    kind=DefinitionKind.SUBAGENT_PROFILE,
                    logical_id=pin.capability_id,
                    revision=int(pin.version),
                    digest=pin.digest,
                )
            )
            rows[text] = ResolvedCapability(pin=CatalogPin.parse(text), definition=row.definition)
        return rows

    return asyncio.run(build())

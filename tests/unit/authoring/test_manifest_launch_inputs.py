"""MP-02: the production manifest launch author resolves node environments or fails pointed.

Compiles the example manifests against the seeded catalog fixture with the in-memory program
compiler (a real Effective Run Configuration, no database), then resolves the lane templates
with FIXTURE deployment bindings (``manifest_launch_fixture``). Missing model, sandbox, auth,
lane or capability bindings fail with the manifest pointer that selected them.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    ManifestChainLaunchInputs,
    ManifestLaunchBindingError,
    ManifestLaunchBindings,
    ManifestLaunchInputAuthor,
    ManifestLaunchResolver,
    ServedComponents,
    binding_ref,
)
from mission_control.application.authoring.manifest_service import (
    CompiledMission,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.application.chains.relay import (
    ChainIntent,
    ChainRelayPump,
    ChainRelayReport,
)
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    DeepAgentModelComponent,
)
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture
from tests.fixtures.applications import installed_applications
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.fixtures.models import bindings_catalog
from tests.unit.authoring.manifest_launch_fixture import (
    deep_agents_chain,
    fixture_bindings,
    fixture_served,
    pubmed_bound,
    unserved_model_ref,
)

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"
MISSION_2 = (
    ROOT / "tests/fixtures/manifests/fast-track/02-research-ingestion-cursor-cloud-chain.yml"
)
MISSION_3 = ROOT / "tests/fixtures/manifests/fast-track/03-codebase-feature-cursor-local.yml"
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
def minimal() -> tuple[MissionDefinition, CompiledMission]:
    definitions, programs = asyncio.run(compile_programs(MINIMAL.read_text(encoding="utf-8")))
    return definitions[0], programs[0]


@pytest.fixture(scope="module")
def chain() -> tuple[list[MissionDefinition], list[CompiledMission]]:
    return asyncio.run(compile_programs(deep_agents_chain(MISSION_2.read_text(encoding="utf-8"))))


def pubmed_digest(definition: MissionDefinition) -> str:
    (capability,) = [item for item in definition.capabilities if item.alias == "pubmed"]
    assert capability.resolved is not None and capability.resolved.digest is not None
    return capability.resolved.digest


# --- Stage Graph ------------------------------------------------------------------------------


def test_stage_templates_bind_each_node_environment(
    minimal: tuple[MissionDefinition, CompiledMission],
) -> None:
    definition, program = minimal
    bindings = pubmed_bound(fixture_bindings(), pubmed_digest(definition))
    server = bindings.capabilities["mcp.pubmed"].mcp_server
    assert server is not None
    templates = resolver(bindings, served=served_with_mcp(bindings)).stage_templates(
        definition, admitted(program)
    )

    assert set(templates) == {"collect/execute/default", "synthesize/execute/default"}
    collect, synthesize = (
        templates["collect/execute/default"],
        templates["synthesize/execute/default"],
    )
    for template in (collect, synthesize):
        deep = DeepAgentExecutionBinding.carried_by(template)
        assert deep is not None and template.execution_runtime == "deep_agent"
        assert deep.model.settings["temperature"] == 0.2
        assert deep.model.settings["reasoning_effort"] == "high"
        assert template.model_policy.reasoning_effort == "high"
        assert [item.ref.digest for item in deep.mcp_servers] == [server.ref.digest]
        assert template.capability_grant.mcp_server_ids == {server.server_name}
        assert [ref.key for ref in template.secret_refs] == ["OPENAI_API_KEY"]
        assert template.workspace.namespace_id.startswith("workspace-namespace:{run_id}:stage:")
        assert template.effective_configuration_digest == program.configuration.digest
    assert collect.workspace.slot_bindings[0].owner.owner_id == "stage:collect"
    assert synthesize.operation_contract_ref.endswith(":synthesize@1")


def test_the_committed_definition_resolves_like_the_compiled_one(
    minimal: tuple[MissionDefinition, CompiledMission],
) -> None:
    """The author reads the definition back from PostgreSQL, where decimals are JSON strings."""

    definition, program = minimal
    stored = MissionDefinition.model_validate(definition.model_dump(mode="json"))
    bindings = pubmed_bound(fixture_bindings(), pubmed_digest(definition))
    bound = resolver(bindings, served=served_with_mcp(bindings))
    assert bound.stage_templates(stored, admitted(program)) == bound.stage_templates(
        definition, admitted(program)
    )


def test_stage_templates_are_deterministic(
    minimal: tuple[MissionDefinition, CompiledMission],
) -> None:
    definition, program = minimal
    bindings = pubmed_bound(fixture_bindings(), pubmed_digest(definition))
    served = served_with_mcp(bindings)
    first = resolver(bindings, served=served).stage_templates(definition, admitted(program))
    second = resolver(bindings, served=served).stage_templates(definition, admitted(program))
    assert first == second


def test_an_unbound_catalog_capability_fails_at_its_pointer(
    minimal: tuple[MissionDefinition, CompiledMission],
) -> None:
    definition, program = minimal
    with pytest.raises(ManifestLaunchBindingError) as raised:
        resolver().stage_templates(definition, admitted(program))
    assert raised.value.pointer == "/mission/environment/capabilities/0"
    assert "mcp.pubmed" in str(raised.value)


def test_an_unserved_capability_component_fails(
    minimal: tuple[MissionDefinition, CompiledMission],
) -> None:
    definition, program = minimal
    bindings = pubmed_bound(fixture_bindings(), pubmed_digest(definition))
    with pytest.raises(ManifestLaunchBindingError) as raised:
        resolver(bindings).stage_templates(definition, admitted(program))
    assert raised.value.pointer == "/mission/environment/capabilities/0"
    assert "does not serve" in str(raised.value)


def test_a_drifted_capability_revision_fails(
    minimal: tuple[MissionDefinition, CompiledMission],
) -> None:
    definition, program = minimal
    bindings = pubmed_bound(fixture_bindings(), "sha256:" + "0" * 64)
    with pytest.raises(ManifestLaunchBindingError, match="pinned at"):
        resolver(bindings).stage_templates(definition, admitted(program))


def test_a_node_model_profile_without_binding_names_the_overlay(
    minimal: tuple[MissionDefinition, CompiledMission],
) -> None:
    definition, program = minimal
    bindings = pubmed_bound(
        fixture_bindings(model_profiles=("frontier.default",)), pubmed_digest(definition)
    )
    with pytest.raises(ManifestLaunchBindingError) as raised:
        resolver(bindings, served=served_with_mcp(bindings)).stage_templates(
            definition, admitted(program)
        )
    assert raised.value.pointer == "/mission/program/nodes/1/environment/model/profile"
    assert "frontier.long_context" in str(raised.value)


# --- Goal Loop and the pointed failures ---------------------------------------------------------


def test_goal_templates_bind_executor_and_verifier(
    chain: tuple[list[MissionDefinition], list[CompiledMission]],
) -> None:
    definitions, programs = chain
    research = next(item for item in definitions if item.mission_key == "research")
    program = next(item for item in programs if item.mission_key == "research")
    templates = pubmed_resolver(research).goal_templates(research, admitted(program))
    assert set(templates) == {"executor", "verifier"}
    for role, template in templates.items():
        assert template.identity.operation_id == f"manifest-template/{role}"
        assert template.workspace.workspace_id == f"workspace:{{run_id}}:{role}"
        assert template.workspace.slot_bindings[0].logical_path == "/work"
        assert template.budget_limits == dict(
            program.configuration.effective_authority.budgets.dimensions
        )
        assert template.requested_at == program.configuration.context.compiled_at


def test_missing_model_binding_fails_at_the_mission_model(
    chain: tuple[list[MissionDefinition], list[CompiledMission]],
) -> None:
    definitions, programs = chain
    bindings = fixture_bindings(model_profiles=())
    with pytest.raises(ManifestLaunchBindingError) as raised:
        pubmed_resolver(definitions[1], bindings).goal_templates(
            definitions[1], admitted(programs[1])
        )
    assert raised.value.pointer == "/missions/1/environment/model/profile"


def test_named_goal_templates_require_explicit_served_schema_binding(chain):
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.execution.contracts import StructuredOutputBinding
    from mission_control.domain.programs.goal_directed_runtime import GoalNamedExecutorObservation
    from tests.unit.orchestration.test_goal_schema_completion import multi_goal_request

    definitions, programs = chain
    research = next(item for item in definitions if item.mission_key == "research")
    program = next(item for item in programs if item.mission_key == "research")
    launch = admitted(program)
    slots = multi_goal_request().completion_blueprint.output_slots
    launch = replace(launch, blueprint=launch.blueprint.model_copy(update={"output_slots": slots}))
    with pytest.raises(ManifestLaunchBindingError, match="GoalNamedExecutorObservation"):
        pubmed_resolver(research).goal_templates(research, launch)
    bindings = fixture_bindings()
    schema = StructuredOutputBinding(
        schema_id="belllabs.goal-executor-observation.v1",
        revision=2,
        schema_digest=sha256_digest(GoalNamedExecutorObservation.model_json_schema()),
    )
    bindings = bindings.model_copy(
        update={
            "deep_agents": bindings.deep_agents.model_copy(
                update={
                    "goal_output_schemas": {
                        **bindings.deep_agents.goal_output_schemas,
                        "executor": schema,
                    },
                }
            )
        }
    )
    templates = pubmed_resolver(research, bindings).goal_templates(research, launch)
    assert "output_bindings" in templates["executor"].prompt_segments[0].content


def test_a_goal_schema_needs_the_model_rows_structured_output_strategy(
    chain: tuple[list[MissionDefinition], list[CompiledMission]],
) -> None:
    """W1 D16: a GoalDirected role that binds a structured-output schema is refused at launch
    when its model row declares no structured_output strategy (never framework auto-detection,
    which forced tool choice on Claude Sonnet 5.5)."""

    from tests.fixtures.models import fixture_model_catalog, fixture_model_profile

    definitions, programs = chain
    research = next(item for item in definitions if item.mission_key == "research")
    program = next(item for item in programs if item.mission_key == "research")
    bound = pubmed_bound(fixture_bindings(), pubmed_digest(research))
    rows = [
        fixture_model_profile(name).model_copy(
            update={"supports": ("tool_use",), "structured_output": None}
        )
        for name in bound.model_profiles
    ]
    author = compose_manifest_launch_resolver(
        bound,
        served_with_mcp(bound),
        applications=installed_applications(),
        models=fixture_model_catalog(bound.model_profiles, rows=rows),
        provider_secret_env=SECRETS,
    )
    with pytest.raises(ManifestLaunchBindingError, match="declares no structured_output") as raised:
        author.goal_templates(research, admitted(program))
    assert raised.value.pointer.endswith("/model/profile")


def test_unserved_model_fails_without_fabricating_one(
    chain: tuple[list[MissionDefinition], list[CompiledMission]],
) -> None:
    definitions, programs = chain
    base = fixture_bindings()
    unserved = DeepAgentModelComponent(
        ref=unserved_model_ref(), provider="openai", model_name="not-served"
    )
    bindings = base.model_copy(update={"model_profiles": {"frontier.default": unserved}})
    served = fixture_served(base)
    with pytest.raises(ManifestLaunchBindingError, match="not served by this deployment"):
        pubmed_resolver(definitions[0], bindings, served=served).goal_templates(
            definitions[0], admitted(programs[0])
        )


def test_missing_auth_reference_fails_at_the_model_pointer(
    chain: tuple[list[MissionDefinition], list[CompiledMission]],
) -> None:
    definitions, programs = chain
    with pytest.raises(ManifestLaunchBindingError) as raised:
        pubmed_resolver(definitions[0], secrets={}).goal_templates(
            definitions[0], admitted(programs[0])
        )
    assert raised.value.pointer == "/missions/0/environment/model/profile"
    assert "openai" in str(raised.value)


def test_missing_sandbox_binding_fails_at_the_sandbox_pointer(
    chain: tuple[list[MissionDefinition], list[CompiledMission]],
) -> None:
    definitions, programs = chain
    bindings = fixture_bindings(sandbox_profiles=("research.standard",))
    with pytest.raises(ManifestLaunchBindingError) as raised:
        pubmed_resolver(definitions[1], bindings).goal_templates(
            definitions[1], admitted(programs[1])
        )
    assert raised.value.pointer == "/missions/1/environment/sandbox/profile"
    assert "ingestion.standard" in str(raised.value)


def test_a_non_deep_agents_lane_fails_at_the_lane_pointer() -> None:
    scope = canonical_scope("tenant-1", "ai-engineer")
    definitions, programs = asyncio.run(
        compile_programs(MISSION_3.read_text(encoding="utf-8"), scope)
    )
    with pytest.raises(ManifestLaunchBindingError) as raised:
        resolver().goal_templates(definitions[0], admitted(programs[0], scope=scope))
    assert raised.value.pointer == "/mission/environment/lane"
    assert "cursor_local" in str(raised.value)


def test_an_unmapped_model_setting_fails_at_its_pointer() -> None:
    document = load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))
    document["mission"]["environment"]["model"]["settings"]["top_k"] = 3
    definitions, programs = asyncio.run(
        compile_programs(canonical_manifest_bytes(document).decode("utf-8"))
    )
    digest = pubmed_digest(definitions[0])
    bindings = pubmed_bound(fixture_bindings(), digest)
    with pytest.raises(ManifestLaunchBindingError) as raised:
        resolver(bindings, served=served_with_mcp(bindings)).stage_templates(
            definitions[0], admitted(programs[0])
        )
    assert raised.value.pointer == "/mission/environment/model/settings/top_k"


def test_the_scaffold_must_select_nothing() -> None:
    bindings = fixture_bindings()
    binding, profile, _ = exact_fixture()
    with pytest.raises(ValueError, match="carries no MCP server"):
        bindings.deep_agents.model_validate(
            {**bindings.deep_agents.model_dump(mode="python"), "profile": profile}
        )
    assert binding.skills  # the qualification profile does select a Skill


def test_an_unserved_checkpointer_refuses_composition() -> None:
    bindings = fixture_bindings()
    served = replace(fixture_served(bindings), checkpointers=frozenset())
    with pytest.raises(ValueError, match="checkpointer"):
        compose_manifest_launch_resolver(
            bindings,
            served,
            applications=installed_applications(),
            models=bindings_catalog(bindings),
            provider_secret_env=SECRETS,
        )


# --- The author freezes its first resolution --------------------------------------------------


class _Stores:
    def __init__(self) -> None:
        self.goal: dict[str, Any] = {}
        self.persisted = 0

    async def persist_templates(self, **values: Any) -> None:
        self.persisted += 1
        self.goal = {"executor": values["executor"], "verifier": values["verifier"]}

    async def get_template(self, *, operation_role: str, **_: Any) -> Any:
        if operation_role not in self.goal:
            raise ValueError("GoalDirected operation template is unavailable")
        return self.goal[operation_role]

    async def list_templates(self, **_: Any) -> dict[str, Any]:
        return {}


def test_the_author_persists_once_and_reuses_the_frozen_templates() -> None:
    # A fresh launch needs an implemented acceptance path: Goal Loop human review.
    document = load_manifest_yaml(deep_agents_chain(MISSION_2.read_text(encoding="utf-8")))
    for mission in document["missions"]:
        for output in mission["program"].get("outputs", ()):
            output["enforcement"] = "optional"
        for goal in mission["goals"]:
            for criterion in goal["criteria"]:
                criterion["acceptance"] = {"human": "review_accept"}
    definitions, programs = asyncio.run(
        compile_programs(canonical_manifest_bytes(document).decode())
    )
    definition, program = definitions[0], programs[0]
    stores = _Stores()
    lookups: list[str] = []

    class Runs:
        async def get_run(self, _scope: str, _run_id: str) -> Any:
            return SimpleNamespace(effective_configuration_digest=program.configuration.digest)

    class Plane:
        async def retrieve_for_admission(self, digest: str) -> Any:
            assert digest == program.configuration.digest
            return program.configuration

    class Definitions:
        async def run_subscriptions(self, _scope: str, run_id: str) -> dict[str, Any]:
            lookups.append(run_id)
            return {"definition": definition.model_dump(mode="json")}

    def author(bindings: ManifestLaunchBindings) -> ManifestLaunchInputAuthor:
        return ManifestLaunchInputAuthor(
            resolver=pubmed_resolver(definition, bindings),
            run_control=Runs(),  # type: ignore[arg-type]
            control_plane=Plane(),  # type: ignore[arg-type]
            definitions=Definitions(),
            stage_templates=stores,
            goal_templates=stores,
        )

    first = asyncio.run(author(fixture_bindings()).bind(SCOPE, "run-1", family="GoalDirected"))
    # A later deployment change (no model bound) does not re-author a frozen run.
    second = asyncio.run(
        author(fixture_bindings(model_profiles=())).bind(SCOPE, "run-1", family="GoalDirected")
    )
    assert first == second and stores.persisted == 1 and lookups == ["run-1"]
    with pytest.raises(ValueError, match="GoalDirected blueprint"):
        asyncio.run(author(fixture_bindings()).bind(SCOPE, "run-1", family="StageGraph"))
    assert binding_ref("run-1") == "semantic-input:manifest:run-1"


# --- Chain relay port and pump ----------------------------------------------------------------


def test_the_chain_port_authors_the_consumer_run() -> None:
    calls: list[dict[str, Any]] = []

    class Author:
        async def family_input(self, **values: Any) -> dict[str, Any]:
            calls.append(values)
            return {"ok": True}

    intent = ChainIntent(
        intent_kind="start_run",
        delivery_key="key",
        request_scope=SCOPE,
        chain_id=uuid4(),
        mission_id=uuid4(),
        run_id=uuid4(),
        run_key="run-consumer",
        family="GoalDirected",
        initial_goal="ingest",
        actor_ref="chain:x",
    )
    assert asyncio.run(ManifestChainLaunchInputs(Author()).family_input(intent)) == {"ok": True}
    assert calls == [
        {
            "request_scope": SCOPE,
            "run_id": "run-consumer",
            "family": "GoalDirected",
            "initial_goal": "ingest",
        }
    ]


def test_the_relay_pump_isolates_scopes_and_stops() -> None:
    passes: list[str] = []

    class Relay:
        async def relay_once(self, scope: str, *, now: datetime, limit: int) -> ChainRelayReport:
            passes.append(scope)
            if scope == "broken":
                raise RuntimeError("scope outage")
            return ChainRelayReport(delivered=(f"{scope}:{limit}",))

    pump = ChainRelayPump(Relay(), ("broken", "ok"), interval_seconds=0.01, limit=7)  # type: ignore[arg-type]
    reports = asyncio.run(pump.run_once())
    assert passes == ["broken", "ok"] and reports == (ChainRelayReport(delivered=("ok:7",)),)

    async def run_and_stop() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(pump.run(stop))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(run_and_stop())
    assert len(passes) > 2
    with pytest.raises(ValueError):
        ChainRelayPump(Relay(), (), interval_seconds=0)  # type: ignore[arg-type]

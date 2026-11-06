"""MP-02 for mission/v2: compile dispatch, v2 lowering, V01 admission and provider launch.

- ``mission/v1`` takes the exact v1 parser and lowering (no ``selections`` in any dump);
  ``mission/v2`` documents compile through the same definitions with additive selections.
- Every checked v2 example under ``tests/fixtures/manifests/multi-provider/`` compiles with the
  fast-track fixture catalog and authors its launch templates against
  the versioned Codex 0.162.1 multi-provider example: claude/codex
  stages and Goal Loop roles carry a sealed ``mc.execution_binding.v2`` routed to their lane
  queue, Deep Agents nodes keep their Deep Agent binding.
- V01: required features a lane's declared matrix cannot provide are pointed compile blockers;
  hosted profiles compile structurally and their launch is refused.
- Missing deployment bindings fail at the manifest pointer that selected them.
- P1: a ``value_ref: config:<key>`` resolves through the installation configuration at compile;
  the value never enters the report, resolution, definitions, digests or launch templates, and a
  secret-like key is refused even when a source supplies it.

Everything here is offline (fixture catalog, in-memory compiler); no provider is contacted.
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.agentic_components.placement import operating_contract
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    ManifestBundleCustodyUnavailable,
    ManifestCompletionUnavailable,
    ManifestLaunchBindingError,
    ManifestLaunchBindings,
    ManifestLaunchInputAuthor,
    ManifestLaunchResolver,
    ServedComponents,
    provider_capability_pins,
)
from mission_control.application.authoring.manifest_service import (
    CompiledMission,
    ManifestCompilation,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.application.authoring.provider_launch import (
    CatalogProjectionRows,
    ProviderBindingRows,
    ProviderLanes,
    binding_capability_pins,
    materialization_digest,
)
from mission_control.application.chains.service import ManifestStructureService
from mission_control.application.environments.kits import (
    CatalogEnvironmentInputs,
    EnvironmentKitCatalog,
)
from mission_control.application.execution.harness.describe import declared_matrix
from mission_control.application.installations.registry import (
    ApplicationBinding,
    HostedAgentApiTerms,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import (
    MissionManifest,
    canonical_manifest_bytes,
    load_manifest_yaml,
    parse_manifest_yaml,
    resolve_environments,
)
from mission_control.domain.authoring.manifest_v2 import (
    MissionManifestV2,
    parse_manifest_any,
    parse_manifest_yaml_versioned,
)
from mission_control.domain.authoring.mission_definition import (
    MissionDefinition,
    manifest_to_definitions,
)
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.data_class import DEFAULT_DATA_CLASS_POLICY, DataClassPolicy
from mission_control.domain.execution.lane_requirements import RequirementSet, admit_requirements
from tests.fixtures.applications import installed_applications
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.environment_kits import StaticDefinitions
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.fixtures.models import bindings_catalog

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "tests/fixtures/manifests/multi-provider"
BINDINGS = (
    ROOT
    / "deployments/examples"
    / ("manifest-launch-bindings.multi-provider.codex-0.162.1.example.json")
)
V1_BINDINGS = ROOT / "deployments/examples/manifest-launch-bindings.deep-agents.example.json"
MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"
SCOPE = canonical_scope("tenant-1", "ai-engineer")
AT = datetime(2026, 10, 9, tzinfo=UTC)
PROFILES = ("claude_agent_sdk", "codex")
FORMS = ("stage-graph", "goal-loop", "chain")


def example(profile: str, form: str) -> Path:
    return EXAMPLES / f"{profile.replace('_', '-')}.{form}.mission.yml"


async def _compile(
    manifest_yaml: str, scope: str, data_class_policy: DataClassPolicy
) -> ManifestCompilation:
    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
        data_class_policy=data_class_policy,
    )
    return await service.compile(
        manifest_yaml, ManifestScope(request_scope=scope, actor_id="owner", at=AT)
    )


def compile_yaml(
    manifest_yaml: str,
    scope: str = SCOPE,
    data_class_policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
) -> ManifestCompilation:
    return asyncio.run(_compile(manifest_yaml, scope, data_class_policy))


def compiled_ok(manifest_yaml: str) -> ManifestCompilation:
    compilation = compile_yaml(manifest_yaml)
    assert compilation.ok, [(item.pointer, item.message) for item in compilation.report.blockers]
    return compilation


def bindings() -> ManifestLaunchBindings:
    return ManifestLaunchBindings.load(BINDINGS)


def served(bound: ManifestLaunchBindings) -> ServedComponents:
    """FIXTURE: the example file's Deep Agent components as a test deployment serves them."""

    profile = bound.deep_agents.profile
    return ServedComponents(
        models=frozenset(item.ref.digest for item in bound.model_profiles.values()),
        sandboxes=frozenset(item.ref.digest for item in bound.sandbox_profiles.values()),
        checkpointers=frozenset({profile.checkpointer_ref.digest}),
        stores=frozenset({profile.store_ref.digest}),
        qualification=True,  # OC-R6: an explicit test composition (fixture models)
    )


def resolver(bound: ManifestLaunchBindings | None = None) -> ManifestLaunchResolver:
    bound = bound or bindings()
    return compose_manifest_launch_resolver(
        bound,
        served(bound),
        applications=installed_applications(),
        models=bindings_catalog(bound),
        provider_secret_env={"openai": "OPENAI_API_KEY"},
    )


def templates_of(
    program: CompiledMission, definition: MissionDefinition, bound: ManifestLaunchBindings | None
) -> dict[str, Any]:
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-v2", program.configuration)
    target = resolver(bound)
    if program.lowered.family == "StageGraph":
        return dict(target.stage_templates(definition, admitted))
    return dict(target.goal_templates(definition, admitted))


def edited(path: Path, change: Any) -> str:
    document = load_manifest_yaml(path.read_text(encoding="utf-8"))
    change(document)
    return canonical_manifest_bytes(document).decode("utf-8")


def blockers(compilation: ManifestCompilation) -> dict[str, str]:
    return {item.pointer: str(item.reason) for item in compilation.report.blockers}


def bundle_selection(skill: str, hook: str | None) -> Any:
    """Pin a skill bundle (and a hook script) mission-wide. Goal Loop criteria are accepted by
    human review and outputs are optional, so a launch reaches its capability rows; the Deep
    Agents node of a Stage Graph example is dropped (it has no component binding here)."""

    def change(document: dict[str, Any]) -> None:
        mission = document["mission"]
        environment = mission["environment"]
        environment["workspace"]["skills"] = [{"pin": skill, "as": "observe"}]
        if hook is not None:
            environment["hooks"] = [{"pin": hook, "events": ["before_tool"], "fail_closed": True}]
        program = mission["program"]
        if program["behavior"] == "stage_graph":
            program["nodes"] = [node for node in program["nodes"] if node["key"] != "summarize"]
            return
        for goal in mission["goals"]:
            for criterion in goal["criteria"]:
                criterion["acceptance"] = {"human": "review_accept"}
        for output in program["outputs"]:
            output["enforcement"] = "optional"

    return change


def stub_author(
    definition: MissionDefinition,
    program: CompiledMission,
    *,
    projection_rows: Any,
    persisted: list[dict[str, Any]],
    target: ManifestLaunchResolver | None = None,
    kits: Any = None,
) -> ManifestLaunchInputAuthor:
    """The launch author over one compiled run, recording every template it would freeze."""

    class Runs:
        async def get_run(self, _scope: str, _run: str) -> Any:
            return SimpleNamespace(effective_configuration_digest=program.configuration.digest)

    class Plane:
        async def retrieve_for_admission(self, _digest: str) -> Any:
            return program.configuration

    class Submissions:
        async def run_subscriptions(self, _scope: str, _run: str) -> dict[str, Any]:
            return {"definition": definition.model_dump(mode="json")}

    class Templates:
        async def persist_templates(self, **values: Any) -> None:
            persisted.append(values)

        async def get_template(self, **_: Any) -> Any:
            raise ValueError("no frozen template")

        async def list_templates(self, **_: Any) -> dict[str, Any]:
            return {}

    return ManifestLaunchInputAuthor(
        resolver=target or resolver(),
        run_control=Runs(),  # type: ignore[arg-type]
        control_plane=Plane(),  # type: ignore[arg-type]
        definitions=Submissions(),
        stage_templates=Templates(),  # type: ignore[arg-type]
        goal_templates=Templates(),  # type: ignore[arg-type]
        projection_rows=projection_rows,
        kits=kits,
    )


# --- Compile dispatch: v1 exactly unchanged ----


def test_v1_documents_take_the_exact_v1_parser() -> None:
    text = MINIMAL.read_text(encoding="utf-8")
    manifest, document = parse_manifest_yaml_versioned(text)
    reference, reference_document = parse_manifest_yaml(text)
    assert type(manifest) is MissionManifest and manifest == reference
    assert document == reference_document
    definitions = manifest_to_definitions(manifest, document)
    assert all("selections" not in item.model_dump_json() for item in definitions)
    # An unknown version is rejected exactly as the v1-only parser rejects it.
    unknown = text.replace("manifest: mission/v1", "manifest: mission/v9")
    with pytest.raises(Exception) as versioned:
        parse_manifest_yaml_versioned(unknown)
    with pytest.raises(Exception) as original:
        parse_manifest_yaml(unknown)
    assert getattr(versioned.value, "issues", None) == getattr(original.value, "issues", None)


def test_v1_compile_reports_are_byte_identical_through_the_dispatching_compile() -> None:
    """The structure service gives v1 the v1 definition digest; no compiled v1 definition grows
    a selections block (the resolved digests themselves are pinned by the golden
    resolutions in ``test_manifest_compile.py``)."""

    text = MINIMAL.read_text(encoding="utf-8")
    report = ManifestStructureService().compile(text)
    manifest, document = parse_manifest_yaml(text)
    (expected,) = manifest_to_definitions(manifest, document)
    assert report.ok and report.definitions[0].definition_digest == expected.digest
    compilation = compiled_ok_scope(text)
    assert "selections" not in compilation.definitions[0].model_dump_json()
    assert compilation.definitions[0].program.selections is None


def compiled_ok_scope(text: str) -> ManifestCompilation:
    compilation = compile_yaml(text, canonical_scope("tenant-1"))
    assert compilation.ok, [(item.pointer, item.message) for item in compilation.report.blockers]
    return compilation


# --- The checked examples ----


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("form", FORMS)
def test_every_v2_example_compiles_and_lowers_with_selections(profile: str, form: str) -> None:
    text = example(profile, form).read_text(encoding="utf-8")
    manifest = parse_manifest_any(load_manifest_yaml(text))
    assert isinstance(manifest, MissionManifestV2)
    compilation = compiled_ok(text)
    families = [program.lowered.family for program in compilation.programs]
    expected = {
        "stage-graph": ["StageGraph"],
        "goal-loop": ["GoalDirected"],
        "chain": ["GoalDirected", "StageGraph"],
    }[form]
    assert families == expected
    for definition in compilation.definitions:
        stored = MissionDefinition.model_validate(definition.model_dump(mode="json"))
        # The committed form (JSON) keeps the digest and the v2 selections.
        assert stored.digest == definition.digest
        assert stored.program.selections == definition.program.selections
        selections = definition.program.selections
        assert selections is not None and selections.auth is not None
        assert selections.execution_environment is not None
        assert selections.execution_environment.kind == "local_workspace"
    if form == "goal-loop":
        (definition,) = compilation.definitions
        assert definition.program.environment.governors is not None
        assert (definition.program.environment.governors.iterations or 0) >= 2
        assert compilation.programs[0].lowered.blueprint.max_iterations >= 2  # type: ignore[union-attr]


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("form", FORMS)
def test_every_v2_example_authors_sealed_provider_bindings(profile: str, form: str) -> None:
    compilation = compiled_ok(example(profile, form).read_text(encoding="utf-8"))
    lane = bindings().providers.lane(profile)  # type: ignore[union-attr]
    assert lane is not None
    provider_templates = 0
    for definition, program in zip(compilation.definitions, compilation.programs, strict=True):
        templates = templates_of(program, definition, None)
        assert templates
        for key, template in templates.items():
            binding = ProviderExecutionBinding.carried_by(template)
            if template.execution_runtime == "deep_agent":
                assert (
                    binding is None and DeepAgentExecutionBinding.carried_by(template) is not None
                )
                continue
            provider_templates += 1
            assert binding is not None and binding.lane_profile == profile
            assert template.lane_profile == profile
            assert template.execution_runtime == ("claude" if profile != "codex" else "codex")
            assert (
                template.native_placement is None
                and DeepAgentExecutionBinding.carried_by(template) is None
            )
            assert binding.binding_digest == binding.computed_digest()
            assert binding.task_queue == lane.task_queue
            assert binding.pins == lane.pins
            assert binding.requirements.describe_digest == declared_matrix(profile).digest
            assert binding.workspace_policy.mode == "managed_worktree"
            assert binding.repo_url == "https://github.com/Overton77/mission-control-fixture"
            assert binding.auth.profile in lane.auth_profiles
            assert binding.environment.host_profile in lane.host_profiles
            assert template.secret_refs == ()
            # The lane recomputes exactly this projection digest at `prepare` (no catalog
            # capability selected: the Kernel Hooks and the operating contract only).
            assert binding.materialization_digest == projection_digest(
                HOST_PROJECTORS.render((), profile, operating_contract(template), None)
            )
            workflow = OperationWorkflowRequest(
                semantic_attempt_id=template.identity.semantic_key,
                operation_kind="bound_operation",
                operation=template,
            )
            assert workflow.activity_task_queue == lane.task_queue, key
    assert provider_templates >= 1


def test_codex_reasoning_effort_maps_to_the_typed_provider_option() -> None:
    compilation = compiled_ok(example("codex", "stage-graph").read_text(encoding="utf-8"))
    templates = templates_of(compilation.programs[0], compilation.definitions[0], None)
    patch = templates["patch/execute/default"]
    assert ProviderExecutionBinding.carried_by(patch) is not None
    options = ProviderExecutionBinding.carried_by(patch).provider_options
    assert getattr(options, "reasoning_effort", None) == "high"
    assert patch.model_policy.reasoning_effort == "high"
    assert ProviderExecutionBinding.carried_by(patch).requirements.controls == (
        "cancel",
        "queue_instruction",
        "request_continuation",
    )
    # The Deep Agents node of the same mission keeps its own lane binding.
    summarize = templates["summarize/execute/default"]
    assert (
        DeepAgentExecutionBinding.carried_by(summarize) is not None
        and ProviderExecutionBinding.carried_by(summarize) is None
    )


def test_session_budgets_are_narrowed_by_the_node_never_raised() -> None:
    compilation = compiled_ok(example("claude_agent_sdk", "stage-graph").read_text("utf-8"))
    templates = templates_of(compilation.programs[0], compilation.definitions[0], None)
    patch = ProviderExecutionBinding.carried_by(templates["patch/execute/default"])
    diagnose = ProviderExecutionBinding.carried_by(templates["diagnose/execute/default"])
    assert patch is not None and diagnose is not None
    assert patch.budgets.token_ceiling == 200_000  # node budget below the deployment ceiling
    assert diagnose.budgets.token_ceiling == 400_000
    assert patch.budgets.max_turns == 12  # continuation.max_session_turns < deployment 16
    assert patch.budgets.wall_clock_s == 7_200


def test_templates_are_deterministic_and_reused_by_the_author() -> None:
    compilation = compiled_ok(example("claude_agent_sdk", "goal-loop").read_text("utf-8"))
    (definition,), (program,) = compilation.definitions, compilation.programs
    assert templates_of(program, definition, None) == templates_of(program, definition, None)

    stored: dict[str, Any] = {}
    persisted: list[int] = []

    class Stores:
        async def persist_templates(self, **values: Any) -> None:
            persisted.append(1)
            stored.update({"executor": values["executor"], "verifier": values["verifier"]})

        async def get_template(self, *, operation_role: str, **_: Any) -> Any:
            if operation_role not in stored:
                raise ValueError("unavailable")
            return stored[operation_role]

        async def list_templates(self, **_: Any) -> dict[str, Any]:
            return {}

    class Runs:
        async def get_run(self, _scope: str, _run: str) -> Any:
            return SimpleNamespace(effective_configuration_digest=program.configuration.digest)

    class Plane:
        async def retrieve_for_admission(self, _digest: str) -> Any:
            return program.configuration

    class Definitions:
        async def run_subscriptions(self, _scope: str, _run: str) -> dict[str, Any]:
            return {"definition": definition.model_dump(mode="json")}

    def author(bound: ManifestLaunchBindings) -> ManifestLaunchInputAuthor:
        return ManifestLaunchInputAuthor(
            resolver=resolver(bound),
            run_control=Runs(),  # type: ignore[arg-type]
            control_plane=Plane(),  # type: ignore[arg-type]
            definitions=Definitions(),
            stage_templates=Stores(),  # type: ignore[arg-type]
            goal_templates=Stores(),  # type: ignore[arg-type]
        )

    with pytest.raises(ManifestCompletionUnavailable, match="schema"):
        asyncio.run(author(bindings()).bind(SCOPE, "run-v2", family="GoalDirected"))
    assert persisted == []
    # Simulate templates frozen before this launch guard existed: resume preserves them.
    stored.update(templates_of(program, definition, None))
    first = asyncio.run(author(bindings()).bind(SCOPE, "run-v2", family="GoalDirected"))
    # The deployment later drops the claude binding: a frozen run is never re-authored.
    unbound = bindings().model_copy(update={"providers": ProviderLanes()})
    second = asyncio.run(author(unbound).bind(SCOPE, "run-v2", family="GoalDirected"))
    assert first == second and persisted == []
    assert ProviderExecutionBinding.carried_by(first["executor"]) is not None
    assert ProviderExecutionBinding.carried_by(first["verifier"]) is not None


# --- V01: pointed compile blockers ----


def test_an_unsupported_required_approval_is_a_pointed_blocker() -> None:
    def require_elicitation(document: dict[str, Any]) -> None:
        node = document["mission"]["program"]["nodes"][1]
        node["environment"]["requires"]["approvals"] = ["workflow_gate", "mcp_elicitation"]

    compilation = compile_yaml(
        edited(example("claude_agent_sdk", "stage-graph"), require_elicitation)
    )
    found = blockers(compilation)
    pointer = "/mission/program/nodes/1/environment/requires/approvals/1"
    assert found.get(pointer) == "LANE_REQUIREMENT_UNSUPPORTED", found
    assert any(item.reason == "ELICITATION_NOT_FORWARDED" for item in compilation.report.blockers)
    assert not compilation.programs  # nothing lowered, nothing compiled, no provider work


def test_an_inherited_refused_control_points_at_the_mission_environment() -> None:
    """The code comes from the declared matrix (never hard-coded here): `hard_pause` has no
    delivery on the claude lane, so it is refused at the mission entry that required it."""

    describe = declared_matrix("claude_agent_sdk")
    (expected,) = admit_requirements(describe, RequirementSet(controls=("hard_pause",)))

    def require_hard_pause(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["requires"]["controls"] = ["cancel", "hard_pause"]

    compilation = compile_yaml(edited(example("claude_agent_sdk", "goal-loop"), require_hard_pause))
    assert blockers(compilation) == {"/mission/environment/requires/controls/1": expected.code}


def test_all_writes_gated_needs_enforcement_on_every_write_family() -> None:
    def gate_all_writes(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["requires"]["all_writes_gated"] = True

    compilation = compile_yaml(edited(example("codex", "goal-loop"), gate_all_writes))
    reasons = [
        (item.pointer, item.reason)
        for item in compilation.report.blockers
        if item.reason == "GATE_COVERAGE_UNENFORCEABLE"
    ]
    # Codex enforces shell and file natively and MCP emulated; network has no evidence.
    assert reasons == [
        ("/mission/environment/requires/all_writes_gated", "GATE_COVERAGE_UNENFORCEABLE")
    ]
    assert "network" in compilation.report.blockers[0].message


def test_switching_lane_revalidates_the_inherited_requirements() -> None:
    """A Deep Agents node inheriting a provider-permission requirement is refused: a child
    cannot drop the approval and the v1 Deep Agents describe cannot prove it."""

    def require_permission_everywhere(document: dict[str, Any]) -> None:
        requires = document["mission"]["environment"]["requires"]
        requires["approvals"] = ["workflow_gate", "provider_permission"]

    compilation = compile_yaml(
        edited(example("claude_agent_sdk", "stage-graph"), require_permission_everywhere)
    )
    assert blockers(compilation) == {
        "/mission/environment/requires/approvals/1": "LANE_REQUIREMENT_UNQUALIFIED"
    }
    (issue,) = compilation.report.blockers
    assert "deep_agents" in issue.message


@pytest.mark.parametrize(
    ("lane", "provider"), [("claude_cloud", "anthropic"), ("codex_cloud", "openai")]
)
def test_hosted_profiles_compile_structurally_and_their_launch_is_refused(
    lane: str, provider: str
) -> None:
    def hosted(document: dict[str, Any]) -> None:
        environment = document["mission"]["environment"]
        environment["lane"] = lane
        environment["execution_environment"] = {
            "kind": "provider_hosted",
            "provider": provider,
            "environment_ref": "env-fixture",
            "expected_revision": "rev-1",
        }
        environment["workspace"]["policy"] = {"mode": "provider_workspace", "reuse": "none"}
        environment.pop("requires")
        environment.pop("continuation", None)

    compilation = compiled_ok(edited(example("claude_agent_sdk", "goal-loop"), hosted))
    warnings = {item.pointer: item.reason for item in compilation.report.warnings}
    assert warnings.get("/mission/environment/lane") == "hosted_launch_refused"
    (definition,), (program,) = compilation.definitions, compilation.programs
    with pytest.raises(ManifestLaunchBindingError) as raised:
        templates_of(program, definition, None)
    assert raised.value.pointer == "/mission/environment/lane"
    assert "evidence-blocked" in str(raised.value)


def test_a_hosted_profile_cannot_compile_a_required_lifecycle_feature() -> None:
    def hosted_with_cancel(document: dict[str, Any]) -> None:
        environment = document["mission"]["environment"]
        environment["lane"] = "codex_cloud"
        environment["execution_environment"] = {
            "kind": "provider_hosted",
            "provider": "openai",
            "environment_ref": "env-fixture",
            "expected_revision": "rev-1",
        }
        environment["workspace"]["policy"] = {"mode": "provider_workspace", "reuse": "none"}
        environment["requires"] = {"controls": ["cancel"]}

    compilation = compile_yaml(edited(example("codex", "goal-loop"), hosted_with_cancel))
    assert blockers(compilation) == {
        "/mission/environment/requires/controls/0": "LANE_REQUIREMENT_UNSUPPORTED"
    }


# --- ADR-0050 hosted agent APIs and the mission Data Class (SPEC-06 section 8) ----


def hosted_agent_api(lane: str, provider: str, data_class: str | None) -> Any:
    """A knowledge mission on a hosted agent API: no repository, a provider workspace."""

    def change(document: dict[str, Any]) -> None:
        mission = document["mission"]
        if data_class is not None:
            mission["data_class"] = data_class
        environment = mission["environment"]
        environment["lane"] = lane
        environment["execution_environment"] = {
            "kind": "provider_hosted",
            "provider": provider,
            "environment_ref": "env-fixture",
            "expected_revision": "rev-1",
        }
        environment["workspace"] = {"policy": {"mode": "provider_workspace", "reuse": "none"}}
        environment.pop("requires")
        environment.pop("continuation", None)

    return change


HOSTED_AGENT_APIS = (("claude_managed", "anthropic"), ("codex_agents", "openai"))


@pytest.mark.parametrize(("lane", "provider"), HOSTED_AGENT_APIS)
def test_a_hosted_agent_api_knowledge_mission_compiles_without_a_repo_and_launch_is_refused(
    lane: str, provider: str
) -> None:
    text = edited(
        example("claude_agent_sdk", "goal-loop"), hosted_agent_api(lane, provider, "internal")
    )
    compilation = compiled_ok(text)
    warnings = {item.pointer: item.reason for item in compilation.report.warnings}
    assert warnings.get("/mission/environment/lane") == "hosted_launch_refused"
    (definition,), (program,) = compilation.definitions, compilation.programs
    with pytest.raises(ManifestLaunchBindingError) as raised:
        templates_of(program, definition, None)
    assert raised.value.pointer == "/mission/environment/lane"


@pytest.mark.parametrize("data_class", ["phi", "secret", "confidential"])
@pytest.mark.parametrize(("lane", "provider"), HOSTED_AGENT_APIS)
def test_a_mission_above_internal_is_refused_on_the_hosted_agent_apis(
    lane: str, provider: str, data_class: str
) -> None:
    text = edited(
        example("claude_agent_sdk", "goal-loop"), hosted_agent_api(lane, provider, data_class)
    )
    compilation = compile_yaml(text)
    assert blockers(compilation) == {"/mission/environment/lane": "DATA_CLASS_NOT_ADMITTED"}
    (blocker,) = compilation.report.blockers
    assert f"not {data_class}" in blocker.message and "/mission/data_class" in blocker.message
    assert not compilation.programs


@pytest.mark.parametrize(("lane", "provider"), HOSTED_AGENT_APIS)
def test_an_unclassified_mission_is_refused_on_the_hosted_agent_apis(
    lane: str, provider: str
) -> None:
    text = edited(example("claude_agent_sdk", "goal-loop"), hosted_agent_api(lane, provider, None))
    assert blockers(compile_yaml(text)) == {"/mission/environment/lane": "DATA_CLASS_UNDECLARED"}


def test_a_node_switching_to_a_hosted_agent_api_is_refused_at_its_own_lane() -> None:
    """The data class is the mission's; the refusal points at the node that chose the lane."""

    def phi_node_on_managed_agents(document: dict[str, Any]) -> None:
        mission = document["mission"]
        mission["data_class"] = "phi"
        node = mission["program"]["nodes"][0]
        node["environment"] = {
            "lane": "claude_managed",
            "execution_environment": {
                "kind": "provider_hosted",
                "provider": "anthropic",
                "environment_ref": "env-fixture",
                "expected_revision": "rev-1",
            },
            "workspace": {"policy": {"mode": "provider_workspace", "reuse": "none"}},
        }

    text = edited(example("claude_agent_sdk", "stage-graph"), phi_node_on_managed_agents)
    refused = {
        pointer: reason
        for pointer, reason in blockers(compile_yaml(text)).items()
        if reason.startswith("DATA_CLASS")
    }
    assert refused == {"/mission/program/nodes/0/environment/lane": "DATA_CLASS_NOT_ADMITTED"}


def binding_of(application: str, widened: dict[str, frozenset[str]] | None) -> ApplicationBinding:
    """An Application Binding as the operator seals it (HL-18), with or without hosted terms."""

    return ApplicationBinding.seal(
        application_id=application,
        installation_id=UUID("00000000-0000-0000-0000-000000000001"),
        binding_version="1",
        supabase_project_ref=f"{application}-project",
        database_secret_ref="APPLICATION_DATABASE_URL",
        accepted_issuers=frozenset({"https://issuer.invalid/auth/v1"}),
        accepted_audiences=frozenset({"authenticated"}),
        required_component_version="1.4.0",
        hosted_agent_apis=None
        if widened is None
        else HostedAgentApiTerms.model_validate({"widened_data_classes": widened}),
    )


WIDEST = {
    "claude_managed": frozenset({"confidential"}),
    "codex_agents": frozenset({"confidential"}),
}


@pytest.mark.parametrize("data_class", ["phi", "secret"])
@pytest.mark.parametrize(("lane", "provider"), HOSTED_AGENT_APIS)
def test_phi_and_secret_are_refused_on_every_hosted_agent_api_under_the_widest_binding(
    lane: str, provider: str, data_class: str
) -> None:
    """HL-18 acceptance: no Application Binding admits PHI (or secrets) onto an API lane."""

    text = edited(
        example("claude_agent_sdk", "goal-loop"), hosted_agent_api(lane, provider, data_class)
    )
    policy = binding_of("ai-engineer", WIDEST).data_class_policy
    compilation = compile_yaml(text, data_class_policy=policy)
    assert blockers(compilation) == {"/mission/environment/lane": "DATA_CLASS_NOT_ADMITTED"}
    assert not compilation.programs


@pytest.mark.parametrize(("lane", "provider"), HOSTED_AGENT_APIS)
def test_confidential_is_admitted_only_on_the_lane_its_application_binding_widened(
    lane: str, provider: str
) -> None:
    text = edited(
        example("claude_agent_sdk", "goal-loop"), hosted_agent_api(lane, provider, "confidential")
    )
    widened = binding_of("ai-engineer", {lane: frozenset({"confidential"})})
    assert compile_yaml(text, data_class_policy=widened.data_class_policy).ok
    other = "codex_agents" if lane == "claude_managed" else "claude_managed"
    elsewhere = binding_of("ai-engineer", {other: frozenset({"confidential"})})
    assert blockers(compile_yaml(text, data_class_policy=elsewhere.data_class_policy)) == {
        "/mission/environment/lane": "DATA_CLASS_NOT_ADMITTED"
    }
    unwidened = binding_of("ai-engineer", None)
    assert blockers(compile_yaml(text, data_class_policy=unwidened.data_class_policy)) == {
        "/mission/environment/lane": "DATA_CLASS_NOT_ADMITTED"
    }


@pytest.mark.parametrize(("lane", "provider"), HOSTED_AGENT_APIS)
def test_a_biotech_mission_reaches_a_hosted_agent_api_only_with_a_non_phi_class(
    lane: str, provider: str
) -> None:
    """SPEC-06 section 8: Biotech is refused unless the manifest declares a non-PHI class that
    its Application Binding admits."""

    biotech = canonical_scope("tenant-1", "biotech")
    policy = binding_of("biotech", None).data_class_policy

    def biotech_mission(data_class: str | None) -> str:
        change = hosted_agent_api(lane, provider, data_class)

        def as_biotech(document: dict[str, Any]) -> None:
            change(document)
            document["mission"]["application"] = "biotech"

        return edited(example("claude_agent_sdk", "goal-loop"), as_biotech)

    def refusal(data_class: str | None) -> dict[str, str]:
        return blockers(compile_yaml(biotech_mission(data_class), biotech, policy))

    assert refusal("phi") == {"/mission/environment/lane": "DATA_CLASS_NOT_ADMITTED"}
    assert refusal(None) == {"/mission/environment/lane": "DATA_CLASS_UNDECLARED"}
    assert refusal("internal") == {}


@pytest.mark.parametrize("profile", PROFILES)
def test_the_local_lanes_admit_every_data_class(profile: str) -> None:
    def phi(document: dict[str, Any]) -> None:
        document["mission"]["data_class"] = "phi"

    compiled_ok(edited(example(profile, "goal-loop"), phi))


# --- SPEC-02 inheritance for the v2 fields ----


def structural_blockers(text: str) -> dict[str, str]:
    manifest, document = parse_manifest_yaml_versioned(text)
    structure = resolve_environments(manifest, document)
    return {item.pointer: str(item.reason) for item in structure.blockers}


def test_a_child_cannot_widen_egress_remove_mandatory_hooks_or_raise_session_turns() -> None:
    hook = {
        "pin": "hook.citation-check@1.0.0#sha256:" + "a" * 64,
        "events": ["before_tool"],
        "fail_closed": True,
    }

    def widen(document: dict[str, Any]) -> None:
        environment = document["mission"]["environment"]
        environment["sandbox"] = {"egress": ["pubmed"]}
        environment["hooks"] = [hook]
        node = document["mission"]["program"]["nodes"][0]
        node["environment"] = {
            "sandbox": {"egress": ["pubmed", "anywhere"]},
            "hooks": [],
            "continuation": {"max_session_turns": 40},
            "requires": {"all_writes_gated": False},
        }
        environment["requires"]["all_writes_gated"] = True

    found = structural_blockers(edited(example("claude_agent_sdk", "stage-graph"), widen))
    env = "/mission/program/nodes/0/environment"
    assert found[f"{env}/sandbox/egress/1"] == "widens_authority"
    assert found[f"{env}/hooks"] == "removes_mandatory_policy"
    assert found[f"{env}/continuation/max_session_turns"] == "widens_authority"
    assert found[f"{env}/requires/all_writes_gated"] == "widens_authority"


def test_an_explicit_empty_list_clears_optional_hooks_only() -> None:
    def optional(document: dict[str, Any]) -> None:
        environment = document["mission"]["environment"]
        environment["hooks"] = [
            {"pin": "hook.note@1.0.0#sha256:" + "b" * 64, "events": ["stop"], "fail_closed": False}
        ]
        document["mission"]["program"]["nodes"][0]["environment"] = {"hooks": []}

    assert structural_blockers(edited(example("claude_agent_sdk", "stage-graph"), optional)) == {}


def test_a_node_switching_to_a_provider_lane_declares_its_placement() -> None:
    def switch(document: dict[str, Any]) -> None:
        environment = document["mission"]["environment"]
        environment.update(lane="deep_agents", model={"profile": "frontier.default"})
        environment["sandbox"] = {"profile": "research.standard"}
        environment.pop("execution_environment")
        document["mission"]["program"]["nodes"][0]["environment"] = {
            "lane": "claude_agent_sdk",
            "model": {"profile": "claude.default"},
        }

    found = structural_blockers(edited(example("claude_agent_sdk", "stage-graph"), switch))
    assert found == {"/mission/program/nodes/0/environment/execution_environment": "missing_field"}


# --- Launch refusals name their manifest pointer ----


def _goal_loop(profile: str = "claude_agent_sdk") -> tuple[MissionDefinition, CompiledMission]:
    compilation = compiled_ok(example(profile, "goal-loop").read_text(encoding="utf-8"))
    return compilation.definitions[0], compilation.programs[0]


def test_a_v1_bindings_file_has_no_provider_binding() -> None:
    definition, program = _goal_loop()
    with pytest.raises(ManifestLaunchBindingError) as raised:
        templates_of(program, definition, ManifestLaunchBindings.load(V1_BINDINGS))
    assert raised.value.pointer == "/mission/environment/lane"
    assert "providers.claude_agent_sdk" in str(raised.value)


@pytest.mark.parametrize(
    ("section", "pointer"),
    [
        ("model_profiles", "/mission/environment/model/profile"),
        ("auth_profiles", "/mission/environment/auth/profile"),
        ("host_profiles", "/mission/environment/execution_environment/profile"),
    ],
)
def test_an_unbound_selection_fails_at_its_manifest_pointer(section: str, pointer: str) -> None:
    definition, program = _goal_loop()
    bound = bindings()
    assert bound.providers is not None and bound.providers.claude_agent_sdk is not None
    lane = bound.providers.claude_agent_sdk.model_copy(update={section: {}})
    unbound = bound.model_copy(
        update={"providers": bound.providers.model_copy(update={"claude_agent_sdk": lane})}
    )
    with pytest.raises(ManifestLaunchBindingError) as raised:
        templates_of(program, definition, unbound)
    assert raised.value.pointer == pointer


def test_an_unmapped_provider_model_setting_fails_at_its_pointer() -> None:
    def temperature(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["model"]["settings"] = {"temperature": 0.2}

    compilation = compiled_ok(edited(example("claude_agent_sdk", "goal-loop"), temperature))
    with pytest.raises(ManifestLaunchBindingError) as raised:
        templates_of(compilation.programs[0], compilation.definitions[0], None)
    assert raised.value.pointer == "/mission/environment/model/settings/temperature"


def test_a_provider_node_selecting_a_capability_needs_projection_rows() -> None:
    """Capabilities project into the lane's files; without a rows resolver nothing is invented."""

    def with_skill(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["workspace"]["skills"] = [
            {"search": "biotech literature review procedure", "kind": "skill_bundle", "as": "lit"}
        ]

    compilation = compile_yaml(edited(example("claude_agent_sdk", "goal-loop"), with_skill))
    if not compilation.ok:  # the fixture skill does not declare claude host support
        assert all(
            item.reason in {"search_no_admitted_hits", "pin_lane_unsupported"}
            for item in compilation.report.blockers
        )
        return
    definition, program = compilation.definitions[0], compilation.programs[0]
    assert provider_capability_pins(definition)
    with pytest.raises(ManifestLaunchBindingError) as raised:
        templates_of(program, definition, None)
    assert raised.value.pointer.startswith("/mission/environment/workspace/skills/0")


def test_a_selected_bundle_without_custody_refuses_the_launch_at_its_pointer() -> None:
    """MO-01: a skill bundle or hook script needs its bytes; with no bundle custody composed
    the launch is a typed refusal at the selecting pointer, and nothing is frozen for a worker."""

    definitions, _search = asyncio.run(fast_track_catalog())
    published = {
        item.ref.logical_id: capability_pin(item).render()
        for item in asyncio.run(definitions.list_published_definitions())
    }
    selection = bundle_selection(
        published["skill.mission-control-observe"], published["hook.mc-policy-template"]
    )
    compilation = compiled_ok(edited(example("claude_agent_sdk", "goal-loop"), selection))
    (definition,), (program,) = compilation.definitions, compilation.programs
    persisted: list[dict[str, Any]] = []
    author = stub_author(
        definition,
        program,
        projection_rows=CatalogProjectionRows(definitions, bundles=None),
        persisted=persisted,
    )
    with pytest.raises(ManifestBundleCustodyUnavailable) as refused:
        asyncio.run(author.bind(SCOPE, "run-v2", family="GoalDirected"))
    assert refused.value.code == "bundle_custody_unavailable"
    assert refused.value.pointer == "/mission/environment/workspace/skills/0"
    assert "skill.mission-control-observe" in refused.value.reason
    assert persisted == []


# --- The deployment file and the lanes' projection ----


def test_the_bindings_file_pins_exactly_the_composed_adapters() -> None:
    document = json.loads(BINDINGS.read_text(encoding="utf-8"))
    assert ManifestLaunchBindings.model_validate(document).providers is not None

    wrong_pin = copy.deepcopy(document)
    wrong_pin["providers"]["claude_agent_sdk"]["pins"]["sdk.claude_agent_sdk"] = "0.2.164"
    with pytest.raises(ValueError, match="0.2.165"):
        ManifestLaunchBindings.model_validate(wrong_pin)

    swapped = copy.deepcopy(document)
    swapped["providers"]["claude_agent_sdk"]["provider_options"] = document["providers"]["codex"][
        "provider_options"
    ]
    with pytest.raises(ValueError, match="codex_app_server options"):
        ManifestLaunchBindings.model_validate(swapped)

    free_form = copy.deepcopy(document)
    free_form["providers"]["codex"]["provider_options"]["model_reasoning_summary"] = "auto"
    with pytest.raises(ValueError):
        ManifestLaunchBindings.model_validate(free_form)

    hosted = copy.deepcopy(document)
    hosted["providers"]["claude_cloud"] = document["providers"]["claude_agent_sdk"]
    with pytest.raises(ValueError):
        ManifestLaunchBindings.model_validate(hosted)

    v1_with_providers = copy.deepcopy(document)
    v1_with_providers["schema_version"] = "mc.manifest_launch_bindings.v1"
    with pytest.raises(ValueError, match="needs schema_version"):
        ManifestLaunchBindings.model_validate(v1_with_providers)
    # A v1 file still reads, unchanged and without a providers key.
    v1 = ManifestLaunchBindings.load(V1_BINDINGS)
    assert v1.providers is None and "providers" not in v1.model_dump(mode="json")


def test_the_operating_contract_is_the_lanes_instruction_channel() -> None:
    compilation = compiled_ok(example("codex", "stage-graph").read_text(encoding="utf-8"))
    templates = templates_of(compilation.programs[0], compilation.definitions[0], None)
    for template in templates.values():
        if ProviderExecutionBinding.carried_by(template) is not None:
            assert ProviderExecutionBinding.carried_by(
                template
            ).materialization_digest == materialization_digest(
                (),
                ProviderExecutionBinding.carried_by(template).lane_profile,
                template.prompt_segments,
                projectors=HOST_PROJECTORS,
            )


def test_the_worker_rows_resolver_reads_the_binding_pins_in_render_order() -> None:
    compilation = compiled_ok(example("claude_agent_sdk", "goal-loop").read_text("utf-8"))
    template = templates_of(compilation.programs[0], compilation.definitions[0], None)["executor"]
    binding = ProviderExecutionBinding.carried_by(template)
    assert binding is not None and binding_capability_pins(binding.pins) == ()
    asked: list[tuple[str, ...]] = []

    async def rows(pins: Any) -> dict[str, Any]:
        asked.append(tuple(pins))
        return {}

    assert asyncio.run(ProviderBindingRows(rows)(template)) == ()
    assert asked == []
    pins = {"capability.skill.b": "b@1#x", "capability.hook.a": "a@1#y", "sdk.x": "1"}
    assert binding_capability_pins(pins) == ("a@1#y", "b@1#x")


def test_projected_capabilities_are_pinned_and_rendered_like_the_lane_renders_them() -> None:
    """A claude node's Skill: the author pins it in the binding and renders its rows; the
    worker's `ProviderBindingRows` re-resolves the same rows, so `prepare` recomputes the
    same projection digest (`RenderedProjectionSource`, as the claude/codex harnesses use)."""

    from mission_control.application.agentic_components.placement import RenderedProjectionSource
    from tests.fixtures.projections.rows import skill_row

    def with_skill(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["workspace"]["skills"] = [
            {"search": "biotech literature review procedure", "kind": "skill_bundle", "as": "lit"}
        ]

    compilation = compiled_ok(edited(example("claude_agent_sdk", "goal-loop"), with_skill))
    definition, program = compilation.definitions[0], compilation.programs[0]
    (text,) = provider_capability_pins(definition)
    row = skill_row()
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-v2", program.configuration)
    executor = resolver().goal_templates(definition, admitted, rows={text: row})["executor"]
    binding = ProviderExecutionBinding.carried_by(executor)
    assert binding is not None
    (key,) = [name for name in binding.pins if name.startswith("capability.")]
    assert key.startswith("capability.skill.") and binding.pins[key] == text
    assert binding.materialization_digest == materialization_digest(
        (row,), "claude_agent_sdk", executor.prompt_segments, projectors=HOST_PROJECTORS
    )

    async def port(pins: Any) -> dict[str, Any]:
        assert tuple(pins) == (text,)
        return {text: row}

    worker = RenderedProjectionSource(ProviderBindingRows(port), projectors=HOST_PROJECTORS)
    projection = asyncio.run(
        worker.project(executor, profile="claude_agent_sdk", packet_index=None)
    )
    assert projection_digest(projection) == binding.materialization_digest


def test_an_execution_environment_of_the_other_kind_replaces_the_inherited_one() -> None:
    """Recovery 2026-10-09 (MP-20 Cursor finding): hosted over local is a replacement, not a
    deep merge (which produced an invalid selection and a 500 at submit)."""

    from mission_control.domain.authoring.manifest import merge_environment_documents

    local = {"execution_environment": {"kind": "local_workspace", "profile": "worker.linux"}}
    hosted = {
        "execution_environment": {
            "kind": "provider_hosted",
            "provider": "cursor",
            "environment_ref": "env-1",
        }
    }
    assert merge_environment_documents(local, hosted) == hosted
    assert merge_environment_documents(hosted, local) == local
    same = {"execution_environment": {"profile": "worker.linux.wsl"}}
    merged = merge_environment_documents(local, same)
    assert merged["execution_environment"] == {
        "kind": "local_workspace",
        "profile": "worker.linux.wsl",
    }


@pytest.mark.parametrize("form", ["stage-graph", "goal-loop"])
def test_codex_only_launch_without_deep_agents_scaffold(form: str) -> None:
    from mission_control.bootstrap.preflight import compose_launch_bindings

    text = example("codex", form).read_text(encoding="utf-8")
    if form == "stage-graph":
        text = edited(example("codex", form), lambda d: d["mission"]["program"]["nodes"].pop())
    compilation = compiled_ok(text)
    present = bindings()
    raw = present.model_dump(mode="json")
    raw.pop("deep_agents")
    bound = compose_launch_bindings(raw, {})
    assert "deep_agents" not in bound.model_dump(mode="json")
    target = compose_manifest_launch_resolver(
        bound,
        ServedComponents(),
        applications=installed_applications(),
        models=bindings_catalog(bound),
        provider_secret_env={"openai": "OPENAI_API_KEY"},
    )
    program = compilation.programs[0]
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-v2", program.configuration)
    templates = (
        target.stage_templates(compilation.definitions[0], admitted)
        if form == "stage-graph"
        else target.goal_templates(compilation.definitions[0], admitted)
    )
    assert templates and all(
        ProviderExecutionBinding.carried_by(item) is not None for item in templates.values()
    )
    # An unchanged present scaffold retains the existing serialized configuration.
    assert ManifestLaunchBindings.model_validate(present.model_dump(mode="json")).model_dump(
        mode="json"
    ) == present.model_dump(mode="json")


def test_selected_deep_agents_without_scaffold_refuses() -> None:
    compilation = compiled_ok(example("codex", "stage-graph").read_text(encoding="utf-8"))
    raw = bindings().model_dump(mode="json")
    raw.pop("deep_agents")
    target = compose_manifest_launch_resolver(
        ManifestLaunchBindings.model_validate(raw),
        ServedComponents(),
        applications=installed_applications(),
        models=bindings_catalog(ManifestLaunchBindings.model_validate(raw)),
        provider_secret_env={"openai": "OPENAI_API_KEY"},
    )
    admitted = AdmittedLaunch.from_configuration(
        SCOPE, "run-v2", compilation.programs[0].configuration
    )
    with pytest.raises(
        ManifestLaunchBindingError, match="selected Deep Agents lane has no scaffold"
    ):
        target.stage_templates(compilation.definitions[0], admitted)


def test_v1_launch_bindings_still_require_scaffold() -> None:
    raw = ManifestLaunchBindings.load(V1_BINDINGS).model_dump(mode="json")
    raw.pop("deep_agents")
    with pytest.raises(ValueError, match="v1 manifest launch bindings require"):
        ManifestLaunchBindings.model_validate(raw)


# --- P1: installation configuration at compile ---------------------------------------------

# FIXTURE: a distinctive value that must never be echoed by compile or launch authoring.
CONFIG_SENTINEL = "p1-sentinel-7f3c9e-never-echoed"
CONFIG_POINTER = "/mission/environment/variables/0/value_ref"


def with_config_variable(key: str) -> str:
    """The checked Claude Agent SDK Stage Graph example with one ``config:`` variable."""

    def change(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["variables"] = [
            {"name": "KS_API_URL", "value_ref": f"config:{key}"}
        ]

    return edited(example("claude_agent_sdk", "stage-graph"), change)


async def _compile_config(manifest_yaml: str, config: dict[str, str]) -> ManifestCompilation:
    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
        # The production port (no kit is pinned here): only the configuration differs.
        environment_inputs=CatalogEnvironmentInputs(
            EnvironmentKitCatalog(StaticDefinitions()), config=config
        ),
    )
    return await service.compile(
        manifest_yaml, ManifestScope(request_scope=SCOPE, actor_id="owner", at=AT)
    )


def compile_config(manifest_yaml: str, config: dict[str, str]) -> ManifestCompilation:
    return asyncio.run(_compile_config(manifest_yaml, config))


def compile_output(compilation: ManifestCompilation) -> str:
    """Everything compile returns, serialized: report, resolution, definitions, programs."""

    assert compilation.resolution is not None
    return json.dumps(
        {
            "report": compilation.report.model_dump(mode="json"),
            "resolution": compilation.resolution.model_dump(mode="json"),
            "definitions": [item.model_dump(mode="json") for item in compilation.definitions],
            "configurations": [
                item.configuration.model_dump(mode="json") for item in compilation.programs
            ],
        },
        sort_keys=True,
    )


def compile_digests(compilation: ManifestCompilation) -> tuple[object, ...]:
    assert compilation.resolution is not None
    return (
        compilation.resolution.model_dump_json(),
        tuple(item.digest for item in compilation.definitions),
        tuple(item.configuration.digest for item in compilation.programs),
    )


def test_a_config_reference_resolves_and_its_value_never_leaves_compile_or_launch() -> None:
    text = with_config_variable("knowledge_services.public_url")
    config = {"knowledge_services.public_url": CONFIG_SENTINEL}
    first = compile_config(text, config)
    assert first.ok, blockers(first)
    assert not [item for item in first.report.blockers if str(item.reason).startswith("config")]
    # Compile records the reference, never the value: not in any compile output ...
    output = compile_output(first)
    assert "config:knowledge_services.public_url" in output
    assert CONFIG_SENTINEL not in output
    # ... nor in the launch templates authored from the compiled programs.
    for definition, program in zip(first.definitions, first.programs, strict=True):
        templates = templates_of(program, definition, None)
        assert templates
        dumped = json.dumps([item.model_dump(mode="json") for item in templates.values()])
        assert CONFIG_SENTINEL not in dumped
    # Identical input, identical compile digests; the value does not enter them either.
    assert compile_digests(compile_config(text, config)) == compile_digests(first)
    other = compile_config(text, {"knowledge_services.public_url": "https://other.example"})
    assert compile_digests(other) == compile_digests(first)


def test_a_config_reference_without_a_value_stays_config_unresolved() -> None:
    compilation = compile_config(with_config_variable("knowledge_services.public_url"), {})
    assert blockers(compilation) == {CONFIG_POINTER: "config_unresolved"}


@pytest.mark.parametrize("supplied", [True, False], ids=["supplied", "empty-source"])
@pytest.mark.parametrize(
    "key", ["service.api_key", "github.token", "DB_PASSWORD", "supabase.dsn", "client_secret"]
)
def test_a_secret_like_config_reference_is_refused_on_the_key_alone(
    key: str, supplied: bool
) -> None:
    # Refused whether a source supplies it or (as in production, the loader refuses one)
    # nothing does: the check depends on the key only and precedes resolution.
    config = {key: CONFIG_SENTINEL} if supplied else {}
    compilation = compile_config(with_config_variable(key), config)
    assert blockers(compilation) == {CONFIG_POINTER: "config_secret_like"}
    (issue,) = compilation.report.blockers
    assert issue.code == "INVALID_DEFINITION"
    assert key in issue.message
    assert CONFIG_SENTINEL not in compilation.report.model_dump_json()

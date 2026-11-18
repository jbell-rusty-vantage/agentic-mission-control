"""One manifest node from compile to one Deep Agents turn, with only the model scripted.

The OVE-238 gap proofs G1 (`tests/unit/deep_agents/test_manifest_to_turn.py`) and G2
(`tests/unit/outputs/test_promises_end_to_end.py`) drive the production steps in order:

1. `ManifestCompileService` over the fast-track fixture catalog (`compile_manifest`);
2. the launch inputs: `ManifestLaunchResolver.stage_templates`, whose Deep Agents template step
   (`DeepAgentsLaneBindings`) seals each node's exact binding (`launch_resolver`);
3. the Stage Graph admission: the real interpreter proposes the first stage of the compiled
   blueprint and `StageGraphOperationPreparationService.prepare` rebinds the template to that
   live attempt (`admit_first_stage`);
4. the operation boundary's invocation: the binding, a checkpoint lineage plan and the
   authored run budget inside the turn (`runtime_invocation`, `run_budget`);
5. the harness, the runtime adapter and the exact materializer over an `ExactComponentRegistry`
   whose model factory records what it was asked to build and returns the scripted model
   (`turn_registry`).

The deployment is the fixture launch bindings (`manifest_launch_fixture`): the qualification
MCP server (a real stdio process, no network) serves `mcp.pubmed`, and the WP-CP-040 Skill
bundle serves the catalog Skill a manifest selects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from mission_control.adapters.deep_agents import (
    ExactComponentRegistry,
    ResolvedSkillBundle,
    StateSandboxFactory,
)
from mission_control.adapters.deep_agents.binding import execution_binding
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    CapabilityComponentBinding,
    ManifestLaunchBindings,
    ManifestLaunchResolver,
    ServedComponents,
)
from mission_control.application.authoring.manifest_service import (
    CompiledMission,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.application.authoring.manifest_submit import budget_envelope
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.execution.operations.operation_execution import (
    InMemoryOperationBindingRepository,
    bind_operation_execution_request,
    in_turn_run_budget,
)
from mission_control.application.programs.service import (
    StageGraphOperationPreparationService,
    StaticStageGraphOperationTemplateProvider,
)
from mission_control.application.resolution.registries import ModelCatalog
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    MaterializedWorkspace,
    OperationExecutionBinding,
    OperationExecutionRequest,
    RuntimeInvocation,
)
from mission_control.domain.policies.contracts import BudgetState
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    StageGraphAdmissionActivityRequest,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.support.applications import installed_applications
from tests.support.checkpoint_lineage import activity_attempt
from tests.support.deep_agents import exact_fixture
from tests.support.lane_bindings import LANE_REBINDERS
from tests.support.manifests.launch_inputs import SCOPE, SECRETS, admitted
from tests.support.manifests.seeded_catalog import fast_track_catalog, publish_output_schemas
from tests.support.model_catalog import fixture_model_profile
from tests.unit.authoring.manifest_launch_fixture import (
    fixture_bindings,
    fixture_served,
    pubmed_bound,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "tests/fixtures/manifests"
RUN_ID = "run-manifest-turn"
ADMITTED_AT = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
SKILL_CAPABILITY = "skill.biotech-literature-review"
MCP_CAPABILITY = "mcp.pubmed"


def manifest_text(name: str, **edits: Any) -> str:
    """A fixture manifest; each `edits` key is a `/`-separated path under `mission` to set."""

    text = (MANIFESTS / name).read_text(encoding="utf-8")
    if not edits:
        return text
    document = load_manifest_yaml(text)
    for path, value in edits.items():
        target = document["mission"]
        *parents, leaf = path.split("/")
        for part in parents:
            target = target[int(part)] if isinstance(target, list) else target[part]
        target[leaf] = value
    return canonical_manifest_bytes(document).decode("utf-8")


async def compile_manifest(
    text: str, *, output_schemas: Mapping[str, dict[str, Any]] | None = None
) -> tuple[MissionDefinition, CompiledMission]:
    """The one mission of a manifest, compiled by `ManifestCompileService` over the fast-track
    fixture catalog, with `output_schemas` published as its output-schema authority (refuses
    with the blockers otherwise)."""

    definitions, search = await fast_track_catalog()
    if output_schemas:
        await publish_output_schemas(definitions, output_schemas)
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    compilation = await service.compile(
        text, ManifestScope(request_scope=SCOPE, actor_id="owner", at=ADMITTED_AT)
    )
    assert compilation.ok, [item.message for item in compilation.report.blockers]
    return compilation.definitions[0], compilation.programs[0]


def capability_digest(definition: MissionDefinition, capability_id: str) -> str:
    item = next(
        item
        for item in definition.capabilities
        if item.resolved is not None and item.resolved.capability_id == capability_id
    )
    assert item.resolved is not None and item.resolved.digest is not None
    return item.resolved.digest


@dataclass(frozen=True)
class Deployment:
    """What the test deployment serves: launch bindings, served digests, Skill bundles."""

    bindings: ManifestLaunchBindings
    served: ServedComponents
    skill_bundles: Mapping[str, ResolvedSkillBundle] = field(default_factory=dict)


def deployment(
    definition: MissionDefinition,
    *,
    extra: Mapping[str, CapabilityComponentBinding] | None = None,
) -> Deployment:
    """FIXTURE: the fixture bindings, plus the qualification MCP server for `mcp.pubmed` and the
    WP-CP-040 Skill for the catalog Skill, each only when the definition selects it."""

    selected = {
        item.resolved.capability_id for item in definition.capabilities if item.resolved is not None
    }
    bindings = fixture_bindings()
    if MCP_CAPABILITY in selected:
        bindings = pubmed_bound(bindings, capability_digest(definition, MCP_CAPABILITY))
    capabilities = dict(bindings.capabilities)
    bundles: dict[str, ResolvedSkillBundle] = {}
    if SKILL_CAPABILITY in selected:
        probe, _profile, bundle = exact_fixture()
        (skill,) = probe.skills
        capabilities[SKILL_CAPABILITY] = CapabilityComponentBinding(
            catalog_digest=capability_digest(definition, SKILL_CAPABILITY),
            kind="skill",
            skill=skill,
        )
        bundles[bundle.bundle_digest] = bundle
    capabilities.update(dict(extra or {}))
    bindings = bindings.model_copy(update={"capabilities": capabilities})
    served = replace(
        fixture_served(bindings),
        mcp_servers=frozenset(
            item.mcp_server.ref.digest
            for item in capabilities.values()
            if item.mcp_server is not None
        ),
        skills=frozenset(bundles),
        tools=frozenset(
            item.tool.ref.digest for item in capabilities.values() if item.tool is not None
        ),
    )
    return Deployment(bindings=bindings, served=served, skill_bundles=bundles)


def catalog(models: Mapping[str, str]) -> ModelCatalog:
    """FIXTURE Model Catalog: one row per profile name, naming the given model id."""

    return ModelCatalog(
        tuple(fixture_model_profile(name, model_id=model) for name, model in models.items())
    )


def launch_resolver(target: Deployment, models: ModelCatalog) -> ManifestLaunchResolver:
    return compose_manifest_launch_resolver(
        target.bindings,
        target.served,
        applications=installed_applications(),
        models=models,
        provider_secret_env=SECRETS,
    )


def launch(program: CompiledMission, run_id: str = RUN_ID) -> AdmittedLaunch:
    return admitted(program, run_id=run_id)


@dataclass(frozen=True)
class StageAdmission:
    """The admitted stage: the family's admission request and the live operation it built."""

    request: StageGraphAdmissionActivityRequest
    operation: OperationExecutionRequest


async def admit_first_stage(
    templates: Mapping[str, OperationExecutionRequest],
    admitted_launch: AdmittedLaunch,
) -> StageAdmission:
    """The live operation of the blueprint's first stage, as the Stage Graph admits it."""

    interpreter = StageGraphInterpreter(admitted_launch.blueprint, effective_max_concurrency=1)
    projection = interpreter.initial_projection(
        identity=ExecutionIdentity(admitted_launch.run_id), run_version=1
    )
    proposal = interpreter.frontier(projection, available_concurrency=1)[0]
    request = StageGraphAdmissionActivityRequest(
        run_id=admitted_launch.run_id,
        request_scope=admitted_launch.request_scope,
        projection=projection,
        proposal=proposal,
        operation=None,
        blueprint=admitted_launch.blueprint.model_dump(mode="json"),
        effective_max_concurrency=1,
        occurred_at=ADMITTED_AT,
        idempotency_issuer="stagegraph-worker",
        correlation_id="stagegraph:manifest-turn",
        semantic_input_binding_ref=f"semantic-input:{admitted_launch.run_id}",
        effective_configuration_digest=admitted_launch.configuration_digest,
    )
    preparation = StageGraphOperationPreparationService(
        lane_bindings=LANE_REBINDERS,
        templates=StaticStageGraphOperationTemplateProvider(dict(templates)),
        operation_bindings=InMemoryOperationBindingRepository(),
    )
    return StageAdmission(request, (await preparation.prepare(request)).operation)


def run_budget(
    program: CompiledMission, binding: OperationExecutionBinding
) -> tuple[tuple[str, ...], dict[str, int]]:
    """The authored run budget inside the turn (W1 D41), as the operation boundary computes it
    from a freshly admitted run: the run account holds the compiled budget envelope's limits
    (`RunControlService` admission) and has spent nothing yet."""

    envelope = budget_envelope(program.configuration)
    state = BudgetState(
        account_id=f"budget-account:{binding.run_id}",
        run_id=binding.run_id,
        limits=envelope.dimensions,
        reserved=dict(envelope.baseline_reservations),
    )
    return in_turn_run_budget(state, binding)


async def runtime_invocation(
    operation: OperationExecutionRequest, program: CompiledMission
) -> RuntimeInvocation:
    """The invocation the operation boundary hands the lane for the first attempt."""

    binding = bind_operation_execution_request(operation)
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    plan = await lineage.observe_attempt(binding, activity_attempt(1), dispatching=True)
    dimensions, remaining = run_budget(program, binding)
    return RuntimeInvocation(
        binding=binding,
        prompt_segments=operation.prompt_segments,
        workspace=MaterializedWorkspace(
            workspace_id=operation.workspace.workspace_id,
            namespace_id=operation.workspace.namespace_id,
            provider=operation.workspace.provider,
            runtime_digest=operation.workspace.runtime_digest,
            image_digest=operation.workspace.image_digest,
            mount_manifest_digest=sha256_digest(f"mounts:{operation.workspace.workspace_id}"),
        ),
        resolved_secret_names=tuple(
            sorted(f"{ref.provider}:{ref.key}" for ref in binding.secret_refs)
        ),
        checkpoint_plan=plan,
        run_budget_dimensions=dimensions,
        run_budget_remaining=remaining,
    )


def resolved_secrets(invocation: RuntimeInvocation) -> dict[str, str]:
    """FIXTURE secret values for the invocation's refs (the scripted model reads none)."""

    return {name: f"fixture-{index}" for index, name in enumerate(invocation.resolved_secret_names)}


@dataclass
class ModelRequests:
    """The model components the materializer asked the deployment's factory to build."""

    built: list[DeepAgentExecutionBinding] = field(default_factory=list)


def turn_registry(
    operation: OperationExecutionRequest,
    target: Deployment,
    model: BaseChatModel,
    *,
    tools: Mapping[str, BaseTool] | None = None,
) -> tuple[ExactComponentRegistry, ModelRequests]:
    """The worker's component registry for the operation's exact binding: the model factory
    records each request and answers with the scripted model; State sandbox; in-memory saver
    and store; the deployment's Skill bundles and tools, by digest."""

    binding = execution_binding(operation)
    requests = ModelRequests()

    def factory(bound: DeepAgentExecutionBinding, _secrets: Mapping[str, str]) -> BaseChatModel:
        requests.built.append(bound)
        return model

    registry = ExactComponentRegistry(
        model_factories={binding.model.ref.digest: factory},
        skill_bundles=dict(target.skill_bundles),
        sandbox_factories={binding.sandbox.ref.digest: StateSandboxFactory()},
        checkpointers={binding.checkpointer_ref.digest: InMemorySaver()},
        stores={binding.store_ref.digest: InMemoryStore()},
        tools=dict(tools or {}),
    )
    return registry, requests

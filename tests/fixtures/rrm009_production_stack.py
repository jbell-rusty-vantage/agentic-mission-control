"""RRM-009 production-shaped stack: the real API composition plus the deployment worker factory.

The catalog is published through the real `ControlPlaneService` into PostgreSQL and compiled into
an Effective Run Configuration the real admission verifier and operation authority read. Only
the model is deterministic: a technical model registered under the exact fixture model
digest, exactly as a deployment registers a provider factory.

Technical inputs only (RRM-009 §2): a two-stage StageGraph with a declared wait and a
two-iteration GoalDirected run. No company fixture, no research run.

FX-TR (TRACING-PROPOSAL §P9, "Fixture work first"): a third family tag, ``StageGraphTracing``,
publishes the four-stage ``S1 -> S2 -> {S3, S4}`` blueprint whose ``S2`` carries a
``StageCyclePolicy(max_cycles=3)``; the scripted model cycles ``S2`` twice (stage cycle
ordinals 0 and 1 answer ``evaluation: cycle``, ordinal 2 accepts), deterministically from the
operation id. The two-stage blueprint and the GoalDirected run are untouched.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from tests.acceptance.control_plane.test_wp_cp_040 import (
    MCP_TOOL_SCHEMA_DIGEST,
    exact,
    exact_fixture,
)
from tests.fixtures import rrm009_mcp_server
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.unit.operations.test_operation_execution import operation_request
from tests.unit.run_control.test_run_control import request as run_request

from mission_control.adapters.capabilities.capability_bundles import bundle_digest
from mission_control.adapters.deep_agents.materializer import (
    ResolvedHookScriptBundle,
    ResolvedSkillBundle,
)
from mission_control.adapters.temporal.deployment_composition import DeploymentCapabilityComponents
from mission_control.adapters.temporal.registration.task_queues import BellLabsTaskQueues
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.execution.service import AdmissionPolicyRegistry
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    AllowedOperationVariant,
    AuthorityCeiling,
    BudgetCeiling,
    CompilationContext,
    CompileInvocation,
    ControlProfileDefinition,
    DefinitionKind,
    DefinitionSelector,
    EffectiveRunConfiguration,
    EnvironmentAvailability,
    EvaluationProfileDefinition,
    ExactDefinitionRef,
    GoalDirectedBlueprint,
    LateResultPolicy,
    LateResultRule,
    PublishRequest,
    RunInputManifestRef,
    RuntimeProfileDefinition,
    SecretRef,
    SlowSiblingPolicy,
    StageCyclePolicy,
    StageDependency,
    StageGraphBlueprint,
    StageGraphWait,
    StageInputSlot,
    StageJoin,
    StageNode,
    StageOperationSlot,
    StageOutputSlot,
    WorkflowTypeDefinition,
    WorkflowWorkspaceContract,
    WorkspaceSlot,
    WorkspaceTemplateDefinition,
)
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    DeepAgentHookScriptComponent,
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
    DeepAgentModelComponent,
    OperationExecutionRequest,
    PromptSegment,
    PromptTrustClass,
    StructuredOutputBinding,
    SyncSubagentProfile,
    WorkspaceContract,
    WorkspaceOwner,
    WorkspaceOwnerKind,
    WorkspaceSlotBinding,
)
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    BudgetDimensionLimit,
    BudgetEnvelope,
    RunRequest,
)
from mission_control.domain.programs.contracts import (
    GoalDirectedRunInput,
    GoalDirectedStartPosition,
    GoalRevision,
    StageGraphRunInput,
)

# Canonical `mc/{installation}/{application}/{tenant}` scope of the disposable common DB.
SCOPE = canonical_scope("tenant-1")
OPERATOR = "operator"
WAIT_ID = "release-review"
GOAL_OBLIGATION = "fixture-obligation"
GOAL_OUTPUT_CONTRACT = "fixture-output"
INPUT_CONTRACT = "contract:rrm009-input@1"
INVARIANT = "contract:rrm009-invariant@1"
CHILD_NAME = "technical-child"
CHILD_MARKER = "RRM009-CHILD-OK"
ANSWER_MARKER = "RRM009-OK"
MCP_CODE = "RRM009"
REPORT_PATH = "/workspace/output/report.md"
# F-T3-1 (T0): the scripted Goal role's prose answer under the PROSE_ROLE switch.
PROSE_EXECUTOR_ANSWER = (
    "I wrote the report to the work slot and checked the binding marker; the record is done."
)
# The provisioned runtime checkpoint schema (packages/mission-control-db-contract/runtime).
LANGGRAPH_SCHEMA = "mission_control_runtime"
TOKENS_PER_CALL = 5
TASK_QUEUE = "rrm009"
# The placement's task queue must be the deployment's agent-cognitive queue: the family
# dispatches `operation.execute` on the binding's own queue (REQ-CP-DA-004 placement).
AGENT_COGNITIVE_QUEUE = BellLabsTaskQueues.from_base(TASK_QUEUE).agent_cognitive
NODE_EXECUTABLE = Path("C:/Program Files/nodejs/node.exe")

TECHNICAL_CEILINGS = {
    "tokens.total": 400,
    "model.turns": 80,
    "operation.attempts": 12,
    "goal.iterations": 6,
}
MAX_CONCURRENCY = 2
# Tracing Stage 2 (live fixtures): one unit's reservation (the stage slot, the template's
# `budget_limits`, the Goal iteration reservation besides `goal.iterations`), the stage and
# goal objectives by stage id / role, and the Goal observation schema digests by role. The
# defaults are the T0 values; `tests/acceptance/mission_control/test_tracing_live.py` sets
# them per live fixture with `monkeypatch.setattr`.
UNIT_RESERVATION: dict[str, int] = {"tokens.total": 40, "model.turns": 8}
STAGE_OBJECTIVES: dict[str, str] = {}
GOAL_OBJECTIVES: dict[str, str] = {}
GOAL_SCHEMA_DIGESTS: dict[str, str] = {}

# --- FX-TR: the tracing Stage Graph (TRACING-PROPOSAL §P9) ---------------------------------
# Family tag selected by `prepare_run(stack, TRACING_FAMILY)`; it is a Stage Graph run whose
# launch body still says `family: StageGraph` (the family switch is a fixture concern).
TRACING_FAMILY = "StageGraphTracing"
STAGE_FAMILIES = frozenset({"StageGraph", TRACING_FAMILY})
TRACING_STAGES = ("S1", "S2", "S3", "S4")
TRACING_CYCLE_STAGE = "S2"
# `StageCyclePolicy.max_cycles`: the interpreter refuses a cycle once the current stage cycle
# ordinal reaches it (`interpreter.py:540`), so 3 allows ordinals 0 -> 1 -> 2 (two cycles).
TRACING_MAX_CYCLES = 3
# The scripted model answers `evaluation: cycle` while the stage cycle ordinal is below this.
TRACING_CYCLES = 2
# The frozen contracts `apply_cycle` checks the evaluation against (`service.py:872-877`).
TRACING_EVALUATION_CONTRACT = "contract:rrm009-tracing-evaluation@1"
TRACING_OBJECTIVE_CONTRACT = "contract:rrm009-tracing-objective@1"
# Hard caps bound reserved + consumed (`reducer.py:_enforce_hard_caps`). The tracing run
# admits up to ten units (S1@c0; S2, S3 and S4 at cycles 0, 1 and 2: a cycle applies only
# once the consumers S2's accepted result released have settled, `stagegraph.py:963`), each
# reserving the slot's 40 tokens / 8 turns and consuming 25 tokens / 5 turns, plus the
# baseline hold and the three stage-cycle units; the caps are sized well above that.
TRACING_CEILINGS = {
    "tokens.total": 2000,
    "model.turns": 400,
    "operation.attempts": 48,
    "goal.iterations": 6,
    "stage.cycles": 8,
}
# `artifact.promote` is the governed promotion authority the generic artifact path verifies
# on the producer binding (`ArtifactPromotionService._validate_authority`).
CAPABILITIES = frozenset(
    {"model.invoke", "sandbox.execute", "mcp.call", "subagent.task", "artifact.promote"}
)

# --- FX-TR-STEP / FX-TR-HOOK fixture pieces (TRACING-PROPOSAL §P9, "Fixture work first") ----
# The exact MCP server of the binding is the fixture-owned `tests/fixtures/rrm009_mcp_server.py`
# (the same `lookup_binding_marker` schema as the qualification module, so the pinned
# `MCP_TOOL_SCHEMA_DIGEST` holds; its result is the marker plus padding to at least 12 KiB).
MCP_SERVER_SCRIPT = Path(rrm009_mcp_server.__file__).resolve()
MCP_TOOL_NAME = "lookup_binding_marker"
MCP_RESULT_MIN_BYTES = rrm009_mcp_server.PAYLOAD_MIN_BYTES
# One catalog hook script bound to the tracing family's stage operations: `before_tool` on
# the MCP tool, decision `allow` with an `additional_context` annotation the middleware
# appends to the tool result (`HookScriptMiddleware._post`). The hook id is a non-kernel id
# (`DeepAgentExecutionBinding` refuses `mc.*`), run after `KERNEL_HOOK_IDS`.
TRACING_HOOK_ID = "rrm009.annotate"
TRACING_HOOK_CONTEXT = "RRM009-HOOK-ANNOTATED"
TRACING_HOOK_ENTRYPOINT = "annotate.py"
TRACING_HOOK_SCRIPT = f'''"""FX-TR-HOOK catalog hook: allow the tool call and annotate it."""
import json
import sys

hook_input = json.loads(sys.stdin.read() or "{{}}")
tool = hook_input.get("tool") or {{}}
sys.stdout.write(
    json.dumps(
        {{
            "schema_version": "mc.hook_result.v1",
            "decision": "allow",
            "additional_context": "{TRACING_HOOK_CONTEXT}::" + str(tool.get("name") or ""),
        }}
    )
)
'''
# Catalog hook bundles reach the materializer through `ExactComponentRegistry.hook_scripts`;
# `DeploymentCapabilityComponents` (the qualification's registration surface) carries no such
# field yet (`deployment_composition.py:350-369`, and `:437` forwards none). The hook is bound
# only once it can be registered, so every other proof keeps materializing; FX-TR-HOOK reports
# the gap exactly until the source change lands.
HOOK_SCRIPTS_REGISTRABLE = "hook_scripts" in {
    item.name for item in fields(DeploymentCapabilityComponents)
}


def tracing_mcp_server() -> DeepAgentMCPServerComponent:
    """The exact stdio MCP server component the binding carries and the worker registers.

    The verifier compares the binding's component with the registered one by full equality
    (`runtime_ports.py::PinnedCapabilityAssetVerifier.verify_launch`), so both sides build it
    here. The launch is `sys.executable <script>`: the server process imports no `tests.*`.
    """

    return DeepAgentMCPServerComponent(
        ref=exact(DefinitionKind.MCP_SERVER, "mcp.rrm009-tracing", "rrm009-tracing-mcp"),
        server_name="qualification",
        transport="stdio",
        command=sys.executable,
        arguments=(str(MCP_SERVER_SCRIPT),),
        tools=(
            DeepAgentMCPToolComponent(
                tool_name=MCP_TOOL_NAME, schema_digest=MCP_TOOL_SCHEMA_DIGEST
            ),
        ),
        schema_digest=sha256_digest("rrm009-tracing-mcp-schema-v1"),
        attachment_target="agent.main",
    )


def tracing_hook_bundle() -> ResolvedHookScriptBundle:
    """The hook script directory as the materializer verifies it (manifest digest of files)."""

    files = ((TRACING_HOOK_ENTRYPOINT, TRACING_HOOK_SCRIPT.encode("utf-8")),)
    return ResolvedHookScriptBundle(
        manifest_digest=bundle_digest(files, require_skill_md=False), files=files
    )


def tracing_hook_component(bundle: ResolvedHookScriptBundle) -> DeepAgentHookScriptComponent:
    """The hook component pinned into the tracing family's Deep Agents binding."""

    return DeepAgentHookScriptComponent(
        ref=exact(DefinitionKind.HOOK_SCRIPT, "hook.rrm009-annotate", "rrm009-annotate-hook"),
        hook_id=TRACING_HOOK_ID,
        order=0,
        events=("before_tool",),
        matcher=f"^{MCP_TOOL_NAME}$",
        timeout_seconds=30,
        fail_closed=False,
        interpreter="python",
        entrypoint=TRACING_HOOK_ENTRYPOINT,
        manifest_digest=bundle.manifest_digest,
        callback="none",
    )


# --- Catalog ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class TechnicalCatalog:
    family: str
    erc: EffectiveRunConfiguration
    workflow_ref: ExactDefinitionRef
    workspace_ref: ExactDefinitionRef
    blueprint: StageGraphBlueprint | GoalDirectedBlueprint

    @property
    def blueprint_digest(self) -> str:
        return sha256_digest(self.blueprint)


def _stage_slot() -> StageOperationSlot:
    return StageOperationSlot(
        operation_slot_id="execute",
        reservation=dict(UNIT_RESERVATION),
        allowed_variants=(
            AllowedOperationVariant(
                operation_variant_id="default",
                operation_contract_ref="operation:rrm009-technical@1",
            ),
        ),
    )


def stage_blueprint() -> StageGraphBlueprint:
    """`draft` -> declared wait `release-review` -> `review`."""

    dependency = StageDependency(
        dependency_id="draft-to-review",
        consumer_stage_id="review",
        join_id="draft-ready",
        producer_stage_id="draft",
        producer_output_slot_id="result",
        consumer_input_slot_id="draft-input",
        dependency_class="required",
    )
    return StageGraphBlueprint(
        logical_id="rrm009-technical-stagegraph",
        title="RRM-009 technical StageGraph",
        description="Draft, a declared wait, then review; technical inputs only.",
        stages=(
            StageNode(
                stage_id="draft",
                output_slots=(
                    StageOutputSlot(output_slot_id="result", output_contract_ref="output:draft@1"),
                ),
                operation_slots=(_stage_slot(),),
            ),
            StageNode(
                stage_id="review",
                input_slots=(StageInputSlot(input_slot_id="draft-input"),),
                output_slots=(
                    StageOutputSlot(output_slot_id="result", output_contract_ref="output:review@1"),
                ),
                operation_slots=(_stage_slot(),),
            ),
        ),
        joins=(
            StageJoin(
                consumer_stage_id="review",
                join_id="draft-ready",
                kind="all",
                dependency_ids=(dependency.dependency_id,),
                slow_sibling_policy=SlowSiblingPolicy(
                    triggers=("join_released",),
                    execution_action="continue",
                    arrival_route="evaluate_late_result",
                ),
            ),
        ),
        dependencies=(dependency,),
        late_result_policy=LateResultPolicy(
            rules=(
                LateResultRule(
                    rule_id="admit-late",
                    trigger="consumer_already_admitted",
                    decision="admit",
                ),
            )
        ),
        waits=(StageGraphWait(scope_kind="stage", scope_id="review", wait_id=WAIT_ID),),
    )


def tracing_stage_blueprint() -> StageGraphBlueprint:
    """FX-TR: `S1 -> S2 -> {S3, S4}`, every dependency required, every join `all`, no wait;
    `S2` carries `StageCyclePolicy(max_cycles=3)` so the scripted model can cycle it twice."""

    def dependency(producer: str, consumer: str) -> StageDependency:
        return StageDependency(
            dependency_id=f"{producer}-to-{consumer}",
            consumer_stage_id=consumer,
            join_id=f"{consumer}-ready",
            producer_stage_id=producer,
            producer_output_slot_id="result",
            consumer_input_slot_id=f"{producer}-input",
            dependency_class="required",
        )

    dependencies = (dependency("S1", "S2"), dependency("S2", "S3"), dependency("S2", "S4"))
    inputs = {edge.consumer_stage_id: edge for edge in dependencies}

    def stage(stage_id: str) -> StageNode:
        edge = inputs.get(stage_id)
        return StageNode(
            stage_id=stage_id,
            input_slots=(
                (StageInputSlot(input_slot_id=edge.consumer_input_slot_id),)
                if edge is not None
                else ()
            ),
            output_slots=(
                StageOutputSlot(
                    output_slot_id="result", output_contract_ref=f"output:{stage_id.lower()}@1"
                ),
            ),
            operation_slots=(_stage_slot(),),
            stage_cycle_policy=(
                StageCyclePolicy(
                    max_cycles=TRACING_MAX_CYCLES,
                    evaluation_contract_ref=TRACING_EVALUATION_CONTRACT,
                    objective_contract_ref=TRACING_OBJECTIVE_CONTRACT,
                    reservation={"stage.cycles": 1},
                )
                if stage_id == TRACING_CYCLE_STAGE
                else None
            ),
        )

    return StageGraphBlueprint(
        logical_id="rrm009-tracing-stagegraph",
        title="FX-TR tracing StageGraph",
        description="S1, then S2 cycled twice, then S3 and S4; technical inputs only.",
        stages=tuple(stage(stage_id) for stage_id in TRACING_STAGES),
        joins=tuple(
            StageJoin(
                consumer_stage_id=edge.consumer_stage_id,
                join_id=edge.join_id,
                kind="all",
                dependency_ids=(edge.dependency_id,),
                slow_sibling_policy=SlowSiblingPolicy(
                    triggers=("join_released",),
                    execution_action="continue",
                    arrival_route="evaluate_late_result",
                ),
            )
            for edge in dependencies
        ),
        dependencies=dependencies,
        late_result_policy=LateResultPolicy(
            rules=(
                LateResultRule(
                    rule_id="admit-late",
                    trigger="consumer_already_admitted",
                    decision="admit",
                ),
            )
        ),
    )


def tracing_cycle_evaluation(operation_id: str) -> dict[str, Any]:
    """The stage evaluation the scripted model adds to its answer, from the operation id alone.

    The id carries the candidate's `stage-cycle:N` (`StageExecutionIdentity.operation_id`),
    so a worker restart or a retried attempt answers identically. Only `S2` below
    `TRACING_CYCLES` cycles: `evaluation: cycle` with `cycle_scope: stage` is what
    `StageGraphWorkflow` reads (`workflows/stagegraph.py:843-881`) and what
    `ProgramService.apply_cycle` validates against the frozen contracts (`service.py:872-877`);
    the next objective must differ from the current cycle's (`interpreter.py:552-556`).
    """

    if ":stage:" not in operation_id:
        return {}
    stage = operation_id.split(":stage:", 1)[1].split(":", 1)[0]
    if stage != TRACING_CYCLE_STAGE or ":stage-cycle:" not in operation_id:
        return {}
    ordinal = int(operation_id.split(":stage-cycle:", 1)[1].split(":", 1)[0])
    if ordinal >= TRACING_CYCLES:
        return {"evaluation": "accept"}
    return {
        "evaluation": "cycle",
        "cycle_scope": "stage",
        "invalidation_frontier": [stage],
        "next_objective": (
            f"RRM-009 tracing stage {stage} cycle {ordinal + 1}: revise the stage record."
        ),
        "evaluation_ref": f"evaluation:rrm009-tracing:{stage}:cycle-{ordinal}",
        "evaluation_contract_ref": TRACING_EVALUATION_CONTRACT,
        "objective_contract_ref": TRACING_OBJECTIVE_CONTRACT,
    }


def goal_blueprint(
    *,
    max_iterations: int = 2,
    workspace_mode: Literal["shared", "fresh"] = "fresh",
) -> GoalDirectedBlueprint:
    reservation = {"goal.iterations": 1, **UNIT_RESERVATION}
    return GoalDirectedBlueprint.model_validate(
        {
            **GENERIC_GOAL_DIRECTED.model_dump(mode="python"),
            "logical_id": "rrm009-technical-goal-directed",
            "title": "RRM-009 technical GoalDirected",
            "description": "Executor then independent verifier; technical inputs only.",
            "max_iterations": max_iterations,
            "authority_ceiling": {
                **GENERIC_GOAL_DIRECTED.authority_ceiling.model_dump(mode="python"),
                "budgets": {"dimensions": reservation},
            },
            "iteration_reservation": reservation,
            # RRM-009's technical qualification runs a `fresh` workspace per iteration;
            # RRM-020's proof runs the default `shared` one, whose next iteration joins the
            # same workspace identity as a new manifest revision.
            "workspace_policy": {
                **GENERIC_GOAL_DIRECTED.workspace_policy.model_dump(mode="python"),
                "workspace_mode": workspace_mode,
            },
        }
    )


def stage_workspace_contract() -> WorkflowWorkspaceContract:
    return WorkflowWorkspaceContract(
        slots=(
            WorkspaceSlot(
                name="output",
                path="/workspace/output",
                access="exclusive_write",
                purpose="report and output slot",
            ),
        )
    )


def goal_workspace_contract() -> WorkflowWorkspaceContract:
    return WorkflowWorkspaceContract(
        slots=(
            WorkspaceSlot(
                name="work", path="/work", access="exclusive_write", purpose="role work slot"
            ),
        )
    )


def _ceiling(ceilings: Mapping[str, int] = TECHNICAL_CEILINGS) -> AuthorityCeiling:
    return AuthorityCeiling(
        capabilities=CAPABILITIES,
        budgets=BudgetCeiling(dimensions=dict(ceilings)),
        max_concurrency=MAX_CONCURRENCY,
    )


async def publish_technical_catalog(
    control_plane: ControlPlaneService,
    *,
    family: str,
    now: datetime,
    ceilings: Mapping[str, int] | None = None,
    goal_workspace_mode: Literal["shared", "fresh"] = "fresh",
) -> TechnicalCatalog:
    """Publish one technical Workflow Type per family and compile its ERC through F1.

    Families: `StageGraph` (two stages, declared wait), `GoalDirected`, and the FX-TR
    `StageGraphTracing` tag (four stages, `S2` cycled; its own ceilings).
    """

    if ceilings is None:
        ceilings = TRACING_CEILINGS if family == TRACING_FAMILY else TECHNICAL_CEILINGS
    tag = {"StageGraph": "stagegraph", TRACING_FAMILY: "stagegraph-tracing"}.get(
        family, "goal-directed"
    )
    blueprint: StageGraphBlueprint | GoalDirectedBlueprint
    if family == "StageGraph":
        blueprint = stage_blueprint()
    elif family == TRACING_FAMILY:
        blueprint = tracing_stage_blueprint()
    else:
        blueprint = goal_blueprint(workspace_mode=goal_workspace_mode)
    contract = stage_workspace_contract() if family in STAGE_FAMILIES else goal_workspace_contract()

    async def publish(definition: Any) -> Any:
        return await control_plane.publish(
            PublishRequest(
                definition=definition,
                actor_id="publisher",
                published_at=now,
                expected_head_revision=0,
            )
        )

    published_blueprint = await publish(blueprint)
    control = await publish(
        ControlProfileDefinition(
            logical_id=f"rrm009.{tag}.control",
            title=f"RRM-009 {family} control",
            description="Technical qualification control profile.",
            blueprint_ref=published_blueprint.ref,
            selected_variants=frozenset({"default"} if family in STAGE_FAMILIES else ()),
            authority_ceiling=_ceiling(ceilings),
            overlayable_fields=frozenset(),
        )
    )
    runtime = await publish(
        RuntimeProfileDefinition(
            logical_id=f"rrm009.{tag}.runtime",
            title=f"RRM-009 {family} runtime",
            description="Technical qualification runtime profile; templates carry the binding.",
            binding="python-3.12",
        )
    )
    workspace = await publish(
        WorkspaceTemplateDefinition(
            logical_id=f"rrm009.{tag}.workspace",
            title=f"RRM-009 {family} workspace",
            description="The governed writable slot of the technical operations.",
            slots=contract.slots,
        )
    )
    evaluation = await publish(
        EvaluationProfileDefinition(
            logical_id=f"rrm009.{tag}.evaluation",
            title=f"RRM-009 {family} evaluation",
            description="Technical qualification gate placeholder.",
            gate_contract_refs=frozenset(
                {"contract:rrm009-evaluation@1"}
                | ({TRACING_EVALUATION_CONTRACT} if family == TRACING_FAMILY else set())
            ),
        )
    )
    workflow = await publish(
        WorkflowTypeDefinition(
            logical_id=f"rrm009.{tag}.workflow",
            title=f"RRM-009 {family} technical workflow",
            description="A technical qualification Workflow Type, not a product workflow.",
            purpose="Qualify the production composition end to end",
            input_admission_contract=INPUT_CONTRACT,
            invariants=frozenset({INVARIANT}),
            obligations=(frozenset() if family in STAGE_FAMILIES else frozenset({GOAL_OBLIGATION})),
            allowed_blueprints=frozenset({published_blueprint.ref}),
            allowed_control_profiles=frozenset({control.ref}),
            allowed_runtime_profiles=frozenset({runtime.ref}),
            allowed_workspace_templates=frozenset({workspace.ref}),
            allowed_evaluation_profiles=frozenset({evaluation.ref}),
            authority_ceiling=_ceiling(ceilings),
            workspace_contract=contract,
        )
    )
    manifest_digest = sha256_digest({"rrm009": "technical-input-manifest", "family": family})
    erc = await control_plane.compile(
        CompileInvocation(
            workflow_type=DefinitionSelector(exact=workflow.ref),
            blueprint=DefinitionSelector(exact=published_blueprint.ref),
            control_profile=DefinitionSelector(exact=control.ref),
            runtime_profile=DefinitionSelector(exact=runtime.ref),
            workspace_template=DefinitionSelector(exact=workspace.ref),
            evaluation_profile=DefinitionSelector(exact=evaluation.ref),
            input_manifest=RunInputManifestRef(
                manifest_id=f"rrm009-{tag}-manifest", revision=1, digest=manifest_digest
            ),
            caller_authority=_ceiling(ceilings),
            environment=EnvironmentAvailability(
                capabilities=CAPABILITIES, runtime_bindings=frozenset({"python-3.12"})
            ),
            context=CompilationContext(
                compilation_id=f"rrm009-{tag}-compilation",
                compiled_at=now,
                actor_id=OPERATOR,
                authority_subject_id=OPERATOR,
                authority_scope=SCOPE,
            ),
        )
    )
    return TechnicalCatalog(
        family=family,
        erc=erc,
        workflow_ref=workflow.ref,
        workspace_ref=workspace.ref,
        blueprint=blueprint,
    )


def technical_admission_policies() -> AdmissionPolicyRegistry:
    policies = AdmissionPolicyRegistry()
    policies.register(INPUT_CONTRACT, lambda _request, _configuration: None)
    policies.register(INVARIANT, lambda _request, _configuration: None)
    return policies


def baseline_reservation(family: str) -> dict[str, int]:
    """The admitted baseline reservation, non-empty for every family: GoalDirected settles
    it at its closing boundary and StageGraph releases it before terminalizing (RRM-021).

    It is one run-level hold, not a per-unit budget: the units reserve from their slot
    (`_stage_slot().reservation`) under the family's ceilings (`TRACING_CEILINGS` for FX-TR),
    so the tracing run holds a slightly larger baseline only to keep the hold visible beside
    its ten unit reservations.
    """

    return {"tokens.total": 40 if family == TRACING_FAMILY else 20}


def admission_request(catalog: TechnicalCatalog, request_id: str) -> RunRequest:
    """A run request bound to the compiled ERC, with hard caps at the effective ceilings."""

    base = run_request(request_scope=SCOPE, request_id=request_id)
    ceilings = catalog.erc.effective_authority.budgets.dimensions
    dimensions = tuple(
        BudgetDimensionLimit(
            dimension=item.dimension,
            applicability=BudgetApplicability.BOUNDED,
            hard_cap=ceilings[item.dimension],
        )
        if item.dimension in ceilings
        else (
            item.model_copy(update={"hard_cap": MAX_CONCURRENCY})
            if item.dimension == "concurrency.slots"
            else item
        )
        for item in base.budget_envelope.dimensions
    )
    return base.model_copy(
        update={
            "effective_configuration_digest": catalog.erc.digest,
            "workflow_type_ref": catalog.workflow_ref,
            "input_manifest": catalog.erc.input_manifest,
            "budget_envelope": BudgetEnvelope(
                dimensions=dimensions, baseline_reservations=baseline_reservation(catalog.family)
            ),
        }
    )


# --- Exact binding and templates -------------------------------------------------------------


@dataclass(frozen=True)
class TechnicalBinding:
    binding: DeepAgentExecutionBinding
    bundle: ResolvedSkillBundle
    child_model_ref: ExactDefinitionRef
    child_prompt_ref: ExactDefinitionRef
    # FX-TR-HOOK: the catalog hook bundle and its component; bound to the tracing family's
    # templates only when the deployment can register the bundle (`HOOK_SCRIPTS_REGISTRABLE`).
    hook_bundle: ResolvedHookScriptBundle
    hook_component: DeepAgentHookScriptComponent
    # Sprint V SV-16 (T1-MC): the knowledge tool components the templates bind; empty unless
    # a knowledge-enabled stack sets them (the model then calls `report_register` and
    # `submit_output` when `MISSION_CONTROL_TECHNICAL_KNOWLEDGE=1`).
    knowledge_tools: tuple[Any, ...] = ()

    def components(self, model_log: list[dict[str, Any]]) -> DeploymentCapabilityComponents:
        """The qualification's exact components: deterministic parent and child models."""

        extra: dict[str, Any] = {}
        if HOOK_SCRIPTS_REGISTRABLE:
            extra["hook_scripts"] = {self.hook_bundle.manifest_digest: self.hook_bundle}
        return DeploymentCapabilityComponents(
            # OC-R6: an explicit qualification composition; its deterministic models declare
            # no vendor or model id and stand in for the WP-CP-040 qualification pin.
            qualification=True,
            model_factories={
                self.binding.model.ref.digest: lambda bound, _secrets: TechnicalModel(
                    run_id=bound.run_id, operation_id=bound.operation_id, log=model_log
                ),
                self.child_model_ref.digest: lambda bound, _secrets: ChildModel(
                    run_id=bound.run_id, operation_id=bound.operation_id, log=model_log
                ),
            },
            prompts={
                self.child_prompt_ref.digest: (
                    "You are the technical child. Reply with the marker you are asked for."
                )
            },
            skill_bundles={self.bundle.bundle_digest: self.bundle},
            # The qualification MCP server (a Python stdio script, not a pinned package) is
            # registered exactly; the worker refuses any other launch (RRM-009 review).
            mcp_servers={server.ref.digest: server for server in self.binding.mcp_servers},
            **extra,
        )

    @property
    def hook_bound(self) -> bool:
        """Whether the tracing family's templates carry the catalog hook."""

        return HOOK_SCRIPTS_REGISTRABLE


def technical_binding() -> TechnicalBinding:
    """The exact fixture binding plus one in-process sync subagent and the qualification MCP."""

    child_model_ref = exact(DefinitionKind.MODEL, "model.rrm009-child", "child-model")
    child_prompt_ref = exact(DefinitionKind.PROMPT, "prompt.rrm009-child", "child-prompt")
    child = SyncSubagentProfile(
        name=CHILD_NAME,
        description="An in-process technical child with a bounded capability slice.",
        system_prompt_ref=child_prompt_ref,
        model=DeepAgentModelComponent(
            ref=child_model_ref, provider="openai", model_name="fixture-child-model"
        ),
        tool_refs=(),
        skill_refs=(),
        state_slice_id="child-state",
        context_slice_id="child-context",
        workspace_id="workspace-child",
        writable_paths=("/workspace/child",),
        # Bounded by the parent's reservation: the fixture profile's delegation ceiling
        # declares no per-child dimension (REQ-CP-DA-007).
        budget_limits={},
    )
    binding, _profile, bundle = exact_fixture(
        include_mcp=True, sync_subagents=(child,), with_child_slices=True
    )
    # FX-TR-STEP: the fixture MCP server (same tool schema, a >8 KiB result) replaces the
    # qualification module's; the binding digest is recomputed over the new component.
    binding = DeepAgentExecutionBinding.create(
        **{
            **binding.model_dump(mode="python", exclude={"binding_digest"}),
            "mcp_servers": (tracing_mcp_server(),),
        }
    )
    hook_bundle = tracing_hook_bundle()
    return TechnicalBinding(
        binding=binding,
        bundle=bundle,
        child_model_ref=child_model_ref,
        child_prompt_ref=child_prompt_ref,
        hook_bundle=hook_bundle,
        hook_component=tracing_hook_component(hook_bundle),
    )


def _workspace(
    template_ref: ExactDefinitionRef,
    *,
    namespace: str,
    workspace_id: str,
    contract: WorkflowWorkspaceContract,
    owner: WorkspaceOwner,
) -> WorkspaceContract:
    base = operation_request().workspace
    slot = contract.slots[0]
    return base.model_copy(
        update={
            "namespace_id": namespace,
            "workspace_id": workspace_id,
            "template_ref": template_ref,
            "workflow_contract_digest": sha256_digest(contract.model_dump(mode="json")),
            "slot_bindings": (
                WorkspaceSlotBinding(
                    slot_name=slot.name,
                    logical_path=slot.path,
                    access="exclusive_write",
                    owner=owner,
                ),
            ),
            "exclusive_write_paths": (slot.path,),
        }
    )


def _segments(objective: str, *, source: str) -> tuple[PromptSegment, ...]:
    """Admitted, non-privileged segments only: the minimal catalog carries no prompt."""

    return (
        PromptSegment(
            source_ref=source,
            source_revision=1,
            trust_class=PromptTrustClass.ADMITTED_INPUT,
            content=objective,
            rendered_digest=sha256_digest(objective),
        ),
    )


def _template(
    technical: TechnicalBinding,
    *,
    objective: str,
    workspace: WorkspaceContract,
    output_schema: StructuredOutputBinding | None = None,
    hook_scripts: tuple[DeepAgentHookScriptComponent, ...] = (),
) -> OperationExecutionRequest:
    base = operation_request()
    return OperationExecutionRequest.model_validate(
        {
            **base.model_dump(mode="python"),
            "request_scope": SCOPE,
            "prompt_segments": _segments(objective, source="input:rrm009@1"),
            "mcp_servers": (),
            "skills": (),
            "capability_grant": {
                "capabilities": sorted(CAPABILITIES),
                "tool_ids": [],
                "mcp_server_ids": [],
                "data_scope_refs": [],
                "network_hosts": [],
            },
            "workspace": workspace,
            "execution_runtime": "deep_agent",
            "native_placement": None,
            **lane_fields(
                DeepAgentExecutionBinding.create(
                    **{
                        **technical.binding.model_dump(mode="python", exclude={"binding_digest"}),
                        "task_queue": AGENT_COGNITIVE_QUEUE,
                        "workspace": workspace,
                        "capability_grant": {
                            "capabilities": sorted(CAPABILITIES),
                            "tool_ids": [],
                            "mcp_server_ids": [],
                            "data_scope_refs": [],
                            "network_hosts": [],
                        },
                        "hook_scripts": hook_scripts,
                        "tools": (*technical.binding.tools, *technical.knowledge_tools),
                    }
                )
            ),
            "budget_limits": dict(UNIT_RESERVATION),
            "secret_refs": (SecretRef(provider="environment", key="OPENAI_API_KEY"),),
            "output_schema": output_schema,
        }
    )


def stage_templates(
    technical: TechnicalBinding, catalog: TechnicalCatalog
) -> dict[str, OperationExecutionRequest]:
    templates: dict[str, OperationExecutionRequest] = {}
    # One template per stage of the published blueprint, keyed `{stage}/{slot}/{variant}`
    # (`manifest_launch_inputs.py:246`): `draft`/`review`, or the FX-TR `S1..S4`.
    stages = (
        tuple(stage.stage_id for stage in catalog.blueprint.stages)
        if isinstance(catalog.blueprint, StageGraphBlueprint)
        else ("draft", "review")
    )
    # FX-TR-HOOK: only the tracing family's stage operations carry the catalog hook, and only
    # while the deployment can register its bundle (see `HOOK_SCRIPTS_REGISTRABLE`).
    hooks = (
        (technical.hook_component,)
        if catalog.family == TRACING_FAMILY and technical.hook_bound
        else ()
    )
    for stage in stages:
        templates[f"{stage}/execute/default"] = _template(
            technical,
            hook_scripts=hooks,
            objective=STAGE_OBJECTIVES.get(
                stage, f"RRM-009 technical stage {stage}. Produce the stage record."
            ),
            # One namespace per stage: both stages bind the Workflow Type's exclusive
            # `/workspace/output` slot, and two workspaces never own one slot in a namespace.
            workspace=_workspace(
                catalog.workspace_ref,
                namespace=f"workspace-namespace:{{run_id}}:stage:{stage}",
                workspace_id=f"workspace:{{run_id}}:stage:{stage}",
                contract=stage_workspace_contract(),
                owner=WorkspaceOwner(kind=WorkspaceOwnerKind.STAGE, owner_id=f"stage:{stage}"),
            ),
        )
    return templates


def goal_templates(
    technical: TechnicalBinding, catalog: TechnicalCatalog
) -> dict[str, OperationExecutionRequest]:
    templates: dict[str, OperationExecutionRequest] = {}
    for role in ("executor", "verifier"):
        templates[role] = _template(
            technical,
            objective=GOAL_OBJECTIVES.get(role, f"RRM-009 technical GoalDirected {role}."),
            workspace=_workspace(
                catalog.workspace_ref,
                namespace="workspace-namespace:{run_id}",
                workspace_id=f"workspace:{{run_id}}:{role}",
                contract=goal_workspace_contract(),
                owner=WorkspaceOwner(kind=WorkspaceOwnerKind.RUN, owner_id="goal-template"),
            ),
            output_schema=StructuredOutputBinding(
                schema_id=f"goal-{role}-observation",
                revision=1,
                schema_digest=GOAL_SCHEMA_DIGESTS.get(
                    role, sha256_digest(f"goal-{role}-observation-schema")
                ),
            ),
        )
    return templates


# --- Family inputs ---------------------------------------------------------------------------


def stage_input(
    catalog: TechnicalCatalog, run_id: str, binding_ref: str, version: int
) -> StageGraphRunInput:
    return StageGraphRunInput(
        run_id=run_id,
        request_scope=SCOPE,
        effective_configuration_digest=catalog.erc.digest,
        workflow_type_digest=catalog.workflow_ref.digest,
        blueprint_digest=catalog.blueprint_digest,
        blueprint=catalog.blueprint.model_dump(mode="json"),
        initial_run_version=version,
        max_concurrency=1,
        task_timeout_seconds=180,
        semantic_input_binding_ref=binding_ref,
        correlation_id=f"rrm009:{run_id}",
        # The same hold the admission request declared (`run_launch.py:213` compares them).
        baseline_reservation=baseline_reservation(catalog.family),
    )


def goal_revision(
    run_id: str,
    objective: str,
    *,
    revision_id: str | None = None,
    envelope_digest: str | None = None,
) -> GoalRevision:
    """The initial Goal Revision of a run. A fork-derived run (1.4.4, P5.4) passes the
    fork's `derived_goal_revision_id` and the source run's envelope digest; the defaults
    are the run-bound values every other caller gets."""

    values = {
        "schema_version": "belllabs.goal-revision.v1",
        "revision_id": revision_id or "goal-revision:1",
        "revision": 1,
        "parent_revision_id": None,
        "envelope_digest": (
            envelope_digest or sha256_digest({"rrm009": "goal-envelope", "run": run_id})
        ),
        "objective": objective,
        "tactical_changes": (),
        "evidence_refs": ("input:rrm009-technical",),
        "unmet_obligations": (GOAL_OBLIGATION,),
        "proposer": "application:qualification",
        "deciding_authority": "authority:qualification",
        "applicability": "remaining_run",
        "tactics": (),
        "subgoals": (),
        "coverage_emphasis": (),
    }
    return GoalRevision(canonical_digest=sha256_digest(values), **values)  # type: ignore[arg-type]


def goal_input(
    catalog: TechnicalCatalog,
    run_id: str,
    binding_ref: str,
    version: int,
    objective: str,
    *,
    revision_id: str | None = None,
    envelope_digest: str | None = None,
    start_position: GoalDirectedStartPosition | None = None,
) -> GoalDirectedRunInput:
    """The launch input of a Goal Directed run. The keyword arguments are for a fork-derived
    run (1.4.4, P5.4): the receipt's `derived_goal_revision_id`, the source's envelope
    digest and the receipt's `start_position`."""

    revision = goal_revision(
        run_id, objective, revision_id=revision_id, envelope_digest=envelope_digest
    )
    return GoalDirectedRunInput(
        run_id=run_id,
        request_scope=SCOPE,
        effective_configuration_digest=catalog.erc.digest,
        blueprint_digest=catalog.blueprint_digest,
        blueprint=catalog.blueprint.model_dump(mode="json"),
        envelope_digest=revision.envelope_digest,
        initial_revision=revision,
        initial_run_version=version,
        task_timeout_seconds=180,
        baseline_reservation=baseline_reservation("GoalDirected"),
        required_obligation_refs=(GOAL_OBLIGATION,),
        required_output_contract_refs=(GOAL_OUTPUT_CONTRACT,),
        semantic_input_binding_ref=binding_ref,
        start_position=start_position,
    )


# --- Deterministic cognition -----------------------------------------------------------------


def _text(messages: Sequence[BaseMessage], kinds: tuple[type, ...]) -> str:
    return "\n".join(str(item.content) for item in messages if isinstance(item, kinds))


def _digest16(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()[:16]


def call_usage() -> dict[str, int]:
    return {"input_tokens": 2, "output_tokens": 3, "total_tokens": TOKENS_PER_CALL}


class _LoggedModel(BaseChatModel):
    run_id: str
    operation_id: str
    log: Any  # a shared list; pydantic would copy a validated `list`

    def bind_tools(
        self,
        tools: Sequence[BaseTool | dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        del tools, tool_choice, kwargs
        return self

    def _record(self, kind: str, messages: list[BaseMessage]) -> tuple[int, int]:
        tools = sum(isinstance(item, ToolMessage) for item in messages)
        humans = sum(isinstance(item, HumanMessage) for item in messages)
        self.log.append(
            {
                "model": kind,
                "run_id": self.run_id,
                "operation": self.operation_id,
                "tools": tools,
                "humans": humans,
                "pid": os.getpid(),
            }
        )
        return tools, humans

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        return self._reply(messages)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        return self._reply(messages)

    def _reply(self, messages: list[BaseMessage]) -> ChatResult:
        raise NotImplementedError


class ChildModel(_LoggedModel):
    """The sync subagent's cognition: one answer carrying the child marker."""

    @property
    def _llm_type(self) -> str:
        return "rrm-009-child"

    def _reply(self, messages: list[BaseMessage]) -> ChatResult:
        self._record("child", messages)
        return ChatResult(
            generations=[
                ChatGeneration(message=AIMessage(content=CHILD_MARKER, usage_metadata=call_usage()))
            ]
        )


class TechnicalModel(_LoggedModel):
    """The parent's cognition, by tool-message count since its latest input:

    0: `task` (the in-process sync subagent); 1: `write_file` into the writable slot (a
    GoalDirected operation writes into its role root's `/work` slot);
    2: `lookup_binding_marker` (the exact MCP tool); 3: the typed answer. GoalDirected
    operations answer with their role's observation; StageGraph operations with an
    artifact ref derived from their admitted objective.
    """

    @property
    def _llm_type(self) -> str:
        return "rrm-009-technical"

    def _reply(self, messages: list[BaseMessage]) -> ChatResult:
        # P1 turn 4 (intervention drills): a per-call delay widens the window in which an
        # `interrupt_and_inject` can land inside a running turn (0 by default).
        delay = float(os.environ.get("MISSION_CONTROL_TECHNICAL_MODEL_DELAY_SECONDS", "0") or 0)
        if delay > 0:
            time.sleep(delay)
        human_indexes = [index for index, item in enumerate(messages) if item.type == "human"]
        since_input = messages[human_indexes[-1] :] if human_indexes else messages
        tools = sum(isinstance(item, ToolMessage) for item in since_input)
        self._record("parent", messages)
        # Tracing Stage 2 (FX-TR-DISCONNECT, T0): `MISSION_CONTROL_TECHNICAL_FAIL_AT_TOOLS=N`
        # makes the parent's call after N tool results fail as a cut provider stream does.
        fail_at = os.environ.get("MISSION_CONTROL_TECHNICAL_FAIL_AT_TOOLS", "")
        if fail_at and tools == int(fail_at):
            raise ConnectionError("simulated provider disconnect mid-turn")
        if tools == 0:
            call = {
                "name": "task",
                "args": {
                    "description": f"Reply with exactly {CHILD_MARKER}.",
                    "subagent_type": CHILD_NAME,
                },
            }
        elif tools == 1:
            objective = _text(since_input, (HumanMessage,))
            call = {
                "name": "write_file",
                "args": {
                    "file_path": _report_path(self.operation_id),
                    "content": f"# RRM-009 report\n\nobjective-digest: {_digest16(objective)}\n",
                },
            }
        elif tools == 2:
            call = {"name": "lookup_binding_marker", "args": {"code": MCP_CODE}}
        elif tools == 3 and os.environ.get("MISSION_CONTROL_TECHNICAL_KNOWLEDGE") == "1":
            # SV-16 (T1-MC): register the operation's report through the knowledge gateway.
            # A real executor needs a full `research-report/v2` registration: the test writes a
            # tenant-substituted template (MISSION_CONTROL_TECHNICAL_KNOWLEDGE_PAYLOAD) and each
            # operation registers it under its own report id; the fake takes any document.
            unique = _digest16(f"{self.run_id}/{self.operation_id}")
            template = os.environ.get("MISSION_CONTROL_TECHNICAL_KNOWLEDGE_PAYLOAD", "")
            if template:
                from tests.fixtures.knowledge_binding import fresh_registration, model_content

                # W1 D1: the model submits content; the host binds producer and digests.
                report = model_content(
                    fresh_registration(
                        json.loads(Path(template).read_text(encoding="utf-8")), unique
                    )
                )
            else:
                from tests.fixtures.knowledge_binding import model_report

                report = model_report(f"report-{unique}")
            call = {"name": "report_register", "args": {"report": report}}
        elif tools == 4 and os.environ.get("MISSION_CONTROL_TECHNICAL_KNOWLEDGE") == "1":
            # ... and submit the exact handle the receipt named for the `report` obligation.
            registered = json.loads(
                next(
                    str(item.content)
                    for item in reversed(since_input)
                    if isinstance(item, ToolMessage)
                )
            )
            affected = (registered.get("result") or {}).get("affected") or []
            items = [
                {"kind": "handle", "ref": entry["handle"], "digest": entry["digest"]}
                for entry in affected
                if "/report/" in entry["handle"]
            ] or [
                {
                    "kind": "path",
                    "ref": _report_path(self.operation_id),
                    "digest": "sha256:" + "0" * 64,
                }
            ]
            call = {"name": "submit_output", "args": {"obligation": "report", "items": items}}
        else:
            # Tracing Stage 2 (F-T3-1, T0): `MISSION_CONTROL_TECHNICAL_PROSE_ROLE=executor` (or
            # `verifier`) makes that Goal Directed role answer in prose, as a real model
            # without a structured output binding does; every other operation still answers
            # its typed JSON.
            role = os.environ.get("MISSION_CONTROL_TECHNICAL_PROSE_ROLE", "")
            prose = bool(role) and (
                self.operation_id.endswith(f"/{role}") or f"/{role}:" in self.operation_id
            )
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content=(
                                PROSE_EXECUTOR_ANSWER
                                if prose
                                else json.dumps(self._answer(since_input), sort_keys=True)
                            ),
                            usage_metadata=call_usage(),
                        )
                    )
                ]
            )
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    **call,
                    "id": f"rrm009-{call['name']}-{_digest16(self.operation_id)}",
                    "type": "tool_call",
                }
            ],
            usage_metadata=call_usage(),
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _answer(self, since_input: list[BaseMessage]) -> dict[str, Any]:
        tool_text = _text(since_input, (ToolMessage,))
        facts = {
            "child": CHILD_MARKER in tool_text,
            "mcp": f"MCP-BOUND::{MCP_CODE}::EXACT" in tool_text,
        }
        if ":stage:" in self.operation_id:
            stage = self.operation_id.split(":stage:", 1)[1].split(":", 1)[0]
            admitted = _text(since_input, (HumanMessage,))
            return {
                "answer": ANSWER_MARKER,
                "facts": facts,
                "output_refs": [f"artifact:rrm009:{stage}:{_digest16(admitted)}"],
                # FX-TR: the `S2` stage evaluation (`cycle` twice, then `accept`); empty for
                # every other stage, so the two-stage blueprint's answers are unchanged.
                **tracing_cycle_evaluation(self.operation_id),
            }
        role = self.operation_id.rsplit("/", 1)[-1]
        iteration = int(self.operation_id.split("goal-iteration/", 1)[1].split("/", 1)[0])
        if role == "executor":
            return {
                "schema_version": "belllabs.goal-executor-observation.v1",
                "disposition": "completed",
                "output_refs": [f"artifact:rrm009-goal:{iteration}"],
                "completion_claim": iteration >= 2,
                "accepted_fact_refs": [f"fact:rrm009:{iteration}"],
                "evidence_refs": [f"evidence:rrm009-goal:executor:{iteration}"],
                "handoff": None,
                "output_contract_ref": GOAL_OUTPUT_CONTRACT,
            }
        accepted = iteration >= 2
        return {
            "schema_version": "belllabs.goal-verifier-observation.v1",
            "decision": "accepted" if accepted else "rejected",
            "progress_made": True,
            "accepted_obligation_refs": [GOAL_OBLIGATION] if accepted else [],
            "findings": [],
            "evidence_refs": [f"evidence:rrm009-goal:verifier:{iteration}"],
            "unmet_obligations": [] if accepted else [GOAL_OBLIGATION],
            "obligation_applicability": [[GOAL_OBLIGATION, True]],
            "output_contract_ref": GOAL_OUTPUT_CONTRACT,
        }


def _report_path(operation_id: str) -> str:
    """The report's path in the operation's governed writable slot."""

    if "goal-iteration/" not in operation_id:
        return REPORT_PATH
    iteration, role = operation_id.split("goal-iteration/", 1)[1].split("/")[:2]
    return f"/goal/{iteration}/{role.split(':', 1)[0]}/work/report.md"


def utc_now() -> datetime:
    return datetime.now(UTC)

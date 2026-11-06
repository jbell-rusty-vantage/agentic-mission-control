"""Lowering ``MissionDefinition@1`` onto the existing compiler inputs (SPEC-05 "Mapping").

The kernel compiles Workflow Types, blueprints and profiles into an Effective Run Configuration
(the Compiled Program); it has no compiler for ``MissionDefinition@1`` yet. This module is the
one deterministic bridge, pure and digest-stable: a ``goal_loop`` root lowers to a
``GoalDirectedBlueprint`` (obligations = the required goals), a ``stage_graph`` root to a
``StageGraphBlueprint`` through ``build_stagegraph_v2`` (one stage per child node; a human gate
or an event wait becomes a stage carrying a declared wait), any other root to a one-stage graph.
A nested Goal Loop or Stage Graph (a stage's node, or a Goal Loop's executor-phase body) is never
flattened (OVE-176): its stage carries a sealed ``NestedBody`` and the body executes recursively
as its own child run; only the composite's declared outputs cross the boundary, and the body's
own promises keep their absolute nested position in the body's promise set.

Goals are owned explicitly (a stage's objectives or the stage whose declared output a
criterion cites); an unowned required goal of a Stage Graph refuses instead of falling to the
last stage. Dependencies carry the exact bound producer output and the authored join
(``all``/``any``/quorum); an explicit ``from: <sibling>.<output>`` binding is itself the
dependency (OVE-171: no ``depends_on``-only side path). Named release groups, typed stage facts
and explicit routes compile under ``GRAPH_SEMANTICS_V1`` (OUTPUT-CONTRACTS §7), as do optional
bindings and any/quorum joins (exact first-qualifying selection, visible optional omission).
Every declared output compiles into one named ``OutputObligation@2``
of the blueprint's ``output_promises`` with a closed completion expression (WI-01).

The Runtime Profile pins every resolved capability by exact ref
(``operation_binding_refs``); the lane execution bindings themselves are produced by the
semantic input binding at launch, never named by the manifest. Logical ids are
content-addressed by the definition digest, so the same definition always lowers to the same
published rows.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    AuthorityCeiling,
    BudgetCeiling,
    ControlProfileDefinition,
    EvaluationProfileDefinition,
    ExactDefinitionRef,
    GoalConvergencePolicy,
    GoalDirectedBlueprint,
    GoalHandoffPolicy,
    GoalSessionRolloverPolicy,
    GoalVerifierPolicy,
    JoinKind,
    RunInputManifestRef,
    RuntimeProfileDefinition,
    StageGraphBlueprint,
    StageGraphWait,
    StageOutputSlot,
    WorkflowTypeDefinition,
    WorkflowWorkspaceContract,
    WorkspaceSlot,
    WorkspaceTemplateDefinition,
)
from mission_control.domain.authoring.graph_routes import (
    GRAPH_SEMANTICS_V1,
    CarriedOutput,
    FactPredicate,
    FactRef,
    RevisitRegion,
    RouteBranch,
    StageFact,
    StageRoute,
)
from mission_control.domain.authoring.manifest import (
    Behavior,
    ManifestIssue,
    QuorumJoin,
    ReleaseGroupDeclaration,
    RevisitDeclaration,
    RouteDeclaration,
)
from mission_control.domain.authoring.mission_definition import (
    DefinitionNode,
    DefinitionOutput,
    MissionDefinition,
)
from mission_control.domain.authoring.nested_bodies import (
    GOAL_EXECUTOR_HOST,
    RECURSIVE_BEHAVIORS,
    NestedBody,
    NestedBodyError,
    NestedExport,
)
from mission_control.domain.authoring.nested_lowering import (
    body_budget,
    composite,
    inherited_inputs,
    max_depth,
    nested_definition,
    nested_exports,
    spend_reservation,
)
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    StageInputBindingSpec,
    StageReleaseGroupSpec,
    build_stagegraph_v2,
)
from mission_control.domain.outputs.contracts import (
    AllOf,
    ObligationLeaf,
    OutputContract,
    OutputObligation,
    OutputPromiseSet,
    SchemaPin,
)
from mission_control.domain.programs.completion import OutputSchemaBinding, SchemaCriterion

LOWERING_VERSION = "mc.manifest-lowering/3"
MANIFEST_INPUT_CONTRACT = "contract:mc.manifest-input@1"
MANIFEST_INVARIANT = "contract:mc.manifest-invariant@1"
MANIFEST_RUNTIME_BINDING = "python-3.12"
MANIFEST_RUN_CAPABILITIES = frozenset(
    {"model.invoke", "sandbox.execute", "mcp.call", "subagent.task", "artifact.promote"}
)
GOAL_WORKSPACE = WorkflowWorkspaceContract(
    slots=(WorkspaceSlot(name="work", path="/work", access="exclusive_write", purpose="role work"),)
)
STAGE_WORKSPACE = WorkflowWorkspaceContract(
    slots=(
        WorkspaceSlot(
            name="output",
            path="/workspace/output",
            access="exclusive_write",
            purpose="stage outputs",
        ),
    )
)
Family = Literal["StageGraph", "GoalDirected"]


# K02: session rollovers a Goal Loop may perform when the manifest sets no `governors.transfers`.
DEFAULT_MAX_ROLLOVERS = 3


def lowering_base_id(definition: MissionDefinition) -> str:
    """Content address both the authored definition and its lowering semantics.

    A new compiler must not overwrite revision 1 of a previously published blueprint.
    """

    digest = sha256_digest({"definition": definition.digest, "lowering": LOWERING_VERSION})
    return f"mc.manifest.{definition.mission_key}.{digest.removeprefix('sha256:')[:12]}"


def required_goals(definition: MissionDefinition) -> frozenset[str]:
    """The goals whose acceptance the run must prove (the run's required obligations)."""

    required = frozenset(
        item.goal_key for item in definition.completion_contract.goals if item.required
    )
    return required or frozenset(goal.key for goal in definition.goals)


def budget_dimensions(
    definition: MissionDefinition, *, goal_iterations: int | None
) -> dict[str, int]:
    """The manifest budget as run-control budget dimensions (integers only, no floats)."""

    budget = definition.budget
    dimensions: dict[str, int] = {}
    if budget.tokens is not None:
        dimensions["tokens.total"] = budget.tokens
    if budget.tool_calls is not None:
        dimensions["tool.calls.total"] = budget.tool_calls
    if budget.usd is not None:
        dimensions["currency.estimated_micros"] = int(
            (Decimal(budget.usd) * Decimal(1_000_000)).to_integral_value()
        )
    if budget.wall_clock_seconds is not None:
        dimensions["time.elapsed_ms"] = budget.wall_clock_seconds * 1000
    if goal_iterations is not None:
        dimensions["goal.iterations"] = goal_iterations
    return dimensions


@dataclass(frozen=True)
class LoweredMission:
    """The compiler inputs of one mission, before publication (refs are assigned on publish)."""

    mission_key: str
    family: Family
    base_id: str
    blueprint: StageGraphBlueprint | GoalDirectedBlueprint
    runtime_profile: RuntimeProfileDefinition
    workspace_template: WorkspaceTemplateDefinition
    evaluation_profile: EvaluationProfileDefinition
    authority: AuthorityCeiling
    obligations: frozenset[str]
    output_contracts: frozenset[str]
    workspace_contract: WorkflowWorkspaceContract
    input_manifest: RunInputManifestRef
    initial_goal: str | None
    warnings: tuple[ManifestIssue, ...] = field(default=())

    @property
    def blueprint_digest(self) -> str:
        return sha256_digest(self.blueprint)

    @property
    def runtime_profile_digest(self) -> str:
        return sha256_digest(self.runtime_profile)

    def control_profile(self, blueprint_ref: ExactDefinitionRef) -> ControlProfileDefinition:
        return ControlProfileDefinition(
            logical_id=f"{self.base_id}.control",
            title=f"{self.mission_key} control",
            description=f"Control profile lowered from mission {self.mission_key}.",
            blueprint_ref=blueprint_ref,
            selected_variants=frozenset({"default"} if self.family == "StageGraph" else ()),
            authority_ceiling=self.authority,
        )

    def workflow_type(
        self,
        *,
        blueprint_ref: ExactDefinitionRef,
        control_ref: ExactDefinitionRef,
        runtime_ref: ExactDefinitionRef,
        workspace_ref: ExactDefinitionRef,
        evaluation_ref: ExactDefinitionRef,
    ) -> WorkflowTypeDefinition:
        return WorkflowTypeDefinition(
            logical_id=f"{self.base_id}.workflow",
            title=f"{self.mission_key} workflow",
            description=f"Workflow Type lowered from mission {self.mission_key}.",
            purpose=f"Run mission {self.mission_key} as authored in its Mission Manifest",
            input_admission_contract=MANIFEST_INPUT_CONTRACT,
            invariants=frozenset({MANIFEST_INVARIANT}),
            obligations=self.obligations,
            output_contracts=self.output_contracts,
            allowed_blueprints=frozenset({blueprint_ref}),
            allowed_control_profiles=frozenset({control_ref}),
            allowed_runtime_profiles=frozenset({runtime_ref}),
            allowed_workspace_templates=frozenset({workspace_ref}),
            allowed_evaluation_profiles=frozenset({evaluation_ref}),
            authority_ceiling=self.authority,
            workspace_contract=self.workspace_contract,
        )


def _goal_text(definition: MissionDefinition, key: str) -> str:
    for goal in definition.goals:
        if goal.key == key:
            return goal.description
    for objective in definition.objectives:
        if objective.key == key:
            return objective.description
    return key


def _owning_goal(definition: MissionDefinition, key: str) -> str | None:
    if any(goal.key == key for goal in definition.goals):
        return key
    return next((item.goal_key for item in definition.objectives if item.key == key), None)


def _goal_blueprint(
    definition: MissionDefinition,
    root: DefinitionNode,
    base_id: str,
    output_schemas: Mapping[str, OutputSchemaBinding],
    *,
    position: str,
    depth: int,
) -> tuple[GoalDirectedBlueprint, frozenset[str], frozenset[str], str]:
    objective_key = str(root.body.get("objective") or definition.goals[0].key)
    iterations = root.environment.governors.iterations if root.environment.governors else None
    patience = root.environment.governors.patience if root.environment.governors else None
    max_iterations = iterations or 1
    obligations = required_goals(definition)
    outputs = frozenset(f"output:{item.name}" for item in root.outputs) or frozenset(
        {f"output:{base_id}:result"}
    )
    authority = AuthorityCeiling(
        capabilities=MANIFEST_RUN_CAPABILITIES,
        budgets=BudgetCeiling(
            dimensions=budget_dimensions(definition, goal_iterations=max_iterations)
        ),
    )
    criteria = ", ".join(sorted(item.key for item in definition.criteria))
    # Reuse the declared-output lowering rules; no StageGraph execution is introduced.
    requirements, _, _ = _stage_blueprint(
        definition, root, base_id, output_schemas, position=position, depth=depth
    )
    requirement = requirements.stages[0]
    executor_body = tuple(
        _nested_body(
            definition,
            child,
            GOAL_EXECUTOR_HOST,
            f"{position}/{child.key}",
            depth + 1,
            output_schemas,
            owner=root,
        )
        for child in root.nodes
    )
    # OVE-176: an iteration hosting an executor body reserves the body's spend (within the
    # loop's authority), so the child run spends only what the iteration charged.
    iteration_reservation = {"goal.iterations": 1}
    for child in root.nodes:
        ceilings = authority.budgets.dimensions
        for name, amount in spend_reservation(body_budget(definition, child)).items():
            if name in ceilings:
                iteration_reservation[name] = min(amount, ceilings[name])
    blueprint = GoalDirectedBlueprint(
        logical_id=f"{base_id}.blueprint",
        title=f"{definition.title} (Goal Loop)",
        description=f"Goal Loop lowered from mission {definition.mission_key}.",
        objective_contract=f"manifest:{definition.mission_key}:objective:{objective_key}",
        acceptance_contract=f"manifest:{definition.mission_key}:criteria:{criteria}",
        admitted_input_classes=frozenset({"mc.manifest-input"}),
        authority_ceiling=authority,
        prohibited_work=frozenset({"work outside the mission manifest"}),
        required_output_contracts=outputs,
        required_obligation_refs=obligations,
        output_slots=requirement.output_slots
        if any(slot.validation_schema for slot in requirement.output_slots)
        else (),
        schema_criteria=requirement.schema_criteria,
        verifier_policy=GoalVerifierPolicy(
            operation_class="manifest_verifier",
            binding_ref=f"verifier:{base_id}@1",
            rubric_ref=f"rubric:{base_id}@1",
            rubric_version=1,
            acceptance_version=1,
            output_contract_ref=sorted(outputs)[0],
        ),
        allowed_operation_classes=frozenset({"manifest_operation"}),
        allowed_async_subgoal_classes=frozenset({"manifest_subgoal"}),
        allowed_linked_run_slot_ids=frozenset({"manifest_link"}),
        session_policy=GoalSessionRolloverPolicy(
            context_selection_policy_ref="context-selection:mc.manifest@1",
            context_compaction_policy_ref="context-compaction:mc.manifest@1",
            protected_fact_classes=frozenset({"objective"}),
            # K02 (P1 turn 4): `governors.transfers` bounds the session rollovers of a Goal
            # Loop (the token threshold crossing rolls the session from the handoff packet);
            # unset means the default, never the old hard-coded 0 that failed the family.
            max_rollovers=(
                root.environment.governors.transfers
                if root.environment.governors and root.environment.governors.transfers is not None
                else DEFAULT_MAX_ROLLOVERS
            ),
            compaction_failure_action="pause",
        ),
        handoff_policy=GoalHandoffPolicy(
            max_instruction_bytes=8192,
            allowed_workspace_ref_classes=frozenset({"mc.workspace"}),
            allowed_snapshot_ref_classes=frozenset({"mc.snapshot"}),
        ),
        convergence_policy=GoalConvergencePolicy(
            max_no_progress_iterations=patience or 3,
            authority_breach_action="fail",
            no_progress_action="partial_or_fail",
            repeated_blocker_action="partial_or_fail",
            soft_budget_action="continue",
        ),
        max_iterations=max_iterations,
        nested_bodies=executor_body,
        iteration_reservation=iteration_reservation,
    )
    return blueprint, obligations, outputs, _goal_text(definition, objective_key)


def _nested_body(
    definition: MissionDefinition,
    node: DefinitionNode,
    host_id: str,
    position: str,
    depth: int,
    output_schemas: Mapping[str, OutputSchemaBinding],
    *,
    owner: DefinitionNode | None = None,
) -> NestedBody:
    """Compile one recursive boundary: its derived body, sealed by the digests of the body's
    sub-definition and its own lowering (recursively, one level deeper), and its exports.

    ``owner`` is the parent node whose promises the exports are adopted into: the composite
    node itself in a Stage Graph, the hosting Goal Loop for an executor body."""

    family = RECURSIVE_BEHAVIORS.get(node.behavior)
    if family is None:
        raise NestedBodyError(
            node.pointer,
            "unsupported_nested_body",
            f"{node.behavior.value} cannot execute recursively as a nested body yet",
        )
    limit = max_depth(definition)
    if depth > limit:
        raise NestedBodyError(
            node.pointer,
            "nested_depth_exceeded",
            f"nested body {node.key} is at depth {depth}; the governor allows {limit}",
        )
    inherited = inherited_inputs(node)
    if inherited:
        raise NestedBodyError(
            node.pointer,
            "nested_inherited_input_unsupported",
            f"nested body {node.key} reads producers outside itself: {list(inherited)}",
        )
    derived = nested_definition(definition, node)
    lowered = lower_mission(derived, output_schemas=output_schemas, position=position, depth=depth)
    return NestedBody(
        host_id=host_id,
        node_key=node.key,
        position=position,
        behavior="goal_loop" if family == "GoalDirected" else "stage_graph",
        family=family,
        depth=depth,
        max_depth=limit,
        definition_digest=derived.digest,
        blueprint_digest=lowered.blueprint_digest,
        exports=_adopted(nested_exports(node), owner or node),
    )


def goal_owners(
    definition: MissionDefinition, children: tuple[DefinitionNode, ...]
) -> dict[str, str]:
    """Explicit goal ownership: a stage's objectives, else the stage whose declared output a
    goal's criterion cites as evidence (document order; the last explicit server wins)."""

    owners: dict[str, str] = {}
    for child in children:
        for key in child.objectives:
            goal = _owning_goal(definition, key)
            if goal is not None:
                owners[goal] = child.key
    declared = {output.name: child.key for child in children for output in child.outputs}
    by_evidence: dict[str, str] = {}
    for criterion in definition.criteria:
        for evidence in criterion.evidence:
            if evidence in declared:
                by_evidence[criterion.goal_key] = declared[evidence]
    for goal, owner in by_evidence.items():
        owners.setdefault(goal, owner)
    return owners


def unowned_stage_goals(definition: MissionDefinition) -> tuple[str, ...]:
    """Required goals of a Stage Graph root that no stage explicitly serves."""

    root = definition.program
    if root.behavior is not Behavior.STAGE_GRAPH:
        return ()
    owners = goal_owners(definition, root.nodes)
    return tuple(sorted(required_goals(definition) - owners.keys()))


def _join(child: DefinitionNode) -> tuple[JoinKind, int | None]:
    if child.join == "any":
        return JoinKind.ANY, None
    if isinstance(child.join, int):
        return JoinKind.MINIMUM, child.join
    return JoinKind.ALL, None


def _bindings(child: DefinitionNode, siblings: set[str]) -> tuple[StageInputBindingSpec, ...]:
    """The explicit named data bindings from sibling producers (each one is a dependency)."""

    found: list[StageInputBindingSpec] = []
    seen: set[tuple[str, str]] = set()
    for item in child.inputs:
        if item.source != "from" or item.ref is None:
            continue
        producer, _, output = item.ref.partition(".")
        if (
            producer in siblings
            and producer != child.key
            and output
            and (producer, output) not in seen
        ):
            seen.add((producer, output))
            found.append(StageInputBindingSpec(producer, output, item.required))
    return tuple(found)


def _join_kind(join: object) -> tuple[JoinKind, int | None]:
    if join == "any":
        return JoinKind.ANY, None
    if isinstance(join, QuorumJoin):
        return JoinKind.MINIMUM, join.quorum
    return JoinKind.ALL, None


def _group_specs(child: DefinitionNode) -> tuple[StageReleaseGroupSpec, ...]:
    def spec(group: ReleaseGroupDeclaration) -> StageReleaseGroupSpec:
        kind, minimum = _join_kind(group.join)
        return StageReleaseGroupSpec(
            group_id=group.key,
            member_stage_ids=group.member_keys,
            join=kind,
            minimum=minimum,
            coverage_subjects=group.coverage,
            member_coverage=tuple(sorted(group.covers().items())),
        )

    return tuple(spec(group) for group in child.release_groups)


def _route(route: RouteDeclaration) -> StageRoute:
    return StageRoute(
        route_id=route.key,
        mode=route.mode,
        branches=tuple(
            RouteBranch(
                branch_id=branch.key,
                predicates=tuple(
                    FactPredicate(
                        stage_id=item.fact.partition(".")[0],
                        fact_id=item.fact.partition(".")[2],
                        op=item.op,
                        value=item.value,
                    )
                    for item in branch.when
                ),
                target_stage_ids=branch.release,
            )
            for branch in route.branches
        ),
        else_stage_ids=route.else_,
    )


def _revisit(region: RevisitDeclaration) -> RevisitRegion:
    progress = None
    if region.progress is not None:
        stage, _, fact = region.progress.partition(".")
        progress = FactRef(stage_id=stage, fact_id=fact)
    return RevisitRegion(
        region_id=region.key,
        stage_ids=region.stages,
        entry_stage_id=region.entry,
        exit_stage_id=region.exit,
        max_visits=region.max_visits,
        until=tuple(
            FactPredicate(
                stage_id=item.fact.partition(".")[0],
                fact_id=item.fact.partition(".")[2],
                op=item.op,
                value=item.value,
            )
            for item in region.until
        ),
        progress=progress,
        patience=region.patience,
        carry=tuple(
            CarriedOutput(stage_id=region.exit, output_slot_id=name) for name in region.carry
        ),
    )


def _route_obligations(
    definition: MissionDefinition,
    children: tuple[DefinitionNode, ...],
    owners: Mapping[str, str],
    routes: tuple[StageRoute, ...],
) -> dict[str, set[str]]:
    """OVE-171 applicability: a goal owned by a route target is owed by whichever of the
    alternative targets that serve it (by objectives) the route selects. A required promise
    of a target no alternative serves still survives its branch not being selected."""

    targets = {stage for route in routes for stage in route.target_stage_ids}
    extra: dict[str, set[str]] = {}
    for child in children:
        if child.key not in targets:
            continue
        for key in child.objectives:
            goal = _owning_goal(definition, key)
            if goal is not None and owners.get(goal) in targets and owners[goal] != child.key:
                extra.setdefault(child.key, set()).add(goal)
    return extra


def _graph_semantics(root: DefinitionNode, children: tuple[DefinitionNode, ...]) -> bool:
    siblings = {child.key for child in children}
    return (
        bool(root.routes)
        or bool(root.revisits)
        or any(
            child.release_groups
            or child.facts
            or child.join != "all"
            or any(
                item.source == "from"
                and item.ref is not None
                and item.ref.partition(".")[0] in siblings
                and not item.required
                for item in child.inputs
            )
            for child in children
        )
    )


def _schema_pin(
    schema_ref: str | None, output_schemas: Mapping[str, OutputSchemaBinding]
) -> SchemaPin | None:
    if schema_ref is None:
        return None
    bound = output_schemas.get(schema_ref)
    if bound is None:
        return SchemaPin(ref=schema_ref)
    return SchemaPin(ref=schema_ref, digest=bound.schema_digest, body=bound.json_schema)


def _adopted(exports: tuple[NestedExport, ...], owner: DefinitionNode) -> tuple[NestedExport, ...]:
    declared = {output.name: output.key for output in owner.outputs}
    return tuple(
        item.model_copy(update={"adopt_into": declared.get(item.output)}) for item in exports
    )


def _program_outputs(
    definition: MissionDefinition, position: str | None = None
) -> list[tuple[str, DefinitionOutput]]:
    """Every output this program itself owes, with its owner position. A Stage Graph root runs
    no cognition, so its outputs are exports of its stages' promises (OVE-169,
    ``stage_graph_root_sources``), never a promise of their own. A nested composite (OVE-176)
    owes its declared outputs at its stage's position; what its body produces belongs to the
    body's own run and is reached only through the composite's exports, never flattened into
    its parent.

    ``position`` is the absolute path of a nested body's root: its promises keep their nesting
    identity, and a nested Stage Graph's own outputs are its exports (owed by its parent).
    """

    found: list[tuple[str, DefinitionOutput]] = []
    root = definition.program

    def walk(node: DefinitionNode, at: str) -> None:
        found.extend((at, output) for output in node.outputs)
        if node.behavior is Behavior.GOAL_LOOP or (node is not root and composite(node)):
            return  # a recursive body: its own run owes what it produces
        for child in node.nodes:
            walk(child, f"{at}/{child.key}")

    if root.behavior is Behavior.STAGE_GRAPH:
        for child in root.nodes:
            walk(child, child.key if position is None else f"{position}/{child.key}")
    else:
        walk(root, position or root.key)
    return found


def output_promises(
    definition: MissionDefinition,
    output_schemas: Mapping[str, OutputSchemaBinding] | None = None,
    *,
    position: str | None = None,
) -> OutputPromiseSet | None:
    """Compile the exact named output promises of a definition (``mc.output_promises.v1``).

    Each declared output becomes one ``OutputObligation@2`` owned by its node's position,
    with its form, enforcement, distinct cardinality, coverage, requirements, nested member
    guarantees and pinned schema. Completion is the closed conjunction over every declared
    obligation; expected and optional promises never block it (their shortfalls stay
    visible), required ones do. ``None`` when the program promises no output.
    """

    schemas = dict(output_schemas or {})
    obligations = [
        OutputObligation(
            key=output.key,
            owner_position=position,
            evaluation_scope=output.scope,
            enforcement=output.enforcement,
            cardinality=output.cardinality,
            contract=OutputContract(
                form=output.form,
                media_type=output.media_type,
                schema_pin=_schema_pin(output.schema_ref, schemas),
                requirements=output.requirements,
                coverage=output.coverage,
                member_contract=output.members,
                repository=output.repository,
                receipt_capabilities=output.receipts,
            ),
        )
        for position, output in _program_outputs(definition, position)
    ]
    if not obligations:
        return None
    return OutputPromiseSet(
        obligations=tuple(obligations),
        completion=AllOf(items=tuple(ObligationLeaf(obligation=item.key) for item in obligations)),
        # The closed vocabularies a completion expression may name besides promises.
        criteria=tuple(f"{item.goal_key}.{item.key}" for item in definition.criteria),
        human_tasks=tuple(sorted(_human_tasks(definition.program))),
    )


def _human_tasks(node: DefinitionNode) -> set[str]:
    found = {node.key} if node.behavior is Behavior.HUMAN_GATE else set()
    for child in node.nodes:
        found |= _human_tasks(child)
    return found


def _stage_children(root: DefinitionNode) -> tuple[DefinitionNode, ...]:
    if root.behavior is Behavior.STAGE_GRAPH:
        return root.nodes
    return (root,)


def _stage_blueprint(
    definition: MissionDefinition,
    root: DefinitionNode,
    base_id: str,
    output_schemas: Mapping[str, OutputSchemaBinding],
    *,
    position: str | None = None,
    depth: int = 0,
) -> tuple[StageGraphBlueprint, frozenset[str], tuple[ManifestIssue, ...]]:
    children = _stage_children(root)
    warnings: list[ManifestIssue] = []
    nested: list[NestedBody] = []
    keys = {child.key for child in children}
    goals = required_goals(definition)
    owners = goal_owners(definition, children)
    if root.behavior is Behavior.STAGE_GRAPH:
        unowned = sorted(goals - owners.keys())
        if unowned:
            # The last stage never proves goals it does not serve (OUTPUT-CONTRACTS §2).
            raise ValueError(
                f"required goals {unowned} have no owning stage: name them in a stage's "
                "objectives or cite one of its declared outputs as criterion evidence"
            )
    else:
        # A single-position program: its one node serves every required goal.
        for goal in sorted(goals):
            owners.setdefault(goal, root.key)
    specs = []
    waits = []
    routes = tuple(_route(item) for item in root.routes)
    semantics = GRAPH_SEMANTICS_V1 if _graph_semantics(root, children) else None
    alternative_owners = _route_obligations(definition, children, owners, routes)
    for child in children:
        if root.behavior is Behavior.STAGE_GRAPH and composite(child):
            # OVE-176: the stage's body executes recursively (never flattened into one stage).
            nested.append(
                _nested_body(
                    definition,
                    child,
                    child.key,
                    child.key if position is None else f"{position}/{child.key}",
                    depth + 1,
                    output_schemas,
                )
            )
        if child.behavior in {Behavior.HUMAN_GATE, Behavior.EVENT_WAIT}:
            # An event_wait stage holds on its declared wait until its implied watcher (or an
            # operator) satisfies it (SPEC-04 §5, `mission_watchers`).
            waits.append(StageGraphWait(scope_kind="stage", scope_id=child.key, wait_id=child.key))
        outputs = tuple(item.name for item in child.outputs) or ("result",)
        schema_criteria: list[SchemaCriterion] = []
        by_name = {item.name: item for item in child.outputs}
        for criterion in definition.criteria:
            expression = criterion.acceptance
            if (
                owners.get(criterion.goal_key) == child.key
                and expression.op == "schema"
                and expression.schema_ref in output_schemas
                and criterion.evidence
                and all(
                    name in by_name and by_name[name].schema_ref == expression.schema_ref
                    for name in criterion.evidence
                )
            ):
                schema_criteria.append(
                    SchemaCriterion(
                        criterion_key=f"{criterion.goal_key}.{criterion.key}",
                        obligation_ref=criterion.goal_key,
                        schema_ref=expression.schema_ref,
                        output_slots=criterion.evidence,
                    )
                )
        if child.completion is not None and child.completion.op == "schema":
            schema_ref = child.completion.schema_ref
            matching = tuple(item.name for item in child.outputs if item.schema_ref == schema_ref)
            if schema_ref in output_schemas and matching:
                schema_criteria.append(
                    SchemaCriterion(
                        criterion_key=f"node:{child.key}",
                        schema_ref=schema_ref,
                        output_slots=matching,
                    )
                )
        bindings = _bindings(child, keys)
        groups = _group_specs(child)
        grouped = {member for group in groups for member in group.member_stage_ids}
        # A binding is its own dependency (01-STAGE_GRAPH §3); group members join their group.
        depends_on = tuple(
            dict.fromkeys(
                item
                for item in (
                    *child.depends_on,
                    *(binding.producer_stage_id for binding in bindings),
                )
                if item in keys and item not in grouped
            )
        )
        join, minimum = _join(child)
        # OVE-176: a stage hosting a nested body reserves the body's spend at admission.
        reservation = (
            {"operation.attempts": 1, **spend_reservation(body_budget(definition, child))}
            if root.behavior is Behavior.STAGE_GRAPH and composite(child)
            else None
        )
        specs.append(
            StageGraphStageSpec(
                stage_id=child.key,
                reservation=reservation,
                depends_on=depends_on,
                ordering_predecessors=tuple(child.depends_on),
                bindings=bindings,
                join=join,
                join_minimum=minimum,
                groups=groups,
                facts=tuple(
                    StageFact(
                        fact_id=fact.name,
                        output_slot_id=fact.output,
                        pointer=fact.pointer,
                        value_type=fact.type,
                    )
                    for fact in child.facts
                ),
                output_slots=outputs,
                output_declarations=tuple(
                    StageOutputSlot(
                        output_slot_id=item.name,
                        output_contract_ref=item.schema_ref
                        or f"output:{item.form.value}:{item.key}",
                        required=item.required,
                        validation_schema=None
                        if item.schema_ref is None
                        else output_schemas.get(item.schema_ref),
                    )
                    for item in child.outputs
                ),
                schema_criteria=tuple(schema_criteria),
                obligation_refs=tuple(
                    sorted(
                        {goal for goal, owner in owners.items() if owner == child.key}
                        | alternative_owners.get(child.key, set())
                    )
                ),
                operation_contract_ref=f"operation:{base_id}:{child.key}@1",
            )
        )
    concurrency = 1
    if root.behavior is Behavior.STAGE_GRAPH:
        concurrency = int(root.body.get("concurrency") or 1)
    blueprint = build_stagegraph_v2(
        logical_id=f"{base_id}.blueprint",
        title=f"{definition.title} (Stage Graph)",
        description=f"Stage Graph lowered from mission {definition.mission_key}.",
        stages=tuple(specs),
        max_concurrency=concurrency,
        routes=routes,
        graph_semantics=semantics,
    )
    if waits:
        blueprint = StageGraphBlueprint.model_validate(
            {**blueprint.model_dump(mode="python"), "waits": tuple(waits)}
        )
    if root.revisits:
        blueprint = StageGraphBlueprint.model_validate(
            {
                **blueprint.model_dump(mode="python"),
                "revisit_regions": tuple(_revisit(item) for item in root.revisits),
            }
        )
    if nested:
        blueprint = StageGraphBlueprint.model_validate(
            {**blueprint.model_dump(mode="python"), "nested_bodies": tuple(nested)}
        )
    return blueprint, frozenset(owners), tuple(warnings)


def lower_mission(
    definition: MissionDefinition,
    *,
    capability_refs: Iterable[ExactDefinitionRef] = (),
    output_schemas: Mapping[str, OutputSchemaBinding] | None = None,
    position: str | None = None,
    depth: int = 0,
) -> LoweredMission:
    """Lower one resolved definition. Pure: the same definition and refs give the same rows.

    ``position``/``depth`` lower a nested body's derived definition (OVE-176): its promises keep
    their absolute nesting position and its own nested bodies are one level deeper.
    """

    base_id = lowering_base_id(definition)
    schemas = dict(output_schemas or {})
    if schemas:
        # Schema custody participates in immutable compiler identity; catalog changes
        # cannot rewrite a previously admitted run or collide with revision 1.
        suffix = sha256_digest(schemas).removeprefix("sha256:")[:12]
        base_id += f".schemas-{suffix}"
    root = definition.program
    warnings: tuple[ManifestIssue, ...] = ()
    family: Family
    initial_goal: str | None = None
    if root.behavior is Behavior.GOAL_LOOP:
        family = "GoalDirected"
        if schemas:
            base_id += ".goal-output-v1"
        blueprint: StageGraphBlueprint | GoalDirectedBlueprint
        blueprint, obligations, outputs, initial_goal = _goal_blueprint(
            definition, root, base_id, schemas, position=position or root.key, depth=depth
        )
        authority = blueprint.authority_ceiling
        workspace = GOAL_WORKSPACE
    else:
        family = "StageGraph"
        blueprint, obligations, warnings = _stage_blueprint(
            definition, root, base_id, schemas, position=position, depth=depth
        )
        outputs = frozenset()
        authority = AuthorityCeiling(
            capabilities=MANIFEST_RUN_CAPABILITIES,
            budgets=BudgetCeiling(dimensions=budget_dimensions(definition, goal_iterations=None)),
            max_concurrency=max(1, int(root.body.get("concurrency") or 1))
            if root.behavior is Behavior.STAGE_GRAPH
            else 1,
        )
        workspace = STAGE_WORKSPACE
    refs = tuple(
        sorted(set(capability_refs), key=lambda ref: (ref.kind.value, ref.logical_id, ref.revision))
    )
    runtime = RuntimeProfileDefinition(
        logical_id=f"{base_id}.runtime",
        title=f"{definition.mission_key} runtime",
        description=(
            f"Runtime profile lowered from mission {definition.mission_key}; the lane "
            "execution bindings come from the semantic input binding at launch."
        ),
        binding=MANIFEST_RUNTIME_BINDING,
        operation_binding_refs=frozenset(refs),
    )
    workspace_template = WorkspaceTemplateDefinition(
        logical_id=f"{base_id}.workspace",
        title=f"{definition.mission_key} workspace",
        description=f"Workspace template lowered from mission {definition.mission_key}.",
        slots=workspace.slots,
    )
    evaluation = EvaluationProfileDefinition(
        logical_id=f"{base_id}.evaluation",
        title=f"{definition.mission_key} evaluation",
        description=f"Evaluation gates lowered from mission {definition.mission_key} criteria.",
        gate_contract_refs=frozenset(
            f"criterion:{item.goal_key}.{item.key}" for item in definition.criteria
        ),
    )
    promises = output_promises(definition, schemas, position=position)
    if promises is not None:
        blueprint = type(blueprint).model_validate(
            {**blueprint.model_dump(mode="python"), "output_promises": promises}
        )
    inputs_digest = sha256_digest({"inputs": list(definition.inputs)})
    return LoweredMission(
        mission_key=definition.mission_key,
        family=family,
        base_id=base_id,
        blueprint=blueprint,
        runtime_profile=runtime,
        workspace_template=workspace_template,
        evaluation_profile=evaluation,
        authority=authority,
        obligations=obligations,
        output_contracts=outputs,
        workspace_contract=workspace,
        input_manifest=RunInputManifestRef(
            manifest_id=f"{base_id}.inputs", revision=1, digest=inputs_digest
        ),
        initial_goal=initial_goal,
        warnings=warnings,
    )


def lowering_digests(lowered: LoweredMission) -> dict[str, str]:
    return {
        "lowering_version": LOWERING_VERSION,
        "blueprint_digest": lowered.blueprint_digest,
        "runtime_profile_digest": lowered.runtime_profile_digest,
    }

from __future__ import annotations

from dataclasses import dataclass

from mission_control.domain.authoring.contracts import (
    AllowedOperationVariant,
    CapacityCeiling,
    CompletionObligationRef,
    DependencyClass,
    JoinKind,
    LateResultPolicy,
    LateResultRule,
    ObligationMatrixRow,
    SlowSiblingPolicy,
    StageDependency,
    StageGraphBlueprint,
    StageInputSlot,
    StageJoin,
    StageNode,
    StageObligationSlot,
    StageOperationSlot,
    StageOutputSlot,
    WorkflowCyclePolicy,
)
from mission_control.domain.authoring.graph_routes import (
    GraphSemantics,
    JoinGroup,
    MemberCoverage,
    StageFact,
    StageRoute,
)
from mission_control.domain.programs.completion import SchemaCriterion


@dataclass(frozen=True)
class StageInputBindingSpec:
    """One explicit named data binding: the consumer reads this exact producer output."""

    producer_stage_id: str
    producer_output_slot_id: str
    required: bool = True
    ordering_only: bool = False


@dataclass(frozen=True)
class StageReleaseGroupSpec:
    """OVE-171: one named release group of a consumer (members in declared position order)."""

    group_id: str
    member_stage_ids: tuple[str, ...]
    join: JoinKind = JoinKind.ALL
    minimum: int | None = None
    coverage_subjects: tuple[str, ...] = ()
    member_coverage: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class StageGraphStageSpec:
    """Compact authoring input that expands only into canonical StageGraph V2 contracts.

    ``depends_on`` enumerates predecessors; ``ordering_predecessors`` preserves explicit
    completion gates while ``bindings`` name exact outputs a consumer reads. A predecessor
    without a data binding waits on admitted completion, carrying no output data.
    ``join`` is the authored release rule (``all``, ``any`` or ``minimum``).
    """

    stage_id: str
    depends_on: tuple[str, ...] = ()
    output_slots: tuple[str, ...] = ()
    obligation_refs: tuple[str, ...] = ()
    reservation: dict[str, int] | None = None
    operation_contract_ref: str = "operation:native-stage@1"
    output_declarations: tuple[StageOutputSlot, ...] = ()
    schema_criteria: tuple[SchemaCriterion, ...] = ()
    bindings: tuple[StageInputBindingSpec, ...] = ()
    join: JoinKind = JoinKind.ALL
    join_minimum: int | None = None
    # OVE-171 (graph routes semantics): named release groups and typed facts of the stage.
    groups: tuple[StageReleaseGroupSpec, ...] = ()
    facts: tuple[StageFact, ...] = ()
    # Manifest lowering distinguishes explicit ordering from binding-derived dependencies.
    ordering_predecessors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.output_declarations
            and tuple(item.output_slot_id for item in self.output_declarations) != self.output_slots
        ):
            raise ValueError("output declarations must match the stage output slots")


def build_stagegraph_v2(
    *,
    logical_id: str,
    title: str,
    description: str,
    stages: tuple[StageGraphStageSpec, ...],
    max_concurrency: int = 1,
    workflow_evaluation_contract_ref: str | None = None,
    workflow_cycle_policy: WorkflowCyclePolicy | None = None,
    routes: tuple[StageRoute, ...] = (),
    graph_semantics: GraphSemantics | None = None,
) -> StageGraphBlueprint:
    """Expand concise domain authoring into the complete typed V2 graph surface.

    With ``graph_semantics`` (OVE-171) an any/quorum ``join`` becomes the named group
    ``inputs`` (exact first-qualifying selection), each named group is its own join
    ``<stage>:group:<key>``, and optional bindings sit in ``<stage>:optional`` (omitted
    visibly when still pending at release). Without it the expansion is unchanged.
    """
    specs = {item.stage_id: item for item in stages}
    if len(specs) != len(stages):
        raise ValueError("StageGraph stage specs must have unique identities")
    dependencies: list[StageDependency] = []
    joins: list[StageJoin] = []
    nodes: list[StageNode] = []
    obligation_matrix: list[ObligationMatrixRow] = []
    completion_obligations: list[CompletionObligationRef] = []
    for spec in stages:
        input_slots: list[StageInputSlot] = []
        dependency_ids: list[str] = []
        member_group = {
            member: group.group_id for group in spec.groups for member in group.member_stage_ids
        }
        producers = tuple(
            dict.fromkeys(
                (
                    *spec.depends_on,
                    *(member for group in spec.groups for member in group.member_stage_ids),
                )
            )
        )
        if member_group and graph_semantics is None:
            raise ValueError("named release groups require the graph routes semantics")
        join_edges: dict[str, list[str]] = {}
        for producer_id in producers:
            producer = specs.get(producer_id)
            if producer is None or not producer.output_slots:
                raise ValueError(f"StageGraph producer {producer_id!r} must declare an output slot")
            # A binding to an output the producer stage does not declare as a slot (an
            # implicit human-gate resolution, a context alias) is delivered by its own path.
            bound = [
                item
                for item in spec.bindings
                if item.producer_stage_id == producer_id
                and item.producer_output_slot_id in producer.output_slots
            ]
            if not bound:
                bound = [
                    StageInputBindingSpec(producer_id, slot, ordering_only=True)
                    for slot in producer.output_slots
                ]
            elif producer_id in spec.ordering_predecessors:
                # Optional data can be omitted at release, but an explicit depends_on
                # still waits for this producer. Never promote that data to required.
                bound.extend(
                    StageInputBindingSpec(producer_id, slot, ordering_only=True)
                    for slot in producer.output_slots
                )
            for item in bound:
                single = len(bound) == 1
                slot_id = (
                    f"from:{producer_id}"
                    if single
                    else f"from:{producer_id}:{item.producer_output_slot_id}"
                )
                dependency_id = (
                    f"{producer_id}:to:{spec.stage_id}"
                    if single
                    else f"{producer_id}:{item.producer_output_slot_id}:to:{spec.stage_id}"
                )
                if item.ordering_only:
                    slot_id += ":order"
                    dependency_id += ":order"
                input_slots.append(StageInputSlot(input_slot_id=slot_id, required=item.required))
                dependency_ids.append(dependency_id)
                join_key = member_group.get(producer_id, "inputs")
                control_order = item.ordering_only and producer_id in spec.ordering_predecessors
                if control_order:
                    join_key = "ordering"
                if graph_semantics is not None and join_key == "inputs" and not item.required:
                    join_key = "optional"
                join_id = (
                    f"{spec.stage_id}:ordering"
                    if control_order
                    else (
                        f"{spec.stage_id}:{join_key}"
                        if join_key in {"inputs", "optional"}
                        else f"{spec.stage_id}:group:{join_key}"
                    )
                )
                join_edges.setdefault(join_id, []).append(dependency_id)
                dependencies.append(
                    StageDependency(
                        dependency_id=dependency_id,
                        consumer_stage_id=spec.stage_id,
                        join_id=join_id,
                        producer_stage_id=producer_id,
                        producer_output_slot_id=item.producer_output_slot_id,
                        consumer_input_slot_id=slot_id,
                        dependency_class=DependencyClass.REQUIRED
                        if item.required
                        else DependencyClass.OPTIONAL,
                        ordering_only=item.ordering_only,
                    )
                )
        inputs = tuple(input_slots)
        groups = {group.group_id: group for group in spec.groups}
        for join_id, edge_ids in join_edges.items():
            key = join_id.removeprefix(f"{spec.stage_id}:").removeprefix("group:")
            group_spec = groups.get(key) if join_id.startswith(f"{spec.stage_id}:group:") else None
            kind = (
                group_spec.join
                if group_spec is not None
                else JoinKind.ALL
                if key in {"optional", "ordering"}
                else spec.join
            )
            minimum = (
                (group_spec.minimum if group_spec is not None else spec.join_minimum)
                if kind is JoinKind.MINIMUM
                else None
            )
            members = tuple(
                dict.fromkeys(
                    edge.producer_stage_id
                    for edge in dependencies
                    if edge.dependency_id in edge_ids and edge.consumer_stage_id == spec.stage_id
                )
            )
            group: JoinGroup | None = None
            if group_spec is not None:
                group = JoinGroup(
                    group_id=group_spec.group_id,
                    member_stage_ids=group_spec.member_stage_ids,
                    coverage_subjects=group_spec.coverage_subjects,
                    member_coverage=tuple(
                        MemberCoverage(producer_stage_id=producer, subjects=subjects)
                        for producer, subjects in group_spec.member_coverage
                    ),
                )
            elif graph_semantics is not None and key == "inputs" and kind is not JoinKind.ALL:
                group = JoinGroup(group_id="inputs", member_stage_ids=members)
            joins.append(
                StageJoin(
                    consumer_stage_id=spec.stage_id,
                    join_id=join_id,
                    kind=kind,
                    minimum=minimum,
                    dependency_ids=tuple(edge_ids),
                    slow_sibling_policy=SlowSiblingPolicy(
                        triggers=("join_released",),
                        execution_action="continue",
                        arrival_route="evaluate_late_result",
                    ),
                    group=group,
                )
            )
        obligation_slots = tuple(
            StageObligationSlot(
                obligation_slot_id=obligation_ref,
                obligation_ref=obligation_ref,
            )
            for obligation_ref in spec.obligation_refs
        )
        for obligation_ref in spec.obligation_refs:
            obligation_matrix.append(
                ObligationMatrixRow(
                    obligation_scope="stage",
                    owner_stage_id=spec.stage_id,
                    obligation_slot_id=obligation_ref,
                    evidence_slot_id=obligation_ref,
                )
            )
            completion_obligations.append(
                CompletionObligationRef(
                    obligation_scope="stage",
                    owner_stage_id=spec.stage_id,
                    obligation_slot_id=obligation_ref,
                )
            )
        nodes.append(
            StageNode(
                stage_id=spec.stage_id,
                input_slots=inputs,
                output_slots=spec.output_declarations
                or tuple(
                    StageOutputSlot(
                        output_slot_id=slot_id,
                        output_contract_ref=f"output:{logical_id}:{slot_id}@1",
                    )
                    for slot_id in spec.output_slots
                ),
                obligation_slots=obligation_slots,
                schema_criteria=spec.schema_criteria,
                facts=spec.facts,
                operation_slots=(
                    StageOperationSlot(
                        operation_slot_id="execute",
                        reservation=dict(spec.reservation or {"operation.attempts": 1}),
                        allowed_variants=(
                            AllowedOperationVariant(
                                operation_variant_id="default",
                                operation_contract_ref=spec.operation_contract_ref,
                            ),
                        ),
                    ),
                ),
            )
        )
    return StageGraphBlueprint(
        logical_id=logical_id,
        title=title,
        description=description,
        stages=tuple(nodes),
        joins=tuple(joins),
        dependencies=tuple(dependencies),
        obligation_matrix=tuple(obligation_matrix),
        completion_obligations=tuple(completion_obligations),
        capacity_ceilings=(
            CapacityCeiling(
                scope_kind="workflow",
                scope_id=logical_id,
                dimension_kind="concurrency",
                dimension_id="operation-slots",
                amount=max_concurrency,
            ),
        ),
        late_result_policy=LateResultPolicy(
            rules=(
                LateResultRule(
                    rule_id="consumer-already-admitted:admit",
                    trigger="consumer_already_admitted",
                    decision="admit",
                ),
            )
        ),
        workflow_evaluation_contract_ref=workflow_evaluation_contract_ref,
        workflow_cycle_policy=workflow_cycle_policy,
        routes=routes,
        graph_semantics=graph_semantics,
    )


__all__ = [
    "StageGraphStageSpec",
    "StageInputBindingSpec",
    "StageReleaseGroupSpec",
    "build_stagegraph_v2",
]

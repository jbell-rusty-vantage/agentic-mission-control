from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Literal

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    DependencyClass,
    JoinKind,
    StageDependency,
    StageGraphBlueprint,
    StageJoin,
    StageOperationSlot,
)
from mission_control.domain.programs.completion import output_binding_errors
from mission_control.domain.programs.contracts import (
    AcceptedResultFact,
    CandidateOrderingKey,
    DependencyDisposition,
    DependencyProjection,
    ExecutionIdentity,
    FactObservation,
    FairnessCursorState,
    GraphExhaustion,
    JoinDisposition,
    LateResultFacts,
    ProducerLiability,
    ResultDecision,
    ResultDispositionProposal,
    RevisitDecision,
    RouteBranchDisposition,
    RouteDecision,
    StageCandidateIdentity,
    StageContinuesFrom,
    StageExecutionIdentity,
    StageGraphAcceptedProjection,
    StageGraphCompletionProposal,
    StageGraphStartPosition,
    StageInputBinding,
    StageInstanceProjection,
    StageInvalidationProposal,
    StageOperationAdmissionProposal,
    StageReleasedBy,
    StageResultObservation,
    StageStatus,
    WorkflowInvalidationProposal,
)
from mission_control.domain.programs.dependencies import descendants_by_stage
from mission_control.domain.programs.routing import (
    MemberState,
    evaluate_predicate,
    evaluate_route,
    fact_from_result,
    group_outcome,
    target_gates,
)

TERMINAL_DEPENDENCY_DISPOSITIONS = frozenset(
    {
        DependencyDisposition.FULFILLED,
        DependencyDisposition.DEGRADED,
        DependencyDisposition.OMITTED,
        DependencyDisposition.FAILED,
        DependencyDisposition.CANCELLED,
        DependencyDisposition.INVALID,
    }
)


class StageGraphExecutionError(ValueError):
    pass


EdgeState = Literal["satisfied", "pending", "failed", "ignored"]
EdgeSelection = Literal["selected", "surplus", "omitted", "unavailable"]
_TERMINAL_NEGATIVE = frozenset(
    {"failed", "cancelled", "skipped", "invalidated", "structurally_unavailable"}
)


@dataclass(frozen=True)
class GraphRouteView:
    """OVE-171: the derived route state of one projection (pure; never persisted on its own).

    ``gates`` holds each route target's gate; ``skipped`` the stages whose branch was not
    selected plus their conclusively unreleasable required dependents (01-STAGE_GRAPH §7).
    """

    decisions: tuple[RouteDecision, ...] = ()
    gates: dict[str, RouteBranchDisposition] | None = None
    skipped: frozenset[str] = frozenset()

    def gate(self, stage_id: str) -> RouteBranchDisposition | None:
        return None if self.gates is None else self.gates.get(stage_id)


class StageGraphInterpreter:
    """Pure proposal interpreter for one immutable normalized StageGraph V2."""

    def __init__(
        self,
        blueprint: StageGraphBlueprint,
        *,
        effective_max_concurrency: int,
        control_gate_keys: frozenset[str] = frozenset(),
    ) -> None:
        if effective_max_concurrency < 1:
            raise StageGraphExecutionError("effective concurrency must be positive")
        oversized = [
            (stage.stage_id, slot.operation_slot_id)
            for stage in blueprint.stages
            for slot in stage.operation_slots
            if slot.concurrency_slots > effective_max_concurrency
        ]
        if oversized:
            raise StageGraphExecutionError(
                f"stages exceed the effective concurrency ceiling: {sorted(oversized)}"
            )
        if not control_gate_keys <= {stage.stage_id for stage in blueprint.stages}:
            raise StageGraphExecutionError("control gate is not a blueprint stage")
        self.control_gate_keys = control_gate_keys
        self.blueprint = blueprint
        self.stages = {stage.stage_id: stage for stage in blueprint.stages}
        self.max_concurrency = effective_max_concurrency
        self.dependencies = {item.dependency_id: item for item in blueprint.dependencies}
        self.joins = {(item.consumer_stage_id, item.join_id): item for item in blueprint.joins}
        self.stage_joins: dict[str, tuple[StageJoin, ...]] = {
            stage_id: tuple(item for item in blueprint.joins if item.consumer_stage_id == stage_id)
            for stage_id in self.stages
        }
        self.descendants = self._descendants()
        self.group_ring = self._weighted_group_ring()
        # OVE-171: graph routes semantics (route gating, visible optional omission, exact
        # group selection) apply only to a blueprint compiled with them.
        self.graph_routes = blueprint.graph_semantics is not None
        self.route_by_target = {
            stage_id: route for route in blueprint.routes for stage_id in route.target_stage_ids
        }
        self.stage_facts = {
            (stage.stage_id, fact.fact_id): fact
            for stage in blueprint.stages
            for fact in stage.facts
        }
        # OVE-171 slice D: the one declared Revisit Region and its downstream consumers.
        self.region = blueprint.revisit_regions[0] if blueprint.revisit_regions else None
        region_stages = set(self.region.stage_ids) if self.region is not None else set()
        self.region_consumers = frozenset(
            edge.consumer_stage_id
            for edge in blueprint.dependencies
            if edge.producer_stage_id in region_stages
            and edge.consumer_stage_id not in region_stages
        )

    def initial_projection(
        self,
        identity: ExecutionIdentity,
        *,
        run_version: int,
        start: StageGraphStartPosition | None = None,
    ) -> StageGraphAcceptedProjection:
        """The first accepted projection; with `start` (1.4.4, TR-D13: a fork-derived run)
        the candidates of a stage begin at the given stage cycle with its objective override
        and the projection at the given workflow cycle, so the seeded unit's identity is the
        source's. A start naming an unknown stage, or a cycle the stage's policy does not
        allow, is refused."""

        cycles = dict(start.stage_cycle_ordinals) if start is not None else {}
        objectives = dict(start.stage_objectives) if start is not None else {}
        workflow_cycle = start.workflow_cycle_ordinal if start is not None else 0
        unknown = sorted((set(cycles) | set(objectives)) - set(self.stages))
        if unknown:
            raise StageGraphExecutionError(f"start position names unknown stages: {unknown}")
        for stage_id, cycle in cycles.items():
            policy = self.stages[stage_id].stage_cycle_policy
            allowed = policy.max_cycles if policy is not None else 0
            if cycle > allowed:
                raise StageGraphExecutionError(
                    f"start position cycle {cycle} of {stage_id} exceeds its policy ({allowed})"
                )
        stages: dict[str, StageInstanceProjection] = {}
        for stage in self.blueprint.stages:
            initial_status: StageStatus = (
                "ready" if not self.stage_joins[stage.stage_id] else "blocked"
            )
            for operation_slot in stage.operation_slots:
                candidate = StageCandidateIdentity(
                    stage_id=stage.stage_id,
                    mapped_instance_presence=0,
                    mapped_instance_id="NO_MAPPED_INSTANCE",
                    workflow_cycle_ordinal=workflow_cycle,
                    stage_cycle_ordinal=cycles.get(stage.stage_id, 0),
                    operation_slot_id=operation_slot.operation_slot_id,
                )
                stages[candidate.semantic_prefix] = StageInstanceProjection(
                    candidate=candidate,
                    status=initial_status,
                    objective_override=objectives.get(stage.stage_id),
                )
        return StageGraphAcceptedProjection(
            identity=identity,
            family_version=0,
            run_version=run_version,
            workflow_cycle_ordinal=workflow_cycle,
            stages=stages,
            dependencies={
                item.dependency_id: DependencyProjection(dependency_id=item.dependency_id)
                for item in self.blueprint.dependencies
            },
            fairness=FairnessCursorState(
                group_ring_cursor=0,
                candidate_cursors={
                    group.group_id: None for group in self.blueprint.fairness_groups
                },
            ),
        )

    @staticmethod
    def dependency_satisfies(
        dependency_class: DependencyClass,
        disposition: DependencyDisposition,
    ) -> bool | None:
        if dependency_class == DependencyClass.ADVISORY:
            return None
        if disposition == DependencyDisposition.UNRESOLVED:
            return False
        if dependency_class == DependencyClass.REQUIRED:
            return disposition == DependencyDisposition.FULFILLED
        if dependency_class == DependencyClass.DEGRADABLE:
            return disposition in {
                DependencyDisposition.FULFILLED,
                DependencyDisposition.DEGRADED,
            }
        return disposition in TERMINAL_DEPENDENCY_DISPOSITIONS

    def join_disposition(
        self,
        join: StageJoin,
        projection: StageGraphAcceptedProjection,
        *,
        view: GraphRouteView | None = None,
    ) -> JoinDisposition:
        if self.graph_routes:
            skipped = (view or self.route_view(projection)).skipped
            return self._join_outcome(join, projection, skipped)[0]
        edges = [self.dependencies[item] for item in join.dependency_ids]
        non_advisory = [edge for edge in edges if edge.dependency_class != DependencyClass.ADVISORY]
        satisfied = 0
        unresolved = 0
        for edge in non_advisory:
            disposition = projection.dependencies[edge.dependency_id].disposition
            if disposition == DependencyDisposition.UNRESOLVED:
                unresolved += 1
            elif self.dependency_satisfies(edge.dependency_class, disposition):
                satisfied += 1
        count = len(non_advisory)
        if join.kind == JoinKind.ALL:
            if satisfied == count:
                return JoinDisposition.SATISFIED
            if satisfied + unresolved < count:
                return JoinDisposition.IMPOSSIBLE
            return JoinDisposition.PENDING
        if join.kind == JoinKind.ANY:
            if satisfied >= 1:
                return JoinDisposition.SATISFIED
            if unresolved == 0:
                return JoinDisposition.IMPOSSIBLE
            return JoinDisposition.PENDING
        minimum = join.minimum
        if minimum is None:
            raise StageGraphExecutionError("minimum join is missing its frozen threshold")
        if satisfied >= minimum:
            return JoinDisposition.SATISFIED
        if satisfied + unresolved < minimum:
            return JoinDisposition.IMPOSSIBLE
        return JoinDisposition.PENDING

    def frontier(
        self,
        projection: StageGraphAcceptedProjection,
        *,
        available_concurrency: int,
        blocked_candidate_keys: frozenset[str] = frozenset(),
    ) -> tuple[StageOperationAdmissionProposal, ...]:
        if available_concurrency < 0:
            raise StageGraphExecutionError("available concurrency cannot be negative")
        candidates_by_group: dict[
            str, list[tuple[CandidateOrderingKey, StageInstanceProjection]]
        ] = defaultdict(list)
        view = self.route_view(projection) if self.graph_routes else None
        for instance in projection.stages.values():
            if instance.status not in {"blocked", "ready"}:
                continue
            if view is not None and not self._route_released(instance.candidate.stage_id, view):
                continue
            if not self._region_released(instance.candidate.stage_id, projection):
                continue
            joins = self.stage_joins[instance.candidate.stage_id]
            dispositions = [self.join_disposition(item, projection, view=view) for item in joins]
            if any(item == JoinDisposition.IMPOSSIBLE for item in dispositions):
                continue
            if any(item != JoinDisposition.SATISFIED for item in dispositions):
                continue
            stage = self.stages[instance.candidate.stage_id]
            slot = next(
                item
                for item in stage.operation_slots
                if item.operation_slot_id == instance.candidate.operation_slot_id
            )
            key = CandidateOrderingKey(priority=slot.priority, identity=instance.candidate)
            candidates_by_group[stage.fairness_group_id].append((key, instance))
        for candidates in candidates_by_group.values():
            candidates.sort(key=lambda item: item[0].as_tuple())

        proposals: list[StageOperationAdmissionProposal] = []
        fairness = projection.fairness
        remaining = min(available_concurrency, self.max_concurrency)
        while candidates_by_group:
            selected = self._select_next_candidate(
                candidates_by_group,
                fairness,
                blocked_candidate_keys,
                remaining,
            )
            if selected is None:
                break
            ring_index, group_id, key, instance, slots = selected
            identity = StageExecutionIdentity(
                run_id=projection.identity.run_id,
                execution_epoch=projection.identity.execution_epoch,
                candidate=instance.candidate,
                semantic_attempt=instance.semantic_attempt + 1,
            )
            control = instance.candidate.stage_id in self.control_gate_keys
            reservation = {} if control else dict(slots.reservation)
            if not control:
                reservation["operation.attempts"] = 1
                reservation["concurrency.slots"] = slots.concurrency_slots
            next_candidate_cursors = dict(fairness.candidate_cursors)
            next_candidate_cursors[group_id] = key
            fairness = FairnessCursorState(
                group_ring_cursor=(ring_index + 1) % len(self.group_ring),
                candidate_cursors=next_candidate_cursors,
            )
            carried = self._carried_bindings(instance.candidate.stage_id, projection)
            input_refs = tuple(
                sorted(
                    {
                        *self._input_refs(instance.candidate.stage_id, projection, view),
                        *(item.artifact_ref for item in carried),
                    },
                    key=lambda item: item.encode("utf-8"),
                )
            )
            request_key = (
                f"{instance.candidate.stage_id}/"
                f"{instance.candidate.operation_slot_id}/"
                f"{slots.allowed_variants[0].operation_variant_id}"
            )
            exact_ref = (
                f"operation-request:{sha256_digest(identity.semantic_key).removeprefix('sha256:')}"
            )
            proposals.append(
                StageOperationAdmissionProposal(
                    ordering_key=key,
                    identity=identity,
                    operation_request_key=request_key,
                    exact_operation_request_ref=exact_ref,
                    reservation_id=f"reservation:{identity.semantic_key}",
                    reservation=reservation,
                    frozen_input_refs=input_refs,
                    selected_ring_index=ring_index,
                    next_fairness=fairness,
                    objective_override=instance.objective_override,
                    frozen_input_bindings=self._input_bindings(
                        instance.candidate.stage_id, projection, view
                    )
                    + carried,
                    released_by=self._released_by(instance.candidate.stage_id, projection, view),
                    continues_from=self._continues_from(instance, projection),
                    route_decisions=self._route_decisions_for(instance.candidate.stage_id, view),
                    revisit_decisions=self._revisit_decisions_for(instance, projection),
                )
            )
            remaining -= 0 if control else slots.concurrency_slots
            candidates_by_group[group_id] = [
                item for item in candidates_by_group[group_id] if item[0] != key
            ]
            if not candidates_by_group[group_id]:
                del candidates_by_group[group_id]
        return tuple(proposals)

    def running_concurrency(self, projection: StageGraphAcceptedProjection) -> int:
        """Return authoritative concurrency slots represented by admitted running stages."""
        total = 0
        for instance in projection.stages.values():
            if (
                instance.status != "running"
                or instance.candidate.stage_id in self.control_gate_keys
            ):
                continue
            stage = self.stages[instance.candidate.stage_id]
            slot = next(
                item
                for item in stage.operation_slots
                if item.operation_slot_id == instance.candidate.operation_slot_id
            )
            total += slot.concurrency_slots
        return total

    def apply_admission(
        self,
        projection: StageGraphAcceptedProjection,
        proposal: StageOperationAdmissionProposal,
        *,
        next_run_version: int,
        next_family_version: int,
    ) -> StageGraphAcceptedProjection:
        key = proposal.identity.candidate.semantic_prefix
        current = projection.stages.get(key)
        if current is None or current.status not in {"blocked", "ready"}:
            raise StageGraphExecutionError("operation admission does not match a ready candidate")
        stages = dict(projection.stages)
        stages[key] = replace(
            current,
            status="running",
            semantic_attempt=proposal.identity.semantic_attempt,
            admitted_operation_request_ref=proposal.exact_operation_request_ref,
            frozen_input_refs=proposal.frozen_input_refs,
            frozen_input_bindings=proposal.frozen_input_bindings,
        )
        liabilities = dict(projection.producer_liabilities)
        liabilities[proposal.identity.semantic_key] = ProducerLiability(
            semantic_attempt_id=proposal.identity.semantic_key,
            reservation_id=proposal.reservation_id,
            reserved_amounts=proposal.reservation,
        )
        return replace(
            projection,
            family_version=next_family_version,
            run_version=next_run_version,
            stages=stages,
            fairness=proposal.next_fairness,
            producer_liabilities=liabilities,
        )

    def apply_admission_rejection(
        self,
        projection: StageGraphAcceptedProjection,
        proposal: StageOperationAdmissionProposal,
        *,
        next_run_version: int,
        next_family_version: int,
    ) -> StageGraphAcceptedProjection:
        key = proposal.identity.candidate.semantic_prefix
        current = projection.stages.get(key)
        if (
            current is None
            or current.status not in {"blocked", "ready"}
            or proposal.identity.semantic_attempt != current.semantic_attempt + 1
        ):
            raise StageGraphExecutionError("rejection does not match an unadmitted candidate")
        stages = dict(projection.stages)
        stages[key] = replace(current, status="failed")
        dependencies = dict(projection.dependencies)
        for edge in self._producer_edges(current.candidate.stage_id):
            prior = dependencies[edge.dependency_id]
            if prior.disposition == DependencyDisposition.UNRESOLVED:
                dependencies[edge.dependency_id] = replace(
                    prior,
                    disposition=self._negative_disposition(edge, cancelled=False),
                    evidence_refs=(),
                )
        return replace(
            projection,
            stages=stages,
            dependencies=dependencies,
            fairness=proposal.next_fairness,
            run_version=next_run_version,
            family_version=next_family_version,
        )

    def apply_result_decision(
        self,
        projection: StageGraphAcceptedProjection,
        observation: StageResultObservation,
        proposal: ResultDispositionProposal,
        *,
        next_run_version: int,
        next_family_version: int,
    ) -> StageGraphAcceptedProjection:
        if observation.identity != proposal.identity:
            raise StageGraphExecutionError("result observation and decision identities differ")
        if proposal.decision == ResultDecision.ADMIT:
            errors = self.result_validation_errors(
                observation.identity, observation.operation_result
            )
            if observation.operation_disposition != "completed" or errors:
                raise StageGraphExecutionError(
                    "cannot admit an unsuccessful or invalid completion candidate: "
                    + ", ".join(errors or (observation.operation_disposition,))
                )
        key = observation.identity.candidate.semantic_prefix
        current = projection.stages.get(key)
        if (
            current is None
            or current.status != "running"
            or current.semantic_attempt != observation.identity.semantic_attempt
        ):
            raise StageGraphExecutionError("result does not match the active semantic attempt")
        liabilities = dict(projection.producer_liabilities)
        liability = liabilities.get(observation.identity.semantic_key)
        if liability is None or liability.result_decision is not None:
            raise StageGraphExecutionError("producer result already has a decision or no liability")
        liabilities[observation.identity.semantic_key] = ProducerLiability(
            semantic_attempt_id=liability.semantic_attempt_id,
            reservation_id=liability.reservation_id,
            reserved_amounts=liability.reserved_amounts,
            child_closed_or_quiesced=observation.child_closed_or_quiesced,
            reservations_and_usage_settled=observation.reservations_and_usage_settled,
            effects_settled=observation.effects_settled,
            cancellation_reconciled=observation.cancellation_reconciled,
            result_decision=proposal.decision,
        )
        result = observation.operation_result
        raw_output_refs = result.get("output_refs", ())
        output_refs = (
            tuple(str(item) for item in raw_output_refs)
            if isinstance(raw_output_refs, list | tuple)
            else ()
        )
        stages = dict(projection.stages)
        stages[key] = replace(
            current,
            status=self._stage_status_for_result(proposal),
            output_refs=output_refs if proposal.decision == ResultDecision.ADMIT else (),
        )
        dependencies = dict(projection.dependencies)
        for edge in self._producer_edges(current.candidate.stage_id):
            existing = dependencies[edge.dependency_id]
            if existing.disposition != DependencyDisposition.UNRESOLVED:
                continue
            dependencies[edge.dependency_id] = replace(
                existing,
                disposition=proposal.dependency_dispositions[edge.dependency_id],
                evidence_refs=(
                    self.output_slot_refs(
                        current.candidate.stage_id, edge.producer_output_slot_id, result
                    )
                    if proposal.decision == ResultDecision.ADMIT and not edge.ordering_only
                    else ()
                ),
            )
        accepted_results = projection.accepted_results
        if proposal.decision == ResultDecision.ADMIT:
            accepted_results += (
                AcceptedResultFact(
                    identity=observation.identity,
                    operation_result=observation.operation_result,
                    accepted_at_order=observation.accepted_order,
                ),
            )
        accepted_results = tuple(
            sorted(
                accepted_results,
                key=lambda item: (
                    item.identity.candidate.stage_id.encode("utf-8"),
                    item.identity.candidate.mapped_instance_presence,
                    item.identity.candidate.mapped_instance_id.encode("utf-8"),
                    item.identity.candidate.workflow_cycle_ordinal,
                    item.identity.candidate.stage_cycle_ordinal,
                    item.identity.candidate.operation_slot_id.encode("utf-8"),
                    item.identity.semantic_attempt,
                ),
            )
        )
        raw_obligation_refs = observation.operation_result.get("obligation_refs", ())
        obligation_refs = (
            frozenset(str(item) for item in raw_obligation_refs)
            if proposal.decision == ResultDecision.ADMIT
            and isinstance(raw_obligation_refs, list | tuple)
            else frozenset()
        )
        return replace(
            projection,
            family_version=next_family_version,
            run_version=next_run_version,
            stages=stages,
            dependencies=dependencies,
            producer_liabilities=liabilities,
            accepted_results=accepted_results,
            accepted_obligation_evidence=(
                frozenset(projection.accepted_obligation_evidence) | obligation_refs
            ),
        )

    def workflow_invalidation(
        self,
        projection: StageGraphAcceptedProjection,
        *,
        invalidation_frontier: tuple[str, ...],
        next_objective: str,
    ) -> WorkflowInvalidationProposal:
        policy = self.blueprint.workflow_cycle_policy
        if policy is None or projection.workflow_cycle_ordinal >= policy.max_cycles:
            raise StageGraphExecutionError("workflow cycle limit exceeded")
        frontier = set(invalidation_frontier)
        if not frontier or not frontier <= self.stages.keys():
            raise StageGraphExecutionError("workflow cycle has an invalid invalidation frontier")
        if not next_objective:
            raise StageGraphExecutionError("a workflow cycle requires a new typed objective")
        invalidated = frontier | {
            descendant for stage_id in frontier for descendant in self.descendants[stage_id]
        }
        reused: dict[str, tuple[str, ...]] = {}
        for instance in projection.stages.values():
            if instance.candidate.stage_id not in invalidated and instance.output_refs:
                reused[instance.candidate.semantic_prefix] = instance.output_refs
        return WorkflowInvalidationProposal(
            next_workflow_cycle_ordinal=projection.workflow_cycle_ordinal + 1,
            invalidation_frontier=tuple(sorted(frontier, key=lambda item: item.encode("utf-8"))),
            invalidated_stage_ids=tuple(sorted(invalidated, key=lambda item: item.encode("utf-8"))),
            reused_output_refs=reused,
            next_objective=next_objective,
        )

    def stage_invalidation(
        self,
        projection: StageGraphAcceptedProjection,
        *,
        stage_id: str,
        next_objective: str,
    ) -> StageInvalidationProposal:
        stage = self.stages.get(stage_id)
        if stage is None or stage.stage_cycle_policy is None:
            raise StageGraphExecutionError("stage cycle is not authored")
        current = max(
            (
                item.candidate.stage_cycle_ordinal
                for item in projection.stages.values()
                if item.candidate.stage_id == stage_id
                and item.candidate.workflow_cycle_ordinal == projection.workflow_cycle_ordinal
            ),
            default=0,
        )
        if current >= stage.stage_cycle_policy.max_cycles:
            raise StageGraphExecutionError("stage cycle limit exceeded")
        if not next_objective:
            raise StageGraphExecutionError("a stage cycle requires a new typed objective")
        current_objectives = {
            item.objective_override
            for item in projection.stages.values()
            if item.candidate.stage_id == stage_id
            and item.candidate.workflow_cycle_ordinal == projection.workflow_cycle_ordinal
            and item.candidate.stage_cycle_ordinal == current
            and item.objective_override is not None
        }
        if next_objective in current_objectives:
            raise StageGraphExecutionError(
                "stage cycle made no objective progress under the frozen stopping rule"
            )
        invalidated = {stage_id, *self.descendants[stage_id]}
        reused = {
            item.candidate.semantic_prefix: item.output_refs
            for item in projection.stages.values()
            if item.candidate.stage_id not in invalidated and item.output_refs
        }
        prior = tuple(
            ref
            for item in projection.stages.values()
            if item.candidate.stage_id == stage_id
            for ref in item.output_refs
        )
        unmet = tuple(
            slot.obligation_ref
            for slot in stage.obligation_slots
            if slot.obligation_ref not in projection.accepted_obligation_evidence
        )
        return StageInvalidationProposal(
            stage_id=stage_id,
            prior_stage_cycle_ordinal=current,
            next_stage_cycle_ordinal=current + 1,
            invalidated_stage_ids=tuple(sorted(invalidated, key=lambda item: item.encode("utf-8"))),
            reused_output_refs=reused,
            unmet_obligation_refs=unmet,
            accepted_evidence_refs=tuple(sorted(projection.accepted_obligation_evidence)),
            allowed_input_refs=self._input_refs(stage_id, projection),
            prior_result_refs=prior,
            next_objective=next_objective,
        )

    def apply_stage_invalidation(
        self,
        projection: StageGraphAcceptedProjection,
        proposal: StageInvalidationProposal,
        *,
        next_run_version: int,
        next_family_version: int,
    ) -> StageGraphAcceptedProjection:
        invalidated = frozenset(proposal.invalidated_stage_ids)
        stages = dict(projection.stages)
        for key, instance in tuple(stages.items()):
            if instance.candidate.stage_id in invalidated:
                stages[key] = replace(instance, status="invalidated")
        for stage_id in sorted(invalidated, key=lambda item: item.encode("utf-8")):
            stage = self.stages[stage_id]
            for slot in stage.operation_slots:
                candidate = StageCandidateIdentity(
                    stage_id=stage_id,
                    mapped_instance_presence=0,
                    mapped_instance_id="NO_MAPPED_INSTANCE",
                    workflow_cycle_ordinal=projection.workflow_cycle_ordinal,
                    stage_cycle_ordinal=proposal.next_stage_cycle_ordinal,
                    operation_slot_id=slot.operation_slot_id,
                )
                stages[candidate.semantic_prefix] = StageInstanceProjection(
                    candidate=candidate,
                    status="ready" if not self.stage_joins[stage_id] else "blocked",
                    objective_override=(
                        proposal.next_objective if stage_id == proposal.stage_id else None
                    ),
                )
        dependencies = dict(projection.dependencies)
        for edge in self.blueprint.dependencies:
            if edge.producer_stage_id not in invalidated:
                continue
            prior = dependencies[edge.dependency_id]
            dependencies[edge.dependency_id] = DependencyProjection(
                dependency_id=edge.dependency_id,
                generation=prior.generation + 1,
                disposition=DependencyDisposition.UNRESOLVED,
                supersedes_generation=prior.generation,
            )
        return replace(
            projection,
            family_version=next_family_version,
            run_version=next_run_version,
            stages=stages,
            dependencies=dependencies,
            invalidated_stage_ids=invalidated,
        )

    def apply_workflow_invalidation(
        self,
        projection: StageGraphAcceptedProjection,
        proposal: WorkflowInvalidationProposal,
        *,
        next_run_version: int,
        next_family_version: int,
    ) -> StageGraphAcceptedProjection:
        """Apply one accepted workflow-cycle decision without overwriting prior lineage."""
        if proposal.next_workflow_cycle_ordinal != projection.workflow_cycle_ordinal + 1:
            raise StageGraphExecutionError("workflow invalidation cycle is not the next ordinal")
        invalidated = frozenset(proposal.invalidated_stage_ids)
        if not invalidated or not invalidated <= self.stages.keys():
            raise StageGraphExecutionError("workflow invalidation names an unknown stage")
        stages = dict(projection.stages)
        for key, instance in tuple(stages.items()):
            if instance.candidate.stage_id not in invalidated:
                continue
            stages[key] = replace(instance, status="invalidated")
        for stage_id in sorted(invalidated, key=lambda item: item.encode("utf-8")):
            stage = self.stages[stage_id]
            status: StageStatus = "ready" if not self.stage_joins[stage_id] else "blocked"
            for slot in stage.operation_slots:
                candidate = StageCandidateIdentity(
                    stage_id=stage_id,
                    mapped_instance_presence=0,
                    mapped_instance_id="NO_MAPPED_INSTANCE",
                    workflow_cycle_ordinal=proposal.next_workflow_cycle_ordinal,
                    stage_cycle_ordinal=0,
                    operation_slot_id=slot.operation_slot_id,
                )
                stages[candidate.semantic_prefix] = StageInstanceProjection(
                    candidate=candidate,
                    status=status,
                    objective_override=(
                        proposal.next_objective
                        if stage_id in proposal.invalidation_frontier
                        else None
                    ),
                )
        dependencies = dict(projection.dependencies)
        for edge in self.blueprint.dependencies:
            if edge.producer_stage_id not in invalidated:
                continue
            prior = dependencies[edge.dependency_id]
            dependencies[edge.dependency_id] = DependencyProjection(
                dependency_id=edge.dependency_id,
                generation=prior.generation + 1,
                disposition=DependencyDisposition.UNRESOLVED,
                supersedes_generation=prior.generation,
            )
        return replace(
            projection,
            family_version=next_family_version,
            run_version=next_run_version,
            workflow_cycle_ordinal=proposal.next_workflow_cycle_ordinal,
            stages=stages,
            dependencies=dependencies,
            invalidated_stage_ids=invalidated,
        )

    def late_result_decision(
        self,
        identity: StageExecutionIdentity,
        edge: StageDependency,
        facts: LateResultFacts,
        *,
        slow_sibling_route: str,
    ) -> ResultDispositionProposal:
        vetoes = (
            (
                facts.run_terminal or facts.terminalization_started,
                "run_terminal_or_terminalization_started",
                ResultDecision.QUARANTINE,
            ),
            (
                facts.generation_superseded or facts.producer_invalidated or facts.evidence_invalid,
                "generation_or_evidence_invalid",
                ResultDecision.QUARANTINE,
            ),
            (facts.run_cancelling, "run_cancelling", ResultDecision.QUARANTINE),
            (
                facts.dependency_terminally_disposed,
                "dependency_terminally_disposed",
                ResultDecision.REJECT,
            ),
        )
        for matched, reason, decision in vetoes:
            if matched:
                return ResultDispositionProposal(
                    identity=identity,
                    decision=decision,
                    dependency_dispositions={edge.dependency_id: self._negative_disposition(edge)},
                    matched_veto=reason,
                    quarantine_reason=reason if decision == ResultDecision.QUARANTINE else None,
                )
        if facts.consumer_already_admitted and slow_sibling_route == "quarantine":
            return ResultDispositionProposal(
                identity=identity,
                decision=ResultDecision.QUARANTINE,
                dependency_dispositions={edge.dependency_id: self._negative_disposition(edge)},
                quarantine_reason="slow_sibling_route",
            )
        if facts.consumer_already_admitted:
            rule = next(
                item
                for item in self.blueprint.late_result_policy.rules
                if item.trigger == "consumer_already_admitted"
            )
            decision = ResultDecision(rule.decision)
            return ResultDispositionProposal(
                identity=identity,
                decision=decision,
                dependency_dispositions={
                    edge.dependency_id: (
                        DependencyDisposition.FULFILLED
                        if decision == ResultDecision.ADMIT
                        else self._negative_disposition(edge)
                    )
                },
                matched_rule_id=rule.rule_id,
                quarantine_reason=(rule.rule_id if decision == ResultDecision.QUARANTINE else None),
            )
        return ResultDispositionProposal(
            identity=identity,
            decision=ResultDecision.ADMIT,
            dependency_dispositions={edge.dependency_id: DependencyDisposition.FULFILLED},
        )

    def output_slot_refs(
        self, stage_id: str, slot_id: str, result: dict[str, Any]
    ) -> tuple[str, ...]:
        bindings = result.get("output_bindings")
        if isinstance(bindings, dict):
            values = bindings.get(slot_id, ())
        elif len(self.stages[stage_id].output_slots) == 1 or all(
            slot.required is None for slot in self.stages[stage_id].output_slots
        ):
            values = result.get("output_refs", ())
        else:
            values = ()
        return tuple(values) if isinstance(values, list | tuple) else ()

    def result_validation_errors(
        self, identity: StageExecutionIdentity, result: dict[str, Any]
    ) -> tuple[str, ...]:
        """Validate declared result shape and ownership, never infer semantic acceptance.

        Schema refs identify contracts; this check does not claim to validate artifact bytes.
        Named bindings are necessary when more than one output slot is declared.
        """
        stage = self.stages[identity.candidate.stage_id]
        errors: list[str] = []
        for field in ("output_refs", "obligation_refs"):
            values = result.get(field, ())
            if not isinstance(values, list | tuple) or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                errors.append(f"invalid_{field}")
        if errors:
            return tuple(errors)
        allowed_obligations = {
            row.evidence_slot_id
            for row in self.blueprint.obligation_matrix
            if row.obligation_scope == "workflow" or row.owner_stage_id == stage.stage_id
        }
        if not set(result.get("obligation_refs", ())) <= allowed_obligations:
            errors.append("undeclared_obligation_claim")
        binding_errors = output_binding_errors(
            result, {slot.output_slot_id for slot in stage.output_slots}
        )
        if binding_errors:
            return (*errors, *binding_errors)
        for slot in stage.output_slots:
            if slot.required and not self.output_slot_refs(
                stage.stage_id, slot.output_slot_id, result
            ):
                errors.append(f"outputs_missing:{slot.output_slot_id}")
        return tuple(errors)

    def result_decision(
        self,
        identity: StageExecutionIdentity,
        facts: LateResultFacts,
        *,
        operation_disposition: str = "completed",
        operation_result: dict[str, Any] | None = None,
        completion_valid: bool = True,
    ) -> ResultDispositionProposal:
        edges = self._producer_edges(identity.candidate.stage_id)
        # These checks apply to every producer, including a terminal/one-stage graph.
        # A leaf has no dependency edges, but still has execution and acceptance policy.
        veto = (
            "run_terminal_or_terminalization_started"
            if facts.run_terminal or facts.terminalization_started
            else "generation_or_evidence_invalid"
            if facts.generation_superseded or facts.producer_invalidated or facts.evidence_invalid
            else "run_cancelling"
            if facts.run_cancelling
            else None
        )
        validation = (
            self.result_validation_errors(identity, operation_result)
            if operation_result is not None
            else ()
        )
        missing_dependency = operation_result is not None and any(
            edge.dependency_class == DependencyClass.REQUIRED
            and not edge.ordering_only
            and not self.output_slot_refs(
                identity.candidate.stage_id, edge.producer_output_slot_id, operation_result
            )
            for edge in edges
        )
        failure = (
            f"operation_{operation_disposition}"
            if operation_disposition != "completed"
            else "completion_validation_failed"
            if not completion_valid
            else "completion_requirement_failed"
            if validation
            else "required_dependency_output_missing"
            if missing_dependency
            else None
        )
        if veto or failure:
            return ResultDispositionProposal(
                identity=identity,
                decision=ResultDecision.QUARANTINE if veto else ResultDecision.REJECT,
                dependency_dispositions={
                    edge.dependency_id: self._negative_disposition(
                        edge, cancelled=operation_disposition == "cancelled"
                    )
                    for edge in edges
                },
                matched_veto=veto or failure,
                quarantine_reason=veto,
            )
        if not edges:
            return ResultDispositionProposal(
                identity=identity,
                decision=ResultDecision.ADMIT,
                dependency_dispositions={},
            )
        decisions = [
            self.late_result_decision(
                identity,
                edge,
                facts,
                slow_sibling_route=self._slow_sibling_route(edge),
            )
            for edge in edges
        ]
        precedence = {
            ResultDecision.ADMIT: 0,
            ResultDecision.REJECT: 1,
            ResultDecision.QUARANTINE: 2,
        }
        first = max(decisions, key=lambda item: precedence[item.decision])
        final_dispositions = {
            edge.dependency_id: (
                decision.dependency_dispositions[edge.dependency_id]
                if first.decision == ResultDecision.ADMIT
                and (
                    operation_result is None
                    or edge.ordering_only
                    or self.output_slot_refs(
                        identity.candidate.stage_id, edge.producer_output_slot_id, operation_result
                    )
                )
                else self._negative_disposition(
                    edge,
                    cancelled=operation_disposition == "cancelled",
                )
            )
            for edge, decision in zip(edges, decisions, strict=True)
        }
        return ResultDispositionProposal(
            identity=identity,
            decision=first.decision,
            dependency_dispositions=final_dispositions,
            matched_veto=first.matched_veto,
            matched_rule_id=first.matched_rule_id,
            quarantine_reason=first.quarantine_reason,
        )

    def completion(
        self,
        projection: StageGraphAcceptedProjection,
    ) -> StageGraphCompletionProposal:
        required_obligations = {
            item.evidence_slot_id for item in self.blueprint.obligation_matrix if item.required
        }
        view = self.route_view(projection) if self.graph_routes else GraphRouteView()
        revisits = self.revisit_view(projection)
        # A region that will run again, or whose stop fact can never be known, holds completion.
        held_regions = tuple(
            f"revisit:{item.region_id}"
            for item in revisits
            if item.disposition in {"revisit", "exhausted"}
        )
        # OVE-171: a dependency into or out of a stage no route selected never resolves; it
        # is not pending (the stage is skipped, visibly, in `route_skipped_stage_ids`).
        pending_dependencies = held_regions + tuple(
            sorted(
                (
                    dependency_id
                    for dependency_id, item in projection.dependencies.items()
                    if item.disposition == DependencyDisposition.UNRESOLVED
                    and self.dependencies[dependency_id].dependency_class
                    != DependencyClass.ADVISORY
                    and self.dependencies[dependency_id].producer_stage_id not in view.skipped
                    and self.dependencies[dependency_id].consumer_stage_id not in view.skipped
                ),
                key=lambda item: item.encode("utf-8"),
            )
        )
        open_liabilities = tuple(
            sorted(
                (
                    liability_id
                    for liability_id, item in projection.producer_liabilities.items()
                    if not item.closed
                ),
                key=lambda item: item.encode("utf-8"),
            )
        )
        outputs = tuple(
            sorted(
                {
                    output_ref
                    for instance in projection.stages.values()
                    for output_ref in instance.output_refs
                },
                key=lambda item: item.encode("utf-8"),
            )
        )
        return StageGraphCompletionProposal(
            required_obligations_accepted=(
                required_obligations <= frozenset(projection.accepted_obligation_evidence)
            ),
            pending_dependency_ids=pending_dependencies,
            open_producer_liability_ids=open_liabilities,
            valid_output_refs=outputs,
            route_skipped_stage_ids=tuple(
                sorted(view.skipped, key=lambda item: item.encode("utf-8"))
            ),
            route_decisions=view.decisions,
            revisit_decisions=revisits,
        )

    def failure_completion(
        self,
        projection: StageGraphAcceptedProjection,
    ) -> StageGraphCompletionProposal | None:
        """MP-20: the graph concluded without acceptance, or ``None`` (a stalemate).

        01-STAGE_GRAPH §6-7: a failed required stage does not by itself fail the graph;
        dependent stages become skipped only when their release is conclusively impossible,
        and the graph's execution completes when every reachable required stage is terminal.
        This is that conclusion when a stage failed (a denied Human Gate is a failed gate
        stage: SPEC-03 "Reject closes the gate as not accepted"): nothing is admitted or
        running, no producer liability is open, every stage still waiting for release has a
        join that can no longer be satisfied (directly, or because its producer is itself
        unreleasable), and no dependency between reachable stages is unresolved. Anything
        else (a dependency that may still resolve, an optional input from an unreleasable
        producer, no failed stage at all) is not concluded: the caller keeps the stalemate.
        """

        stages = projection.stages.values()
        if any(item.status in {"reserved", "running", "waiting", "paused"} for item in stages):
            return None
        if not any(item.status == "failed" for item in stages):
            return self._governed_revisit_conclusion(projection)
        waiting = [item for item in stages if item.status in {"blocked", "ready"}]
        skipped: set[str] = set(self.route_view(projection).skipped) if self.graph_routes else set()
        changed = True
        while changed:
            changed = False
            for instance in waiting:
                stage_id = instance.candidate.stage_id
                if stage_id in skipped:
                    continue
                if any(
                    self._conclusively_impossible(join, projection, skipped)
                    for join in self.stage_joins[stage_id]
                ):
                    skipped.add(stage_id)
                    changed = True
        if any(item.candidate.stage_id not in skipped for item in waiting):
            return None
        pending = [
            dependency_id
            for dependency_id, item in projection.dependencies.items()
            if item.disposition == DependencyDisposition.UNRESOLVED
            and self.dependencies[dependency_id].dependency_class != DependencyClass.ADVISORY
            and self.dependencies[dependency_id].producer_stage_id not in skipped
            and self.dependencies[dependency_id].consumer_stage_id not in skipped
        ]
        completion = self.completion(projection)
        if pending or completion.open_producer_liability_ids:
            return None
        return replace(
            completion,
            pending_dependency_ids=(),
            failed=True,
            skipped_stage_ids=tuple(sorted(skipped, key=lambda item: item.encode("utf-8"))),
        )

    def _conclusively_impossible(
        self,
        join: StageJoin,
        projection: StageGraphAcceptedProjection,
        skipped: set[str],
    ) -> bool:
        """A join that can never be satisfied, counting a dependency whose producer stage is
        skipped as never resolving. An optional dependency of a skipped producer would be
        omitted (and so satisfy its join), which this conclusion does not record: such a join
        is never treated as impossible."""

        if self.graph_routes:
            outcome = self._join_outcome(join, projection, frozenset(skipped))
            return outcome[0] == JoinDisposition.IMPOSSIBLE
        satisfied = 0
        unresolved = 0
        non_advisory = [
            self.dependencies[item]
            for item in join.dependency_ids
            if self.dependencies[item].dependency_class != DependencyClass.ADVISORY
        ]
        for edge in non_advisory:
            disposition = projection.dependencies[edge.dependency_id].disposition
            if disposition == DependencyDisposition.UNRESOLVED:
                if edge.producer_stage_id not in skipped:
                    unresolved += 1
                elif edge.dependency_class == DependencyClass.OPTIONAL:
                    return False
            elif self.dependency_satisfies(edge.dependency_class, disposition):
                satisfied += 1
        count = len(non_advisory)
        if join.kind == JoinKind.ALL:
            return satisfied + unresolved < count
        if join.kind == JoinKind.ANY:
            return satisfied == 0 and unresolved == 0
        minimum = join.minimum
        if minimum is None:
            raise StageGraphExecutionError("minimum join is missing its frozen threshold")
        return satisfied < minimum and satisfied + unresolved < minimum

    def _select_next_candidate(
        self,
        candidates_by_group: dict[str, list[tuple[CandidateOrderingKey, StageInstanceProjection]]],
        fairness: FairnessCursorState,
        blocked_candidate_keys: frozenset[str],
        remaining_concurrency: int,
    ) -> (
        tuple[
            int,
            str,
            CandidateOrderingKey,
            StageInstanceProjection,
            StageOperationSlot,
        ]
        | None
    ):
        for offset in range(len(self.group_ring)):
            ring_index = (fairness.group_ring_cursor + offset) % len(self.group_ring)
            group_id = self.group_ring[ring_index]
            candidates = candidates_by_group.get(group_id, ())
            if not candidates:
                continue
            cursor = fairness.candidate_cursors.get(group_id)
            cursor_tuple = cursor.as_tuple() if cursor is not None else None
            after = [
                item
                for item in candidates
                if cursor_tuple is None or item[0].as_tuple() > cursor_tuple
            ]
            ordered = [*after, *(item for item in candidates if item not in after)]
            for key, instance in ordered:
                stage = self.stages[instance.candidate.stage_id]
                slot = next(
                    item
                    for item in stage.operation_slots
                    if item.operation_slot_id == instance.candidate.operation_slot_id
                )
                if instance.candidate.semantic_prefix in blocked_candidate_keys or (
                    instance.candidate.stage_id not in self.control_gate_keys
                    and slot.concurrency_slots > remaining_concurrency
                ):
                    continue
                return ring_index, group_id, key, instance, slot
        return None

    def _weighted_group_ring(self) -> tuple[str, ...]:
        groups = sorted(
            self.blueprint.fairness_groups,
            key=lambda item: item.group_id.encode("utf-8"),
        )
        ring = tuple(
            group.group_id
            for round_number in range(1, max(item.weight for item in groups) + 1)
            for group in groups
            if group.weight >= round_number
        )
        if not ring:
            raise StageGraphExecutionError("weighted fairness ring cannot be empty")
        return ring

    def _input_refs(
        self,
        stage_id: str,
        projection: StageGraphAcceptedProjection,
        view: GraphRouteView | None = None,
    ) -> tuple[str, ...]:
        selection = self._edge_selection(stage_id, projection, view)
        refs = {
            evidence_ref
            for edge in self.blueprint.dependencies
            if edge.consumer_stage_id == stage_id
            and not edge.ordering_only
            and selection.get(edge.dependency_id, "selected") == "selected"
            for evidence_ref in projection.dependencies[edge.dependency_id].evidence_refs
        }
        return tuple(sorted(refs, key=lambda item: item.encode("utf-8")))

    def _input_bindings(
        self,
        stage_id: str,
        projection: StageGraphAcceptedProjection,
        view: GraphRouteView | None = None,
    ) -> tuple[StageInputBinding, ...]:
        """FT-B2: keep each dependency's `producer_output_slot -> consumer_input_slot` mapping.

        Ordered like the blueprint's dependency declarations (then by ref), so the consumer's
        bindings arrive in declaration order. A ref carries the producer's accepted result
        decision when the producer's admitted result is on the projection; otherwise it is
        unaccepted and the Context Packer omits it (`not_accepted`).
        """

        bindings: list[StageInputBinding] = []
        seen: set[tuple[str, str]] = set()
        selection = self._edge_selection(stage_id, projection, view)
        for edge in self.blueprint.dependencies:
            if edge.consumer_stage_id != stage_id or edge.ordering_only:
                continue
            if selection.get(edge.dependency_id, "selected") != "selected":
                # OVE-171: a surplus or omitted producer is never a sealed input.
                continue
            dependency = projection.dependencies[edge.dependency_id]
            accepted = self._accepted_decision_ref(edge.producer_stage_id, projection)
            for ref in sorted(dependency.evidence_refs, key=lambda item: item.encode("utf-8")):
                key = (edge.consumer_input_slot_id, ref)
                if key in seen:
                    continue
                seen.add(key)
                bindings.append(
                    StageInputBinding(
                        consumer_input_slot_id=edge.consumer_input_slot_id,
                        producer_stage_key=edge.producer_stage_id,
                        producer_output_slot_id=edge.producer_output_slot_id,
                        artifact_ref=ref,
                        accepted_decision_ref=(
                            accepted
                            if dependency.disposition
                            in {DependencyDisposition.FULFILLED, DependencyDisposition.DEGRADED}
                            else None
                        ),
                        provisional=False,
                    )
                )
        return tuple(bindings)

    @staticmethod
    def _latest_accepted(
        producer_stage_id: str, projection: StageGraphAcceptedProjection
    ) -> AcceptedResultFact | None:
        accepted = [
            fact
            for fact in projection.accepted_results
            if fact.identity.candidate.stage_id == producer_stage_id
        ]
        if not accepted:
            return None
        return max(accepted, key=lambda fact: fact.accepted_at_order)

    @classmethod
    def _accepted_decision_ref(
        cls, producer_stage_id: str, projection: StageGraphAcceptedProjection
    ) -> str | None:
        latest = cls._latest_accepted(producer_stage_id, projection)
        if latest is None:
            return None
        return f"stage-result:{latest.identity.semantic_key}:admit"

    def _released_by(
        self,
        stage_id: str,
        projection: StageGraphAcceptedProjection,
        view: GraphRouteView | None = None,
    ) -> tuple[StageReleasedBy, ...]:
        """1.4.4 (P3.8): one entry per dependency of the released stage, in blueprint
        order, naming the producer attempt whose accepted result fulfilled it. The unit
        key is left for the admitting service (it needs the request scope). OVE-171: under
        the graph routes semantics each entry records its frozen `selection`."""

        released: list[StageReleasedBy] = []
        selection = self._edge_selection(stage_id, projection, view)
        for edge in self.blueprint.dependencies:
            if edge.consumer_stage_id != stage_id:
                continue
            dependency = projection.dependencies[edge.dependency_id]
            latest = self._latest_accepted(edge.producer_stage_id, projection)
            chosen = selection.get(edge.dependency_id)
            fulfilled = (
                latest is not None
                and chosen in {None, "selected"}
                and dependency.disposition
                in {DependencyDisposition.FULFILLED, DependencyDisposition.DEGRADED}
            )
            released.append(
                StageReleasedBy(
                    dependency_id=edge.dependency_id,
                    join_id=edge.join_id,
                    producer_stage_id=edge.producer_stage_id,
                    producer_output_slot_id=edge.producer_output_slot_id,
                    producer_identity=latest.identity if fulfilled and latest else None,
                    accepted_decision_ref=(
                        f"stage-result:{latest.identity.semantic_key}:admit"
                        if fulfilled and latest
                        else None
                    ),
                    selection=chosen,
                )
            )
        return tuple(released)

    @staticmethod
    def _continues_from(
        instance: StageInstanceProjection, projection: StageGraphAcceptedProjection
    ) -> StageContinuesFrom | None:
        """1.4.4 (P3.8): the latest earlier-cycle attempt of the same stage slot, when a
        stage or workflow cycle re-admits it (its result refs are the cycle proposal's
        `prior_result_refs`). None for a first-cycle candidate."""

        candidate = instance.candidate
        ordinal = (candidate.workflow_cycle_ordinal, candidate.stage_cycle_ordinal)
        priors = [
            item
            for item in projection.stages.values()
            if item.candidate.stage_id == candidate.stage_id
            and item.candidate.mapped_instance_id == candidate.mapped_instance_id
            and item.candidate.operation_slot_id == candidate.operation_slot_id
            and item.semantic_attempt > 0
            and (item.candidate.workflow_cycle_ordinal, item.candidate.stage_cycle_ordinal)
            < ordinal
        ]
        if not priors:
            return None
        prior = max(
            priors,
            key=lambda item: (
                item.candidate.workflow_cycle_ordinal,
                item.candidate.stage_cycle_ordinal,
            ),
        )
        return StageContinuesFrom(
            prior_identity=StageExecutionIdentity(
                run_id=projection.identity.run_id,
                execution_epoch=projection.identity.execution_epoch,
                candidate=prior.candidate,
                semantic_attempt=prior.semantic_attempt,
            ),
            prior_result_refs=prior.output_refs,
        )

    # --- OVE-171: routes, named release groups and visible optional omission -------------

    def route_view(self, projection: StageGraphAcceptedProjection) -> GraphRouteView:
        """Every route's decision over the projection's pinned facts, each target's gate and
        the derived skipped set (not-selected targets plus their conclusively unreleasable
        required dependents). Pure and deterministic; legacy blueprints have no routes."""

        if not self.graph_routes:
            return GraphRouteView()
        decisions = self._route_decisions(projection, frozenset())
        gates = self._gates(decisions)
        skipped = self._skip_closure(
            projection, frozenset(stage for stage, gate in gates.items() if gate == "not_selected")
        )
        if skipped:
            # A fact source that was skipped can never decide: its unknowns are final.
            decisions = self._route_decisions(projection, skipped)
            gates = self._gates(decisions)
        return GraphRouteView(decisions=decisions, gates=gates, skipped=skipped)

    def _route_decisions(
        self, projection: StageGraphAcceptedProjection, skipped: frozenset[str]
    ) -> tuple[RouteDecision, ...]:
        def observe(stage_id: str, fact_id: str) -> FactObservation:
            return self._observe(stage_id, fact_id, projection, skipped)

        return tuple(evaluate_route(route, observe) for route in self.blueprint.routes)

    def _gates(self, decisions: tuple[RouteDecision, ...]) -> dict[str, RouteBranchDisposition]:
        gates: dict[str, RouteBranchDisposition] = {}
        for route, decision in zip(self.blueprint.routes, decisions, strict=True):
            gates.update(target_gates(route, decision))
        return gates

    def _observe(
        self,
        stage_id: str,
        fact_id: str,
        projection: StageGraphAcceptedProjection,
        skipped: frozenset[str],
    ) -> FactObservation:
        fact = self.stage_facts[(stage_id, fact_id)]
        instance = self._current_instance(stage_id, projection)
        if instance is not None and instance.status in {"completed", "degraded"}:
            accepted = [
                item
                for item in projection.accepted_results
                if item.identity.candidate == instance.candidate
            ]
            latest = max(accepted, key=lambda item: item.accepted_at_order, default=None)
            return fact_from_result(
                stage_id,
                fact,
                latest.operation_result if latest is not None else None,
                final=True,
            )
        final = stage_id in skipped or (
            instance is not None and instance.status in _TERMINAL_NEGATIVE
        )
        return FactObservation(
            stage_id,
            fact_id,
            False,
            reason="source_not_accepted" if final else "source_pending",
            final=final,
        )

    @staticmethod
    def _current_instance(
        stage_id: str, projection: StageGraphAcceptedProjection
    ) -> StageInstanceProjection | None:
        instances = [
            item for item in projection.stages.values() if item.candidate.stage_id == stage_id
        ]
        if not instances:
            return None

        def position(item: StageInstanceProjection) -> tuple[int, int, bytes]:
            return (
                item.candidate.workflow_cycle_ordinal,
                item.candidate.stage_cycle_ordinal,
                item.candidate.operation_slot_id.encode("utf-8"),
            )

        return max(instances, key=position)

    def _skip_closure(
        self, projection: StageGraphAcceptedProjection, seed: frozenset[str]
    ) -> frozenset[str]:
        skipped = set(seed)
        changed = True
        while changed:
            changed = False
            for stage_id in self.stages:
                if stage_id in skipped:
                    continue
                instance = self._current_instance(stage_id, projection)
                if instance is None or instance.status not in {"blocked", "ready"}:
                    continue
                frozen = frozenset(skipped)
                if any(
                    self._join_outcome(join, projection, frozen)[0] == JoinDisposition.IMPOSSIBLE
                    for join in self.stage_joins[stage_id]
                ):
                    skipped.add(stage_id)
                    changed = True
        return frozenset(skipped)

    def _route_released(self, stage_id: str, view: GraphRouteView) -> bool:
        if stage_id in view.skipped:
            return False
        return stage_id not in self.route_by_target or view.gate(stage_id) == "selected"

    def _route_decisions_for(
        self, stage_id: str, view: GraphRouteView | None
    ) -> tuple[RouteDecision, ...]:
        route = self.route_by_target.get(stage_id)
        if view is None or route is None:
            return ()
        return tuple(item for item in view.decisions if item.route_id == route.route_id)

    def _edge_state(
        self,
        edge: StageDependency,
        projection: StageGraphAcceptedProjection,
        skipped: frozenset[str],
        *,
        omit_optional: bool,
    ) -> EdgeState:
        """One dependency under the graph routes semantics. An optional input still pending
        (or from a skipped producer) never blocks an ALL join: it is omitted visibly at release
        (OC-D141). A required input from a skipped producer can never resolve."""

        if edge.dependency_class == DependencyClass.ADVISORY:
            return "ignored"
        disposition = projection.dependencies[edge.dependency_id].disposition
        optional = edge.dependency_class == DependencyClass.OPTIONAL
        if disposition == DependencyDisposition.UNRESOLVED:
            if edge.producer_stage_id in skipped:
                return "ignored" if optional else "failed"
            return "ignored" if optional and omit_optional else "pending"
        if optional:
            # Only an accepted optional output is an input; an omitted or failed one is absent.
            return (
                "satisfied"
                if disposition in {DependencyDisposition.FULFILLED, DependencyDisposition.DEGRADED}
                else "ignored"
            )
        return (
            "satisfied"
            if self.dependency_satisfies(edge.dependency_class, disposition)
            else "failed"
        )

    def _join_outcome(
        self,
        join: StageJoin,
        projection: StageGraphAcceptedProjection,
        skipped: frozenset[str],
    ) -> tuple[JoinDisposition, dict[str, EdgeSelection]]:
        """A join's disposition and each edge's selection under the graph routes semantics."""

        edges = [self.dependencies[item] for item in join.dependency_ids]
        group = join.group
        if group is not None:
            members: list[MemberState] = []
            for position, producer in enumerate(group.member_stage_ids):
                states = {
                    self._edge_state(edge, projection, skipped, omit_optional=False)
                    for edge in edges
                    if edge.producer_stage_id == producer
                }
                latest = self._latest_accepted(producer, projection)
                members.append(
                    MemberState(
                        stage_id=producer,
                        state="failed"
                        if "failed" in states
                        else "satisfied"
                        if states <= {"satisfied", "ignored"}
                        else "pending",
                        accepted_order=latest.accepted_at_order if latest is not None else 0,
                        position=position,
                    )
                )
            outcome = group_outcome(group, join.kind, join.minimum, members)
            chosen = set(outcome.selected)
            failed = {item.stage_id for item in members if item.state == "failed"}
            group_selection: dict[str, EdgeSelection] = {
                edge.dependency_id: "selected"
                if edge.producer_stage_id in chosen
                else "unavailable"
                if edge.producer_stage_id in failed
                else "surplus"
                for edge in edges
            }
            return outcome.disposition, group_selection
        omit = join.kind == JoinKind.ALL
        edge_states = {
            edge.dependency_id: self._edge_state(edge, projection, skipped, omit_optional=omit)
            for edge in edges
        }
        selection: dict[str, EdgeSelection] = {
            dependency_id: "selected"
            if state == "satisfied"
            else "omitted"
            if state == "ignored"
            else "unavailable"
            if state == "failed"
            else "surplus"
            for dependency_id, state in edge_states.items()
            if self.dependencies[dependency_id].dependency_class != DependencyClass.ADVISORY
        }
        counted = [state for state in edge_states.values() if state != "ignored"]
        satisfied = counted.count("satisfied")
        pending = counted.count("pending")
        if join.kind == JoinKind.ALL:
            if "failed" in counted:
                return JoinDisposition.IMPOSSIBLE, selection
            return (
                JoinDisposition.SATISFIED if satisfied == len(counted) else JoinDisposition.PENDING
            ), selection
        threshold = 1 if join.kind == JoinKind.ANY else join.minimum
        if threshold is None:
            raise StageGraphExecutionError("minimum join is missing its frozen threshold")
        if satisfied >= threshold:
            return JoinDisposition.SATISFIED, selection
        if satisfied + pending < threshold:
            return JoinDisposition.IMPOSSIBLE, selection
        return JoinDisposition.PENDING, selection

    def _edge_selection(
        self,
        stage_id: str,
        projection: StageGraphAcceptedProjection,
        view: GraphRouteView | None,
    ) -> dict[str, EdgeSelection]:
        """Each dependency's frozen selection at release (graph routes semantics only)."""

        if not self.graph_routes:
            return {}
        skipped = (view or self.route_view(projection)).skipped
        selection: dict[str, EdgeSelection] = {}
        for join in self.stage_joins[stage_id]:
            selection.update(self._join_outcome(join, projection, skipped)[1])
        return selection

    # --- OVE-171 slice D: bounded Revisit Regions ----------------------------------------

    def revisit_view(self, projection: StageGraphAcceptedProjection) -> tuple[RevisitDecision, ...]:
        """The region's governed decision at its current visit (empty without a region)."""

        region = self.region
        if region is None:
            return ()
        visit = projection.workflow_cycle_ordinal + 1

        def decision(disposition: str, reason: str, **fields: Any) -> RevisitDecision:
            return RevisitDecision(
                region_id=region.region_id,
                visit=visit,
                max_visits=region.max_visits,
                disposition=disposition,  # type: ignore[arg-type]
                reason=reason,
                **fields,
            )

        instances = [self._current_instance(stage, projection) for stage in region.stage_ids]
        exit_instance = self._current_instance(region.exit_stage_id, projection)
        if exit_instance is None or exit_instance.status in _TERMINAL_NEGATIVE:
            return (decision("failed", "the exit stage ended without acceptance"),)
        if exit_instance.status not in {"completed", "degraded"} or any(
            item is not None and item.status not in {"completed", "degraded"} for item in instances
        ):
            return (decision("pending", "the visit is still running"),)
        progress = self._progress_history(projection)
        evidence: list[str] = []
        if region.until:
            outcomes: list[bool | None] = []
            for predicate in region.until:
                observation = self._observe(
                    predicate.stage_id, predicate.fact_id, projection, frozenset()
                )
                if observation.evidence_ref:
                    evidence.append(observation.evidence_ref)
                outcomes.append(evaluate_predicate(predicate, observation))
            if any(item is False for item in outcomes):
                pass  # the stop rule does not hold: revisit, unless a governor ends it
            elif all(item is True for item in outcomes):
                return (
                    decision(
                        "exit",
                        "the stop rule holds",
                        evidence_refs=tuple(evidence),
                        progress=progress,
                    ),
                )
            else:
                return (
                    decision(
                        "exhausted",
                        "a stop fact of the accepted visit is unknown",
                        evidence_refs=tuple(evidence),
                        progress=progress,
                    ),
                )
        else:
            owed = {
                row.evidence_slot_id
                for row in self.blueprint.obligation_matrix
                if row.required and row.owner_stage_id in region.stage_ids
            }
            if owed <= frozenset(projection.accepted_obligation_evidence):
                return (
                    decision(
                        "exit",
                        "every required obligation of the region is fulfilled",
                        progress=progress,
                    ),
                )
        if region.patience is not None and len(progress) > region.patience:
            earlier = [item for item in progress[: -region.patience] if item is not None]
            recent = [item for item in progress[-region.patience :] if item is not None]
            if not recent or (earlier and max(recent) <= max(earlier)):
                return (
                    decision(
                        "no_progress",
                        f"no progress over {region.patience} visits",
                        evidence_refs=tuple(evidence),
                        progress=progress,
                    ),
                )
        if visit >= region.max_visits:
            return (
                decision(
                    "cap_exhausted",
                    f"the visit cap {region.max_visits} is reached without the stop rule",
                    evidence_refs=tuple(evidence),
                    progress=progress,
                ),
            )
        return (
            decision(
                "revisit",
                "the stop rule does not hold",
                evidence_refs=tuple(evidence),
                progress=progress,
            ),
        )

    def current_instance(
        self, stage_id: str, projection: StageGraphAcceptedProjection
    ) -> StageInstanceProjection | None:
        """The stage's instance at its latest workflow/stage cycle."""

        return self._current_instance(stage_id, projection)

    def _governed_revisit_conclusion(
        self, projection: StageGraphAcceptedProjection
    ) -> StageGraphCompletionProposal | None:
        """A region that ended at its cap or without progress is a governed terminal outcome,
        never success: once everything releasable has run and a required obligation is still
        unmet, the graph concludes failed with the typed unmet reason that cites the governor."""

        governed = [
            item
            for item in self.revisit_view(projection)
            if item.disposition in {"cap_exhausted", "no_progress"}
        ]
        if not governed:
            return None
        completion = self.completion(projection)
        if (
            completion.required_obligations_accepted
            or completion.pending_dependency_ids
            or completion.open_producer_liability_ids
        ):
            return None
        skipped = self.route_view(projection).skipped if self.graph_routes else frozenset()
        if any(
            item.status in {"blocked", "ready"} and item.candidate.stage_id not in skipped
            for item in projection.stages.values()
        ):
            return None
        return replace(
            completion,
            failed=True,
            unmet_reasons=tuple(
                f"revisit-{item.disposition.replace('_', '-')}:{item.region_id}:"
                f"visit-{item.visit}-of-{item.max_visits}"
                for item in governed
            ),
        )

    def revisit_due(self, projection: StageGraphAcceptedProjection) -> RevisitDecision | None:
        due = [item for item in self.revisit_view(projection) if item.disposition == "revisit"]
        return due[0] if due else None

    def revisit_invalidation(
        self, projection: StageGraphAcceptedProjection, *, region_id: str, next_objective: str
    ) -> WorkflowInvalidationProposal:
        """The next visit of a due region: its stages re-run at the next workflow cycle; every
        other accepted output (upstream, independent branches) is reused, never re-run."""

        region = self.region
        due = self.revisit_due(projection)
        if region is None or due is None or due.region_id != region_id:
            raise StageGraphExecutionError("no revisit of this region is due")
        if not next_objective:
            raise StageGraphExecutionError("a revisit requires its objective")
        invalidated = frozenset(region.stage_ids)
        reused = {
            instance.candidate.semantic_prefix: instance.output_refs
            for instance in projection.stages.values()
            if instance.candidate.stage_id not in invalidated and instance.output_refs
        }
        return WorkflowInvalidationProposal(
            next_workflow_cycle_ordinal=projection.workflow_cycle_ordinal + 1,
            invalidation_frontier=(region.entry_stage_id,),
            invalidated_stage_ids=tuple(sorted(invalidated, key=lambda item: item.encode())),
            reused_output_refs=reused,
            next_objective=next_objective,
        )

    def exhaustion(self, projection: StageGraphAcceptedProjection) -> tuple[GraphExhaustion, ...]:
        """Routes and regions whose unknown can never resolve (empty for legacy blueprints)."""

        found: list[GraphExhaustion] = []
        if self.graph_routes:
            view = self.route_view(projection)
            for route, decision in zip(self.blueprint.routes, view.decisions, strict=True):
                if not decision.exhausted:
                    continue
                waiting = tuple(
                    sorted(
                        stage
                        for stage in route.target_stage_ids
                        if view.gate(stage) == "waiting" and stage not in view.skipped
                    )
                )
                reasons = sorted(
                    {reason for branch in decision.branches for reason in branch.unknown_reasons}
                )
                found.append(
                    GraphExhaustion(
                        condition_id=f"route-exhausted:{route.route_id}",
                        stage_ids=waiting or tuple(sorted(route.target_stage_ids)),
                        reason="; ".join(reasons)[:1000] or "unknown route evidence",
                    )
                )
        for item in self.revisit_view(projection):
            if item.disposition == "exhausted" and self.region is not None:
                found.append(
                    GraphExhaustion(
                        condition_id=f"revisit-exhausted:{item.region_id}",
                        stage_ids=tuple(sorted(self.region_consumers or self.region.stage_ids)),
                        reason=item.reason,
                    )
                )
        return tuple(found)

    def _region_released(self, stage_id: str, projection: StageGraphAcceptedProjection) -> bool:
        """A consumer of the region waits until its governed outcome is final."""

        if self.region is None or stage_id not in self.region_consumers:
            return True
        return any(
            item.disposition in {"exit", "cap_exhausted", "no_progress"}
            for item in self.revisit_view(projection)
        )

    def _revisit_decisions_for(
        self, instance: StageInstanceProjection, projection: StageGraphAcceptedProjection
    ) -> tuple[RevisitDecision, ...]:
        region = self.region
        if (
            region is None
            or instance.candidate.stage_id != region.entry_stage_id
            or instance.candidate.workflow_cycle_ordinal == 0
        ):
            return ()
        return (
            RevisitDecision(
                region_id=region.region_id,
                visit=instance.candidate.workflow_cycle_ordinal + 1,
                max_visits=region.max_visits,
                disposition="revisit",
                reason=f"visit {instance.candidate.workflow_cycle_ordinal + 1} continues visit "
                f"{instance.candidate.workflow_cycle_ordinal}",
                progress=self._progress_history(projection),
            ),
        )

    def _progress_history(self, projection: StageGraphAcceptedProjection) -> tuple[int | None, ...]:
        region = self.region
        if region is None or region.progress is None:
            return ()
        fact = self.stage_facts[(region.progress.stage_id, region.progress.fact_id)]
        values: list[int | None] = []
        for cycle in range(projection.workflow_cycle_ordinal + 1):
            accepted = [
                item
                for item in projection.accepted_results
                if item.identity.candidate.stage_id == region.progress.stage_id
                and item.identity.candidate.workflow_cycle_ordinal == cycle
            ]
            latest = max(accepted, key=lambda item: item.accepted_at_order, default=None)
            observation = fact_from_result(
                region.progress.stage_id,
                fact,
                latest.operation_result if latest is not None else None,
                final=True,
            )
            values.append(observation.value if observation.known else None)  # type: ignore[arg-type]
        return tuple(values)

    def _carried_bindings(
        self, stage_id: str, projection: StageGraphAcceptedProjection
    ) -> tuple[StageInputBinding, ...]:
        """A region entry's revisit receives the exit outputs of the prior visit exactly (the
        selected prior cycle's accepted attempt; never a sibling or an older attempt)."""

        region = self.region
        if region is None or stage_id != region.entry_stage_id or not region.carry:
            return ()
        cycle = projection.workflow_cycle_ordinal
        if cycle == 0:
            return ()
        prior = [
            item
            for item in projection.accepted_results
            if item.identity.candidate.stage_id == region.exit_stage_id
            and item.identity.candidate.workflow_cycle_ordinal == cycle - 1
        ]
        latest = max(prior, key=lambda item: item.accepted_at_order, default=None)
        if latest is None:
            return ()
        bindings: list[StageInputBinding] = []
        for carried in region.carry:
            for ref in self.output_slot_refs(
                region.exit_stage_id, carried.output_slot_id, latest.operation_result
            ):
                bindings.append(
                    StageInputBinding(
                        consumer_input_slot_id=(
                            f"carry:{region.region_id}:{carried.output_slot_id}"
                        ),
                        producer_stage_key=region.exit_stage_id,
                        producer_output_slot_id=carried.output_slot_id,
                        artifact_ref=ref,
                        accepted_decision_ref=f"stage-result:{latest.identity.semantic_key}:admit",
                    )
                )
        return tuple(bindings)

    def _producer_edges(self, stage_id: str) -> tuple[StageDependency, ...]:
        return tuple(
            item for item in self.blueprint.dependencies if item.producer_stage_id == stage_id
        )

    def _slow_sibling_route(self, edge: StageDependency) -> str:
        return self.joins[(edge.consumer_stage_id, edge.join_id)].slow_sibling_policy.arrival_route

    @staticmethod
    def _negative_disposition(
        edge: StageDependency,
        *,
        cancelled: bool = False,
    ) -> DependencyDisposition:
        if edge.dependency_class == DependencyClass.ADVISORY:
            return DependencyDisposition.UNRESOLVED
        if edge.dependency_class == DependencyClass.OPTIONAL:
            return DependencyDisposition.OMITTED
        if cancelled:
            return DependencyDisposition.CANCELLED
        return DependencyDisposition.FAILED

    @staticmethod
    def _stage_status_for_result(proposal: ResultDispositionProposal) -> StageStatus:
        if proposal.decision == ResultDecision.ADMIT:
            return (
                "degraded"
                if DependencyDisposition.DEGRADED in proposal.dependency_dispositions.values()
                else "completed"
            )
        return "failed"

    def _descendants(self) -> dict[str, frozenset[str]]:
        # 1.4.4 (TR-D12): the one closure rule, shared with the fork's frontier closure.
        return descendants_by_stage(self.blueprint)

"""Safe macro snapshots and semantic forks (REQ-CP-EXEC-012, REQ-CP-EXEC-016).

`RunSnapshotService` builds an immutable `RunSnapshotManifest` only at a declared safe
boundary, from PostgreSQL authority read as one consistent snapshot (`InspectionReadRepository`)
plus the family head, linked runs and async-child dispositions; it never sends a workflow
Query. `SemanticForkService` validates a typed patch against the protected and declared
patchable fields, records the reuse frontier, compiles the derived run's independent admission
(epoch 1, its own budget, unit keys and cognitive namespaces), and runs the audited fork saga
(`RuntimeForkService`) to one durable receipt. `ForkReuseResolver` lets the derived run settle a
reused unit by immutable ref instead of re-running cognition.

These seams are provider-, family-instance- and company-neutral (mission-horizon lens).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.execution.inspection import (
    InspectionReadRepository,
    RunSnapshot,
    UnitRecord,
)
from mission_control.application.execution.run_control_repository import RunControlRepository
from mission_control.application.execution.service import RunControlService, run_identity_for
from mission_control.application.recovery.runtime_lineage import (
    ExecutionLineageRepository,
    PersistedExecutionLineage,
)
from mission_control.application.recovery.runtime_recovery import (
    ForkAdmission,
    ForkAdmissionObservation,
    ForkMaterialization,
    ForkMaterializationObservation,
    RuntimeForkService,
)
from mission_control.contracts.contracts import ContentRef, InlineText
from mission_control.domain.authoring.canonical import sha256_digest, stable_json_dump
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.authoring.errors import ControlPlaneError
from mission_control.domain.context.render import MISSION_FILE_SLOT_NAMES
from mission_control.domain.context.snapshot_evidence import (
    ConversationEvidence,
    LaneSnapshotEvidence,
)
from mission_control.domain.execution.async_subagent_reconciliation import (
    AsyncChildLifecycleSubject,
    classify_async_children_for_fork,
)
from mission_control.domain.execution.cognition_points import CognitionPointRecord
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    OperationExecutionBinding,
    OperationSettlement,
    ReusedResultRef,
)
from mission_control.domain.graph_runtime.definitions import ExecutionLineageEnvelope
from mission_control.domain.graph_runtime.identities import (
    ExecutionEpochKey,
    GoalDirectedUnitLocation,
    StageGraphUnitLocation,
)
from mission_control.domain.graph_runtime.kernel import (
    LineageKind,
    LineageParentEdge,
    ProviderQualifiedLineageRecord,
)
from mission_control.domain.policies.contracts import (
    COMPLETED_RECEIPT_STATES,
    ActorContext,
    BoundaryCommandStatus,
    BudgetEnvelope,
    BudgetLedgerEntry,
    BudgetLedgerKind,
    DecisionStatus,
    ReceiptState,
    RunPhase,
    RunRequest,
)
from mission_control.domain.policies.forks import (
    DERIVED_EXECUTION_EPOCH,
    INVALIDATE_ALL,
    AcceptedEvidenceRef,
    AnyCognitiveSeed,
    AsyncChildDisposition,
    BudgetFrontier,
    EffectFrontierEntry,
    ExcludedUnit,
    FamilyPosition,
    ForkAt,
    ForkFamily,
    ForkLineageManifest,
    ForkPatchChange,
    ForkPatchPolicy,
    ForkRejected,
    ForkReuseDecision,
    ForkStartPosition,
    FrontierPolicy,
    LinkedRunDisposition,
    MessageDelivery,
    ReuseCandidate,
    RunForkPatch,
    RunForkReceipt,
    RunForkRequest,
    RunSnapshotManifest,
    SnapshotBoundaryKind,
    admission_request_ref,
    compute_reuse_decisions,
    default_patch_policy,
    derived_goal_revision_id,
    fork_request_fingerprint,
    lineage_for,
    required_invalidation_frontier,
    snapshot_id_for,
    snapshots_equivalent,
)
from mission_control.domain.policies.inspection import AsyncChildInspection
from mission_control.domain.programs.dependencies import closed_frontier

FORK_PERMISSION = "workflow_run.fork"
SNAPSHOT_PERMISSION = "workflow_run.snapshot"
ADMIT_PERMISSION = "workflow_run.admit"
FORK_LINEAGE_PROVIDER = "belllabs"
FORK_WORKFLOW_IMPLEMENTATION_REF = "belllabs.semantic-fork.v1"
# StageGraph instances holding admitted, in-flight work: budget `reserved`, an operation
# `running`, or admitted work `waiting`/`paused` for a resume (not a settled boundary). A
# `blocked` stage held back by a declared wait has no admitted work and is not active.
ACTIVE_STAGE_STATUSES = frozenset({"reserved", "running", "waiting", "paused"})
FORK_REQUEST_MARKER_PREFIX = "fork-request:"
# FT-F1: every completed outcome (applied, rejected, expired, failed) is settled.
SETTLED_RECEIPT_STATES = COMPLETED_RECEIPT_STATES
SETTLED_STATUSES = frozenset({"completed", "failed", "cancelled", "timed_out"})
MAX_SNAPSHOT_READ_ATTEMPTS = 3

Clock = Callable[[], datetime]


class ForkSnapshotNotFound(LookupError):
    """The run or snapshot does not exist in the caller's scope (indistinguishable)."""


# --- Source authority beyond the inspection snapshot ---------------------------------------


@dataclass(frozen=True)
class FamilyHeadRecord:
    """The last accepted family-admission head of a run (generic family envelope)."""

    family_kind: str
    family_version: int
    mutation_fingerprint: str
    mutation: Mapping[str, Any]


@dataclass(frozen=True)
class LinkedRunRecord:
    link_id: str
    child_run_id: str
    terminal_status: str | None


@dataclass(frozen=True)
class ForkSourceFacts:
    run_version: int
    family_heads: tuple[FamilyHeadRecord, ...] = ()
    linked_runs: tuple[LinkedRunRecord, ...] = ()
    blueprint_digest: str | None = None
    semantic_input_binding_digest: str | None = None


class ForkSourceReader(Protocol):
    async def read_fork_source(self, request_scope: str, run_id: str) -> ForkSourceFacts | None: ...


class AsyncChildForkClassifier(Protocol):
    """Port: classify a run's parent-owned async children at a fork boundary.

    An `active` child makes the snapshot unsafe (`snapshot_not_quiescent`, EXEC-016); the
    child stays parent-owned either way and is never copied. The production classifier is
    `LineageAsyncChildForkClassifier` (RRM-013's `classify_async_children_for_fork` over the
    authority lineage).
    """

    async def classify_async_children_for_fork(
        self,
        request_scope: str,
        run_id: str,
        children: tuple[AsyncChildInspection, ...],
    ) -> tuple[AsyncChildDisposition, ...]: ...


class AsyncChildLineageSource(Protocol):
    """A parent run's children with their authoritative lifecycle (RRM-013 read side)."""

    async def list_children(
        self, request_scope: str, parent_run_id: str
    ) -> Sequence[AsyncChildLifecycleSubject]: ...


class LineageAsyncChildForkClassifier:
    """RRM-013's classifier (`classify_async_children_for_fork`) over the child lineage.

    The lineage is the 0016 authority row with its 0021 lifecycle mirror
    (`PostgresAsyncSubagentAuthority.list_children`). A child that the run's inspection snapshot
    lists but the lineage does not is classified active (fail closed).
    """

    def __init__(self, lineage: AsyncChildLineageSource) -> None:
        self._lineage = lineage

    async def classify_async_children_for_fork(
        self,
        request_scope: str,
        run_id: str,
        children: tuple[AsyncChildInspection, ...],
    ) -> tuple[AsyncChildDisposition, ...]:
        lineage = tuple(await self._lineage.list_children(request_scope, run_id))
        classification = classify_async_children_for_fork(lineage)
        active = set(classification.active_child_execution_ids)
        known = {child.child_execution_id for child in lineage}
        results = {child.child_execution_id: child for child in children}
        dispositions = [
            AsyncChildDisposition(
                child_execution_id=child.child_execution_id,
                lifecycle=str(child.lifecycle),
                disposition="active" if child.child_execution_id in active else "terminal",
                result_decision=(
                    results[child.child_execution_id].result_decision
                    if child.child_execution_id in results
                    else None
                ),
            )
            for child in lineage
        ]
        dispositions.extend(
            AsyncChildDisposition(
                child_execution_id=child.child_execution_id,
                lifecycle=child.lifecycle,
                disposition="active",
                result_decision=child.result_decision,
            )
            for child in children
            if child.child_execution_id not in known
        )
        return tuple(sorted(dispositions, key=lambda item: item.child_execution_id))


class PendingCommandReader(Protocol):
    """Port: command receipts targeting the run that are not yet `applied` or `rejected`.

    REQ-CP-EXEC-016: an `accepted` or `delivered` command makes the snapshot unsafe. The
    production reader is `LedgerPendingCommands` over RRM-007's durable ledger.
    """

    async def unapplied_command_receipts(
        self, request_scope: str, run_id: str
    ) -> tuple[str, ...]: ...


class BoundaryCommandLedger(Protocol):
    async def list_boundary_commands(
        self, request_scope: str, run_id: str
    ) -> tuple[BoundaryCommandStatus, ...]: ...


class LedgerPendingCommands:
    """RRM-007's `boundary_commands` / `boundary_command_receipts`, read through run control.

    Every command whose latest receipt is neither `applied` nor `rejected` is unapplied and is
    reported as `<issuer>:<command_id>:<state>`. Commands and receipts are audit facts of the
    source run; a fork never copies them.
    """

    def __init__(self, ledger: BoundaryCommandLedger) -> None:
        self._ledger = ledger

    async def unapplied_command_receipts(self, request_scope: str, run_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                f"{item.command.idempotency_issuer}:{item.command.command_id}:{item.state.value}"
                for item in await self._ledger.list_boundary_commands(request_scope, run_id)
                # FT-F1/F4: a `queued` mailbox entry waits for a boundary that has not been
                # reached; it is mailbox content of this run (never copied), not in-flight work.
                if item.state not in SETTLED_RECEIPT_STATES and item.state != ReceiptState.QUEUED
            )
        )


class RunSnapshotRepository(Protocol):
    async def get(self, request_scope: str, snapshot_id: str) -> RunSnapshotManifest | None: ...

    async def latest(self, request_scope: str, run_id: str) -> RunSnapshotManifest | None: ...

    async def put(self, snapshot: RunSnapshotManifest) -> RunSnapshotManifest: ...


class InMemoryRunSnapshotRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.snapshots: dict[tuple[str, str], RunSnapshotManifest] = {}

    async def get(self, request_scope: str, snapshot_id: str) -> RunSnapshotManifest | None:
        return deepcopy(self.snapshots.get((request_scope, snapshot_id)))

    async def latest(self, request_scope: str, run_id: str) -> RunSnapshotManifest | None:
        """FT-F4: the newest sealed Snapshot of a run (highest version, then latest taken)."""

        candidates = [
            item
            for (scope, _), item in self.snapshots.items()
            if scope == request_scope and item.source_run_id == run_id
        ]
        if not candidates:
            return None
        return deepcopy(max(candidates, key=lambda item: (item.projection_version, item.taken_at)))

    async def put(self, snapshot: RunSnapshotManifest) -> RunSnapshotManifest:
        key = (snapshot.request_scope, snapshot.snapshot_id)
        async with self._lock:
            prior = self.snapshots.get(key)
            if prior is not None:
                # Tracing Stage 3 (R2-11): a re-take at the same version and boundary as a
                # snapshot sealed before 1.4.4 differs only by the 1.4.4 stage positions.
                if not snapshots_equivalent(prior, snapshot):
                    raise ForkRejected(
                        "snapshot_digest_conflict",
                        "the same run version and boundary produced a different snapshot",
                        reasons=(prior.snapshot_digest, snapshot.snapshot_digest),
                    )
                return deepcopy(prior)
            self.snapshots[key] = deepcopy(snapshot)
            return deepcopy(snapshot)


# --- Snapshot building (EXEC-016) -----------------------------------------------------------


_FAMILY_BY_HEAD_KIND: Mapping[str, ForkFamily] = {
    "stagegraph": "stage_graph",
    "goal_directed": "goal_directed",
}


def build_run_snapshot(
    snapshot: RunSnapshot,
    facts: ForkSourceFacts,
    async_children: tuple[AsyncChildDisposition, ...],
    *,
    taken_at: datetime,
    unapplied_commands: tuple[str, ...] = (),
    sandbox_snapshot_refs: tuple[str, ...] = (),
    conversation: ConversationEvidence | None = None,
) -> RunSnapshotManifest:
    """Build the manifest at a declared safe boundary, or reject `snapshot_not_quiescent`.

    Every quiescence reason is collected and reported; in-flight work is never classified
    as reusable.
    """

    projection = snapshot.run.projection
    if projection.phase == RunPhase.PENDING:
        raise ForkRejected("unsupported_boundary", "a run that never started has no boundary")
    heads = [head for head in facts.family_heads if head.family_kind in _FAMILY_BY_HEAD_KIND]
    if len(heads) != 1:
        raise ForkRejected(
            "unsupported_boundary", "a run snapshot requires exactly one family head"
        )
    head = heads[0]
    family = _FAMILY_BY_HEAD_KIND[head.family_kind]
    budget = snapshot.budget
    effects = snapshot.effects
    if budget is None or effects is None:
        raise ForkRejected("unsupported_boundary", "run budget and effect authority are absent")

    reasons: list[str] = []
    if projection.phase == RunPhase.CANCELLING:
        reasons.append("run_cancelling")
    reasons.extend(
        f"budget_reservation_open:{reservation_id}"
        for reservation_id, amounts in sorted(budget.reservations.items())
        if reservation_id != "baseline" and any(amounts.values())
    )
    if any(budget.pending_settlement.values()):
        reasons.append("usage_pending_settlement")
    reasons.extend(
        f"effect_claim_unsettled:{effect_id}"
        for effect_id, claim in sorted(effects.claims.items())
        if claim.settlement is None
    )
    reasons.extend(
        f"operator_reconciliation_wait:{wait.condition_id}"
        for wait in projection.active_waits
        if wait.kind == "operator_reconciliation"
    )
    reasons.extend(f"command_unapplied:{item}" for item in unapplied_commands)
    reasons.extend(
        f"continuation_pending:{item.proposal_id}"
        for item in projection.pending_continuation_proposals
    )
    reasons.extend(
        f"async_child_active:{child.child_execution_id}"
        for child in async_children
        if child.disposition == "active"
    )
    linked = tuple(
        LinkedRunDisposition(
            link_id=item.link_id,
            child_run_id=item.child_run_id,
            terminal_status=item.terminal_status,
            disposition="terminal" if item.terminal_status is not None else "active",
        )
        for item in facts.linked_runs
    )
    reasons.extend(
        f"linked_run_active:{item.child_run_id}" for item in linked if item.disposition == "active"
    )

    accepted_settlements = {
        item.settlement_id for item in projection.accepted_operation_settlement_evidence
    }
    candidates: list[ReuseCandidate] = []
    excluded: list[ExcludedUnit] = []
    for unit in snapshot.units:
        reasons.extend(_unit_quiescence_reasons(unit))
        decided = _unit_candidate(unit, accepted_settlements)
        if isinstance(decided, ReuseCandidate):
            candidates.append(decided)
        elif decided is not None:
            excluded.append(decided)

    position, boundary_kind, family_reasons = _family_boundary(
        family, head, snapshot.units, candidates
    )
    reasons.extend(family_reasons)
    if reasons:
        raise ForkRejected(
            "snapshot_not_quiescent",
            "the run is not at a declared safe boundary (EXEC-016)",
            reasons=sorted(set(reasons)),
        )

    accepted_evidence = (
        *(
            AcceptedEvidenceRef(
                kind="obligation", ref=item.obligation_ref, evidence_digest=item.evidence_digest
            )
            for item in projection.accepted_obligation_evidence
        ),
        *(
            AcceptedEvidenceRef(
                kind="output", ref=item.output_ref, evidence_digest=item.evidence_digest
            )
            for item in projection.accepted_output_evidence
        ),
        *(
            AcceptedEvidenceRef(
                kind="operation_settlement",
                ref=item.settlement_id,
                evidence_digest=item.settlement_payload_digest,
            )
            for item in projection.accepted_operation_settlement_evidence
        ),
    )
    boundary_ref = f"family-head:{head.family_kind}:{position.head_mutation_id}"
    return RunSnapshotManifest.create(
        snapshot_id=snapshot_id_for(
            projection.request_scope, projection.run_id, projection.version, boundary_ref
        ),
        request_scope=projection.request_scope,
        source_run_id=projection.run_id,
        execution_epoch=_execution_epoch(snapshot.units),
        family=family,
        projection_version=projection.version,
        run_phase=projection.phase.value,
        effective_configuration_digest=projection.effective_configuration_digest,
        workflow_type_ref=projection.workflow_type_ref,
        input_manifest=projection.input_manifest,
        obligation_revision=projection.obligation_revision,
        evidence_frontier_digest=projection.evidence_frontier_digest,
        blueprint_digest=facts.blueprint_digest,
        semantic_input_binding_digest=facts.semantic_input_binding_digest,
        boundary_kind=boundary_kind,
        boundary_ref=boundary_ref,
        family_position=position,
        accepted_evidence=tuple(sorted(accepted_evidence, key=lambda item: (item.kind, item.ref))),
        reuse_candidates=tuple(sorted(candidates, key=lambda item: item.unit_key)),
        excluded_units=tuple(sorted(excluded, key=lambda item: item.unit_key)),
        budget_frontier=BudgetFrontier(
            account_id=budget.account_id,
            limits=budget.limits,
            reserved=dict(budget.reserved),
            consumed=dict(budget.consumed),
            pending_settlement=dict(budget.pending_settlement),
            reservation_ids=tuple(sorted(budget.reservations)),
        ),
        effect_frontier=tuple(
            EffectFrontierEntry(
                effect_id=effect_id,
                effect_kind=claim.effect_kind,
                disposition=claim.disposition.value,
                settled=claim.settlement is not None,
            )
            for effect_id, claim in sorted(effects.claims.items())
        ),
        async_children=tuple(sorted(async_children, key=lambda item: item.child_execution_id)),
        # FT-G4: the lane workspace a fork restores (empty for lanes without one).
        sandbox_snapshot_refs=tuple(sandbox_snapshot_refs),
        conversation=conversation,
        linked_runs=tuple(sorted(linked, key=lambda item: item.link_id)),
        pending_commands=(),
        taken_at=taken_at,
    )


def _execution_epoch(units: tuple[UnitRecord, ...]) -> int:
    epochs = {unit.identity.execution_epoch for unit in units}
    if len(epochs) > 1:
        raise ForkRejected("unsupported_boundary", "a snapshot spans exactly one execution epoch")
    return next(iter(epochs), 1)


def _current_generation(unit: UnitRecord) -> int | None:
    live = [item.execution_generation for item in unit.generations if not item.superseded]
    return max(live) if live else None


def _unit_quiescence_reasons(unit: UnitRecord) -> list[str]:
    reasons: list[str] = []
    key = unit.identity.unit_key
    generation = _current_generation(unit)
    if generation is not None and not any(
        item.execution_generation == generation for item in unit.results
    ):
        reasons.append(f"unit_unsettled:{key}")
    if any(item.status != "resolved" for item in _latest_incidents(unit)):
        reasons.append(f"unit_in_doubt:{key}")
    if any(record.in_flight_unit_key is not None for record in unit.namespaces):
        reasons.append(f"cognition_in_flight:{key}")
    for claim in unit.journal:
        if not any(item.status in SETTLED_STATUSES for item in claim.settlements):
            reasons.append(f"operation_claim_unsettled:{claim.effect_claim_id}")
    return reasons


def _latest_incidents(unit: UnitRecord) -> list[Any]:
    latest: dict[tuple[int, int], Any] = {}
    for item in unit.incidents:
        latest[(item.execution_generation, item.revision)] = item
    return list(latest.values())


def _unit_candidate(
    unit: UnitRecord, accepted_settlements: set[str]
) -> ReuseCandidate | ExcludedUnit | None:
    identity = unit.identity
    generation_number = _current_generation(unit)
    if generation_number is None:
        if unit.generations:
            return ExcludedUnit(unit=identity, unit_key=identity.unit_key, reason="superseded")
        return None
    generation = next(
        item for item in unit.generations if item.execution_generation == generation_number
    )
    result = next(
        (item for item in unit.results if item.execution_generation == generation_number),
        None,
    )
    if result is None:
        return None  # unsettled: reported as a quiescence reason, never a candidate
    if any(
        item.execution_generation == generation_number and item.status != "resolved"
        for item in _latest_incidents(unit)
    ):
        return ExcludedUnit(unit=identity, unit_key=identity.unit_key, reason="quarantined")
    if result.status != "completed":
        return ExcludedUnit(unit=identity, unit_key=identity.unit_key, reason="not_completed")
    settled = next(
        (
            settlement
            for claim in unit.journal
            if claim.semantic_binding_id == generation.binding_id
            for settlement in claim.settlements
            if settlement.settlement_id == result.settlement_id
            and settlement.status == "completed"
            and settlement.result_manifest_digest == result.result_manifest_digest
        ),
        None,
    )
    if settled is None or result.settlement_id not in accepted_settlements:
        return ExcludedUnit(unit=identity, unit_key=identity.unit_key, reason="not_accepted")
    transition = next(
        (
            item
            for item in unit.transitions
            if item.execution_generation == generation_number
            and item.transition_id == result.checkpoint_transition_id
        ),
        None,
    )
    return ReuseCandidate(
        unit=identity,
        unit_key=identity.unit_key,
        execution_generation=generation_number,
        binding_id=generation.binding_id,
        binding_digest=generation.binding_digest,
        state_schema_digest=generation.state_schema_digest,
        settlement_id=result.settlement_id,
        result_manifest_ref=result.result_manifest_ref,
        result_manifest_digest=result.result_manifest_digest,
        result_manifest_size_bytes=result.result_manifest_size_bytes,
        result_checkpoint=transition.result_key if transition is not None else None,
    )


def _liability_closed(liability: object) -> bool:
    return isinstance(liability, dict) and (
        all(
            liability.get(flag) is True
            for flag in (
                "child_closed_or_quiesced",
                "reservations_and_usage_settled",
                "effects_settled",
                "cancellation_reconciled",
            )
        )
        and liability.get("result_decision") is not None
    )


def _completed(unit: UnitRecord) -> bool:
    generation = _current_generation(unit)
    return (
        generation is not None
        and any(
            item.execution_generation == generation and item.status == "completed"
            for item in unit.results
        )
        and not any(
            item.execution_generation == generation and item.status != "resolved"
            for item in _latest_incidents(unit)
        )
    )


def _family_boundary(
    family: ForkFamily,
    head: FamilyHeadRecord,
    units: tuple[UnitRecord, ...],
    candidates: list[ReuseCandidate],
) -> tuple[FamilyPosition, SnapshotBoundaryKind, list[str]]:
    mutation = head.mutation
    common = {
        "family": family,
        "family_kind": head.family_kind,
        "family_version": head.family_version,
        "head_mutation_id": str(mutation.get("mutation_id", "")),
        "head_mutation_kind": str(mutation.get("mutation_kind", "")),
        "head_mutation_fingerprint": head.mutation_fingerprint,
    }
    reasons: list[str] = []
    if family == "stage_graph":
        payload = mutation.get("decision_payload")
        projection = payload.get("projection") if isinstance(payload, dict) else None
        if not isinstance(projection, dict):
            raise ForkRejected("unsupported_boundary", "the StageGraph head has no projection")
        liabilities = projection.get("producer_liabilities") or {}
        # A decided producer liability stays in the projection, closed; only an open one
        # (admitted work not yet settled and decided) blocks the boundary.
        reasons.extend(
            f"stage_liability_open:{key}"
            for key, liability in sorted(liabilities.items())
            if not _liability_closed(liability)
        )
        stages = projection.get("stages") or {}
        accepted = sorted(
            {
                str(instance["candidate"]["stage_id"])
                for instance in stages.values()
                if isinstance(instance, dict)
                and instance.get("status") in {"completed", "degraded"}
                and isinstance(instance.get("candidate"), dict)
            }
        )
        reasons.extend(
            f"stage_active:{prefix}"
            for prefix, instance in sorted(stages.items())
            if isinstance(instance, dict) and instance.get("status") in ACTIVE_STAGE_STATUSES
        )
        if not projection.get("accepted_results"):
            raise ForkRejected("unsupported_boundary", "no stage settlement has been accepted yet")
        workflow_cycle = int(projection.get("workflow_cycle_ordinal", 0))
        stage_cycles, stage_objectives = _stage_cycles(stages, workflow_cycle)
        position = FamilyPosition(
            **common,
            accepted_projection_digest=str(mutation.get("next_projection_digest")),
            workflow_cycle_ordinal=workflow_cycle,
            accepted_stage_ids=tuple(accepted),
            stage_cycle_ordinals=stage_cycles,
            stage_objectives=stage_objectives,
        )
        return position, "stage_settled", reasons

    role = mutation.get("operation_role")
    iteration = mutation.get("goal_iteration")
    revision_id = mutation.get("goal_revision_id")
    if role != "verifier":
        reasons.append("goal_iteration_in_progress")
    # The verifier decision is settled when the head iteration's verifier unit has a
    # completed, fenced result observation and no open incident. GoalDirected records its
    # own usage and acceptance, so this does not require the run-control journal.
    verifier_settled = any(
        isinstance(unit.identity.location, GoalDirectedUnitLocation)
        and unit.identity.location.operation_role == "verifier"
        and unit.identity.location.goal_iteration == iteration
        and unit.identity.location.goal_revision_id == revision_id
        and _completed(unit)
        for unit in units
    )
    if role == "verifier" and not verifier_settled:
        reasons.append("goal_verifier_unsettled")
    del candidates
    position = FamilyPosition(
        **common,
        goal_revision_id=str(revision_id) if revision_id else None,
        goal_revision_digest=(
            str(mutation["goal_revision_digest"]) if mutation.get("goal_revision_digest") else None
        ),
        goal_iteration=int(iteration) if isinstance(iteration, int) else None,
        head_operation_role=role if role in {"executor", "verifier"} else None,
        handoff_ref=str(mutation["handoff_ref"]) if mutation.get("handoff_ref") else None,
    )
    return position, "goal_verifier_settled", reasons


def _stage_cycles(
    stages: Mapping[str, Any], workflow_cycle: int
) -> tuple[dict[str, int], dict[str, str]]:
    """1.4.4 (P5.3): the current stage cycle of every stage of the head projection (the
    highest `stage_cycle_ordinal` among its candidates in the current workflow cycle) and
    the objective override of that cycle, so a fork can place the derived run there."""

    cycles: dict[str, int] = {}
    objectives: dict[str, str] = {}
    for instance in stages.values():
        candidate = instance.get("candidate") if isinstance(instance, dict) else None
        if not isinstance(candidate, dict):
            continue
        stage_id = str(candidate.get("stage_id", ""))
        if not stage_id or int(candidate.get("workflow_cycle_ordinal", 0)) != workflow_cycle:
            continue
        cycle = int(candidate.get("stage_cycle_ordinal", 0))
        if stage_id in cycles and cycles[stage_id] >= cycle:
            continue
        cycles[stage_id] = cycle
        objective = instance.get("objective_override")
        if isinstance(objective, str) and objective:
            objectives[stage_id] = objective
        else:
            objectives.pop(stage_id, None)
    return cycles, objectives


class LaneSnapshotRefReader(Protocol):
    """FT-G4: the lane workspace snapshot a run's file-based lane froze at session end
    (`cursor-snapshot:<ref>`), recorded so a fork restores the workspace from it."""

    async def sandbox_snapshot_refs(self, request_scope: str, run_id: str) -> tuple[str, ...]: ...


@runtime_checkable
class LaneSnapshotEvidenceReader(Protocol):
    async def sandbox_snapshot_evidence(
        self, request_scope: str, run_id: str
    ) -> LaneSnapshotEvidence: ...


class RunSnapshotService:
    """Take and read immutable run snapshots at safe boundaries (EXEC-016)."""

    def __init__(
        self,
        *,
        reads: InspectionReadRepository,
        sources: ForkSourceReader,
        snapshots: RunSnapshotRepository,
        async_children: AsyncChildForkClassifier,
        commands: PendingCommandReader,
        clock: Clock | None = None,
        lane_snapshots: LaneSnapshotRefReader | None = None,
    ) -> None:
        self._reads = reads
        self._sources = sources
        self._snapshots = snapshots
        self._async_children = async_children
        self._commands = commands
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lane_snapshots = lane_snapshots

    async def take(
        self,
        request_scope: str,
        run_id: str,
        *,
        expected_run_version: int | None = None,
    ) -> RunSnapshotManifest:
        for _attempt in range(MAX_SNAPSHOT_READ_ATTEMPTS):
            read = await self._reads.read_run(request_scope, run_id)
            if read is None:
                raise ForkSnapshotNotFound("workflow run not found")
            version = read.run.projection.version
            if expected_run_version is not None and version != expected_run_version:
                raise ForkRejected(
                    "stale_expected_version",
                    f"expected run version {expected_run_version}, current is {version}",
                )
            facts = await self._sources.read_fork_source(request_scope, run_id)
            if facts is None:
                raise ForkSnapshotNotFound("workflow run not found")
            if facts.run_version != version:
                continue  # authority moved between the two reads; read both again
            dispositions = await self._async_children.classify_async_children_for_fork(
                request_scope, run_id, read.async_children
            )
            unapplied = await self._commands.unapplied_command_receipts(request_scope, run_id)
            lane_evidence = (
                await self._lane_snapshots.sandbox_snapshot_evidence(request_scope, run_id)
                if isinstance(self._lane_snapshots, LaneSnapshotEvidenceReader)
                else LaneSnapshotEvidence(
                    refs=(
                        await self._lane_snapshots.sandbox_snapshot_refs(request_scope, run_id)
                        if self._lane_snapshots is not None
                        else ()
                    )
                )
            )
            manifest = build_run_snapshot(
                read,
                facts,
                dispositions,
                taken_at=self._clock(),
                unapplied_commands=tuple(unapplied),
                sandbox_snapshot_refs=lane_evidence.refs,
                conversation=lane_evidence.conversation,
            )
            return await self._snapshots.put(manifest)
        raise ForkRejected("snapshot_source_moving", "run authority kept moving while it was read")

    async def get(self, request_scope: str, snapshot_id: str) -> RunSnapshotManifest:
        snapshot = await self._snapshots.get(request_scope, snapshot_id)
        if snapshot is None:
            raise ForkSnapshotNotFound("run snapshot not found")
        return snapshot

    async def latest_or_take(self, request_scope: str, run_id: str) -> RunSnapshotManifest:
        """FT-F4: the latest safe Snapshot of the run, taking one at the current boundary
        when none was sealed; a run with no safe boundary is `CHECKPOINT_INVALID`."""

        latest = await self._snapshots.latest(request_scope, run_id)
        if latest is not None:
            return latest
        try:
            return await self.take(request_scope, run_id)
        except ForkRejected as error:
            if error.code in {"stale_expected_version", "snapshot_source_moving"}:
                raise
            raise ForkRejected(
                "CHECKPOINT_INVALID",
                "the run has no safe Snapshot to fork from",
                reasons=(error.code, *error.reasons),
            ) from error


# --- Fork command, policy registry, admission compilation ---------------------------------


class ForkCommand(BaseModel):
    """An operator's fork intent before the server binds snapshot, patch and admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_scope: str = Field(min_length=1, max_length=256)
    source_run_id: str = Field(min_length=1, max_length=512)
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
    idempotency_key: str = Field(min_length=1, max_length=512)
    snapshot_id: str = Field(min_length=1, max_length=512)
    snapshot_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    changes: tuple[ForkPatchChange, ...] = ()
    invalidation_frontier: tuple[str, ...] = ()
    cognitive_seed: AnyCognitiveSeed | None = None
    baseline_reservations: dict[str, int] = Field(default_factory=dict)
    sponsorship_ref: str = Field(min_length=1)
    approval_refs: tuple[str, ...] = ()
    actor: ActorContext
    reason: str = Field(min_length=1, max_length=2_000)
    requested_at: AwareDatetime
    # 1.4.4 (P5.1): the precise fork.
    at: ForkAt | None = None
    frontier_policy: FrontierPolicy = "close"
    message: ContentRef | InlineText | None = None


class ForkPatchPolicyRegistry:
    """Patchable-field declarations by exact Workflow Type digest, with family defaults."""

    def __init__(self) -> None:
        self._policies: dict[str, ForkPatchPolicy] = {}

    def register(self, workflow_type_digest: str, policy: ForkPatchPolicy) -> None:
        prior = self._policies.get(workflow_type_digest)
        if prior is not None and prior != policy:
            raise ValueError("a different fork patch policy is registered for this Workflow Type")
        self._policies[workflow_type_digest] = policy

    def resolve(self, snapshot: RunSnapshotManifest) -> ForkPatchPolicy:
        policy = self._policies.get(snapshot.workflow_type_ref.digest)
        if policy is None:
            return default_patch_policy(snapshot.family)
        if policy.family != snapshot.family:
            raise ValueError("the registered fork patch policy belongs to another family")
        return policy


def compile_fork_admission(
    snapshot: RunSnapshotManifest,
    command: ForkCommand,
    *,
    patch_digest: str,
    effective_configuration_digest: str,
    input_manifest: Any,
    baseline_reservations: Mapping[str, int] | None = None,
) -> RunRequest:
    """The derived run's own admission: same scope and Workflow Type, protected budget
    ceilings, a fresh budget account and reservations, and the caller's authority.
    `baseline_reservations` (F-S2-10) is the derived run's baseline hold; the command's own
    when not given."""

    return RunRequest(
        request_scope=snapshot.request_scope,
        idempotency_issuer=command.actor.actor_id,
        request_id=command.request_id,
        actor=command.actor,
        effective_configuration_digest=effective_configuration_digest,
        workflow_type_ref=snapshot.workflow_type_ref,
        input_manifest=input_manifest,
        budget_envelope=BudgetEnvelope(
            dimensions=snapshot.budget_frontier.limits,
            baseline_reservations=dict(
                command.baseline_reservations
                if baseline_reservations is None
                else baseline_reservations
            ),
        ),
        requested_at=command.requested_at,
        correlation_id=f"fork:{command.request_id}",
        causation_id=snapshot.snapshot_id,
        sponsorship_ref=command.sponsorship_ref,
        approval_refs=command.approval_refs,
        # The fork marker travels in the derived run's immutable admission transition.
        admission_evidence_refs=(
            f"{FORK_REQUEST_MARKER_PREFIX}{command.request_id}",
            snapshot.snapshot_ref,
            f"fork-patch:{patch_digest}",
        ),
    )


class ForkBlueprintReader(Protocol):
    """1.4.4 (P5.2): the frozen Stage Graph blueprint of the source run, for the closure."""

    async def stage_blueprint(
        self, request_scope: str, snapshot: RunSnapshotManifest
    ) -> StageGraphBlueprint | None: ...


class EffectiveConfigurationRetrieval(Protocol):
    async def retrieve(self, digest: str) -> Any: ...


@runtime_checkable
class SelectedBlueprintSource(Protocol):
    """An effective configuration that names its selected blueprint."""

    @property
    def selected_blueprint(self) -> object: ...


class EffectiveConfigurationBlueprintReader:
    """The source blueprint from the run's immutable effective configuration (its
    `selected_blueprint`); None for a Goal Directed run or an unreadable configuration."""

    def __init__(self, control_plane: EffectiveConfigurationRetrieval) -> None:
        self._control_plane = control_plane

    async def stage_blueprint(
        self, request_scope: str, snapshot: RunSnapshotManifest
    ) -> StageGraphBlueprint | None:
        if snapshot.family != "stage_graph":
            return None
        try:
            erc = await self._control_plane.retrieve(snapshot.effective_configuration_digest)
        except (ControlPlaneError, LookupError, OSError, ValueError) as error:
            # Tracing Stage 3: a missing, unreadable or invalid configuration (or a store that
            # did not answer) is the typed outcome; anything else is a defect and propagates.
            raise ForkRejected(
                "frontier_closure_unavailable",
                f"the source blueprint could not be read for the closure: {error}",
            ) from error
        if not isinstance(erc, SelectedBlueprintSource):
            return None
        blueprint = erc.selected_blueprint
        return blueprint if isinstance(blueprint, StageGraphBlueprint) else None


class CognitiveSeeds(Protocol):
    """P1 turn 4: the cognitive seed admission and restore (`recovery/cognitive_seed.py`)."""

    async def resolve(
        self, request_scope: str, source_run_id: str, seed: AnyCognitiveSeed
    ) -> Any: ...

    async def seed(self, request: RunForkRequest, receipt: RunForkReceipt) -> Any: ...


class ForkAdmissionProvenance(Protocol):
    """Trusted origin evidence; caller-authored fork patches cannot supply admission facts."""

    async def evidence(self, target: RunRequest) -> tuple[str, ...]: ...


class SemanticForkService:
    """Validate a fork against its immutable snapshot and run the audited saga."""

    def __init__(
        self,
        *,
        snapshots: RunSnapshotRepository,
        saga: RuntimeForkService,
        policies: ForkPatchPolicyRegistry | None = None,
        seeds: CognitiveSeeds | None = None,
        blueprints: ForkBlueprintReader | None = None,
        admission_provenance: ForkAdmissionProvenance | None = None,
    ) -> None:
        self._snapshots = snapshots
        self._saga = saga
        self._policies = policies or ForkPatchPolicyRegistry()
        # P1 turn 4 (WP-2): admits and applies `cognitive_seed` for lanes forking at R3.
        self._seeds = seeds
        # 1.4.4 (P5.2): the frontier closure needs the source blueprint; without a reader
        # the frontier is taken as given and the receipt records it unclosed.
        self._blueprints = blueprints
        self._admission_provenance = admission_provenance

    async def prepare(self, command: ForkCommand) -> RunForkRequest:
        missing = sorted({FORK_PERMISSION, ADMIT_PERMISSION} - command.actor.permissions)
        if missing:
            # Checked before anything is reserved, so an under-privileged caller never leaves
            # a fork reservation stuck in `admitting`.
            raise ForkRejected(
                "unauthorized", "the actor lacks the fork permissions", reasons=missing
            )
        snapshot = await self._snapshots.get(command.request_scope, command.snapshot_id)
        if snapshot is None or snapshot.source_run_id != command.source_run_id:
            raise ForkSnapshotNotFound("run snapshot not found")
        if snapshot.snapshot_digest != command.snapshot_digest:
            raise ForkRejected(
                "stale_snapshot", "the fork names another snapshot digest for this snapshot"
            )
        policy = self._policies.resolve(snapshot)
        target_ref = (
            f"run-request:{snapshot.request_scope}:{command.actor.actor_id}:{command.request_id}"
        )
        seed_allowed = False
        seed_record: CognitionPointRecord | None = None
        if command.cognitive_seed is not None and self._seeds is not None:
            seed_record = await self._seeds.resolve(
                command.request_scope, snapshot.source_run_id, command.cognitive_seed
            )
            seed_allowed = True
        # 1.4.4 (P5.1, P5.2): the fork position (from the seed point when not given) and
        # the frontier closure under the policy.
        at = _fork_position(snapshot, command.at, seed_record)
        requested = set(command.invalidation_frontier)
        if at is not None and at.stage is not None:
            requested.add(at.stage)
        frontier_requested = tuple(sorted(requested))
        closed = await self._close_frontier(snapshot, frontier_requested, command.frontier_policy)
        # Tracing Stage 3 (R2-15): a frontier nothing closed (no blueprint reader composed,
        # or no blueprint) is recorded as unclosed, never as its own closure.
        frontier_closed = closed if closed is not None else ()
        patch = RunForkPatch.create(
            source_snapshot_id=snapshot.snapshot_id,
            source_snapshot_digest=snapshot.snapshot_digest,
            target_admission_request_ref=target_ref,
            changes=command.changes,
            invalidation_frontier=closed if closed is not None else frontier_requested,
            cognitive_seed=command.cognitive_seed,
        )
        frontier = required_invalidation_frontier(
            patch, policy, cognitive_seed_allowed=seed_allowed
        )
        configuration = patch.change("effective_configuration_digest")
        manifest = patch.change("input_manifest")
        baseline = await self._baseline_reservations(command)
        try:
            target = compile_fork_admission(
                snapshot,
                command,
                patch_digest=patch.patch_digest,
                effective_configuration_digest=(
                    str(configuration.value)
                    if configuration is not None
                    else snapshot.effective_configuration_digest
                ),
                input_manifest=(
                    manifest.value if manifest is not None else snapshot.input_manifest
                ),
                baseline_reservations=baseline,
            )
        except ValidationError as error:
            # For example a baseline reservation above a protected budget ceiling.
            raise ForkRejected(
                "fork_admission_rejected",
                "the derived run's admission request is invalid",
                reasons=("invalid_admission_request",),
            ) from error
        if self._admission_provenance is not None:
            evidence = await self._admission_provenance.evidence(target)
            target = target.model_copy(
                update={
                    "admission_evidence_refs": (*target.admission_evidence_refs, *evidence),
                }
            )
        if admission_request_ref(target) != target_ref:
            raise ForkRejected("invalid_patch", "the compiled admission is not the patched one")
        derived_run_id = run_identity_for(
            target.request_scope, target.idempotency_issuer, target.request_id
        )
        derived_revision: str | None = None
        if at is not None and at.iteration is not None:
            source_revision = snapshot.family_position.goal_revision_id
            if source_revision is None:
                raise ForkRejected(
                    "fork_position_unavailable",
                    "the snapshot's family position names no Goal Revision to derive from",
                )
            _check_goal_position(snapshot, at, source_revision)
            derived_revision = derived_goal_revision_id(source_revision, derived_run_id)
        decisions = compute_reuse_decisions(
            snapshot,
            fork_request_id=command.request_id,
            derived_run_id=derived_run_id,
            frontier=frontier,
            at=at,
            derived_goal_revision_id=derived_revision,
        )
        message_text, delivery = _message_delivery(command)
        return RunForkRequest(
            request_id=command.request_id,
            idempotency_key=command.idempotency_key,
            request_scope=command.request_scope,
            source_run_id=snapshot.source_run_id,
            source_execution_epoch=snapshot.execution_epoch,
            snapshot_id=snapshot.snapshot_id,
            snapshot_digest=snapshot.snapshot_digest,
            patch=patch,
            target=target,
            derived_run_id=derived_run_id,
            reuse_decisions=decisions,
            actor_id=command.actor.actor_id,
            reason=command.reason,
            requested_at=command.requested_at,
            at=at,
            frontier_policy=command.frontier_policy,
            frontier_requested=frontier_requested,
            frontier_closed=frontier_closed,
            start_position=_start_position(snapshot, at, decisions, frontier),
            derived_goal_revision_id=derived_revision,
            message_text=message_text,
            message_delivery=delivery,
        )

    async def _baseline_reservations(self, command: ForkCommand) -> dict[str, int]:
        """F-S2-10 (owner decision 2026-10-22, "default to source"): the derived run's
        baseline hold is the source run's admitted baseline, with the command's own
        `baseline_reservations` overriding it per dimension. A replay of a fork reserved
        before this default keeps the baseline that fork recorded."""

        explicit = dict(command.baseline_reservations)
        persisted = await self._saga.persisted_request(command.request_scope, command.request_id)
        if persisted is not None:
            recorded = dict(persisted.target.budget_envelope.baseline_reservations)
            if all(recorded.get(name) == amount for name, amount in explicit.items()):
                return recorded
        source = await self._saga.source_baseline(command.request_scope, command.source_run_id)
        return {**dict(source or {}), **explicit}

    async def _close_frontier(
        self,
        snapshot: RunSnapshotManifest,
        requested: tuple[str, ...],
        policy: FrontierPolicy,
    ) -> tuple[str, ...] | None:
        """P5.2 (TR-D12): `requested | descendants(requested)` over the source blueprint.
        `close` records the closed set; `strict` refuses a frontier narrower than its closure
        (`frontier_not_closed`, naming the missing stages). Under `*`, for a Goal Directed
        run or an empty frontier the frontier is its own closure. Without a blueprint reader
        (or a blueprint) nothing is closed: None (Tracing Stage 3, R2-15), and `strict`
        refuses `frontier_closure_unavailable`."""

        if snapshot.family != "stage_graph" or not requested or INVALIDATE_ALL in requested:
            return requested
        blueprint = (
            await self._blueprints.stage_blueprint(snapshot.request_scope, snapshot)
            if self._blueprints is not None
            else None
        )
        if blueprint is None:
            if policy == "strict":
                raise ForkRejected(
                    "frontier_closure_unavailable",
                    "a strict frontier needs the source blueprint, which is not available here",
                    reasons=requested,
                )
            return None
        unknown = sorted(set(requested) - {stage.stage_id for stage in blueprint.stages})
        if unknown:
            raise ForkRejected(
                "invalid_patch", "the invalidation frontier names unknown stages", reasons=unknown
            )
        closure = closed_frontier(blueprint, requested)
        missing = sorted(closure - set(requested))
        if missing and policy == "strict":
            raise ForkRejected(
                "frontier_not_closed",
                "the invalidation frontier leaves consumers of invalidated stages outside it",
                reasons=missing,
            )
        return tuple(sorted(closure))

    async def fork(self, command: ForkCommand) -> RunForkReceipt:
        request = await self.prepare(command)
        if request.patch.cognitive_seed is None or self._seeds is None:
            return await self._saga.fork(request)
        # The derived run is admitted and materialized; its seed unit's namespace now
        # continues from the point. Tracing Stage 3 (R2-2, R2-3): the seed runs before the
        # receipt is recorded, so a receipt proves the seed is in place (the launch refuses a
        # seeded fork without one, retryably), a refused seed leaves the fork replayable, and
        # a replay of a fork that has its receipt never re-runs the copy.
        return await self._saga.fork(request, before_receipt=self._seeds.seed)

    async def persisted_request(self, request_scope: str, request_id: str) -> RunForkRequest | None:
        """The fork already reserved under this id (a retry reuses its Snapshot)."""

        return await self._saga.persisted_request(request_scope, request_id)


def _fork_position(
    snapshot: RunSnapshotManifest, at: ForkAt | None, seed: CognitionPointRecord | None
) -> ForkAt | None:
    """P5.1: `at` as given, else derived from the seed point's location; a position of the
    other family is refused."""

    if at is None and seed is not None:
        location = seed.location
        if location.family == "stage_graph":
            at = ForkAt(stage=location.node_key, cycle=location.cycle)
        else:
            at = ForkAt(
                iteration=location.iteration, session_generation=location.session_generation or 1
            )
    if at is not None and at.family != snapshot.family:
        raise ForkRejected(
            "invalid_patch",
            f"`at` names a {at.family} position on a {snapshot.family} run",
        )
    if at is not None and seed is not None:
        location = seed.location
        seed_session = location.session_generation or 1
        matches = (
            (at.stage == location.node_key and at.cycle == location.cycle)
            if at.stage is not None
            # Tracing Stage 3 (R2-9): the seeded thread is the role thread of the seed's
            # session generation; `at` defaults to it and may not name another.
            else at.iteration == location.iteration
            and at.session_generation in (None, seed_session)
        )
        if matches and at.iteration is not None and at.session_generation is None:
            at = ForkAt(iteration=at.iteration, session_generation=seed_session)
        if not matches:
            raise ForkRejected(
                "invalid_patch",
                "`at` does not name the seed point's unit position",
                reasons=(
                    f"{location.node_key}@{location.cycle}"
                    if location.family == "stage_graph"
                    else f"iteration:{location.iteration},session:{seed_session}",
                ),
            )
    return at


def _start_position(
    snapshot: RunSnapshotManifest,
    at: ForkAt | None,
    decisions: tuple[ForkReuseDecision, ...],
    frontier: frozenset[str] = frozenset(),
) -> ForkStartPosition | None:
    """P5.3/P5.4: where the derived run starts, from the fork position, the snapshot's family
    position and the reuse decisions (the invalidated units of the `at` stage must reach the
    requested cycle; the Goal Directed agent run follows the last reused unit).

    Tracing Stage 3 (R2-7/8): every Stage Graph stage outside the invalidation frontier
    starts at the cycle the source holds it at (`FamilyPosition.stage_cycle_ordinals`) with
    that cycle's objective, so a reused upstream stage that cycled is not re-run from cycle 0.
    The snapshot records only the current cycle's objective of each stage, so a fork at an
    older cycle after the first is refused `fork_position_unavailable` rather than started
    without the objective that cycle ran with. Goal Directed (R2-4): every iteration below
    `at.iteration` must be reused (executor and verifier), or the derived run cannot start
    there (a whole-run patch such as `goal.objective` invalidates them all).
    """

    if at is None:
        return None
    position = snapshot.family_position
    if at.stage is not None:
        assert at.cycle is not None
        reached = max(
            (
                item.derived_unit.location.stage_cycle_ordinal
                for item in decisions
                if isinstance(item.derived_unit.location, StageGraphUnitLocation)
                and item.derived_unit.location.stage_id == at.stage
            ),
            default=None,
        )
        if reached is None or reached < at.cycle:
            raise ForkRejected(
                "fork_position_unavailable",
                f"the source never reached {at.stage} cycle {at.cycle}",
                reasons=(f"reached:{reached}",),
            )
        current = position.stage_cycle_ordinals.get(at.stage)
        if at.cycle > 0 and at.cycle != current:
            raise ForkRejected(
                "fork_position_unavailable",
                f"the snapshot holds the objective of {at.stage} cycle {current} only; a fork "
                f"at cycle {at.cycle} would run without the objective that cycle ran with",
                reasons=(f"current:{current}", f"requested:{at.cycle}"),
            )
        ordinals = {at.stage: at.cycle}
        objectives: dict[str, str] = {}
        objective = position.stage_objectives.get(at.stage) if at.cycle > 0 else None
        if objective is not None:
            objectives[at.stage] = objective
        if INVALIDATE_ALL not in frontier:
            for stage_id, cycle in sorted(position.stage_cycle_ordinals.items()):
                if stage_id in frontier or stage_id == at.stage or cycle == 0:
                    continue
                ordinals[stage_id] = cycle
                upstream = position.stage_objectives.get(stage_id)
                if upstream is not None:
                    objectives[stage_id] = upstream
        return ForkStartPosition(
            workflow_cycle_ordinal=position.workflow_cycle_ordinal or 0,
            stage_cycle_ordinals=ordinals,
            stage_objectives=objectives,
        )
    assert at.iteration is not None
    reused = [
        item.derived_unit.location
        for item in decisions
        if item.decision == "reuse"
        and isinstance(item.derived_unit.location, GoalDirectedUnitLocation)
    ]
    covered = {(location.goal_iteration, location.operation_role) for location in reused}
    missing = [
        f"{role}@{iteration}"
        for iteration in range(1, at.iteration)
        for role in ("executor", "verifier")
        if (iteration, role) not in covered
    ]
    if missing:
        raise ForkRejected(
            "fork_position_unavailable",
            f"the derived run cannot start at iteration {at.iteration}: the iterations before "
            "it are not all reused (a whole-run patch such as a new goal objective re-runs "
            "every iteration; fork at iteration 1, or without `at` and a seed)",
            reasons=(*(("whole_run_patch",) if INVALIDATE_ALL in frontier else ()), *missing),
        )
    return ForkStartPosition(
        goal_iteration=at.iteration,
        session_generation=at.session_generation or 1,
        agent_run=(max(location.agent_run for location in reused) + 1) if reused else 1,
    )


def _check_goal_position(snapshot: RunSnapshotManifest, at: ForkAt, head_revision: str) -> None:
    """Tracing Stage 3 (R2-5, R2-10): a Goal Directed `at` names an iteration the source
    reached, below which every unit ran under the head's Goal Revision (the derived run's
    revision is minted from it; a revision accepted below the fork iteration would need a
    re-minted revision per reused iteration, which does not exist yet)."""

    assert at.iteration is not None
    units = [
        *(item.unit for item in snapshot.reuse_candidates),
        *(item.unit for item in snapshot.excluded_units),
    ]
    locations = [
        unit.location for unit in units if isinstance(unit.location, GoalDirectedUnitLocation)
    ]
    reached = snapshot.family_position.goal_iteration or max(
        (location.goal_iteration for location in locations), default=0
    )
    if at.iteration > reached:
        raise ForkRejected(
            "fork_position_unavailable",
            f"the source never reached iteration {at.iteration}",
            reasons=(f"reached:{reached}",),
        )
    changed = sorted(
        {
            f"iteration:{location.goal_iteration}"
            for location in locations
            if location.goal_iteration < at.iteration and location.goal_revision_id != head_revision
        }
    )
    if changed:
        raise ForkRejected(
            "fork_position_unavailable",
            f"an accepted Goal Revision changed below iteration {at.iteration}; a fork there "
            "is not supported until reused iterations re-mint their own revisions",
            reasons=changed,
        )


def _message_delivery(command: ForkCommand) -> tuple[str | None, MessageDelivery]:
    """Every fork message is queued to the derived run's mailbox as an operator instruction.

    Loop iter-3 F1-G3 (owner, 2026-11-06), superseding P5.1's seed-head delivery: as the seed
    head's last human message it was followed by the derived stage's re-sent prompt and
    rendered as data, so the model declined it. As a queued instruction for the fork's stage
    it renders last, in the start packet's Operator instructions section; the seed head stays
    the exact state at the point. `seed_head` remains a readable value for older receipts.
    """

    if command.message is None:
        return None, "none"
    return None, "mailbox"


# --- Admission authority over run control -------------------------------------------------


class AdmissionDecisionReader(Protocol):
    async def get_admission_decision(
        self, request_scope: str, idempotency_issuer: str, request_id: str
    ) -> Any: ...


@runtime_checkable
class BudgetLedgerReader(Protocol):
    async def list_budget_ledger(
        self, request_scope: str, run_id: str
    ) -> Sequence[BudgetLedgerEntry]: ...


class RunControlForkAuthority:
    """Admit the derived run through the ordinary transactional admission (REQ-CP-RUN-001)."""

    def __init__(
        self,
        run_control: RunControlService,
        decisions: RunControlRepository | AdmissionDecisionReader,
    ) -> None:
        self._run_control = run_control
        self._decisions = decisions

    async def admit_fork(self, request: RunForkRequest) -> ForkAdmission:
        decision = await self._run_control.admit(request.target)
        return await self._admission(request, decision)

    async def admitted_baseline(self, request_scope: str, run_id: str) -> dict[str, int] | None:
        """F-S2-10: the baseline the source run's admission reserved (its `baseline`
        reservation ledger entry), read from the run-control ledger; None when this
        authority has no ledger reader or the run recorded none."""

        if not isinstance(self._decisions, BudgetLedgerReader):
            return None
        for entry in await self._decisions.list_budget_ledger(request_scope, run_id):
            if entry.kind == BudgetLedgerKind.RESERVATION and entry.idempotency_id == "baseline":
                return dict(entry.amounts)
        return None

    async def reconcile_fork_admission(self, request: RunForkRequest) -> ForkAdmissionObservation:
        target = request.target
        decision = await self._decisions.get_admission_decision(
            target.request_scope, target.idempotency_issuer, target.request_id
        )
        if decision is None:
            return ForkAdmissionObservation(status="definitively_missing")
        return ForkAdmissionObservation(
            status="admitted", admission=await self._admission(request, decision)
        )

    async def _admission(self, request: RunForkRequest, decision: Any) -> ForkAdmission:
        target = request.target
        if decision.status != DecisionStatus.ACCEPTED or decision.run_id is None:
            raise ForkRejected(
                "fork_admission_rejected",
                f"the derived run was not admitted: {decision.reason}",
                reasons=(decision.reason_code,),
            )
        scope = target.request_scope
        projection = await self._run_control.get_run(scope, decision.run_id)
        budget = await self._run_control.get_budget(scope, decision.run_id)
        transitions = await self._run_control.list_transitions(scope, decision.run_id)
        admitted = transitions[0] if transitions else None
        marker = f"{FORK_REQUEST_MARKER_PREFIX}{request.request_id}"
        # The derived run's epoch is read from its admission transition: a run admitted at
        # version 1 by this fork's admission request starts at epoch 1, and run control
        # records no epoch rollover (rollover is not published; `decide_recovery_mode`).
        if (
            admitted is None
            or admitted.resulting_version != 1
            or admitted.prior_version != 0
            or admitted.command_id != f"admission:{target.request_id}"
            or marker not in admitted.evidence_refs
        ):
            raise ForkRejected(
                "fork_admission_rejected",
                "the admitted run is not this fork's fresh admission",
                reasons=("admission_transition_mismatch",),
            )
        if budget.parent_account_id is not None or budget.limits != tuple(
            target.budget_envelope.dimensions
        ):
            raise ForkRejected(
                "fork_admission_rejected",
                "the derived run's budget account is not the fork's own",
                reasons=("budget_account_mismatch",),
            )
        return ForkAdmission(
            request_id=request.request_id,
            target_epoch=ExecutionEpochKey(
                request_scope=scope,
                belllabs_run_id=decision.run_id,
                execution_epoch=DERIVED_EXECUTION_EPOCH,
            ),
            admission_ref=f"admission:{scope}:{target.idempotency_issuer}:{target.request_id}",
            budget_reservation_ref=f"budget-account:{budget.account_id}",
            admitted_effective_configuration_digest=projection.effective_configuration_digest,
        )


# --- Materialization: lineage and reuse decisions, nothing copied --------------------------


@dataclass(frozen=True)
class ForkOfRun:
    fork_request_id: str
    materialized: bool


class ForkLineageReader(Protocol):
    async def lineage_of_run(
        self, request_scope: str, run_id: str
    ) -> tuple[ForkLineageManifest, ...]: ...


class ForkMaterializationStore(Protocol):
    async def record_materialization(
        self,
        request: RunForkRequest,
        lineage: ForkLineageManifest,
        execution_lineage: PersistedExecutionLineage,
    ) -> ForkLineageManifest: ...

    async def get_materialization(
        self, request_scope: str, request_id: str
    ) -> ForkLineageManifest | None: ...

    async def fork_of_run(self, request_scope: str, derived_run_id: str) -> ForkOfRun | None: ...

    async def fork_marker(self, request_scope: str, run_id: str) -> str | None:
        """The fork request id a run's immutable admission transition names, if any."""
        ...

    async def get_reuse_decision(
        self, request_scope: str, derived_run_id: str, derived_unit_key: str
    ) -> ForkReuseDecision | None: ...

    async def list_reuse_decisions(
        self, request_scope: str, request_id: str
    ) -> tuple[ForkReuseDecision, ...]: ...


class TransitionReader(Protocol):
    async def list_transitions(self, request_scope: str, run_id: str) -> Sequence[Any]: ...


def fork_marker_of(evidence_refs: Sequence[str]) -> str | None:
    return next(
        (
            ref.removeprefix(FORK_REQUEST_MARKER_PREFIX)
            for ref in evidence_refs
            if ref.startswith(FORK_REQUEST_MARKER_PREFIX)
        ),
        None,
    )


class InMemoryForkMaterializationStore:
    def __init__(
        self,
        lineage: ExecutionLineageRepository | None = None,
        *,
        transitions: TransitionReader | None = None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._lineage = lineage
        self._transitions = transitions
        self.requests: dict[tuple[str, str], RunForkRequest] = {}
        self.materializations: dict[tuple[str, str], ForkLineageManifest] = {}
        self.decisions: dict[tuple[str, str, str], ForkReuseDecision] = {}

    def register_request(self, request: RunForkRequest) -> None:
        """Mirror of the fork reservation (the PostgreSQL store reads the same row)."""

        key = (request.request_scope, request.request_id)
        prior = self.requests.get(key)
        if prior is not None and fork_request_fingerprint(prior) != fork_request_fingerprint(
            request
        ):
            raise ValueError("fork request identity conflict")
        self.requests.setdefault(key, deepcopy(request))

    async def record_materialization(
        self,
        request: RunForkRequest,
        lineage: ForkLineageManifest,
        execution_lineage: PersistedExecutionLineage,
    ) -> ForkLineageManifest:
        key = (request.request_scope, request.request_id)
        async with self._lock:
            self.register_request(request)
            prior = self.materializations.get(key)
            if prior is not None:
                if prior != lineage:
                    raise ValueError("fork materialization conflicts with the recorded one")
                return deepcopy(prior)
            if self._lineage is not None:
                await self._lineage.append(execution_lineage)
            for decision in request.reuse_decisions:
                self.decisions[
                    (request.request_scope, decision.derived_run_id, decision.derived_unit_key)
                ] = deepcopy(decision)
            self.materializations[key] = deepcopy(lineage)
            return deepcopy(lineage)

    async def get_materialization(
        self, request_scope: str, request_id: str
    ) -> ForkLineageManifest | None:
        return deepcopy(self.materializations.get((request_scope, request_id)))

    async def lineage_of_run(
        self, request_scope: str, run_id: str
    ) -> tuple[ForkLineageManifest, ...]:
        """FT-F4: materialized forks a run is the source or the target of."""

        return tuple(
            deepcopy(item)
            for (scope, _), item in sorted(self.materializations.items())
            if scope == request_scope and run_id in {item.source_run_id, item.derived_run_id}
        )

    async def fork_of_run(self, request_scope: str, derived_run_id: str) -> ForkOfRun | None:
        request = next(
            (
                item
                for (scope, _), item in self.requests.items()
                if scope == request_scope and item.derived_run_id == derived_run_id
            ),
            None,
        )
        if request is None:
            return None
        return ForkOfRun(
            fork_request_id=request.request_id,
            materialized=(request_scope, request.request_id) in self.materializations,
        )

    async def get_reuse_decision(
        self, request_scope: str, derived_run_id: str, derived_unit_key: str
    ) -> ForkReuseDecision | None:
        return deepcopy(self.decisions.get((request_scope, derived_run_id, derived_unit_key)))

    async def fork_marker(self, request_scope: str, run_id: str) -> str | None:
        if self._transitions is None:
            return None
        transitions = await self._transitions.list_transitions(request_scope, run_id)
        return fork_marker_of(transitions[0].evidence_refs) if transitions else None

    async def list_reuse_decisions(
        self, request_scope: str, request_id: str
    ) -> tuple[ForkReuseDecision, ...]:
        return tuple(
            sorted(
                (
                    deepcopy(item)
                    for (scope, _, _), item in self.decisions.items()
                    if scope == request_scope and item.fork_request_id == request_id
                ),
                key=lambda item: item.derived_unit_key,
            )
        )


def fork_execution_lineage(
    request: RunForkRequest, lineage: ForkLineageManifest, *, retain_until: datetime
) -> PersistedExecutionLineage:
    """The fork as an immutable lineage-journal record (kernel kinds and relationships).

    Edges: the derived run is `derived_from` the snapshot, which the source run `contains`;
    the derived run `reuses` each reused result manifest. There is no graph assembly for a
    fork; the envelope anchors to the source snapshot digest instead.
    """

    scope = request.request_scope

    def record(
        kind: LineageKind, identity: str, digest: str, manifest_ref: str | None = None
    ) -> ProviderQualifiedLineageRecord:
        return ProviderQualifiedLineageRecord(
            kind=kind,
            provider=FORK_LINEAGE_PROVIDER,
            provider_identity=identity,
            request_scope=scope,
            canonical_digest=digest,
            manifest_ref=manifest_ref,
        )

    derived = record(
        LineageKind.BELL_LABS_RUN,
        request.derived_run_id,
        sha256_digest({"run_id": request.derived_run_id, "execution_epoch": 1}),
    )
    source = record(
        LineageKind.BELL_LABS_RUN,
        request.source_run_id,
        sha256_digest(
            {"run_id": request.source_run_id, "execution_epoch": request.source_execution_epoch}
        ),
    )
    snapshot = record(
        LineageKind.RUN_SNAPSHOT,
        request.snapshot_id,
        request.snapshot_digest,
        manifest_ref=request.snapshot_id,
    )
    identities: list[ProviderQualifiedLineageRecord] = [derived, source, snapshot]
    edges: list[LineageParentEdge] = [
        LineageParentEdge(child=derived, parent=snapshot, relationship="derived_from"),
        LineageParentEdge(child=snapshot, parent=source, relationship="contains"),
    ]
    for decision in request.reuse_decisions:
        if decision.decision != "reuse" or decision.candidate is None:
            continue
        reused = record(
            LineageKind.RESULT_MANIFEST,
            decision.candidate.result_manifest_ref,
            decision.candidate.result_manifest_digest,
            manifest_ref=decision.candidate.result_manifest_ref,
        )
        if reused.canonical_key in {item.canonical_key for item in identities}:
            continue
        identities.append(reused)
        edges.append(LineageParentEdge(child=derived, parent=reused, relationship="reuses"))
    return PersistedExecutionLineage.create(
        lineage_id=f"fork-lineage:{request.request_id}",
        envelope=ExecutionLineageEnvelope(
            request_scope=scope,
            belllabs_run_id=request.derived_run_id,
            execution_epoch=DERIVED_EXECUTION_EPOCH,
            workflow_implementation_ref=FORK_WORKFLOW_IMPLEMENTATION_REF,
            graph_assembly_digest=request.snapshot_digest,
            workflow_cycle=0,
            input_manifest_digest=request.target.input_manifest.digest,
            evidence_refs=(
                f"{request.snapshot_id}@{request.snapshot_digest}",
                f"fork-patch:{request.patch.patch_digest}",
                f"fork-lineage:{lineage.lineage_digest}",
            ),
        ),
        qualified_identities=tuple(identities),
        parent_edges=tuple(edges),
        recorded_at=request.requested_at,
        retain_until=retain_until,
    )


class RecordingForkMaterializer:
    """Materialize a fork as recorded lineage and reuse decisions (no provider copy)."""

    def __init__(
        self,
        store: ForkMaterializationStore,
        *,
        retention: Callable[[datetime], datetime],
    ) -> None:
        self._store = store
        self._retention = retention

    async def materialize(
        self, request: RunForkRequest, admission: ForkAdmission
    ) -> ForkMaterialization:
        lineage = lineage_for(request, admission_ref=admission.admission_ref)
        recorded = await self._store.record_materialization(
            request,
            lineage,
            fork_execution_lineage(
                request, lineage, retain_until=self._retention(request.requested_at)
            ),
        )
        return ForkMaterialization(
            request_id=request.request_id,
            target_run_id=admission.target_epoch.belllabs_run_id,
            lineage=recorded,
        )

    async def reconcile_materialization(
        self, request: RunForkRequest, admission: ForkAdmission
    ) -> ForkMaterializationObservation:
        recorded = await self._store.get_materialization(request.request_scope, request.request_id)
        if recorded is None:
            return ForkMaterializationObservation(status="definitively_missing")
        return ForkMaterializationObservation(
            status="materialized",
            materialization=ForkMaterialization(
                request_id=request.request_id,
                target_run_id=admission.target_epoch.belllabs_run_id,
                lineage=recorded,
            ),
        )


# --- Reuse in the derived run ---------------------------------------------------------------


class ResultPayloadReader(Protocol):
    async def retrieve(self, address: ArtifactPayloadAddress) -> bytes: ...


class SourceBindingReader(Protocol):
    async def get_binding_by_id(
        self, binding_id: str, *, request_scope: str
    ) -> OperationExecutionBinding | None: ...


@dataclass(frozen=True)
class ReusedResult:
    decision: ForkReuseDecision
    source_settlement: OperationSettlement

    @property
    def ref(self) -> ReusedResultRef:
        candidate = self.decision.candidate
        assert candidate is not None
        return ReusedResultRef(
            fork_request_id=self.decision.fork_request_id,
            source_run_id=self.decision.source_run_id,
            source_unit_key=self.decision.source_unit_key,
            source_settlement_id=candidate.settlement_id,
            source_result_manifest_ref=candidate.result_manifest_ref,
            source_result_manifest_digest=candidate.result_manifest_digest,
        )


_RUN_SCOPED_BINDING_FIELDS = frozenset(
    {
        "binding_id",
        "semantic_attempt_key",
        "request_fingerprint",
        "run_id",
        "prior_binding_id",
        "run_control_revision",
        "budget_reservation_id",
        "side_effect_key",
        "bound_at",
        "runtime_unit",
    }
)
_RUN_SCOPED_DEEP_FIELDS = frozenset(
    {
        "binding_id",
        "binding_digest",
        "run_id",
        "control_revision",
        "reservation_id",
        "runtime_unit",
        "cognitive_session_namespace",
    }
)


def reuse_compatibility_digest(binding: OperationExecutionBinding) -> str:
    """Digest of a binding's run-independent content (REQ-CP-EXEC-012 compatibility).

    Run-scoped identities (run, binding and reservation IDs, revisions, unit identity,
    cognitive namespace, timestamps, and the digests that cover them) are removed, and the
    run ID inside the remaining text (workspace and namespace paths) is replaced by a
    placeholder. Two units are compatible exactly when everything else (prompt sources,
    model, tools, skills, MCP, schemas, capability grant, budget limits, ERC) is equal.
    """

    content = stable_json_dump(binding, exclude={*_RUN_SCOPED_BINDING_FIELDS, "lane_binding"})
    _drop_derived_context_files(content.get("workspace"))
    # Residual payload reader (OC-R2): only the Deep Agents bytes carry run-scoped fields, which
    # compatibility must strip; any other lane's sealed binding is run-independent by digest.
    deep_binding = DeepAgentExecutionBinding.carried_by(binding)
    deep = stable_json_dump(deep_binding) if deep_binding is not None else None
    if deep is not None:
        content["lane_binding_content"] = deep
    elif binding.lane_binding is not None:
        content["lane_binding"] = binding.lane_binding.digest
    if isinstance(deep, dict):
        for name in _RUN_SCOPED_DEEP_FIELDS:
            deep.pop(name, None)
    if isinstance(deep, dict):
        _drop_derived_context_files(deep.get("workspace"))
    unit = binding.runtime_unit
    if unit is not None and unit.family == "goal_directed":
        # 1.4.4 (P5.4, option B): a Goal Directed unit reused by iteration runs under the
        # revision id the fork minted for the derived run, and the Context Packet's digest
        # covers that identity (`goal_revision_digest` is a protected packet fact). The
        # packet segment is therefore compared by its presence and trust class, not its
        # digest; a patched objective invalidates every iteration before this rule applies.
        # The read mounts of a reused verifier are the reused executor's output as this run
        # materialized it (a run-scoped workspace reference), so they are compared by shape.
        _neutralize_context_packet_sources(content.get("prompt_sources"))
        _neutralize_read_mounts(content.get("workspace"))
        if isinstance(deep, dict):
            _neutralize_read_mounts(deep.get("workspace"))
    return sha256_digest(_replace_text(content, binding.run_id, "{run_id}"))


def _neutralize_read_mounts(workspace: Any) -> None:
    mounts = workspace.get("read_mounts") if isinstance(workspace, dict) else None
    if not isinstance(mounts, list):
        return
    for mount in mounts:
        if isinstance(mount, dict):
            for name in ("content_digest", "durable_ref"):
                if name in mount:
                    mount[name] = "{reused_output}"


def _neutralize_context_packet_sources(sources: Any) -> None:
    if not isinstance(sources, list):
        return
    for source in sources:
        if (
            isinstance(source, list)
            and len(source) == 4
            and isinstance(source[0], str)
            and source[0].startswith("context-packet:")
        ):
            source[0] = "context-packet:{goal_revision}"
            source[3] = "{goal_revision}"


MISSION_FILE_SLOT_NAMES_SET = frozenset(MISSION_FILE_SLOT_NAMES.values())


def _drop_derived_context_files(workspace: Any) -> None:
    """FT-B2: the `.mission/` files are a pure rendering of the Context Packet, whose
    run-relative digest is already compared through its prompt segment; their content
    addresses embed the run id inside a hash, so they are not compared themselves."""

    if not isinstance(workspace, dict):
        return
    slots = workspace.get("slot_bindings")
    if isinstance(slots, list):
        workspace["slot_bindings"] = [
            slot
            for slot in slots
            if not (isinstance(slot, dict) and slot.get("slot_name") in MISSION_FILE_SLOT_NAMES_SET)
        ]


def _replace_text(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, dict):
        return {key: _replace_text(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_text(item, old, new) for item in value]
    return value


class ForkReuseOracle:
    """FT-F4: the fork's recorded reuse decision for a derived unit (mailbox delivery skips a
    unit settled by reference, so queued content reaches the first executed turn)."""

    def __init__(self, store: ForkMaterializationStore) -> None:
        self._store = store

    async def reused(self, request_scope: str, run_id: str, unit_key: str) -> bool:
        decision = await self._store.get_reuse_decision(request_scope, run_id, unit_key)
        return decision is not None and decision.decision == "reuse"


class ForkReuseResolver:
    """The derived run's reuse port: an immutable source result, or fresh execution.

    Fails closed: an unmaterialized fork, an incompatible binding or state schema, or a
    manifest that does not match its recorded digest never falls back to re-execution.
    """

    def __init__(
        self,
        store: ForkMaterializationStore,
        *,
        results: ResultPayloadReader,
        bindings: SourceBindingReader,
    ) -> None:
        self._store = store
        self._results = results
        self._bindings = bindings

    async def reused_result(self, binding: OperationExecutionBinding) -> ReusedResult | None:
        unit = binding.runtime_unit
        if unit is None:
            return None
        fork = await self._store.fork_of_run(binding.request_scope, unit.belllabs_run_id)
        if fork is None:
            # A fork-derived run whose fork row (and with it its reuse decisions) is missing,
            # for example purged, fails closed instead of silently re-executing everything.
            marker = await self._store.fork_marker(binding.request_scope, unit.belllabs_run_id)
            if marker is not None:
                raise ForkRejected(
                    "fork_lineage_missing",
                    "the run was admitted by a fork whose lineage and decisions are missing",
                    reasons=(marker,),
                )
            return None
        if not fork.materialized:
            raise ForkRejected(
                "fork_not_materialized",
                "a fork-derived run cannot execute before its fork is materialized",
            )
        decision = await self._store.get_reuse_decision(
            binding.request_scope, unit.belllabs_run_id, unit.unit_key
        )
        if decision is None or decision.decision != "reuse" or decision.candidate is None:
            return None
        candidate = decision.candidate
        if decision.derived_unit != unit:
            raise ForkRejected("incompatible_restore", "the reuse decision is another unit's")
        deep = DeepAgentExecutionBinding.carried_by(binding)
        state_schema = deep.cognitive_state_schema.schema_digest if deep is not None else None
        if state_schema != candidate.state_schema_digest:
            raise ForkRejected(
                "incompatible_restore",
                "the derived unit's cognitive state schema differs from the reused result's",
            )
        source_binding = await self._bindings.get_binding_by_id(
            candidate.binding_id, request_scope=binding.request_scope
        )
        if source_binding is None or reuse_compatibility_digest(
            source_binding
        ) != reuse_compatibility_digest(binding):
            raise ForkRejected(
                "incompatible_restore",
                "the derived unit's binding is not the reused result's (patch frontier drift)",
            )
        manifest = await self._results.retrieve(
            ArtifactPayloadAddress(
                object_ref=candidate.result_manifest_ref,
                content_digest=candidate.result_manifest_digest,
                size_bytes=candidate.result_manifest_size_bytes,
            )
        )
        settlement = OperationSettlement.model_validate_json(manifest)
        if (
            settlement.binding_id != candidate.binding_id
            or settlement.settlement_id != candidate.settlement_id
            or settlement.status != "completed"
        ):
            raise ForkRejected(
                "incompatible_restore", "the reused manifest is not the recorded settlement"
            )
        if settlement.output_payload_ref is not None:
            assert settlement.output_payload_digest is not None
            assert settlement.output_payload_size_bytes is not None
            payload = json.loads(
                await self._results.retrieve(
                    ArtifactPayloadAddress(
                        object_ref=settlement.output_payload_ref,
                        content_digest=settlement.output_payload_digest,
                        size_bytes=settlement.output_payload_size_bytes,
                    )
                )
            )
            settlement = settlement.model_copy(
                update={
                    "output_text": payload["output_text"],
                    "structured_output": payload["structured_output"],
                }
            )
        return ReusedResult(decision=decision, source_settlement=settlement)

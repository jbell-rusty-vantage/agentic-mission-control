"""Recursive composition use cases: activate, settle and control nested bodies (OVE-176).

``NestedProgramService`` is the one application seam a parent family calls (through the
``nested_program.*`` activities) for a unit whose body is itself a family program:

- ``activate`` admits the body's child run (a run of the same mission revision, admitted under
  the parent's lineage with a budget contained in the parent unit's reservation) and returns its
  root input. Idempotent per parent unit attempt: a restart or a redelivered activity returns the
  recorded activation, never a second child.
- ``settle`` turns the child's end into the exact export receipt (only declared exports, only
  accepted revisions), adopts each accepted export the parent promises into the parent unit's
  named obligation (``NestedExportAdoption``: a submission the parent's own assessment and
  fulfillment decide, never an approval), settles the parent unit's reservation against the
  child's actual spend (capped at its admitted ceiling, reported the same way everywhere) and
  closes a child run that was admitted but never started.
- ``propagate`` delivers a parent cancel/pause/resume to the child through the child's own run
  control, so the child's family runs its own saga (never a raw Temporal cancel).

Ports keep I/O out: the launcher (compile + admission + launch-input authoring), the accepted
outputs of a run, the child's run control and the activation lineage store. Swarm members
(WI-14) and Evaluator Optimizer rounds (WI-15) reuse this service with their own host ids.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

from mission_control.application.execution.service import RunControlService
from mission_control.application.programs.service import orchestration_lifecycle_actor
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    LifecycleCommand,
    RecordUsageAction,
    RunPhase,
)
from mission_control.domain.programs.contracts import BellLabsRunInput
from mission_control.domain.programs.nested import (
    NestedActivation,
    NestedActivationRequest,
    NestedControlReceipt,
    NestedControlRequest,
    NestedProjection,
    NestedSettlement,
    NestedSettlementRequest,
    capped_usage,
    child_terminal,
    project_exports,
    uncontained,
)

SETTLEMENT_ATTEMPTS = 4


class NestedLaunchRefused(Exception):
    """The launcher refused the body (typed ``code``); nothing was admitted."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class NestedLaunch:
    child_run_id: str
    child_root: BellLabsRunInput
    budget_ceiling: dict[str, int]


class NestedRunLauncher(Protocol):
    """Derive the body from the parent's committed definition, verify its sealed digests,
    compile it, admit the child run (parent lineage, contained budget) and author its root
    input. Idempotent in ``request.request_id``."""

    async def launch(self, request: NestedActivationRequest) -> NestedLaunch: ...


class NestedOutputs(Protocol):
    async def accepted(self, scope: str, run_id: str) -> dict[str, tuple[str, ...]] | None:
        """The run's accepted output refs by obligation key; ``None`` when the run registered
        no named promises (its family's accepted results are then the export basis)."""
        ...


class NestedControls(Protocol):
    async def command(self, request: NestedControlRequest) -> NestedControlReceipt: ...


class NestedAdoptionRefused(Exception):
    """The parent refused an adopted export (typed ``code``): the composite is not accepted."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class NestedExportAdoption(Protocol):
    """Adopt each accepted export with an ``adopt_into`` obligation into the hosting parent
    unit's invocation (exact revision and digest; idempotent); returns the parent revisions."""

    async def adopt(
        self, request: NestedSettlementRequest, projection: NestedProjection
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class NestedActivationRecord:
    """Durable lineage of one nested activation (``mission_control.nested_activation``)."""

    request_scope: str
    parent_run_id: str
    host_id: str
    semantic_attempt_id: str
    position: str
    family: str
    depth: int
    child_run_id: str
    budget_ceiling: dict[str, int]
    body_digest: str
    activated_at: datetime
    receipt: dict[str, object] | None = None
    settled_at: datetime | None = None


class NestedActivationStore(Protocol):
    async def get(
        self, scope: str, parent_run_id: str, host_id: str, semantic_attempt_id: str
    ) -> NestedActivationRecord | None: ...

    async def record(self, record: NestedActivationRecord) -> NestedActivationRecord: ...

    async def settle(
        self,
        scope: str,
        child_run_id: str,
        receipt: dict[str, object],
        settled_at: datetime,
    ) -> NestedActivationRecord: ...

    async def for_parent(
        self, scope: str, parent_run_id: str
    ) -> tuple[NestedActivationRecord, ...]: ...

    async def by_child(self, scope: str, child_run_id: str) -> NestedActivationRecord | None: ...


class NestedActivationConflict(ValueError):
    """A recorded activation differs from the one presented (never overwritten)."""


class InMemoryNestedActivationStore:
    """Conformance store with the same write-once and settle-once rules as PostgreSQL."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rows: dict[tuple[str, str, str, str], NestedActivationRecord] = {}

    async def get(
        self, scope: str, parent_run_id: str, host_id: str, semantic_attempt_id: str
    ) -> NestedActivationRecord | None:
        return self._rows.get((scope, parent_run_id, host_id, semantic_attempt_id))

    async def record(self, record: NestedActivationRecord) -> NestedActivationRecord:
        key = (
            record.request_scope,
            record.parent_run_id,
            record.host_id,
            record.semantic_attempt_id,
        )
        async with self._lock:
            prior = self._rows.get(key)
            if prior is not None:
                if prior.child_run_id != record.child_run_id or prior.body_digest != (
                    record.body_digest
                ):
                    raise NestedActivationConflict("the unit attempt activated another child")
                return prior
            self._rows[key] = record
            return record

    async def settle(
        self,
        scope: str,
        child_run_id: str,
        receipt: dict[str, object],
        settled_at: datetime,
    ) -> NestedActivationRecord:
        async with self._lock:
            for key, row in self._rows.items():
                if row.request_scope == scope and row.child_run_id == child_run_id:
                    if row.receipt is not None:
                        if row.receipt.get("receipt_digest") != receipt.get("receipt_digest"):
                            raise NestedActivationConflict("the activation settled differently")
                        return row
                    settled = replace(row, receipt=receipt, settled_at=settled_at)
                    self._rows[key] = settled
                    return settled
        raise LookupError(f"no nested activation for child run {child_run_id}")

    async def for_parent(
        self, scope: str, parent_run_id: str
    ) -> tuple[NestedActivationRecord, ...]:
        return tuple(
            row
            for row in self._rows.values()
            if row.request_scope == scope and row.parent_run_id == parent_run_id
        )

    async def by_child(self, scope: str, child_run_id: str) -> NestedActivationRecord | None:
        return next(
            (
                row
                for row in self._rows.values()
                if row.request_scope == scope and row.child_run_id == child_run_id
            ),
            None,
        )


class NestedProgramService:
    def __init__(
        self,
        *,
        run_control: RunControlService,
        launcher: NestedRunLauncher | None,
        outputs: NestedOutputs | None,
        controls: NestedControls | None,
        activations: NestedActivationStore,
        adoption: NestedExportAdoption | None = None,
        idempotency_issuer: str = "nested-program",
    ) -> None:
        self._adoption = adoption
        self._run_control = run_control
        self._launcher = launcher
        self._outputs = outputs
        self._controls = controls
        self._activations = activations
        self._issuer = idempotency_issuer

    async def activate(self, request: NestedActivationRequest) -> NestedActivation:
        body = request.body
        prior = await self._activations.get(
            request.request_scope,
            request.parent_run_id,
            request.host_id,
            request.semantic_attempt_id,
        )
        if body.host_id != request.host_id:
            return _refused("nested_host_mismatch", "the body is hosted by another unit")
        if body.depth > body.max_depth:
            return _refused("nested_depth_exceeded", f"depth {body.depth} > {body.max_depth}")
        if prior is None:
            parent = await self._run_control.get_run(request.request_scope, request.parent_run_id)
            if parent.phase in {RunPhase.CANCELLING, RunPhase.TERMINAL}:
                return _refused("parent_not_running", f"the parent run is {parent.phase.value}")
        if self._launcher is None:
            return _refused(
                "nested_execution_unavailable",
                "this installation composes no nested-body launcher; the body is not "
                "flattened into its parent",
            )
        try:
            launched = await self._launcher.launch(request)
        except NestedLaunchRefused as error:
            return _refused(error.code, error.detail)
        spill = uncontained(request.parent_reservation, launched.budget_ceiling)
        if spill:
            # Containment is the launcher's contract; never trust it silently: the child may
            # not spend on a dimension the unit did not reserve, nor more than it reserved.
            return _refused(
                "nested_budget_uncontained",
                f"the child budget exceeds the unit reservation on {list(spill)}",
            )
        record = await self._activations.record(
            NestedActivationRecord(
                request_scope=request.request_scope,
                parent_run_id=request.parent_run_id,
                host_id=request.host_id,
                semantic_attempt_id=request.semantic_attempt_id,
                position=body.position,
                family=body.family,
                depth=body.depth,
                child_run_id=launched.child_run_id,
                budget_ceiling=dict(launched.budget_ceiling),
                body_digest=sha256_digest(body),
                activated_at=request.occurred_at if prior is None else prior.activated_at,
            )
        )
        return NestedActivation(
            activated=True,
            child_run_id=record.child_run_id,
            child_root=launched.child_root,
            budget_ceiling=dict(record.budget_ceiling),
        )

    async def settle(self, request: NestedSettlementRequest) -> NestedSettlement:
        terminal = child_terminal(
            request.body.family, request.end, request.family_result, cause=request.cause
        )
        admitted = bool(request.child_run_id)
        ran = admitted and request.child_started
        record = (
            await self._activations.by_child(request.request_scope, request.child_run_id)
            if admitted
            else None
        )
        if record is not None and record.receipt is not None:
            # Redelivered: the receipt was recorded once; settle the reservation from it.
            projection = _projection_of(request, record.receipt)
        else:
            accepted = (
                await self._outputs.accepted(request.request_scope, request.child_run_id)
                if self._outputs is not None and ran
                else None
            )
            consumed = (
                (
                    await self._run_control.get_budget(request.request_scope, request.child_run_id)
                ).consumed
                if admitted
                else {}
            )
            ceiling = record.budget_ceiling if record is not None else {}
            projection = project_exports(
                request.body,
                request.child_run_id,
                terminal,
                accepted if ran else {},
                actual_usage=capped_usage(consumed, ceiling),
            )
            projection = await self._adopt(request, projection)
        version, reason = await self._settle_reservation(request, projection.actual_usage)
        if admitted and not request.child_started:
            await self._close_unstarted(request)
        if record is not None and record.receipt is None:
            await self._activations.settle(
                request.request_scope,
                request.child_run_id,
                projection.receipt(),
                request.occurred_at,
            )
        return NestedSettlement(
            projection=projection, settled_run_version=version, reason_code=reason
        )

    async def _adopt(
        self, request: NestedSettlementRequest, projection: NestedProjection
    ) -> NestedProjection:
        """An accepted composite's exports the parent promises become parent submissions; a
        refused adoption leaves the composite not accepted (its receipt says why)."""

        wanted = {item.output for item in request.body.exports if item.adopt_into}
        if (
            not projection.composite_accepted
            or self._adoption is None
            or not any(item.output in wanted for item in projection.exports)
        ):
            return projection
        try:
            adopted = await self._adoption.adopt(request, projection)
        except NestedAdoptionRefused as error:
            return replace(
                projection,
                outcome="not_accepted",
                composite_accepted=False,
                exports=(),
                cause=f"adoption_refused:{error.code}",
            )
        return replace(projection, adopted=adopted)

    async def _close_unstarted(self, request: NestedSettlementRequest) -> None:
        """A child admitted but never started (cancelled first) is cancelled in its own run
        control, so no admitted run is left pending (idempotent)."""

        child = await self._run_control.get_run(request.request_scope, request.child_run_id)
        if child.phase in {RunPhase.CANCELLING, RunPhase.TERMINAL}:
            return
        await self._run_control.execute(
            LifecycleCommand(
                command_id=f"nested:{request.child_run_id}:never-started",
                idempotency_issuer=self._issuer,
                request_scope=request.request_scope,
                run_id=request.child_run_id,
                expected_run_version=child.version,
                actor=orchestration_lifecycle_actor(),
                action=CancelAction(),
                reason="the parent cancelled the nested body before its child run started",
                occurred_at=request.occurred_at,
                correlation_id=request.correlation_id or request.child_run_id,
            )
        )

    async def propagate(self, request: NestedControlRequest) -> NestedControlReceipt:
        if self._controls is None:
            return NestedControlReceipt(False, reason_code="nested_controls_unavailable")
        child = await self._run_control.get_run(request.request_scope, request.child_run_id)
        if child.phase == RunPhase.TERMINAL:
            return NestedControlReceipt(False, status="child_terminal")
        if request.kind == "cancel" and child.phase == RunPhase.CANCELLING:
            return NestedControlReceipt(True, status="already_cancelling")
        return await self._controls.command(request)

    async def _settle_reservation(
        self, request: NestedSettlementRequest, usage: Mapping[str, int]
    ) -> tuple[int, str]:
        """Settle the parent unit's reservation: the child's charged spend as the unit's usage,
        the unused reservation released (idempotent)."""

        for attempt in range(SETTLEMENT_ATTEMPTS):
            budget = await self._run_control.get_budget(
                request.request_scope, request.parent_run_id
            )
            run = await self._run_control.get_run(request.request_scope, request.parent_run_id)
            remaining = {
                name: amount
                for name, amount in budget.reservations.get(
                    request.parent_reservation_id, {}
                ).items()
                if amount > 0
            }
            if request.parent_reservation_id not in budget.reservations:
                return run.version, ""
            # The child's whole charged spend is the unit's usage (S4: nothing it spent goes
            # uncharged; a bounded dimension never exceeds its reservation, by containment).
            actual = {name: amount for name, amount in usage.items() if amount > 0}
            result = await self._run_control.execute(
                LifecycleCommand(
                    command_id=(
                        f"nested:{request.parent_reservation_id}:settlement"
                        if attempt == 0
                        else f"nested:{request.parent_reservation_id}:settlement:"
                        f"at-version:{run.version}"
                    ),
                    idempotency_issuer=self._issuer,
                    request_scope=request.request_scope,
                    run_id=request.parent_run_id,
                    expected_run_version=run.version,
                    actor=orchestration_lifecycle_actor(),
                    action=RecordUsageAction(
                        usage_id=f"nested-usage:{request.parent_reservation_id}",
                        actual_amounts=actual,
                        reservation_id=request.parent_reservation_id,
                        release_amounts={
                            name: amount - actual.get(name, 0)
                            for name, amount in remaining.items()
                            if amount > actual.get(name, 0)
                        },
                    ),
                    reason=f"Settle the nested body at {request.body.position}",
                    evidence_refs=(f"nested-run:{request.child_run_id}",),
                    occurred_at=request.occurred_at,
                    correlation_id=(
                        request.correlation_id
                        or request.child_run_id
                        or f"nested:{request.parent_run_id}:{request.host_id}"
                    ),
                )
            )
            if result.status != CommandStatus.STALE:
                return result.resulting_run_version, (
                    "" if result.status == CommandStatus.ACCEPTED else result.reason_code
                )
        raise RuntimeError("nested reservation settlement is stale; retrying")


def _refused(code: str, detail: str) -> NestedActivation:
    return NestedActivation(activated=False, reason_code=code, detail=detail)


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list | tuple) else ()


def _projection_of(request: NestedSettlementRequest, receipt: Mapping[str, object]) -> Any:
    """The recorded receipt as a projection (a redelivered settlement never recomputes)."""

    from mission_control.domain.programs.nested import ExportedOutput

    def exported(items: object) -> tuple[ExportedOutput, ...]:
        rows = items if isinstance(items, list) else []
        return tuple(
            ExportedOutput(
                output=str(row["output"]),
                source=str(row["source"]),
                timing="early" if row.get("timing") == "early" else "final",
                refs=tuple(str(ref) for ref in row.get("refs") or ()),
            )
            for row in rows
            if isinstance(row, dict)
        )

    usage = receipt.get("actual_usage")
    return NestedProjection(
        child_run_id=str(receipt.get("child_run_id", request.child_run_id)),
        position=str(receipt.get("position", request.body.position)),
        outcome=receipt.get("outcome", "execution_failed"),  # type: ignore[arg-type]
        composite_accepted=bool(receipt.get("composite_accepted")),
        exports=exported(receipt.get("exports")),
        early_exports=exported(receipt.get("early_exports")),
        missing_required=_strings(receipt.get("missing_required")),
        actual_usage=(
            {str(k): int(v) for k, v in usage.items()} if isinstance(usage, dict) else {}
        ),
        cause=str(receipt.get("cause", "")),
        adopted=_strings(receipt.get("adopted")),
    )


__all__ = [
    "InMemoryNestedActivationStore",
    "NestedActivationConflict",
    "NestedActivationRecord",
    "NestedActivationStore",
    "NestedAdoptionRefused",
    "NestedControls",
    "NestedExportAdoption",
    "NestedLaunch",
    "NestedLaunchRefused",
    "NestedOutputs",
    "NestedProgramService",
    "NestedRunLauncher",
]

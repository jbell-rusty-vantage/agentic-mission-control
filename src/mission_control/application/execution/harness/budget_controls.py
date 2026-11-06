"""Durable budget intents executed only by the current session owner.

An intent is committed before POST. A lost response (including process death before
the call) is reconciled by GET only: the provider has no idempotency/CAS primitive.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from mission_control.application.execution.approvals import ApprovalContextProbe
from mission_control.application.execution.harness.dispatch import SessionOwner
from mission_control.application.execution.stop_fence import StopFenceRepository
from mission_control.application.resolution.registries import lane_profile_for
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.budget_controls import (
    BudgetControlRecord,
    LaneBudgetControlRequest,
    ManagedBudgetSnapshot,
    budget_control_key,
)
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.policies.contracts import (
    BoundaryCommandRecord,
    PauseAction,
    ResumeAction,
)
from mission_control.domain.policies.stop_fence import EffectAdmission

if TYPE_CHECKING:
    from mission_control.application.execution.harness.state import LaneExecutionStateStore


@runtime_checkable
class BudgetControlAuthority(Protocol):
    async def verify_budget_control(
        self, request: LaneBudgetControlRequest
    ) -> BoundaryCommandRecord: ...


@runtime_checkable
class ManagedBudgetProvider(Protocol):
    async def read_budget(self, native_session_ref: str) -> ManagedBudgetSnapshot: ...

    async def set_budget(self, native_session_ref: str, cap_minor_units: int) -> None: ...


def held(records: dict[str, BudgetControlRecord]) -> bool:
    """Unresolved intents also prevent new sends and retain cleanup liability."""

    return bool(_active_holds(records))


def _active_holds(records: dict[str, BudgetControlRecord]) -> set[str]:

    latest = sorted(records.values(), key=lambda r: r.command_sequence)
    active: set[str] = set()
    for record in latest:
        if record.action == "hold" and record.phase != "rejected":
            active.add(record.key)
        elif record.action == "resume" and record.applied:
            active.discard(record.hold_key or "")
    return active


class BudgetControlService:
    def __init__(
        self,
        *,
        states: LaneExecutionStateStore,
        authority: BudgetControlAuthority,
        approvals: ApprovalContextProbe,
        fences: StopFenceRepository,
    ) -> None:
        self.states, self.authority, self.approvals, self.fences = (
            states,
            authority,
            approvals,
            fences,
        )
        self._locks: dict[str, asyncio.Lock] = {}

    async def enqueue(
        self, request: LaneBudgetControlRequest, heid: object, now: datetime
    ) -> BudgetControlRecord:
        from uuid import UUID

        identity = UUID(str(heid))
        operation = request.operation
        state = await self.states.load(operation.request_scope, identity)
        if state is None or state.owner is None or state.native_session_ref is None:
            raise ValueError("budget control requires an existing owned native session")
        command = await self.authority.verify_budget_control(request)
        seal = await self.approvals.current(
            operation.request_scope,
            run_id=operation.identity.run_id,
            harness_execution_id=str(identity),
        )
        if (
            not seal.granted
            or seal.generation != request.generation
            or state.owner.generation != request.generation
        ):
            raise ValueError("budget control approval/generation is stale")
        binding = ProviderExecutionBinding.carried_by(operation)
        ceiling = binding.budget_gate_ceiling() if binding is not None else None
        if (
            binding is None
            or ceiling is None
            or not binding.lane_dispatch().declares("budget_gate")
        ):
            raise ValueError("budget gate supports only a lane that declares it")
        action = command.action
        if not isinstance(action, (PauseAction, ResumeAction)):
            raise ValueError("budget gate requires an accepted pause or resume")
        gate = action.decision.budget_gate
        if gate is None:
            raise ValueError("budget gate was not explicitly accepted")
        record = BudgetControlRecord(
            key=budget_control_key(request.command_issuer, request.command_id),
            command_id=request.command_id,
            command_issuer=request.command_issuer,
            command_digest=command.payload_digest,
            command_sequence=command.target_sequence,
            operation_digest=sha256_digest(operation),
            request_scope=operation.request_scope,
            run_id=operation.identity.run_id,
            harness_execution_id=identity,
            native_session_ref=state.native_session_ref,
            generation=request.generation,
            binding_digest=seal.policy_digest,
            configuration_digest=operation.effective_configuration_digest,
            action="hold" if command.kind == "pause" else "resume",
            hold_key=(
                budget_control_key(gate.hold_command_issuer, gate.hold_command_id)
                if gate.hold_command_issuer and gate.hold_command_id
                else None
            ),
            ceiling_minor_units=ceiling,
            requested_cap_minor_units=gate.target_cap_minor_units,
            recorded_at=now,
        )
        return await self.states.enqueue_budget_control(record)

    async def drain(
        self,
        operation: OperationExecutionRequest,
        heid: object,
        owner: SessionOwner,
        provider: ManagedBudgetProvider,
        now: datetime,
    ) -> None:
        async with self._locks.setdefault(str(heid), asyncio.Lock()):
            await self._drain(operation, heid, owner, provider, now)

    async def _drain(
        self,
        operation: OperationExecutionRequest,
        heid: object,
        owner: SessionOwner,
        provider: ManagedBudgetProvider,
        now: datetime,
    ) -> None:
        from uuid import UUID

        identity = UUID(str(heid))
        state = await self.states.load(operation.request_scope, identity)
        if state is None:
            return
        for record in sorted(state.budget_controls.values(), key=lambda r: r.command_sequence):
            if record.phase == "rejected" or record.applied:
                continue
            request = LaneBudgetControlRequest(
                operation=operation,
                generation=record.generation,
                command_id=record.command_id,
                command_issuer=record.command_issuer,
            )
            try:
                if (
                    state.native_session_ref != record.native_session_ref
                    or owner.generation != record.generation
                ):
                    raise ValueError("budget control native identity/generation changed")
                if sha256_digest(operation) != record.operation_digest:
                    raise ValueError("budget control operation changed")
                command = await self.authority.verify_budget_control(request)
                if command.payload_digest != record.command_digest:
                    raise ValueError("budget control command changed")
                seal = await self.approvals.current(
                    record.request_scope, run_id=record.run_id, harness_execution_id=str(identity)
                )
                if (
                    not seal.granted
                    or seal.generation != record.generation
                    or seal.policy_digest != record.binding_digest
                ):
                    raise ValueError("budget control approval seal changed")
                await self.states.assert_owner(record.request_scope, identity, owner)
                snapshot = await provider.read_budget(record.native_session_ref)
                if snapshot.cap_minor_units > record.ceiling_minor_units:
                    raise ValueError("provider cap exceeds immutable ceiling")
                if record.phase == "queued":
                    current = await self.states.load(record.request_scope, identity)
                    preceding = {
                        key: value
                        for key, value in (current.budget_controls.items() if current else ())
                        if value.command_sequence < record.command_sequence
                    }
                    active_holds = _active_holds(preceding)
                    if record.action == "hold":
                        if active_holds:
                            raise ValueError("budget hold overlaps an unresolved held command")
                        target = min(
                            snapshot.spent_minor_units + 1,
                            snapshot.cap_minor_units,
                            record.ceiling_minor_units,
                        )
                    else:
                        hold = (
                            current.budget_controls.get(record.hold_key or "") if current else None
                        )
                        if (
                            hold is None
                            or hold.action != "hold"
                            or not hold.applied
                            or active_holds != {hold.key}
                        ):
                            raise ValueError("resume requires the observed held boundary")
                        target = record.requested_cap_minor_units or record.ceiling_minor_units
                        if (
                            target > record.ceiling_minor_units
                            or target <= snapshot.spent_minor_units
                            or target <= snapshot.cap_minor_units
                        ):
                            raise ValueError("resume cap outside immutable remaining budget")
                    # Admission is fresh before the only possible POST. Replays of an
                    # intended record never reuse an old admission to issue another POST.
                    verdict = await self.fences.admit_effect(
                        EffectAdmission(
                            request_scope=record.request_scope,
                            run_id=record.run_id,
                            generation=record.generation,
                            effect_ref=f"budget:{record.key}"[:512],
                            effect_kind="other",
                            lane_profile=lane_profile_for(operation),
                        )
                    )
                    if not verdict.allowed:
                        raise ValueError("budget control denied by stop fence")
                    record = await self._save(
                        record,
                        owner,
                        now,
                        phase="intended",
                        target_cap_minor_units=target,
                        prior_cap_minor_units=snapshot.cap_minor_units,
                        prior_boundary_evidence=snapshot.evidence,
                        observed_cost_minor_units=snapshot.spent_minor_units,
                    )
                    # Authority and approval may change while native GET or the journal
                    # write is in flight. Recheck both after intent, before the effect.
                    command = await self.authority.verify_budget_control(request)
                    seal = await self.approvals.current(
                        record.request_scope,
                        run_id=record.run_id,
                        harness_execution_id=str(identity),
                    )
                    if command.payload_digest != record.command_digest or (
                        not seal.granted
                        or seal.generation != record.generation
                        or seal.policy_digest != record.binding_digest
                    ):
                        raise ValueError("budget control authority changed after intent")
                    await self.states.assert_owner(record.request_scope, identity, owner)
                    fence = await self.fences.get(record.request_scope, record.run_id)
                    if fence is not None and fence.covers(record.generation):
                        await self._save(
                            record, owner, now, phase="in_doubt", reason="stop_fence_after_intent"
                        )
                        return
                    # An already-equal cap is readback-only; never auto-resume on hold.
                    if target != snapshot.cap_minor_units:
                        try:
                            await provider.set_budget(record.native_session_ref, target)
                        except Exception:
                            record = await self._save(
                                record,
                                owner,
                                now,
                                phase="in_doubt",
                                reason="provider_update_outcome_unknown",
                            )
                    snapshot = await provider.read_budget(record.native_session_ref)
                if snapshot.cap_minor_units != record.target_cap_minor_units:
                    await self._save(
                        record,
                        owner,
                        now,
                        phase="in_doubt",
                        reason="provider_cap_readback_mismatch",
                    )
                    return
                fresh_boundary = snapshot.boundary_observed and (
                    record.target_cap_minor_units == record.prior_cap_minor_units
                    or snapshot.evidence != record.prior_boundary_evidence
                )
                phase = (
                    "boundary_observed"
                    if record.action == "hold" and fresh_boundary
                    else "cap_confirmed"
                )
                reason = ""
                if record.action == "hold" and not fresh_boundary:
                    reason = f"budget_boundary_not_observed:{snapshot.disposition}"
                    if snapshot.disposition == "terminal":
                        phase = "in_doubt"
                await self._save(
                    record,
                    owner,
                    now,
                    phase=phase,
                    evidence=snapshot.evidence or "provider_cap_readback",
                    observed_cost_minor_units=snapshot.spent_minor_units,
                    reason=reason,
                )
                if phase == "cap_confirmed" and record.action == "hold":
                    return
            except ValueError as error:
                await self._save(
                    record,
                    owner,
                    now,
                    phase="rejected" if record.phase == "queued" else "in_doubt",
                    reason=str(error)[:512],
                )
                return

    async def _save(
        self, record: BudgetControlRecord, owner: SessionOwner, now: datetime, **changes: object
    ) -> BudgetControlRecord:
        updated = record.model_copy(
            update={
                **changes,
                "revision": record.revision + 1,
                "owner_epoch": owner.epoch,
                "recorded_at": now,
            }
        )
        return await self.states.update_budget_control(
            updated, expected_revision=record.revision, owner=owner
        )

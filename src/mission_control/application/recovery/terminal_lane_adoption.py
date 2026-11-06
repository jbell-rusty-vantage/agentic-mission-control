"""Inspection-only terminal evidence adoption planning; no writer or provider port.

Trusted readers supply facts, callers supply identity and optimistic versions only.
Even an unblocked plan is review material, never settlement or dispatch authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from mission_control.domain.authoring.canonical import sha256_digest


class AdoptionInspectionRefused(ValueError):
    """The captured facts cannot be joined to one unchanged execution."""


@dataclass(frozen=True)
class AdoptionIdentity:
    request_scope: str
    public_run_key: str
    internal_run_id: str
    harness_execution_id: str
    generation: int
    native_session_ref: str
    native_turn_ref: str


@dataclass(frozen=True)
class AdoptionInspectionRequest:
    identity: AdoptionIdentity
    expected_run_version: int
    expected_owner_epoch: int | None


@dataclass(frozen=True)
class AdoptionAuthority:
    identity: AdoptionIdentity
    run_version: int
    phase: str
    harness_lifecycle: str
    claim_status: str
    binding_id: str | None
    binding_digest: str | None
    claim_id: str | None
    harness_revision: int | None
    owner_epoch: int | None
    # Dispatches live inside the harness row. This is that parent row's revision,
    # not a separate independently persisted dispatch counter.
    dispatch_revision: int | None
    dispatch_digest: str | None
    dispatches_resolved: bool
    family_head_digest: str | None
    cancel_command_id: str | None
    cancel_receipt_revision: int | None
    cancel_state: str | None
    currency_liability_retained: bool | None
    admitted_currency_micros: int | None = None


@dataclass(frozen=True)
class TerminalLaneEvidence:
    identity: AdoptionIdentity
    native_status: str
    evidence_digest: str
    result_digest: str
    result_size: int
    total_tokens: int | None
    cost_micros_usd: int | None
    custody_ref: str | None
    custody_digest: str | None
    custody_size: int | None
    custody_immutable: bool


class AdoptionAuthorityReader(Protocol):
    async def read(self, identity: AdoptionIdentity) -> AdoptionAuthority: ...


class TerminalLaneEvidenceReader(Protocol):
    async def read(self, identity: AdoptionIdentity) -> TerminalLaneEvidence: ...


@dataclass(frozen=True)
class TerminalLaneAdoptionPlan:
    authority: AdoptionAuthority
    evidence: TerminalLaneEvidence
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    digest: str
    provider_acknowledged: bool = False
    writer_available: bool = False


class TerminalLaneAdoption:
    def __init__(
        self, authority: AdoptionAuthorityReader, evidence: TerminalLaneEvidenceReader
    ) -> None:
        self._authority, self._evidence = authority, evidence

    async def inspect(self, request: AdoptionInspectionRequest) -> TerminalLaneAdoptionPlan:
        identity = request.identity
        if (
            not all(asdict(identity).values())
            or identity.generation < 1
            or request.expected_run_version < 1
            or identity.public_run_key == identity.internal_run_id
        ):
            raise AdoptionInspectionRefused("invalid execution identity/version")
        before = await self._authority.read(identity)
        if before.identity != identity or before.run_version != request.expected_run_version:
            raise AdoptionInspectionRefused("identity or run version differs")
        if before.owner_epoch != request.expected_owner_epoch:
            raise AdoptionInspectionRefused("owner epoch differs")
        if (before.phase, before.harness_lifecycle, before.claim_status) != (
            "cancelling",
            "live",
            "claimed",
        ):
            raise AdoptionInspectionRefused("unsupported reconciliation shape")
        evidence = await self._evidence.read(identity)
        if evidence.identity != identity:
            raise AdoptionInspectionRefused("native evidence identity differs")
        if evidence.native_status != "FINISHED":
            raise AdoptionInspectionRefused("native FINISHED evidence required")
        if not evidence.evidence_digest or not evidence.result_digest or evidence.result_size < 1:
            raise AdoptionInspectionRefused("terminal byte provenance missing")
        if evidence.total_tokens is not None and (
            type(evidence.total_tokens) is not int or evidence.total_tokens < 0
        ):
            raise AdoptionInspectionRefused("invalid token counter")
        if evidence.cost_micros_usd is not None and (
            type(evidence.cost_micros_usd) is not int or evidence.cost_micros_usd < 0
        ):
            raise AdoptionInspectionRefused("invalid cost counter")
        after = await self._authority.read(identity)
        if before != after:
            raise AdoptionInspectionRefused("authority changed during inspection")
        blockers = []
        warnings = []
        currency = before.admitted_currency_micros
        if currency is not None and (type(currency) is not int or currency < 0):
            raise AdoptionInspectionRefused("invalid admitted currency amount")
        if not all(
            (
                before.binding_id,
                before.binding_digest,
                before.claim_id,
                before.family_head_digest,
                before.dispatch_digest,
            )
        ) or any(
            value is None or value < 1
            for value in (before.harness_revision, before.owner_epoch, before.dispatch_revision)
        ):
            blockers.append("authority_frontier_missing")
        if not before.dispatches_resolved:
            blockers.append("dispatch_unresolved")
        if not (
            before.cancel_command_id
            and before.cancel_receipt_revision is not None
            and before.cancel_receipt_revision > 0
            and before.cancel_state
        ):
            blockers.append("cancel_command_frontier_missing")
        # Normal terminalization applies a matching pending cancel. Requiring its
        # prior application here would create a recovery prerequisite cycle.
        # This inspection still grants neither writer authority nor provider ack.
        if before.cancel_state in {"accepted", "delivered"}:
            warnings.append("cancel_applies_at_terminalization")
        elif before.cancel_state not in {"applied", "rejected", "expired", "failed", "superseded"}:
            blockers.append("cancel_command_unresolved")
        if not (
            evidence.custody_ref
            and evidence.custody_immutable
            and evidence.custody_digest == evidence.result_digest
            and evidence.custody_size == evidence.result_size
        ):
            blockers.append("immutable_result_custody_missing")
        if evidence.total_tokens is None:
            blockers.append("token_usage_unknown")
        if evidence.cost_micros_usd is None:
            warnings.append("external_billing_unknown")
            if currency is None:
                blockers.append("admitted_currency_unknown")
            elif currency > 0 and before.currency_liability_retained is not True:
                blockers.append("unknown_cost_liability_unproven")
        body = {
            "schema_version": "mc.terminal-lane-adoption-plan.v1",
            "authority": asdict(before),
            "evidence": asdict(evidence),
            "blockers": blockers,
            "warnings": warnings,
            "provider_acknowledged": False,
            "writer_available": False,
        }
        return TerminalLaneAdoptionPlan(
            before, evidence, tuple(blockers), tuple(warnings), sha256_digest(body)
        )

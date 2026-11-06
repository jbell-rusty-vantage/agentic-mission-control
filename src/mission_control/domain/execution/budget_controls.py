"""Opt-in Managed budget control receipts; never a native pause guarantee."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from mission_control.domain.execution.contracts import Contract, OperationExecutionRequest


class LaneBudgetControlRequest(Contract):
    schema_version: Literal["mc.managed-budget-control.v1"] = "mc.managed-budget-control.v1"
    operation: OperationExecutionRequest
    generation: int = Field(ge=1)
    command_id: str = Field(min_length=1)
    command_issuer: str = Field(min_length=1)


class BudgetControlRecord(Contract):
    schema_version: Literal["mc.managed-budget-journal.v1"] = "mc.managed-budget-journal.v1"
    key: str
    command_id: str
    command_issuer: str
    command_digest: str
    command_sequence: int = Field(ge=1)
    operation_digest: str
    request_scope: str
    run_id: str
    harness_execution_id: UUID
    native_session_ref: str
    generation: int = Field(ge=1)
    binding_digest: str
    configuration_digest: str
    action: Literal["hold", "resume"]
    hold_key: str | None = None
    ceiling_minor_units: int = Field(ge=1)
    requested_cap_minor_units: int | None = Field(default=None, ge=1)
    target_cap_minor_units: int | None = Field(default=None, ge=1)
    prior_cap_minor_units: int | None = Field(default=None, ge=1)
    prior_boundary_evidence: str = ""
    observed_cost_minor_units: int | None = Field(default=None, ge=0)
    phase: Literal[
        "queued", "intended", "in_doubt", "cap_confirmed", "boundary_observed", "rejected"
    ] = "queued"
    revision: int = Field(default=1, ge=1)
    owner_epoch: int | None = None
    evidence: str = ""
    reason: str = ""
    recorded_at: AwareDatetime

    @property
    def applied(self) -> bool:
        return self.phase == ("boundary_observed" if self.action == "hold" else "cap_confirmed")


class ManagedBudgetSnapshot(Contract):
    cap_minor_units: int = Field(ge=1)
    spent_minor_units: int = Field(ge=0)
    boundary_observed: bool = False
    evidence: str = ""
    disposition: Literal["running", "budget_boundary", "requires_action", "terminal"] = "running"


def budget_control_key(issuer: str, command_id: str) -> str:
    # Length prefix avoids ambiguous concatenation of principal-controlled identities.
    return f"{len(issuer)}:{issuer}{command_id}"

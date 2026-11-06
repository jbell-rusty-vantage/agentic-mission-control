"""Immutable Cursor billing request and observation contracts; no provider I/O."""

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

COST_DIMENSION = "currency.estimated_micros"
CostState = Literal["settled", "unknown", "unattributable", "overage", "conflict"]


class CostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_scope: str
    binding_id: str
    activity_task_queue: str = Field(min_length=1)

    @property
    def workflow_id(self) -> str:
        identity = f"{self.request_scope}|{self.binding_id}".encode()
        return "cursor-costs/" + sha256(identity).hexdigest()


class NativeBillingRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    agent_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)


class CostReadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: CostState
    observed_micros: int | None = Field(default=None, ge=0)
    pending_micros: int = Field(ge=0)
    native_runs: tuple[NativeBillingRun, ...] = ()
    native_costs_micros: tuple[int | None, ...] = ()
    requested_model: str | None = None
    observed_model: str | None = None
    source: str = "cursor.charged_cents"
    initial_recorded_micros: int = Field(default=0, ge=0)
    recorded_at: str

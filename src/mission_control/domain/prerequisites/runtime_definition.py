"""The existing generic runtime admission snapshot, distinct from a Mission Manifest."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mission_control.domain.authoring.contracts import ExactDefinitionRef, RunInputManifestRef
from mission_control.domain.policies.contracts import BudgetDimensionLimit


class RuntimeRequestDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract: Literal["mc.run-request-definition/1"]
    request_scope: str
    idempotency_issuer: str
    request_id: str
    workflow_type_ref: ExactDefinitionRef
    effective_configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    input_manifest: RunInputManifestRef
    obligation_revision: str
    required_obligation_refs: tuple[str, ...]
    budget_limits: tuple[BudgetDimensionLimit, ...]
    baseline_reservations: dict[str, int]
    parent_budget_account: str | None

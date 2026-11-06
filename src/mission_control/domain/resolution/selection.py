"""The resolution seam's input: one node's (lane, model, blueprint, application) choice."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.data_class import DataClass
from mission_control.domain.resolution.configuration import AgentConfiguration, Family, Vendor


class RuntimeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_profile: str = Field(min_length=1, max_length=64)
    model_profile: str = Field(min_length=1, max_length=192)
    family: Family
    # executor, verifier, evaluator, convergence ...
    node_role: str = Field(min_length=1, max_length=64)
    application_id: str = Field(min_length=1, max_length=64)
    # Built by the compiler before resolution; its items are not yet resolved to a lane.
    agent: AgentConfiguration
    # No `requirements` (OC-R7): the manifest's `requires` is admitted where it was before the
    # seam (`domain/execution/lane_requirements.admit_requirements`); no caller set the field
    # and the resolver never read it (SELECTION-AND-ROUTING-INTERFACES §8).
    # The lane's discriminated container (`provider_options[lane]`); opaque to the core.
    lane_options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_choice(self) -> RuntimeSelection:
        if self.agent.lane_profile != self.lane_profile:
            raise ValueError("the selection and its agent configuration name different lanes")
        if self.agent.model.profile != self.model_profile:
            raise ValueError("the selection and its agent configuration name different models")
        return self

    def digest(self) -> str:
        return sha256_digest(self.model_dump(mode="python"))


class LaneAdmission(BaseModel):
    """The admission half of a selection, for a lane whose compile cannot yet take the whole
    node (OC-R3, OC-D199: the describe-only lanes until the provider sweep).

    `vendor` is the model's vendor when the deployment declares one (a provider lane's native
    route); `None` when the lane's deployment pins a lane-local model id that no Model Profile
    declares yet (the Cursor model catalog until R6's `models.toml`), so no route is checked.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_profile: str = Field(min_length=1, max_length=64)
    application_id: str = Field(min_length=1, max_length=64)
    family: Family
    data_class: DataClass
    vendor: Vendor | None = None


__all__ = ["LaneAdmission", "RuntimeSelection"]

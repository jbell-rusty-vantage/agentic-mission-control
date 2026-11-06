"""Installation placement limits and evidence-bound preference order (MO-52)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mission_control.domain.execution.lanes import HOSTED_PROFILES, LaneProfileName


class PlacementLimit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_active: int = Field(ge=1, le=1000)
    launches_per_minute: int | None = Field(default=None, ge=1, le=10000)
    retry_after_s: int = Field(default=30, ge=1, le=900)


class PlacementCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: LaneProfileName
    qualified: bool
    prerequisites_met: bool
    capacity_available: bool


def choose_placement(
    candidates: tuple[PlacementCandidate, ...],
    preference: Literal["prefer_cloud", "cloud_only", "local_only"] = "prefer_cloud",
) -> LaneProfileName:
    admitted = [
        item
        for item in candidates
        if item.qualified and item.prerequisites_met and item.capacity_available
    ]
    if preference == "prefer_cloud":
        admitted.sort(key=lambda item: item.profile not in HOSTED_PROFILES)
    else:
        hosted = preference == "cloud_only"
        admitted = [item for item in admitted if (item.profile in HOSTED_PROFILES) == hosted]
    if not admitted:
        raise ValueError(
            "PREREQUISITES_UNMET: no qualified placement satisfies prerequisites and budget"
        )
    return admitted[0].profile

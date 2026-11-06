"""The coordinator-facing model listing (OC-D201, OC-R6 / OVE-200; interface sketch §3.1).

A coordinator writes a Model Profile name in a manifest's `model.profile`; it runs only on a lane
that routes the profile's vendor. This read-only handler joins the two declarations that decide
that: every row of the installation's Model Catalog (`deployments/<app>/models.toml`) and every
registered lane's declared `model_routes` (its package `LaneRegistration`). A declared lane
profile absent from this process's registry is `unbound`: the installation binds no credential
for it, so it cannot run here (OC-R3) and no verdict is offered. A profile registered without a
package registration (a runtime-only describe) is `unregistered`: no verdict is invented.

These profiles seed workflows; they are not the AI Engineer knowledge schema's model entities.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from mission_control.application.execution.harness.describe import DECLARED_LANES
from mission_control.application.resolution.ports import LaneRegistry, ModelCatalog
from mission_control.domain.execution.data_class import DataClass
from mission_control.domain.execution.lanes import LANE_PROFILES
from mission_control.domain.resolution.configuration import PriceTier, Vendor
from mission_control.domain.resolution.profiles import ModelCapability, ModelProfile, ModelRoute

MODEL_LISTING_SCHEMA: Final = "mc.model_listing.v1"
RouteVerdict = Literal["native", "emulated", "unsupported", "unbound", "unregistered"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LaneModelRoute(_Frozen):
    """One lane's verdict on one model's vendor, with the lane's own mechanism word."""

    lane_profile: str
    verdict: RouteVerdict
    mechanism: str | None = None


class ModelListing(_Frozen):
    """One Model Profile with each lane profile's route verdict (`GET .../models`)."""

    profile: str
    vendor: Vendor
    model_id: str
    context_window_tokens: int
    max_input_tokens: int
    cost_per_million_input: float
    cost_per_million_output: float
    price_tiers: tuple[PriceTier, ...]
    supports: tuple[ModelCapability, ...]
    data_class_ceiling: DataClass
    # lane profile -> verdict
    routes: dict[str, RouteVerdict]


class ModelDescription(ModelListing):
    """`GET .../models/{profile}`: the listing row plus each lane's mechanism."""

    lanes: tuple[LaneModelRoute, ...]


class ModelList(_Frozen):
    schema_version: Literal["mc.model_listing.v1"] = MODEL_LISTING_SCHEMA
    models: tuple[ModelListing, ...]


def declared_model_routes(lanes: LaneRegistry, lane_profile: str) -> tuple[ModelRoute, ...] | None:
    """The lane's declared `model_routes`, or `None` when it has no package registration."""

    try:
        return lanes.get(lane_profile).declaration.model_routes
    except KeyError:
        return None


def _lane_profiles(lanes: LaneRegistry) -> tuple[str, ...]:
    return tuple(sorted({*LANE_PROFILES, *lanes.profiles()}))


def _route(lanes: LaneRegistry, lane_profile: str, model: ModelProfile) -> LaneModelRoute:
    routes = declared_model_routes(lanes, lane_profile)
    if routes is None:
        # Absent from this process's registry: the installation binds no credential for it.
        # Present without a package registration (a runtime-only describe): `unregistered`.
        verdict: RouteVerdict = (
            "unbound"
            if lane_profile in DECLARED_LANES and lane_profile not in lanes.profiles()
            else "unregistered"
        )
        return LaneModelRoute(lane_profile=lane_profile, verdict=verdict)
    route = next((item for item in routes if item.vendor == model.vendor), None)
    if route is None:
        return LaneModelRoute(lane_profile=lane_profile, verdict="unsupported")
    return LaneModelRoute(
        lane_profile=lane_profile, verdict=route.verdict, mechanism=route.mechanism
    )


def describe_model(models: ModelCatalog, lanes: LaneRegistry, profile: str) -> ModelDescription:
    """One profile with every lane's route; `KeyError` when the catalog has no such profile."""

    model = models.get(profile)
    rows = tuple(_route(lanes, lane_profile, model) for lane_profile in _lane_profiles(lanes))
    return ModelDescription(
        profile=model.profile,
        vendor=model.vendor,
        model_id=model.model_id,
        context_window_tokens=model.context_window_tokens,
        max_input_tokens=model.max_input_tokens,
        cost_per_million_input=model.cost_per_million_input,
        cost_per_million_output=model.cost_per_million_output,
        price_tiers=model.price_tiers,
        supports=model.supports,
        data_class_ceiling=model.data_class_ceiling,
        routes={row.lane_profile: row.verdict for row in rows},
        lanes=rows,
    )


def list_models(models: ModelCatalog, lanes: LaneRegistry) -> ModelList:
    """Every catalog profile, sorted by name, with each lane profile's route verdict."""

    return ModelList(
        models=tuple(
            ModelListing.model_validate(
                describe_model(models, lanes, profile).model_dump(exclude={"lanes"})
            )
            for profile in models.profiles()
        )
    )


__all__ = [
    "MODEL_LISTING_SCHEMA",
    "LaneModelRoute",
    "ModelDescription",
    "ModelList",
    "ModelListing",
    "RouteVerdict",
    "declared_model_routes",
    "describe_model",
    "list_models",
]

"""Model Profile listing routes (OC-D201, OC-R6 / OVE-200).

`GET /v1/applications/{app}/models` lists the installation's Model Catalog with each lane
profile's route verdict (`native | emulated | unsupported`, `unbound` for a declared lane this
installation binds no credential for, or `unregistered` for a lane profile without a package
registration in this process); `GET .../models/{profile}` returns one profile
with each lane's mechanism. Read-only and authenticated like every public route; the handler is
`application/resolution/model_listing.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from mission_control.application.resolution.model_listing import (
    ModelDescription,
    ModelList,
    describe_model,
    list_models,
)
from mission_control.application.resolution.registries import LaneRegistry, ModelCatalog
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    authorize_application,
    get_mission_principal,
)

router = APIRouter(prefix="/v1/applications/{application_id}/models", tags=["models"])
Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]


def model_registries(
    application_id: str, request: Request, principal: Principal
) -> tuple[ModelCatalog, LaneRegistry]:
    authorize_application(application_id, request, principal)
    catalogs = getattr(request.app.state, "mission_control_model_catalogs", None) or {}
    catalog = catalogs.get(application_id)
    lanes = getattr(request.app.state, "mission_control_lanes", None)
    if not isinstance(catalog, ModelCatalog) or not isinstance(lanes, LaneRegistry):
        raise HTTPException(503, detail={"code": "models_unavailable"})
    return catalog, lanes


Registries = Annotated[tuple[ModelCatalog, LaneRegistry], Depends(model_registries)]


@router.get("", response_model=ModelList)
def list_model_profiles(registries: Registries) -> ModelList:
    catalog, lanes = registries
    return list_models(catalog, lanes)


@router.get("/{profile}", response_model=ModelDescription)
def describe_model_profile(profile: str, registries: Registries) -> ModelDescription:
    catalog, lanes = registries
    try:
        return describe_model(catalog, lanes, profile)
    except KeyError:
        raise HTTPException(404, detail={"code": "model_profile_not_in_catalog"}) from None

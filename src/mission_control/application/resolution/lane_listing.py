"""One lane profile's full describe, as every transport serves it (SPEC-07 Interfaces; FT-G1).

`GET /v1/applications/{app}/lanes/{profile}`, `missionctl lane describe` and the guide's
`lane:<profile>` describe answer with this one document: the lane's `mc.lane_describe` matrix
(`controls`, `delivery_semantics`, `time_travel`, hooks, usage, identity), what the lane does with
each `mc.subagent_profile.v1` field, and the vendors it routes. Read-only; it never reveals
whether a credential is bound beyond the fact that the profile is registered.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.authoring.subagent_support import subagent_field_support
from mission_control.application.resolution.model_listing import declared_model_routes
from mission_control.application.resolution.registries import LaneRegistry


def describe_lane(lanes: LaneRegistry, lane_profile: str) -> dict[str, Any]:
    """The lane describe document; `UnknownLaneProfile` for an unregistered profile."""

    describe = lanes.describe(lane_profile)
    payload = describe.model_dump(mode="json")
    # P1 subagents: what the lane does with each `mc.subagent_profile.v1` field, served
    # beside the persisted describe document (the same table compile enforces). Folding it
    # into `mc.lane_describe.v2` itself is a lane-describe migration.
    payload["subagent_fields"] = dict(subagent_field_support(describe.lane_profile))
    # OC-R6: the vendors this lane routes, from its package declaration; `null` for a profile
    # without a package registration in this process (its routes are declared nowhere here).
    routes = declared_model_routes(lanes, describe.lane_profile)
    payload["model_routes"] = (
        [route.model_dump(mode="json") for route in routes] if routes is not None else None
    )
    return payload


__all__ = ["describe_lane"]

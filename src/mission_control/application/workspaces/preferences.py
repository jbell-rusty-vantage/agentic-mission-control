"""Expand exact author-declared alternatives before compilation and sealing."""

from copy import deepcopy
from typing import Any

from mission_control.application.prerequisites.preflight import PrerequisitePreflight, node_roles
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.execution.lanes import HOSTED_PROFILES


class FreshPlacementEligibility:
    def __init__(self, registry: LaneRegistry | None, prerequisites: PrerequisitePreflight) -> None:
        self._registry, self._prerequisites = registry, prerequisites

    async def __call__(self, scope: str, definitions: tuple[MissionDefinition, ...]) -> bool:
        registry = self._registry
        # An allow-unqualified worker flag is deliberately not qualification evidence.
        if registry is None:
            return False
        for definition in definitions:
            for node, verifier in node_roles(definition.program):
                environment = node.verifier_environment if verifier else node.environment
                profile = (environment.lane if environment else None) or node.lane
                if profile.value not in registry.profiles():
                    return False
                if not registry.describe(profile.value).qualified:
                    return False
        return (await self._prerequisites.assess(scope, definitions)).ready


def placement_documents(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered bounded alternatives; selected environments are compiled independently."""

    def find(value: Any, path: tuple[str | int, ...] = ()) -> tuple[str | int, ...] | None:
        if isinstance(value, dict):
            if path and path[-1] == "environment" and value.get("lanes"):
                return path
            for key, child in value.items():
                result = find(child, (*path, key))
                if result is not None:
                    return result
        elif isinstance(value, list):
            for index, child in enumerate(value):
                result = find(child, (*path, index))
                if result is not None:
                    return result
        return None

    pending = [document]
    selected: list[dict[str, Any]] = []
    while pending:
        current = pending.pop(0)
        path = find(current)
        if path is None:
            selected.append(current)
            continue
        environment: Any = current
        for key in path:
            environment = environment[key]
        lanes = list(environment["lanes"])
        preference = environment.get("placement") or "prefer_cloud"
        if preference == "prefer_cloud":
            lanes.sort(key=lambda lane: lane not in HOSTED_PROFILES)
        else:
            lanes = [
                lane for lane in lanes if (lane in HOSTED_PROFILES) == (preference == "cloud_only")
            ]
        alternatives = []
        for lane in lanes:
            candidate = deepcopy(current)
            target: Any = candidate
            for key in path:
                target = target[key]
            overlay = deepcopy(target["lane_environments"][lane])
            for key in ("lanes", "lane_environments", "placement"):
                target.pop(key, None)
            target.update(overlay)
            alternatives.append(candidate)
        pending[0:0] = alternatives
        if len(pending) + len(selected) > 64:
            raise ValueError("placement alternatives exceed the 64 compilation limit")
    return selected

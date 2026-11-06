"""Every lane package registration bootstrap composes has a compile conformance entry (R1).

A lane registers its package (`LaneRegistry.register`) only in bootstrap composition: the
worker's `compose_lane_registry` and the launch author's `compose_launch_resolution`. Each
registration there must be driven by the compile suite (`registry.COMPILE_LANES`); a runtime-only
entry (`register_harness`) is refused by the resolver as `LANE_UNKNOWN` and needs none.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mission_control.adapters.deep_agents.describe import DEEP_AGENTS_DESCRIBE
from mission_control.adapters.temporal.deployment_composition import compose_lane_registry
from mission_control.application.execution.harness.describe import DECLARED_LANES
from mission_control.application.resolution.registries import DescribeOnlyLane, LaneRegistry
from mission_control.bootstrap.resolution import compose_launch_resolution
from tests.conformance.lanes.compile.registry import COMPILE_LANES
from tests.fixtures.applications import installed_applications
from tests.fixtures.models import bindings_catalog
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings, fixture_served


def _packages(registry: LaneRegistry) -> set[str]:
    registered: set[str] = set()
    for profile in registry.profiles():
        try:
            registry.get(profile)
        except KeyError:
            continue
        registered.add(profile)
    return registered


def _launch_registry() -> LaneRegistry:
    bindings = fixture_bindings()
    resolution = compose_launch_resolution(
        bindings,
        fixture_served(bindings),
        applications=installed_applications(),
        models=bindings_catalog(bindings),
    )
    lanes: Any = resolution.runtime._lanes
    assert isinstance(lanes, LaneRegistry)
    return lanes


def _worker_registry() -> LaneRegistry:
    settings: Any = SimpleNamespace(cursor_api_key=None, allow_unqualified_lanes=False)
    harness: Any = DescribeOnlyLane(DEEP_AGENTS_DESCRIBE)
    return compose_lane_registry(settings, harness)


def test_every_bootstrap_lane_registration_has_a_compile_conformance_entry() -> None:
    conformed = {lane.profile for lane in COMPILE_LANES}
    for registry in (_launch_registry(), _worker_registry()):
        packages = _packages(registry)
        assert packages, "bootstrap composed no lane package registration"
        assert packages <= conformed, f"no compile conformance for {sorted(packages - conformed)}"


def test_the_registered_deep_agents_package_is_the_declared_lane() -> None:
    for registry in (_launch_registry(), _worker_registry()):
        registration = registry.get("deep_agents")
        assert registration.declaration.describe == registry.describe("deep_agents")
        assert registration.adapter.profile == "deep_agents"


def test_the_launch_author_registers_every_declared_lane_package() -> None:
    """OC-R3: every declared profile has a package registration whose declaration is the lane
    package's own (the aggregator's entry), so the seam can admit any node."""

    registry = _launch_registry()
    assert _packages(registry) == set(DECLARED_LANES)
    for profile, declaration in DECLARED_LANES.items():
        registration = registry.get(profile)
        assert registration.declaration == declaration
        assert registration.adapter.profile == profile

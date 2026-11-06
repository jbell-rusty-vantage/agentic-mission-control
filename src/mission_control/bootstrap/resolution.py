"""Composition of the resolution seam (ADR-0063, OC-R1 / OVE-196): the only place its variants
are named.

`LaneRegistry` gets every lane package's registration: Deep Agents with its deployment facts,
the others (`bootstrap/lanes.SESSION_LANES`, OC-R3) with their describe-only compile. The
`ApplicationRegistry` and the `ModelCatalog` are the caller's: bootstrap composes the first from
the installation's `deployments/<app>/application.toml` (`bootstrap/application_profiles.py`,
OC-R4) and the second from `deployments/<app>/models.toml` (`bootstrap/model_profiles.py`,
OC-R6). The deployment's Deep Agents `model_profiles` are references into that catalog: the lane
package pairs each with its catalog row (`compile.catalog_model_components`).
"""

from __future__ import annotations

from collections.abc import Mapping

from mission_control.adapters.deep_agents.binding import DEEP_AGENTS_LANE_BINDINGS
from mission_control.adapters.deep_agents.compile import (
    DeepAgentsDeploymentFacts,
    deep_agents_lane,
)
from mission_control.application.authoring.manifest_launch_inputs import (
    LaunchResolution,
    ManifestLaunchBindings,
    ManifestLaunchResolver,
    ServedComponents,
)
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    DescribeOnlyLane,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.lanes import SESSION_LANES
from mission_control.domain.execution.network_policy import NetworkHosts

# -- The seam the manifest launch author resolves through ---------------------------------------


def compose_launch_resolution(
    bindings: ManifestLaunchBindings,
    served: ServedComponents,
    *,
    applications: ApplicationRegistry,
    models: ModelCatalog,
    async_result_policy_refs: frozenset[str] | None = None,
    allow_unqualified_lanes: bool = False,
) -> LaunchResolution:
    """The resolver, model catalog and template port the launch author uses.

    ``applications`` holds the installation's Application Profiles (OC-R4) and ``models`` its
    Model Catalog (OC-R6). The launch process compiles but never executes a lane, so the Deep
    Agents registration is paired with its describe-only harness.
    """

    facts = DeepAgentsDeploymentFacts.from_bindings(
        bindings, served, models=models, async_result_policy_refs=async_result_policy_refs
    )
    registration = deep_agents_lane(facts)
    lanes = LaneRegistry(allow_unqualified=allow_unqualified_lanes)
    lanes.register(registration, DescribeOnlyLane(registration.declaration.describe))
    # OC-R3: every other lane package, describe-only (their compile admits, never executes).
    for session_lane in SESSION_LANES.values():
        lanes.register(session_lane)
    return LaunchResolution(
        runtime=RuntimeResolver(
            lanes,
            applications,
            models,
            allow_unqualified_lanes=allow_unqualified_lanes,
        ),
        models=models,
        applications=applications,
        templates=DEEP_AGENTS_LANE_BINDINGS,
    )


def compose_manifest_launch_resolver(
    bindings: ManifestLaunchBindings,
    served: ServedComponents,
    *,
    applications: ApplicationRegistry,
    models: ModelCatalog,
    provider_secret_env: Mapping[str, str],
    network_hosts: NetworkHosts | None = None,
    hosted_digest: object = None,
    async_result_policy_refs: frozenset[str] | None = None,
    allow_unqualified_lanes: bool = False,
) -> ManifestLaunchResolver:
    """The manifest template author over the deployment bindings and the resolution seam."""

    return ManifestLaunchResolver(
        bindings,
        provider_secret_env=provider_secret_env,
        network_hosts=network_hosts,
        hosted_digest=hosted_digest,
        projectors=HOST_PROJECTORS,
        resolution=compose_launch_resolution(
            bindings,
            served,
            applications=applications,
            models=models,
            async_result_policy_refs=async_result_policy_refs,
            allow_unqualified_lanes=allow_unqualified_lanes,
        ),
    )


__all__ = [
    "compose_launch_resolution",
    "compose_manifest_launch_resolver",
]

"""The operator-reviewed runtime options of a local single-host installation (Sprint OC W1).

Selected only by process configuration: ``MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY=
mission_control.bootstrap.local_operator:runtime_options`` (``bootstrap/api.py``
``load_runtime_options``). Without a factory the API composes deny-by-default admission, no family
admissions and no artifact body reader; this factory adds exactly what an ordinary manifest
launch and its inspection need on one laptop, and nothing a request can select:

* the GoalDirected and StageGraph family admissions the worker also registers, so the API's
  governed family mutations are admitted under the same rules;
* the filesystem artifact payload store under ``ARTIFACT_PAYLOAD_ROOT`` (the store the worker
  promotes into), so ``GET transcript?full=true`` reads promoted bodies;
* the control-plane payload store stays unavailable: no S3 bucket is configured, and inline
  payloads up to the worker's 15 MB threshold need none.

The Mission Manifest service registers the manifest admission contract into the same registry
at composition (``bootstrap/manifests.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from mission_control.adapters.storage.control_plane_payloads import UnavailablePayloadStore
from mission_control.adapters.temporal.deployment_composition import artifact_payload_store
from mission_control.application.execution.service import (
    AdmissionPolicyRegistry,
    FamilyAdmissionRegistry,
)
from mission_control.application.frames.artifact_bodies import ContentAddressedPayloadReader
from mission_control.application.programs.goal_directed import (
    configure_goal_directed_family_admissions,
)
from mission_control.application.programs.service import register_stagegraph_family_mutations
from mission_control.bootstrap.api import MissionDeployment, RuntimeOptions
from mission_control.bootstrap.settings import get_settings
from mission_control.domain.authoring.extensions import ExtensionRegistry


def runtime_options(deployment: MissionDeployment) -> Mapping[str, RuntimeOptions]:
    """One typed options value per configured application (fresh registries for each)."""

    settings = get_settings()
    result: dict[str, RuntimeOptions] = {}
    for item in deployment.applications:
        families = FamilyAdmissionRegistry()
        configure_goal_directed_family_admissions(families)
        register_stagegraph_family_mutations(families)
        result[item.authentication.binding.application_id] = RuntimeOptions(
            AdmissionPolicyRegistry(),
            ExtensionRegistry(),
            UnavailablePayloadStore(),
            family_admissions=families,
            # The filesystem store (no S3 bucket here) is a content-addressed reader.
            artifact_payloads=cast(ContentAddressedPayloadReader, artifact_payload_store(settings)),
        )
    return result


__all__ = ["runtime_options"]

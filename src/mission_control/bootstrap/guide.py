"""Composition of the guide (`application/guide/service.py`).

The guide reads what the Selection Workspace of the same tenant reads: the describe-only Lane
Registry, the Model Catalog and, through the workspace, the tenant's published catalog
definitions (one short-lived cache for both). The one thing it adds is each lane's selectable
feature registry, which lives in the lane's package: bootstrap is where a lane package is named.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from mission_control.adapters.deep_agents.describe import DEEP_AGENTS_DECLARATION
from mission_control.adapters.deep_agents.routes import AGENT_FEATURES
from mission_control.application.guide.service import GuideService
from mission_control.application.resolution.registries import LaneRegistry, ModelCatalog
from mission_control.application.selection.workspace import SelectionWorkspace
from mission_control.domain.capabilities.features.registry import FeatureRegistry

# Lane profile -> the features a node on that lane may select (`provider_options`): the lane's
# own features and the vendor rows of its model routes. Only Deep Agents declares a registry.
LANE_FEATURE_REGISTRIES: Final[Mapping[str, FeatureRegistry]] = {
    DEEP_AGENTS_DECLARATION.lane_profile: AGENT_FEATURES,
}


def compose_guide(
    *,
    workspace: SelectionWorkspace,
    lanes: LaneRegistry,
    models: ModelCatalog,
    sandbox_profiles: Mapping[str, str] | None = None,
) -> GuideService:
    """One application's guide over the registries its Selection Workspace was composed from.
    `sandbox_profiles` is what the workspace was given (`bootstrap/selection.py`): the sandbox
    profiles the deployment binds, or `None` where the process reads no launch bindings."""

    return GuideService(
        application_id=workspace.application_id,
        lanes=lanes,
        models=models,
        catalog=workspace,
        features=LANE_FEATURE_REGISTRIES,
        sandbox_profiles=sandbox_profiles,
    )


__all__ = ["LANE_FEATURE_REGISTRIES", "compose_guide"]

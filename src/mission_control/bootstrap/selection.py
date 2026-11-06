"""Composition of the Selection Workspace (`application/selection/workspace.py`).

The workspace reads what the API process already holds for one application: the describe-only
Lane Registry (`bootstrap/lanes.describe_only_registry`), the Model Catalog
(`deployments/<app>/models.toml`), the Application Profile (`deployments/<app>/application.toml`)
and the tenant's catalog service. Its admission is the resolution seam's own
`RuntimeResolver.admit` over those registries, so a check answers exactly as the seam would at
steps 1 and 2. Nothing here compiles a lane.
"""

from __future__ import annotations

from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.application.capabilities.catalog import CatalogService
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.application.selection.workspace import SelectionWorkspace
from mission_control.bootstrap.application_profiles import compose_application_registry
from mission_control.bootstrap.lanes import (
    SESSION_LANES,
    describe_only_registry,
    settings_bound_lanes,
)
from mission_control.bootstrap.model_profiles import compose_model_catalog
from mission_control.bootstrap.settings import Settings


def compose_selection_workspace(
    *,
    application_id: str,
    lanes: LaneRegistry,
    models: ModelCatalog,
    applications: ApplicationRegistry,
    catalog: CatalogService | None,
) -> SelectionWorkspace:
    """One application's workspace over registries the caller composed (fails closed on none)."""

    return SelectionWorkspace(
        application_id=application_id,
        lanes=lanes,
        models=models,
        applications=applications,
        admission=RuntimeResolver(
            lanes, applications, models, allow_unqualified_lanes=lanes.allow_unqualified
        ),
        catalog_scope=catalog.catalog_scope if catalog is not None else None,
        search=catalog.search if catalog is not None else None,
        definitions=catalog.definitions if catalog is not None else None,
    )


def compose_settings_selection_workspace(
    settings: Settings, application_id: str, catalog: CatalogService | None
) -> SelectionWorkspace:
    """The same workspace from process settings, for a process without the API's registries
    (the development coordinator MCP server). It mirrors the API's lane composition: the bound
    lanes describe-only, each with its package registration."""

    return compose_selection_workspace(
        application_id=application_id,
        lanes=describe_only_registry(
            bound=settings_bound_lanes(settings),
            allow_unqualified=settings.allow_unqualified_lanes,
            registrations=(deep_agents_lane(None), *SESSION_LANES.values()),
        ),
        models=compose_model_catalog(settings.deployments_root, application_id),
        applications=compose_application_registry(settings.deployments_root, (application_id,)),
        catalog=catalog,
    )


__all__ = ["compose_selection_workspace", "compose_settings_selection_workspace"]

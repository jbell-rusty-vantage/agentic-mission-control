"""In-memory compositions for the guide tests (no database, no network, no server process).

`stub_guide` is the guide over the two stub lanes the Selection Workspace tests use and the
conformance Model Catalog; `full_guide` is the guide as the API composes it when every lane
profile is bound (`describe_only_registry`), the widest pages an installation can serve;
`operator_server` is the operator FastMCP server over placeholder registries, as the API builds
it, for listing its tools, resources and prompts.
"""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastmcp import FastMCP

from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.application.guide.service import GuideService
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.application.selection.workspace import SelectionWorkspace
from mission_control.bootstrap.guide import LANE_FEATURE_REGISTRIES, compose_guide
from mission_control.bootstrap.lanes import SESSION_LANES, describe_only_registry
from mission_control.domain.execution.lanes import LANE_PROFILES
from mission_control.domain.resolution.profiles import LaneDeclaration
from mission_control.interfaces.mcp.operator_server import create_operator_server
from tests.conformance.lanes.compile.stub import NARROW_DECLARATION, STUB_DECLARATION
from tests.conformance.resolution.fixtures import APPLICATIONS, MODELS
from tests.unit.selection.test_selection_workspace import (
    CATALOG_SCOPE,
    FakeDefinitions,
    FakeSearch,
    _registration,
)

APPLICATION = "biotech"
INSTALLATION = UUID("11111111-1111-4111-8111-111111111111")
TENANT = UUID("22222222-2222-4222-8222-222222222222")
# The scoped registries `create_operator_server` reads from the API's `app.state`.
OPERATOR_REGISTRIES = (
    "coordinator_inbox_services",
    "transcript_services",
    "transcript_search_services",
    "run_list_services",
    "subscription_services",
    "output_inspection_services",
    "chain_services",
    "manifest_services",
    "services",
    "runtime_services",
    "human_task_services",
    "governed_effect_services",
    "cognition_point_services",
    "point_reconcilers",
    "selection_workspaces",
    "knowledge_review_services",
    "guides",
)


def _workspace(lanes: LaneRegistry, models: ModelCatalog, *, catalog: bool) -> SelectionWorkspace:
    applications = ApplicationRegistry(APPLICATIONS)
    return SelectionWorkspace(
        application_id=APPLICATION,
        lanes=lanes,
        models=models,
        applications=applications,
        admission=RuntimeResolver(
            lanes, applications, models, allow_unqualified_lanes=lanes.allow_unqualified
        ),
        catalog_scope=CATALOG_SCOPE if catalog else None,
        search=FakeSearch() if catalog else None,
        definitions=FakeDefinitions() if catalog else None,
    )


def stub_guide(
    *,
    declarations: Iterable[LaneDeclaration] = (STUB_DECLARATION, NARROW_DECLARATION),
    allow_unqualified: bool = True,
    catalog: bool = True,
) -> GuideService:
    lanes = LaneRegistry(allow_unqualified=allow_unqualified)
    for declaration in declarations:
        lanes.register(_registration(declaration))
    models = ModelCatalog(MODELS)
    workspace = _workspace(lanes, models, catalog=catalog)
    return GuideService(
        application_id=APPLICATION,
        lanes=lanes,
        models=models,
        catalog=workspace if catalog else None,
        features=LANE_FEATURE_REGISTRIES,
    )


def full_guide() -> GuideService:
    """Every lane profile bound, with its package registration: the widest generated tables."""

    lanes = describe_only_registry(
        bound=LANE_PROFILES,
        allow_unqualified=False,
        registrations=(deep_agents_lane(None), *SESSION_LANES.values()),
    )
    models = ModelCatalog(MODELS)
    return compose_guide(
        workspace=_workspace(lanes, models, catalog=True), lanes=lanes, models=models
    )


def operator_server(guides: dict[Any, GuideService] | None = None) -> FastMCP:
    key = (INSTALLATION, APPLICATION, TENANT)
    state = SimpleNamespace(
        **{f"mission_control_{name}": {key: object()} for name in OPERATOR_REGISTRIES}
    )
    if guides is not None:
        state.mission_control_guides = guides
    return create_operator_server(state)

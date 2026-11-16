"""In-memory compositions for the guide tests (no database, no network, no server process).

`stub_guide` is the guide over the two stub lanes the Selection Workspace tests use and the
conformance Model Catalog; `full_guide` is the guide as the API composes it when every lane
profile is bound (`describe_only_registry`), the widest pages an installation can serve;
`operator_server` is the operator FastMCP server over placeholder registries, as the API builds
it, for listing its tools, resources and prompts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastmcp import FastMCP

from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.adapters.deep_agents.describe import SANDBOX_BACKEND_FACTS
from mission_control.application.guide.mission_templates import load_template, mission_templates
from mission_control.application.guide.service import GuideService
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.application.selection.workspace import (
    SANDBOX_REF_PREFIX,
    SelectionWorkspace,
    WorkspaceEntry,
)
from mission_control.bootstrap.guide import LANE_FEATURE_REGISTRIES, compose_guide
from mission_control.bootstrap.lanes import SESSION_LANES, describe_only_registry
from mission_control.domain.authoring.contracts import PublishedDefinition
from mission_control.domain.authoring.manifest import load_manifest_yaml
from mission_control.domain.authoring.manifest_lowering import lower_mission
from mission_control.domain.authoring.manifest_v2 import parse_manifest_any
from mission_control.domain.authoring.mission_definition import manifest_to_definitions
from mission_control.domain.execution.lanes import LANE_PROFILES
from mission_control.domain.resolution.profiles import LaneDeclaration
from mission_control.interfaces.mcp.operator_server import create_operator_server
from tests.conformance.lanes.compile.stub import NARROW_DECLARATION, STUB_DECLARATION
from tests.conformance.resolution.fixtures import APPLICATIONS, MODELS
from tests.unit.selection.test_selection_workspace import (
    CATALOG_SCOPE,
    FakeDefinitions,
    FakeSearch,
    _published,
    _registration,
)

APPLICATION = "biotech"
# The sandbox profiles a deployment's launch bindings bind, as the composition reads them
# (`bootstrap/selection.bound_sandbox_details`): the one line, and what the binding declares.
SANDBOXES: Mapping[str, str] = {"research.standard": "docker sandbox bound by this deployment"}
SANDBOX_DETAILS: Mapping[str, Mapping[str, Any]] = {
    "research.standard": {
        "summary": SANDBOXES["research.standard"],
        "backend": "docker",
        **SANDBOX_BACKEND_FACTS["docker"],
        "idle_ttl_seconds": 300,
        "definition": "sandbox.docker@1",
        "same_binding_as": [],
    }
}
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


def workspace_entries(
    sandboxes: Mapping[str, str] | None = SANDBOXES,
) -> dict[str, tuple[WorkspaceEntry, ...]]:
    """The templates and bound sandbox profiles as `bootstrap/selection.py` hands them in."""

    return {
        "templates": tuple(
            WorkspaceEntry(ref=template.ref, title=template.title, summary=template.purpose)
            for template in mission_templates()
        ),
        "sandbox_profiles": tuple(
            WorkspaceEntry(ref=f"{SANDBOX_REF_PREFIX}{name}", title=name, summary=summary)
            for name, summary in (sandboxes or {}).items()
        ),
    }


def _workspace(
    lanes: LaneRegistry,
    models: ModelCatalog,
    *,
    catalog: bool,
    rows: Sequence[PublishedDefinition] | None = None,
) -> SelectionWorkspace:
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
        definitions=(FakeDefinitions() if rows is None else FakeDefinitions(rows))
        if catalog
        else None,
        **workspace_entries(),
    )


def stub_guide(
    *,
    declarations: Iterable[LaneDeclaration] = (STUB_DECLARATION, NARROW_DECLARATION),
    allow_unqualified: bool = True,
    catalog: bool = True,
    rows: Sequence[PublishedDefinition] | None = None,
    sandboxes: Mapping[str, str] | None = SANDBOXES,
) -> GuideService:
    lanes = LaneRegistry(allow_unqualified=allow_unqualified)
    for declaration in declarations:
        lanes.register(_registration(declaration))
    models = ModelCatalog(MODELS)
    workspace = _workspace(lanes, models, catalog=catalog, rows=rows)
    return GuideService(
        application_id=APPLICATION,
        lanes=lanes,
        models=models,
        catalog=workspace if catalog else None,
        features=LANE_FEATURE_REGISTRIES,
        sandbox_profiles=sandboxes,
        sandbox_details=SANDBOX_DETAILS if sandboxes else None,
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
        workspace=_workspace(lanes, models, catalog=True),
        lanes=lanes,
        models=models,
        sandbox_profiles=SANDBOXES,
        sandbox_details=SANDBOX_DETAILS,
    )


def lowered_rows() -> tuple[PublishedDefinition, ...]:
    """The six definitions one submitted manifest leaves in the catalog, from the real
    lowering of the `smallest` template: its Workflow Type first, then its blueprint, control
    profile, runtime profile, workspace template and evaluation profile."""

    template = load_template("smallest")
    document = load_manifest_yaml(template.fill(template.examples()))
    (definition,) = manifest_to_definitions(parse_manifest_any(document), document)
    lowered = lower_mission(definition)
    blueprint = _published(lowered.blueprint)
    control = _published(lowered.control_profile(blueprint.ref))
    runtime = _published(lowered.runtime_profile)
    workspace = _published(lowered.workspace_template)
    evaluation = _published(lowered.evaluation_profile)
    workflow = _published(
        lowered.workflow_type(
            blueprint_ref=blueprint.ref,
            control_ref=control.ref,
            runtime_ref=runtime.ref,
            workspace_ref=workspace.ref,
            evaluation_ref=evaluation.ref,
        )
    )
    return (workflow, blueprint, control, runtime, workspace, evaluation)


def operator_server(guides: dict[Any, GuideService] | None = None) -> FastMCP:
    key = (INSTALLATION, APPLICATION, TENANT)
    state = SimpleNamespace(
        **{f"mission_control_{name}": {key: object()} for name in OPERATOR_REGISTRIES}
    )
    # A catalog that composes search, external discovery and candidate inspection, so the
    # listing holds every tool the operator server can register.
    state.mission_control_catalog_services = {
        key: SimpleNamespace(search=object(), discovery=object(), inspection=object())
    }
    if guides is not None:
        state.mission_control_guides = guides
    return create_operator_server(state)

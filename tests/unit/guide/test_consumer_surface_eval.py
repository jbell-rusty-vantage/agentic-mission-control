"""`scripts/consumer_surface_eval.py` against an API assembled in memory.

The evaluation runs as it would against a deployed server: over HTTP and the operator MCP mount
of one FastAPI app, here behind `TestClient` (no process, no network, no database). The app
carries the seeded fast-track catalog with its lexical projection, three bound lanes, the
conformance Model Catalog, one bound sandbox profile and the real manifest compile service over
that catalog, so the launch section compiles every template. Two Workflow Types are published
without being projected, as on an installation whose Search Projection was never built for
them, and one manifest's lowered definitions are published beside them.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi.testclient import TestClient

from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    MissionManifestService,
)
from mission_control.application.guide.mission_templates import TEMPLATE_IDS
from mission_control.application.guide.pages import TOPIC_IDS
from mission_control.application.resolution.registries import ApplicationRegistry, ModelCatalog
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.application.selection.workspace import SelectionWorkspace
from mission_control.bootstrap.guide import compose_guide
from mission_control.bootstrap.lanes import SESSION_LANES, describe_only_registry
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.interfaces.http.guide import router as guide_router
from mission_control.interfaces.http.lanes import router as lanes_router
from mission_control.interfaces.http.models import router as models_router
from mission_control.interfaces.http.selection import router as selection_router
from mission_control.interfaces.mcp.guide_tools import server_tool_listing
from mission_control.interfaces.mcp.operator_server import (
    OPERATOR_MCP_PATH,
    BearerPrincipalGate,
    create_operator_server,
)
from tests.conformance.resolution.fixtures import APPLICATIONS, MODELS
from tests.fixtures.catalog.fast_track_catalog import NOW, fast_track_catalog
from tests.fixtures.catalog_http import INSTALLATION, TENANT, catalog_harness
from tests.unit.guide.support import (
    OPERATOR_REGISTRIES,
    SANDBOXES,
    lowered_rows,
    workspace_entries,
)
from tests.unit.selection.test_selection_workspace import NARROW_WORKFLOW, OPEN_WORKFLOW

ROOT = Path(__file__).resolve().parents[3]
BOUND_LANES = ("deep_agents", "cursor_local", "claude_agent_sdk")
# What the evaluation asks, one check each, beside one compile per template.
QUESTIONS = 23


def _evaluation() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "consumer_surface_eval", ROOT / "scripts" / "consumer_surface_eval.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve their annotations through `sys.modules`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def _catalog() -> tuple[Any, Any]:
    definitions, search = await fast_track_catalog()
    for row in (OPEN_WORKFLOW, NARROW_WORKFLOW, *lowered_rows()):
        await definitions.publish(row.definition, "fixture", NOW, 0)
    return definitions, search


def _application() -> Any:
    definitions, search = asyncio.run(_catalog())
    permissions = frozenset({"catalog.read", "mission.read"})
    harness = catalog_harness(definitions, search, permissions)
    app = harness.app
    for router in (selection_router, guide_router, lanes_router, models_router):
        app.include_router(router)
    lanes = describe_only_registry(
        bound=BOUND_LANES,
        allow_unqualified=True,
        registrations=(deep_agents_lane(None), *SESSION_LANES.values()),
    )
    models = ModelCatalog(MODELS)
    applications = ApplicationRegistry(APPLICATIONS)
    workspace = SelectionWorkspace(
        application_id="biotech",
        lanes=lanes,
        models=models,
        applications=applications,
        admission=RuntimeResolver(lanes, applications, models, allow_unqualified_lanes=True),
        catalog_scope="global",
        search=search,
        definitions=definitions,
        **workspace_entries(),
    )
    key = (INSTALLATION, "biotech", TENANT)
    for name in OPERATOR_REGISTRIES:
        setattr(app.state, f"mission_control_{name}", {key: object()})
    app.state.mission_control_lanes = lanes
    app.state.mission_control_model_catalogs = {"biotech": models}
    app.state.mission_control_selection_workspaces = {key: workspace}
    app.state.mission_control_guides = {
        key: compose_guide(
            workspace=workspace, lanes=lanes, models=models, sandbox_profiles=SANDBOXES
        )
    }
    # The real compile over the same catalog: the launch section compiles every template.
    app.state.mission_control_manifest_services = {
        key: MissionManifestService(
            compiler=ManifestCompileService(
                definitions=definitions,
                search=search,
                programs=ManifestProgramCompiler(
                    definitions, ExtensionRegistry(), InMemoryPayloadStore()
                ),
            ),
            request_scope=harness.tenant_scope,
        )
    }
    server = create_operator_server(app.state)
    app.state.mission_control_tool_listing = asyncio.run(server_tool_listing(server))
    operator = server.http_app(
        path="/", transport="streamable-http", stateless_http=True, json_response=True
    )
    app.mount(
        OPERATOR_MCP_PATH,
        BearerPrincipalGate(operator, lambda _application_id, _authorization: harness.principal),
    )
    app.router.lifespan_context = lambda _app: operator.router.lifespan_context(operator)
    return app


def test_the_evaluation_scores_the_guide_the_listing_and_the_templates() -> None:
    evaluation = _evaluation()
    card = evaluation.Scorecard(url="http://testserver", application="biotech")
    with TestClient(_application()) as client:
        evaluation.evaluate(
            evaluation.Surface("http://testserver", "biotech", "unused", client=client), card
        )

    results = {(check.path, check.question): check for check in card.checks}
    failed = sorted(question for (_path, question), check in results.items() if not check.passed)
    # Everything a consumer asks is answered; the tool listing is still above the ceiling.
    assert failed == ["Is the tool listing small enough to read every session?"], [
        (check.question, check.observed) for check in card.checks if not check.passed
    ]
    assert len(card.checks) == QUESTIONS + len(TEMPLATE_IDS)
    assert evaluation.GUIDE_TOPICS == TOPIC_IDS

    def observed(path: str, question: str) -> str:
        return str(results[(path, question)].observed)

    assert "41 tools" in observed("mcp", "Is every tool self-explanatory?")
    assert "for 41 tools, mission_manifest_compile among them" in observed(
        "mcp", "Does describe answer for every tool?"
    )
    assert "prompts: 1; resources: 11" in observed("mcp", "Where do I start?")
    markdown = observed("mcp", "Does a page arrive as Markdown?")
    assert "11 pages; not Markdown: none" in markdown and "manifest ~" in markdown
    # The workflow systems, the templates, and the two published Workflow Types counted apart
    # from the one manifest's lowered Workflow Type.
    workflows = observed("mcp", "How do I look up all workflow types?")
    assert "workflow systems not named: none" in workflows
    assert "2 not lowered, 1 lowered and left out, 3 with include_lowered" in workflows
    assert "the page states ('2', '1')" in workflows
    lanes = observed("mcp", "How do I look up all provider cognition configurations?")
    assert all(profile in lanes for profile in BOUND_LANES)
    # The Workflow Types the projection does not hold are scanned, and the result says so
    # while the projected capabilities keep the catalog's own mode.
    search = observed("mcp", "Is a search ever silently empty?")
    assert "stated reason (notes or unavailable): ['skill', 'workflow', 'mcp server', 'hook']" in (
        search
    )
    assert "'skill': 'lexical'" in search
    assert "bound profiles ['research.standard']" in observed(
        "mcp", "Which sandbox profile do I name?"
    )
    assert str(list(TEMPLATE_IDS)) in observed("mcp", "Which mission templates can I start from?")
    # Each template, read through MCP, filled and compiled by the real compiler: never started.
    for template_id in TEMPLATE_IDS:
        compiled = observed("mcp", f"Does the `{template_id}` template compile?")
        assert "mission_manifest_compile: ok True, startable True" in compiled, compiled
        assert "sandbox research.standard" in compiled and "blockers: none" in compiled
    assert "`skill`" in observed("http", "What is in the catalog?")
    assert "4 prose answers and an unknown lane; differing: none" in observed(
        "http", "Does describe say the same thing over HTTP and MCP?"
    )
    report = evaluation.render(card)
    assert report.startswith(
        f"Consumer surface: {QUESTIONS + len(TEMPLATE_IDS) - 1} of "
        f"{QUESTIONS + len(TEMPLATE_IDS)} checks pass (biotech at"
    )

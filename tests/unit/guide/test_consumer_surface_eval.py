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
import json
import sys
from dataclasses import replace
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
from tests.support.capability_search import seeded_published
from tests.support.catalog_http import INSTALLATION, TENANT, catalog_harness
from tests.support.manifests.seeded_catalog import NOW, fast_track_catalog
from tests.support.unit.selection.selection_workspace import NARROW_WORKFLOW, OPEN_WORKFLOW
from tests.unit.guide.support import (
    OPERATOR_REGISTRIES,
    SANDBOX_DETAILS,
    SANDBOXES,
    lowered_rows,
    workspace_entries,
)

ROOT = Path(__file__).resolve().parents[3]
BOUND_LANES = ("deep_agents", "cursor_local", "claude_agent_sdk")
# What the evaluation asks without a run id, one check each, beside one compile per template.
QUESTIONS = 32


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
    # The capture server's later revisions, as an installation holds them: a Deep Agents node
    # mounts its newest revision's allowlist.
    # An id a later revision added (chain_write's row) is already its first published row here.
    first = {
        item.ref.logical_id for item in seeded_published(("common",)) if item.ref.revision == 1
    }
    for item in seeded_published(("common",), every_revision=True):
        logical_id = item.ref.logical_id
        if logical_id.startswith("mcp.knowledge-capture") and item.ref.revision > 1:
            if logical_id in first:
                await definitions.publish(item.definition, "seed", NOW, item.ref.revision - 1)
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
    # As an API that composes external discovery and candidate inspection beside its search.
    app.state.mission_control_catalog_services = {
        key: replace(harness.service, discovery=object(), inspection=object())  # type: ignore[arg-type]
    }
    app.state.mission_control_lanes = lanes
    app.state.mission_control_model_catalogs = {"biotech": models}
    app.state.mission_control_selection_workspaces = {key: workspace}
    app.state.mission_control_guides = {
        key: compose_guide(
            workspace=workspace,
            lanes=lanes,
            models=models,
            sandbox_profiles=SANDBOXES,
            sandbox_details=SANDBOX_DETAILS,
            external_discovery=True,
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
    # Everything a consumer asks is answered, the tool listing inside its ceiling included.
    assert failed == [], [
        (check.question, check.observed) for check in card.checks if not check.passed
    ]
    # Without a run id the six checks that read a run are not run.
    assert len(card.checks) == QUESTIONS + len(TEMPLATE_IDS)
    assert evaluation.GUIDE_TOPICS == TOPIC_IDS

    def observed(path: str, question: str) -> str:
        return str(results[(path, question)].observed)

    assert "47 tools" in observed("mcp", "Is every tool self-explanatory?")
    assert "for 47 tools, mission_manifest_compile among them" in observed(
        "mcp", "Does describe answer for every tool?"
    )
    listing = observed("mcp", "Is the tool listing small enough to read every session?")
    assert "entries with an `outputSchema`: 0; with `_meta`: 3" in listing
    who = observed("mcp", "Who am I, and what do I hold?")
    assert "actor reader" in who and "reviews_as ['reader']" in who
    assert "fields absent: none" in who and "the same document: True" in who
    assert "prompts: 1; resources: 11" in observed("mcp", "Where do I start?")
    markdown = observed("mcp", "Does a page arrive as Markdown?")
    assert "11 pages; not Markdown: none" in markdown and "manifest ~" in markdown
    assert "structured content repeating the page: none" in markdown
    discovery = observed(
        "mcp", "Can I look for a capability the catalog lacks, and pin one it has?"
    )
    assert "absent of" in discovery and ": none; mission_whoami" in discovery
    assert "server.external_discovery: composed" in discovery
    mounting = observed("mcp", "Which Knowledge Services tools can a research node mount?")
    assert (
        "row: revision 3; lanes `deep_agents`" in mounting and "tools mounted 23 of 42" in mounting
    )
    assert "research tools missing: none" in mounting and "withheld tools handed: none" in mounting
    serving = observed("mcp", "What must the installation serve for the capture server?")
    assert "MCP_SERVER_ENDPOINTS" in serving and "VERIFY_EXECUTOR_TOKEN" in serving
    sandbox = observed("mcp", "What does each sandbox profile give me?")
    assert "sandbox:research.standard: backend docker" in sandbox
    assert "no line in mission_guide('manifest'): none" in sandbox
    # A capability written as a search resolves to the capability it names, and the
    # resolution says who answered (this catalog's projection is built: `lexical`).
    searched = observed("mcp", "Does a manifest whose capability is a `search` entry compile?")
    assert "ok True" in searched and "resolved to tool.knowledge-submit-output@" in searched
    assert "search_mode lexical" in searched
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
    # The interview is recorded: the page shows the block, every template carries one, and
    # a compile reads the brief back (who asked is the caller) and only warns without one.
    interview = observed("mcp", "Does the interview end in a recorded brief?")
    assert "shows a `brief:` block: True; brief fields not named: none" in interview
    assert "still says no interview record is persisted: False" in interview
    carried = observed("mcp", "Does every mission template carry a brief?")
    assert "templates without a `brief` block: none" in carried
    assert "the brief read back: none" in carried
    assert "'research-report': 'research'" in carried
    assert "'system-improvement': 'system'" in carried
    sealed = observed("mcp", "Is the brief sealed with the mission and read back?")
    assert "requested_by reader (caller reader)" in sealed
    assert "without its brief: ok True, warning brief_missing: True, blockers: none" in sealed
    assert "`skill`" in observed("http", "What is in the catalog?")
    assert "4 prose answers and an unknown lane; differing: none" in observed(
        "http", "Does describe say the same thing over HTTP and MCP?"
    )
    report = evaluation.render(card)
    assert report.startswith(
        f"Consumer surface: {QUESTIONS + len(TEMPLATE_IDS)} of "
        f"{QUESTIONS + len(TEMPLATE_IDS)} checks pass (biotech at"
    )


class _RunSurface:
    """One completed run as the evaluation reads it: a canned answer per tool."""

    def __init__(self, system: str, brief: dict[str, Any] | None) -> None:
        request = {
            "system": {"ref": "frame-body://sha256:s", "body": {"content": system}},
            "messages": [],
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._answers: dict[str, dict[str, Any]] = {
            "mission_run_outputs": {"obligations": [], "accepted": []},
            "mission_run_inspect": {"cost": {}, **({"brief": brief} if brief else {})},
            "mission_run_points": {"entries": []},
            "mission_run_transcript": {
                "entries": [{"kind": "model_request", "body_excerpt": json.dumps(request)}]
            },
        }

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        self.calls.append((name, arguments))
        return "", self._answers[name]

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.call(name, arguments)[1]

    def get(self, path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
        return 404, {}


def test_a_run_is_scored_on_its_brief_and_on_the_card_its_first_request_carried() -> None:
    evaluation = _evaluation()
    brief = {
        "purpose": "system",
        "request": "Show me that a first mission runs end to end here.",
        "answers": [{"question": "Who reviews it?", "answer": "I do."}],
        "requested_by": "reader",
    }
    card = (
        "# Purpose card\n\nMission Control wrote this card.\n\n## Why\n- Purpose: system (x)\n"
        f"```data source=brief.request trust=admitted_input\n{brief['request']}\n```\n\n"
        "## Your part\n- Node `write`\n- Outputs you owe:\n  - `write.result` (text, required)\n"
        '    - Accepted when (a reviewer accepts it): "Three sentences."\n\n'
        "## What you were given\n- Budget: none declared.\n\n"
        "## Rules\n" + "\n".join(evaluation.PURPOSE_CARD_RULES) + "\n\nThe host line."
    )
    brief_question = "What was the run asked to do, and by whom?"
    card_question = "Was the node told why the mission exists and what its part is?"

    def scored(system: str, sealed: dict[str, Any] | None) -> tuple[Any, dict[str, Any]]:
        surface = _RunSurface(system, sealed)
        scorecard = evaluation.Scorecard(url="http://testserver", application="biotech")
        evaluation._evaluate_run(surface, scorecard, "run-1", {})
        return surface, {check.question: check for check in scorecard.checks}

    surface, told = scored(card, brief)
    _surface, untold = scored("The host line.", None)

    # Four checks read the run's outputs, cost, transcript and state; two read its brief.
    assert len(told) == 6
    assert told[brief_question].passed and told[card_question].passed
    assert "purpose system" in told[brief_question].observed
    assert "requested_by reader" in told[brief_question].observed
    observed = told[card_question].observed
    assert "opens with the purpose card: True; quotes the brief's request: True" in observed
    assert "rules present: 4 of 4; names the purpose system: True" in observed
    # How many of its outputs' acceptance criteria the node was told is recorded, not scored.
    assert observed.endswith("acceptance lines under its outputs: 1")
    assert untold[card_question].observed.endswith("acceptance lines under its outputs: 0")
    # The card is read through the transcript tool: the first model request, bodies inlined.
    assert (
        "mission_run_transcript",
        {"run_id": "run-1", "kinds": ["model_request"], "limit": 1, "full": True},
    ) in surface.calls
    # A run without a brief, whose prompt carries no card, fails both and says why.
    assert not untold[brief_question].passed and not untold[card_question].passed
    assert "absent (the run's mission records no brief)" in untold[brief_question].observed
    assert "opens with the purpose card: False" in untold[card_question].observed
    # A system prompt in content parts reads the same as one string.
    parts = {
        "entries": [
            {
                "body_excerpt": json.dumps(
                    {
                        "system": {
                            "body": {
                                "content": [
                                    {"type": "text", "text": "# Purpose card\n"},
                                    {"type": "text", "text": "rest"},
                                ]
                            }
                        }
                    }
                )
            }
        ]
    }
    assert evaluation._system_prompt(parts) == "# Purpose card\nrest"
    assert evaluation._system_prompt({"entries": []}) == ""
    assert evaluation._system_prompt({"entries": [{"body_excerpt": "not json"}]}) == ""

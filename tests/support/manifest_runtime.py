"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_manifest_launch_production.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI

from mission_control.adapters.capabilities.capability_pins import (
    CapabilityPinError,
    PinnedSkill,
    PinnedTool,
)
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
from mission_control.adapters.temporal.submission import TemporalWorkflowSubmitter
from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchInputAuthor
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
    MissionManifestService,
)
from mission_control.application.chains.relay import ChainRelayPump, ChainRelayReport
from mission_control.application.execution.service import RunControlService
from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
)
from mission_control.bootstrap.manifests import compose_chain_relay_pump
from mission_control.bootstrap.settings import get_settings
from mission_control.bootstrap.technical_api import api
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from mission_control.interfaces.http.missions import router as missions_router
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.manifest_runtime import AUTHOR, ChainScript
from tests.fixtures.models import model_binding
from tests.fixtures.rrm009_production_harness import ProductionStack
from tests.fixtures.rrm009_production_stack import AGENT_COGNITIVE_QUEUE, TechnicalBinding
from tests.support.ids import INSTALLATIONS, SCOPE
from tests.unit.authoring.manifest_launch_fixture import (
    deep_agents_chain,
    fixture_bindings,
    pubmed_bound,
)

ROOT = Path(__file__).resolve().parents[2]
MISSION_2 = (
    ROOT / "tests/fixtures/manifests/fast-track/02-research-ingestion-cursor-cloud-chain.yml"
)


KEY = parse_request_scope(SCOPE)
OWNER_KEY = (KEY.installation_id, KEY.application_id, KEY.tenant_id)
SCOPED = "installation_id = $1 AND application_id = $2 AND tenant_id = $3"
PREFIX = f"/v1/applications/{KEY.application_id}"
# FIXTURE catalog schema for every declared output here: the document `ChainModel` writes.
CLAIM_DOCUMENT = {
    "type": "object",
    "required": ["obligation", "iteration", "rows"],
    "properties": {
        "obligation": {"type": "string"},
        "iteration": {"type": "integer"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim", "citation"],
                "properties": {"claim": {"type": "string"}, "citation": {"type": "string"}},
            },
        },
    },
}
OUTPUT_SCHEMAS = dict.fromkeys(
    ("claim_table@1", "source_manifest@1", "ingestion_receipt@1", "ingestion_summary@1"),
    CLAIM_DOCUMENT,
)


def evaluable(manifest_yaml: str) -> str:
    """FIXTURE transform: keep only what this deployment can evaluate and the FIXTURE writes.

    No assessment evaluator is bound, so assessment criteria are dropped, and a compound
    acceptance keeps its schema operand. A Goal Loop declares only its first output: `ChainModel`
    writes one document and names no output bindings, and several Goal Directed outputs need the
    deployment's named executor-observation schema, which these bindings do not configure.
    Criteria citing an undeclared output go with it. Every remaining schema is in
    `OUTPUT_SCHEMAS`.
    """

    document = load_manifest_yaml(manifest_yaml)
    for mission in document.get("missions") or [document["mission"]]:
        program = mission["program"]
        dropped: set[str] = set()
        if program["behavior"] == "goal_loop" and program.get("outputs"):
            dropped = {item["name"] for item in program["outputs"][1:]}
            program["outputs"] = program["outputs"][:1]
        for goal in mission["goals"]:
            criteria = []
            for criterion in goal.get("criteria", ()):
                acceptance = criterion["acceptance"]
                if "assessment" in acceptance or dropped & set(criterion.get("evidence", ())):
                    continue
                if "all" in acceptance:
                    (acceptance,) = [item for item in acceptance["all"] if "schema" in item]
                criteria.append({**criterion, "acceptance": acceptance})
            goal["criteria"] = criteria
    return canonical_manifest_bytes(document).decode("utf-8")


async def pubmed_digest() -> str:
    """The catalog revision ``pubmed literature retrieval`` resolves to (fast-track fixture)."""

    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    compilation = await service.compile(
        deep_agents_chain(MISSION_2.read_text(encoding="utf-8")),
        ManifestScope(request_scope=SCOPE, actor_id="owner", at=datetime.now(UTC)),
    )
    assert compilation.ok, [item.message for item in compilation.report.blockers]
    (capability,) = [
        item for item in compilation.definitions[0].capabilities if item.alias == "pubmed"
    ]
    assert capability.resolved is not None and capability.resolved.digest is not None
    return capability.resolved.digest


async def write_bindings(path: Path, technical: TechnicalBinding) -> None:
    """FIXTURE deployment bindings: `frontier.default` only (`frontier.long_context` is
    deliberately unbound), both sandbox profiles, pubmed on the qualification MCP server."""

    (server,) = technical.binding.mcp_servers
    bindings = fixture_bindings(task_queue=AGENT_COGNITIVE_QUEUE).model_copy(
        update={
            "model_profiles": {"frontier.default": model_binding(technical.binding.model)},
            "sandbox_profiles": {
                "research.standard": technical.binding.sandbox,
                "ingestion.standard": technical.binding.sandbox,
            },
        }
    )
    bound = pubmed_bound(bindings, await pubmed_digest(), server)
    await asyncio.to_thread(path.write_text, bound.model_dump_json(indent=2), encoding="utf-8")


def host_pins(path: Path) -> Path:
    """FIXTURE pin file: the deployment pins minus the tool and Skill pins that do not resolve
    on this host (a git worktree's parent has no ``.tools``/``.agents``; a developer workspace
    may carry a re-installed Skill whose bytes drifted from the reviewed pin). No manifest here
    selects a tool or Skill; every other pin is unchanged, and pin drift itself stays covered by
    the capability-pin tests, which fail closed."""

    source = get_settings().capability_pins_path
    document = json.loads(source.read_text(encoding="utf-8"))

    def resolves(verify: Callable[[], object]) -> bool:
        try:
            verify()
        except CapabilityPinError:
            return False
        return True

    document["tools"] = [
        item
        for item in document.get("tools", ())
        if resolves(PinnedTool.model_validate(item).verify_entrypoint)
    ]
    document["skills"] = [
        item
        for item in document.get("skills", ())
        if resolves(PinnedSkill.model_validate(item).bundle)
    ]
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


class CountingAuthor:
    """Delegates to the production author; counts what the relay asked of it."""

    def __init__(self, author: ManifestLaunchInputAuthor) -> None:
        self.author = author
        self.calls: list[str] = []

    async def family_input(self, **values: Any) -> dict[str, Any]:
        self.calls.append(values["run_id"])
        return await self.author.family_input(**values)


@dataclass
class LaunchStack:
    stack: ProductionStack
    script: ChainScript
    author: ManifestLaunchInputAuthor
    app: FastAPI
    model_log: list[dict[str, Any]] = field(default_factory=list)


def missions_app(lifecycle: MissionManifestService) -> FastAPI:
    installation_id, project_ref = INSTALLATIONS[KEY.application_id]
    registry = ApplicationRegistry(
        (
            ApplicationBinding.seal(
                application_id=KEY.application_id,
                installation_id=installation_id,
                binding_version="1",
                supabase_project_ref=project_ref,
                database_secret_ref="TEST_DATABASE_URL",
                accepted_issuers={"https://issuer.invalid"},
                accepted_audiences={"authenticated"},
                required_component_version="1",
            ),
        )
    )
    registry.observe(
        KEY.application_id,
        InstallationObservation(installation_id, KEY.application_id, project_ref, frozenset({"1"})),
    )
    app = FastAPI()
    app.include_router(missions_router)
    app.state.mission_control_registry = registry
    app.state.mission_control_manifest_services = {OWNER_KEY: lifecycle}
    app.dependency_overrides[get_mission_principal] = lambda: MissionPrincipal(
        installation_id=installation_id,
        application_id=KEY.application_id,
        tenant_id=KEY.tenant_id,
        issuer="https://issuer.invalid",
        audiences=frozenset({"authenticated"}),
        actor=AUTHOR,
        sponsorship_refs=frozenset({"sponsorship:test"}),
    )
    return app


async def post(app: FastAPI, path: str, body: dict[str, Any]) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mission-control"
    ) as client:
        return await client.post(f"{PREFIX}{path}", json=body)


async def submit(app: FastAPI, manifest_yaml: str) -> dict[str, Any]:
    response = await post(
        app, "/missions:submit", {"manifest_yaml": manifest_yaml, "request_id": str(uuid4())}
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


async def fetch(stack: ProductionStack, query: str, *args: Any) -> list[Any]:
    async with stack.owner_pool.acquire() as connection:
        return list(await connection.fetch(query, *OWNER_KEY, *args))


async def root_executions(stack: ProductionStack, run_key: str) -> list[str]:
    workflow_id = f"belllabs-run/{run_key}"
    return [
        item.run_id async for item in stack.client.list_workflows(f"WorkflowId = '{workflow_id}'")
    ]


def relay_pump(stack: ProductionStack, author: CountingAuthor) -> ChainRelayPump:
    """The production relay composition over the test stack's root submitter."""

    queues = coordinator_task_queues(stack.settings.temporal_task_queue)
    return compose_chain_relay_pump(
        stack.worker_pool,
        settings=stack.settings,
        author=author,
        run_control=cast(RunControlService, api.state.run_control_service),
        submitter=TemporalWorkflowSubmitter.for_production(
            stack.client,
            stagegraph_task_queue=queues.stagegraph,
            goal_directed_task_queue=queues.goal_directed,
            search_attribute_policy="required",
        ),
        request_scopes=[SCOPE],
        lease_owner="mp02-relay",
    )


@contextlib.asynccontextmanager
async def pumping(pump: ChainRelayPump) -> AsyncIterator[None]:
    stop = asyncio.Event()
    task = asyncio.create_task(pump.run(stop))
    try:
        yield
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=30)


def delivered(reports: tuple[ChainRelayReport, ...]) -> list[str]:
    return [key for report in reports for key in report.delivered]

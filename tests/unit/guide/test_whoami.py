"""Who the caller is, on every transport, and the refusals that name what it holds.

`whoami` reads the verified principal and its operator grant: the actor, the tenant, the
permissions, the sponsorship and approval refs a fork binds, the reviewer names a Human Task
is resolved as, and what this server composed for the controls its lanes declare. HTTP
(`GET whoami`), `missionctl whoami` and the MCP tool `mission_whoami` answer one document. A
refusal about the principal (`not_reviewer`, a sponsorship it does not hold, a lane whose
saved state this server cannot read) names what was required and what is held.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, Context, FastMCP

import mission_control.interfaces.cli.main as cli
from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.application.execution.harness.time_travel import (
    TimeTravelRegistry,
    TimeTravelUnsupported,
)
from mission_control.application.guide.whoami import PrincipalFacts, server_facts, whoami
from mission_control.application.human_tasks.service import HumanTaskRejected, not_reviewer
from mission_control.application.recovery.run_forks import snapshot_refusal
from mission_control.application.resolution.registries import ModelCatalog
from mission_control.bootstrap.guide import compose_guide
from mission_control.bootstrap.lanes import SESSION_LANES, describe_only_registry
from mission_control.contracts.contracts import MissionControlRejected, grant_not_held
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.policies.forks import ForkRejected
from mission_control.domain.programs.human_gate import reviewer_roles, reviews_as
from mission_control.interfaces.http.guide import prefers_markdown
from mission_control.interfaces.http.guide import router as guide_router
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    get_mission_principal,
    principal_request_scope,
)
from mission_control.interfaces.mcp.coordinator_server import _principal_call
from mission_control.interfaces.mcp.guide_tools import (
    WHOAMI_TOOL,
    ScopedGuide,
    register_guide_tools,
)
from mission_control.interfaces.mcp.human_task_tools import domain_error as human_task_error
from mission_control.interfaces.mcp.operator_server import operator_principal
from mission_control.interfaces.mcp.run_control_tools import domain_error as run_control_error
from tests.conformance.resolution.fixtures import MODELS
from tests.support.catalog_http import INSTALLATION, TENANT, CatalogHarness, catalog_harness
from tests.unit.guide.support import _workspace, full_guide, stub_guide

PERMISSIONS = frozenset(
    {"catalog.read", "workflow_run.read", "workflow_run.fork", "reviewer:owner", "reviewer:qa"}
)
SPONSORSHIPS = frozenset({"sponsor:mission-alpha", "sponsor:lab"})
APPROVALS = frozenset({"approval:budget-2026"})


def _principal(permissions: frozenset[str] = PERMISSIONS) -> MissionPrincipal:
    return MissionPrincipal(
        installation_id=INSTALLATION,
        application_id="biotech",
        tenant_id=TENANT,
        issuer="https://issuer.invalid",
        audiences={"authenticated"},
        actor=ActorContext(
            actor_id="operator:probe",
            permissions=set(permissions),
            authority_refs=frozenset({"authority:lab"}),
        ),
        sponsorship_refs=SPONSORSHIPS,
        approval_refs=APPROVALS,
    )


@pytest.fixture
def harness() -> CatalogHarness:
    harness = catalog_harness(InMemoryDefinitionRepository(), None)
    harness.app.include_router(guide_router)
    harness.app.state.mission_control_guides = {(INSTALLATION, "biotech", TENANT): stub_guide()}
    harness.app.dependency_overrides[get_mission_principal] = _principal
    return harness


class _Resolver:
    def __init__(self, principal: MissionPrincipal) -> None:
        self.principal = operator_principal(principal)

    async def resolve(self, _context: Context) -> Any:
        return self.principal


def _server(harness: CatalogHarness, principal: MissionPrincipal) -> FastMCP:
    server = FastMCP("whoami test")
    guide = harness.app.state.mission_control_guides[(INSTALLATION, "biotech", TENANT)]
    register_guide_tools(
        server,
        ScopedGuide({principal_request_scope(principal): guide}),
        _Resolver(principal),
        call=_principal_call,
    )
    return server


# -- the document --------------------------------------------------------------------------------


def test_whoami_is_the_verified_principal_and_its_grant() -> None:
    document = whoami(
        PrincipalFacts(
            actor_id="operator:probe",
            installation_id=str(INSTALLATION),
            application_id="biotech",
            tenant_id=str(TENANT),
            request_scope="mc/x/biotech/y",
            permissions=PERMISSIONS,
            sponsorship_refs=SPONSORSHIPS,
            approval_refs=APPROVALS,
        )
    )

    assert document.schema_version == "mc.whoami.v1" and document.actor_id == "operator:probe"
    assert document.permissions == tuple(sorted(PERMISSIONS))
    assert document.sponsorship_refs == ("sponsor:lab", "sponsor:mission-alpha")
    assert document.approval_refs == ("approval:budget-2026",)
    # A reviewer entry is satisfied by the actor id or by `reviewer:<name>`.
    assert document.reviewer_roles == ("owner", "qa")
    assert document.reviews_as == ("operator:probe", "owner", "qa")
    assert "server" not in document.model_dump(mode="json")
    assert reviewer_roles({"reviewer:", "catalog.read"}) == ()
    assert reviews_as("owner", {"reviewer:owner"}) == ("owner",)


def test_server_facts_say_which_lanes_state_this_process_reads_and_what_is_missing() -> None:
    lanes = describe_only_registry(
        bound=("deep_agents", "cursor_local"),
        allow_unqualified=True,
        registrations=tuple(SESSION_LANES.values()),
    )
    registry = TimeTravelRegistry()
    registry.mark_unavailable("deep_agents", "no runtime checkpoint DSN is configured")

    class _Lane:
        lane_profile = "cursor_local"

    registry.register(_Lane())  # type: ignore[arg-type]
    facts = server_facts(
        lanes,
        registry,
        external_discovery=True,
        external_discovery_prerequisite="skill discovery starts a subprocess this loop cannot",
    )
    rows = {row.lane_profile: row for row in facts.time_travel}
    # A prerequisite is a fact about composed discovery only, and absent where none is missing.
    assert facts.external_discovery_prerequisite == (
        "skill discovery starts a subprocess this loop cannot"
    )
    not_composed = server_facts(lanes, registry, external_discovery_prerequisite="unused")
    assert not_composed.external_discovery_prerequisite is None
    assert "external_discovery_prerequisite" not in not_composed.model_dump(mode="json")

    assert rows["cursor_local"].state_as_of == "readable"
    assert rows["cursor_local"].prerequisite is None
    assert rows["deep_agents"].state_as_of == "not_composed"
    assert rows["deep_agents"].declared_read == "R3"
    assert rows["deep_agents"].prerequisite == "no runtime checkpoint DSN is configured"
    assert facts.external_discovery == "composed"
    # The registry's refusal carries the same sentence, and registering the lane clears it.
    refusal = registry.unsupported("deep_agents")
    assert isinstance(refusal, TimeTravelUnsupported)
    assert refusal.prerequisite == "no runtime checkpoint DSN is configured"
    with pytest.raises(TimeTravelUnsupported) as raised:
        registry.lane("deep_agents")
    assert raised.value.prerequisite == refusal.prerequisite

    class _Deep:
        lane_profile = "deep_agents"

    registry.register(_Deep())  # type: ignore[arg-type]
    assert registry.prerequisite("deep_agents") is None
    # A process that composed no registry names that, never silence.
    bare = {row.lane_profile: row for row in server_facts(lanes, None).time_travel}
    assert bare["deep_agents"].prerequisite and bare["deep_agents"].state_as_of == "not_composed"


async def test_the_guide_pages_use_whoami_and_say_what_this_server_reads() -> None:
    lanes_guide = full_guide()
    index = (await lanes_guide.index("mcp")).markdown
    observe = (await lanes_guide.topic("observe", "mcp")).markdown
    control = (await lanes_guide.topic("control", "mcp")).markdown
    capabilities = (await lanes_guide.topic("capabilities", "mcp")).markdown

    assert "First call `mission_whoami`" in index and "sponsorship refs a fork needs" in index
    assert "`mission_whoami` returns `reviews_as`" in observe
    assert "`mission_run_output_content`" in observe and "`cost`" in observe
    assert "on `stale_version` resend once" in control
    assert "`sponsorship_ref` you hold (`mission_whoami`)" in control
    assert "A fork needs a Snapshot, taken only at a safe boundary" in control
    assert "This server reads state at a point for" in control
    assert "`pin_capability`" in capabilities and "`discover_mcp_servers`" in capabilities
    assert "it cannot be pinned, bound or run" in capabilities
    cli_index = (await lanes_guide.index("cli")).markdown
    assert "`missionctl whoami`" in cli_index
    assert "`GET whoami`" in (await lanes_guide.index("http")).markdown


async def test_the_control_page_names_a_lane_this_server_cannot_read() -> None:
    lanes = describe_only_registry(bound=("deep_agents",), allow_unqualified=True, registrations=())
    registry = TimeTravelRegistry()
    registry.mark_unavailable("deep_agents", "no runtime checkpoint DSN is configured")
    models = ModelCatalog(MODELS)
    guide = compose_guide(
        workspace=_workspace(lanes, models, catalog=True),
        lanes=lanes,
        models=models,
        time_travel=lambda: registry,
    )

    control = (await guide.topic("control", "mcp")).markdown

    assert "This server reads state at a point for no lane." in control
    assert "Not for `deep_agents`: no runtime checkpoint DSN is configured." in control


# -- the three transports ------------------------------------------------------------------------


async def test_whoami_is_one_document_on_http_cli_and_mcp(
    harness: CatalogHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from_http = harness.client.get("/v1/applications/biotech/whoami")
    assert from_http.status_code == 200, from_http.text
    document = from_http.json()
    assert document["actor_id"] == "operator:probe"
    assert document["tenant_id"] == str(TENANT) and document["application_id"] == "biotech"
    assert document["sponsorship_refs"] == sorted(SPONSORSHIPS)
    assert document["approval_refs"] == sorted(APPROVALS)
    assert document["authority_refs"] == ["authority:lab"]
    assert document["reviews_as"] == ["operator:probe", "owner", "qa"]
    assert document["request_scope"] == principal_request_scope(_principal())

    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "test-token")
    monkeypatch.setattr(cli.httpx, "Client", lambda **_kwargs: TestClient(harness.app))
    assert cli.main(["whoami", "--application", "biotech"]) == 0
    assert json.loads(capsys.readouterr().out) == document

    async with Client(_server(harness, _principal())) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        from_mcp = await mcp.call_tool(WHOAMI_TOOL, {})
    assert "sponsorship" in (tools[WHOAMI_TOOL].description or "")
    envelope = from_mcp.structured_content
    assert envelope is not None and envelope["ok"] is True
    assert envelope["data"] == document


async def test_whoami_needs_only_an_authenticated_principal(harness: CatalogHarness) -> None:
    """A principal without `catalog.read` cannot read the guide and still learns what it
    holds: that is how it finds out which permission it lacks."""

    bare = _principal(frozenset({"workflow_run.read"}))
    harness.app.dependency_overrides[get_mission_principal] = lambda: bare

    assert harness.client.get("/v1/applications/biotech/guide").status_code == 403
    answered = harness.client.get("/v1/applications/biotech/whoami")
    assert answered.status_code == 200
    assert answered.json()["permissions"] == ["workflow_run.read"]
    assert answered.json()["reviews_as"] == ["operator:probe"]
    async with Client(_server(harness, bare)) as mcp:
        guide = await mcp.call_tool("mission_guide", {})
        who = await mcp.call_tool(WHOAMI_TOOL, {})
    assert guide.structured_content["error"]["code"] == "FORBIDDEN"  # type: ignore[index]
    assert "mission_whoami" in guide.structured_content["error"]["message"]  # type: ignore[index]
    assert who.structured_content["data"]["permissions"] == ["workflow_run.read"]  # type: ignore[index]
    # Another application's principal is refused before any guide is read.
    assert harness.client.get("/v1/applications/other/whoami").status_code == 403


def test_accept_markdown_is_preferred_only_when_it_ranks_first() -> None:
    assert prefers_markdown("text/markdown")
    assert prefers_markdown("text/markdown, application/json;q=0.5")
    assert prefers_markdown("text/markdown;q=0.9, */*;q=0.1")
    assert not prefers_markdown(None)
    assert not prefers_markdown("application/json")
    assert not prefers_markdown("*/*")
    assert not prefers_markdown("application/json, text/markdown")
    assert not prefers_markdown("text/markdown;q=0")
    assert not prefers_markdown("text/markdown;q=0.2, application/json;q=0.8")


# -- refusals that name what the principal holds -------------------------------------------------


def test_not_reviewer_names_the_reviewers_required_and_what_the_principal_reviews_as() -> None:
    actor = ActorContext(actor_id="operator:probe", permissions=frozenset({"reviewer:qa"}))

    refused = not_reviewer(("owner", "lead"), actor)

    assert isinstance(refused, HumanTaskRejected) and refused.code == "not_reviewer"
    assert "needs one of owner, lead" in str(refused)
    assert "reviews as operator:probe, qa" in str(refused)
    assert refused.details == {
        "required_reviewers": "owner,lead",
        "principal_reviews_as": "operator:probe,qa",
    }
    envelope = human_task_error(refused).envelope()
    assert envelope.code == "FORBIDDEN"
    assert envelope.details == {"code": "not_reviewer", **refused.details}


def test_a_sponsorship_the_principal_does_not_hold_names_what_it_holds() -> None:
    refused = grant_not_held("sponsorship", ("sponsor:other",), SPONSORSHIPS)
    none_held = grant_not_held("approval", ("approval:a", "approval:b"), ())

    assert isinstance(refused, MissionControlRejected) and refused.code == "unauthorized"
    assert "sponsorship sponsor:other was not granted" in str(refused)
    assert "it holds sponsor:lab, sponsor:mission-alpha" in str(refused)
    assert refused.details == {
        "grant": "sponsorship_refs",
        "required": "sponsor:other",
        "held": "sponsor:lab,sponsor:mission-alpha",
    }
    assert "it holds no approval ref" in str(none_held)
    envelope = run_control_error(refused).envelope()
    assert envelope.code == "FORBIDDEN" and envelope.details["held"] == refused.details["held"]


def test_a_stale_command_carries_the_values_to_resend_with() -> None:
    stale = MissionControlRejected(
        "stale_version",
        "run version changed",
        frontier={"version": 9, "execution_generation": 2, "phase": "executing"},
    )

    envelope = run_control_error(stale).envelope()

    assert envelope.code == "CONFLICT"
    assert envelope.details == {
        "code": "stale_version",
        "version": "9",
        "execution_generation": "2",
        "phase": "executing",
    }
    assert "current version 9, execution_generation 2" in envelope.message
    assert "resend once" in envelope.message


def test_a_fork_without_a_safe_boundary_says_what_holds_it_and_when_it_is_possible() -> None:
    held = ForkRejected(
        "snapshot_not_quiescent",
        "the run is not at a declared safe boundary (EXEC-016)",
        reasons=("stage_active:review", "stage_liability_open:review#1", "unit_unsettled:u1"),
    )
    never_started = ForkRejected(
        "unsupported_boundary", "no stage settlement has been accepted yet"
    )

    message = snapshot_refusal(held)

    assert "no safe Snapshot to fork from and none can be taken now" in message
    assert "stage review is active (a Human Gate stays active until its Human Task is" in message
    assert "stage work review#1 is admitted and not yet settled" in message
    assert "a fork from a cognition point included" in message
    assert "once the work above settles" in message and "every seedable cognition point" in message
    assert "no stage settlement has been accepted yet" in snapshot_refusal(never_started)
    # Over MCP the reasons travel beside the message, as the HTTP route's `reasons` do.
    refusal = ForkRejected("CHECKPOINT_INVALID", message, reasons=(held.code, *held.reasons))
    envelope = run_control_error(refusal).envelope()
    assert envelope.code == "CONFLICT" and envelope.details["code"] == "CHECKPOINT_INVALID"
    assert envelope.details["reasons"].startswith("snapshot_not_quiescent,stage_active:review")

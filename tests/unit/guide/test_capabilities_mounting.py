"""The `capabilities` guide page says what a node can mount, from the catalog and the lanes.

Composed like the API composes the guide with every lane bound, over one installation's seeded
catalog (common and application seeds, every revision): each MCP server's row is its newest
revision's lanes, tool count, secret names and what the installation must serve; each plugin's
row names its members; and the member rule of a member-expanding lane is the lane
declaration's.
"""

from __future__ import annotations

from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.application.resolution.registries import ModelCatalog
from mission_control.bootstrap.guide import compose_guide
from mission_control.bootstrap.lanes import SESSION_LANES, describe_only_registry
from mission_control.domain.execution.lanes import LANE_PROFILES
from tests.conformance.resolution.fixtures import MODELS
from tests.fixtures.capability_search_catalog import seeded_published
from tests.unit.guide.support import SANDBOX_DETAILS, SANDBOXES, _workspace, full_guide

APPLICATION = "ai-engineer"


async def _capabilities_page() -> str:
    lanes = describe_only_registry(
        bound=LANE_PROFILES,
        allow_unqualified=False,
        registrations=(deep_agents_lane(None), *SESSION_LANES.values()),
    )
    models = ModelCatalog(MODELS)
    rows = tuple(seeded_published(("common", APPLICATION), every_revision=True))
    guide = compose_guide(
        workspace=_workspace(lanes, models, catalog=True, rows=rows),
        lanes=lanes,
        models=models,
        sandbox_profiles=SANDBOXES,
        sandbox_details=SANDBOX_DETAILS,
    )
    return (await guide.topic("capabilities", "mcp")).markdown


def _row(page: str, capability_id: str) -> list[str]:
    (line,) = [line for line in page.splitlines() if line.startswith(f"| `{capability_id}` (")]
    return [cell.strip() for cell in line.strip("|").split("|")]


async def test_the_page_lists_each_server_at_its_newest_revision_with_what_it_needs() -> None:
    page = await _capabilities_page()
    assert "### What a node can mount" in page

    capture = _row(page, "mcp.knowledge-capture")
    assert capture[0] == "`mcp.knowledge-capture` (revision 2)"
    assert capture[1] == "`deep_agents`"
    assert capture[2] == "19 of 40 (allowlist)"
    assert capture[3] == "`VERIFY_EXECUTOR_TOKEN`"
    assert "`MCP_SERVER_ENDPOINTS` under `mcp.knowledge-capture`" in capture[4]
    assert "remote server" in capture[4]

    github = _row(page, "mcp.github")
    assert github[0] == "`mcp.github` (revision 1)" and "`deep_agents`" in github[1]
    assert github[2] == "22" and github[3] == "`GITHUB_PERSONAL_ACCESS_TOKEN`"
    assert "ghcr.io/github/github-mcp-server@sha256:" in github[4]

    context7 = _row(page, "mcp.context7")
    assert context7[2] == "2" and context7[3] == "`CONTEXT7_API_KEY`"
    assert "`npm:@upstash/context7-mcp@4.7.0`" in context7[4]
    # No secret value, only names; no endpoint URL either.
    assert "127.0.0.1" not in page


async def test_the_page_names_each_plugins_members_and_the_member_rule() -> None:
    page = await _capabilities_page()

    knowledge = _row(page, "plugin.cognition-knowledge")
    assert knowledge[0] == "`plugin.cognition-knowledge` (revision 3)"
    assert knowledge[1] == "`deep_agents`"
    for member in (
        "`skill.knowledge-research` (skill)",
        "`skill.knowledge-verify` (skill)",
        "`mcp.knowledge-capture` (mcp_server)",
        "`subagent.mc-cognition-source-verifier` (subagent)",
    ):
        assert member in knowledge[2]
    code = _row(page, "plugin.code-research")
    assert code[2] == "`mcp.context7` (mcp_server), `mcp.github` (mcp_server)"
    assert "On `deep_agents` a plugin is run as its members" in page
    assert "A `hook`, `prompt`, `resource` member blocks the compile" in page
    assert "`plugin_member_unsupported_on_lane`" in page


async def test_a_catalog_without_servers_or_plugins_adds_no_section() -> None:
    page = (await full_guide().topic("capabilities", "mcp")).markdown
    assert "What a node can mount" not in page

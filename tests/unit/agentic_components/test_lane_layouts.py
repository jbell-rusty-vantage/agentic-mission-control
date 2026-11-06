"""MO-30: the per-lane layout table drives the Host Projection (SPEC-02 §3).

The table has one row per lane profile, recorded from the provider fact sheets; the renderer
places every kind where its row says, carries the subagent fields its row maps and reports
every other one, holds the provider limits, and names the API field a hosted agent API row will
travel through. A provider change is a data change: patching a row moves the rendered files.
"""

from __future__ import annotations

import re

import pytest

from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.projection import (
    ProjectionError,
    ResolvedCapability,
)
from mission_control.domain.capabilities.host_support import (
    HOSTED_PROFILES,
    AgentCapabilityKind,
    LaneProfile,
)
from mission_control.domain.capabilities.layouts import (
    CODEX_INSTRUCTIONS_LIMIT,
    LANE_LAYOUTS,
    LAYERING_LAYOUTS,
    REPOSITORY_DELIVERY,
    DeliveryMode,
    LaneLayout,
)
from tests.fixtures.projections import regen
from tests.fixtures.projections.rows import (
    INSTRUCTION,
    firecrawl_row,
    fixture_rows,
    summarizer_row,
    verifier_row,
)

FILE_LANES = tuple(
    profile for profile, layout in LANE_LAYOUTS.items() if layout.layering is not None
)
HOSTED_APIS = (LaneProfile.CLAUDE_MANAGED, LaneProfile.CODEX_AGENTS)


def _subagent(name: str, **fields: object) -> ResolvedCapability:
    """A subagent profile row named ``name`` with ``fields`` set on its profile."""

    row = summarizer_row()
    definition = row.definition
    profile = definition.profile.model_copy(  # type: ignore[union-attr]
        update={"name": name, "background": False, "max_turns": None, **fields}
    )
    pin = row.pin.model_copy(update={"capability_id": f"subagent.{name}"})
    return row.model_copy(
        update={
            "pin": pin,
            "definition": definition.model_copy(
                update={"logical_id": f"subagent.{name}", "profile": profile}
            ),
        }
    )


# --- the table ------------------------------------------------------------------------------------


def test_the_table_has_one_row_per_lane_profile_and_layering_is_its_repository_view() -> None:
    assert set(LANE_LAYOUTS) == set(LaneProfile)
    assert set(LAYERING_LAYOUTS) == {
        profile
        for profile, layout in LANE_LAYOUTS.items()
        if layout.delivery in REPOSITORY_DELIVERY
    }
    for profile, layering in LAYERING_LAYOUTS.items():
        assert LANE_LAYOUTS[profile].layering is layering
    assert set(LAYERING_LAYOUTS) == {
        LaneProfile.CURSOR_LOCAL,
        LaneProfile.CURSOR_CLOUD,
        LaneProfile.CLAUDE_AGENT_SDK,
        LaneProfile.CODEX,
        LaneProfile.CLAUDE_CLOUD,
        LaneProfile.CODEX_CLOUD,
    }


def test_local_lanes_write_the_worktree_and_cloud_lanes_commit_the_branch() -> None:
    delivery = {profile: layout.delivery for profile, layout in LANE_LAYOUTS.items()}
    for profile in (LaneProfile.CURSOR_LOCAL, LaneProfile.CLAUDE_AGENT_SDK, LaneProfile.CODEX):
        assert delivery[profile] is DeliveryMode.WORKTREE_WRITE
    for profile in (LaneProfile.CURSOR_CLOUD, LaneProfile.CLAUDE_CLOUD, LaneProfile.CODEX_CLOUD):
        assert delivery[profile] is DeliveryMode.BRANCH_COMMIT
    for profile in HOSTED_APIS:
        assert delivery[profile] is DeliveryMode.PROVIDER_REGISTRY
    assert delivery[LaneProfile.DEEP_AGENTS] is DeliveryMode.INLINE_LAUNCH
    assert set(HOSTED_APIS) <= HOSTED_PROFILES


def test_rows_record_the_fact_sheet_paths_and_limits() -> None:
    cursor_local = LANE_LAYOUTS[LaneProfile.CURSOR_LOCAL]
    cursor_cloud = LANE_LAYOUTS[LaneProfile.CURSOR_CLOUD]
    # Cursor cloud ignores the project MCP file: servers travel inline, at most 50.
    assert cursor_local.mcp_file == ".cursor/mcp.json" and cursor_local.mcp_inline is None
    assert cursor_cloud.mcp_file is None and cursor_cloud.mcp_inline == "mcp_servers"
    assert cursor_cloud.mcp_inline_limit == 50
    assert cursor_cloud.layering is not None
    assert ".cursor/mcp.json" not in cursor_cloud.layering.config_files
    # Inline customSubagents: at most 20, carrying name, description, prompt and model.
    assert cursor_cloud.subagents is not None
    assert cursor_cloud.subagents.inline_limit == 20
    assert cursor_cloud.subagents.inline_fields == ("model",)
    assert set(cursor_cloud.subagents.fields.values()) == {"model", "readonly", "is_background"}
    # Claude frontmatter keys; Codex custom agents carry model and sandbox_mode only.
    claude = LANE_LAYOUTS[LaneProfile.CLAUDE_AGENT_SDK].subagents
    assert claude is not None and claude.fields["max_turns"] == "maxTurns"
    assert claude.fields["mcp_servers"] == "mcpServers"
    codex = LANE_LAYOUTS[LaneProfile.CODEX].subagents
    assert codex is not None and set(codex.fields) == {"model", "readonly"}
    # Codex cloud: no per-task MCP, hooks or custom agents; instructions capped at 32 KiB.
    codex_cloud = LANE_LAYOUTS[LaneProfile.CODEX_CLOUD]
    assert codex_cloud.instructions_limit == CODEX_INSTRUCTIONS_LIMIT == 32 * 1024
    assert (codex_cloud.mcp_file, codex_cloud.hooks_file, codex_cloud.subagents) == (None,) * 3
    for profile in FILE_LANES:
        assert LANE_LAYOUTS[profile].skill_name_limit == 64


def test_hosted_agent_api_rows_name_their_api_targets_and_nothing_else() -> None:
    kinds = {
        AgentCapabilityKind.SKILL_BUNDLE,
        AgentCapabilityKind.MCP_SERVER,
        AgentCapabilityKind.HOOK_SCRIPT,
        AgentCapabilityKind.SUBAGENT_PROFILE,
    }
    managed = LANE_LAYOUTS[LaneProfile.CLAUDE_MANAGED]
    agents = LANE_LAYOUTS[LaneProfile.CODEX_AGENTS]
    for layout in (managed, agents):
        assert set(layout.api_targets) == kinds
        assert layout.layering is None and layout.subagents is None
        assert (layout.hooks_file, layout.mcp_file, layout.mcp_inline) == (None, None, None)
    assert managed.api_targets[AgentCapabilityKind.SKILL_BUNDLE].startswith("agent.skills")
    assert managed.api_targets[AgentCapabilityKind.MCP_SERVER].startswith("agent.mcp_servers")
    assert agents.api_targets[AgentCapabilityKind.MCP_SERVER].startswith("agent.tools")
    assert "Skills API" in agents.api_targets[AgentCapabilityKind.SKILL_BUNDLE]


def test_a_row_must_be_consistent_with_its_delivery_mode() -> None:
    with pytest.raises(ValueError, match="layering layout"):
        LaneLayout(delivery=DeliveryMode.WORKTREE_WRITE)
    with pytest.raises(ValueError, match="layering layout"):
        LaneLayout(
            delivery=DeliveryMode.PROVIDER_REGISTRY,
            layering=LAYERING_LAYOUTS[LaneProfile.CODEX],
            api_targets={AgentCapabilityKind.SKILL_BUNDLE: "x"},
        )
    with pytest.raises(ValueError, match="API targets"):
        LaneLayout(delivery=DeliveryMode.PROVIDER_REGISTRY)
    with pytest.raises(ValueError, match="API targets"):
        LaneLayout(
            delivery=DeliveryMode.INLINE_LAUNCH,
            api_targets={AgentCapabilityKind.SKILL_BUNDLE: "x"},
        )


# --- the renderer follows the table --------------------------------------------------------------


@pytest.mark.parametrize("profile", FILE_LANES)
def test_every_projected_cognition_file_lands_where_the_row_says(profile: LaneProfile) -> None:
    layout = LANE_LAYOUTS[profile]
    layering = layout.layering
    assert layering is not None
    paths = set(regen.project(profile).paths())
    assert f"{layering.skills}/agent-browser/SKILL.md" in paths
    if layering.agents is not None:
        assert {
            f"{layering.agents}/verifier{layering.agent_suffix}",
            f"{layering.agents}/summarizer{layering.agent_suffix}",
        } <= paths
    if layout.hooks_file is not None:
        assert layout.hooks_file in paths
    if layout.mcp_file is not None:
        assert layout.mcp_file in paths
    if not layering.overlay_inline:
        assert layering.overlay in paths
    # Nothing outside the row's roots, the Mission Control-owned `.mission/` tree and the
    # declared files.
    declared = {layout.hooks_file, layout.mcp_file, layering.overlay}
    roots = tuple(root for root in (layering.skills, layering.agents, ".mission") if root)
    assert all(path in declared or path.startswith(roots) for path in paths), sorted(paths)


def test_a_provider_change_is_a_data_change(monkeypatch: pytest.MonkeyPatch) -> None:
    codex = LANE_LAYOUTS[LaneProfile.CODEX]
    assert codex.layering is not None
    moved = codex.model_copy(
        update={
            "layering": codex.layering.model_copy(update={"skills": ".codex/skills"}),
            "hooks_file": ".codex/hooks-v2.json",
        }
    )
    monkeypatch.setitem(LANE_LAYOUTS, LaneProfile.CODEX, moved)  # type: ignore[arg-type]
    paths = set(HOST_PROJECTORS.render(fixture_rows(), LaneProfile.CODEX, INSTRUCTION).paths())
    assert ".codex/skills/agent-browser/SKILL.md" in paths
    assert ".codex/hooks-v2.json" in paths
    assert not any(path.startswith(".agents/skills/") for path in paths)


# --- subagent field mapping -----------------------------------------------------------------------

_EVERY_FIELD = {
    "model": "fast-model",
    "tools": ("Read", "Grep"),
    "skills": ("agent-browser",),
    "mcp_servers": ("mcp.firecrawl",),
    "readonly": True,
    "background": True,
    "max_turns": 7,
    "interrupt_on": ("Bash",),
    "context_mode": "fork",
}


@pytest.mark.parametrize(
    "profile",
    [profile for profile, layout in LANE_LAYOUTS.items() if layout.subagents is not None],
)
def test_every_set_field_is_carried_or_reported_degraded(profile: LaneProfile) -> None:
    subagents = LANE_LAYOUTS[profile].subagents
    assert subagents is not None
    projection = HOST_PROJECTORS.render(
        (firecrawl_row(), _subagent("auditor", **_EVERY_FIELD)),
        profile,
        INSTRUCTION,
        agent_server_bound=True,
    )
    lost = {
        field
        for field in _EVERY_FIELD
        for item in projection.report.degraded
        if item.startswith(f"subagent auditor: {profile.value} subagents have no per-agent ")
        and _LOSS_WORDS[field] in item
    }
    assert lost == set(_EVERY_FIELD) - set(subagents.fields), lost


_LOSS_WORDS = {
    "model": "model choice",
    "tools": "tool allowlist",
    "skills": "skill restriction",
    "mcp_servers": "MCP server restriction",
    "readonly": "read-only setting",
    "background": "background setting",
    "max_turns": "max_turns limit",
    "interrupt_on": "interrupt_on approvals",
    "context_mode": "forked context",
}


@pytest.mark.parametrize("profile", [LaneProfile.CLAUDE_AGENT_SDK, LaneProfile.CLAUDE_CLOUD])
def test_claude_frontmatter_carries_every_mapped_field(profile: LaneProfile) -> None:
    subagents = LANE_LAYOUTS[profile].subagents
    assert subagents is not None
    projection = HOST_PROJECTORS.render(
        (firecrawl_row(), _subagent("auditor", **_EVERY_FIELD)), profile, INSTRUCTION
    )
    text = projection.file(".claude/agents/auditor.md").content.decode()
    keys = set(re.findall(r"^(\w+):", text.split("\n---\n", 1)[0], re.MULTILINE))
    assert set(subagents.fields.values()) <= keys
    assert "maxTurns: 7" in text and 'tools: "Read, Grep"' in text
    assert 'mcpServers: ["mc-firecrawl"]' in text


@pytest.mark.parametrize("profile", [LaneProfile.CURSOR_LOCAL, LaneProfile.CURSOR_CLOUD])
def test_cursor_frontmatter_carries_every_mapped_field(profile: LaneProfile) -> None:
    subagents = LANE_LAYOUTS[profile].subagents
    assert subagents is not None
    projection = HOST_PROJECTORS.render(
        (_subagent("auditor", **_EVERY_FIELD),), profile, INSTRUCTION
    )
    text = projection.file(".cursor/agents/auditor.md").content.decode()
    keys = set(re.findall(r"^(\w+):", text.split("\n---\n", 1)[0], re.MULTILINE))
    assert set(subagents.fields.values()) <= keys


def test_codex_custom_agents_carry_model_and_sandbox_mode() -> None:
    projection = HOST_PROJECTORS.render(
        (_subagent("auditor", **_EVERY_FIELD),), LaneProfile.CODEX, INSTRUCTION
    )
    text = projection.file(".codex/agents/auditor.toml").content.decode()
    assert 'model = "fast-model"' in text and 'sandbox_mode = "read-only"' in text


def test_the_fixture_goldens_report_what_each_lane_loses() -> None:
    """The golden degradation reports, re-recorded from the fact sheets."""

    degraded = {profile: regen.project(profile).report.degraded for profile in LaneProfile}
    verifier_lost = "subagent verifier: {} subagents have no per-agent MCP server restriction"
    for profile in (LaneProfile.CURSOR_LOCAL, LaneProfile.CURSOR_CLOUD, LaneProfile.CODEX):
        assert any(
            item.startswith(verifier_lost.format(profile.value)) for item in degraded[profile]
        )
    # Claude carries the verifier's skills, servers and read-only mode and the summarizer's
    # max_turns; Cursor and Codex lose max_turns.
    for profile in (LaneProfile.CLAUDE_AGENT_SDK, LaneProfile.CLAUDE_CLOUD):
        assert not any(item.startswith("subagent ") for item in degraded[profile])
    for profile in (LaneProfile.CURSOR_LOCAL, LaneProfile.CODEX):
        assert any("summarizer" in item and "max_turns" in item for item in degraded[profile])


# --- limits ---------------------------------------------------------------------------------------


def test_cursor_cloud_inline_subagents_over_the_limit_fall_back_to_their_files() -> None:
    rows = tuple(_subagent(f"helper-{index:02d}") for index in range(21))
    projection = HOST_PROJECTORS.render(rows, LaneProfile.CURSOR_CLOUD, INSTRUCTION)
    inline = projection.send_options["agents"]
    assert isinstance(inline, list) and len(inline) == 20
    assert projection.report.overflow == (
        "cursor_cloud inline subagent limit 20 exceeded (21 inline subagents); the rest load "
        "from .cursor/agents only",
    )
    assert ".cursor/agents/helper-20.md" in projection.paths()
    local = HOST_PROJECTORS.render(rows, LaneProfile.CURSOR_LOCAL, INSTRUCTION)
    assert len(local.send_options["agents"]) == 21  # type: ignore[arg-type]
    assert not local.report.overflow


def test_cursor_cloud_refuses_more_inline_mcp_servers_than_it_accepts() -> None:
    base = firecrawl_row()
    rows = tuple(
        base.model_copy(
            update={
                "pin": base.pin.model_copy(update={"capability_id": f"mcp.server-{index:02d}"}),
                "definition": base.definition.model_copy(
                    update={"logical_id": f"mcp.server-{index:02d}"}
                ),
            }
        )
        for index in range(51)
    )
    with pytest.raises(ProjectionError, match="at most 50 inline MCP servers, not 51"):
        HOST_PROJECTORS.render(rows, LaneProfile.CURSOR_CLOUD, INSTRUCTION)
    local = HOST_PROJECTORS.render(rows, LaneProfile.CURSOR_LOCAL, INSTRUCTION)
    assert ".cursor/mcp.json" in local.paths()


# --- hosted agent APIs ----------------------------------------------------------------------------


@pytest.mark.parametrize("profile", HOSTED_APIS)
def test_hosted_agent_apis_report_each_row_with_its_api_target(profile: LaneProfile) -> None:
    projection = regen.project(profile)
    assert projection.files == ()
    assert INSTRUCTION.splitlines()[0] in str(projection.send_options["instructions"])
    assert projection.send_options["hosted_skills"]
    assert projection.send_options["hosted_mcp_servers"] == []
    for row in (verifier_row(), summarizer_row()):
        assert row.pin.render() in projection.report.skipped_members
        assert any(
            "hosted catalog hooks/subagent execution unavailable" in item
            and row.pin.render() in item
            for item in projection.report.degraded
        )
    firecrawl = firecrawl_row()
    assert firecrawl.pin.render() in projection.report.skipped_members
    assert (
        f"{firecrawl.pin.render()}: hosted MCP credential transport is unavailable"
        in projection.report.degraded
    )

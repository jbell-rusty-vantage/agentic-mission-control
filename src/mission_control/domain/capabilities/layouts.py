"""The per-lane layout table: where each lane profile's provider reads cognition (SPEC-02 §3).

One row per :class:`LaneProfile`, recorded from the provider fact sheets
(``docs/specs/archive/materialization-observation-2026-10/research/``), so a provider change is a
data
change plus a re-recorded golden fixture, never a renderer change. A row holds:

- the delivery mode (SPEC-02 §6) and, for lanes whose cognition lands in a repository, the
  :class:`LayeringLayout` (MO-02): the instruction overlay channel, the repository instruction
  files and cognition roots the provider reads, and the config files layering merges;
- the native hook and MCP files, or the launch option that carries MCP servers inline;
- the subagent field mapping: which ``mc.subagent_profile.v1`` fields the provider's subagent
  definition can carry and under which native key. A set field without a mapping is lost on
  that lane and the Host Projection reports it;
- the limits the provider enforces (skill names, inline subagents, inline MCP servers,
  instruction bytes);
- for the hosted agent APIs, the provider API field each capability kind travels through. Their
  projection through those fields is HL-21's; until then the rows only name the targets.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.capabilities.host_support import AgentCapabilityKind, LaneProfile

# Codex reads at most `project_doc_max_bytes` (32 KiB by default) of AGENTS files.
CODEX_INSTRUCTIONS_LIMIT: Final = 32 * 1024
# Claude Code, Codex and Cursor reject (or warn on) skill names longer than 64 characters.
SKILL_NAME_LIMIT: Final = 64


class DeliveryMode(StrEnum):
    """How a lane's cognition reaches the provider, and so what proves it was delivered."""

    WORKTREE_WRITE = "worktree_write"
    BRANCH_COMMIT = "branch_commit"
    INLINE_LAUNCH = "inline_launch"
    PROVIDER_REGISTRY = "provider_registry"


# Delivery modes that place cognition in a repository: the worktree or the mission branch.
REPOSITORY_DELIVERY: Final = frozenset({DeliveryMode.WORKTREE_WRITE, DeliveryMode.BRANCH_COMMIT})


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LayeringLayout(_Row):
    """One lane profile's instruction channel and the native roots discovery reads."""

    # A Mission Control-owned file (written to the worktree or committed on the mission
    # branch), or the launch option that carries the overlay when ``overlay_inline``.
    overlay: str = Field(min_length=1)
    overlay_inline: bool = False
    # Files and rule directories the provider reads natively; Mission Control never writes
    # them (``AGENTS.override.md`` on codex_cloud is a merge of ``AGENTS.md``, not a write).
    repo_instructions: tuple[str, ...]
    skills: str
    agents: str | None
    agent_suffix: str = ".md"
    config_files: tuple[str, ...] = ()


class SubagentLayout(_Row):
    """How a lane carries a subagent profile.

    ``fields`` maps a profile field (``model``, ``tools``, ``skills``, ``mcp_servers``,
    ``readonly``, ``background``, ``max_turns``, ``interrupt_on``, ``context_mode``) to the
    native key of the lane's subagent file or object. ``inline_fields`` are the profile fields
    an inline launch definition (Cursor ``customSubagents`` / SDK ``agents``) carries; a profile
    that sets a field outside them is placed as a file only.
    """

    fields: Mapping[str, str]
    inline_fields: tuple[str, ...] = ()
    inline_limit: int | None = Field(default=None, ge=1)


class LaneLayout(_Row):
    """One row of the per-lane layout table (see the module doc)."""

    delivery: DeliveryMode
    layering: LayeringLayout | None = None
    hooks_file: str | None = None
    mcp_file: str | None = None
    # The launch option that carries MCP servers when the provider ignores the project file;
    # it is sent with every create and every run.
    mcp_inline: str | None = None
    mcp_inline_limit: int | None = Field(default=None, ge=1)
    subagents: SubagentLayout | None = None
    skill_name_limit: int = SKILL_NAME_LIMIT
    instructions_limit: int | None = Field(default=None, ge=1)
    # Hosted agent APIs: the provider API field each capability kind travels through. The
    # overlay travels as the agent's instructions (`agent.system` / `agent.instructions`).
    api_targets: Mapping[AgentCapabilityKind, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def repository_delivery_has_a_layout(self) -> LaneLayout:
        if (self.layering is not None) != (self.delivery in REPOSITORY_DELIVERY):
            raise ValueError("a lane has a layering layout exactly when cognition lands in a repo")
        if (self.delivery is DeliveryMode.PROVIDER_REGISTRY) != bool(self.api_targets):
            raise ValueError("provider registry lanes name their API targets, and only they do")
        return self


_CURSOR_LAYERING: Final = LayeringLayout(
    overlay=".cursor/rules/mc-mission.mdc",
    repo_instructions=("AGENTS.md", ".cursor/rules"),
    skills=".cursor/skills",
    agents=".cursor/agents",
    config_files=(".cursor/hooks.json", ".cursor/mcp.json"),
)
# `.cursor/agents/<name>.md` frontmatter; inline definitions carry `name`, `description`,
# `prompt` and `model` only (cursor.md §5 "Subagents").
_CURSOR_SUBAGENT_FIELDS: Final = {
    "model": "model",
    "readonly": "readonly",
    "background": "is_background",
}
_CLAUDE_INSTRUCTIONS: Final = ("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", ".claude/rules")
_CLAUDE_CONFIG: Final = (".claude/settings.json", ".mcp.json")
# `.claude/agents/<name>.md` frontmatter (claude-code.md Q5 "Subagents"). A read-only profile
# runs in `permissionMode: plan`.
_CLAUDE_SUBAGENTS: Final = SubagentLayout(
    fields={
        "model": "model",
        "tools": "tools",
        "skills": "skills",
        "mcp_servers": "mcpServers",
        "readonly": "permissionMode",
        "background": "background",
        "max_turns": "maxTurns",
    }
)
_CODEX_INSTRUCTIONS: Final = ("AGENTS.override.md", "AGENTS.md")
# `.codex/agents/<name>.toml`: `name`, `description`, `developer_instructions` plus config keys
# (codex.md "Custom agents"). A read-only profile runs in `sandbox_mode = "read-only"`.
_CODEX_SUBAGENTS: Final = SubagentLayout(fields={"model": "model", "readonly": "sandbox_mode"})

LANE_LAYOUTS: Final[Mapping[LaneProfile, LaneLayout]] = {
    # In-process Deep Agents objects (`InProcessProjection`); `SubAgent` dict keys.
    LaneProfile.DEEP_AGENTS: LaneLayout(
        delivery=DeliveryMode.INLINE_LAUNCH,
        subagents=SubagentLayout(
            fields={
                "model": "model",
                "tools": "tools",
                "skills": "skills",
                "readonly": "permissions",
                "background": "background",
                "interrupt_on": "interrupt_on",
            }
        ),
    ),
    LaneProfile.CURSOR_LOCAL: LaneLayout(
        delivery=DeliveryMode.WORKTREE_WRITE,
        layering=_CURSOR_LAYERING,
        hooks_file=".cursor/hooks.json",
        mcp_file=".cursor/mcp.json",
        subagents=SubagentLayout(fields=_CURSOR_SUBAGENT_FIELDS, inline_fields=("model",)),
    ),
    # Cloud ignores the project `.cursor/mcp.json`: MCP servers travel inline as `mcpServers`
    # on every create and every follow-up run (cursor.md §4.1, §5 "MCP").
    LaneProfile.CURSOR_CLOUD: LaneLayout(
        delivery=DeliveryMode.BRANCH_COMMIT,
        layering=_CURSOR_LAYERING.model_copy(update={"config_files": (".cursor/hooks.json",)}),
        hooks_file=".cursor/hooks.json",
        mcp_inline="mcp_servers",
        mcp_inline_limit=50,
        subagents=SubagentLayout(
            fields=_CURSOR_SUBAGENT_FIELDS, inline_fields=("model",), inline_limit=20
        ),
    ),
    # SDK `system_prompt={"type": "preset", "preset": "claude_code", "append": overlay}`.
    LaneProfile.CLAUDE_AGENT_SDK: LaneLayout(
        delivery=DeliveryMode.WORKTREE_WRITE,
        layering=LayeringLayout(
            overlay="system_prompt.append",
            overlay_inline=True,
            repo_instructions=_CLAUDE_INSTRUCTIONS,
            skills=".claude/skills",
            agents=".claude/agents",
            config_files=_CLAUDE_CONFIG,
        ),
        hooks_file=".claude/settings.json",
        mcp_file=".mcp.json",
        subagents=_CLAUDE_SUBAGENTS,
    ),
    # app-server `thread/start.developerInstructions`; no file is written.
    LaneProfile.CODEX: LaneLayout(
        delivery=DeliveryMode.WORKTREE_WRITE,
        layering=LayeringLayout(
            overlay="developer_instructions",
            overlay_inline=True,
            repo_instructions=_CODEX_INSTRUCTIONS,
            skills=".agents/skills",
            agents=".codex/agents",
            agent_suffix=".toml",
            config_files=(".codex/hooks.json", ".codex/config.toml"),
        ),
        hooks_file=".codex/hooks.json",
        mcp_file=".codex/config.toml",
        subagents=_CODEX_SUBAGENTS,
    ),
    LaneProfile.CLAUDE_CLOUD: LaneLayout(
        delivery=DeliveryMode.BRANCH_COMMIT,
        layering=LayeringLayout(
            overlay=".claude/rules/mc-mission.md",
            repo_instructions=_CLAUDE_INSTRUCTIONS,
            skills=".claude/skills",
            agents=".claude/agents",
            config_files=_CLAUDE_CONFIG,
        ),
        hooks_file=".claude/settings.json",
        mcp_file=".mcp.json",
        subagents=_CLAUDE_SUBAGENTS,
    ),
    # No per-task override: `AGENTS.override.md` replaces `AGENTS.md` for its directory, so
    # it carries the repository's `AGENTS.md` verbatim followed by the mission section. A task
    # carries no MCP, hook or custom-agent configuration (cloud custom agents: UNVERIFIED).
    LaneProfile.CODEX_CLOUD: LaneLayout(
        delivery=DeliveryMode.BRANCH_COMMIT,
        layering=LayeringLayout(
            overlay="AGENTS.override.md",
            repo_instructions=_CODEX_INSTRUCTIONS,
            skills=".agents/skills",
            agents=None,
        ),
        instructions_limit=CODEX_INSTRUCTIONS_LIMIT,
    ),
    # Managed Agents: one versioned agent per pack (SPEC-06 §4.1, §9).
    LaneProfile.CLAUDE_MANAGED: LaneLayout(
        delivery=DeliveryMode.PROVIDER_REGISTRY,
        api_targets={
            AgentCapabilityKind.SKILL_BUNDLE: "agent.skills (Skills API custom skill, pinned)",
            AgentCapabilityKind.MCP_SERVER: (
                "agent.mcp_servers with an mcp_toolset and a vault credential"
            ),
            AgentCapabilityKind.HOOK_SCRIPT: "none (Kernel Hooks become custom tools)",
            AgentCapabilityKind.SUBAGENT_PROFILE: "agent.multiagent (off for code attempts)",
        },
    ),
    # Agents API saved agent (SPEC-06 §5.1, §9).
    LaneProfile.CODEX_AGENTS: LaneLayout(
        delivery=DeliveryMode.PROVIDER_REGISTRY,
        api_targets={
            AgentCapabilityKind.SKILL_BUNDLE: "environment skills (Skills API skill_reference)",
            AgentCapabilityKind.MCP_SERVER: "agent.tools mcp tool with a vault credential",
            AgentCapabilityKind.HOOK_SCRIPT: "none (Kernel Hooks become function tools)",
            AgentCapabilityKind.SUBAGENT_PROFILE: (
                "agent.multi_agent (off by default; custom agents UNVERIFIED)"
            ),
        },
    ),
}

# The lanes whose cognition lands in a repository (worktree or mission branch) are layered.
LAYERING_LAYOUTS: Final[Mapping[LaneProfile, LayeringLayout]] = {
    profile: layout.layering
    for profile, layout in LANE_LAYOUTS.items()
    if layout.layering is not None
}


__all__ = [
    "CODEX_INSTRUCTIONS_LIMIT",
    "LANE_LAYOUTS",
    "LAYERING_LAYOUTS",
    "REPOSITORY_DELIVERY",
    "SKILL_NAME_LIMIT",
    "DeliveryMode",
    "LaneLayout",
    "LayeringLayout",
    "SubagentLayout",
]

"""FT-A4: Host Projection golden files, purity, secrets, hooks, subagents, plugins, paths."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from mission_control.application.agentic_components.materialization import MaterializationPlanner
from mission_control.application.agentic_components.projections import (
    HOOK_RUNNER_SCRIPT,
)
from mission_control.application.agentic_components.repository import (
    InMemoryAgenticComponentRepository,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.contracts import (
    HOST_LANE_PROFILE,
    AgentHost,
    AgenticComponentRelease,
    ComponentKind,
    MaterializationRequest,
    OperatingSystem,
    PluginBinding,
)
from mission_control.domain.agentic_components.layering import (
    MISSION_SECTION_BEGIN,
    OPERATING_CONTRACT_PATH,
)
from mission_control.domain.agentic_components.projection import (
    KERNEL_HOOK_SCRIPT,
    BundleFile,
    ProjectionError,
    ResolvedCapability,
)
from mission_control.domain.authoring.contracts import MCPServerDefinition
from mission_control.domain.capabilities.hooks import KERNEL_HOOK_IDS, HookEvent
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.layouts import CODEX_INSTRUCTIONS_LIMIT
from tests.fixtures.projections import regen
from tests.fixtures.projections.rows import (
    FIXTURE_SECRET_VALUES,
    INSTRUCTION,
    PACKET_INDEX,
    firecrawl_row,
    fixture_rows,
    hook_row,
    skill_row,
    tavily_row,
    verifier_row,
)
from tests.unit.agentic_components.test_harness import Architecture, mcp_release

GOLDEN = Path(regen.__file__).resolve().parent


def _lf(data: bytes) -> bytes:
    # Windows checkouts with core.autocrlf may rewrite text goldens; content is LF.
    return data.replace(b"\r\n", b"\n")


@pytest.mark.parametrize("profile", list(LaneProfile))
def test_projection_matches_golden_files(profile: LaneProfile) -> None:
    projection = regen.project(profile)
    root = GOLDEN / profile.value
    on_disk = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != regen.REPORT
    }
    assert on_disk == set(projection.paths()), (
        "regenerate: python -m tests.fixtures.projections.regen"
    )
    for item in projection.files:
        assert _lf((root / item.path).read_bytes()) == item.content, item.path
    assert _lf((root / regen.REPORT).read_bytes()) == regen.summary(projection)


@pytest.mark.parametrize("profile", list(LaneProfile))
def test_projection_is_pure_and_secret_free(
    profile: LaneProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", FIXTURE_SECRET_VALUES[0])
    monkeypatch.setenv("FIRECRAWL_API_KEY", FIXTURE_SECRET_VALUES[1])
    first = HOST_PROJECTORS.render(fixture_rows(), profile, INSTRUCTION, PACKET_INDEX)
    second = HOST_PROJECTORS.render(fixture_rows(), profile, INSTRUCTION, PACKET_INDEX)
    assert first == second
    blobs = [item.content for item in first.files]
    blobs.append(regen.summary(first))
    for blob in blobs:
        for secret in FIXTURE_SECRET_VALUES:
            assert secret.encode() not in blob


def test_cursor_mcp_uses_env_interpolation_and_cloud_prefers_remote() -> None:
    local = json.loads(regen.project(LaneProfile.CURSOR_LOCAL).file(".cursor/mcp.json").content)
    tavily = local["mcpServers"]["mc-tavily"]
    assert tavily == {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "tavily-mcp@0.2.22"],
        "env": {"TAVILY_API_KEY": "${env:TAVILY_API_KEY}"},
    }
    assert local["mcpServers"]["mc-firecrawl"]["headers"] == {
        "Authorization": "Bearer ${env:FIRECRAWL_API_KEY}"
    }
    # Cursor cloud ignores `.cursor/mcp.json`: the servers travel inline as `mcpServers`.
    projection = regen.project(LaneProfile.CURSOR_CLOUD)
    assert ".cursor/mcp.json" not in projection.paths()
    servers = projection.send_options["mcp_servers"]
    assert isinstance(servers, list)
    cloud = {item["name"]: item for item in servers}
    assert cloud["mc-tavily"] == {
        "name": "mc-tavily",
        "type": "http",
        "url": "https://mcp.tavily.com/mcp/",
        "headers": {"Authorization": "Bearer ${env:TAVILY_API_KEY}"},
    }
    # the optional agent-browser MCP member is unqualified on cursor_cloud: skipped, reported
    assert "mc-agent-browser" not in cloud
    report = projection.report
    assert any("mcp.agent-browser" in item for item in report.skipped_members)
    # Whether the cloud agent resolves the references from its secrets is not yet proven.
    assert any(item.startswith("tavily: inline MCP secret") for item in report.unqualified)


def test_claude_and_codex_mcp_syntax() -> None:
    claude = json.loads(regen.project(LaneProfile.CLAUDE_AGENT_SDK).file(".mcp.json").content)
    assert claude["mcpServers"]["mc-tavily"]["env"] == {"TAVILY_API_KEY": "${TAVILY_API_KEY}"}
    assert claude["mcpServers"]["mc-firecrawl"]["type"] == "http"
    config = tomllib.loads(
        regen.project(LaneProfile.CODEX).file(".codex/config.toml").content.decode()
    )
    servers = config["mcp_servers"]
    assert servers["mc-tavily"]["env_vars"] == ["TAVILY_API_KEY"]
    assert servers["mc-firecrawl"]["bearer_token_env_var"] == "FIRECRAWL_API_KEY"
    assert servers["mc-firecrawl"]["enabled_tools"] == ["firecrawl_scrape"]
    assert "${" not in regen.project(LaneProfile.CODEX).file(".codex/config.toml").content.decode()


def test_projections_name_the_variables_their_mcp_configuration_reads() -> None:
    # MO-04: what a local lane adds to its child-environment allowlist (names, never values).
    for profile in (
        LaneProfile.CURSOR_LOCAL,
        LaneProfile.CURSOR_CLOUD,
        LaneProfile.CLAUDE_AGENT_SDK,
        LaneProfile.CLAUDE_CLOUD,
        LaneProfile.CODEX,
    ):
        projection = regen.project(profile)
        assert projection.environment_names == ("FIRECRAWL_API_KEY", "TAVILY_API_KEY")
    # Deep Agents connects in-process; Codex Cloud carries no per-task MCP configuration.
    assert regen.project(LaneProfile.DEEP_AGENTS).environment_names == ()
    assert regen.project(LaneProfile.CODEX_CLOUD).environment_names == ()
    # Cursor's OAuth block reads its client refs from the environment as well.
    firecrawl = firecrawl_row()
    oauth = MCPServerDefinition.model_validate(
        {
            **firecrawl.definition.model_dump(),
            "secret_refs": ["FIRECRAWL_API_KEY", "FIRECRAWL_CLIENT_ID"],
            "oauth": {"client_id_ref": "FIRECRAWL_CLIENT_ID"},
        }
    )
    row = ResolvedCapability(pin=firecrawl.pin, definition=oauth)
    cursor = HOST_PROJECTORS.render([row], LaneProfile.CURSOR_LOCAL, INSTRUCTION)
    assert cursor.environment_names == ("FIRECRAWL_API_KEY", "FIRECRAWL_CLIENT_ID")
    claude = HOST_PROJECTORS.render([row], LaneProfile.CLAUDE_AGENT_SDK, INSTRUCTION)
    assert claude.environment_names == ("FIRECRAWL_API_KEY",)


def test_deep_agents_connections_leave_secret_refs_unresolved() -> None:
    projection = regen.project(LaneProfile.DEEP_AGENTS)
    assert projection.in_process is not None
    tavily = projection.in_process.mcp_connections["tavily"]
    assert tavily["env_refs"] == {"TAVILY_API_KEY": "TAVILY_API_KEY"}
    assert "env" not in tavily
    assert projection.in_process.memory == ("/memory/AGENTS.md",)
    assert projection.in_process.skills == ("/skills/mission/",)
    assert projection.in_process.system_prompt == INSTRUCTION


def test_kernel_hooks_render_first_and_fail_closed_on_cursor() -> None:
    hooks = json.loads(regen.project(LaneProfile.CURSOR_LOCAL).file(".cursor/hooks.json").content)
    assert hooks["version"] == 1
    shell = hooks["hooks"]["beforeShellExecution"]
    kernel = [item for item in shell if KERNEL_HOOK_SCRIPT in item["command"]]
    catalog = [item for item in shell if HOOK_RUNNER_SCRIPT in item["command"]]
    assert shell == kernel + catalog
    assert [item["command"].split()[-1] for item in kernel] == [
        "mc.stop_fence",
        "mc.operation_intent",
        "mc.frame_capture",
    ]
    assert all(item["failClosed"] is True for item in kernel)
    assert catalog[0]["timeout"] == 10
    # sessionStart exists on cursor_local but not on cursor_cloud
    assert "sessionStart" in hooks["hooks"]
    cloud = json.loads(regen.project(LaneProfile.CURSOR_CLOUD).file(".cursor/hooks.json").content)
    assert "sessionStart" not in cloud["hooks"]
    unsupported = {
        (item.hook_id, item.event)
        for item in regen.project(LaneProfile.CURSOR_CLOUD).report.unsupported_on_lane
    }
    assert ("hook.mc-policy-template", HookEvent.SESSION_START) in unsupported
    assert ("hook.mc-policy-template", HookEvent.BEFORE_MODEL) in unsupported


def test_claude_hooks_exec_form_and_codex_requires_trust() -> None:
    # claude_cloud: the repository settings file is the only hook route, Kernel Hooks first.
    cloud = json.loads(
        regen.project(LaneProfile.CLAUDE_CLOUD).file(".claude/settings.json").content
    )
    pre_tool = cloud["hooks"]["PreToolUse"]
    first = pre_tool[0]["hooks"][0]
    assert first["command"] == "python" and first["args"][0] == KERNEL_HOOK_SCRIPT
    bash = [group for group in pre_tool if group.get("matcher") == "Bash"]
    assert bash and bash[-1]["hooks"][0]["args"][0] == HOOK_RUNNER_SCRIPT
    # claude_agent_sdk: Kernel Hooks are in-process callbacks; the settings file carries
    # only catalog hooks, and the projected project layer is the only setting source.
    local = regen.project(LaneProfile.CLAUDE_AGENT_SDK)
    settings = local.file(".claude/settings.json").content.decode()
    assert KERNEL_HOOK_SCRIPT not in settings and HOOK_RUNNER_SCRIPT in settings
    assert local.send_options["setting_sources"] == ["project"]
    callbacks = local.send_options["hook_callbacks"]
    assert isinstance(callbacks, list)
    assert [item["hook_id"] for item in callbacks[:3]] == [
        "mc.stop_fence",
        "mc.stop_fence",
        "mc.stop_fence",
    ]
    assert all(item["fail_closed"] is True for item in callbacks)
    codex = regen.project(LaneProfile.CODEX)
    codex_hooks = json.loads(codex.file(".codex/hooks.json").content)
    assert all(
        handler["type"] == "command"
        for groups in codex_hooks["hooks"].values()
        for group in groups
        for handler in group["hooks"]
    )
    assert "hook.mc-policy-template" in codex.report.requires_trust
    assert set(KERNEL_HOOK_IDS) <= set(codex.report.requires_trust)


def test_kernel_hooks_cannot_be_reordered_by_rows() -> None:
    rows = (hook_row(), hook_row().model_copy(update={}))
    with pytest.raises(ProjectionError, match="selected more than once"):
        HOST_PROJECTORS.render(rows, LaneProfile.CURSOR_LOCAL, INSTRUCTION)
    projection = HOST_PROJECTORS.render((hook_row(),), LaneProfile.DEEP_AGENTS, INSTRUCTION)
    assert projection.in_process is not None
    order = [item["hook_id"] for item in projection.in_process.hook_middleware]
    assert order[:4] == list(KERNEL_HOOK_IDS)
    assert order[4:] == ["hook.mc-policy-template"]


def test_subagent_rendering_per_profile() -> None:
    cursor = regen.project(LaneProfile.CURSOR_LOCAL)
    verifier = cursor.file(".cursor/agents/verifier.md").content.decode()
    assert "readonly: true" in verifier and "is_background: false" in verifier
    assert "agents" not in cursor.send_options  # readonly/background need the file form
    inline = HOST_PROJECTORS.render(
        (
            verifier_row().model_copy(
                update={
                    "definition": verifier_row().definition.model_copy(
                        update={
                            "profile": verifier_row().definition.profile.model_copy(  # type: ignore[union-attr]
                                update={"readonly": False}
                            )
                        }
                    )
                }
            ),
        ),
        LaneProfile.CURSOR_LOCAL,
        INSTRUCTION,
    )
    assert inline.send_options["agents"] == [
        {
            "name": "verifier",
            "description": "Validates completed work. Use proactively after any task is done.",
            "prompt": "You are a skeptical validator. Run the tests before agreeing.",
            "model": "inherit",
        }
    ]
    claude = regen.project(LaneProfile.CLAUDE_AGENT_SDK).file(".claude/agents/verifier.md")
    text = claude.content.decode()
    assert 'mcpServers: ["mc-tavily"]' in text and 'permissionMode: "plan"' in text
    deep = regen.project(LaneProfile.DEEP_AGENTS)
    assert deep.in_process is not None
    by_name = {item["name"]: item for item in deep.in_process.subagents}
    assert by_name["verifier"]["permissions"] == [
        {"operations": ["write", "edit", "execute"], "mode": "deny", "path": "/"}
    ]
    assert "background" not in by_name["summarizer"]
    assert any("summarizer" in item for item in deep.report.degraded)
    hosted = HOST_PROJECTORS.render(
        fixture_rows(), LaneProfile.DEEP_AGENTS, INSTRUCTION, agent_server_bound=True
    )
    assert hosted.in_process is not None
    assert {item["name"]: item for item in hosted.in_process.subagents}["summarizer"][
        "background"
    ] is True


def test_skill_paths_and_deep_agents_source_order() -> None:
    kernel_skill = skill_row().model_copy(update={"scope": "kernel"})
    projection = HOST_PROJECTORS.render(
        (kernel_skill, tavily_row()), LaneProfile.DEEP_AGENTS, INSTRUCTION
    )
    assert projection.in_process is not None
    assert projection.in_process.skills == ("/skills/kernel/",)
    assert "skills/kernel/agent-browser/SKILL.md" in projection.paths()
    for profile, root in (
        (LaneProfile.CURSOR_LOCAL, ".cursor/skills"),
        (LaneProfile.CLAUDE_AGENT_SDK, ".claude/skills"),
        (LaneProfile.CODEX, ".agents/skills"),
    ):
        projection = HOST_PROJECTORS.render((skill_row(),), profile, INSTRUCTION)
        assert f"{root}/agent-browser/SKILL.md" in projection.paths()
        assert projection.file(f"{root}/agent-browser/scripts/open.sh").mode == 0o755


@pytest.mark.parametrize("profile", [p for p in LaneProfile if p is not LaneProfile.DEEP_AGENTS])
def test_no_lane_writes_the_repository_instruction_files(profile: LaneProfile) -> None:
    """SPEC-02 §4: the mission overlay is additive; AGENTS.md and CLAUDE.md stay the repo's."""

    assert not {"AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md"} & set(regen.project(profile).paths())


def test_each_lane_carries_the_overlay_through_its_additive_channel() -> None:
    first_line = PACKET_INDEX.splitlines()[0]
    for profile in (LaneProfile.CURSOR_LOCAL, LaneProfile.CURSOR_CLOUD):
        rule = regen.project(profile).file(".cursor/rules/mc-mission.mdc").content.decode()
        assert rule.startswith("---\n") and "alwaysApply: true" in rule and first_line in rule
    claude = regen.project(LaneProfile.CLAUDE_AGENT_SDK).send_options["system_prompt"]
    assert isinstance(claude, dict)
    assert (claude["type"], claude["preset"]) == ("preset", "claude_code")
    assert claude["append"].startswith(INSTRUCTION.strip()) and first_line in claude["append"]
    cloud_rule = regen.project(LaneProfile.CLAUDE_CLOUD).file(".claude/rules/mc-mission.md")
    assert first_line in cloud_rule.content.decode()
    codex = regen.project(LaneProfile.CODEX).send_options["developer_instructions"]
    assert isinstance(codex, str) and first_line in codex
    override = regen.project(LaneProfile.CODEX_CLOUD)
    assert override.file("AGENTS.override.md").content.decode().startswith(MISSION_SECTION_BEGIN)
    assert first_line in override.file(OPERATING_CONTRACT_PATH).content.decode()


def test_codex_overflow_is_reported_on_cloud_only() -> None:
    huge = "x" * (CODEX_INSTRUCTIONS_LIMIT + 10)
    local = HOST_PROJECTORS.render((), LaneProfile.CODEX, huge)
    assert local.send_options["developer_instructions"] == huge + "\n"
    assert not local.report.overflow
    cloud = HOST_PROJECTORS.render((), LaneProfile.CODEX_CLOUD, huge, telemetry=False)
    assert cloud.report.overflow
    assert cloud.file(OPERATING_CONTRACT_PATH).content == (huge + "\n").encode()


def test_path_hygiene() -> None:
    bad_skill = skill_row().model_copy(
        update={"files": (*skill_row().files, BundleFile(path="extra.md", content=b"x"))}
    )
    with pytest.raises(ProjectionError, match="differ from its manifest"):
        HOST_PROJECTORS.render((bad_skill,), LaneProfile.CURSOR_LOCAL, INSTRUCTION)
    with pytest.raises(ValueError):
        BundleFile(path="../escape.sh", content=b"x")
    with pytest.raises(ProjectionError, match="selected more than once"):
        HOST_PROJECTORS.render((skill_row(), skill_row()), LaneProfile.CODEX, INSTRUCTION)
    fork = skill_row().model_copy(
        update={"pin": skill_row().pin.model_copy(update={"capability_id": "skill.fork"})}
    )
    with pytest.raises(ProjectionError, match="duplicate skill"):
        HOST_PROJECTORS.render((skill_row(), fork), LaneProfile.CODEX, INSTRUCTION)


def test_resolved_plugin_members_must_match_the_manifest() -> None:
    plugin = fixture_rows()[0]
    with pytest.raises(ValueError, match="manifest pins"):
        ResolvedCapability(pin=plugin.pin, definition=plugin.definition, members=plugin.members[1:])
    with pytest.raises(ValueError, match="position order"):
        ResolvedCapability(
            pin=plugin.pin,
            definition=plugin.definition,
            members=(plugin.members[1], plugin.members[0], plugin.members[2]),
        )


def test_agent_host_lane_profile_mapping_is_total() -> None:
    assert set(HOST_LANE_PROFILE) == set(AgentHost)
    assert AgentHost.CURSOR.lane_profile is LaneProfile.CURSOR_LOCAL


@pytest.mark.asyncio
async def test_planner_records_plugin_expansion_in_steps() -> None:
    member = mcp_release()
    values = member.model_dump(mode="python")
    values.update(
        kind=ComponentKind.PLUGIN,
        mcp=None,
        definition_ref=None,
        coordinate={
            **values["coordinate"],
            "component_id": "plugin.web",
            "digest": "sha256:" + "f" * 64,
        },
        plugin=PluginBinding(members=(member.coordinate,)),
    )
    plugin = AgenticComponentRelease.model_validate(values)
    planner = MaterializationPlanner(InMemoryAgenticComponentRepository((member, plugin)))
    plan = await planner.plan(
        MaterializationRequest(
            request_id="materialize:plugin",
            component_digests=(plugin.coordinate.digest,),
            host=AgentHost.CURSOR,
            operating_system=OperatingSystem.LINUX,
            architecture=Architecture.AMD64,
            workspace_root="/work",
        )
    )
    assert [coordinate.digest for coordinate in plan.releases] == [
        plugin.coordinate.digest,
        member.coordinate.digest,
    ]
    assert plan.steps[0].description.startswith("Expand plugin plugin.web into members")
    assert any(item.path == ".cursor/mcp.json" for item in plan.generated_files)

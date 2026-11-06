"""MP-03: the recorded Claude Code discovery FIXTURE proves the projected skill, MCP server,
subagent and SessionStart hook load in one exact local CLI build. MO-02: it was recorded over a
repository that owns its own AGENTS.md, skill and hooks, so it also proves the layering is
additive in that build: the repository's skill and the mission's are both discovered, both
SessionStart hooks of the merged settings fire, and the repository files are byte-identical
after the restore.

Re-record with ``uv run --frozen python -m tests.fixtures.projections.discovery.claude_cli``
(no provider call; see that module). The recording is bound to the projection digest, so any
renderer change that alters the claude_agent_sdk bytes makes this test demand a re-record
instead of silently trusting stale evidence. It proves local discovery only; it qualifies
nothing and says nothing about hosted Claude (Outcome 3).
"""

from __future__ import annotations

import json

from mission_control.adapters.claude.discovery import init_report
from mission_control.application.agentic_components.layering import LayeringReceipt
from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.environments import BootstrapRoute, route_evidence
from mission_control.application.environments.discovery import discovery_expectation
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.discovery import DiscoveryItem, discovery_gaps
from tests.fixtures.projections.discovery import claude_cli

RECORDING = json.loads(claude_cli.RECORDING.read_text(encoding="utf-8"))


def test_recording_is_labelled_and_made_without_a_provider_call() -> None:
    assert RECORDING["schema_version"] == "mc.discovery_recording.v1"
    assert RECORDING["fixture"] is True
    assert RECORDING["evidence"] == "local_cli_discovery"
    assert RECORDING["lane_profile"] == "claude_agent_sdk"
    assert "127.0.0.1:9" in RECORDING["provider_call"]
    assert RECORDING["cli"]["version"].startswith("2.1.")
    assert "--setting-sources" in RECORDING["invocation"]
    assert RECORDING["invocation"][RECORDING["invocation"].index("--setting-sources") + 1] == (
        "project"
    )
    # The SDK's `claude_code` preset `append` is this flag (`SubprocessCLITransport`).
    assert "--append-system-prompt" in RECORDING["invocation"]


def test_recording_matches_the_current_projection() -> None:
    projection = claude_cli.project()
    assert RECORDING["projection_digest"] == projection_digest(projection), (
        "claude_agent_sdk projection changed: re-record "
        "`uv run --frozen python -m tests.fixtures.projections.discovery.claude_cli`"
    )
    assert RECORDING["projected_paths"] == list(projection.paths())


def test_projected_skill_mcp_subagent_and_hook_were_discovered() -> None:
    discovered = RECORDING["discovered"]
    assert "agent-browser" in discovered["skills"]
    assert "discovery-reviewer" in discovered["agents"]
    assert {"name": "mc-discovery-stub", "status": "connected"} in discovered["mcp_servers"]
    assert "mcp__mc-discovery-stub__discovery_echo" in discovered["mcp_tools"]
    assert "fired-session_start.json" in RECORDING["hooks_fired"]


def test_the_repository_cognition_loads_beside_the_mission_and_stays_byte_identical() -> None:
    assert "repo-notes" in RECORDING["discovered"]["skills"]
    assert "fired-repo-session_start.json" in RECORDING["hooks_fired"]
    assert RECORDING["repository"]["byte_identical_after_restore"] is True
    assert {"AGENTS.md", ".claude/skills/repo-notes/SKILL.md", ".cursor/hooks.json"} <= set(
        RECORDING["repository"]["paths"]
    )
    layering = RECORDING["layering"]
    assert "AGENTS.md" not in RECORDING["projected_paths"]
    (settings,) = (item for item in layering["merged"] if item["path"] == ".claude/settings.json")
    assert settings["mission_keys"] == ["hooks.SessionStart"]
    assert set(settings["repo_keys"]) == {"hooks.SessionStart", "hooks.InstructionsLoaded"}
    origins = {(item["kind"], item["name"]): item["origin"] for item in layering["discovery"]}
    assert origins[("skill", "repo-notes")] == "repo"
    assert origins[("skill", "agent-browser")] == "mission"
    assert origins[("instructions", "AGENTS.md")] == "repo"


def _recorded_init() -> dict[str, object]:
    """The `system/init` fields the recording kept (skills, agents, MCP servers)."""

    discovered = RECORDING["discovered"]
    return {key: discovered[key] for key in ("skills", "agents", "mcp_servers")}


def test_the_recorded_init_proves_discovery_of_what_the_mission_placed() -> None:
    """MO-34: the lane's Discovery Proof over the recorded init proves every mission skill,
    subagent and MCP server the layering placed, and names the repository's skill too."""

    expectation = discovery_expectation(
        LaneProfile.CLAUDE_AGENT_SDK, LayeringReceipt.model_validate(RECORDING["layering"]), {}
    )
    assert expectation is not None and expectation.mechanism == "session_init"
    assert set(expectation.items) == {
        DiscoveryItem(kind="skill", name="agent-browser"),
        DiscoveryItem(kind="subagent", name="discovery-reviewer"),
        DiscoveryItem(kind="mcp_server", name="mc-discovery-stub"),
    }
    report = init_report(_recorded_init(), source="system/init:recording")
    assert discovery_gaps(expectation, report) == ()
    assert DiscoveryItem(kind="skill", name="repo-notes") in report.items


def test_an_mcp_server_that_did_not_connect_is_not_discovered() -> None:
    init = _recorded_init()
    init["mcp_servers"] = [{"name": "mc-discovery-stub", "status": "failed"}]
    expectation = discovery_expectation(
        LaneProfile.CLAUDE_AGENT_SDK, LayeringReceipt.model_validate(RECORDING["layering"]), {}
    )
    assert expectation is not None
    assert discovery_gaps(expectation, init_report(init, source="init")) == (
        "mcp_server mc-discovery-stub was not reported loaded",
    )


def test_recording_is_secret_and_path_free() -> None:
    text = claude_cli.RECORDING.read_text(encoding="utf-8")
    assert "\r\n" not in text
    for needle in ("Users\\", "/Users/", "/home/", "sk-ant", "placeholder-not-a-credential"):
        assert needle not in text


def test_route_evidence_cites_the_recording_but_stays_unqualified() -> None:
    evidence = route_evidence(LaneProfile.CLAUDE_AGENT_SDK, BootstrapRoute.PRE_SESSION_FILES)
    assert evidence is not None and evidence.status == "unqualified"
    assert any(ref.endswith("claude_agent_sdk.recorded.json") for ref in evidence.evidence_refs)

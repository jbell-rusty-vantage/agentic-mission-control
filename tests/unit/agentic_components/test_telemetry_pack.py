"""MO-41: the Telemetry Hook Pack's native projection per lane (SPEC-04 sections 4.1 and 4.2).

The goldens under tests/fixtures/projections hold the exact bytes; these cases state the
rules: which lanes carry the pack, where each hook lands, that pack hooks are fail-open and
come after the Kernel and catalog hooks, and that turning the pack off removes all of it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mission_control.application.agentic_components.telemetry import (
    ADVISORY_INSTRUCTION,
    SIGNAL_CLI,
    SIGNAL_POLICY,
    SIGNAL_SCRIPT,
    SIGNAL_SKILL_SOURCE,
    TELEMETRY_EVENTS,
    TELEMETRY_HOOK_ID,
    signal_policy,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.projection import (
    DEFAULT_KERNEL_HOOKS,
    BundleFile,
    HostProjection,
    ResolvedCapability,
)
from mission_control.domain.authoring.contracts import SkillDefinition
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.pins import CapabilityPin
from tests.fixtures.projections.rows import INSTRUCTION, fixture_rows, skill_row

SKILL_BUNDLE = Path(__file__).resolve().parents[3] / "skills" / "mc-signals" / "SKILL.md"
PACK = (SIGNAL_SCRIPT, SIGNAL_CLI, SIGNAL_POLICY)


def project(lane: LaneProfile, *, kernel: bool = True, telemetry: bool = True) -> HostProjection:
    hooks = DEFAULT_KERNEL_HOOKS if kernel else ()
    return HOST_PROJECTORS.render(
        fixture_rows(), lane, INSTRUCTION, None, hooks, telemetry=telemetry
    )


def pack_paths(projection: HostProjection) -> set[str]:
    return {
        item.path for item in projection.files if item.path in PACK or "/mc-signals/" in item.path
    }


@pytest.mark.parametrize("lane", list(LaneProfile))
def test_every_repository_lane_but_the_local_sdk_carries_the_pack(lane: LaneProfile) -> None:
    projection = project(lane)
    paths = pack_paths(projection)
    if lane in TELEMETRY_EVENTS:
        layering = {
            LaneProfile.CURSOR_LOCAL: ".cursor/skills",
            LaneProfile.CURSOR_CLOUD: ".cursor/skills",
            LaneProfile.CODEX: ".agents/skills",
            LaneProfile.CODEX_CLOUD: ".agents/skills",
            LaneProfile.CLAUDE_CLOUD: ".claude/skills",
        }[lane]
        assert paths == {*PACK, f"{layering}/mc-signals/SKILL.md"}
        assert projection.file(SIGNAL_SCRIPT).mode == projection.file(SIGNAL_CLI).mode == 0o755
        policy = json.loads(projection.file(SIGNAL_POLICY).content)
        assert policy == signal_policy(lane)
        assert all(path in projection.paths() for path in policy["materialization"]["files"])
    else:
        # Deep Agents and the local SDK feed frames in process; hosted APIs have `mc_signal`.
        assert paths == set()


def _cursor_hooks(projection: HostProjection) -> dict[str, list[dict[str, object]]]:
    hooks: dict[str, list[dict[str, object]]] = json.loads(
        projection.file(".cursor/hooks.json").content
    )["hooks"]
    return hooks


def _is_pack(command: object) -> bool:
    return isinstance(command, str) and command.startswith(f"python {SIGNAL_SCRIPT} hook ")


def test_cursor_cloud_forwards_the_spec_events_fail_open_after_its_catalog_hooks() -> None:
    hooks = _cursor_hooks(project(LaneProfile.CURSOR_CLOUD, kernel=False))
    pack = {
        native: [item for item in items if _is_pack(item["command"])]
        for native, items in hooks.items()
    }
    assert {native for native, items in pack.items() if items} == {
        "preToolUse",
        "postToolUse",
        "subagentStart",
        "subagentStop",
        "afterAgentResponse",
        "preCompact",
        "stop",
    }
    for native, items in hooks.items():
        commands = [item["command"] for item in items]
        first_pack = next((i for i, c in enumerate(commands) if _is_pack(c)), len(commands))
        assert not any(_is_pack(c) for c in commands[:first_pack])
        assert all(_is_pack(c) for c in commands[first_pack:]), f"pack entries last: {native}"
    for items in pack.values():
        for item in items:
            assert item["failClosed"] is False and item["timeout"] == 15
    policy = signal_policy(LaneProfile.CURSOR_CLOUD)
    assert policy["flush"] == ["stop"]
    assert policy["stdout"]["before_tool"] == {"permission": "allow"}  # type: ignore[index]
    assert policy["stdout"]["stop"] == {}  # type: ignore[index]


def test_cursor_local_and_codex_add_stop_and_subagent_stop_beside_the_kernel_hooks() -> None:
    expected = {f"python {SIGNAL_SCRIPT} hook stop", f"python {SIGNAL_SCRIPT} hook subagent_stop"}
    cursor = _cursor_hooks(project(LaneProfile.CURSOR_LOCAL))
    pack = {
        str(item["command"])
        for items in cursor.values()
        for item in items
        if _is_pack(item["command"])
    }
    assert pack == expected
    assert any("kernel.py" in str(item["command"]) for item in cursor["stop"])

    codex = project(LaneProfile.CODEX)
    settings = json.loads(codex.file(".codex/hooks.json").content)["hooks"]
    commands = {
        handler["command"]
        for groups in settings.values()
        for group in groups
        for handler in group["hooks"]
        if _is_pack(handler["command"])
    }
    assert commands == expected
    assert TELEMETRY_HOOK_ID in codex.report.requires_trust, "Codex hooks need hash trust"


def test_claude_cloud_runs_the_pack_asynchronously_on_its_session_and_stop_events() -> None:
    settings = json.loads(project(LaneProfile.CLAUDE_CLOUD).file(".claude/settings.json").content)
    pack = {
        (native, group.get("matcher"), handler["args"][2])
        for native, groups in settings["hooks"].items()
        for group in groups
        for handler in group["hooks"]
        if handler["args"][:2] == [SIGNAL_SCRIPT, "hook"]
        and handler["async"] is True
        and handler["command"] == "python"
    }
    assert pack == {
        ("SessionStart", None, "session_start"),
        ("PostToolUse", "Bash", "after_shell"),
        ("PostToolUse", "Edit|Write", "after_file_edit"),
        ("PreCompact", None, "before_compaction"),
        ("SubagentStop", None, "subagent_stop"),
        ("Stop", None, "stop"),
        ("SessionEnd", None, "session_end"),
    }
    assert signal_policy(LaneProfile.CLAUDE_CLOUD)["flush"] == ["stop", "session_end"]


def test_codex_cloud_gets_the_command_skill_and_an_advisory_line_but_no_hooks() -> None:
    projection = project(LaneProfile.CODEX_CLOUD)
    assert ADVISORY_INSTRUCTION in projection.file("AGENTS.override.md").content.decode()
    assert signal_policy(LaneProfile.CODEX_CLOUD)["signals"] == {}
    assert not any(item.path.endswith("hooks.json") for item in projection.files)


@pytest.mark.parametrize("lane", sorted(TELEMETRY_EVENTS))
def test_turning_the_pack_off_removes_every_trace(lane: LaneProfile) -> None:
    off = project(lane, telemetry=False)
    assert pack_paths(off) == set()
    assert SIGNAL_SCRIPT not in b"".join(item.content for item in off.files).decode()
    assert ADVISORY_INSTRUCTION not in b"".join(item.content for item in off.files).decode()
    assert TELEMETRY_HOOK_ID not in off.report.requires_trust


def _catalog_mc_signals() -> ResolvedCapability:
    content = b"---\nname: mc-signals\ndescription: The catalog's copy.\n---\n\nCatalog.\n"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    document = skill_row().definition.model_dump(mode="json")
    document.update(
        logical_id="skill.mc-signals",
        title="mc-signals",
        skill_name="mc-signals",
        frontmatter={"name": "mc-signals"},
        file_manifest=[{"path": "SKILL.md", "digest": digest, "size_bytes": len(content)}],
    )
    return ResolvedCapability(
        pin=CapabilityPin(capability_id="skill.mc-signals", version="0.1.0", digest=digest),
        definition=SkillDefinition.model_validate(document),
        files=(BundleFile(path="SKILL.md", content=content),),
    )


def test_a_catalog_mc_signals_skill_is_placed_instead_of_the_packaged_one() -> None:
    catalog = _catalog_mc_signals()
    projection = HOST_PROJECTORS.render((catalog,), LaneProfile.CURSOR_CLOUD, INSTRUCTION, None, ())
    placed = projection.file(".cursor/skills/mc-signals/SKILL.md").content
    assert placed == catalog.files[0].content


def test_the_packaged_skill_is_the_mc_signals_bundle() -> None:
    assert SIGNAL_SKILL_SOURCE.read_bytes() == SKILL_BUNDLE.read_bytes()

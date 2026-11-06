"""Ambient project and home cognition is inventoried before a local lane writes."""

from pathlib import Path

import pytest

from mission_control.application.agentic_components.ambient import inventory_ambient
from mission_control.application.agentic_components.materialization import (
    MaterializationRejected,
    materialize_projection,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.layering import MaterializationPolicy
from mission_control.domain.capabilities.host_support import LaneProfile
from tests.fixtures.projections.rows import INSTRUCTION, skill_row


def put(root: Path, path: str, content: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    ("lane", "repo_root", "home_root"),
    [
        (LaneProfile.CURSOR_LOCAL, ".claude", ".cursor"),
        (LaneProfile.CLAUDE_AGENT_SDK, ".claude", ".claude"),
        (LaneProfile.CODEX, ".agents", ".codex"),
    ],
)
def test_each_local_receipt_lists_cross_loaded_project_and_home_items(
    tmp_path: Path, lane: LaneProfile, repo_root: str, home_root: str
) -> None:
    workspace, home = tmp_path / "repo", tmp_path / "home"
    workspace.mkdir()
    put(workspace, f"{repo_root}/skills/ambient/SKILL.md", "project-private-content")
    put(home, f"{home_root}/agents/home-agent.md", "home-private-content")
    projection = HOST_PROJECTORS.render((skill_row(),), lane, INSTRUCTION)
    receipt = materialize_projection(projection, workspace, ambient_home=home)
    assert {(i.kind, i.name, i.origin) for i in receipt.ambient} >= {
        ("skill", "ambient", "repo"),
        ("subagent", "home-agent", "home"),
    }
    assert all(i.digest.startswith("sha256:") for i in receipt.ambient)
    assert "private-content" not in receipt.model_dump_json()


@pytest.mark.parametrize(
    ("lane", "root"),
    [
        (LaneProfile.CURSOR_LOCAL, ".claude"),
        (LaneProfile.CLAUDE_AGENT_SDK, ".claude"),
        (LaneProfile.CODEX, ".agents"),
    ],
)
def test_same_named_pack_skill_refuses_before_writing(
    tmp_path: Path, lane: LaneProfile, root: str
) -> None:
    put(tmp_path, f"{root}/skills/agent-browser/SKILL.md", "different repo skill")
    projection = HOST_PROJECTORS.render((skill_row(),), lane, INSTRUCTION)
    with pytest.raises(MaterializationRejected, match="ambient cognition conflicts"):
        materialize_projection(
            projection,
            tmp_path,
            ambient_home=tmp_path / "absent",
            policy=MaterializationPolicy(ambient="refuse_conflicts"),
        )
    assert not (tmp_path / ".mission").exists()


def test_cross_loaded_cursor_hooks_refuse_even_without_name_collision(tmp_path: Path) -> None:
    put(
        tmp_path,
        ".claude/settings.json",
        '{"hooks":{"PreToolUse":[{"hooks":[{"command":"echo local"}]}]}}',
    )
    projection = HOST_PROJECTORS.render((skill_row(),), "cursor_local", INSTRUCTION)
    # Imported Claude events use Claude names, unlike Cursor's native event names.
    with pytest.raises(MaterializationRejected, match="ambient cognition conflicts"):
        materialize_projection(
            projection,
            tmp_path,
            ambient_home=tmp_path / "absent",
            policy=MaterializationPolicy(ambient="refuse_conflicts"),
        )


def test_inventory_digest_changes_when_a_skill_support_file_changes(tmp_path: Path) -> None:
    put(tmp_path, ".agents/skills/ambient/SKILL.md", "skill")
    put(tmp_path, ".agents/skills/ambient/support.py", "first")
    projection = HOST_PROJECTORS.render((), "codex", INSTRUCTION)
    first = inventory_ambient(tmp_path, projection)
    put(tmp_path, ".agents/skills/ambient/support.py", "second")
    second = inventory_ambient(tmp_path, projection)
    assert first[0].digest != second[0].digest


def test_declared_ambient_name_is_used_and_allow_preserves_both(tmp_path: Path) -> None:
    put(
        tmp_path,
        ".claude/skills/alias/SKILL.md",
        "---\nname: agent-browser\ndescription: repo skill\n---\n",
    )
    projection = HOST_PROJECTORS.render((skill_row(),), "cursor_local", INSTRUCTION)
    with pytest.raises(MaterializationRejected, match="ambient cognition conflicts"):
        materialize_projection(
            projection,
            tmp_path,
            ambient_home=tmp_path / "absent",
            policy=MaterializationPolicy(ambient="refuse_conflicts"),
        )
    receipt = materialize_projection(
        projection,
        tmp_path,
        ambient_home=tmp_path / "absent",
        policy=MaterializationPolicy(ambient="allow"),
    )
    assert any(item.name == "agent-browser" for item in receipt.ambient)
    assert (tmp_path / ".claude/skills/alias/SKILL.md").read_text().endswith("---\n")


def test_ambient_default_does_not_change_preexisting_policy_serialization() -> None:
    assert MaterializationPolicy().model_dump() == {"conflicts": None}
    assert MaterializationPolicy(ambient="allow").model_dump()["ambient"] == "allow"


def test_malformed_local_hook_config_refuses_before_writes(tmp_path: Path) -> None:
    put(tmp_path, ".claude/settings.local.json", "{bad json")
    projection = HOST_PROJECTORS.render((), "claude_agent_sdk", INSTRUCTION)
    with pytest.raises(MaterializationRejected, match="ambient cognition conflicts"):
        materialize_projection(
            projection,
            tmp_path,
            ambient_home=tmp_path / "absent",
            policy=MaterializationPolicy(ambient="refuse_conflicts"),
        )
    assert not (tmp_path / ".mission").exists()


def test_junction_roots_are_not_inventoried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    put(tmp_path, ".agents/skills/foreign/SKILL.md", "not read")
    monkeypatch.setattr(Path, "is_junction", lambda path: path == tmp_path / ".agents")
    assert inventory_ambient(tmp_path, HOST_PROJECTORS.render((), "codex", INSTRUCTION)) == ()

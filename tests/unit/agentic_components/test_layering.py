"""MO-02: additive instruction layering and structural config merge (SPEC-02 §4).

The Host Projection is layered over a repository that already owns ``AGENTS.md``, a skill,
hooks, MCP servers and Codex settings: repository entries are kept byte for byte, Mission
Control's entries carry their provenance marker, conflicts resolve by the declared policy,
the merge is deterministic and idempotent, and the receipt lists merged keys and what each
native root holds from the repository and from the mission.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from mission_control.application.agentic_components.layering import (
    LAYERING_RECORD_PATH,
    DirectoryView,
    LayeredProjection,
    LayeringRefused,
    TreeView,
    layer_projection,
    repository_roots,
    restore_repository_files,
)
from mission_control.application.agentic_components.materialization import materialize_projection
from mission_control.application.agentic_components.telemetry import ADVISORY_INSTRUCTION
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.layering import (
    MISSION_SECTION_BEGIN,
    MISSION_SECTION_END,
    MISSION_SECTION_POINTER,
    ConflictCategory,
    ConflictPolicy,
    MaterializationPolicy,
    MergeFormat,
    conflict_category,
)
from mission_control.domain.agentic_components.projection import (
    HostProjection,
    ProjectedFile,
    ProjectionReport,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.layouts import CODEX_INSTRUCTIONS_LIMIT
from tests.fixtures.layering_repo import REPO_FILES
from tests.fixtures.projections.rows import (
    INSTRUCTION,
    hook_row,
    skill_row,
    tavily_row,
    verifier_row,
)

LOCAL_LANES = (LaneProfile.CURSOR_LOCAL, LaneProfile.CLAUDE_AGENT_SDK, LaneProfile.CODEX)
MISSION_WINS = MaterializationPolicy(conflicts=ConflictPolicy.MISSION_WINS)
REPO_WINS = MaterializationPolicy(conflicts=ConflictPolicy.REPO_WINS)
REFUSE = MaterializationPolicy(conflicts=ConflictPolicy.REFUSE)


def _project(profile: LaneProfile) -> HostProjection:
    rows = (skill_row(), tavily_row(), hook_row(), verifier_row())
    return HOST_PROJECTORS.render(rows, profile, INSTRUCTION)


def _layer(
    profile: LaneProfile,
    files: dict[str, bytes] | None = None,
    policy: MaterializationPolicy | None = None,
) -> LayeredProjection:
    repo = dict(REPO_FILES) if files is None else files
    return layer_projection(_project(profile), TreeView(repo), policy)


def _placed(layered: LayeredProjection) -> dict[str, bytes]:
    return {item.path: item.content for item in layered.files}


def _json(content: bytes) -> dict[str, object]:
    document = json.loads(content)
    assert isinstance(document, dict)
    return document


# --- instructions --------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", LOCAL_LANES)
def test_repository_instruction_files_are_never_placed(profile: LaneProfile) -> None:
    placed = _placed(_layer(profile))
    assert not {"AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md"} & set(placed)
    assert ".claude/skills/repo-notes/SKILL.md" not in placed


def test_codex_cloud_override_is_the_repository_agents_md_then_the_mission_section() -> None:
    layered = _layer(LaneProfile.CODEX_CLOUD)
    override = _placed(layered)["AGENTS.override.md"].decode()
    assert override.startswith(REPO_FILES["AGENTS.md"].decode().rstrip("\n") + "\n\n")
    section = override[override.index(MISSION_SECTION_BEGIN) :]
    assert section.endswith(MISSION_SECTION_END + "\n") and INSTRUCTION.strip() in section
    (merged,) = layered.receipt.merged
    assert merged.format is MergeFormat.INSTRUCTIONS_OVERRIDE
    assert merged.repo_keys == ("AGENTS.md",)
    # Layering its own output again changes nothing (the section is replaced, not repeated).
    again = layer_projection(
        _project(LaneProfile.CODEX_CLOUD),
        TreeView({**REPO_FILES, "AGENTS.override.md": override.encode()}),
    )
    assert _placed(again)["AGENTS.override.md"].decode() == override


def test_codex_cloud_override_points_at_the_contract_when_it_would_exceed_32_kib() -> None:
    instruction = "Mission detail.\n" * (CODEX_INSTRUCTIONS_LIMIT // 20)
    projection = HOST_PROJECTORS.render((), LaneProfile.CODEX_CLOUD, instruction)
    assert not projection.report.overflow, "the section alone fits"
    repo = {"AGENTS.md": b"Repository guide.\n" * 400}
    layered = layer_projection(projection, TreeView(repo))
    override = _placed(layered)["AGENTS.override.md"]
    assert len(override) <= CODEX_INSTRUCTIONS_LIMIT
    assert override.startswith(repo["AGENTS.md"].rstrip(b"\n"))
    assert MISSION_SECTION_POINTER.encode() in override and b"Mission detail." not in override
    assert layered.receipt.overflow
    contract = _placed(layered)[".mission/operating-contract.md"]
    # The Telemetry Hook Pack's advisory line follows the instruction (SPEC-04 section 4.2).
    assert contract.decode() == f"{instruction}\n\n{ADVISORY_INSTRUCTION}"


def test_a_repository_override_of_its_own_is_kept_before_the_mission_section() -> None:
    own = b"# Repository override\n\nUse the staging database.\n"
    layered = _layer(LaneProfile.CODEX_CLOUD, {**REPO_FILES, "AGENTS.override.md": own})
    override = _placed(layered)["AGENTS.override.md"]
    assert override.startswith(own.rstrip(b"\n") + b"\n\n" + MISSION_SECTION_BEGIN.encode())
    assert layered.receipt.merged[0].repo_keys == ("AGENTS.override.md",)


# --- structural merges ---------------------------------------------------------------------------


def test_claude_settings_and_mcp_keep_repository_entries_beside_marked_mission_entries() -> None:
    layered = _layer(LaneProfile.CLAUDE_AGENT_SDK)
    placed = _placed(layered)
    repo_settings = _json(REPO_FILES[".claude/settings.json"])
    settings = _json(placed[".claude/settings.json"])
    assert settings["permissions"] == repo_settings["permissions"]
    hooks = settings["hooks"]
    assert isinstance(hooks, dict)
    repo_group = repo_settings["hooks"]["PreToolUse"][0]  # type: ignore[index]
    pre_tool = hooks["PreToolUse"]
    # Mission Control's groups first (they run a script under .mission/hooks/), then the repo's.
    assert pre_tool[-1] == repo_group
    assert all(".mission/hooks/" in " ".join(g["hooks"][0]["args"]) for g in pre_tool[:-1])
    servers = _json(placed[".mcp.json"])["mcpServers"]
    assert isinstance(servers, dict)
    assert servers["repo-docs"] == {"type": "stdio", "command": "repo-docs"}
    assert "mc-tavily" in servers
    receipt = {item.path: item for item in layered.receipt.merged}
    assert "hooks.PreToolUse" in receipt[".claude/settings.json"].mission_keys
    assert {"permissions", "hooks.PreToolUse"} <= set(receipt[".claude/settings.json"].repo_keys)
    assert receipt[".mcp.json"].mission_keys == ("mcpServers.mc-tavily",)
    assert receipt[".mcp.json"].repo_keys == ("mcpServers.repo-docs",)
    assert not layered.receipt.conflicts
    assert set(layered.originals) == {".claude/settings.json", ".mcp.json"}


def test_cursor_hooks_put_kernel_hooks_first_and_keep_the_repository_hook() -> None:
    placed = _placed(_layer(LaneProfile.CURSOR_LOCAL))
    hooks = _json(placed[".cursor/hooks.json"])
    assert hooks["version"] == 1
    shell = hooks["hooks"]["beforeShellExecution"]  # type: ignore[index]
    assert shell[-1] == {"command": "./scripts/audit.sh"}
    assert all(".mission/hooks/" in entry["command"] for entry in shell[:-1])
    assert any("kernel.py" in entry["command"] for entry in shell[:-1])


def test_codex_config_keeps_the_repository_text_and_appends_a_marked_block() -> None:
    layered = _layer(LaneProfile.CODEX)
    text = _placed(layered)[".codex/config.toml"].decode()
    assert text.startswith(REPO_FILES[".codex/config.toml"].decode())
    config = tomllib.loads(text)
    assert config["model_reasoning_effort"] == "high"
    assert set(config["mcp_servers"]) == {"repo-docs", "mc-tavily"}
    (merged,) = (item for item in layered.receipt.merged if item.path == ".codex/config.toml")
    assert merged.mission_keys == ("mcp_servers.mc-tavily",)
    assert merged.repo_keys == ("model_reasoning_effort", "mcp_servers.repo-docs")


@pytest.mark.parametrize("profile", [*LOCAL_LANES, LaneProfile.CURSOR_CLOUD])
def test_layering_is_deterministic_and_idempotent(profile: LaneProfile) -> None:
    first = _layer(profile)
    assert _layer(profile) == first
    # Layered again over its own output (a reused lease or a restored fork): same bytes.
    repo = {**REPO_FILES, **_placed(first)}
    again = layer_projection(_project(profile), TreeView(repo))
    assert _placed(again) == _placed(first)
    assert [item.mission_keys for item in again.receipt.merged] == [
        item.mission_keys for item in first.receipt.merged
    ]


def test_stale_mission_entries_are_replaced_and_repository_entries_never_dropped() -> None:
    stale = {
        "mcpServers": {
            "repo-docs": {"type": "stdio", "command": "repo-docs"},
            "mc-retired": {"type": "stdio", "command": "old"},
        }
    }
    repo = {**REPO_FILES, ".mcp.json": json.dumps(stale).encode()}
    servers = _json(_placed(_layer(LaneProfile.CLAUDE_AGENT_SDK, repo))[".mcp.json"])["mcpServers"]
    assert set(servers) == {"repo-docs", "mc-tavily"}  # type: ignore[arg-type]


def test_a_merge_that_adds_nothing_keeps_the_repository_bytes() -> None:
    projection = HostProjection(
        profile=LaneProfile.CLAUDE_AGENT_SDK,
        files=(ProjectedFile(path=".mcp.json", content=b'{"mcpServers": {}}\n'),),
        report=ProjectionReport(),
    )
    layered = layer_projection(projection, TreeView(dict(REPO_FILES)))
    assert _placed(layered)[".mcp.json"] == REPO_FILES[".mcp.json"]
    assert not layered.originals


def test_a_repository_without_the_files_gets_the_projected_bytes() -> None:
    projection = _project(LaneProfile.CLAUDE_AGENT_SDK)
    layered = layer_projection(projection, TreeView({}))
    expected = {item.path: item.content for item in projection.files}
    assert _placed(layered) == expected and not layered.originals


# --- conflicts -----------------------------------------------------------------------------------


def _same_named_skill(profile: LaneProfile) -> dict[str, bytes]:
    root = {
        LaneProfile.CURSOR_LOCAL: ".cursor/skills",
        LaneProfile.CLAUDE_AGENT_SDK: ".claude/skills",
        LaneProfile.CODEX: ".agents/skills",
    }[profile]
    return {**REPO_FILES, f"{root}/agent-browser/SKILL.md": b"the repository's own skill\n"}


@pytest.mark.parametrize("profile", LOCAL_LANES)
def test_a_same_named_repository_skill_follows_the_policy(profile: LaneProfile) -> None:
    repo = _same_named_skill(profile)
    path = next(p for p in repo if p.endswith("agent-browser/SKILL.md"))
    # Default: `repo_wins` for everything but permissions and hooks.
    kept = _layer(profile, repo)
    assert path not in _placed(kept) and path in kept.receipt.skipped
    (conflict,) = kept.receipt.conflicts
    assert conflict.category is ConflictCategory.OTHER
    assert conflict.resolution is ConflictPolicy.REPO_WINS
    assert conflict.path == path.removesuffix("SKILL.md")
    origins = {item.origin for item in kept.receipt.discovery if item.name == "agent-browser"}
    assert origins == {"repo"}
    # `mission_wins`: Mission Control's bytes are placed and the repository's kept to restore.
    won = _layer(profile, repo, MISSION_WINS)
    assert _placed(won)[path].startswith(b"---\nname: agent-browser")
    assert won.originals[path] == b"the repository's own skill\n"
    assert won.receipt.conflicts[0].resolution is ConflictPolicy.MISSION_WINS
    with pytest.raises(LayeringRefused, match="agent-browser"):
        _layer(profile, repo, REFUSE)


def test_hook_conflicts_refuse_by_default() -> None:
    repo = {**REPO_FILES, ".cursor/hooks.json": b'{"version": 2, "hooks": {}}\n'}
    with pytest.raises(LayeringRefused, match="version"):
        _layer(LaneProfile.CURSOR_LOCAL, repo)
    kept = _layer(LaneProfile.CURSOR_LOCAL, repo, REPO_WINS)
    assert _json(_placed(kept)[".cursor/hooks.json"])["version"] == 2
    assert kept.receipt.conflicts[0].category is ConflictCategory.HOOK


def test_permission_conflicts_refuse_by_default() -> None:
    mission = {"permissions": {"deny": ["WebFetch"]}, "hooks": {}}
    projection = HostProjection(
        profile=LaneProfile.CLAUDE_AGENT_SDK,
        files=(ProjectedFile(path=".claude/settings.json", content=json.dumps(mission).encode()),),
        report=ProjectionReport(),
    )
    with pytest.raises(LayeringRefused, match="permission conflicts as refuse"):
        layer_projection(projection, TreeView(dict(REPO_FILES)))
    won = layer_projection(projection, TreeView(dict(REPO_FILES)), MISSION_WINS)
    settings = _json(_placed(won)[".claude/settings.json"])
    assert settings["permissions"] == mission["permissions"]
    assert won.receipt.merged[0].overridden == ("permissions",)


def test_conflict_categories_and_default_resolutions() -> None:
    assert (
        conflict_category(MergeFormat.MATCHER_HOOKS, "permissions") is ConflictCategory.PERMISSION
    )
    assert (
        conflict_category(MergeFormat.CODEX_CONFIG, "sandbox_mode") is ConflictCategory.PERMISSION
    )
    assert conflict_category(MergeFormat.CURSOR_HOOKS, "version") is ConflictCategory.HOOK
    assert conflict_category(MergeFormat.MCP_JSON, "mcpServers") is ConflictCategory.OTHER
    default = MaterializationPolicy()
    assert default.resolution(ConflictCategory.PERMISSION) is ConflictPolicy.REFUSE
    assert default.resolution(ConflictCategory.HOOK) is ConflictPolicy.REFUSE
    assert default.resolution(ConflictCategory.OTHER) is ConflictPolicy.REPO_WINS
    assert MISSION_WINS.resolution(ConflictCategory.HOOK) is ConflictPolicy.MISSION_WINS


def test_an_unparsable_repository_file_is_one_conflict() -> None:
    repo = {**REPO_FILES, ".mcp.json": b"{not json"}
    kept = _layer(LaneProfile.CLAUDE_AGENT_SDK, repo)
    assert ".mcp.json" in kept.receipt.skipped and ".mcp.json" not in _placed(kept)
    won = _layer(LaneProfile.CLAUDE_AGENT_SDK, repo, MISSION_WINS)
    assert "mc-tavily" in _json(_placed(won)[".mcp.json"])["mcpServers"]  # type: ignore[operator]


# --- discovery -----------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", LOCAL_LANES)
def test_discovery_reports_repository_and_mission_items(profile: LaneProfile) -> None:
    receipt = _layer(profile).receipt
    repo = {(item.kind, item.name) for item in receipt.discovered("repo")}
    mission = {(item.kind, item.name) for item in receipt.discovered("mission")}
    assert ("instructions", "AGENTS.md") in repo
    assert ("instructions", "mission overlay") in mission
    assert ("skill", "agent-browser") in mission
    assert ("subagent", "verifier") in mission
    assert any(kind == "mcp_server" and name.startswith("mc-") for kind, name in mission)
    assert any(kind == "hook" for kind, _name in mission)
    if profile is LaneProfile.CLAUDE_AGENT_SDK:
        assert {
            ("skill", "repo-notes"),
            ("hook", "PreToolUse"),
            ("mcp_server", "repo-docs"),
        } <= repo
    if profile is LaneProfile.CURSOR_LOCAL:
        assert ("hook", "beforeShellExecution") in repo
    if profile is LaneProfile.CODEX:
        assert ("mcp_server", "repo-docs") in repo


# --- the workspace: views, materialization and restore -------------------------------------------


def _write(root: Path, files: dict[str, bytes]) -> None:
    for path, content in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(content)


@pytest.mark.parametrize("profile", LOCAL_LANES)
def test_a_directory_and_a_commit_tree_layer_the_same(profile: LaneProfile, tmp_path: Path) -> None:
    _write(tmp_path, dict(REPO_FILES))
    projection = _project(profile)
    from_disk = layer_projection(projection, DirectoryView(tmp_path))
    roots = repository_roots(projection)
    tree = {
        path: content
        for path, content in REPO_FILES.items()
        if any(path == root or path.startswith(root + "/") for root in roots)
    }
    assert from_disk == layer_projection(projection, TreeView(tree))


def test_materialize_then_restore_leaves_repository_files_byte_identical(tmp_path: Path) -> None:
    _write(tmp_path, dict(REPO_FILES))
    projection = _project(LaneProfile.CLAUDE_AGENT_SDK)
    receipt = materialize_projection(projection, tmp_path, which=lambda _: "/bin/x")
    assert receipt.layering is not None and receipt.layering.merged
    assert (tmp_path / ".claude/settings.json").read_bytes() != REPO_FILES[".claude/settings.json"]
    assert (tmp_path / LAYERING_RECORD_PATH).is_file()
    # A reused lease layers again: the record keeps the repository's original bytes.
    materialize_projection(projection, tmp_path, which=lambda _: "/bin/x")
    restored = restore_repository_files(tmp_path)
    assert set(restored) == {".claude/settings.json", ".mcp.json"}
    assert {path: (tmp_path / path).read_bytes() for path in REPO_FILES} == dict(REPO_FILES)
    assert not (tmp_path / LAYERING_RECORD_PATH).exists()


def test_restore_leaves_a_file_the_session_changed(tmp_path: Path) -> None:
    _write(tmp_path, dict(REPO_FILES))
    materialize_projection(_project(LaneProfile.CODEX), tmp_path, which=lambda _: "/bin/x")
    edited = tmp_path / ".codex/config.toml"
    edited.write_bytes(edited.read_bytes() + b"\n# edited by the session\n")
    assert ".codex/config.toml" not in restore_repository_files(tmp_path)
    assert edited.read_bytes().endswith(b"# edited by the session\n")
    assert (tmp_path / ".codex/hooks.json").exists(), "a file new to the repository stays"

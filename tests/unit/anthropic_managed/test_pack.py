"""Pack files: the checked-in AI Engineer pack, refusals, rendering and the digests."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from mission_control.adapters.anthropic_managed.pack import (
    REPOSITORY_INSTRUCTIONS_HEADING,
    ClaudeManagedPack,
    PackRefused,
    RenderedPack,
    bundle_digest,
    load_pack,
    render_pack,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
AI_ENGINEER_PACK: Final = REPO_ROOT / "deployments/hosted-packs/ai-engineer/claude_managed"
INGRESS: Final = "ingress.example.com"


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    target = tmp_path / "pack"
    shutil.copytree(AI_ENGINEER_PACK, target)
    return target


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# Repo rules\n\nRun the tests before you finish.\n")
    return repo


def edit_yaml(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")


def rendered(
    pack: ClaudeManagedPack, repo: Path, *, ingress: str = INGRESS, installation: str = "local"
) -> RenderedPack:
    return render_pack(pack, installation_id=installation, repo_root=repo, ingress_host=ingress)


def test_the_ai_engineer_pack_is_internal_knowledge_on_the_hosted_queue() -> None:
    pack = load_pack(AI_ENGINEER_PACK)

    assert pack.pack_id == "ai-engineer/knowledge"
    assert pack.identity.data_class == "internal"
    assert pack.identity.task_queue == "mc-ai-engineer-lane-hosted"
    assert pack.agent.model == "claude-haiku-5-5"  # owner model choice 2026-11-06
    assert {name for name, policy in pack.agent.tools.items() if policy == "always_ask"} == {
        "bash",
        "write",
        "edit",
    }
    assert [credential.name for credential in pack.vault.credentials] == ["FIRECRAWL_API_KEY"]
    assert set(pack.skill_files) == {"mission-control-signals"}


def test_rendering_puts_the_repository_agents_md_into_system(target_repo: Path) -> None:
    result = rendered(load_pack(AI_ENGINEER_PACK), target_repo)

    overlay, _, repository = result.system.partition(REPOSITORY_INSTRUCTIONS_HEADING)
    assert overlay.startswith("You are a Mission Control knowledge agent")
    assert "Run the tests before you finish." in repository


def test_networking_is_always_limited_and_adds_the_ingress_host(target_repo: Path) -> None:
    config = rendered(load_pack(AI_ENGINEER_PACK), target_repo).environment_config

    assert config["networking"] == {
        "type": "limited",
        "allowed_hosts": ["api.firecrawl.dev", INGRESS],
        "allow_package_managers": False,
        "allow_mcp_servers": False,
    }


def test_the_agent_body_names_tools_skills_and_no_multiagent(target_repo: Path) -> None:
    result = rendered(load_pack(AI_ENGINEER_PACK), target_repo)
    body = result.agent_body([{"type": "custom", "skill_id": "skill_1", "version": "v1"}])

    toolset, *custom = body["tools"]
    assert toolset["type"] == "agent_toolset_20260401"
    assert toolset["default_config"] == {"enabled": False}
    assert {c["name"]: c["permission_policy"]["type"] for c in toolset["configs"]}[
        "bash"
    ] == "always_ask"
    assert [tool["name"] for tool in custom] == ["mc_prepare", "mc_signal"]
    assert body["skills"] == [{"type": "custom", "skill_id": "skill_1", "version": "v1"}]
    assert body["multiagent"] is None and body["mcp_servers"] == []


def test_digests_are_stable_and_follow_what_they_key(pack_dir: Path, target_repo: Path) -> None:
    pack = load_pack(pack_dir)
    base = rendered(pack, target_repo)
    assert rendered(load_pack(pack_dir), target_repo) == base

    (target_repo / "AGENTS.md").write_text("# Repo rules\n\nNew rule.\n")
    rules_changed = rendered(pack, target_repo)
    assert rules_changed.materialization_digest != base.materialization_digest
    assert rules_changed.kit_digest == base.kit_digest

    other_ingress = rendered(pack, target_repo, ingress="other.example.com")
    assert other_ingress.kit_digest != base.kit_digest
    assert other_ingress.environment_name != base.environment_name
    assert other_ingress.materialization_digest == rules_changed.materialization_digest

    other_installation = rendered(pack, target_repo, installation="hosted")
    assert other_installation.secret_set_digest != base.secret_set_digest

    edit_yaml(pack_dir / "agent.yaml", lambda doc: doc["metadata"].update(application="other"))
    metadata_changed = rendered(load_pack(pack_dir), target_repo)
    assert metadata_changed.materialization_digest != rules_changed.materialization_digest


def test_a_skill_bundle_digest_ignores_order_and_names_its_content() -> None:
    files = [("SKILL.md", b"a"), ("ref/x.md", b"b")]

    assert bundle_digest(files) == bundle_digest(list(reversed(files)))
    assert bundle_digest(files) != bundle_digest([("SKILL.md", b"a"), ("ref/x.md", b"c")])


def test_a_skill_display_name_carries_its_bundle_digest(target_repo: Path) -> None:
    (skill,) = rendered(load_pack(AI_ENGINEER_PACK), target_repo).skills

    digest = skill.bundle_digest.removeprefix("sha256:")
    assert skill.display_name == f"mc-mission-control-signals-{digest[:16]}"
    assert [path for path, _ in skill.upload()] == ["mission-control-signals/SKILL.md"]


def test_a_phi_pack_is_refused_on_claude_managed(pack_dir: Path) -> None:
    edit_yaml(pack_dir / "pack.yaml", lambda doc: doc.update(data_class="phi"))

    with pytest.raises(PackRefused, match="not ZDR-eligible"):
        load_pack(pack_dir)


def test_a_credential_host_outside_the_allowlist_is_refused(
    pack_dir: Path, target_repo: Path
) -> None:
    edit_yaml(
        pack_dir / "vault.yaml",
        lambda doc: doc.update(
            credentials=[{"name": "OTHER_TOKEN", "allowed_hosts": ["api.other.dev"]}]
        ),
    )

    with pytest.raises(PackRefused, match="credential_host_unreachable_error"):
        rendered(load_pack(pack_dir), target_repo)


def test_a_credential_may_reach_the_ingress_host_the_render_adds(
    pack_dir: Path, target_repo: Path
) -> None:
    edit_yaml(
        pack_dir / "vault.yaml",
        lambda doc: doc.update(credentials=[{"name": "MC_INGRESS", "allowed_hosts": [INGRESS]}]),
    )

    result = rendered(load_pack(pack_dir), target_repo)

    assert INGRESS in result.environment_config["networking"]["allowed_hosts"]


def test_a_wildcard_allowlist_entry_covers_a_credential_host(
    pack_dir: Path, target_repo: Path
) -> None:
    edit_yaml(
        pack_dir / "environment.yaml",
        lambda doc: doc["networking"].update(allowed_hosts=["*.firecrawl.dev"]),
    )

    result = rendered(load_pack(pack_dir), target_repo)

    assert result.environment_config["networking"]["allowed_hosts"] == ["*.firecrawl.dev", INGRESS]


def test_a_pack_file_carrying_an_api_key_is_refused(pack_dir: Path) -> None:
    with (pack_dir / "system.md").open("a", encoding="utf-8") as system:
        system.write("\nUse sk-ant-api03-AAAAAAAAAAAAAAAA if needed.\n")

    with pytest.raises(PackRefused, match="system.md: carries an Anthropic API key"):
        load_pack(pack_dir)


def test_repository_instructions_carrying_an_api_key_are_refused(target_repo: Path) -> None:
    (target_repo / "AGENTS.md").write_text("Use sk-ant-api03-AAAAAAAAAAAAAAAA if needed.\n")

    with pytest.raises(PackRefused, match="AGENTS.md: the target repository's instructions"):
        rendered(load_pack(AI_ENGINEER_PACK), target_repo)


def test_skill_directories_sharing_a_name_are_refused(pack_dir: Path) -> None:
    shutil.copytree(
        pack_dir / "skills/mission-control-signals", pack_dir / "more/mission-control-signals"
    )
    edit_yaml(
        pack_dir / "agent.yaml",
        lambda doc: doc["skills"].append("more/mission-control-signals"),
    )

    with pytest.raises(PackRefused, match="share the name mission-control-signals"):
        load_pack(pack_dir)


def test_a_skill_directory_without_skill_md_is_refused(pack_dir: Path) -> None:
    (pack_dir / "skills/mission-control-signals/SKILL.md").unlink()
    (pack_dir / "skills/mission-control-signals/notes.md").write_text("x")

    with pytest.raises(PackRefused, match="needs SKILL.md"):
        load_pack(pack_dir)


def test_pack_paths_cannot_escape_the_pack(pack_dir: Path) -> None:
    edit_yaml(pack_dir / "agent.yaml", lambda doc: doc.update(system="../outside.md"))
    (pack_dir.parent / "outside.md").write_text("x")

    with pytest.raises(PackRefused, match="not a path inside"):
        load_pack(pack_dir)


def test_packages_need_package_manager_egress(pack_dir: Path) -> None:
    edit_yaml(pack_dir / "environment.yaml", lambda doc: doc.update(packages={"pip": ["httpx"]}))

    with pytest.raises(PackRefused, match="allow_package_managers"):
        load_pack(pack_dir)


def test_signal_ingress_needs_the_ingress_host(target_repo: Path) -> None:
    pack = load_pack(AI_ENGINEER_PACK)

    with pytest.raises(PackRefused, match="Signal Ingress host"):
        render_pack(pack, installation_id="local", repo_root=target_repo, ingress_host=None)


def test_repository_instructions_need_the_target_repository() -> None:
    with pytest.raises(PackRefused, match="target repository root"):
        render_pack(load_pack(AI_ENGINEER_PACK), installation_id="local", ingress_host=INGRESS)


def test_unknown_tools_and_reserved_metadata_are_refused(pack_dir: Path) -> None:
    edit_yaml(pack_dir / "agent.yaml", lambda doc: doc["tools"].update(task="always_allow"))
    with pytest.raises(PackRefused, match="unknown agent toolset tool"):
        load_pack(pack_dir)

    shutil.copy(AI_ENGINEER_PACK / "agent.yaml", pack_dir / "agent.yaml")
    edit_yaml(pack_dir / "agent.yaml", lambda doc: doc.update(metadata={"mc_pack": "x"}))
    with pytest.raises(PackRefused, match="reserved"):
        load_pack(pack_dir)

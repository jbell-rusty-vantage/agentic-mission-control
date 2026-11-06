"""HL-11: `codex_agents` pack files load, refuse what policy forbids and digest by part."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from mission_control.adapters.openai_agents.pack import (
    PackError,
    load_pack,
    pack_directory,
)
from tests.unit.openai_agents.support import SHIPPED_PACK, copy_pack


def _edit(pack: Path, change: dict[str, Any]) -> None:
    path = pack / "pack.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    for dotted, value in change.items():
        *parents, leaf = dotted.split(".")
        target = document
        for key in parents:
            target = target[key]
        target[leaf] = value
    path.write_text(yaml.safe_dump(document), encoding="utf-8")


def test_the_shipped_ai_engineer_pack_is_an_internal_codex_agents_pack() -> None:
    pack = load_pack(pack_directory(SHIPPED_PACK.parents[2], "ai-engineer"))

    document = pack.document
    assert (document.application, document.lane_profile, document.tool_placement) == (
        "ai-engineer",
        "codex_agents",
        "openai_hosted",
    )
    assert (document.data_class, document.task_queue) == ("internal", "mc-ai-engineer-lane-hosted")
    assert pack.agent_config["model"] == "gpt-6.1-sol"  # owner model choice 2026-11-06
    assert pack.agent_config["multi_agent"] == {"enabled": False}
    tools = pack.agent_config["tools"]
    assert tools and all(tool["type"] == "function" for tool in tools)
    assert all(tool["name"].startswith("mc_") and tool["description"] for tool in tools)
    assert [skill.name for skill in pack.skills] == ["cited-findings"]
    assert document.environment.network.access == "restricted"
    assert [credential.name for credential in document.vault.credentials] == ["GITHUB_TOKEN"]


def test_the_repository_rules_are_inlined_after_the_instruction_overlay() -> None:
    pack = load_pack(SHIPPED_PACK)

    overlay = (SHIPPED_PACK / "instructions.md").read_text(encoding="utf-8").strip()
    rules = (SHIPPED_PACK / "repo-rules.md").read_text(encoding="utf-8").strip()
    assert pack.instructions == f"{overlay}\n\n## Repository rules\n\n{rules}"
    assert pack.agent_config["instructions"] == pack.instructions


def test_loading_twice_gives_the_same_digests() -> None:
    first, second = load_pack(SHIPPED_PACK), load_pack(SHIPPED_PACK)

    assert first.digest == second.digest
    assert first.template_body() == second.template_body()
    assert first.template_name == f"mc-ai-engineer-{first.template_digest[7:23]}"


def test_a_skill_edit_moves_the_template_and_pack_digests_but_not_the_agent(
    tmp_path: Path,
) -> None:
    pack = copy_pack(tmp_path)
    before = load_pack(pack)
    skill = pack / "skills" / "cited-findings" / "SKILL.md"
    skill.write_bytes(skill.read_bytes() + b"\n5. Keep it short.\n")

    after = load_pack(pack)
    assert after.template_digest != before.template_digest
    assert after.digest != before.digest
    assert after.agent_digest == before.agent_digest
    assert after.secret_set_digest == before.secret_set_digest


def test_an_instruction_edit_moves_only_the_agent_side(tmp_path: Path) -> None:
    pack = copy_pack(tmp_path)
    before = load_pack(pack)
    with (pack / "instructions.md").open("a", encoding="utf-8") as overlay:
        overlay.write("- Prefer primary sources.\n")

    after = load_pack(pack)
    assert after.agent_digest != before.agent_digest
    assert after.digest != before.digest
    assert after.template_digest == before.template_digest


def test_the_template_inlines_skills_and_plugins_as_stable_zips(tmp_path: Path) -> None:
    pack = copy_pack(tmp_path)
    plugin = pack / "plugins" / "notes"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "notes", "description": "Shared note templates."}), encoding="utf-8"
    )
    (plugin / "skills").mkdir()
    (plugin / "skills" / "README.md").write_text("notes\n", encoding="utf-8")
    _edit(pack, {"environment.plugins": "plugins"})

    body = load_pack(pack).template_body()
    assert body == load_pack(pack).template_body()
    [skill] = body["skills"]
    assert (skill["type"], skill["name"], skill["source"]["media_type"]) == (
        "inline",
        "cited-findings",
        "application/zip",
    )
    names = zipfile.ZipFile(io.BytesIO(base64.b64decode(skill["source"]["data"]))).namelist()
    assert names == ["cited-findings/SKILL.md"]
    [inline_plugin] = body["plugins"]
    archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(inline_plugin["source"]["data"])))
    assert archive.namelist() == [".codex-plugin/plugin.json", "skills/README.md"]
    assert (inline_plugin["name"], inline_plugin["description"]) == (
        "notes",
        "Shared note templates.",
    )


def test_pack_files_hold_no_credential_value() -> None:
    document = yaml.safe_load((SHIPPED_PACK / "pack.yaml").read_text(encoding="utf-8"))

    for credential in document["vault"]["credentials"]:
        assert set(credential) == {"name", "source_env", "allowed_hosts"}


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"data_class": "phi"}, "admits only data class"),
        ({"data_class": "secret"}, "admits only data class"),
        ({"agent.multi_agent": True}, "multi_agent"),
        (
            {
                "agent.function_tools": [
                    {"name": "publish", "description": "x", "parameters": {"type": "object"}}
                ]
            },
            "function_tools",
        ),
        (
            {"agent.function_tools": [{"name": "mc_signal", "parameters": {"type": "object"}}]},
            "description",
        ),
        ({"environment.env": {"OPENAI_API_KEY": "x"}}, "reserved"),
        ({"environment.env": {"CODEX_HOME": "/x"}}, "reserved"),
        ({"environment.env": {"PATH": "/bin"}}, "reserved"),
        ({"environment.network": {"access": "restricted"}}, "allowed_domains"),
        (
            {"environment.network": {"access": "enabled", "allowed_domains": ["pypi.org"]}},
            "allowed_domains",
        ),
        (
            {"environment.network": {"access": "restricted", "allowed_domains": ["*.github.com"]}},
            "exact lowercase host",
        ),
        (
            {"environment.network": {"access": "restricted", "allowed_domains": ["pypi.org"]}},
            "network policy does not allow",
        ),
        ({"environment.network": {"access": "disabled"}}, "need network access"),
        (
            {
                "vault.credentials": [
                    {
                        "name": "OPENAI_TOKEN",
                        "source_env": "OPENAI_API_KEY",
                        "allowed_hosts": ["api.github.com"],
                    }
                ]
            },
            "organisation key",
        ),
        (
            {
                "vault.credentials": [
                    {"name": "CODEX_TOKEN", "source_env": "X", "allowed_hosts": ["api.github.com"]}
                ]
            },
            "reserved variable",
        ),
        (
            {
                "vault.credentials": [
                    {"name": "T", "source_env": "X", "allowed_hosts": ["api.github.com"]},
                    {"name": "T", "source_env": "Y", "allowed_hosts": ["api.github.com"]},
                ]
            },
            "distinct",
        ),
        (
            {
                "vault.credentials": [
                    {"name": "T", "source_env": "X", "allowed_hosts": ["api.github.com"]}
                ],
                "vault.secret_value": "leaked",
            },
            "secret_value",
        ),
        ({"tool_placement": "self_hosted"}, "tool_placement"),
    ],
)
def test_policy_violations_are_refused(tmp_path: Path, change: dict[str, Any], reason: str) -> None:
    pack = copy_pack(tmp_path)
    _edit(pack, change)

    with pytest.raises(PackError) as refused:
        load_pack(pack)
    assert reason in str(refused.value.__cause__)


def test_a_skill_whose_name_differs_from_its_directory_is_refused(tmp_path: Path) -> None:
    pack = copy_pack(tmp_path)
    (pack / "skills" / "cited-findings").rename(pack / "skills" / "findings")

    with pytest.raises(PackError, match="the directory must match"):
        load_pack(pack)


def test_an_instruction_file_outside_the_pack_is_refused(tmp_path: Path) -> None:
    pack = copy_pack(tmp_path)
    (tmp_path / "elsewhere.md").write_text("outside\n", encoding="utf-8")
    _edit(pack, {"agent.instructions": "../elsewhere.md"})

    with pytest.raises(PackError, match="outside the pack"):
        load_pack(pack)

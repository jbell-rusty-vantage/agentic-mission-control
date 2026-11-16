"""The coordinator skill bundles cannot drift from the guide or from `missionctl`.

A bundle's `SKILL.md` is a short router of judgment; its reference material is the guide as
`scripts/skills_from_guide.py` renders it for the `missionctl` surface. These tests hold the
bundles to that: the generated references equal a fresh rendering, every `missionctl` command
any shipped bundle names is in the argparse tree with the flags it uses, no bundle carries a
delivery marker of a ticket that shipped, and the hand-written chain reference validates
against the manifest model.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

from mission_control.application.guide.pages import INDEX, TOPIC_IDS
from mission_control.domain.authoring.manifest import ChainLinkDeclaration, load_manifest_yaml
from mission_control.interfaces.cli.exits import WAIT_TIMEOUT, exit_status
from mission_control.interfaces.cli.main import build_parser

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "skills"
ROUTER = "mission-control"
# Each coordinator bundle with the line count its `SKILL.md` had before it followed the guide:
# a bundle is a router of judgment and does not grow back into a manual.
COORDINATOR_BUNDLES = {
    "mission-control": 54,
    "mission-control-author": 111,
    "mission-control-catalog": 87,
    "mission-control-observe": 97,
    "mission-control-intervene": 96,
    "mission-control-compose": 70,
}
# What an agent reaches the server's own answers with; the router names each.
SERVER_COMMANDS = (
    "missionctl whoami",
    "missionctl guide",
    "missionctl describe",
    "missionctl search",
    "missionctl workspace check",
)
_INLINE = re.compile(r"`(missionctl(?: [^`]*)?)`")
_FENCE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
_MARKER = re.compile(r"\bFT-[A-Z]?\d|Availability:")


def _script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FROM_GUIDE = _script("skills_from_guide")


def _cli_parsers() -> dict[tuple[str, ...], argparse.ArgumentParser]:
    """Every `missionctl` path with its parser: `("mission", "compile")`, `("guide",)` ..."""

    found: dict[tuple[str, ...], argparse.ArgumentParser] = {}

    def walk(parser: argparse.ArgumentParser, prefix: tuple[str, ...]) -> None:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    found[(*prefix, name)] = child
                    walk(child, (*prefix, name))

    walk(build_parser(), ())
    return found


def _calls(text: str) -> list[str]:
    """Every `missionctl ...` call a Markdown file writes: in a code span, or on a line of a
    fenced block (a continued line is joined)."""

    # A bare `missionctl` is the tool's name, not a call.
    calls = [call for call in _INLINE.findall(text) if call != "missionctl"]
    for block in _FENCE.findall(text):
        joined = block.replace("\\\n", " ")
        calls += [line.strip() for line in joined.splitlines() if line.startswith("missionctl ")]
    return calls


def _problem(call: str, parsers: dict[tuple[str, ...], argparse.ArgumentParser]) -> str | None:
    """Why `call` is not a `missionctl` command, or `None`."""

    words = call.split()
    path: tuple[str, ...] = ()
    rest = words[1:]
    while rest and (*path, rest[0]) in parsers:
        path, rest = (*path, rest[0]), rest[1:]
    if not path:
        return "names no missionctl command"
    parser = parsers[path]
    groups = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if groups and groups[0].required:
        named = rest[0] if rest else "nothing"
        return f"`missionctl {' '.join(path)}` needs a subcommand, got {named}"
    known = {option for action in parser._actions for option in action.option_strings}
    unknown = [word for word in rest if word.startswith("--") and word not in known]
    if unknown:
        return f"`missionctl {' '.join(path)}` has no {', '.join(unknown)}"
    return None


def _bundle_markdown() -> list[Path]:
    return sorted(
        path
        for bundle in SKILLS.iterdir()
        if (bundle / "SKILL.md").is_file()
        for path in bundle.rglob("*.md")
    )


# -- generated from the guide --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_generated_references_equal_a_fresh_rendering_of_the_guide() -> None:
    rendered = await FROM_GUIDE.render()
    assert rendered, "no reference is generated"
    for path, content in rendered.items():
        assert path.is_file(), f"{path.relative_to(ROOT)}: run `make skills-references`"
        assert path.read_bytes() == content, (
            f"{path.relative_to(ROOT)} differs from the guide: run `make skills-references`, "
            "bump the bundle version and run `make skills-manifest`"
        )
    assert FROM_GUIDE.stale(set(rendered)) == []


def test_every_guide_page_is_carried_by_exactly_one_bundle() -> None:
    carried = [page for pages in FROM_GUIDE.BUNDLE_PAGES.values() for page in pages]
    assert sorted(carried) == sorted([INDEX, FROM_GUIDE.WHOAMI, *TOPIC_IDS])
    assert set(FROM_GUIDE.BUNDLE_PAGES) == set(COORDINATOR_BUNDLES) - {"mission-control-compose"}
    for bundle, pages in FROM_GUIDE.BUNDLE_PAGES.items():
        skill = (SKILLS / bundle / "SKILL.md").read_text(encoding="utf-8")
        manifest = json.loads((SKILLS / bundle / "manifest.json").read_bytes())
        for page in pages:
            reference = FROM_GUIDE.reference_path(bundle, page)
            relative = reference.relative_to(SKILLS / bundle).as_posix()
            # The bundle pins the page and its `SKILL.md` points at it.
            assert relative in manifest["files"], (bundle, relative)
            assert f"({relative})" in skill, (bundle, relative)


@pytest.mark.asyncio
async def test_a_reference_answers_for_no_installation() -> None:
    """A page rendered with no installation behind it says where the installation's answer
    is; it never states the empty catalog, model list or sandbox list of the rendering."""

    for path, content in (await FROM_GUIDE.render()).items():
        text = content.decode("utf-8")
        assert text.startswith("<!-- Generated by scripts/skills_from_guide.py"), path
        for offline in (
            "No catalog is composed",
            "no catalog is composed",
            "The catalog is not composed",
            "0 Model Profiles",
            "does not launch",
            "does not allow unqualified lanes",
        ):
            assert offline not in text, (path.name, offline)
    assert set(FROM_GUIDE.LIVE) <= {INDEX, *TOPIC_IDS}
    with pytest.raises(SystemExit, match="expected one paragraph"):
        FROM_GUIDE.swap_live(INDEX, "# A start page the guide no longer writes")


# -- judgment, held to the CLI -------------------------------------------------------------------


def test_every_missionctl_command_a_bundle_names_is_in_the_cli() -> None:
    parsers = _cli_parsers()
    checked = 0
    problems = []
    for path in _bundle_markdown():
        for call in _calls(path.read_text(encoding="utf-8")):
            checked += 1
            problem = _problem(call, parsers)
            if problem:
                problems.append(f"{path.relative_to(ROOT).as_posix()}: `{call}`: {problem}")
    assert not problems, "\n".join(problems)
    assert checked > 100
    # The check itself refuses what the tree does not hold.
    assert _problem("missionctl frobnicate RUN_ID", parsers)
    assert _problem("missionctl run frobnicate RUN_ID", parsers)
    assert _problem("missionctl run inspect RUN_ID --no-such-flag", parsers)
    assert _problem("missionctl catalog", parsers)
    assert (
        _problem("missionctl run fork RUN_ID --point POINT_ID --at stage:S,cycle:1", parsers)
        is None
    )


def test_the_router_names_the_commands_that_ask_the_server() -> None:
    router = (SKILLS / ROUTER / "SKILL.md").read_text(encoding="utf-8")
    for command in SERVER_COMMANDS:
        assert f"`{command}" in router, command
    for bundle in COORDINATOR_BUNDLES:
        assert f"`{bundle}`" in router or bundle == ROUTER
    # The exit codes it states are the CLI's.
    sentence = " ".join(router.split("exit code")[1].split("Inspect.")[0].split())
    stated = dict(re.findall(r"(\d) ([a-z][a-z ]+)", sentence))
    assert set(stated) == {"0", "2", "3", "4", "5", str(WAIT_TIMEOUT)}
    assert [exit_status(code) for code in (200, 422, 403, 409, 503)] == [0, 2, 3, 4, 5]
    assert "denied" in stated["3"] and "conflict" in stated["4"] and "unavailable" in stated["5"]


def test_a_coordinator_bundle_is_short_and_carries_no_shipped_ticket_marker() -> None:
    for bundle, ceiling in COORDINATOR_BUNDLES.items():
        skill = SKILLS / bundle / "SKILL.md"
        lines = skill.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= ceiling, f"{bundle}/SKILL.md has {len(lines)} lines (was {ceiling})"
        assert "missionctl guide" in "\n".join(lines) or bundle == "mission-control-compose"
        for path in (SKILLS / bundle).rglob("*.md"):
            assert not _MARKER.search(path.read_text(encoding="utf-8")), path
    # What the stale bundles got wrong stays out: the manifest refuses a mission-level `inputs`
    # and no bundle restates which lane injects how.
    author = (SKILLS / "mission-control-author" / "SKILL.md").read_text(encoding="utf-8")
    assert "Mission-level `inputs`: the manifest refuses them" in author
    intervene = (SKILLS / "mission-control-intervene" / "SKILL.md").read_text(encoding="utf-8")
    assert "no first-wave lane" not in intervene
    control = (SKILLS / "mission-control-intervene" / "references" / "guide-control.md").read_text(
        encoding="utf-8"
    )
    deep_agents = next(line for line in control.splitlines() if line.startswith("| `deep_agents`"))
    assert "cooperative_inject" in deep_agents


def test_the_chain_reference_validates_against_the_manifest_model() -> None:
    """`mission-control-compose` keeps a hand-written reference: every link it shows is a valid
    `links` entry, and every field or value it names is the model's."""

    text = (SKILLS / "mission-control-compose" / "references" / "chain-patterns.md").read_text(
        encoding="utf-8"
    )
    links = [
        ChainLinkDeclaration.model_validate(link)
        for block in re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
        for link in load_manifest_yaml(block).get("links", [])
    ]
    assert len(links) >= 4
    assert {link.kind for link in links} == {"supplies", "depends_on"}
    fields = ChainLinkDeclaration.model_fields
    assert fields["on_upstream_cancel"].default == "continue"
    assert "`continue` (default)" in text and "`goal_accepted` (default)" in text
    for value in ("cancel_downstream", "detach", "mission_accepted", "execution_complete"):
        assert f"`{value}`" in text
    assert "release_on" not in text
    skill = (SKILLS / "mission-control-compose" / "SKILL.md").read_text(encoding="utf-8")
    assert "release_on" not in skill and "existing_mission_ref" not in skill

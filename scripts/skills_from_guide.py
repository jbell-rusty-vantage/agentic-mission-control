#!/usr/bin/env python3
"""Render the guide into the coordinator skill bundles' references, or verify they are current.

The guide (``src/mission_control/application/guide``) is the one statement of how to drive
Mission Control, held to the tool, command and route surface by ``tests/unit/guide``. A
coordinator skill bundle under ``skills/`` therefore states no operational fact of its own: its
``SKILL.md`` carries judgment, and its reference material is this script's output, the guide
pages of the bundle's job as the guide service renders them for the ``missionctl`` surface
(``references/guide-<topic>.md``) and the shape of ``missionctl whoami``
(``references/whoami.md``).

The service is composed as the API composes it when every lane profile is bound, with no
installation behind it: no Model Catalog rows, no catalog, no sandbox bindings. Where a page
then answers for "this server", the answer belongs to an installation, so the paragraph is
replaced by the command that prints it (``LIVE``). A paragraph the guide no longer writes is an
error here, never a silent miss.

Usage:
  python scripts/skills_from_guide.py --write   # rewrite the generated references
  python scripts/skills_from_guide.py --check   # exit 1 on a differing, missing or stale one

Edit the guide page, run ``--write``, bump the bundle's version and run
``scripts/skills_manifest.py --write``. Output is LF bytes; two runs are byte-identical.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Final, get_args

from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.application.guide.pages import INDEX, TOPIC_IDS
from mission_control.application.guide.service import GuideService
from mission_control.application.guide.whoami import (
    WHOAMI_SCHEMA,
    LaneTimeTravel,
    PrincipalFacts,
    ServerFacts,
    whoami,
)
from mission_control.application.resolution.registries import ModelCatalog
from mission_control.bootstrap.guide import LANE_FEATURE_REGISTRIES
from mission_control.bootstrap.lanes import SESSION_LANES, describe_only_registry
from mission_control.domain.execution.lanes import LANE_PROFILES

ROOT: Final = Path(__file__).resolve().parents[1]
SKILLS: Final = ROOT / "skills"
SURFACE: Final = "cli"
# The application id of a rendering that has no installation: a placeholder in the capitals
# `missionctl` help uses for one.
APPLICATION: Final = "APPLICATION_ID"
WHOAMI: Final = "whoami"
# Bundle -> the guide pages of its job, in the order a Coordinator meets them.
BUNDLE_PAGES: Final[dict[str, tuple[str, ...]]] = {
    "mission-control": (INDEX, WHOAMI),
    "mission-control-author": ("interview", "templates", "manifest", "launch"),
    "mission-control-catalog": ("capabilities", "lanes", "models", "workflows"),
    "mission-control-observe": ("observe",),
    "mission-control-intervene": ("control",),
}
# Topic -> (how the paragraph an installation owns starts, what a bundle says in its place).
LIVE: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    INDEX: (
        (
            "This server: application ",
            "Your server's application, bound lanes, Model Profile count, catalog size and "
            "templates: `missionctl guide`.",
        ),
    ),
    "workflows": (
        (
            "This installation ",
            "Your installation's rule on unqualified lanes: `missionctl guide workflows`.",
        ),
        (
            "The catalog is not composed",
            "Your catalog's count of published Workflow Types: `missionctl guide workflows`.",
        ),
    ),
    "manifest": (
        (
            "This server does not launch",
            "Your installation's bound sandbox profiles: "
            "`missionctl search --facet sandbox_profile`.",
        ),
    ),
    "models": (
        (
            "| Model Profile |",
            "Your installation's Model Profiles: `missionctl search --facet model`.",
        ),
    ),
    "capabilities": (
        (
            "No catalog is composed",
            "Your catalog's kinds and how many of each it publishes: "
            "`missionctl guide capabilities`.",
        ),
    ),
}
GENERATED_NAMES: Final = ("guide-*.md", f"{WHOAMI}.md")


def reference_path(bundle: str, page: str) -> Path:
    name = f"{WHOAMI}.md" if page == WHOAMI else f"guide-{page}.md"
    return SKILLS / bundle / "references" / name


def release_guide() -> GuideService:
    """The guide over every lane profile this release declares and nothing an installation
    adds."""

    lanes = describe_only_registry(
        bound=LANE_PROFILES,
        allow_unqualified=False,
        registrations=(deep_agents_lane(None), *SESSION_LANES.values()),
    )
    return GuideService(
        application_id=APPLICATION,
        lanes=lanes,
        models=ModelCatalog(),
        catalog=None,
        features=LANE_FEATURE_REGISTRIES,
        sandbox_profiles=None,
    )


def swap_live(topic: str, markdown: str) -> str:
    """`markdown` with each paragraph an installation owns replaced by its command."""

    paragraphs = markdown.split("\n\n")
    for start, instead in LIVE.get(topic, ()):
        found = [index for index, text in enumerate(paragraphs) if text.startswith(start)]
        if len(found) != 1:
            raise SystemExit(
                f"guide topic {topic}: expected one paragraph starting {start!r}, found "
                f"{len(found)}; update LIVE in scripts/skills_from_guide.py"
            )
        paragraphs[found[0]] = instead
    return "\n\n".join(paragraphs)


def _header(source: str, command: str, body: str) -> str:
    lines = [
        f"<!-- Generated by scripts/skills_from_guide.py from {source}. Do not edit: change "
        "the guide, then run `make skills-references`. -->",
        "",
        f"> `{command}` as this release renders it, with no installation behind it. Where this "
        "file and your server differ, the server is right.",
    ]
    if "| Lane profile |" in body or "| Lane |" in body:
        lines.append(
            "> Lane tables list every lane profile the release declares; your server binds "
            "some of them."
        )
    if f"`{APPLICATION}`" in body:
        lines.append(
            f"> `{APPLICATION}` stands for your server's application id (`missionctl whoami`)."
        )
    return "\n".join(lines)


async def guide_reference(guide: GuideService, topic: str) -> str:
    page = await (guide.index(SURFACE) if topic == INDEX else guide.topic(topic, SURFACE))
    body = swap_live(topic, page.markdown)
    command = "missionctl guide" if topic == INDEX else f"missionctl guide {topic}"
    return f"{_header(f'guide topic `{topic}`', command, body)}\n\n{body}\n"


def whoami_reference() -> str:
    """The `mc.whoami.v1` document as its model prints it, placeholders in capitals."""

    document = whoami(
        PrincipalFacts(
            actor_id="ACTOR_ID",
            installation_id="INSTALLATION_ID",
            application_id=APPLICATION,
            tenant_id="TENANT_ID",
            request_scope="REQUEST_SCOPE",
            permissions=frozenset({"PERMISSION", "reviewer:ROLE"}),
            authority_refs=frozenset({"AUTHORITY_REF"}),
            sponsorship_refs=frozenset({"SPONSORSHIP_REF"}),
            approval_refs=frozenset({"APPROVAL_REF"}),
        ),
        ServerFacts(
            time_travel=(
                LaneTimeTravel(
                    lane_profile="LANE_PROFILE",
                    declared_read="LEVEL",
                    declared_fork="LEVEL",
                    state_as_of="not_composed",
                    prerequisite="WHAT THE DEPLOYMENT MUST PROVIDE",
                ),
            ),
            external_discovery="not_composed",
        ),
    ).model_dump(mode="json")
    states = get_args(LaneTimeTravel.model_fields["state_as_of"].annotation)
    discovery = get_args(ServerFacts.model_fields["external_discovery"].annotation)
    body = "\n".join(
        [
            "# Who you are: `missionctl whoami`",
            "",
            f"One JSON document, `{WHOAMI_SCHEMA}`: the verified principal of the token in use "
            "and what this server composed. It reads nothing a request body says. Placeholders "
            "are in capitals.",
            "",
            "```json",
            json.dumps(document, indent=2, ensure_ascii=False),
            "```",
            "",
            f"- `server.time_travel[].state_as_of`: {_spans(states)}; `prerequisite` is "
            "present only where the state is not `readable`.",
            f"- `server.external_discovery`: {_spans(discovery)}.",
        ]
    )
    return f"{_header(f'the `{WHOAMI_SCHEMA}` model', 'missionctl whoami', body)}\n\n{body}\n"


def _spans(values: tuple[str, ...]) -> str:
    return ", ".join(f"`{value}`" for value in values)


async def render() -> dict[Path, bytes]:
    """Every generated reference: path -> LF bytes."""

    unknown = {
        page for pages in BUNDLE_PAGES.values() for page in pages if page not in {INDEX, WHOAMI}
    } - set(TOPIC_IDS)
    if unknown:
        raise SystemExit(f"BUNDLE_PAGES names no guide topic: {sorted(unknown)}")
    guide = release_guide()
    rendered: dict[Path, bytes] = {}
    for bundle, pages in BUNDLE_PAGES.items():
        for page in pages:
            text = whoami_reference() if page == WHOAMI else await guide_reference(guide, page)
            rendered[reference_path(bundle, page)] = text.replace("\r\n", "\n").encode("utf-8")
    return rendered


def stale(expected: set[Path]) -> list[Path]:
    """Generated-looking references no bundle maps any more."""

    found = {
        path
        for pattern in GENERATED_NAMES
        for path in SKILLS.glob(f"*/references/{pattern}")
        if path.is_file()
    }
    return sorted(found - expected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify; exit 1 on any difference")
    mode.add_argument("--write", action="store_true", help="rewrite the generated references")
    args = parser.parse_args(argv)

    rendered = asyncio.run(render())
    leftovers = stale(set(rendered))
    if args.write:
        for path, content in rendered.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"wrote    {path.relative_to(ROOT).as_posix()}")
        for path in leftovers:
            path.unlink()
            print(f"removed  {path.relative_to(ROOT).as_posix()}")
        return 0
    failures = 0
    for path, content in rendered.items():
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            print(f"MISSING  {relative}")
            failures += 1
        elif path.read_bytes() != content:
            print(f"DRIFT    {relative}: differs from the guide; run `make skills-references`")
            failures += 1
        else:
            print(f"ok       {relative}")
    for path in leftovers:
        print(f"STALE    {path.relative_to(ROOT).as_posix()}: no bundle maps this page")
        failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

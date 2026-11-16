"""`missionctl guide`, `describe` and `whoami`: how to use the server, read from the server.

``whoami`` prints `mc.whoami.v1` (`GET /whoami`): the actor, tenant, permissions, sponsorship
and approval refs and reviewer names of the token in use, and what the server composed.
``guide [TOPIC]`` prints the start page (who you are, the jobs in order, the commands for
each) or one topic; ``describe REF`` prints everything about one thing (`lane:<profile>`,
`model:<profile>`, `feature:<id>`, `tool:<name>`, `template:<id>`, `sandbox:<profile>`,
`manifest`, `manifest:<section>` or a Capability Pin). Both are thin clients of
`GET /guide[/{topic}]` and `GET /describe`, the routes behind the MCP tools ``mission_guide``
and ``mission_describe``. Plain Markdown by default, with every call written as a `missionctl`
command; ``--json`` prints the envelope (`mc.guide.v1`, `mc.describe.v1`). A refusal prints its
JSON and exits like any other command.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Protocol

import httpx

from mission_control.interfaces.cli.exits import exit_status

# The vocabulary a guide page's calls are written in for this client.
SURFACE = "cli"


class GuideClient(Protocol):
    def guide(self, topic: str | None, *, surface: str) -> httpx.Response: ...

    def describe(self, ref: str) -> httpx.Response: ...

    def whoami(self) -> httpx.Response: ...


def add_guide_parsers(groups: Any, common: argparse.ArgumentParser) -> None:
    groups.add_parser(
        "whoami",
        parents=[common],
        help="who this token is: actor, tenant, permissions, sponsorship refs, reviewer roles",
    )
    guide = groups.add_parser(
        "guide", parents=[common], help="how to use this server: the start page or one topic"
    )
    guide.add_argument("topic", nargs="?", help="omit for the start page, which lists the topics")
    describe = groups.add_parser(
        "describe", parents=[common], help="everything about one lane, model, tool or capability"
    )
    describe.add_argument(
        "ref",
        help="lane:PROFILE, model:PROFILE, feature:ID, tool:NAME, template:ID, manifest, "
        "manifest:SECTION or a search hit's ref",
    )


def describe_markdown(document: dict[str, Any]) -> str:
    """A describe envelope as Markdown: the answer's own Markdown where it is prose (a tool, a
    template, the manifest reference), else its title and its data as one JSON block."""

    markdown = document.get("markdown")
    if isinstance(markdown, str):
        return markdown
    data = dict(document.get("data") or {})
    lines = [f"# {document.get('title') or document.get('ref', '')}", ""]
    lines += ["```json", json.dumps(data, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


def _emit(text: str) -> None:
    """Markdown may carry non-ASCII text; never depend on the console code page."""

    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write((text + "\n").encode("utf-8"))
        buffer.flush()
    else:
        print(text)


def run_guide(client: GuideClient, args: argparse.Namespace) -> int:
    if args.group == "guide":
        response = client.guide(getattr(args, "topic", None), surface=SURFACE)
    elif args.group == "whoami":
        response = client.whoami()
    else:
        response = client.describe(args.ref)
    try:
        document: Any = response.json()
    except ValueError:
        document = {"error": "non-JSON service response", "status": response.status_code}
    status = exit_status(response.status_code)
    if (
        status != 0
        or args.group == "whoami"
        or getattr(args, "json", False)
        or not isinstance(document, dict)
    ):
        # `whoami` is data (`mc.whoami.v1`): one JSON document, like every other read.
        print(json.dumps(document, allow_nan=False))
    elif args.group == "guide":
        _emit(str(document.get("markdown", "")))
    else:
        _emit(describe_markdown(document))
    return status


__all__ = ["GuideClient", "add_guide_parsers", "describe_markdown", "run_guide"]

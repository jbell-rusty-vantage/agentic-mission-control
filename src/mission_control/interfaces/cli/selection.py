"""`missionctl search` and `missionctl workspace check`: the Selection Workspace.

``search QUERY [--facet capability|lane|model|sandbox_profile|workflow_type]... [--lane PROFILE]
[--limit N]`` prints one ranked, faceted answer (`mc.selection_search.v1`): each hit's stable
ref (a Capability Pin, `lane:<profile>` or `model:<profile>`) and why it matched.
``workspace check DRAFT`` reads a draft selection (JSON, or YAML for ``.yaml``/``.yml``) and
prints the decision (`mc.selection_check.v1`). Both post to the same routes the coordinator MCP
tools ``mission_search`` and ``selection_check`` call through. A refused draft exits 6 (a
blocked result) so a script can branch on it; nothing is launched either way.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

from mission_control.contracts.json import parse_json_object
from mission_control.interfaces.cli.exits import exit_status

# `application/selection/workspace.FACETS`, repeated so the thin client imports no handler; the
# route validates the body either way.
FACETS = ("capability", "lane", "model", "sandbox_profile", "workflow_type")
# A blocked result (exits.py): the draft was checked and refused.
BLOCKED = 6


class SelectionClient(Protocol):
    def selection(self, action: str, body: dict[str, Any]) -> httpx.Response: ...


def add_selection_parsers(groups: Any, common: argparse.ArgumentParser) -> None:
    search = groups.add_parser(
        "search", parents=[common], help="search capabilities, lanes, models and types"
    )
    search.add_argument("query")
    search.add_argument("--facet", action="append", dest="facets", choices=FACETS)
    search.add_argument("--lane", dest="lane_profile")
    search.add_argument("--limit", type=int)
    workspace = groups.add_parser(
        "workspace", parents=[common], help="check a draft lane/model/capability selection"
    )
    actions = workspace.add_subparsers(dest="action", required=True)
    check = actions.add_parser("check", parents=[common])
    check.add_argument("draft", help="a draft selection file (JSON, or YAML)")


def read_draft(path: str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() in {".yaml", ".yml"}:
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            raise ValueError("a draft selection is a mapping")
        return loaded
    return parse_json_object(text)


def search_body(args: argparse.Namespace) -> dict[str, Any]:
    body: dict[str, Any] = {"query": args.query}
    if getattr(args, "facets", None):
        body["facets"] = sorted(set(args.facets))
    if getattr(args, "lane_profile", None):
        body["lane_profile"] = args.lane_profile
    if getattr(args, "limit", None) is not None:
        body["limit"] = args.limit
    return body


def run_selection(client: SelectionClient, args: argparse.Namespace) -> int:
    if args.group == "search":
        response = client.selection("search", search_body(args))
    else:
        response = client.selection("check", read_draft(args.draft))
    try:
        document: Any = response.json()
    except ValueError:
        document = {"error": "non-JSON service response", "status": response.status_code}
    print(json.dumps(document, allow_nan=False, ensure_ascii=False))
    status = exit_status(response.status_code)
    if status == 0 and args.group == "workspace" and not document.get("admissible", False):
        return BLOCKED
    return status


__all__ = [
    "SelectionClient",
    "add_selection_parsers",
    "read_draft",
    "run_selection",
    "search_body",
]

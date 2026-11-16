"""Consumer-surface evaluation: can an agent answer the owner's questions from a running server?

Runs against a live Mission Control API (the deployed shape: REST plus the operator MCP mount at
``/v1/applications/<app>/mcp/``). It asks the questions a coordinator agent asks before it can
run a mission, through the two consumer paths:

- ``mcp``: an agent with no compute environment, which has the MCP server and nothing else;
- ``http``: a sandboxed agent, whose ``missionctl`` is a thin client over these same routes.

Every check is deterministic (no model call, nothing paid, read-only). The result is a scorecard,
not a gate: it records what the surface answers today so a change can be measured.

Usage:
  uv run --no-sync python scripts/consumer_surface_eval.py \\
    --url http://127.0.0.1:8010 --application ai-engineer --token-file <operator token file> \\
    [--out <dir>]

The token is read from its file and never printed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

GUIDE_WORDS = re.compile(r"guide|help|start_here|bootstrap|how_to", re.IGNORECASE)
INTERVIEW_WORDS = re.compile(r"interview|brief|authoring_session|elicit", re.IGNORECASE)


@dataclass
class Check:
    question: str
    path: str
    passed: bool
    observed: str
    wanted: str


@dataclass
class Scorecard:
    url: str
    application: str
    checks: list[Check] = field(default_factory=list)

    def add(self, question: str, path: str, passed: bool, observed: str, wanted: str) -> None:
        self.checks.append(Check(question, path, passed, observed, wanted))


class Surface:
    def __init__(self, url: str, application: str, token: str) -> None:
        self.base = f"{url.rstrip('/')}/v1/applications/{application}"
        self.http = httpx.Client(
            timeout=60.0, headers={"Authorization": f"Bearer {token}"}, follow_redirects=True
        )

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.http.post(
            f"{self.base}/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        return dict(response.json())

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments}).get("result", {})
        structured = result.get("structuredContent")
        if structured is None:
            text = "".join(part.get("text", "") for part in result.get("content", []))
            try:
                structured = json.loads(text)
            except ValueError:
                return {"error": text[:200]}
        return dict(structured.get("data", structured))

    def get(self, path: str) -> tuple[int, Any]:
        response = self.http.get(f"{self.base}/{path}")
        return response.status_code, _json(response)

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        response = self.http.post(f"{self.base}/{path}", json=body)
        return response.status_code, _json(response)


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:200]}


def _untyped(tool: dict[str, Any]) -> bool:
    properties = (tool.get("inputSchema") or {}).get("properties") or {}
    return any(
        spec.get("type") == "object" and not spec.get("properties") for spec in properties.values()
    )


def _hits(surface: Surface, query: str, facets: list[str]) -> tuple[int, list[str]]:
    data = surface.tool("mission_search", {"query": query, "facets": facets, "limit": 20})
    hits = data.get("hits") or []
    return len(hits), [str(item) for item in data.get("unavailable") or []]


def evaluate(surface: Surface, card: Scorecard) -> None:
    tools = surface.rpc("tools/list").get("result", {}).get("tools", [])
    names = [tool["name"] for tool in tools]
    undescribed = [tool["name"] for tool in tools if not (tool.get("description") or "").strip()]
    untyped = [tool["name"] for tool in tools if _untyped(tool)]
    tokens = sum(len(json.dumps(tool)) for tool in tools) // 4
    prompts = surface.rpc("prompts/list").get("result", {}).get("prompts", [])
    resources = surface.rpc("resources/list").get("result", {}).get("resources", [])

    card.add(
        "Is every tool self-explanatory?",
        "mcp",
        not undescribed and not untyped,
        f"{len(tools)} tools (~{tokens} tokens); {len(undescribed)} with no description; "
        f"{len(untyped)} with an untyped object argument",
        "0 undescribed, 0 untyped",
    )
    guides = [name for name in names if GUIDE_WORDS.search(name)]
    card.add(
        "Where do I start?",
        "mcp",
        bool(guides or prompts or resources),
        f"guide tools: {guides or 'none'}; prompts: {len(prompts)}; resources: {len(resources)}",
        "one start-here guide reachable without a filesystem",
    )
    described = [
        tool["name"]
        for tool in tools
        if INTERVIEW_WORDS.search(tool["name"] + " " + (tool.get("description") or ""))
    ]
    interview = described + [p["name"] for p in prompts if INTERVIEW_WORDS.search(p["name"])]
    card.add(
        "How do I interview the user before a mission?",
        "mcp",
        bool(interview),
        f"interview tools or prompts: {interview or 'none'}",
        "an interview guide and a way to record its answers as a brief",
    )

    count, unavailable = _hits(surface, "workflow", ["workflow_type"])
    card.add(
        "How do I look up all workflow types?",
        "mcp",
        count > 0,
        f"mission_search facet workflow_type: {count} hits; unavailable: {unavailable or 'none'}",
        "every published workflow type, findable",
    )
    lane_count, _ = _hits(surface, "agents", ["lane"])
    lane_tools = [name for name in names if name.startswith("lane_")]
    card.add(
        "How do I look up all provider cognition configurations?",
        "mcp",
        lane_count > 0 and bool(lane_tools),
        f"mission_search facet lane: {lane_count} hits; "
        f"lane describe tools: {lane_tools or 'none'}",
        "lanes listed and each lane's controls, delivery semantics and time travel readable",
    )
    for label, query in (
        ("agent skills", "skill"),
        ("MCP servers", "mcp server"),
        ("hooks", "hook"),
    ):
        count, unavailable = _hits(surface, query, ["capability"])
        card.add(
            f"Which {label} are available to me?",
            "mcp",
            count > 0,
            f"mission_search facet capability, query '{query}': {count} hits; "
            f"unavailable: {unavailable or 'none'}",
            "at least one hit, or an explicit 'unavailable' reason",
        )
    model_count, _ = _hits(surface, "model", ["model"])
    card.add(
        "Which model choices are available to me?",
        "mcp",
        model_count > 0,
        f"mission_search facet model: {model_count} hits",
        "every model profile",
    )
    control = {"mission_run_fork", "mission_command_send", "mission_run_state_as_of"}
    weak = sorted(control & (set(undescribed) | set(untyped)))
    card.add(
        "What are the rules for fork, time travel and intervention?",
        "mcp",
        not weak,
        f"undescribed or untyped control tools: {weak or 'none'}",
        "described, typed control tools and a rules answer per lane",
    )

    status, body = surface.get("catalog/definitions")
    capabilities = body.get("capabilities", []) if isinstance(body, dict) else []
    kinds: dict[str, int] = {}
    for item in capabilities:
        kinds[str(item.get("kind"))] = kinds.get(str(item.get("kind")), 0) + 1
    size = len(json.dumps(body))
    card.add(
        "What is in the catalog?",
        "http",
        status == 200 and bool(capabilities) and size < 60_000,
        f"GET catalog/definitions: {status}; {len(capabilities)} definitions; "
        f"{size // 1000} KB in one response; kinds: {dict(sorted(kinds.items()))}",
        "200, non-empty and small enough for an agent to read (a paged or summarized listing)",
    )
    status, body = surface.post("selection/search", {"query": "skill", "facets": ["capability"]})
    found = len(body.get("hits", [])) if isinstance(body, dict) else 0
    card.add(
        "Which agent skills are available to me?",
        "http",
        status == 200 and found > 0,
        f"POST selection/search: {status}; {found} hits",
        "at least one hit",
    )
    status, body = surface.get("lanes/deep_agents")
    keys = sorted(body.keys()) if isinstance(body, dict) else []
    wanted_keys = {"controls", "delivery_semantics", "time_travel"}
    card.add(
        "What are the rules for fork, time travel and intervention?",
        "http",
        status == 200 and wanted_keys <= set(keys),
        f"GET lanes/deep_agents: {status}; has controls/delivery_semantics/time_travel: "
        f"{wanted_keys <= set(keys)}",
        "the lane describe with its control matrix",
    )
    status, body = surface.get("models")
    models = body.get("models", body) if isinstance(body, dict) else body
    card.add(
        "Which model choices are available to me?",
        "http",
        status == 200 and bool(models),
        f"GET models: {status}; {len(models) if isinstance(models, list) else 0} profiles",
        "every model profile",
    )


def render(card: Scorecard) -> str:
    passed = sum(1 for check in card.checks if check.passed)
    lines = [
        f"Consumer surface: {passed} of {len(card.checks)} checks pass "
        f"({card.application} at {card.url})",
        "",
        "| Result | Path | Question | Observed |",
        "| --- | --- | --- | --- |",
    ]
    for check in card.checks:
        mark = "pass" if check.passed else "FAIL"
        lines.append(f"| {mark} | {check.path} | {check.question} | {check.observed} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--application", default="ai-engineer")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    token = args.token_file.read_text(encoding="utf-8").strip()
    card = Scorecard(url=args.url, application=args.application)
    evaluate(Surface(args.url, args.application, token), card)
    report = render(card)
    print(report)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "scorecard.md").write_text(report + "\n", encoding="utf-8", newline="\n")
        (args.out / "scorecard.json").write_text(
            json.dumps(asdict(card), indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

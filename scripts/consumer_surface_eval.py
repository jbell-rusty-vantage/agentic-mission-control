"""Consumer-surface evaluation: can an agent answer the owner's questions from a running server?

Runs against a live Mission Control API (the deployed shape: REST plus the operator MCP mount at
``/v1/applications/<app>/mcp/``). It asks the questions a coordinator agent asks before it can
run a mission, through the two consumer paths:

- ``mcp``: an agent with no compute environment, which has the MCP server and nothing else;
- ``http``: a sandboxed agent, whose ``missionctl`` is a thin client over these same routes.

The answers come from the guide (``mission_guide``, ``mission_describe``; ``GET guide``,
``GET describe``) and from the Selection Workspace's listing (``mission_search`` without a
query). Every check is deterministic (no model call, nothing paid, read-only). The result is a
scorecard, not a gate: it records what the surface answers today so a change can be measured.
Sizes are token estimates: characters of the JSON divided by four.

Usage:
  uv run --no-sync python scripts/consumer_surface_eval.py \\
    --url http://127.0.0.1:8010 --application ai-engineer --token-file <operator token file> \\
    [--out <dir>]

The token is read from its file and never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

# The jobs the start page must name, as the topics that explain them (select is two topics).
START_TOPICS = ("interview", "lanes", "capabilities", "launch", "observe", "control")
GUIDE_TOPICS = (
    "interview",
    "workflows",
    "lanes",
    "models",
    "capabilities",
    "launch",
    "observe",
    "control",
)
# What the interview page must map the brief to (Mission Manifest fields).
MANIFEST_FIELDS = (
    "goals[].description",
    "goals[].criteria[]",
    "environment.budget",
    "environment.side_effects",
    "environment.lane",
    "environment.model.profile",
)
CONTROL_MATRIX = ("controls", "delivery_semantics", "time_travel")
CONTROL_TOOLS = ("mission_command_send", "mission_run_fork", "mission_run_state_as_of")
# `tools/list` is read on every session: the owner's ceiling, in tokens.
TOOL_LISTING_TOKENS = 9_000
# A page or a listing an agent reads in one call.
SMALL_RESPONSE_TOKENS = 4_000


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
    """The server as a consumer reaches it; ``client`` replaces the network in a test."""

    def __init__(
        self, url: str, application: str, token: str, *, client: httpx.Client | None = None
    ) -> None:
        self.base = f"{url.rstrip('/')}/v1/applications/{application}"
        self.http = client or httpx.Client(timeout=60.0, follow_redirects=True)
        self.headers = {"Authorization": f"Bearer {token}"}

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.http.post(
            f"{self.base}/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            headers={**self.headers, "Accept": "application/json, text/event-stream"},
        )
        return dict(_json(response))

    def listing(self, method: str, key: str) -> list[dict[str, Any]]:
        return list(self.rpc(method).get("result", {}).get(key, []))

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """A tool's data, or ``{"error": ...}`` when it refused or is not on the server."""

        answer = self.rpc("tools/call", {"name": name, "arguments": arguments})
        result = answer.get("result") or {}
        structured = result.get("structuredContent")
        if structured is None:
            text = "".join(part.get("text", "") for part in result.get("content", []))
            try:
                structured = json.loads(text)
            except ValueError:
                return {"error": (text or json.dumps(answer.get("error", "no result")))[:200]}
        if result.get("isError") or structured.get("ok") is False:
            return {"error": json.dumps(structured.get("error", structured))[:300]}
        return dict(structured.get("data", structured))

    def get(self, path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
        response = self.http.get(f"{self.base}/{path}", params=params, headers=self.headers)
        return response.status_code, _json(response)

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        response = self.http.post(f"{self.base}/{path}", json=body, headers=self.headers)
        return response.status_code, _json(response)


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:200]}


def _tokens(value: Any) -> int:
    return len(value if isinstance(value, str) else json.dumps(value)) // 4


def _untyped(tool: dict[str, Any]) -> list[str]:
    """The tool's arguments published as a bare object (no properties, nothing closed)."""

    found = []
    for name, spec in ((tool.get("inputSchema") or {}).get("properties") or {}).items():
        for variant in (spec, *spec.get("anyOf", [])):
            if (
                variant.get("type") == "object"
                and not variant.get("properties")
                and "$ref" not in variant
                and variant.get("additionalProperties", True) is True
            ):
                found.append(name)
                break
    return found


def _markdown(page: dict[str, Any]) -> str:
    return str(page.get("markdown", ""))


def _listed(surface: Surface, arguments: dict[str, Any]) -> tuple[int, str]:
    """A listing call's hit count and what to report about it."""

    data = surface.tool("mission_search", arguments)
    if "error" in data:
        return 0, f"mission_search {json.dumps(arguments)}: {data['error']}"
    hits = data.get("hits") or []
    return len(hits), (
        f"mission_search {json.dumps(arguments)}: {len(hits)} hits of {data.get('total')}; "
        f"~{_tokens(data)} tokens; catalog_search_mode {data.get('catalog_search_mode')}; "
        f"unavailable {[item.get('facet') for item in data.get('unavailable') or []] or 'none'}"
    )


def evaluate(surface: Surface, card: Scorecard) -> None:
    tools = surface.listing("tools/list", "tools")
    names = {tool["name"] for tool in tools}
    undescribed = [tool["name"] for tool in tools if not (tool.get("description") or "").strip()]
    listing_tokens = sum(len(json.dumps(tool)) for tool in tools) // 4
    prompts = surface.listing("prompts/list", "prompts")
    resources = surface.listing("resources/list", "resources")

    # An object argument is explained when the listing types it or `tool:<name>` returns it.
    unexplained = []
    for tool in tools:
        if not _untyped(tool):
            continue
        shape = surface.tool("mission_describe", {"ref": f"tool:{tool['name']}"}).get("data", {})
        if not (shape.get("notes") and (shape.get("schema") or shape.get("example"))):
            unexplained.append(f"{tool['name']}({', '.join(_untyped(tool))})")
    card.add(
        "Is every tool self-explanatory?",
        "mcp",
        bool(tools) and not undescribed and not unexplained,
        f"{len(tools)} tools (~{listing_tokens} tokens); {len(undescribed)} with no "
        f"description; object arguments neither typed nor described: {unexplained or 'none'}",
        "0 undescribed; every object argument typed in the schema or returned by "
        "mission_describe('tool:<name>')",
    )
    card.add(
        "Is the tool listing small enough to read every session?",
        "mcp",
        bool(tools) and listing_tokens <= TOOL_LISTING_TOKENS,
        f"tools/list: {len(tools)} tools, ~{listing_tokens} tokens",
        f"at most {TOOL_LISTING_TOKENS} tokens",
    )

    start = surface.tool("mission_guide", {})
    missing = [topic for topic in START_TOPICS if f"`{topic}`" not in _markdown(start)]
    card.add(
        "Where do I start?",
        "mcp",
        "error" not in start and not missing,
        start.get("error")
        or f"mission_guide(): ~{_tokens(_markdown(start))} tokens; jobs not named: "
        f"{missing or 'none'}; prompts: {len(prompts)}; resources: {len(resources)}",
        "a start page naming the interview, select, launch, observe and control jobs",
    )
    interview = surface.tool("mission_guide", {"topic": "interview"})
    text = _markdown(interview)
    unmapped = [name for name in MANIFEST_FIELDS if name not in text]
    card.add(
        "How do I interview the user before a mission?",
        "mcp",
        "error" not in interview and "brief" in text.lower() and not unmapped,
        interview.get("error")
        or f"mission_guide('interview'): ~{_tokens(text)} tokens; names a brief: "
        f"{'brief' in text.lower()}; manifest fields not mapped: {unmapped or 'none'}",
        "an interview page that names the brief and the manifest field each part becomes",
    )

    count, observed = _listed(surface, {"facets": ["workflow_type"], "limit": 50})
    card.add(
        "How do I look up all workflow types?",
        "mcp",
        count > 0,
        observed,
        "every published Workflow Type, listed without a query",
    )

    lanes = surface.tool("mission_search", {"facets": ["lane"], "limit": 100})
    profiles = [
        str(hit["ref"]).removeprefix("lane:")
        for hit in lanes.get("hits") or []
        if str(hit.get("ref", "")).startswith("lane:")
    ]
    status, lane_list = surface.get("lanes")
    registered = sorted(
        item["lane_profile"]
        for item in (lane_list.get("lanes", []) if isinstance(lane_list, dict) else [])
    )
    described = {
        profile: surface.tool("mission_describe", {"ref": f"lane:{profile}"}).get("data", {})
        for profile in profiles
    }
    incomplete = sorted(
        profile
        for profile, data in described.items()
        if not {"controls", "delivery_semantics"} <= set(data)
    )
    travel = sorted(profile for profile, data in described.items() if "time_travel" in data)
    card.add(
        "How do I look up all provider cognition configurations?",
        "mcp",
        bool(profiles)
        and status == 200
        and sorted(profiles) == registered
        and not incomplete
        and bool(travel),
        lanes.get("error")
        or f"mission_search facet lane: {sorted(profiles)}; GET lanes: {registered}; "
        f"mission_describe('lane:<each>') without controls or delivery_semantics: "
        f"{incomplete or 'none'}; declaring time_travel: {travel or 'none'}",
        "every registered lane listed, each lane's controls and delivery semantics readable "
        "and time travel readable where the lane declares it",
    )

    for label, kind in (
        ("agent skills", "skill"),
        ("MCP servers", "mcp_server"),
        ("hooks", "hook_script"),
    ):
        count, observed = _listed(surface, {"kinds": [kind], "limit": 100})
        card.add(
            f"Which {label} are available to me?",
            "mcp",
            count > 0,
            observed,
            f"every published {kind}, listed without a query",
        )
    count, observed = _listed(surface, {"facets": ["model"], "limit": 100})
    card.add(
        "Which model choices are available to me?",
        "mcp",
        count > 0,
        observed,
        "every Model Profile",
    )

    silent = []
    explained = []
    modes = {}
    for query in ("skill", "workflow", "mcp server", "hook"):
        data = surface.tool("mission_search", {"query": query, "limit": 20})
        catalog_hits = [hit for hit in data.get("hits") or [] if hit.get("kind")]
        modes[query] = data.get("catalog_search_mode")
        if data.get("notes") or data.get("unavailable"):
            explained.append(query)
        elif "error" in data or not catalog_hits:
            silent.append(query)
    card.add(
        "Is a search ever silently empty?",
        "mcp",
        not silent,
        f"queries with no catalog hit and no stated reason: {silent or 'none'}; queries "
        f"answered with a stated reason (notes or unavailable): {explained or 'none'}; "
        f"catalog_search_mode per query: {modes}",
        "a catalog hit, or the reason there is none (`unavailable` or `notes`)",
    )

    control = surface.tool("mission_guide", {"topic": "control"})
    weak = sorted(set(CONTROL_TOOLS) & set(undescribed)) + sorted(set(CONTROL_TOOLS) - names)
    unlisted = [profile for profile in profiles if f"`{profile}`" not in _markdown(control)]
    card.add(
        "What are the rules for fork, time travel and intervention?",
        "mcp",
        "error" not in control and bool(profiles) and not weak and not unlisted,
        control.get("error")
        or f"mission_guide('control'): ~{_tokens(_markdown(control))} tokens; lanes missing "
        f"from its table: {unlisted or 'none'}; control tools absent or undescribed: "
        f"{weak or 'none'}",
        "the rules, the control tools and one row per lane of what the lane does",
    )

    status, page = surface.get("guide/capabilities")
    text = _markdown(page) if isinstance(page, dict) else ""
    kinds = [line.split("|")[1].strip() for line in text.splitlines() if line.startswith("| `")]
    card.add(
        "What is in the catalog?",
        "http",
        status == 200 and bool(kinds) and _tokens(page) <= SMALL_RESPONSE_TOKENS,
        f"GET guide/capabilities: {status}; ~{_tokens(page)} tokens; kinds with counts: "
        f"{', '.join(kinds) or 'none'}",
        f"the catalog kinds with counts in at most {SMALL_RESPONSE_TOKENS} tokens",
    )
    status, body = surface.post("selection/search", {"kinds": ["skill"], "limit": 100})
    found = len(body.get("hits", [])) if isinstance(body, dict) else 0
    card.add(
        "Which agent skills are available to me?",
        "http",
        status == 200 and found > 0,
        f"POST selection/search kinds skill: {status}; {found} hits; ~{_tokens(body)} tokens",
        "every published skill, listed without a query",
    )
    differing = []
    for profile in registered:
        status, lane = surface.get(f"lanes/{profile}")
        _, wrapped = surface.get("describe", {"ref": f"lane:{profile}"})
        data = wrapped.get("data") if isinstance(wrapped, dict) else None
        if status != 200 or data != lane or data != described.get(profile):
            differing.append(profile)
    card.add(
        "What are the rules for fork, time travel and intervention?",
        "http",
        bool(registered) and not differing,
        f"GET describe?ref=lane:<each> against GET lanes/<each> and mission_describe: "
        f"{len(registered)} lanes; differing: {differing or 'none'}",
        "one lane document, with its control matrix, on every transport",
    )
    status, body = surface.get("models")
    models = body.get("models", body) if isinstance(body, dict) else body
    card.add(
        "Which model choices are available to me?",
        "http",
        status == 200 and bool(models),
        f"GET models: {status}; {len(models) if isinstance(models, list) else 0} profiles",
        "every Model Profile",
    )

    unequal = []
    for topic in (None, *GUIDE_TOPICS):
        status, page = surface.get(f"guide/{topic}" if topic else "guide", {"surface": "mcp"})
        tool_page = surface.tool("mission_guide", {"topic": topic} if topic else {})
        if status != 200 or "error" in tool_page or page != tool_page:
            unequal.append(topic or "index")
    card.add(
        "Does the guide say the same thing over HTTP and MCP?",
        "http",
        not unequal,
        f"GET guide[/topic]?surface=mcp against mission_guide: {len(GUIDE_TOPICS) + 1} pages; "
        f"differing: {unequal or 'none'}",
        "the same page on both transports",
    )
    unequal = []
    for ref in ("tool:mission_command_send", "tool:mission_run_fork", "lane:nowhere"):
        status, wrapped = surface.get("describe", {"ref": ref})
        from_tool = surface.tool("mission_describe", {"ref": ref})
        same = (
            wrapped == from_tool if status == 200 else status in {404, 422} and "error" in from_tool
        )
        if not same:
            unequal.append(ref)
    card.add(
        "Does describe say the same thing over HTTP and MCP?",
        "http",
        not unequal,
        f"GET describe against mission_describe for two tool requests and an unknown lane; "
        f"differing: {unequal or 'none'}",
        "the same document, and a refusal on both for an unknown ref",
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
        observed = check.observed.replace("|", "\\|")
        lines.append(f"| {mark} | {check.path} | {check.question} | {observed} |")
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

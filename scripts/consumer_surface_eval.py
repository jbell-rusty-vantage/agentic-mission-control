"""Consumer-surface evaluation: can an agent answer the owner's questions from a running server?

Runs against a live Mission Control API (the deployed shape: REST plus the operator MCP mount at
``/v1/applications/<app>/mcp/``). It asks the questions a coordinator agent asks before it can
run a mission, through the two consumer paths:

- ``mcp``: an agent with no compute environment, which has the MCP server and nothing else;
- ``http``: a sandboxed agent, whose ``missionctl`` is a thin client over these same routes.

The answers come from the guide (``mission_guide``, ``mission_describe``; ``GET guide``,
``GET describe``) and from the Selection Workspace's listing (``mission_search`` without a
query). The launch section takes each mission template the way that agent would: it reads the
template through ``mission_describe``, fills its slots with fixed test values and compiles the
result with ``mission_manifest_compile``. It never submits and never starts.

Every check is deterministic (no model call, nothing paid, read-only). The result is a
scorecard, not a gate: it records what the surface answers today so a change can be measured.
Sizes are token estimates: characters divided by four.

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

# The jobs the start page must name, as the topics that explain them (select is two topics).
START_TOPICS = ("interview", "lanes", "capabilities", "launch", "observe", "control")
GUIDE_TOPICS = (
    "interview",
    "workflows",
    "templates",
    "manifest",
    "lanes",
    "models",
    "capabilities",
    "launch",
    "observe",
    "control",
)
# What the interview page must map the brief to (Mission Manifest fields), including what a
# first manifest needs and an earlier page left out.
MANIFEST_FIELDS = (
    "goals[].criteria[]",
    "environment.budget",
    "environment.governors",
    "environment.side_effects",
    "environment.lane",
    "environment.model.profile",
    "environment.sandbox.profile",
    "`key`",
    "`importance`",
    "`primary`",
    "`evidence`",
    "`acceptance`",
    "`objectives`",
    "`instruction`",
    "`action_space`",
    "`form`",
)
# What the manifest page must say: required fields of each shape, and which acceptance starts.
MANIFEST_TOPIC = (
    "`behavior: stage_graph`",
    "`behavior: goal_loop`",
    "`behavior: agent_executor`",
    "`behavior: human_gate`",
    "`instruction`",
    "`action_space`",
    "`human: review_accept`",
    "starts",
    "refused",
)
WORKFLOW_SYSTEMS = ("stage_graph", "goal_loop", "parallel_swarm", "evaluator_optimizer")
CONTROL_MATRIX = ("controls", "delivery_semantics", "time_travel")
CONTROL_TOOLS = ("mission_command_send", "mission_run_fork", "mission_run_state_as_of")
# A tool whose arguments the listing types in full: describe must answer for it too.
TYPED_TOOL = "mission_manifest_compile"
# `tools/list` is read on every session: the owner's ceiling, in tokens.
TOOL_LISTING_TOKENS = 9_000
# A page or a listing an agent reads in one call.
SMALL_RESPONSE_TOKENS = 4_000
# The fixed values a template's slots are filled with; `{id}` is the template id. A slot that
# is not named here takes the example the template itself gives.
SLOT_VALUES = {
    "mission_key": "surface-eval-{id}",
    "title": "Consumer surface evaluation of the {id} template",
    "goal": "Write three sentences that explain what a Mission Manifest is.",
    "criterion": "The text is three sentences and names compile, submit and start.",
    "budget_usd": "0.5",
    "reviewer": "owner",
    "repository_url": "https://example.invalid/surface-eval/repository.git",
    "repository_ref": "main",
}
_SLOT = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_YAML_BLOCK = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)


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
        self.application = application
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

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """A tool call as an agent receives it: the text content it reads, and the tool's data
        (or ``{"error": ...}`` when it refused or is not on the server)."""

        answer = self.rpc("tools/call", {"name": name, "arguments": arguments})
        result = answer.get("result") or {}
        text = "".join(part.get("text", "") for part in result.get("content", []))
        structured = result.get("structuredContent")
        if structured is None:
            try:
                structured = json.loads(text)
            except ValueError:
                return text, {"error": (text or json.dumps(answer.get("error", "no result")))[:200]}
        if result.get("isError") or structured.get("ok") is False:
            return text, {"error": json.dumps(structured.get("error", structured))[:300]}
        return text, dict(structured.get("data", structured))

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.call(name, arguments)[1]

    def describe(self, ref: str) -> tuple[str, dict[str, Any]]:
        """`mission_describe(ref)`: the text an agent reads, and the answer's own `data`
        (with ``error`` when it refused)."""

        text, document = self.call("mission_describe", {"ref": ref})
        data = dict(document.get("data") or {})
        return text, data | ({"error": document["error"]} if "error" in document else {})

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


def _is_markdown(text: str) -> bool:
    """A page as written: it opens with its title and is not JSON."""

    if not text.startswith("# "):
        return False
    try:
        json.loads(text)
    except ValueError:
        return True
    return False


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


def _refs(surface: Surface, facet: str, prefix: str, **extra: Any) -> list[str]:
    """The names a facet lists under one ref prefix (`template:`, `sandbox:`, `model:`)."""

    data = surface.tool("mission_search", {"facets": [facet], "limit": 100, **extra})
    return [
        str(hit["ref"]).removeprefix(prefix)
        for hit in data.get("hits") or []
        if str(hit.get("ref", "")).startswith(prefix)
    ]


def _fill(manifest: str, template_id: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """The manifest with its slots replaced, and the slots no value was found for."""

    missing = sorted({name for name in _SLOT.findall(manifest) if name not in values})
    filled = _SLOT.sub(
        lambda match: values.get(match.group(1), match.group(0)).replace("{id}", template_id),
        manifest,
    )
    return filled, missing


def evaluate(surface: Surface, card: Scorecard) -> None:
    tools = surface.listing("tools/list", "tools")
    names = {tool["name"] for tool in tools}
    undescribed = [tool["name"] for tool in tools if not (tool.get("description") or "").strip()]
    listing_tokens = sum(len(json.dumps(tool)) for tool in tools) // 4
    prompts = surface.listing("prompts/list", "prompts")
    resources = surface.listing("resources/list", "resources")

    # Describe answers for every tool: its description and the arguments the listing
    # publishes. An object argument the listing does not type also needs notes and its shape.
    unanswered = []
    unexplained = []
    for tool in tools:
        text, shape = surface.describe(f"tool:{tool['name']}")
        listed = set((tool.get("inputSchema") or {}).get("properties") or {})
        if (
            "error" in shape
            or not shape.get("description")
            or set((shape.get("input_schema") or {}).get("properties") or {}) != listed
            or not _is_markdown(text)
        ):
            unanswered.append(tool["name"])
        if _untyped(tool) and not (
            shape.get("notes") and (shape.get("schema") or shape.get("example"))
        ):
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
        "Does describe answer for every tool?",
        "mcp",
        bool(tools) and not unanswered and TYPED_TOOL in names,
        f"mission_describe('tool:<each>') for {len(tools)} tools, {TYPED_TOOL} among them: "
        f"without a Markdown answer, a description or the listed arguments: "
        f"{unanswered or 'none'}",
        "every tool's description and argument schema, as Markdown",
    )
    card.add(
        "Is the tool listing small enough to read every session?",
        "mcp",
        bool(tools) and listing_tokens <= TOOL_LISTING_TOKENS,
        f"tools/list: {len(tools)} tools, ~{listing_tokens} tokens",
        f"at most {TOOL_LISTING_TOKENS} tokens",
    )

    start_text, start = surface.call("mission_guide", {})
    missing = [topic for topic in START_TOPICS if f"`{topic}`" not in start_text]
    card.add(
        "Where do I start?",
        "mcp",
        "error" not in start and not missing,
        start.get("error")
        or f"mission_guide(): ~{_tokens(start_text)} tokens; jobs not named: "
        f"{missing or 'none'}; prompts: {len(prompts)}; resources: {len(resources)}",
        "a start page naming the interview, select, launch, observe and control jobs",
    )
    pages = {topic: surface.call("mission_guide", {"topic": topic}) for topic in GUIDE_TOPICS}
    escaped = [topic for topic, (text, _data) in pages.items() if not _is_markdown(text)]
    if not _is_markdown(start_text):
        escaped.insert(0, "index")
    sizes = ", ".join(f"{topic} ~{_tokens(text)}" for topic, (text, _data) in pages.items())
    card.add(
        "Does a page arrive as Markdown?",
        "mcp",
        not escaped,
        f"mission_guide text content of {len(pages) + 1} pages; not Markdown: "
        f"{escaped or 'none'}; tokens: index ~{_tokens(start_text)}, {sizes}",
        "every page's text content is the Markdown itself, not JSON",
    )
    text, interview = pages["interview"]
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

    # Workflow systems, templates, and the published Workflow Types apart from the lowered.
    workflows = pages["workflows"][0]
    templates = _refs(surface, "template", "template:")
    systems = [name for name in WORKFLOW_SYSTEMS if f"`{name}`" not in workflows]
    unnamed = [name for name in templates if f"`{name}`" not in workflows]
    curated = surface.tool("mission_search", {"facets": ["workflow_type"], "limit": 100})
    every = surface.tool(
        "mission_search", {"facets": ["workflow_type"], "limit": 100, "include_lowered": True}
    )
    kept, hidden = curated.get("total"), curated.get("lowered_hidden", 0)
    counted = re.search(
        r"not lowered from a manifest: (\d+)\. Lowered from submitted manifests and left out "
        r"of listings: (\d+)\.",
        workflows,
    )
    separated = (
        "error" not in curated
        and "error" not in every
        and isinstance(kept, int)
        and every.get("total") == kept + hidden
        and counted is not None
        and (int(counted.group(1)), int(counted.group(2))) == (kept, hidden)
    )
    card.add(
        "How do I look up all workflow types?",
        "mcp",
        not systems and bool(templates) and not unnamed and separated,
        curated.get("error")
        or f"mission_guide('workflows'): workflow systems not named: {systems or 'none'}; "
        f"templates listed by mission_search: {templates or 'none'}, not named in the page: "
        f"{unnamed or 'none'}; mission_search facet workflow_type: {kept} not lowered, "
        f"{hidden} lowered and left out, {every.get('total')} with include_lowered; the page "
        f"states {counted.groups() if counted else 'no counts'}",
        "the workflow systems, the templates to start from, and the published Workflow Types "
        "counted apart from the per-manifest lowered ones",
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

    text, control = pages["control"]
    weak = sorted(set(CONTROL_TOOLS) & set(undescribed)) + sorted(set(CONTROL_TOOLS) - names)
    unlisted = [profile for profile in profiles if f"`{profile}`" not in text]
    card.add(
        "What are the rules for fork, time travel and intervention?",
        "mcp",
        "error" not in control and bool(profiles) and not weak and not unlisted,
        control.get("error")
        or f"mission_guide('control'): ~{_tokens(text)} tokens; lanes missing "
        f"from its table: {unlisted or 'none'}; control tools absent or undescribed: "
        f"{weak or 'none'}",
        "the rules, the control tools and one row per lane of what the lane does",
    )

    # The manifest, reachable without a filesystem.
    manifest_page = pages["manifest"][0]
    absent = [name for name in MANIFEST_TOPIC if name not in manifest_page]
    reference_text, reference = surface.describe("manifest")
    section_text, section = surface.describe("manifest:OutputDeclaration")
    card.add(
        "What does a Mission Manifest hold?",
        "mcp",
        not absent
        and "error" not in reference
        and _is_markdown(reference_text)
        and bool(reference.get("sections"))
        and "error" not in section
        and "`form`" in section_text,
        reference.get("error")
        or f"mission_guide('manifest'): ~{_tokens(manifest_page)} tokens; not said: "
        f"{absent or 'none'}; mission_describe('manifest'): ~{_tokens(reference_text)} tokens, "
        f"{len(reference.get('sections') or {})} sections and "
        f"{len(reference.get('more_sections') or [])} more by name; "
        f"mission_describe('manifest:OutputDeclaration'): ~{_tokens(section_text)} tokens",
        "the required fields per workflow system, which acceptance starts, and every field "
        "as Markdown",
    )
    sandboxes = _refs(surface, "sandbox_profile", "sandbox:")
    unnamed = [name for name in sandboxes if f"`{name}`" not in manifest_page]
    card.add(
        "Which sandbox profile do I name?",
        "mcp",
        bool(sandboxes) and not unnamed,
        f"mission_search facet sandbox_profile: bound profiles {sandboxes or 'none'}; not "
        f"named in mission_guide('manifest'): {unnamed or 'none'}",
        "the sandbox profiles this deployment binds, listed and named in the manifest page",
    )

    # Launch: each template as an agent takes it, compiled and never submitted.
    templates_page = pages["templates"][0]
    unnamed = [name for name in templates if f"`{name}`" not in templates_page]
    card.add(
        "Which mission templates can I start from?",
        "mcp",
        bool(templates) and not unnamed,
        f"mission_search facet template: {templates or 'none'}; not in "
        f"mission_guide('templates'): {unnamed or 'none'}",
        "every template listed by search and described on the templates page",
    )
    for template_id in templates:
        text, data = surface.describe(f"template:{template_id}")
        block = _YAML_BLOCK.search(text)
        manifest = block.group(1) if block else ""
        lane = re.search(r"^\s*lane:\s*(\S+)\s*$", manifest, re.MULTILINE)
        models = _refs(
            surface, "model", "model:", **({"lane_profile": lane.group(1)} if lane else {})
        )
        values = {slot["name"]: slot["example"] for slot in data.get("slots") or []}
        values |= SLOT_VALUES | {"application_id": surface.application}
        for name in values:
            if name.endswith("model_profile") and models:
                values[name] = models[0]
        if sandboxes:
            values["sandbox_profile"] = sandboxes[0]
        filled, missing = _fill(manifest, template_id, values)
        report = (
            surface.tool("mission_manifest_compile", {"manifest_yaml": filled})
            if manifest and not missing
            else {"error": f"no manifest in the answer, or slots without a value: {missing}"}
        )
        blockers = [
            f"{item.get('code')} {item.get('pointer')} ({item.get('reason')})"
            for item in (*report.get("blockers", ()), *report.get("start_blockers", ()))
        ]
        card.add(
            f"Does the `{template_id}` template compile?",
            "mcp",
            report.get("ok") is True and report.get("startable") is True,
            report.get("error")
            or f"mission_describe('template:{template_id}'): ~{_tokens(text)} tokens, "
            f"{len(set(_SLOT.findall(manifest)))} slots filled (model "
            f"{models[0] if models else 'the example'}, "
            f"sandbox {sandboxes[0] if sandboxes else 'the example'}); "
            f"mission_manifest_compile: ok {report.get('ok')}, startable "
            f"{report.get('startable')}, {len(report.get('warnings') or [])} warnings; "
            f"blockers: {blockers or 'none'}",
            "the filled template compiles (`ok`) and a start would accept it (`startable`)",
        )

    status, page = surface.get("guide/capabilities")
    text = str(page.get("markdown", "")) if isinstance(page, dict) else ""
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
        status, lane_document = surface.get(f"lanes/{profile}")
        _, wrapped = surface.get("describe", {"ref": f"lane:{profile}"})
        data = wrapped.get("data") if isinstance(wrapped, dict) else None
        if status != 200 or data != lane_document or data != described.get(profile):
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
    listed_models = body.get("models", body) if isinstance(body, dict) else body
    card.add(
        "Which model choices are available to me?",
        "http",
        status == 200 and bool(listed_models),
        f"GET models: {status}; "
        f"{len(listed_models) if isinstance(listed_models, list) else 0} profiles",
        "every Model Profile",
    )

    unequal = []
    for topic in (None, *GUIDE_TOPICS):
        status, page = surface.get(f"guide/{topic}" if topic else "guide", {"surface": "mcp"})
        text, tool_page = (start_text, start) if topic is None else pages[topic]
        if (
            status != 200
            or "error" in tool_page
            or page != tool_page
            or page.get("markdown") != text
        ):
            unequal.append(topic or "index")
    card.add(
        "Does the guide say the same thing over HTTP and MCP?",
        "http",
        not unequal,
        f"GET guide[/topic]?surface=mcp against mission_guide: {len(GUIDE_TOPICS) + 1} pages; "
        f"differing in the envelope or in the Markdown text: {unequal or 'none'}",
        "the same page on both transports, and its Markdown as the MCP text content",
    )
    unequal = []
    prose = [f"tool:{TYPED_TOOL}", "tool:mission_command_send", "manifest"]
    prose += [f"template:{name}" for name in templates[:1]]
    for ref in (*prose, "lane:nowhere"):
        status, wrapped = surface.get("describe", {"ref": ref})
        text, from_tool = surface.call("mission_describe", {"ref": ref})
        if status == 200:
            same = wrapped == from_tool and wrapped.get("markdown") == text
        else:
            same = status in {404, 422} and "error" in from_tool
        if not same:
            unequal.append(ref)
    card.add(
        "Does describe say the same thing over HTTP and MCP?",
        "http",
        not unequal,
        f"GET describe against mission_describe for {len(prose)} prose answers and an unknown "
        f"lane; differing: {unequal or 'none'}",
        "the same document, its Markdown as the MCP text content, and a refusal on both for "
        "an unknown ref",
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

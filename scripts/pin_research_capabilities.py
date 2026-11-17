"""Write the deployment's capability pin file from the reviewed workspace artifacts (RRM-009).

The only writer of `infra/capability-pins/research-capabilities.json`. It reads the reviewed
MCP modules (`.tools/...`), lists their tools through the same `MultiServerMCPClient` path
the materializer uses (so the pinned input-schema digests are exactly what a binding is
verified against), reads the agent-browser Skill bundle from `.agents/skills/agent-browser`,
hashes the pinned agent-browser entrypoint, and records the exact model, sandbox,
checkpointer and store definitions the deployment serves. Credentials are passed to the
MCP subprocesses from the environment and appear in the output only as reference names.

    uv run --no-sync --env-file ../biotech-research-ingestion-evaluation-system/.env \\
      python scripts/pin_research_capabilities.py --node "C:/Program Files/nodejs/node.exe" \\
      --component model:model.wp-cp-040:1:<digest> \\
      --component sandbox.state:sandbox.wp-cp-040:1:<digest> \\
      --component checkpointer:checkpointer.wp-cp-040:1:<digest> \\
      --component store:store.wp-cp-040:1:<digest>

Supabase bundle custody (W1 defect D4). A worker with `CAPABILITY_BUNDLE_BACKEND=supabase`
admits only `bytes_v1` Skill pins whose locator is `capability-bundles://<manifest digest>`
(`adapters/postgres/capability_bundles.py`), so a workspace pin is refused at start.
`--skill-custody <directory>` writes that form instead of the workspace pin: the manifest is the
`mission-control.skill-bundle.v1` document `register_supabase_skill_bundle.py` (Supabase) and
`DirectoryBundleStore.publish` (local custody) stage for the same bytes, asset id and version, so
the pinned digest is the one they register. `--upgrade-skill-custody` rewrites only the
agent-browser Skill pin of an existing `--output` file (no MCP subprocess, no `--node`); every
other pin keeps its bytes. The reviewed custody source is the catalog seed's
`tests/fixtures/skills/agent-browser` (vercel-labs/agent-browser v0.38.2):

    uv run --no-sync python scripts/pin_research_capabilities.py --upgrade-skill-custody \\
      --skill-custody tests/fixtures/skills/agent-browser

Research capabilities (IP-013). Three further rows are written from the catalog seed rows
(`packages/mission-control-db-contract/seeds/agent_capabilities.py`), each in the pin form its
server needs, and each only from what is on this host: nothing is downloaded, and a row whose
artifact is absent or differs from the catalog is reported under `not_pinned` with the reason.

- `mcp.context7`: the node module `.tools/node_modules/@upstash/context7-mcp` at the catalog's
  version (`mcp_servers`).
- `mcp.github`: the release binary named by `--github-mcp-server <absolute path>`, which must
  report the catalog's version and commit and list exactly the catalog's tools with the
  catalog's read-only arguments (`executable_mcp_servers`).
- `mcp.knowledge-capture`: the executor at `--knowledge-capture-endpoint` (default: this
  deployment's `MCP_SERVER_ENDPOINTS["mcp.knowledge-capture"]`), pinned to the catalog's
  allowlist with the `allowlist` tool filter (`remote_mcp_servers`). The pin states no URL.
  `--knowledge-capture-credential-env none` pins an executor that runs without a token.

`--add-research` adds or replaces only those rows of an existing `--output` file; every other
pin keeps its bytes:

    uv run --no-sync python scripts/pin_research_capabilities.py --add-research \\
      --node "C:/Program Files/nodejs/node.exe" \\
      --github-mcp-server "C:/tools/github-mcp-server/github-mcp-server.exe" \\
      --knowledge-capture-endpoint http://127.0.0.1:4310/mcp

Method skills (``--add-catalog-skills <application> --skill-custody-root <dir>``): a `bytes_v1`
custody Skill pin for each method skill the application's agent-skill seed imports, at the revision
the seed publishes, its recorded import bytes published into the custody root the worker reads
(`CAPABILITY_BUNDLE_LOCAL_ROOT`). Combinable with `--add-research`; other pins keep their bytes.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any, NamedTuple, cast

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from mission_control.adapters.capabilities.capability_bundles import (
    BundleManifest,
    bundle_digest,
    bytes_digest,
    directory_files,
    file_manifest,
)
from mission_control.adapters.capabilities.capability_pins import (
    AnyPinnedMCPServer,
    CapabilityPinError,
    CapabilityPins,
    PinnedExactRef,
    PinnedExecutableMCPServer,
    PinnedMCPServer,
    PinnedMCPTool,
    PinnedModel,
    PinnedPersistence,
    PinnedRemoteMCPServer,
    PinnedSandbox,
    PinnedSkill,
    PinnedTool,
    read_skill_bundle,
    remote_endpoint,
    workspace_path,
)
from mission_control.adapters.deep_agents.browser_tool import (
    AGENT_BROWSER_PAGE_TOOL_NAME,
    AgentBrowserPageTool,
)
from mission_control.adapters.deep_agents.materializer import tool_schema_digest
from mission_control.bootstrap.settings import PROJECT_ROOT, get_settings
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind

FIRECRAWL_MODULE = "workspace://.tools/reviewed/firecrawl-mcp-7232b6d1cdd80335107d53a33b80c902b515a334/dist/index.js"
TAVILY_MODULE = "workspace://.tools/node_modules/tavily-mcp/build/index.js"
AGENT_BROWSER_ENTRYPOINT = "workspace://.tools/node_modules/agent-browser/bin/agent-browser.js"
AGENT_BROWSER_SKILL = "workspace://.agents/skills/agent-browser"
AGENT_BROWSER_SKILL_ID = "skill.agent-browser"
AGENT_BROWSER_SKILL_NAME = "agent-browser"
AGENT_BROWSER_SKILL_VERSION = 1
CUSTODY_SCHEME = "capability-bundles://"
DEFAULT_OUTPUT = PROJECT_ROOT / "infra" / "capability-pins" / "research-capabilities.json"
# The catalog seeds and their bundle sources are this checkout's, wherever MISSION_CONTROL_HOME
# (and with it PROJECT_ROOT) points for the deployment being pinned.
REPOSITORY = Path(__file__).resolve().parents[1]
CATALOG_SEEDS = REPOSITORY / "packages" / "mission-control-db-contract" / "seeds"
CONTEXT7_ID = "mcp.context7"
CONTEXT7_MODULE = "workspace://.tools/node_modules/@upstash/context7-mcp/dist/index.js"
GITHUB_ID = "mcp.github"
KNOWLEDGE_CAPTURE_ID = "mcp.knowledge-capture"
RESEARCH_IDS = (CONTEXT7_ID, GITHUB_ID, KNOWLEDGE_CAPTURE_ID)
# The pin-file list each research row belongs to (its form, IP-008).
RESEARCH_SECTIONS = {
    CONTEXT7_ID: "mcp_servers",
    GITHUB_ID: "executable_mcp_servers",
    KNOWLEDGE_CAPTURE_ID: "remote_mcp_servers",
}
ToolLister = Callable[[Mapping[str, Any]], Awaitable[Sequence[BaseTool]]]
VersionReader = Callable[[Path], str]


class NotPinned(NamedTuple):
    """A research row the writer did not write, and the fact that prevented it."""

    server_id: str
    reason: str


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--node", type=Path, help="required unless --upgrade-skill-custody")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--component",
        action="append",
        default=[],
        help="kind:logical_id:revision:digest; kind is model, sandbox.<backend>, "
        "checkpointer or store",
    )
    parser.add_argument("--skip-mcp", action="store_true")
    parser.add_argument(
        "--skill-custody",
        type=Path,
        help="pin the agent-browser Skill from this directory in bytes_v1 custody form",
    )
    parser.add_argument(
        "--upgrade-skill-custody",
        action="store_true",
        help="rewrite only the agent-browser Skill pin of --output (needs --skill-custody)",
    )
    parser.add_argument(
        "--add-research",
        action="store_true",
        help="add or replace only the research rows (Context7, GitHub, knowledge capture) of "
        "--output; every other pin keeps its bytes",
    )
    parser.add_argument(
        "--github-mcp-server",
        type=Path,
        help="absolute path of the reviewed github-mcp-server release binary on this host",
    )
    parser.add_argument(
        "--knowledge-capture-endpoint",
        help="the executor's MCP endpoint to list tools from (default: this deployment's "
        f'MCP_SERVER_ENDPOINTS["{KNOWLEDGE_CAPTURE_ID}"])',
    )
    parser.add_argument(
        "--knowledge-capture-credential-env",
        help="environment name of the executor's token (default: the catalog row's secret "
        "reference); `none` for an executor that runs without one",
    )
    parser.add_argument(
        "--context7-credential-env",
        help="environment name of the Context7 key; omitted: the server is pinned keyless",
    )
    parser.add_argument(
        "--add-catalog-skills",
        metavar="APPLICATION",
        choices=("ai-engineer", "biotech"),
        help="add or replace the Skill pins of the method skills the application's agent-skill "
        "seed imports (current revision of each), published into --skill-custody-root; every "
        "other pin keeps its bytes",
    )
    parser.add_argument(
        "--skill-custody-root",
        type=Path,
        help="the local bundle custody root the worker reads (CAPABILITY_BUNDLE_LOCAL_ROOT)",
    )
    args = parser.parse_args()
    if args.upgrade_skill_custody and args.skill_custody is None:
        parser.error("--upgrade-skill-custody needs --skill-custody <directory>")
    if args.add_catalog_skills and args.skill_custody_root is None:
        parser.error("--add-catalog-skills needs --skill-custody-root <directory>")
    adding = args.add_research or args.add_catalog_skills
    if not (args.upgrade_skill_custody or adding) and args.node is None:
        parser.error("--node is required")
    return args


def catalog_rows() -> dict[str, Any]:
    """`capability_id -> MCPServerDefinition` of each research server at its newest seeded
    revision: the identity, version, launch template, secret references and tool allowlist
    every research row is written from."""

    spec = importlib.util.spec_from_file_location(
        "mc_pin_agent_capabilities", CATALOG_SEEDS / "agent_capabilities.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        server_id: module.server_definition(row)
        for server_id, row in module.served_research_specs().items()
    }


async def list_tools(connection: Mapping[str, Any]) -> Sequence[BaseTool]:
    """One server's tools through the client path the materializer uses."""

    client = MultiServerMCPClient(cast(Any, {"pinned": dict(connection)}))
    return await client.get_tools()


def _launch_environment(credential_envs: Sequence[str], *, required: bool) -> dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "PATHEXT", "SYSTEMROOT", "COMSPEC", "WINDIR")
        if key in os.environ
    }
    environment.update({"CI": "1", "NO_COLOR": "1"})
    for name in credential_envs:
        value = os.environ.get(name, "")
        if value:
            environment[name] = value
        elif required:
            raise CapabilityPinError(f"{name} is required to start the MCP server")
    return environment


def _bound_tools(
    server_id: str, definition: Any, listed: Sequence[BaseTool]
) -> tuple[tuple[PinnedMCPTool, ...], str, str]:
    """The tools to pin, their server schema digest and the tool filter, held to the catalog.

    A row with a tool allowlist pins exactly that allowlist under the `allowlist` filter (the
    server may list more). A row without one pins every tool under `exact`, and the server
    must list exactly the catalog's tools."""

    by_name = {tool.name: tool for tool in listed}
    if definition.tool_allowlist is not None:
        bound, tool_filter = sorted(definition.tool_allowlist), "allowlist"
        missing = sorted(set(bound) - set(by_name))
        if missing:
            raise CapabilityPinError(
                f"{server_id} does not list the catalog's allowlisted tool(s) {missing}"
            )
    else:
        bound, tool_filter = sorted(definition.allowed_tools), "exact"
        if set(bound) != set(by_name):
            raise CapabilityPinError(
                f"{server_id} lists tools that differ from its catalog row: missing "
                f"{sorted(set(bound) - set(by_name))}, unexpected "
                f"{sorted(set(by_name) - set(bound))}"
            )
    pinned = tuple(
        PinnedMCPTool(tool_name=name, schema_digest=tool_schema_digest(by_name[name]))
        for name in bound
    )
    schema_digest = sha256_digest(
        [{"tool_name": tool.tool_name, "schema_digest": tool.schema_digest} for tool in pinned]
    )
    return pinned, schema_digest, tool_filter


async def pin_context7(
    node: Path | None,
    definition: Any,
    *,
    credential_env: str | None = None,
    lister: ToolLister = list_tools,
) -> PinnedMCPServer | NotPinned:
    """`mcp.context7` as a node module, when the catalog's package version is installed."""

    package, _, version = str(definition.package_pin).removeprefix("npm:").rpartition("@")
    try:
        if node is None:
            raise CapabilityPinError("--node is required to pin a node module")
        module = workspace_path(CONTEXT7_MODULE)
        if not module.is_file():
            raise CapabilityPinError(
                f"{package}@{version} is not installed at {CONTEXT7_MODULE} "
                f"(npm install {package}@{version} under the workspace .tools)"
            )
        metadata = json.loads((module.parent.parent / "package.json").read_text("utf-8"))
        if (metadata.get("name"), metadata.get("version")) != (package, version):
            raise CapabilityPinError(
                f"{CONTEXT7_MODULE} is {metadata.get('name')}@{metadata.get('version')}, "
                f"not the catalog's {package}@{version}"
            )
        credentials = (credential_env,) if credential_env is not None else ()
        listed = await lister(
            {
                "transport": "stdio",
                "command": str(node),
                "args": [str(module)],
                "env": _launch_environment(credentials, required=True),
            }
        )
        tools, schema_digest, tool_filter = _bound_tools(CONTEXT7_ID, definition, listed)
        if tool_filter != "exact":
            raise CapabilityPinError("a node-module pin binds every tool its server lists")
    except (CapabilityPinError, OSError, json.JSONDecodeError, ValueError) as error:
        return NotPinned(CONTEXT7_ID, str(error))
    module_digest = _digest_of(module)
    return PinnedMCPServer(
        server_id=CONTEXT7_ID,
        server_name="context7",
        ref=_ref(
            DefinitionKind.MCP_SERVER,
            CONTEXT7_ID,
            1,
            sha256_digest({"module": module_digest, "schema": schema_digest}),
        ),
        package_name=package,
        package_version=version,
        module_locator=CONTEXT7_MODULE,
        module_digest=module_digest,
        schema_digest=schema_digest,
        credential_env=credential_env,
        tools=tools,
    )


def read_version(binary: Path) -> str:
    """`<binary> --version`, run directly (an argument list, no shell)."""

    completed = subprocess.run(
        [str(binary), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=_launch_environment((), required=False),
    )
    return completed.stdout + completed.stderr


def _require_absolute_file(binary: Path) -> None:
    if not binary.is_absolute() or not binary.is_file():
        raise CapabilityPinError(f"{binary} is not an absolute path to a file on this host")


async def pin_github(
    binary: Path | None,
    definition: Any,
    *,
    lister: ToolLister = list_tools,
    version_reader: VersionReader = read_version,
) -> PinnedExecutableMCPServer | NotPinned:
    """`mcp.github` as a stdio executable: the release binary at an absolute path, hashed,
    run with the catalog row's read-only arguments. Never downloaded."""

    provenance = definition.source_provenance
    version, commit = provenance.upstream_version, provenance.commit_digest
    command, *arguments = definition.launch_template
    try:
        if binary is None:
            raise CapabilityPinError(
                f"no {command} binary was named (--github-mcp-server <absolute path>); "
                "nothing is downloaded"
            )
        _require_absolute_file(binary)
        reported = version_reader(binary)
        if f"Version: {version}" not in reported or f"Commit: {commit}" not in reported:
            raise CapabilityPinError(
                f"{binary.name} does not report the catalog's version {version} at commit {commit}"
            )
        credentials = tuple(definition.secret_refs)
        listed = await lister(
            {
                "transport": "stdio",
                "command": str(binary),
                "args": list(arguments),
                "env": _launch_environment(credentials, required=False),
            }
        )
        tools, schema_digest, tool_filter = _bound_tools(GITHUB_ID, definition, listed)
        command_digest = _digest_of(binary)
    except (CapabilityPinError, OSError, subprocess.SubprocessError, ValueError) as error:
        return NotPinned(GITHUB_ID, str(error))
    return PinnedExecutableMCPServer(
        server_id=GITHUB_ID,
        server_name="github",
        ref=_ref(
            DefinitionKind.MCP_SERVER,
            GITHUB_ID,
            1,
            sha256_digest(
                {"command": command_digest, "arguments": arguments, "schema": schema_digest}
            ),
        ),
        package_name=command,
        package_version=version,
        command=str(binary),
        command_digest=command_digest,
        arguments=tuple(arguments),
        schema_digest=schema_digest,
        credential_envs=credentials,
        tool_filter=cast(Any, tool_filter),
        tools=tools,
    )


async def pin_knowledge_capture(
    endpoint: str | None,
    definition: Any,
    *,
    credential_env: str | None,
    lister: ToolLister = list_tools,
) -> PinnedRemoteMCPServer | NotPinned:
    """`mcp.knowledge-capture` as a remote server: the catalog's allowlist of the tools the
    executor at `endpoint` lists. The endpoint is read, never written into the pin."""

    try:
        url = remote_endpoint(KNOWLEDGE_CAPTURE_ID, endpoint)
        headers: dict[str, str] = {}
        if credential_env is not None:
            token = os.environ.get(credential_env, "")
            if not token:
                raise CapabilityPinError(
                    f"{credential_env} is required to list the executor's tools "
                    "(--knowledge-capture-credential-env none for an executor without a token)"
                )
            headers["Authorization"] = "Bearer " + token
        listed = await lister(
            {"transport": definition.transport, "url": url, "headers": headers or None}
        )
        tools, schema_digest, tool_filter = _bound_tools(KNOWLEDGE_CAPTURE_ID, definition, listed)
    except CapabilityPinError as error:
        return NotPinned(KNOWLEDGE_CAPTURE_ID, str(error))
    except Exception as error:
        return NotPinned(
            KNOWLEDGE_CAPTURE_ID, f"the endpoint did not list its tools: {type(error).__name__}"
        )
    source = str(definition.package_pin)
    return PinnedRemoteMCPServer(
        server_id=KNOWLEDGE_CAPTURE_ID,
        server_name="knowledge_capture",
        ref=_ref(
            DefinitionKind.MCP_SERVER,
            KNOWLEDGE_CAPTURE_ID,
            1,
            sha256_digest({"source": source, "schema": schema_digest, "tool_filter": tool_filter}),
        ),
        source=source,
        schema_digest=schema_digest,
        credential_env=credential_env,
        tool_filter=cast(Any, tool_filter),
        tools=tools,
    )


async def research_rows(
    args: argparse.Namespace,
    *,
    lister: ToolLister = list_tools,
    version_reader: VersionReader = read_version,
) -> tuple[list[AnyPinnedMCPServer], list[NotPinned]]:
    """The three research rows, each pinned or reported with the reason it was not."""

    rows = catalog_rows()
    capture = rows[KNOWLEDGE_CAPTURE_ID]
    named = args.knowledge_capture_credential_env
    credential_env = None if named == "none" else named or next(iter(capture.secret_refs), None)
    endpoint = args.knowledge_capture_endpoint or get_settings().mcp_server_endpoints.get(
        KNOWLEDGE_CAPTURE_ID
    )
    outcomes = (
        await pin_context7(
            args.node.resolve(strict=True) if args.node is not None else None,
            rows[CONTEXT7_ID],
            credential_env=args.context7_credential_env,
            lister=lister,
        ),
        await pin_github(
            args.github_mcp_server, rows[GITHUB_ID], lister=lister, version_reader=version_reader
        ),
        await pin_knowledge_capture(
            endpoint, capture, credential_env=credential_env, lister=lister
        ),
    )
    pinned = [item for item in outcomes if not isinstance(item, NotPinned)]
    return pinned, [item for item in outcomes if isinstance(item, NotPinned)]


def add_research_rows(output: Path, pinned: Sequence[AnyPinnedMCPServer]) -> None:
    """Add or replace only the research rows of ``output``; a row that was not pinned now
    leaves any earlier row for the same server in place."""

    document = json.loads(output.read_text(encoding="utf-8"))
    CapabilityPins.model_validate(document)
    for row in pinned:
        section = RESEARCH_SECTIONS[row.server_id]
        kept = [item for item in document.get(section, ()) if item["server_id"] != row.server_id]
        document[section] = [*kept, row.model_dump(mode="json")]
    CapabilityPins.model_validate(document)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def _agent_skills() -> Any:
    spec = importlib.util.spec_from_file_location(
        "mc_pin_agent_skills", CATALOG_SEEDS / "agent_skills.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def catalog_skill_rows(application_id: str, custody_root: Path) -> list[PinnedSkill]:
    """A `bytes_v1` custody Skill pin for every method skill the application's agent-skill
    seed imports, at the revision the seed publishes: its recorded import bytes are published
    into ``custody_root`` under that id and revision (idempotent: the same bytes are the same
    version), and the pin names the custody manifest. Nothing is downloaded."""

    from mission_control.adapters.capabilities.capability_bundles import DirectoryBundleStore

    module = _agent_skills()
    imported = {
        record["capability_id"]
        for name, record in module.imported_records().items()
        if application_id in module.IMPORTED_SKILLS[name][1]
    }
    store = DirectoryBundleStore(custody_root)
    rows: list[PinnedSkill] = []
    for entry, revision, _changed in module.revised_definitions(application_id):
        definition = entry["definition"]
        if definition.logical_id not in imported:
            continue
        directory = REPOSITORY / entry["source"]["directory"]
        manifest = store.publish(directory, asset_id=definition.logical_id, version=revision)
        skill_md = dict(directory_files(directory))["SKILL.md"]
        rows.append(
            PinnedSkill(
                ref=_ref(
                    DefinitionKind.SKILL, definition.logical_id, revision, manifest.bundle_digest
                ),
                skill_name=definition.skill_name,
                source_locator=CUSTODY_SCHEME + manifest.digest,
                digest_format="bytes_v1",
                bundle_digest=manifest.bundle_digest,
                skill_md_digest=bytes_digest(skill_md),
                mount_root=f"/skills/{definition.skill_name}",
            )
        )
    return rows


def add_skill_rows(output: Path, skills: Sequence[PinnedSkill]) -> None:
    """Add or replace only the Skill pins named by ``skills`` (by skill name) in ``output``."""

    document = json.loads(output.read_text(encoding="utf-8"))
    CapabilityPins.model_validate(document)
    names = {skill.skill_name for skill in skills}
    kept = [item for item in document.get("skills", ()) if item["skill_name"] not in names]
    document["skills"] = [*kept, *(skill.model_dump(mode="json") for skill in skills)]
    CapabilityPins.model_validate(document)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def research_report(
    pinned: Sequence[AnyPinnedMCPServer], not_pinned: Sequence[NotPinned]
) -> dict[str, Any]:
    return {
        "pinned": {
            row.server_id: {
                "form": RESEARCH_SECTIONS[row.server_id],
                "tools": [tool.tool_name for tool in row.tools],
            }
            for row in pinned
        },
        "not_pinned": {item.server_id: item.reason for item in not_pinned},
    }


def custody_manifest(directory: Path, *, asset_id: str, version: int) -> BundleManifest:
    """The manifest custody stages for these bytes (Supabase `stage`, local `publish`)."""

    files = directory_files(directory)
    return BundleManifest(
        asset_id=asset_id,
        version=version,
        files=file_manifest(files),
        bundle_digest=bundle_digest(files),
    )


def custody_skill_pin(
    directory: Path,
    *,
    logical_id: str = AGENT_BROWSER_SKILL_ID,
    version: int = AGENT_BROWSER_SKILL_VERSION,
    skill_name: str = AGENT_BROWSER_SKILL_NAME,
) -> PinnedSkill:
    """A `bytes_v1` Skill pin naming the immutable custody manifest of ``directory``."""

    manifest = custody_manifest(directory, asset_id=logical_id, version=version)
    skill_md = dict(directory_files(directory))["SKILL.md"]
    return PinnedSkill(
        ref=_ref(DefinitionKind.SKILL, logical_id, version, manifest.bundle_digest),
        skill_name=skill_name,
        source_locator=CUSTODY_SCHEME + manifest.digest,
        digest_format="bytes_v1",
        bundle_digest=manifest.bundle_digest,
        skill_md_digest=bytes_digest(skill_md),
        mount_root=f"/skills/{skill_name}",
    )


def register_command(skill: PinnedSkill, directory: Path) -> str:
    """The integrator's custody registration for ``skill`` (Supabase; publisher env file)."""

    return (
        "uv run --no-sync python scripts/register_supabase_skill_bundle.py "
        f"{directory.as_posix()} --asset-id {skill.ref.logical_id} --version {skill.ref.revision} "
        f"--skill-name {skill.skill_name} --definition-digest {skill.ref.digest} "
        "--env-file .scratch/sprint-oc/runtime/<app>/bundle-publisher.env"
    )


def upgrade_skill_custody(output: Path, directory: Path) -> PinnedSkill:
    """Replace only the agent-browser Skill pin of ``output`` with its custody form."""

    document = json.loads(output.read_text(encoding="utf-8"))
    CapabilityPins.model_validate(document)
    skill = custody_skill_pin(directory)
    names = [item.get("skill_name") for item in document.get("skills", ())]
    if names.count(AGENT_BROWSER_SKILL_NAME) != 1:
        raise SystemExit(f"{output} must pin exactly one {AGENT_BROWSER_SKILL_NAME} Skill")
    # Only this entry changes; every other pin keeps its exact JSON (no re-dump of defaults).
    document["skills"] = [
        skill.model_dump(mode="json")
        if item.get("skill_name") == AGENT_BROWSER_SKILL_NAME
        else item
        for item in document["skills"]
    ]
    CapabilityPins.model_validate(document)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return skill


def _digest_of(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _package_version(module: Path) -> str:
    package = json.loads((module.parent.parent / "package.json").read_text(encoding="utf-8"))
    return str(package["version"])


def _ref(kind: DefinitionKind, logical_id: str, revision: int, digest: str) -> PinnedExactRef:
    return PinnedExactRef(kind=kind, logical_id=logical_id, revision=revision, digest=digest)


async def _mcp_tools(
    node: Path, module: Path, credential_env: str | None
) -> tuple[tuple[PinnedMCPTool, ...], str]:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "PATHEXT", "SYSTEMROOT", "COMSPEC", "WINDIR")
        if key in os.environ
    }
    environment.update({"CI": "1", "NO_COLOR": "1"})
    if credential_env is not None:
        value = os.environ.get(credential_env, "")
        if not value:
            raise SystemExit(f"{credential_env} is required to start the MCP server")
        environment[credential_env] = value
    client = MultiServerMCPClient(
        cast(
            Any,
            {
                "pinned": {
                    "transport": "stdio",
                    "command": str(node),
                    "args": [str(module)],
                    "env": environment,
                }
            },
        )
    )
    tools = await client.get_tools()
    pinned = tuple(
        PinnedMCPTool(tool_name=tool.name, schema_digest=tool_schema_digest(tool))
        for tool in sorted(tools, key=lambda item: item.name)
    )
    schema_digest = sha256_digest(
        [{"tool_name": tool.tool_name, "schema_digest": tool.schema_digest} for tool in pinned]
    )
    return pinned, schema_digest


async def main() -> int:
    args = _arguments()
    if args.upgrade_skill_custody:
        directory = args.skill_custody.resolve(strict=True)
        skill = upgrade_skill_custody(args.output, directory)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "skill": skill.model_dump(mode="json"),
                    "register": register_command(skill, args.skill_custody),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.add_research or args.add_catalog_skills:
        report: dict[str, Any] = {"output": str(args.output)}
        if args.add_research:
            pinned, not_pinned = await research_rows(args)
            add_research_rows(args.output, pinned)
            report.update(research_report(pinned, not_pinned))
        if args.add_catalog_skills:
            skills = catalog_skill_rows(args.add_catalog_skills, args.skill_custody_root)
            add_skill_rows(args.output, skills)
            report["skills"] = {skill.skill_name: skill.ref.revision for skill in skills}
        print(json.dumps(report, sort_keys=True))
        return 0
    node = args.node.resolve(strict=True)
    servers: list[PinnedMCPServer] = []
    if not args.skip_mcp:
        for server_id, name, locator, package, credential in (
            ("mcp.firecrawl", "firecrawl", FIRECRAWL_MODULE, "firecrawl-mcp", "FIRECRAWL_API_KEY"),
            ("mcp.tavily", "tavily", TAVILY_MODULE, "tavily-mcp", "TAVILY_API_KEY"),
        ):
            module = workspace_path(locator)
            tools, schema_digest = await _mcp_tools(node, module, credential)
            module_digest = _digest_of(module)
            servers.append(
                PinnedMCPServer(
                    server_id=server_id,
                    server_name=name,
                    ref=_ref(
                        DefinitionKind.MCP_SERVER,
                        server_id,
                        1,
                        sha256_digest({"module": module_digest, "schema": schema_digest}),
                    ),
                    package_name=package,
                    package_version=_package_version(module),
                    module_locator=locator,
                    module_digest=module_digest,
                    schema_digest=schema_digest,
                    credential_env=credential,
                    tools=tools,
                )
            )
    if args.skill_custody is not None:
        skill = custody_skill_pin(args.skill_custody.resolve(strict=True))
    else:
        skill_directory = workspace_path(AGENT_BROWSER_SKILL)
        bundle = read_skill_bundle(skill_directory)
        skill_md = next(content for path, content in bundle.files if path == "SKILL.md")
        skill = PinnedSkill(
            ref=_ref(
                DefinitionKind.SKILL,
                AGENT_BROWSER_SKILL_ID,
                AGENT_BROWSER_SKILL_VERSION,
                bundle.bundle_digest,
            ),
            skill_name=AGENT_BROWSER_SKILL_NAME,
            source_locator=AGENT_BROWSER_SKILL,
            bundle_digest=bundle.bundle_digest,
            skill_md_digest=sha256_digest(skill_md.decode("utf-8")),
            mount_root=f"/skills/{AGENT_BROWSER_SKILL_NAME}",
        )
    entrypoint = workspace_path(AGENT_BROWSER_ENTRYPOINT)
    browser = AgentBrowserPageTool(node_executable=node, entrypoint=entrypoint)
    tool = PinnedTool(
        ref=_ref(DefinitionKind.TOOL, "tool.agent-browser-page", 1, tool_schema_digest(browser)),
        tool_name=AGENT_BROWSER_PAGE_TOOL_NAME,
        kind="agent_browser_page",
        schema_digest=tool_schema_digest(browser),
        entrypoint_locator=AGENT_BROWSER_ENTRYPOINT,
        entrypoint_digest=_digest_of(entrypoint),
        package_version=_package_version(entrypoint),
    )
    models: list[PinnedModel] = []
    sandboxes: list[PinnedSandbox] = []
    checkpointers: list[PinnedPersistence] = []
    stores: list[PinnedPersistence] = []
    for component in args.component:
        kind, logical_id, revision, digest = component.split(":", 3)
        if kind.startswith("model"):
            # OC-R6: `model@<vendor>@<model_id>:<logical_id>:<revision>:<digest>`; a served
            # model pin states the vendor and model id it serves.
            parts = kind.split("@")
            if len(parts) != 3 or parts[0] != "model":
                raise SystemExit("model components are model@<vendor>@<model_id>:...")
            models.append(
                PinnedModel(
                    ref=_ref(DefinitionKind.MODEL, logical_id, int(revision), digest),
                    provider=cast(Any, parts[1]),
                    model_id=parts[2],
                )
            )
        elif kind.startswith("sandbox."):
            sandboxes.append(
                PinnedSandbox(
                    ref=_ref(DefinitionKind.SANDBOX_PROFILE, logical_id, int(revision), digest),
                    backend=cast(Any, kind.removeprefix("sandbox.")),
                )
            )
        elif kind == "checkpointer":
            checkpointers.append(
                PinnedPersistence(
                    ref=_ref(DefinitionKind.RUNTIME_PROFILE, logical_id, int(revision), digest)
                )
            )
        elif kind == "store":
            stores.append(
                PinnedPersistence(
                    ref=_ref(DefinitionKind.MEMORY_POLICY, logical_id, int(revision), digest)
                )
            )
        else:
            raise SystemExit(f"unknown component kind: {kind}")
    research: list[AnyPinnedMCPServer] = []
    not_pinned: list[NotPinned] = []
    if not args.skip_mcp:
        research, not_pinned = await research_rows(args)
    pins = CapabilityPins(
        mcp_servers=(
            *servers,
            *(row for row in research if isinstance(row, PinnedMCPServer)),
        ),
        remote_mcp_servers=tuple(row for row in research if isinstance(row, PinnedRemoteMCPServer)),
        executable_mcp_servers=tuple(
            row for row in research if isinstance(row, PinnedExecutableMCPServer)
        ),
        skills=(skill,),
        tools=(tool,),
        models=tuple(models),
        sandboxes=tuple(sandboxes),
        checkpointers=tuple(checkpointers),
        stores=tuple(stores),
    )
    document = pins.model_dump(mode="json")
    for section in ("remote_mcp_servers", "executable_mcp_servers"):
        if not document[section]:
            del document[section]  # a file without these forms keeps its earlier shape
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "research": research_report(research, not_pinned),
                "mcp_servers": {
                    server.server_id: [tool.tool_name for tool in server.tools]
                    for server in servers
                },
                "skill_bundle_digest": skill.bundle_digest,
                "browser_tool_schema_digest": tool.schema_digest,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

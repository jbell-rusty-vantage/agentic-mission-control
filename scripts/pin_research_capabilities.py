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
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from langchain_mcp_adapters.client import MultiServerMCPClient

from mission_control.adapters.capabilities.capability_bundles import (
    BundleManifest,
    bundle_digest,
    bytes_digest,
    directory_files,
    file_manifest,
)
from mission_control.adapters.capabilities.capability_pins import (
    CapabilityPins,
    PinnedExactRef,
    PinnedMCPServer,
    PinnedMCPTool,
    PinnedModel,
    PinnedPersistence,
    PinnedSandbox,
    PinnedSkill,
    PinnedTool,
    read_skill_bundle,
    workspace_path,
)
from mission_control.adapters.deep_agents.browser_tool import (
    AGENT_BROWSER_PAGE_TOOL_NAME,
    AgentBrowserPageTool,
)
from mission_control.adapters.deep_agents.materializer import tool_schema_digest
from mission_control.bootstrap.settings import PROJECT_ROOT
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
    args = parser.parse_args()
    if args.upgrade_skill_custody and args.skill_custody is None:
        parser.error("--upgrade-skill-custody needs --skill-custody <directory>")
    if not args.upgrade_skill_custody and args.node is None:
        parser.error("--node is required")
    return args


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
    pins = CapabilityPins(
        mcp_servers=tuple(servers),
        skills=(skill,),
        tools=(tool,),
        models=tuple(models),
        sandboxes=tuple(sandboxes),
        checkpointers=tuple(checkpointers),
        stores=tuple(stores),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(pins.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
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

"""Checked-in `claude_managed` pack files and the digests prepare keys provider resources by.

R30 (DECISIONS): until the general projection (HL-21) exists, the first `claude_managed`
prepare reads a pack directory, `deployments/hosted-packs/<app>/claude_managed/`:

- `pack.yaml`: the pack's identity (application, lane profile, placement, data class and the
  task queue its lane worker serves);
- `agent.yaml` plus the system overlay it names: model, the agent toolset with a permission
  policy per tool, Mission Control custom tools, MCP servers, skill directories and metadata;
- `environment.yaml`: the cloud Environment Kit (packages and `limited` networking with
  explicit `allowed_hosts`; `include_signal_ingress` adds the ingress host given at sync);
- `vault.yaml`: credential *names* and the hosts each may reach. Values come from the worker
  environment at sync time and never from a file.

`load_pack` validates a directory into a `ClaudeManagedPack`; `render_pack` resolves it for one
sync (the target repository's AGENTS.md rendered into `system`, because Managed Agents does not
read it, and the ingress host) into a `RenderedPack` carrying four digests:

- `materialization_digest` (one agent version per digest): model, system, tools, MCP servers,
  multiagent, the agent metadata and the skills by *bundle* digest, so it is the same in every
  installation;
- a bundle digest per skill directory (the skill's display name carries it: skills have no
  metadata);
- `kit_digest` (one environment per digest: environments are not versioned);
- `secret_set_digest` (one vault per installation and digest): credential names and hosts.

A pack is refused when its data class is not admitted on `claude_managed` (SPEC-06 section 8),
when two skill directories share a name, or when any pack file carries something shaped like an
Anthropic API key. A render is refused when a credential's host is outside the rendered
environment allowlist, ingress host included (the session would report
`credential_host_unreachable_error`, HL-23), or when the target repository's AGENTS.md carries
an Anthropic API key (it is uploaded as part of `system`).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mission_control.application.secrets.references import SecretDeclaration
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.data_class import DataClass, admit_data_class

PACK_SCHEMA: Final = "mc.hosted_pack.claude_managed.v1"
AGENT_TOOLSET: Final = "agent_toolset_20260401"
# Multiagent with dynamic workflows (the Managed Agents docs' agent `multiagent` field); a pack
# enables it only for read-only knowledge work (DECISIONS R33). Not exercised by a drill yet.
MULTIAGENT_WITH_WORKFLOWS: Final = {"type": "multiagent_20261001", "workflows": {"type": "enabled"}}
AGENT_TOOLS: Final = ("bash", "read", "write", "edit", "glob", "grep", "web_fetch", "web_search")
REPOSITORY_INSTRUCTIONS_HEADING: Final = "# Repository instructions (AGENTS.md)"
# An Anthropic API key (org or admin) in any pack file refuses the pack.
_API_KEY_SHAPE: Final = re.compile(rb"sk-ant-[A-Za-z0-9_\-]{8,}")
_ENV_NAME: Final = re.compile(r"^[A-Z][A-Z0-9_]*$")
_HOST: Final = re.compile(
    r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)

PermissionPolicy = Literal["always_allow", "always_ask"]
PackageManager = Literal["apt", "cargo", "gem", "go", "npm", "pip"]


class PackRefused(ValueError):
    """The pack directory cannot be prepared; the message names the file and the rule."""


class _PackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PackIdentity(_PackModel):
    schema_: Literal["mc.hosted_pack.claude_managed.v1"] = Field(alias="schema")
    pack: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    application: str = Field(min_length=1)
    lane_profile: Literal["claude_managed"]
    placement: Literal["cloud"]
    data_class: DataClass
    task_queue: str = Field(min_length=1)


class CustomTool(_PackModel):
    """A Mission Control tool the lane answers through `user.custom_tool_result`."""

    name: str = Field(pattern=r"^mc_[a-z_]+$")
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]


class McpServer(_PackModel):
    name: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    permission_policy: PermissionPolicy = "always_ask"


class AgentSpec(_PackModel):
    name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    system: str = Field(min_length=1, description="The instruction overlay file, pack-relative.")
    repository_instructions: str | None = Field(
        default=None, description="The target repository's AGENTS.md path, repo-relative."
    )
    tools: dict[str, PermissionPolicy] = Field(
        description="The agent toolset tools enabled, each with its permission policy."
    )
    custom_tools: tuple[CustomTool, ...] = ()
    mcp_servers: tuple[McpServer, ...] = ()
    skills: tuple[str, ...] = Field(default=(), description="Skill directories, pack-relative.")
    metadata: dict[str, str] = Field(default_factory=dict)
    multiagent: bool = Field(
        default=False,
        description="Subagents and dynamic workflows; read-only knowledge packs only (R33).",
    )

    @model_validator(mode="after")
    def _known_tools(self) -> AgentSpec:
        unknown = sorted(set(self.tools) - set(AGENT_TOOLS))
        if unknown:
            raise ValueError(f"unknown agent toolset tool(s): {', '.join(unknown)}")
        clashes = {tool.name for tool in self.custom_tools} & set(AGENT_TOOLS)
        if clashes:
            raise ValueError(f"custom tool(s) collide with built-ins: {', '.join(sorted(clashes))}")
        if any(key.startswith("mc_") for key in self.metadata):
            raise ValueError("agent metadata keys starting with mc_ are reserved for prepare")
        return self


class Networking(_PackModel):
    allowed_hosts: tuple[str, ...] = ()
    include_signal_ingress: bool = False
    allow_package_managers: bool = False
    allow_mcp_servers: bool = False

    @model_validator(mode="after")
    def _hosts(self) -> Networking:
        bad = [host for host in self.allowed_hosts if not _HOST.match(host)]
        if bad:
            raise ValueError(f"not a host name: {', '.join(bad)}")
        return self


class EnvironmentSpec(_PackModel):
    kit: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    packages: dict[PackageManager, tuple[str, ...]] = Field(default_factory=dict)
    networking: Networking

    @model_validator(mode="after")
    def _package_egress(self) -> EnvironmentSpec:
        if any(self.packages.values()) and not self.networking.allow_package_managers:
            raise ValueError("packages need networking.allow_package_managers under limited egress")
        return self


class CredentialSpec(_PackModel):
    name: str = Field(description="The environment variable the sandbox sees.")
    allowed_hosts: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _name(self) -> CredentialSpec:
        if not _ENV_NAME.match(self.name):
            raise ValueError(f"credential name {self.name} is not an environment variable name")
        return self


class VaultSpec(_PackModel):
    credentials: tuple[CredentialSpec, ...] = Field(default=(), max_length=20)


class ClaudeManagedPack(_PackModel):
    """A validated pack directory: its declarations plus the files they name, read once."""

    root: Path
    identity: PackIdentity
    agent: AgentSpec
    environment: EnvironmentSpec
    vault: VaultSpec
    system_overlay: str
    skill_files: dict[str, tuple[tuple[str, bytes], ...]] = Field(
        description="Per skill directory name, its files as (relative path, content), sorted."
    )

    @property
    def pack_id(self) -> str:
        return f"{self.identity.application}/{self.identity.pack}"


@dataclass(frozen=True)
class SkillBundle:
    name: str
    files: tuple[tuple[str, bytes], ...]
    bundle_digest: str

    @property
    def display_name(self) -> str:
        """Skills have no metadata, so the display name carries the bundle digest."""

        return f"mc-{self.name}-{self.bundle_digest.removeprefix('sha256:')[:16]}"

    def upload(self) -> list[tuple[str, bytes]]:
        return [(f"{self.name}/{path}", content) for path, content in self.files]


@dataclass(frozen=True)
class RenderedPack:
    """One sync's resolved pack: provider request bodies minus provider ids, plus digests."""

    pack: ClaudeManagedPack
    system: str
    skills: tuple[SkillBundle, ...]
    environment_config: Mapping[str, Any]
    materialization_digest: str
    kit_digest: str
    secret_set_digest: str
    secret_declarations: tuple[SecretDeclaration, ...] = ()

    @property
    def environment_name(self) -> str:
        return f"mc-{self.pack.environment.kit}-{self.kit_digest.removeprefix('sha256:')[:8]}"

    def agent_body(self, skill_refs: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        """The agent create/update body with the provider's skill references filled in."""

        return _agent_body(self.pack.agent, self.system, skill_refs)


def load_pack(root: Path) -> ClaudeManagedPack:
    """Read and validate one `claude_managed` pack directory."""

    root = root.resolve()
    raw = {name: _read(root / f"{name}.yaml") for name in ("pack", "agent", "environment", "vault")}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if _API_KEY_SHAPE.search(path.read_bytes()):
            raise PackRefused(f"{path.relative_to(root).as_posix()}: carries an Anthropic API key")
    try:
        identity = PackIdentity.model_validate(_mapping(raw["pack"], "pack.yaml"))
        agent = AgentSpec.model_validate(_mapping(raw["agent"], "agent.yaml"))
        environment = EnvironmentSpec.model_validate(
            _mapping(raw["environment"], "environment.yaml")
        )
        vault = VaultSpec.model_validate(_mapping(raw["vault"], "vault.yaml"))
    except ValidationError as error:
        raise PackRefused(f"{root.name}: {error}") from None
    issue = admit_data_class(identity.lane_profile, identity.data_class)
    if issue is not None:
        raise PackRefused(f"pack.yaml: {issue.message}")
    skill_dirs = [_inside(root, rel) for rel in agent.skills]
    names = [directory.name for directory in skill_dirs]
    shared = sorted({name for name in names if names.count(name) > 1})
    if shared:
        # The directory name is the skill's name in the upload and its display name.
        raise PackRefused(f"agent.yaml: skill directories share the name {', '.join(shared)}")
    return ClaudeManagedPack(
        root=root,
        identity=identity,
        agent=agent,
        environment=environment,
        vault=vault,
        system_overlay=_inside(root, agent.system).read_text(encoding="utf-8"),
        skill_files={directory.name: _skill_files(directory) for directory in skill_dirs},
    )


def render_pack(
    pack: ClaudeManagedPack,
    *,
    installation_id: str,
    repo_root: Path | None = None,
    ingress_host: str | None = None,
) -> RenderedPack:
    """Resolve the pack for one sync and compute the digests its resources are keyed by."""

    system = pack.system_overlay.rstrip() + "\n"
    if pack.agent.repository_instructions is not None:
        if repo_root is None:
            raise PackRefused(
                "agent.yaml: repository_instructions needs the target repository root"
            )
        agents_md = _inside(repo_root.resolve(), pack.agent.repository_instructions)
        rules = agents_md.read_text(encoding="utf-8").strip()
        if _API_KEY_SHAPE.search(rules.encode("utf-8")):
            raise PackRefused(
                f"{pack.agent.repository_instructions}: the target repository's instructions "
                "carry an Anthropic API key"
            )
        system += f"\n{REPOSITORY_INSTRUCTIONS_HEADING}\n\n{rules}\n"
    skills = tuple(
        SkillBundle(name=name, files=files, bundle_digest=bundle_digest(files))
        for name, files in sorted(pack.skill_files.items())
    )
    environment_config = _environment_config(pack.environment, ingress_host)
    _check_credential_hosts(pack.vault, environment_config["networking"]["allowed_hosts"])
    return RenderedPack(
        pack=pack,
        system=system,
        skills=skills,
        environment_config=environment_config,
        materialization_digest=sha256_digest(
            {
                "pack": pack.pack_id,
                "agent": _agent_body(
                    pack.agent,
                    system,
                    [{"type": "custom", "bundle_digest": skill.bundle_digest} for skill in skills],
                ),
                "metadata": pack.agent.metadata,
            }
        ),
        kit_digest=sha256_digest({"kit": pack.environment.kit, "config": environment_config}),
        secret_set_digest=sha256_digest(
            {
                "installation": installation_id,
                "credentials": sorted(
                    (credential.name, sorted(credential.allowed_hosts))
                    for credential in pack.vault.credentials
                ),
            }
        ),
    )


def bundle_digest(files: Sequence[tuple[str, bytes]]) -> str:
    """The digest of one skill directory: its sorted relative paths and content hashes."""

    return sha256_digest(
        sorted((path, hashlib.sha256(content).hexdigest()) for path, content in files)
    )


def _agent_body(
    spec: AgentSpec, system: str, skill_refs: Sequence[Mapping[str, str]]
) -> dict[str, Any]:
    return {
        "name": spec.name,
        "model": spec.model,
        "system": system,
        "tools": _tools(spec),
        "mcp_servers": [
            {"type": "url", "name": server.name, "url": server.url} for server in spec.mcp_servers
        ],
        "skills": [dict(ref) for ref in skill_refs],
        "multiagent": dict(MULTIAGENT_WITH_WORKFLOWS) if spec.multiagent else None,
    }


def _tools(spec: AgentSpec) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "type": AGENT_TOOLSET,
            "default_config": {"enabled": False},
            "configs": [
                {"name": name, "enabled": True, "permission_policy": {"type": policy}}
                for name, policy in sorted(spec.tools.items())
            ],
        }
    ]
    tools.extend(
        {
            "type": "mcp_toolset",
            "mcp_server_name": server.name,
            "default_config": {"permission_policy": {"type": server.permission_policy}},
        }
        for server in spec.mcp_servers
    )
    tools.extend(
        {
            "type": "custom",
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in spec.custom_tools
    )
    return tools


def _environment_config(spec: EnvironmentSpec, ingress_host: str | None) -> dict[str, Any]:
    hosts = list(spec.networking.allowed_hosts)
    if spec.networking.include_signal_ingress:
        if not ingress_host or not _HOST.match(ingress_host):
            raise PackRefused(
                "environment.yaml: include_signal_ingress needs the Signal Ingress host name"
            )
        hosts.append(ingress_host)
    return {
        "type": "cloud",
        # Always explicit: the API default is `unrestricted` (SPEC-06 section 4.1).
        "networking": {
            "type": "limited",
            "allowed_hosts": sorted(set(hosts)),
            "allow_package_managers": spec.networking.allow_package_managers,
            "allow_mcp_servers": spec.networking.allow_mcp_servers,
        },
        "packages": {manager: list(names) for manager, names in sorted(spec.packages.items())},
    }


def _check_credential_hosts(vault: VaultSpec, allowed: Sequence[str]) -> None:
    for credential in vault.credentials:
        unreachable = [
            host for host in credential.allowed_hosts if not _host_allowed(host, allowed)
        ]
        if unreachable:
            raise PackRefused(
                f"vault.yaml: {credential.name} reaches {', '.join(unreachable)}, which the "
                "environment allowlist does not (credential_host_unreachable_error)"
            )


def _host_allowed(host: str, allowed: Sequence[str]) -> bool:
    return any(
        host == entry or (entry.startswith("*.") and host.endswith(entry[1:])) for entry in allowed
    )


def _skill_files(directory: Path) -> tuple[tuple[str, bytes], ...]:
    if not (directory / "SKILL.md").is_file():
        raise PackRefused(f"{directory.name}: a skill directory needs SKILL.md at its root")
    return tuple(
        (path.relative_to(directory).as_posix(), path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    )


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.exists():
        raise PackRefused(f"{relative}: not a path inside {root.name}")
    return path


def _read(path: Path) -> object:
    if not path.is_file():
        raise PackRefused(f"{path.name}: missing from the pack")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PackRefused(f"{name}: not a mapping")
    return value


__all__ = [
    "PACK_SCHEMA",
    "ClaudeManagedPack",
    "PackRefused",
    "RenderedPack",
    "SkillBundle",
    "bundle_digest",
    "load_pack",
    "render_pack",
]

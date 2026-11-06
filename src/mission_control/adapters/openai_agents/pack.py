"""`codex_agents` pack files: what a hosted pack prepares through the Agents API (SPEC-06
section 5.1; DECISIONS R30; HL-11).

Until the full Cognition Pack projection lands (HL-21), the `codex_agents` lane prepares from
checked-in files under `deployments/hosted-packs/<application>/codex_agents/`:

- `pack.yaml`: the application, Data Class and task queue; the saved agent (model, the
  instruction overlay and the repository rules inlined after it, Mission Control function tools
  `mc_*`, MCP servers, `multi_agent` off); the environment template (setup commands, packages,
  an explicit network policy, variables); and the vault credentials by name;
- the instruction and repository-rule Markdown files `pack.yaml` names;
- `skills/<name>/` (a `SKILL.md` with `name` and `description`) and `plugins/<name>/` (a
  `.codex-plugin/plugin.json`), each inlined into the template as a ZIP.

The repository rules are inlined because a turn answered before the hosted environment connects
does not see `/workspace/AGENTS.md` (Q-O2, research/provider-smoke-2026-10.md section 1).
Skills and plugins ride inline in the template (`HostedSkillParamInline`, `HostedPluginParam`
in `openai` 3.29.0): a Skills API upload has no metadata and takes its name from `SKILL.md`,
so it cannot be keyed by digest, while the template name can. The layout inside an inline ZIP
(a skill under its own top directory, a plugin at the root) is UNVERIFIED until a live drill.

Values never live in pack files: a credential names the worker environment variable its value
is read from at sync time, and an organisation API key is refused as a source. Each part has a
digest over what shapes it, and the pack digest (`mc_pack` on the saved agent) covers them all.
"""

from __future__ import annotations

import base64
import io
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Annotated, Any, Final, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from mission_control.adapters.capabilities.capability_bundles import (
    BundleError,
    bundle_digest,
    directory_files,
)
from mission_control.application.secrets.references import SecretDeclaration
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.data_class import DataClass, admit_data_class

PACK_FILE: Final = "pack.yaml"
PACK_SCHEMA: Final = "mc.hosted_pack.codex_agents.v1"
SKILL_FILE: Final = "SKILL.md"
PLUGIN_FILE: Final = ".codex-plugin/plugin.json"
# The worker variables that hold organisation keys never feed a vault credential.
ORGANISATION_KEY_VARIABLES: Final = frozenset({"OPENAI_API_KEY", "ANTHROPIC_API_KEY"})
# Hosted environment variables the Agents API rejects (research/openai-hosted-agents.md
# section 3); `CODEX_` also prefixes the reserved credential names.
_RESERVED_VARIABLE = re.compile(r"^(PATH|OPENAI_API_KEY|CODEX_.*)$")
_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Exact hosts only: no scheme, port, path or wildcard.
_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_HOST = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})+$")
_ZIP_TIME: Final = (1980, 1, 1, 0, 0, 0)


class PackError(ValueError):
    """A pack directory that cannot be prepared: missing, malformed or against policy."""


class _PackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _exact_hosts(values: tuple[str, ...]) -> tuple[str, ...]:
    for host in values:
        if not _HOST.match(host):
            raise ValueError(f"{host!r} is not an exact lowercase host name")
    if len(set(values)) != len(values):
        raise ValueError("hosts must be distinct")
    return values


Hosts = Annotated[tuple[str, ...], AfterValidator(_exact_hosts)]


class FunctionTool(_PackModel):
    """A Mission Control function tool; the Agents API requires its description."""

    name: str = Field(pattern=r"^mc_[a-z0-9_]{1,60}$")
    description: str = Field(min_length=1)
    parameters: dict[str, Any]


class McpServer(_PackModel):
    """A remote MCP server; its credential is the vault credential matching its URL."""

    server_label: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    server_url: str = Field(pattern=r"^https://\S+$")
    allowed_tools: tuple[str, ...] | None = None
    required: bool = False


class AgentSpec(_PackModel):
    name: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1)
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = (
        None
    )
    service_tier: Literal["auto", "default", "flex", "priority", "fast"] | None = None
    instructions: str = Field(min_length=1)
    repo_rules: tuple[str, ...] = ()
    # Subagents cannot call function tools (SPEC-06 section 5.3).
    multi_agent: Literal[False] = False
    function_tools: tuple[FunctionTool, ...] = ()
    mcp_servers: tuple[McpServer, ...] = ()

    @model_validator(mode="after")
    def _distinct_tools(self) -> AgentSpec:
        names = [tool.name for tool in self.function_tools]
        labels = [server.server_label for server in self.mcp_servers]
        if len(set(names)) != len(names) or len(set(labels)) != len(labels):
            raise ValueError("function tool names and MCP server labels must be distinct")
        return self


class SetupCommand(_PackModel):
    command: str = Field(min_length=1)
    cwd: str | None = Field(default=None, pattern=r"^/")


class NetworkPolicy(_PackModel):
    """Always explicit: an omitted policy is whatever the API version defaults to."""

    access: Literal["enabled", "disabled", "restricted"]
    allowed_domains: Hosts = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def _domains_only_when_restricted(self) -> NetworkPolicy:
        if (self.access == "restricted") != bool(self.allowed_domains):
            raise ValueError("allowed_domains is required with, and only with, access restricted")
        return self


class Packages(_PackModel):
    python: tuple[str, ...] = ()
    system: tuple[str, ...] = ()
    npm: tuple[str, ...] = ()


class EnvironmentSpec(_PackModel):
    container_size: Literal["small", "medium", "large"] = "medium"
    network: NetworkPolicy
    packages: Packages = Packages()
    setup_commands: tuple[SetupCommand, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    skills: str | None = None
    plugins: str | None = None

    @field_validator("env")
    @classmethod
    def _allowed_variables(cls, env: dict[str, str]) -> dict[str, str]:
        for name in env:
            if not _VARIABLE.match(name) or _RESERVED_VARIABLE.match(name):
                raise ValueError(f"environment variable {name} is reserved or malformed")
        return env


class VaultCredentialSpec(_PackModel):
    """An egress-substituted `environment_variable` credential: `name` is the variable the
    sandbox sees (a placeholder), `source_env` the worker variable holding the value."""

    name: str = Field(pattern=_VARIABLE.pattern)
    source_env: str = Field(pattern=_VARIABLE.pattern)
    allowed_hosts: Hosts = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def _no_reserved_or_organisation_key(self) -> VaultCredentialSpec:
        if _RESERVED_VARIABLE.match(self.name):
            raise ValueError(f"vault credential {self.name} uses a reserved variable name")
        if self.source_env in ORGANISATION_KEY_VARIABLES:
            raise ValueError(f"vault credential {self.name} cannot carry an organisation key")
        return self


class VaultSpec(_PackModel):
    credentials: tuple[VaultCredentialSpec, ...] = ()

    @model_validator(mode="after")
    def _distinct(self) -> VaultSpec:
        names = [credential.name for credential in self.credentials]
        if len(set(names)) != len(names):
            raise ValueError("vault credential names must be distinct")
        return self


class PackDocument(_PackModel):
    schema_version: Literal["mc.hosted_pack.codex_agents.v1"]
    application: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    lane_profile: Literal["codex_agents"]
    # The Sandbox Host placement is funding-gated (DECISIONS R31).
    tool_placement: Literal["openai_hosted"]
    data_class: DataClass
    task_queue: str = Field(min_length=1)
    agent: AgentSpec
    environment: EnvironmentSpec
    vault: VaultSpec = VaultSpec()

    @model_validator(mode="after")
    def _admissible(self) -> PackDocument:
        issue = admit_data_class(self.lane_profile, self.data_class)
        if issue is not None:
            raise ValueError(issue.message)
        network = self.environment.network
        if self.vault.credentials and network.access == "disabled":
            raise ValueError("vault credentials need network access (SPEC-06 section 5.1)")
        if network.access == "restricted":
            for credential in self.vault.credentials:
                unreachable = sorted(set(credential.allowed_hosts) - set(network.allowed_domains))
                if unreachable:
                    raise ValueError(
                        f"vault credential {credential.name} targets {', '.join(unreachable)}, "
                        "which the network policy does not allow"
                    )
        return self


@dataclass(frozen=True)
class InlineBundle:
    """A skill or plugin directory inlined into the template as a base64 ZIP."""

    name: str
    description: str
    files: tuple[tuple[str, bytes], ...]
    digest: str
    top_directory: bool

    def archive(self) -> bytes:
        """A byte-stable ZIP: sorted entries, fixed timestamps and modes."""

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, content in self.files:
                entry = zipfile.ZipInfo(f"{self.name}/{path}" if self.top_directory else path)
                entry.date_time = _ZIP_TIME
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o644 << 16
                archive.writestr(entry, content)
        return buffer.getvalue()

    def inline_param(self) -> dict[str, Any]:
        return {
            "type": "inline",
            "name": self.name,
            "description": self.description,
            "source": {
                "type": "base64",
                "media_type": "application/zip",
                "data": base64.b64encode(self.archive()).decode("ascii"),
            },
        }

    def identity(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description, "digest": self.digest}


def _digest_hex(digest: str, length: int) -> str:
    return digest.removeprefix("sha256:")[:length]


@dataclass(frozen=True)
class CodexAgentsPack:
    """A loaded pack: the validated document, the rendered instructions and the inline bundles,
    with the request bodies and digests derived from them."""

    document: PackDocument
    instructions: str
    skills: tuple[InlineBundle, ...]
    plugins: tuple[InlineBundle, ...]
    secret_declarations: tuple[SecretDeclaration, ...] = ()

    @property
    def application(self) -> str:
        return self.document.application

    @cached_property
    def agent_config(self) -> dict[str, Any]:
        """The saved agent body without its metadata."""

        agent = self.document.agent
        tools: list[dict[str, Any]] = [
            {"type": "function", **tool.model_dump()} for tool in agent.function_tools
        ]
        tools += [
            {
                "type": "mcp",
                "server_label": server.server_label,
                "transport": {"type": "http", "server_url": server.server_url},
                "required": server.required,
                **({"allowed_tools": list(server.allowed_tools)} if server.allowed_tools else {}),
            }
            for server in agent.mcp_servers
        ]
        body: dict[str, Any] = {
            "name": agent.name,
            "model": agent.model,
            "instructions": self.instructions,
            "tools": tools,
            "multi_agent": {"enabled": agent.multi_agent},
        }
        if agent.reasoning_effort is not None:
            body["reasoning"] = {"effort": agent.reasoning_effort}
        if agent.service_tier is not None:
            body["service_tier"] = agent.service_tier
        return body

    @cached_property
    def agent_digest(self) -> str:
        return sha256_digest(self.agent_config)

    def _template_config(self) -> dict[str, Any]:
        environment = self.document.environment
        return {
            "network": environment.network.model_dump(),
            "packages": environment.packages.model_dump(),
            "setup_commands": [
                command.model_dump(exclude_none=True) for command in environment.setup_commands
            ],
            "env": environment.env,
        }

    @cached_property
    def template_digest(self) -> str:
        return sha256_digest(
            {
                **self._template_config(),
                "skills": [skill.identity() for skill in self.skills],
                "plugins": [plugin.identity() for plugin in self.plugins],
            }
        )

    @property
    def template_name(self) -> str:
        """The template's provider name, which carries its digest: templates take no metadata."""

        return f"mc-{self.application}-{_digest_hex(self.template_digest, 16)}"

    def template_body(self) -> dict[str, Any]:
        config = self._template_config()
        network = config["network"]
        if not network["allowed_domains"]:
            del network["allowed_domains"]
        return {
            "name": self.template_name,
            **config,
            "skills": [skill.inline_param() for skill in self.skills],
            "plugins": [plugin.inline_param() for plugin in self.plugins],
        }

    @cached_property
    def secret_set_digest(self) -> str:
        """Over the credential declarations only; values never enter a digest."""

        return sha256_digest([item.model_dump() for item in self.document.vault.credentials])

    @cached_property
    def digest(self) -> str:
        """The pack (materialization) digest: one saved agent exists per value."""

        return sha256_digest(
            {
                "schema_version": self.document.schema_version,
                "application": self.application,
                "agent": self.agent_digest,
                "template": self.template_digest,
                "secret_set": self.secret_set_digest,
                "container_size": self.document.environment.container_size,
            }
        )


def _read_text(directory: Path, relative: str) -> str:
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise PackError(f"pack file {relative} is missing or outside the pack")
    return path.read_text(encoding="utf-8").strip()


def _render_instructions(directory: Path, agent: AgentSpec) -> str:
    overlay = _read_text(directory, agent.instructions)
    rules = [_read_text(directory, relative) for relative in agent.repo_rules]
    if not rules:
        return overlay
    return "\n\n".join([overlay, "## Repository rules", *rules])


def _skill_identity(files: Mapping[str, bytes], where: str) -> tuple[str, str]:
    text = files[SKILL_FILE].decode("utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    front = yaml.safe_load(match.group(1)) if match else None
    if not isinstance(front, Mapping) or not front.get("name") or not front.get("description"):
        raise PackError(f"{where}/{SKILL_FILE} needs front matter with name and description")
    return str(front["name"]), str(front["description"])


def _plugin_identity(files: Mapping[str, bytes], where: str) -> tuple[str, str]:
    if PLUGIN_FILE not in files:
        raise PackError(f"{where} has no {PLUGIN_FILE}")
    manifest = json.loads(files[PLUGIN_FILE])
    if (
        not isinstance(manifest, Mapping)
        or not manifest.get("name")
        or not manifest.get("description")
    ):
        raise PackError(f"{where}/{PLUGIN_FILE} needs a name and a description")
    return str(manifest["name"]), str(manifest["description"])


def _bundles(directory: Path, relative: str | None, *, plugins: bool) -> tuple[InlineBundle, ...]:
    if relative is None:
        return ()
    root = directory / relative
    if not root.is_dir():
        raise PackError(f"pack directory {relative} is missing")
    bundles: list[InlineBundle] = []
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        where = f"{relative}/{child.name}"
        try:
            files = directory_files(child, require_skill_md=not plugins)
            digest = bundle_digest(files, require_skill_md=not plugins)
        except BundleError as error:
            raise PackError(f"{where}: {error}") from error
        identify = _plugin_identity if plugins else _skill_identity
        name, description = identify(dict(files), where)
        if name != child.name:
            raise PackError(f"{where} declares the name {name}; the directory must match it")
        bundles.append(InlineBundle(name, description, files, digest, top_directory=not plugins))
    return tuple(bundles)


def load_pack(directory: Path) -> CodexAgentsPack:
    """Read and validate a `codex_agents` pack directory."""

    try:
        raw = yaml.safe_load(_read_text(directory, PACK_FILE))
        document = PackDocument.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as error:
        raise PackError(f"{directory / PACK_FILE} is not a valid {PACK_SCHEMA} pack") from error
    return CodexAgentsPack(
        document=document,
        instructions=_render_instructions(directory, document.agent),
        skills=_bundles(directory, document.environment.skills, plugins=False),
        plugins=_bundles(directory, document.environment.plugins, plugins=True),
    )


def pack_directory(deployments: Path, application: str) -> Path:
    """Where an application's `codex_agents` pack lives under `deployments/`."""

    return deployments / "hosted-packs" / application / "codex_agents"


__all__ = [
    "PACK_FILE",
    "PACK_SCHEMA",
    "AgentSpec",
    "CodexAgentsPack",
    "EnvironmentSpec",
    "FunctionTool",
    "InlineBundle",
    "McpServer",
    "NetworkPolicy",
    "PackDocument",
    "PackError",
    "VaultCredentialSpec",
    "load_pack",
    "pack_directory",
]

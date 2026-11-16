"""Digest/revision pins of the search and browser capabilities a deployment mounts (RRM-009).

The pin file (`infra/capability-pins/research-capabilities.json`) is the deployment's frozen
statement of which MCP servers, Agent Skill bundles and tools its workers may materialize:
every entry names the exact definition reference, the module or bundle digest and, for an
MCP server, the exact tool filter with each tool's input-schema digest. Workers refuse any
binding whose digests differ (REQ-CP-DA-005), and `scripts/pin_research_capabilities.py`
is the only writer: it reads the reviewed modules and bundles from the workspace and records
what it observed. Credentials appear only as environment reference names.

An MCP server is pinned in one of three forms (IP-008). `mcp_servers`: a stdio node module
(`PinnedMCPServer`), its entry module hashed and run with the deployment's node.
`remote_mcp_servers`: a remote Streamable HTTP endpoint (`PinnedRemoteMCPServer`); the pin
states the bound tools and the credential's environment name, and the deployment supplies the
URL (`MCP_SERVER_ENDPOINTS`). `executable_mcp_servers`: a stdio executable that is not a node
module (`PinnedExecutableMCPServer`), an absolute path whose bytes are hashed before every
launch, with fixed arguments. `pinned_mcp_component` derives the one exact component a worker
may launch or connect from any of them.

Locators are workspace-relative (`workspace://...`, under `MISSION_CONTROL_WORKSPACE_ROOT`), so the
same pin file is valid on every host that lays the workspace out the same way.

Resource-root contract (`workspace_path`). A locator is lexically safe (no `..`, absolute,
drive, device or ADS spelling) and must resolve, after every link is followed, inside its
containment root:

- for a locator under a declared resource root (`WORKSPACE_RESOURCE_ROOTS`: `.agents`,
  `.tools`), the real path of `<workspace>/<root>`. That top-level entry may be a directory
  link in external layouts, but its target must keep the resource root's name, and
  nothing beneath it may resolve outside that target;
- for any other locator, the real path of the workspace itself, so every other link that
  leaves the workspace (including undeclared top-level links) is refused.

The function returns the verified real path, so bundle readers that refuse links in a path
(`directory_files`) read exactly what was checked.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.adapters.capabilities.capability_bundles import (
    BundleError,
    BundleReader,
    DirectoryBundleStore,
    bundle_digest,
    directory_files,
    safe_relative_path,
)
from mission_control.adapters.deep_agents.materializer import ResolvedSkillBundle
from mission_control.bootstrap.settings import PROJECT_ROOT, Settings, get_settings
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef, SecretRef
from mission_control.domain.execution.contracts import (
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
    DeepAgentSkillComponent,
    DeepAgentToolComponent,
)
from mission_control.domain.execution.errors import DeepAgentRuntimeDrift

DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
ENV_NAME_PATTERN = r"^[A-Z][A-Z0-9_]*$"
WORKSPACE_SCHEME = "workspace://"
PIN_SCHEMA_VERSION: Literal["belllabs.capability-pins.v1"] = "belllabs.capability-pins.v1"
MAX_SKILL_BUNDLE_FILES = 64
MAX_SKILL_FILE_BYTES = 256_000
# Top-level workspace entries that may be relocated behind a directory link (see module
# docstring). Adding a name here widens what a pin file can address; it is a reviewed change.
WORKSPACE_RESOURCE_ROOTS: frozenset[str] = frozenset({".agents", ".tools"})


class CapabilityPinError(ValueError):
    """The pin file is malformed, or the workspace artifact differs from its pin."""


class PinnedExactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DefinitionKind
    logical_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    digest: str = Field(pattern=DIGEST_PATTERN)

    def as_ref(self) -> ExactDefinitionRef:
        return ExactDefinitionRef(
            kind=self.kind, logical_id=self.logical_id, revision=self.revision, digest=self.digest
        )


class PinnedMCPTool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(min_length=1)
    schema_digest: str = Field(pattern=DIGEST_PATTERN)


class PinnedMCPServer(BaseModel):
    """One stdio MCP server run as a worker-side subprocess with a sanitized environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    server_id: str = Field(min_length=1)
    server_name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    ref: PinnedExactRef
    package_name: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    module_locator: str = Field(pattern=r"^workspace://.+")
    module_digest: str = Field(pattern=DIGEST_PATTERN)
    schema_digest: str = Field(pattern=DIGEST_PATTERN)
    credential_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    tools: tuple[PinnedMCPTool, ...] = Field(min_length=1)

    def module_path(self) -> Path:
        return workspace_path(self.module_locator)

    def verify_module(self) -> Path:
        module = self.module_path()
        try:
            content = module.read_bytes()
        except OSError as error:
            raise CapabilityPinError(
                f"pinned MCP module is unavailable: {self.module_locator}"
            ) from error
        if "sha256:" + sha256(content).hexdigest() != self.module_digest:
            raise CapabilityPinError(
                f"pinned MCP module {self.package_name} differs from its reviewed digest"
            )
        package_path = module.parent.parent / "package.json"
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CapabilityPinError(
                f"pinned MCP package metadata is unavailable: {self.package_name}"
            ) from error
        if (
            package.get("name") != self.package_name
            or package.get("version") != self.package_version
        ):
            raise CapabilityPinError(
                f"{self.package_name} must be pinned to {self.package_version}"
            )
        return module

    def component(
        self, *, node_executable: Path, attachment_target: str = "agent.main"
    ) -> DeepAgentMCPServerComponent:
        """The exact Deep Agent MCP component: stdio through the pinned node module."""

        module = self.verify_module()
        return DeepAgentMCPServerComponent(
            ref=self.ref.as_ref(),
            server_name=self.server_name,
            transport="stdio",
            command=str(node_executable.resolve(strict=True)),
            arguments=(str(module),),
            credential_refs=(
                (SecretRef(provider="environment", key=self.credential_env),)
                if self.credential_env is not None
                else ()
            ),
            tools=tuple(
                DeepAgentMCPToolComponent(
                    tool_name=tool.tool_name, schema_digest=tool.schema_digest
                )
                for tool in self.tools
            ),
            schema_digest=self.schema_digest,
            attachment_target=attachment_target,
        )


def _bound_tools(tools: tuple[PinnedMCPTool, ...]) -> tuple[DeepAgentMCPToolComponent, ...]:
    return tuple(
        DeepAgentMCPToolComponent(tool_name=tool.tool_name, schema_digest=tool.schema_digest)
        for tool in tools
    )


def _credential_refs(names: tuple[str, ...]) -> tuple[SecretRef, ...]:
    return tuple(SecretRef(provider="environment", key=name) for name in names)


def remote_endpoint(server_id: str, endpoint: str | None) -> str:
    """The deployment-supplied endpoint of a pinned remote server, or a refusal that names it.

    A pin file is the same on every host, so it never states a URL: the deployment does
    (`MCP_SERVER_ENDPOINTS`, keyed by the pin's `server_id`). The URL is `http` or `https`
    with a host, and carries no credentials or fragment: the credential travels only as the
    `Authorization` header the pin's `credential_env` names.
    """

    if not endpoint:
        raise CapabilityPinError(
            f"pinned remote MCP server {server_id} has no endpoint in this deployment "
            f"(MCP_SERVER_ENDPOINTS[{server_id!r}])"
        )
    try:
        parts = urlsplit(endpoint)
        host = parts.hostname
    except ValueError:
        parts, host = None, None
    if (
        parts is None
        or parts.scheme not in ("http", "https")
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise CapabilityPinError(
            f"the endpoint of pinned remote MCP server {server_id} must be an http(s) URL with a "
            "host and without credentials or a fragment"
        )
    return endpoint


class PinnedRemoteMCPServer(BaseModel):
    """One remote Streamable HTTP MCP server a worker connects to (IP-008).

    Nothing is launched: the worker opens a session to the endpoint the deployment supplies
    for `server_id` and sends `credential_env`'s value as `Authorization: Bearer`. What the pin
    fixes is what the agent may be handed: the bound tools with their input-schema digests,
    and whether the server may list more (`tool_filter`, IP-009). `source` names the reviewed
    server build the tool list was captured from, for disclosure only.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    server_id: str = Field(min_length=1)
    server_name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    ref: PinnedExactRef
    source: str = Field(min_length=1)
    transport: Literal["streamable_http"] = "streamable_http"
    schema_digest: str = Field(pattern=DIGEST_PATTERN)
    credential_env: str | None = Field(default=None, pattern=ENV_NAME_PATTERN)
    tool_filter: Literal["exact", "allowlist"] = "exact"
    tools: tuple[PinnedMCPTool, ...] = Field(min_length=1)

    def component(
        self, *, endpoint: str | None, attachment_target: str = "agent.main"
    ) -> DeepAgentMCPServerComponent:
        """The exact Deep Agent MCP component at the deployment's endpoint."""

        return DeepAgentMCPServerComponent(
            ref=self.ref.as_ref(),
            server_name=self.server_name,
            transport=self.transport,
            endpoint=remote_endpoint(self.server_id, endpoint),
            credential_refs=_credential_refs(
                (self.credential_env,) if self.credential_env is not None else ()
            ),
            tools=_bound_tools(self.tools),
            schema_digest=self.schema_digest,
            attachment_target=attachment_target,
            tool_filter=self.tool_filter,
        )


class PinnedExecutableMCPServer(BaseModel):
    """One stdio MCP server that is a native executable, not a node module (IP-008).

    `command` is the executable's absolute path on the worker and `command_digest` the sha256
    of its bytes, re-read before every launch. `arguments` are fixed and passed as a list:
    no shell is involved. The subprocess receives the credentials `credential_envs` name and
    the MCP client's default sanitized environment, nothing else.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    server_id: str = Field(min_length=1)
    server_name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    ref: PinnedExactRef
    package_name: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    command: str = Field(min_length=1)
    command_digest: str = Field(pattern=DIGEST_PATTERN)
    arguments: tuple[str, ...] = ()
    schema_digest: str = Field(pattern=DIGEST_PATTERN)
    credential_envs: tuple[Annotated[str, Field(pattern=ENV_NAME_PATTERN)], ...] = ()
    tool_filter: Literal["exact", "allowlist"] = "exact"
    tools: tuple[PinnedMCPTool, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def absolute_command_and_plain_arguments(self) -> PinnedExecutableMCPServer:
        absolute = (
            PurePosixPath(self.command).is_absolute() or PureWindowsPath(self.command).is_absolute()
        )
        if not absolute or "\x00" in self.command:
            raise ValueError(
                f"pinned MCP executable {self.server_id} needs an absolute command path"
            )
        if any("\x00" in argument for argument in self.arguments):
            raise ValueError(f"pinned MCP executable {self.server_id} has a malformed argument")
        if len(set(self.credential_envs)) != len(self.credential_envs):
            raise ValueError(f"pinned MCP executable {self.server_id} names a credential twice")
        return self

    def verify_executable(self) -> Path:
        """The executable, after its bytes were hashed and found equal to `command_digest`."""

        executable = Path(self.command)
        try:
            if not executable.is_absolute():
                raise OSError("the pinned command path is not absolute on this host")
            observed = _file_sha256(executable)
        except OSError as error:
            raise CapabilityPinError(
                f"pinned MCP executable {self.server_id} is unavailable at {self.command}"
            ) from error
        if observed != self.command_digest:
            raise CapabilityPinError(
                f"pinned MCP executable {self.server_id} at {self.command} has digest "
                f"{observed}, not its pinned command_digest {self.command_digest}"
            )
        return executable

    def component(self, *, attachment_target: str = "agent.main") -> DeepAgentMCPServerComponent:
        """The exact Deep Agent MCP component: stdio through the verified executable."""

        self.verify_executable()
        return DeepAgentMCPServerComponent(
            ref=self.ref.as_ref(),
            server_name=self.server_name,
            transport="stdio",
            command=self.command,
            arguments=self.arguments,
            credential_refs=_credential_refs(self.credential_envs),
            tools=_bound_tools(self.tools),
            schema_digest=self.schema_digest,
            attachment_target=attachment_target,
            tool_filter=self.tool_filter,
        )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


type AnyPinnedMCPServer = PinnedMCPServer | PinnedRemoteMCPServer | PinnedExecutableMCPServer


class PinnedSkill(BaseModel):
    """One Agent Skill bundle read from the workspace `.agents/skills/<name>` directory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: PinnedExactRef
    skill_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    source_locator: str = Field(pattern=r"^(workspace|capability-bundles)://.+")
    digest_format: Literal["legacy_text_v1", "bytes_v1"] = "legacy_text_v1"
    bundle_digest: str = Field(pattern=DIGEST_PATTERN)
    skill_md_digest: str = Field(pattern=DIGEST_PATTERN)
    mount_root: str = Field(pattern=r"^/.*[^/]$")

    @property
    def manifest_digest(self) -> str:
        return self.bundle_digest

    def bundle(self, *, store: BundleReader | None = None) -> ResolvedSkillBundle:
        if self.source_locator.startswith("capability-bundles://"):
            selected_store = store or DirectoryBundleStore(
                PROJECT_ROOT / ".runtime" / "capability-bundles"
            )
            try:
                manifest, files = selected_store.load(
                    self.source_locator.removeprefix("capability-bundles://")
                )
                if (manifest.asset_id, manifest.version) != (
                    self.ref.logical_id,
                    self.ref.revision,
                ):
                    raise BundleError("pinned skill version differs from stored manifest")
                if self.digest_format != "bytes_v1":
                    raise BundleError("stored bundles require bytes_v1 digests")
                bundle = ResolvedSkillBundle(manifest.bundle_digest, files, "bytes_v1")
            except (ValueError, OSError) as error:
                raise CapabilityPinError(str(error)) from error
        else:
            bundle = read_skill_bundle(
                workspace_path(self.source_locator), digest_format=self.digest_format
            )
        if bundle.bundle_digest != self.bundle_digest:
            raise CapabilityPinError(
                f"Skill bundle {self.skill_name} differs from its pinned bundle digest"
            )
        try:
            bundle.verify(skill_md_digest=self.skill_md_digest)
        except DeepAgentRuntimeDrift as error:
            raise CapabilityPinError(str(error)) from error
        return bundle

    def component(self, *, attachment_target: str = "agent.main") -> DeepAgentSkillComponent:
        return DeepAgentSkillComponent(
            ref=self.ref.as_ref(),
            skill_name=self.skill_name,
            bundle_digest=self.bundle_digest,
            skill_md_digest=self.skill_md_digest,
            mount_root=self.mount_root,
            attachment_target=attachment_target,
        )


class PinnedTool(BaseModel):
    """One exact host tool (today: the agent-browser page tool over the pinned CLI)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: PinnedExactRef
    tool_name: str = Field(min_length=1)
    kind: Literal["agent_browser_page"]
    schema_digest: str = Field(pattern=DIGEST_PATTERN)
    entrypoint_locator: str = Field(pattern=r"^workspace://.+")
    entrypoint_digest: str = Field(pattern=DIGEST_PATTERN)
    package_version: str = Field(min_length=1)

    def verify_entrypoint(self) -> Path:
        entrypoint = workspace_path(self.entrypoint_locator)
        try:
            content = entrypoint.read_bytes()
        except OSError as error:
            raise CapabilityPinError(
                f"pinned tool entrypoint is unavailable: {self.entrypoint_locator}"
            ) from error
        if "sha256:" + sha256(content).hexdigest() != self.entrypoint_digest:
            raise CapabilityPinError(
                f"pinned tool entrypoint {self.tool_name} differs from its reviewed digest"
            )
        return entrypoint

    def component(self, *, attachment_target: str = "agent.main") -> DeepAgentToolComponent:
        return DeepAgentToolComponent(
            ref=self.ref.as_ref(),
            tool_name=self.tool_name,
            schema_digest=self.schema_digest,
            attachment_target=attachment_target,
        )


class PinnedModel(BaseModel):
    """An exact model definition the deployment serves, with the vendor and model id it serves.

    OC-R6: both are authoritative and enforced. A Deep Agents model binding whose Model Catalog
    row names another vendor or model id is refused at composition, readiness and by the
    worker's factory (`MODEL_PIN_VENDOR_MISMATCH`, `MODEL_PIN_MODEL_MISMATCH`). The
    `model.wp-cp-040` pin is the WP-CP-040 qualification slot (model id `fixture-model`, served
    by deterministic cognition in tests); no installed catalog row binds it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: PinnedExactRef
    provider: Literal["openai", "anthropic"]
    model_id: str = Field(min_length=1, max_length=256)


class PinnedSandbox(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: PinnedExactRef
    backend: Literal["state", "docker", "langsmith"]


class PinnedPersistence(BaseModel):
    """A checkpointer or store definition served by the deployment's persistent saver/store."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: PinnedExactRef
    # 1.4.4 (P6.2): filled at composition from the bound conninfo (`saver_locator_digest`),
    # never written into the pins file by hand.
    locator_digest: str | None = None


class CapabilityPins(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["belllabs.capability-pins.v1"] = PIN_SCHEMA_VERSION
    mcp_servers: tuple[PinnedMCPServer, ...] = ()
    # IP-008: the two other forms of MCP server a worker serves. Absent from a pin file
    # written before them, which reads unchanged.
    remote_mcp_servers: tuple[PinnedRemoteMCPServer, ...] = ()
    executable_mcp_servers: tuple[PinnedExecutableMCPServer, ...] = ()
    skills: tuple[PinnedSkill, ...] = ()
    tools: tuple[PinnedTool, ...] = ()
    models: tuple[PinnedModel, ...] = ()
    sandboxes: tuple[PinnedSandbox, ...] = ()
    checkpointers: tuple[PinnedPersistence, ...] = ()
    stores: tuple[PinnedPersistence, ...] = ()

    @classmethod
    def load(cls, path: Path) -> CapabilityPins:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CapabilityPinError(f"capability pins are unavailable: {path}") from error
        pins = cls.model_validate(payload)
        servers = pins.all_mcp_servers
        for what, values in (
            ("an MCP server", [item.server_id for item in servers]),
            ("an MCP server name", [item.server_name for item in servers]),
            ("an MCP server definition digest", [item.ref.digest for item in servers]),
        ):
            if len(values) != len(set(values)):
                raise CapabilityPinError(f"capability pins name {what} twice")
        return pins

    @property
    def all_mcp_servers(self) -> tuple[AnyPinnedMCPServer, ...]:
        """Every pinned MCP server, whatever its form: node module, remote, executable."""

        return (*self.mcp_servers, *self.remote_mcp_servers, *self.executable_mcp_servers)

    def pinned_mcp_server(self, server_id: str) -> AnyPinnedMCPServer:
        for server in self.all_mcp_servers:
            if server.server_id == server_id:
                return server
        raise CapabilityPinError(f"MCP server {server_id} is not pinned")

    def mcp_component(
        self,
        server_id: str,
        *,
        node_executable: Path | None,
        endpoints: Mapping[str, str] | None = None,
        attachment_target: str = "agent.main",
    ) -> DeepAgentMCPServerComponent:
        """The exact component of one pinned server, verified for its form."""

        return pinned_mcp_component(
            self.pinned_mcp_server(server_id),
            node_executable=node_executable,
            endpoints=endpoints,
            attachment_target=attachment_target,
        )

    @classmethod
    def empty(cls) -> CapabilityPins:
        return cls()

    @classmethod
    def from_settings(cls, settings: Settings, *, required: bool = True) -> CapabilityPins:
        """The deployment's pins. The production compositions (launch-enabled workers, the
        Temporal-enabled API) require the file: a missing pin file fails closed instead of
        silently mounting nothing (RRM-009 review). `required=False` is for tooling only."""

        path = settings.capability_pins_path
        if path.exists():
            return cls.load(path)
        if required:
            raise CapabilityPinError(f"capability pins are required but absent: {path}")
        return cls.empty()

    def mcp_server(self, server_id: str) -> PinnedMCPServer:
        for server in self.mcp_servers:
            if server.server_id == server_id:
                return server
        raise CapabilityPinError(f"MCP server {server_id} is not pinned")

    def skill(self, skill_name: str) -> PinnedSkill:
        for skill in self.skills:
            if skill.skill_name == skill_name:
                return skill
        raise CapabilityPinError(f"Skill {skill_name} is not pinned")

    def tool(self, tool_name: str) -> PinnedTool:
        for tool in self.tools:
            if tool.tool_name == tool_name:
                return tool
        raise CapabilityPinError(f"tool {tool_name} is not pinned")

    def mcp_schema_digests(self) -> dict[str, str]:
        return {server.server_id: server.schema_digest for server in self.all_mcp_servers}

    def asset_manifest_digests(self) -> dict[str, str]:
        return {
            f"{skill.ref.kind.value}:{skill.ref.logical_id}:{skill.ref.revision}": (
                skill.manifest_digest
            )
            for skill in self.skills
        }

    def disclosure(self) -> dict[str, object]:
        """A secret-free record of the mounted capabilities for sanitized lineage."""

        return {
            "schema_version": self.schema_version,
            "mcp_servers": [
                {
                    "server_id": server.server_id,
                    "ref": server.ref.model_dump(mode="json"),
                    "package": f"{server.package_name}@{server.package_version}",
                    "module_locator": server.module_locator,
                    "module_digest": server.module_digest,
                    "schema_digest": server.schema_digest,
                    "credential_ref": (
                        f"environment:{server.credential_env}"
                        if server.credential_env is not None
                        else None
                    ),
                    "tools": [tool.model_dump(mode="json") for tool in server.tools],
                    "egress": "worker_mediated_stdio_subprocess",
                }
                for server in self.mcp_servers
            ],
            **(
                {
                    "remote_mcp_servers": [
                        {
                            "server_id": server.server_id,
                            "ref": server.ref.model_dump(mode="json"),
                            "source": server.source,
                            "transport": server.transport,
                            "endpoint": f"deployment:MCP_SERVER_ENDPOINTS[{server.server_id}]",
                            "schema_digest": server.schema_digest,
                            "credential_ref": (
                                f"environment:{server.credential_env}"
                                if server.credential_env is not None
                                else None
                            ),
                            "tool_filter": server.tool_filter,
                            "tools": [tool.model_dump(mode="json") for tool in server.tools],
                            "egress": "worker_remote_session",
                        }
                        for server in self.remote_mcp_servers
                    ]
                }
                if self.remote_mcp_servers
                else {}
            ),
            **(
                {
                    "executable_mcp_servers": [
                        {
                            "server_id": server.server_id,
                            "ref": server.ref.model_dump(mode="json"),
                            "package": f"{server.package_name}@{server.package_version}",
                            "command": server.command,
                            "command_digest": server.command_digest,
                            "arguments": list(server.arguments),
                            "schema_digest": server.schema_digest,
                            "credential_refs": [
                                f"environment:{name}" for name in server.credential_envs
                            ],
                            "tool_filter": server.tool_filter,
                            "tools": [tool.model_dump(mode="json") for tool in server.tools],
                            "egress": "worker_mediated_stdio_subprocess",
                        }
                        for server in self.executable_mcp_servers
                    ]
                }
                if self.executable_mcp_servers
                else {}
            ),
            "skills": [skill.model_dump(mode="json") for skill in self.skills],
            "tools": [tool.model_dump(mode="json") for tool in self.tools],
        }


def pinned_mcp_component(
    pin: AnyPinnedMCPServer,
    *,
    node_executable: Path | None,
    endpoints: Mapping[str, str] | None = None,
    attachment_target: str = "agent.main",
) -> DeepAgentMCPServerComponent:
    """The exact component a pin describes, after the verification its form requires: the
    node module's digest and package metadata, the executable's digest, or the presence and
    shape of the deployment's endpoint. Raises `CapabilityPinError` naming the fact."""

    if isinstance(pin, PinnedRemoteMCPServer):
        return pin.component(
            endpoint=(endpoints or {}).get(pin.server_id), attachment_target=attachment_target
        )
    if isinstance(pin, PinnedExecutableMCPServer):
        return pin.component(attachment_target=attachment_target)
    if node_executable is None:
        raise CapabilityPinError(
            f"pinned node-module MCP server {pin.server_id} requires the deployment's node "
            "(WEB_RESEARCH_AGENT_BROWSER_NODE)"
        )
    return pin.component(node_executable=node_executable, attachment_target=attachment_target)


def workspace_root() -> Path:
    """The configured capability resource owner (`Settings.workspace_root`, `.env`
    applies); a typed `InstallationDefaultUnavailable` when nothing names one."""

    return get_settings().workspace_root


def workspace_path(locator: str, *, root: Path | None = None) -> Path:
    """The verified real path of a `workspace://` locator under `root` (default: the
    configured resource owner). Enforces the resource-root contract in the module docstring."""

    if not locator.startswith(WORKSPACE_SCHEME):
        raise CapabilityPinError(f"locator is not workspace-relative: {locator}")
    raw = locator.removeprefix(WORKSPACE_SCHEME)
    base = workspace_root() if root is None else root
    try:
        parts = PurePosixPath(safe_relative_path(raw)).parts
        workspace = base.resolve()
        containment = workspace
        if parts[0] in WORKSPACE_RESOURCE_ROOTS:
            containment = (base / parts[0]).resolve()
            relocated = not containment.is_relative_to(workspace)
            if relocated and containment.name != parts[0]:
                raise BundleError("resource root links to a directory of another name")
        result = base.joinpath(*parts).resolve()
        if not result.is_relative_to(containment):
            raise BundleError("locator escapes its containment root through a link")
    except (BundleError, OSError, RuntimeError) as error:
        raise CapabilityPinError(f"locator escapes or aliases the workspace: {locator}") from error
    return result


def read_skill_bundle(
    directory: Path, *, digest_format: Literal["legacy_text_v1", "bytes_v1"] = "legacy_text_v1"
) -> ResolvedSkillBundle:
    """Read complete directory bytes; legacy pins keep their original digest algorithm."""
    try:
        files = directory_files(directory)
        if digest_format == "bytes_v1":
            digest = bundle_digest(files)
        else:
            manifest = [
                {
                    "path": relative,
                    "digest": sha256_digest(content.decode("utf-8")),
                    "size_bytes": len(content),
                }
                for relative, content in files
            ]
            digest = sha256_digest(manifest)
    except (ValueError, OSError) as error:
        raise CapabilityPinError(str(error)) from error
    return ResolvedSkillBundle(bundle_digest=digest, files=files, digest_format=digest_format)

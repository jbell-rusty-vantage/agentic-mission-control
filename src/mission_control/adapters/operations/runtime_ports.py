"""Deployment implementations of the operation-boundary ports (RRM-009, CP-050 prerequisite).

`OperationExecutionService` is composed from ports. The conformance adapters in
`conformance_operation_runtime.py` qualify the service's invariants; these are the
deployment's own: credential references resolved from the worker environment (values
never enter a binding, a record or a log; the Secret Broker serves them in the composed
worker, MO-11) and the launch variables a lane binding names through them, a
content-addressed artifact payload store on a shared directory for deployments without an
object-store bucket, an event sink that records only identities, and an asset verifier
bound to the deployment's digest pins.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from mission_control.adapters.capabilities.capability_pins import CapabilityPinError, CapabilityPins
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.execution.operations.operation_execution import (
    SecretResolutionPort,
)
from mission_control.application.secrets.broker import SecretUnavailable
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import SecretRef
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    DeepAgentMCPServerComponent,
    OperationExecutionBinding,
)
from mission_control.domain.execution.errors import WorkspaceDigestMismatch

logger = logging.getLogger(__name__)

FILE_ARTIFACT_SCHEME = "file-artifacts://"
_ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SecretReferenceUnavailable(SecretUnavailable):
    """A declared credential reference has no value in this deployment."""


class EnvironmentSecretResolver:
    """Resolve `environment:` credential references from the worker process environment.

    Only the `environment` provider is served; a reference to another provider is refused
    here so that a missing secrets backend never degrades into an ambient lookup. Resolved
    values are returned to the caller only; they are never logged or persisted.
    """

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = environment if environment is not None else os.environ

    async def resolve(self, refs: tuple[SecretRef, ...]) -> Mapping[str, str]:
        resolved: dict[str, str] = {}
        for ref in refs:
            key = f"{ref.provider}:{ref.key}"
            if ref.provider != "environment":
                raise SecretReferenceUnavailable(
                    f"secret provider {ref.provider!r} is not composed in this deployment"
                )
            value = self._environment.get(ref.key, "")
            if not value:
                raise SecretReferenceUnavailable(
                    f"credential reference {key} has no value in the worker environment"
                )
            resolved[key] = value
        return resolved


def env_var_refs(env_vars_ref: str) -> tuple[SecretRef, ...]:
    """`<provider>:<NAME>[,<NAME>...]` (for example `environment:LOG_LEVEL,FIRECRAWL_API_KEY`)
    to one reference per variable, keyed by the variable's own name."""

    provider, separator, listed = env_vars_ref.partition(":")
    names = [name.strip() for name in listed.split(",")]
    if (
        not separator
        or not all(_ENV_VAR_NAME.fullmatch(name) for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError(
            "env_vars_ref is <provider>:<NAME>[,<NAME>...] with distinct variable names, "
            "e.g. environment:LOG_LEVEL,FIRECRAWL_API_KEY"
        )
    return tuple(SecretRef.model_validate({"provider": provider, "key": name}) for name in names)


class SecretEnvVarsResolver:
    """Resolve a binding's `env_vars_ref` into the variables it names (SPEC-01 section 4).

    Every variable is a credential reference served by the deployment's secret port, so the
    variables come from wherever that port reads: the Secret Broker's sources in the composed
    worker (MO-11), the worker environment under the `EnvironmentSecretResolver`.
    A provider the port does not serve, or a name without a value, refuses the launch.
    """

    def __init__(self, secrets: SecretResolutionPort) -> None:
        self._secrets = secrets

    async def __call__(self, env_vars_ref: str) -> Mapping[str, str]:
        refs = env_var_refs(env_vars_ref)
        resolved = await self._secrets.resolve(refs)
        return {ref.key: resolved[f"{ref.provider}:{ref.key}"] for ref in refs}


class FilesystemArtifactPayloadStore:
    """Content-addressed payloads on a directory every worker and the API can reach.

    The address scheme is `file-artifacts://<sha256>`; bytes are verified against their
    digest on every write and read, and a second write of a different payload to the same
    address is refused. It stands in for `S3ArtifactPayloadStore` when no bucket is set.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    async def stage(
        self,
        *,
        artifact_id: str,
        content: bytes,
        content_digest: str,
        media_type: str,
    ) -> ArtifactPayloadAddress:
        del artifact_id, media_type
        _verify(content, content_digest, len(content))
        path = self._path(content_digest.removeprefix("sha256:"))
        if path.exists():
            if path.read_bytes() != content:
                raise WorkspaceDigestMismatch("content address contains conflicting bytes")
        else:
            staging = path.with_name(path.name + f".{os.getpid()}.staging")
            staging.write_bytes(content)
            staging.replace(path)
        return ArtifactPayloadAddress(
            object_ref=f"{FILE_ARTIFACT_SCHEME}{path.name}",
            content_digest=content_digest,
            size_bytes=len(content),
        )

    async def retrieve(self, address: ArtifactPayloadAddress) -> bytes:
        if not address.object_ref.startswith(FILE_ARTIFACT_SCHEME):
            raise WorkspaceDigestMismatch("artifact belongs to a different object store")
        path = self._path(address.object_ref.removeprefix(FILE_ARTIFACT_SCHEME))
        try:
            content = path.read_bytes()
        except OSError as error:
            raise WorkspaceDigestMismatch("artifact payload is unavailable") from error
        _verify(content, address.content_digest, address.size_bytes)
        return content

    def address_for(self, *, content_digest: str, size_bytes: int) -> ArtifactPayloadAddress:
        path = self._path(content_digest.removeprefix("sha256:"))
        return ArtifactPayloadAddress(
            object_ref=f"{FILE_ARTIFACT_SCHEME}{path.name}",
            content_digest=content_digest,
            size_bytes=size_bytes,
        )

    def _path(self, name: str) -> Path:
        if len(name) != 64 or any(character not in "0123456789abcdef" for character in name):
            raise WorkspaceDigestMismatch("artifact address is not a content digest")
        return self._root / name


class RecordedOperationEventSink:
    """Idempotent operation events keyed by their event key; payload digests only.

    The journaled composition settles usage and effects through run control, so this port
    is reached only by the unjournaled boundary. It never logs payload values.
    """

    def __init__(self) -> None:
        self._digests: dict[str, tuple[str, str]] = {}

    async def publish(self, *, event_key: str, binding_id: str, payload: dict[str, object]) -> None:
        digest = sha256_digest(payload)
        prior = self._digests.get(event_key)
        if prior is not None and prior != (binding_id, digest):
            raise ValueError("event idempotency key has conflicting payload")
        self._digests[event_key] = (binding_id, digest)
        logger.info(
            "operation event recorded",
            extra={"event_key": event_key, "binding_id": binding_id, "payload_digest": digest},
        )


class PinnedCapabilityAssetVerifier:
    """Verify an operation binding's capability assets against the deployment's pins.

    REQ-CP-DA-005: MCP server schema digests and immutable asset (Skill, plugin) manifest
    digests must equal the pinned revision; anything unpinned is refused before any
    provider work. The same object serves `CapabilityAssetPort` and `MCPRuntimePort`.

    RRM-009 review: the worker also verifies what it will *launch*. Every MCP server
    component of the Deep Agent binding must be either a pinned server, re-derived here from
    the pin with the module digest re-read from disk (and the package name/version checked),
    with exactly the pinned command (the deployment's node executable), arguments,
    credential references, tool filter and schema digest; or an exact component the
    deployment registered (`registered_mcp_servers`, full equality; qualification
    harnesses only). A binding that names the pinned schema digest but another command or
    module is refused. Residual: the pin covers the entry module and the package metadata,
    not the package's transitive `node_modules` tree.
    """

    def __init__(
        self,
        pins: CapabilityPins,
        *,
        node_executable: Path | None = None,
        registered_mcp_servers: Mapping[str, DeepAgentMCPServerComponent] | None = None,
    ) -> None:
        self._mcp = dict(pins.mcp_schema_digests())
        self._assets = dict(pins.asset_manifest_digests())
        self._pinned_servers = {server.ref.digest: server for server in pins.mcp_servers}
        self._node_executable = node_executable
        self._registered = dict(registered_mcp_servers or {})

    async def verify(self, binding: OperationExecutionBinding) -> None:
        for server in binding.mcp_servers:
            if self._mcp.get(server.server_id) != server.schema_digest:
                raise ValueError(f"MCP server {server.server_id} is not pinned at this digest")
        for asset in (*binding.skills, *binding.plugins):
            key = f"{asset.ref.kind.value}:{asset.ref.logical_id}:{asset.ref.revision}"
            if self._assets.get(key) != asset.manifest_digest:
                raise ValueError(f"immutable asset {key} is not pinned at this digest")

    async def verify_servers(self, binding: OperationExecutionBinding) -> None:
        await self.verify(binding)
        self.verify_launch(binding)

    def verify_launch(self, binding: OperationExecutionBinding) -> None:
        """Refuse any MCP server launch that is not exactly a pinned or registered one."""

        deep = DeepAgentExecutionBinding.carried_by(binding)
        if deep is None:
            return
        for component in deep.mcp_servers:
            registered = self._registered.get(component.ref.digest)
            if registered is not None:
                if component != registered:
                    raise ValueError(
                        f"MCP server {component.server_name} differs from its registered component"
                    )
                continue
            pin = self._pinned_servers.get(component.ref.digest)
            if pin is None:
                raise ValueError(f"MCP server {component.server_name} is not pinned")
            if self._node_executable is None:
                raise ValueError("a pinned stdio MCP server requires the deployment's node")
            try:
                expected = pin.component(
                    node_executable=self._node_executable,
                    attachment_target=component.attachment_target,
                )
            except (CapabilityPinError, OSError) as error:
                raise ValueError(
                    f"pinned MCP server {component.server_name} failed verification: {error}"
                ) from error
            if component != expected:
                raise ValueError(
                    f"MCP server {component.server_name} launch differs from its pin "
                    "(command, arguments, credentials, tools or schema)"
                )


def _verify(content: bytes, content_digest: str, size_bytes: int) -> None:
    actual = f"sha256:{sha256(content).hexdigest()}"
    if actual != content_digest or len(content) != size_bytes:
        raise WorkspaceDigestMismatch(
            f"artifact payload mismatch: expected {content_digest}, got {actual}"
        )

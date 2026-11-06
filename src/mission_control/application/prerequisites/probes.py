"""Operator-pinned verification bindings; callers can request a check, never supply proof."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.application.authoring.cursor_launch import WorkspaceProvision
from mission_control.application.prerequisites.oauth import OAuthCredentialBinding
from mission_control.application.prerequisites.setup import ProbeResult, ProbeUnavailable
from mission_control.domain.authoring.contracts import ExactDefinitionRef, SecretRef
from mission_control.domain.execution.bindings import AuthPin, ClaudeSdkOptions
from mission_control.domain.execution.lanes import CursorPins, CursorWorkspace
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord, VerificationMethod


class NativeCodexHostIdentity(BaseModel):
    """Public identity observed by the reviewed native host attestor."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace: WorkspaceProvision
    build_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    host_profile: str = Field(min_length=1)
    auth: AuthPin
    cli_version: str = Field(min_length=1)
    cli_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    attestor: str = Field(min_length=1)
    model_id: str = Field(min_length=1)


class NativeCodexEvidenceBinding(NativeCodexHostIdentity):
    """Installation authority pins public host observations, never caller evidence."""

    path: Path
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def absolute_path(self) -> NativeCodexEvidenceBinding:
        if not self.path.is_absolute():
            raise ValueError("native evidence requires an operator-pinned absolute path")
        return self


class NativeClaudeHostIdentity(BaseModel):
    """Selected local SDK host/configuration; no API authentication claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace: WorkspaceProvision
    build_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    host_profile: str = Field(min_length=1)
    auth: AuthPin
    cli_version: str = Field(min_length=1)
    cli_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    attestor: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    sdk_version: str = Field(min_length=1)
    auth_route: Literal["api_key"]
    provider_options: ClaudeSdkOptions
    agent_profile_ref: ExactDefinitionRef
    host_configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class NativeClaudeEvidenceBinding(NativeClaudeHostIdentity):
    path: Path
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def absolute_path(self) -> NativeClaudeEvidenceBinding:
        if not self.path.is_absolute():
            raise ValueError("native evidence requires an operator-pinned absolute path")
        return self


class NativeCursorConfiguration(BaseModel):
    """Existing sealed Cursor subset; auth/host are separate admission identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    pins: CursorPins
    model_id: str = Field(min_length=1)
    workspace: CursorWorkspace
    mode: Literal["agent", "plan"]
    sandbox_enabled: bool
    disallowed_tools: tuple[str, ...]
    hook_callback_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class NativeCursorHostIdentity(BaseModel):
    """Public selected host identity; no authentication or model-entitlement claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace: WorkspaceProvision
    build_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    host_profile: str = Field(min_length=1)
    host_configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    auth: AuthPin
    auth_route: Literal["api_key"]
    agent_profile_ref: ExactDefinitionRef
    cursor_configuration: NativeCursorConfiguration
    attestor: str = Field(min_length=1)
    observed_repository_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    git_executable: Path
    git_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    node_version: Literal["v24.5.0"]
    node_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    bridge_archive_version: Literal["1.0.0"]
    bridge_archive_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sdk_closure_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    loader_closure_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class NativeCursorEvidenceBinding(NativeCursorHostIdentity):
    path: Path
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def absolute_path(self) -> NativeCursorEvidenceBinding:
        if not self.path.is_absolute():
            raise ValueError("native evidence requires an operator-pinned absolute path")
        return self


class OwnerProbeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_scope: str
    prerequisite_id: str
    definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    operation: Literal[
        "managed_agents_access",
        "agents_api_access",
        "github_readonly_repository",
        "broker_names",
        "signed_webhook",
        "exercised_environment",
        "signal_receipt",
        "github_publication_repository",
        "managed_mcp_oauth",
        "codex_native_auth",
        "codex_native_cli",
        "claude_native_host",
        "cursor_native_host",
    ]
    credentials: tuple[SecretRef, ...] = ()
    oauth_credentials: tuple[OAuthCredentialBinding, ...] = Field(default=(), max_length=20)
    repository: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    run_key: str | None = None
    binding_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    provider_binding_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    auth: AuthPin | None = None
    repo_url: str | None = None
    repo_ref: str | None = None
    repo_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,64}$")
    max_age_seconds: int = Field(default=86400, ge=60, le=2592000)
    native_codex: NativeCodexEvidenceBinding | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    native_claude: NativeClaudeEvidenceBinding | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    native_cursor: NativeCursorEvidenceBinding | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def complete_binding(self) -> OwnerProbeBinding:
        if self.operation == "cursor_native_host":
            if self.native_cursor is None or self.credentials or self.oauth_credentials:
                raise ValueError("native Cursor host proof requires only pinned public evidence")
        elif self.native_cursor is not None:
            raise ValueError("native Cursor evidence is only admitted for its host operation")
        if self.operation == "claude_native_host":
            if self.native_claude is None or self.credentials or self.oauth_credentials:
                raise ValueError("native Claude host proof requires only pinned public evidence")
        elif self.native_claude is not None:
            raise ValueError("native Claude evidence is only admitted for its host operation")
        if self.operation in {"codex_native_auth", "codex_native_cli"}:
            if self.native_codex is None or self.credentials or self.oauth_credentials:
                raise ValueError("native Codex probes require only pinned public host evidence")
        elif self.native_codex is not None:
            raise ValueError("native Codex evidence is only admitted for its native operations")
        if self.oauth_credentials and self.operation != "managed_mcp_oauth":
            raise ValueError(
                "OAuth credentials are only admitted for the OAuth validation operation"
            )
        if self.operation == "managed_mcp_oauth":
            pins = [item.server_pin for item in self.oauth_credentials]
            if not pins or len(pins) != len(set(pins)):
                raise ValueError(
                    "OAuth probe requires one unique credential per selected MCP server"
                )
        if self.operation in {"signed_webhook", "exercised_environment", "signal_receipt"}:
            if not self.run_key or not self.binding_digest:
                raise ValueError("a probe mission must name its run and sealed binding digest")
        elif (
            not self.credentials
            and self.native_codex is None
            and self.native_claude is None
            and self.native_cursor is None
        ):
            raise ValueError("this probe requires an explicit Secret Broker reference")
        if self.operation.startswith("github_") and not self.repository:
            raise ValueError("the repository probe requires an exact owner/repository")
        return self

    @property
    def method(self) -> VerificationMethod:
        if self.operation in {"signed_webhook", "exercised_environment", "signal_receipt"}:
            return VerificationMethod.PROBE_MISSION
        if self.operation in {
            "broker_names",
            "codex_native_auth",
            "codex_native_cli",
            "claude_native_host",
            "cursor_native_host",
        }:
            return VerificationMethod.FILE_CHECK
        return VerificationMethod.API_PROBE


class OwnerProbeConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["mc.owner_probes.v1"] = "mc.owner_probes.v1"
    bindings: tuple[OwnerProbeBinding, ...] = ()

    @model_validator(mode="after")
    def unique(self) -> OwnerProbeConfiguration:
        keys = [(item.request_scope, item.prerequisite_id) for item in self.bindings]
        if len(keys) != len(set(keys)):
            raise ValueError("owner probe bindings are unique per scope and prerequisite")
        return self

    @classmethod
    def load(cls, path: Path) -> OwnerProbeConfiguration:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ProbeObservation:
    evidence_ref: str
    observed_at: datetime


class OwnerProbeExecutor(Protocol):
    async def check(
        self, binding: OwnerProbeBinding, record: OwnerPrerequisiteRecord
    ) -> ProbeObservation:
        """Return a server-issued evidence reference after the concrete check succeeds."""
        ...


class ConfiguredOwnerProbes:
    def __init__(self, configuration: OwnerProbeConfiguration, executor: OwnerProbeExecutor):
        self._bindings = {
            (item.request_scope, item.prerequisite_id): item for item in configuration.bindings
        }
        self._executor = executor

    async def verify(self, request_scope: str, record: OwnerPrerequisiteRecord) -> ProbeResult:
        binding = self._bindings.get((request_scope, record.prerequisite.id))
        if binding is None:
            raise ProbeUnavailable(
                "the installation has no trusted probe binding for this scoped prerequisite; "
                "configure MISSION_CONTROL_OWNER_PROBES_PATH from the current setup report"
            )
        if binding.definition_digest != record.definition_digest:
            raise ProbeUnavailable("the trusted probe binding is stale; review the current setup")
        if binding.method != record.prerequisite.verify.method:
            raise ProbeUnavailable("the configured probe does not satisfy the declared method")
        evidence = await self._executor.check(binding, record)
        expires_at = evidence.observed_at + timedelta(seconds=binding.max_age_seconds)
        now = datetime.now(UTC)
        if evidence.observed_at > now or expires_at <= now:
            raise ProbeUnavailable("the trusted probe observation is stale or in the future")
        return ProbeResult(
            method=binding.method,
            evidence_ref=evidence.evidence_ref,
            expires_at=expires_at,
        )

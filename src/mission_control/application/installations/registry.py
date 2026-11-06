"""Trusted application selection after token verification, before pool selection.

This module never verifies token signatures itself. Authentication adapters pass verified
identity claims; client supplied headers and URLs are not identities or connection strings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.contracts.canonical import canonical_digest
from mission_control.domain.execution.data_class import (
    DEFAULT_DATA_CLASS_POLICY,
    DataClass,
    DataClassPolicy,
    application_policy,
)
from mission_control.domain.execution.lanes import LaneProfileName
from mission_control.domain.execution.session_retention import (
    DEFAULT_SESSION_RETENTION,
    DEFAULT_SESSION_RETENTION_POLICY,
    SessionRetentionPolicy,
)


class HostedAgentApiTerms(BaseModel):
    """One Application's terms on the non-ZDR hosted agent APIs (SPEC-06 section 8): the Data
    Classes it adds to a profile's default admission (never past ``confidential``, so never
    ``phi`` or ``secret``), and how long a session outlives custody before it is deleted."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    widened_data_classes: dict[LaneProfileName, frozenset[DataClass]] = Field(default_factory=dict)
    session_retention_seconds: int = Field(
        default=int(DEFAULT_SESSION_RETENTION.total_seconds()), ge=0
    )

    @model_validator(mode="after")
    def _within_ceiling(self) -> HostedAgentApiTerms:
        application_policy(self.widened_data_classes)
        return self

    @property
    def data_class_policy(self) -> DataClassPolicy:
        return application_policy(self.widened_data_classes)

    @property
    def session_retention(self) -> SessionRetentionPolicy:
        return SessionRetentionPolicy(retention=timedelta(seconds=self.session_retention_seconds))


class ApplicationBindingContent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    application_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    installation_id: UUID
    binding_version: str = Field(min_length=1)
    supabase_project_ref: str = Field(min_length=1)
    database_secret_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    accepted_issuers: frozenset[str] = Field(min_length=1)
    accepted_audiences: frozenset[str] = Field(min_length=1)
    required_component_version: str = Field(min_length=1)
    # HL-18: unset, the Application runs under the hosted agent API defaults.
    hosted_agent_apis: HostedAgentApiTerms | None = None


def _digest_content(content: ApplicationBindingContent) -> dict[str, Any]:
    """The pinned content; an unset optional field stays out of it, so a binding sealed before
    that field existed keeps its digest."""

    return {
        name: value
        for name in ApplicationBindingContent.model_fields
        if (value := getattr(content, name)) is not None
    }


class ApplicationBinding(ApplicationBindingContent):
    binding_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_digest(self) -> ApplicationBinding:
        if self.binding_digest != canonical_digest(_digest_content(self)):
            raise ValueError("application binding digest does not match its content")
        return self

    @property
    def data_class_policy(self) -> DataClassPolicy:
        """The Data Classes this Application's missions may carry onto each lane profile."""

        terms = self.hosted_agent_apis
        return DEFAULT_DATA_CLASS_POLICY if terms is None else terms.data_class_policy

    @property
    def session_retention(self) -> SessionRetentionPolicy:
        """How long this Application's hosted sessions outlive custody."""

        terms = self.hosted_agent_apis
        return DEFAULT_SESSION_RETENTION_POLICY if terms is None else terms.session_retention

    @classmethod
    def seal(cls, **values: Any) -> ApplicationBinding:
        """Build operator configuration with a canonical pin; loading verifies that pin."""
        if "binding_digest" in values:
            raise ValueError("seal computes the binding digest")
        content = ApplicationBindingContent.model_validate(values)
        return cls.model_validate(
            {
                **content.model_dump(mode="python"),
                "binding_digest": canonical_digest(_digest_content(content)),
            }
        )


@dataclass(frozen=True)
class VerifiedApplicationIdentity:
    """Construct only after signature, expiry and current grant verification."""

    issuer: str
    audiences: frozenset[str]
    application_id: str
    installation_id: UUID
    tenant_id: UUID


@dataclass(frozen=True)
class InstallationObservation:
    installation_id: UUID
    application_id: str
    supabase_project_ref: str
    compatible_writer_versions: frozenset[str]


class InstallationUnavailable(ValueError):
    pass


class ApplicationScopeDenied(PermissionError):
    pass


def request_scope(identity: VerifiedApplicationIdentity) -> str:
    return f"mc/{identity.installation_id}/{identity.application_id}/{identity.tenant_id}"


class ApplicationRegistry:
    """Immutable binding registry with separate revocable readiness observations."""

    def __init__(self, bindings: tuple[ApplicationBinding, ...]) -> None:
        validated = tuple(
            ApplicationBinding.model_validate(item.model_dump(mode="python")) for item in bindings
        )
        by_app = {item.application_id: item for item in validated}
        if len(by_app) != len(bindings):
            raise ValueError("duplicate application binding")
        if len({item.installation_id for item in bindings}) != len(bindings):
            raise ValueError("installation cannot be shared between applications")
        self.bindings: Mapping[str, ApplicationBinding] = MappingProxyType(by_app)
        self._available: set[str] = set()

    def observe(self, application_id: str, actual: InstallationObservation) -> None:
        self._available.discard(application_id)
        binding = self.bindings.get(application_id)
        if binding is None or (
            actual.application_id != binding.application_id
            or actual.installation_id != binding.installation_id
            or actual.supabase_project_ref != binding.supabase_project_ref
            or binding.required_component_version not in actual.compatible_writer_versions
        ):
            raise InstallationUnavailable("installation identity or writer compatibility mismatch")
        self._available.add(application_id)

    def disable(self, application_id: str) -> None:
        self._available.discard(application_id)

    def resolve(
        self,
        requested_application: str,
        identity: VerifiedApplicationIdentity,
        *,
        pinned_binding_digest: str | None = None,
    ) -> ApplicationBinding:
        binding = self.bindings.get(requested_application)
        if binding is None or (
            identity.application_id != requested_application
            or identity.installation_id != binding.installation_id
            or identity.issuer not in binding.accepted_issuers
            or not identity.audiences & binding.accepted_audiences
        ):
            raise ApplicationScopeDenied("authenticated application scope denied")
        if requested_application not in self._available:
            raise InstallationUnavailable("application installation is not verified or is disabled")
        if pinned_binding_digest is not None and pinned_binding_digest != binding.binding_digest:
            raise InstallationUnavailable("execution binding does not match deployment pin")
        return binding

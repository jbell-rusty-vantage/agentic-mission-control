"""The trusted invocation origin (OC-D79, design §5): built by the host from the live attempt."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.live_invocation import TEMPLATE_OPERATION_PREFIX

ORIGIN_SCHEMA_VERSION: Final = "mc.invocation_origin.v1"


class MissionIdentityUnavailable(RuntimeError):
    """The live attempt's ledger mission identity cannot be resolved (no locator composed, or
    its run is absent from the request scope): no invocation origin is built (fail closed)."""


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InvocationOrigin(Contract):
    """Who is calling: one live attempt of one operation, never model-supplied JSON.

    The lane adapter constructs it per attempt from the execution binding (SV-01); a template
    operation (``manifest-template/...``) is refused, so no stale launch identity can become
    an origin.
    """

    schema_version: Literal["mc.invocation_origin.v1"] = ORIGIN_SCHEMA_VERSION
    issuer: str = Field(min_length=1)
    installation_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    # Provenance slice 1 (OVE-204): the ledger ``mission_run.mission_id`` and the
    # ``activation.activation_id`` attempt admission recorded for the runtime unit (``None``:
    # the attempt has no runtime unit, e.g. a nested adoption or an operator review).
    activation_id: str | None = Field(default=None, min_length=1)
    operation_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    generation: int = Field(ge=1)
    lane: str = Field(min_length=1)
    parent_invocation_id: str | None = Field(default=None, min_length=1)

    @field_validator("operation_id")
    @classmethod
    def live_operation(cls, value: str) -> str:
        if value.startswith(TEMPLATE_OPERATION_PREFIX):
            raise ValueError("an invocation origin cannot name a launch template operation")
        return value

    @property
    def scope(self) -> tuple[str, str, str]:
        """Installation, application and tenant: the scope effect keys are unique in."""

        return (self.installation_id, self.application_id, self.tenant_id)

    def digest(self) -> str:
        """Canonical content digest; equal origins have equal digests in any process."""

        return sha256_digest(self.model_dump(mode="json"))

    def in_scope_of(self, other: InvocationOrigin) -> bool:
        return self.issuer == other.issuer and self.scope == other.scope


__all__ = ["ORIGIN_SCHEMA_VERSION", "InvocationOrigin", "MissionIdentityUnavailable"]

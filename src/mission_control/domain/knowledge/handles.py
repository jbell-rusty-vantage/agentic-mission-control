"""Qualified knowledge handles and remote operation handles (OC-D89, design §5)."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from mission_control.domain.authoring.canonical import sha256_digest

DIGEST_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
_SEGMENT: Final = r"^[^/@\s]+$"
# A binding pin names its version with `@` ("ai-engineer.research@1") but never a `/`.
_BINDING: Final = r"^[^/\s]+$"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HandleKind(StrEnum):
    REPORT = "report"
    ASSERTION = "assertion"
    ASSERTION_SET = "assertion_set"


class QualifiedHandle(Contract):
    """An exact report/assertion reference resolvable by exactly one binding in one tenant.

    Opaque to the agent; it renders as ``kh:<binding>/<kind>/<id>@<version>``. The digest is
    the exact content digest of that version, so two handles name the same content only when
    binding, kind, id, version and digest all agree.
    """

    kind: HandleKind
    id: str = Field(min_length=1, pattern=_SEGMENT)
    version: str = Field(min_length=1, pattern=_SEGMENT)
    digest: str = Field(pattern=DIGEST_PATTERN)
    tenant_id: str = Field(min_length=1)
    binding: str = Field(min_length=1, pattern=_BINDING)

    def render(self) -> str:
        return f"kh:{self.binding}/{self.kind.value}/{self.id}@{self.version}"

    def identity_digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))


class OperationHandle(Contract):
    """The remote handle of one dispatched knowledge operation (known after dispatch)."""

    tenant_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    binding: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)


__all__ = ["DIGEST_PATTERN", "HandleKind", "OperationHandle", "QualifiedHandle"]

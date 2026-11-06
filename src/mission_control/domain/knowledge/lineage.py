"""The seven provenance roles and lineage facts (SP-10, OC-D80)."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.knowledge.origin import InvocationOrigin


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProvenanceRole(StrEnum):
    PRODUCER = "producer"  # first created the content (an origin, or external)
    CALLER = "caller"  # the invocation performing this operation
    RECEIPT = "receipt"  # the native receipt proving the effect
    REVISION = "revision"  # the exact revision this fact is about
    ADOPTER = "adopter"  # the obligation that selected existing content
    ASSESSOR = "assessor"  # who assessed it, under which method
    CONSUMER = "consumer"  # the invocation that received it as input


class ActorKind(StrEnum):
    ORIGIN = "origin"
    EXTERNAL = "external"
    RECEIPT = "receipt"
    REVISION = "revision"
    OBLIGATION = "obligation"
    ASSESSMENT = "assessment"


# The same matrix the `content_lineage` CHECK (release 1.5.0) enforces.
ROLE_ACTORS: Final[Mapping[ProvenanceRole, frozenset[ActorKind]]] = MappingProxyType(
    {
        ProvenanceRole.PRODUCER: frozenset({ActorKind.ORIGIN, ActorKind.EXTERNAL}),
        ProvenanceRole.CALLER: frozenset({ActorKind.ORIGIN}),
        ProvenanceRole.RECEIPT: frozenset({ActorKind.RECEIPT}),
        ProvenanceRole.REVISION: frozenset({ActorKind.REVISION}),
        ProvenanceRole.ADOPTER: frozenset({ActorKind.OBLIGATION}),
        ProvenanceRole.ASSESSOR: frozenset({ActorKind.ASSESSMENT}),
        ProvenanceRole.CONSUMER: frozenset({ActorKind.ORIGIN}),
    }
)
ADOPTION_ACT: Final = "adoption"


class LineageFact(Contract):
    """One append-only provenance fact about one qualified handle."""

    subject_handle: str = Field(min_length=1, max_length=2048)
    role: ProvenanceRole
    actor_kind: ActorKind
    actor_ref: str = Field(min_length=1)
    actor_origin: InvocationOrigin | None = None
    fact: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def legal_actor(self) -> LineageFact:
        if self.actor_kind not in ROLE_ACTORS[self.role]:
            raise ValueError(f"role {self.role} cannot be held by a {self.actor_kind} actor")
        if (self.actor_kind is ActorKind.ORIGIN) != (self.actor_origin is not None):
            raise ValueError("exactly the origin actors carry their invocation origin")
        if self.role is ProvenanceRole.PRODUCER and self.fact.get("act") == ADOPTION_ACT:
            raise ValueError("adopting existing content never writes a producer fact")
        return self


__all__ = ["ADOPTION_ACT", "ROLE_ACTORS", "ActorKind", "LineageFact", "ProvenanceRole"]

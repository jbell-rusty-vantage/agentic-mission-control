"""Frozen effect identity and the host journal states (design §5, OC-D85/D88)."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.authoring.canonical import canonical_json, sha256_digest
from mission_control.domain.knowledge.handles import DIGEST_PATTERN
from mission_control.domain.knowledge.origin import InvocationOrigin

EFFECT_KEY_PREFIX: Final = "ek1:"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JournalState(StrEnum):
    PREPARED = "prepared"
    DISPATCHED = "dispatched"
    APPLIED = "applied"
    NOOP = "noop"
    PARTIAL = "partial"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


TERMINAL_STATES: Final = frozenset(
    {JournalState.APPLIED, JournalState.NOOP, JournalState.PARTIAL, JournalState.REJECTED}
)
# The same edges `mission_control.knowledge_operation_guard` (release 1.5.0) enforces.
LEGAL_TRANSITIONS: Final[Mapping[JournalState, frozenset[JournalState]]] = MappingProxyType(
    {
        JournalState.PREPARED: frozenset({JournalState.DISPATCHED, JournalState.REJECTED}),
        JournalState.DISPATCHED: frozenset(TERMINAL_STATES | {JournalState.UNCERTAIN}),
        JournalState.UNCERTAIN: frozenset(TERMINAL_STATES | {JournalState.DISPATCHED}),
        **{state: frozenset() for state in TERMINAL_STATES},
    }
)


class IllegalJournalTransition(ValueError):
    pass


class EffectConflict(ValueError):
    """Same scoped effect key, different bound effect (EFFECT_CONFLICT)."""


def is_legal_transition(current: JournalState, target: JournalState) -> bool:
    return target in LEGAL_TRANSITIONS[current]


def require_transition(current: JournalState, target: JournalState) -> JournalState:
    if not is_legal_transition(current, target):
        raise IllegalJournalTransition(
            f"illegal knowledge operation transition {current} -> {target}"
        )
    return target


def mint_effect_key(
    origin: InvocationOrigin, capability_pin: str, semantic_payload_digest: str
) -> str:
    """Host-minted effect key: stable for one logical effect of one operation of one run.

    Retries and recoveries of the same operation with the same payload mint the same key; the
    attempt, generation, activation and caller are deliberately not inputs. The run is: family
    operation ids are run-relative (``goal-iteration/1/executor``, a StageGraph stage slot),
    so without it the same stage of a later run would be deduplicated to an earlier run's
    receipt (found by the SV-16 T1-MC proof).
    """

    material = {
        "issuer": origin.issuer,
        "scope": list(origin.scope),
        "run_id": origin.run_id,
        "operation_id": origin.operation_id,
        "capability_pin": capability_pin,
        "semantic_payload_digest": semantic_payload_digest,
    }
    return EFFECT_KEY_PREFIX + hashlib.sha256(canonical_json(material)).hexdigest()


def bound_effect_digest(originating_origin: InvocationOrigin, native_payload_digest: str) -> str:
    """Digest of the native bytes bound to the originating origin (bind before seal, OC-D85)."""

    return sha256_digest(
        {"origin": originating_origin.model_dump(mode="json"), "native": native_payload_digest}
    )


class EffectIdentity(Contract):
    effect_key: str = Field(min_length=1, max_length=512)
    semantic_payload_digest: str = Field(pattern=DIGEST_PATTERN)
    bound_effect_digest: str = Field(pattern=DIGEST_PATTERN)
    originating_origin: InvocationOrigin
    current_caller_origin: InvocationOrigin
    dispatch_id: str | None = Field(default=None, min_length=1)
    envelope_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def consistent(self) -> EffectIdentity:
        if (self.dispatch_id is None) != (self.envelope_digest is None):
            raise ValueError("a dispatch names both its id and its envelope digest")
        if not self.current_caller_origin.in_scope_of(self.originating_origin):
            raise ValueError("an effect never changes issuer, installation, application or tenant")
        return self

    @classmethod
    def prepare(
        cls,
        origin: InvocationOrigin,
        *,
        capability_pin: str,
        semantic_payload_digest: str,
        native_payload_digest: str,
    ) -> EffectIdentity:
        return cls(
            effect_key=mint_effect_key(origin, capability_pin, semantic_payload_digest),
            semantic_payload_digest=semantic_payload_digest,
            bound_effect_digest=bound_effect_digest(origin, native_payload_digest),
            originating_origin=origin,
            current_caller_origin=origin,
        )

    @property
    def requires_recovery_authority(self) -> bool:
        """A caller other than the originating one needs explicit host recovery authority."""

        return self.current_caller_origin != self.originating_origin

    def conflicts_with(self, other: EffectIdentity) -> bool:
        return (
            self.originating_origin.scope == other.originating_origin.scope
            and self.effect_key == other.effect_key
            and self.bound_effect_digest != other.bound_effect_digest
        )

    def require_same_effect(self, other: EffectIdentity) -> None:
        if self.conflicts_with(other):
            raise EffectConflict(f"EFFECT_CONFLICT {self.effect_key}")

    def dispatched(self, dispatch_id: str, envelope_digest: str) -> EffectIdentity:
        return type(self).model_validate(
            {
                **self.model_dump(mode="python"),
                "dispatch_id": dispatch_id,
                "envelope_digest": envelope_digest,
            }
        )

    def recovered_by(self, caller: InvocationOrigin) -> EffectIdentity:
        """A later attempt or recovery: same frozen bytes, new caller, no dispatch yet."""

        return type(self).model_validate(
            {
                **self.model_dump(mode="python"),
                "current_caller_origin": caller,
                "dispatch_id": None,
                "envelope_digest": None,
            }
        )


__all__ = [
    "EFFECT_KEY_PREFIX",
    "LEGAL_TRANSITIONS",
    "TERMINAL_STATES",
    "EffectConflict",
    "EffectIdentity",
    "IllegalJournalTransition",
    "JournalState",
    "bound_effect_digest",
    "is_legal_transition",
    "mint_effect_key",
    "require_transition",
]

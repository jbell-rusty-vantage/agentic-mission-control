"""Durable transition reactions: declarations, compiled descriptors, transitions and activations
(OUTPUT-CONTRACTS §11, ADR-0062; Sprint OC WI-22).

A reaction is authored against one **durable transition** of a run: an output submitted, an
assessment recorded, a fulfillment decided, a transfer delivery recorded or a saved result
settled. The five are distinct kinds with their own versions and facts; a provider stop is none
of them. A declaration binds the event and version, an optional closed condition over the
event's facts (the ADR-0010 AST of :mod:`~mission_control.domain.programs.watcher_conditions`),
one admitted operation template, the output promises that operation answers for, its grants and
mandatory limits: activations, recursion depth, a rate, a lifetime and operation time, and spend.

:func:`compile_reaction` resolves every bound into an immutable :class:`ReactionDescriptor`.
Attaching a descriptor to a run gives a :class:`ReactionBinding` with a generation; re-attaching
bumps it, so activations admitted under an older generation are stale. Each admitted reaction is
one :class:`ReactionActivation`, keyed by (binding, transition): a duplicate event yields the same
activation. Its operation id is ``reaction-<activation id>``. A transition's ``cause_ref`` is the
host-derived authenticated operation it is attributed to (never a caller-supplied field), so a
transition the reaction's own operation caused names its parent (the self-trigger chain), and a
``reaction-`` cause naming no activation of the run fails closed (``CAUSE_UNKNOWN``).

Pure rules only: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.contributions import stable_uuid
from mission_control.domain.execution.data_class import DataClass
from mission_control.domain.programs.watcher_conditions import (
    ConditionSyntaxError,
    WatcherCondition,
    parse_condition,
)


class TransitionKind(StrEnum):
    """The durable transitions a reaction can bind; each has its own source and facts."""

    OUTPUT_SUBMITTED = "output.submitted"
    ASSESSMENT_RECORDED = "assessment.recorded"
    FULFILLMENT_DECIDED = "fulfillment.decided"
    DELIVERY_RECORDED = "delivery.recorded"
    SETTLEMENT_SETTLED = "settlement.settled"


TRANSITION_VERSION: Final = 1
# The facts each kind carries (the capture trigger of migration 0061 writes exactly these). A
# condition may only read ``event.<fact>`` of its kind, so a reaction never matches by accident on
# a field another kind happens to carry.
TRANSITION_FACTS: Final[dict[TransitionKind, frozenset[str]]] = {
    TransitionKind.OUTPUT_SUBMITTED: frozenset(
        {"obligation_key", "deliverable_id", "revision", "form", "content_digest"}
    ),
    TransitionKind.ASSESSMENT_RECORDED: frozenset(
        {"subject_kind", "subject_ref", "result", "method_pin", "policy_pin"}
    ),
    TransitionKind.FULFILLMENT_DECIDED: frozenset(
        {"obligation_key", "obligation_revision", "enforcement", "disposition", "distinct_count"}
    ),
    TransitionKind.DELIVERY_RECORDED: frozenset(
        {"transfer_plan_id", "result", "operation_attempt", "receiver_invocation_ref"}
    ),
    TransitionKind.SETTLEMENT_SETTLED: frozenset({"binding_id", "unit_key", "execution_outcome"}),
}
REACTION_OPERATION_PREFIX: Final = "reaction-"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_REACTION_OPERATION = re.compile(rf"(?:^|[^0-9A-Za-z]){REACTION_OPERATION_PREFIX}({_UUID})")
_KEY = r"^[a-z0-9][a-z0-9._:-]{0,127}$"
_BINDING_NAMESPACE: Final = "mission-control:reaction-binding"
_ACTIVATION_NAMESPACE: Final = "mission-control:reaction-activation"

MAX_ACTIVATIONS: Final = 64
MAX_DEPTH: Final = 8
MAX_LIFETIME_SECONDS: Final = 30 * 24 * 3600
MAX_OPERATION_SECONDS: Final = 86_400
MAX_FACT_CHARS: Final = 512


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReactionCompileError(ValueError):
    """A declaration that cannot be admitted; ``code`` is the typed refusal."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- declaration


class ReactionTrigger(_Closed):
    event: TransitionKind
    version: int = Field(default=TRANSITION_VERSION, ge=1)


class ReactionOperation(_Closed):
    """The admitted operation template the reaction runs (an operation request key of the run's
    admitted templates) and what it is for."""

    template: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=500)


class ReactionGrants(_Closed):
    """The most the reaction's operation may hold; its template's grant must fit inside."""

    tools: tuple[str, ...] = Field(default=(), max_length=64)
    mcp_servers: tuple[str, ...] = Field(default=(), max_length=16)


class RateLimit(_Closed):
    count: int = Field(default=4, ge=1, le=MAX_ACTIVATIONS)
    window_seconds: int = Field(default=300, ge=1, le=86_400)


class TimeLimit(_Closed):
    lifetime_seconds: int | None = Field(default=None, ge=1, le=MAX_LIFETIME_SECONDS)
    """How long after arming the binding admits activations (``None``: the run's life)."""
    operation_seconds: int = Field(default=300, ge=1, le=MAX_OPERATION_SECONDS)
    """The bound of one reaction operation (its workflow timeout)."""


class SpendLimit(_Closed):
    tokens_per_activation: int = Field(ge=1)
    max_tokens: int = Field(ge=1)

    @model_validator(mode="after")
    def _within(self) -> SpendLimit:
        if self.tokens_per_activation > self.max_tokens:
            raise ValueError("a reaction's per-activation spend exceeds its total spend")
        return self


class ReactionLimits(_Closed):
    """Mandatory bounds. Spend has no default: an unbounded reaction is not admitted."""

    max_activations: int = Field(default=4, ge=1, le=MAX_ACTIVATIONS)
    max_depth: int = Field(default=2, ge=1, le=MAX_DEPTH)
    rate: RateLimit = Field(default_factory=RateLimit)
    time: TimeLimit = Field(default_factory=TimeLimit)
    spend: SpendLimit


class ReactionDeclaration(_Closed):
    """``mc.reaction.v1``: one authored durable-transition reaction."""

    schema_version: Literal["mc.reaction.v1"] = "mc.reaction.v1"
    id: str = Field(pattern=_KEY)
    on: ReactionTrigger
    where: str | None = Field(default=None, min_length=1, max_length=2048)
    operation: ReactionOperation
    outputs: tuple[str, ...] = Field(default=(), max_length=16)
    """Obligation keys of the run the reaction's operation answers for."""
    grants: ReactionGrants = Field(default_factory=ReactionGrants)
    limits: ReactionLimits


# ---------------------------------------------------------------- compiled descriptor


class ReactionDescriptor(_Closed):
    """``mc.reaction_descriptor.v1``: a declaration with every bound resolved."""

    schema_version: Literal["mc.reaction_descriptor.v1"] = "mc.reaction_descriptor.v1"
    reaction_id: str = Field(pattern=_KEY)
    event: TransitionKind
    version: int = Field(ge=1)
    where: str | None = None
    condition: WatcherCondition | None = None
    operation: ReactionOperation
    outputs: tuple[str, ...] = ()
    grants: ReactionGrants
    limits: ReactionLimits

    @property
    def digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))


def compile_reaction(
    declaration: ReactionDeclaration, *, spend_ceiling_tokens: int | None = None
) -> ReactionDescriptor:
    """Resolve one declaration or refuse it (:class:`ReactionCompileError`).

    Refusals: an unsupported event version, a condition that does not parse or reads anything
    other than the event's own facts, a duplicate or malformed output key, and a total spend
    above the admitted ceiling (the run's budget the reaction draws on)."""

    trigger = declaration.on
    if trigger.version != TRANSITION_VERSION:
        raise ReactionCompileError(
            "UNSUPPORTED_EVENT_VERSION",
            f"{trigger.event.value} has version {TRANSITION_VERSION}, not {trigger.version}",
        )
    condition = None
    if declaration.where is not None:
        try:
            condition = parse_condition(declaration.where)
        except ConditionSyntaxError as error:
            raise ReactionCompileError("CONDITION_INVALID", str(error)) from error
        facts = TRANSITION_FACTS[trigger.event]
        for path in condition.paths():
            root, _, name = path.partition(".")
            if root != "event" or name.split(".")[0] not in facts:
                raise ReactionCompileError(
                    "CONDITION_PATH",
                    f"{path!r} is not a fact of {trigger.event.value} "
                    f"(allowed: {', '.join(sorted('event.' + fact for fact in facts))})",
                )
    outputs = declaration.outputs
    if len(set(outputs)) != len(outputs) or any(
        re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,199}", key) is None for key in outputs
    ):
        raise ReactionCompileError("OUTPUT_KEY_INVALID", "output keys must be distinct keys")
    spend = declaration.limits.spend
    if spend_ceiling_tokens is not None and spend.max_tokens > spend_ceiling_tokens:
        raise ReactionCompileError(
            "SPEND_ABOVE_CEILING",
            f"reaction spend {spend.max_tokens} exceeds the admitted ceiling "
            f"{spend_ceiling_tokens}",
        )
    return ReactionDescriptor(
        reaction_id=declaration.id,
        event=trigger.event,
        version=trigger.version,
        where=declaration.where,
        condition=condition,
        operation=declaration.operation,
        outputs=outputs,
        grants=declaration.grants,
        limits=declaration.limits,
    )


# ---------------------------------------------------------------- binding, transition, activation


def binding_id_for(scope: str, run_id: str, reaction_id: str) -> str:
    return stable_uuid(_BINDING_NAMESPACE, f"{scope}|{run_id}|{reaction_id}")


def transition_id_for(kind: TransitionKind, source_ref: str) -> str:
    """The identity of one durable transition; migration 0061's capture computes the same
    ``md5('mc.durable_transition|' || kind || '|' || source_ref)::uuid``."""

    basis = f"mc.durable_transition|{kind.value}|{source_ref}".encode()
    return str(UUID(hashlib.md5(basis, usedforsecurity=False).hexdigest()))


def activation_id_for(binding_id: str, transition_id: str) -> str:
    """One logical reaction per (binding, transition): a duplicate event maps here again."""

    return stable_uuid(_ACTIVATION_NAMESPACE, f"{binding_id}|{transition_id}")


def reaction_operation_id(activation_id: str) -> str:
    return f"{REACTION_OPERATION_PREFIX}{activation_id}"


def causing_activation(cause_ref: str | None) -> str | None:
    """The activation whose operation caused a transition, read from its host-derived cause
    (an operation id, a binding id or a semantic key all contain ``reaction-<id>``)."""

    if not cause_ref:
        return None
    match = _REACTION_OPERATION.search(cause_ref)
    return None if match is None else match.group(1)


class ReactionBinding(_Closed):
    """A descriptor attached to one run. ``generation`` moves forward on every re-attach and
    on detach; an activation admitted under another generation is stale."""

    binding_id: str
    run_id: str = Field(min_length=1)
    reaction_id: str = Field(pattern=_KEY)
    generation: int = Field(ge=1)
    state: Literal["armed", "detached"] = "armed"
    descriptor: ReactionDescriptor
    armed_at: datetime
    deadline_at: datetime | None = None
    semantic_input_binding_ref: str | None = None
    """The run's admitted semantic binding whose operation templates the reaction draws on."""
    data_class: DataClass | None = None
    """The run's declared data class: the class of every fact a reaction hands its operation."""

    @property
    def descriptor_digest(self) -> str:
        return self.descriptor.digest


FactValue = str | int | bool | None


class DurableTransition(_Closed):
    """``mc.durable_transition.v1``: one captured durable transition of a run."""

    schema_version: Literal["mc.durable_transition.v1"] = "mc.durable_transition.v1"
    transition_id: str
    kind: TransitionKind
    version: int = Field(default=TRANSITION_VERSION, ge=1)
    source_ref: str = Field(min_length=1, max_length=512)
    run_id: str = Field(min_length=1)
    cause_ref: str | None = Field(default=None, max_length=1024)
    """The authenticated operation the transition is attributed to, derived by the host."""
    execution_generation: int | None = Field(default=None, ge=1)
    facts: dict[str, FactValue] = Field(default_factory=dict, max_length=16)
    captured_at: datetime

    @model_validator(mode="after")
    def _identity(self) -> DurableTransition:
        if self.transition_id != transition_id_for(self.kind, self.source_ref):
            raise ValueError("a transition's identity is its kind and source")
        unknown = set(self.facts) - TRANSITION_FACTS[self.kind]
        if unknown:
            raise ValueError(f"{self.kind.value} carries no fact {sorted(unknown)}")
        if any(isinstance(v, str) and len(v) > MAX_FACT_CHARS for v in self.facts.values()):
            raise ValueError("a transition fact exceeds its bound")
        return self

    @classmethod
    def of(
        cls,
        kind: TransitionKind,
        source_ref: str,
        *,
        run_id: str,
        captured_at: datetime,
        cause_ref: str | None = None,
        execution_generation: int | None = None,
        facts: dict[str, FactValue] | None = None,
    ) -> DurableTransition:
        return cls(
            transition_id=transition_id_for(kind, source_ref),
            kind=kind,
            source_ref=source_ref,
            run_id=run_id,
            cause_ref=cause_ref,
            execution_generation=execution_generation,
            facts=facts or {},
            captured_at=captured_at,
        )


ActivationState = Literal["admitted", "dispatched", "cancelled", "refused"]
ACTIVATION_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "admitted": frozenset({"dispatched", "cancelled"}),
    "dispatched": frozenset(),
    "cancelled": frozenset(),
    "refused": frozenset(),
}


class ReactionActivation(_Closed):
    """One logical reaction to one transition through one binding.

    ``refused`` records which admitted limit stopped it (``refusal_code``); ``admitted`` holds a
    dispatch intent; ``cancelled`` (``cancel_reason``) was fenced or stale before dispatch;
    ``dispatched`` names the ordinary operation workflow Temporal runs."""

    activation_id: str
    binding_id: str
    binding_generation: int = Field(ge=1)
    run_id: str
    reaction_id: str
    transition_id: str
    event: TransitionKind
    depth: int = Field(ge=1)
    root_activation_id: str
    cause_activation_id: str | None = None
    run_generation: int | None = Field(default=None, ge=1)
    state: ActivationState
    refusal_code: str | None = None
    cancel_reason: str | None = None
    reserved_tokens: int = Field(ge=0)
    admitted_at: datetime
    workflow_id: str | None = None
    dispatched_at: datetime | None = None

    @property
    def operation_id(self) -> str:
        return reaction_operation_id(self.activation_id)

    @model_validator(mode="after")
    def _shape(self) -> ReactionActivation:
        if (self.state == "refused") != (self.refusal_code is not None):
            raise ValueError("a refused activation names its refusal code, and only it")
        if (self.state == "cancelled") != (self.cancel_reason is not None):
            raise ValueError("a cancelled activation names its reason, and only it")
        if (self.state == "dispatched") != (self.workflow_id is not None):
            raise ValueError("a dispatched activation names its workflow, and only it")
        if self.state == "refused" and self.reserved_tokens:
            raise ValueError("a refused activation reserves nothing")
        if (self.depth == 1) != (self.cause_activation_id is None):
            raise ValueError("only a caused activation is deeper than one")
        if self.cause_activation_id is None and self.root_activation_id != self.activation_id:
            raise ValueError("an uncaused activation is its own chain root")
        return self


__all__ = [
    "ACTIVATION_TRANSITIONS",
    "REACTION_OPERATION_PREFIX",
    "TRANSITION_FACTS",
    "TRANSITION_VERSION",
    "ActivationState",
    "DurableTransition",
    "FactValue",
    "RateLimit",
    "ReactionActivation",
    "ReactionBinding",
    "ReactionCompileError",
    "ReactionDeclaration",
    "ReactionDescriptor",
    "ReactionGrants",
    "ReactionLimits",
    "ReactionOperation",
    "ReactionTrigger",
    "SpendLimit",
    "TimeLimit",
    "TransitionKind",
    "activation_id_for",
    "binding_id_for",
    "causing_activation",
    "compile_reaction",
    "reaction_operation_id",
    "transition_id_for",
]

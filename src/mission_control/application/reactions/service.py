"""Attach durable transition reactions and relay them into ordinary admitted operations
(OUTPUT-CONTRACTS §11, ADR-0004, ADR-0062; Sprint OC WI-22).

There is no reaction scheduler. Three durable steps move a reaction, each a transaction:

1. **Capture.** The transition's own transaction records it (migration 0061's capture
   triggers on the output, assessment, fulfillment, delivery and settlement tables, or
   :meth:`ReactionStore.record_transition` for a caller that owns the commit). Only a run with an
   armed binding for that kind captures anything; the transition id is its kind and source, so a
   duplicate event is one row.
2. **Admission** (:meth:`ReactionRelay.admit_once`). One transaction per transition locks the
   bindings of its run and kind, plans each with the pure
   :func:`~mission_control.domain.reactions.planning.plan_activation`, inserts the activation
   (unique per binding and transition) and, for an admitted one, its ``mc.reaction.dispatch``
   outbox intent, then marks the transition admitted. Admission and dispatch intent commit
   together; a refused activation records its limit.
3. **Dispatch** (:meth:`ReactionRelay.dispatch_once`). The relay leases due intents, re-checks
   currency (:func:`~mission_control.domain.reactions.planning.dispatch_currency`: a stale
   generation or a fenced or finished run cancels), and hands the activation to the
   :class:`ReactionOperationPort`, which materializes the ordinary operation request and starts
   its workflow under the run-derived id with reject-duplicate / use-existing, so Temporal alone
   schedules it and a redelivery attaches. The activation and the intent's acknowledgement then
   commit together; a crash between the start and that commit re-delivers into the same
   workflow, and a crash after admission and before any dispatch is simply a pending intent.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from mission_control.domain.execution.data_class import DataClass
from mission_control.domain.reactions.contracts import (
    DurableTransition,
    ReactionActivation,
    ReactionBinding,
    ReactionDeclaration,
    binding_id_for,
    compile_reaction,
)
from mission_control.domain.reactions.planning import (
    RunAuthority,
    dispatch_currency,
)

_LOG = logging.getLogger(__name__)

DISPATCH_DESTINATION = "mc.reaction.dispatch"
MAX_DISPATCH_ATTEMPTS = 12


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- ports


@dataclass(frozen=True, slots=True)
class DispatchIntent:
    """One leased ``mc.reaction.dispatch`` outbox intent."""

    delivery_key: str
    activation_id: str
    run_id: str
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    kind: Literal["dispatched", "cancelled"]
    workflow_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReactionDispatchReceipt:
    workflow_id: str
    temporal_run_id: str | None = None
    already_started: bool = False


class ReactionDispatchRefused(RuntimeError):
    """The activation cannot become an admitted operation (template, grant or budget);
    terminal for the activation, never retried."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AdmissionReport:
    transitions: int = 0
    activations: tuple[ReactionActivation, ...] = ()


class ReactionStore(Protocol):
    async def attach(self, scope: str, binding: ReactionBinding) -> ReactionBinding:
        """Arm the binding at generation 1, or re-attach it: the same armed descriptor returns
        unchanged; another descriptor (or a detached binding) moves to the next generation."""
        ...

    async def detach(self, scope: str, binding_id: str, *, at: datetime) -> ReactionBinding | None:
        """Detach and move the generation forward, so pending activations cancel."""
        ...

    async def binding(self, scope: str, binding_id: str) -> ReactionBinding | None: ...

    async def record_transition(self, scope: str, transition: DurableTransition) -> bool:
        """Record a transition once (``True`` when it was new); captured only while the run
        has an armed binding of its kind."""
        ...

    async def transition(self, scope: str, transition_id: str) -> DurableTransition | None: ...

    async def admit_pending(self, scope: str, *, now: datetime, limit: int) -> AdmissionReport:
        """Admit due transitions (one transaction each, see the module docstring)."""
        ...

    async def activation(self, scope: str, activation_id: str) -> ReactionActivation | None: ...

    async def activations(self, scope: str, run_id: str) -> tuple[ReactionActivation, ...]: ...

    async def lease_dispatches(
        self,
        scope: str,
        *,
        lease_owner: str,
        lease_until: datetime,
        now: datetime,
        limit: int,
    ) -> tuple[DispatchIntent, ...]: ...

    async def settle_dispatch(
        self,
        scope: str,
        intent: DispatchIntent,
        *,
        lease_owner: str,
        outcome: DispatchOutcome,
        at: datetime,
    ) -> ReactionActivation:
        """Move the activation (compare-and-set from ``admitted``) and acknowledge the intent in
        one transaction; an activation already settled the same way is returned unchanged."""
        ...

    async def retry_dispatch(
        self,
        scope: str,
        intent: DispatchIntent,
        *,
        lease_owner: str,
        retry_at: datetime,
        dead: bool,
    ) -> None: ...


class ReactionAuthorityPort(Protocol):
    async def current(self, scope: str, run_id: str) -> RunAuthority:
        """The run's execution generation, stop fence and terminal state, read now."""
        ...


class ReactionOperationPort(Protocol):
    async def dispatch(
        self,
        scope: str,
        activation: ReactionActivation,
        binding: ReactionBinding,
        transition: DurableTransition,
    ) -> ReactionDispatchReceipt:
        """Materialize the activation as an ordinary admitted operation and start it on
        Temporal (idempotent per activation); raise :class:`ReactionDispatchRefused` when it
        cannot be admitted."""
        ...


# ---------------------------------------------------------------- attachment


class ReactionBindingService:
    """Compile declarations and attach them to a run (one binding per reaction id)."""

    def __init__(self, store: ReactionStore, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._store = store
        self._clock = clock

    async def attach(
        self,
        scope: str,
        run_id: str,
        declarations: Sequence[ReactionDeclaration],
        *,
        spend_ceiling_tokens: int | None = None,
        semantic_input_binding_ref: str | None = None,
        data_class: DataClass | None = None,
    ) -> tuple[ReactionBinding, ...]:
        """``data_class`` is the run's declared class (``MissionDefinition.data_class``): every
        fact a reaction hands its operation is run data of that class, and dispatch refuses a
        template whose lane does not admit it."""
        if len({item.id for item in declarations}) != len(declarations):
            raise ValueError("reaction ids are unique within a run")
        descriptors = [
            compile_reaction(item, spend_ceiling_tokens=spend_ceiling_tokens)
            for item in declarations
        ]
        now = self._clock()
        bound: list[ReactionBinding] = []
        for descriptor in descriptors:
            lifetime = descriptor.limits.time.lifetime_seconds
            bound.append(
                await self._store.attach(
                    scope,
                    ReactionBinding(
                        binding_id=binding_id_for(scope, run_id, descriptor.reaction_id),
                        run_id=run_id,
                        reaction_id=descriptor.reaction_id,
                        generation=1,
                        descriptor=descriptor,
                        armed_at=now,
                        deadline_at=None if lifetime is None else now + timedelta(seconds=lifetime),
                        semantic_input_binding_ref=semantic_input_binding_ref,
                        data_class=data_class,
                    ),
                )
            )
        return tuple(bound)

    async def detach(self, scope: str, run_id: str, reaction_id: str) -> ReactionBinding | None:
        return await self._store.detach(
            scope, binding_id_for(scope, run_id, reaction_id), at=self._clock()
        )


# ---------------------------------------------------------------- relay


@dataclass(frozen=True, slots=True)
class DispatchReport:
    dispatched: tuple[str, ...] = ()
    cancelled: dict[str, str] = field(default_factory=dict)
    retried: tuple[str, ...] = ()
    dead: tuple[str, ...] = ()
    receipts: dict[str, ReactionDispatchReceipt] = field(default_factory=dict)


class ReactionRelay:
    """Admission and at-least-once dispatch of reactions; acknowledgement follows the start."""

    def __init__(
        self,
        *,
        store: ReactionStore,
        authority: ReactionAuthorityPort,
        operations: ReactionOperationPort,
        lease_owner: str = "reaction-relay",
        lease_seconds: int = 60,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 900.0,
    ) -> None:
        self._store = store
        self._authority = authority
        self._operations = operations
        self._owner = lease_owner
        self._lease = timedelta(seconds=lease_seconds)
        self._base = base_backoff_seconds
        self._cap = max_backoff_seconds

    async def admit_once(self, scope: str, *, now: datetime, limit: int = 50) -> AdmissionReport:
        return await self._store.admit_pending(scope, now=now, limit=limit)

    async def dispatch_once(self, scope: str, *, now: datetime, limit: int = 20) -> DispatchReport:
        intents = await self._store.lease_dispatches(
            scope, lease_owner=self._owner, lease_until=now + self._lease, now=now, limit=limit
        )
        dispatched: list[str] = []
        cancelled: dict[str, str] = {}
        retried: list[str] = []
        dead: list[str] = []
        receipts: dict[str, ReactionDispatchReceipt] = {}
        for intent in intents:
            try:
                outcome, receipt = await self._deliver(scope, intent, now)
            except Exception as error:  # a delivery failure is retried, never dropped
                attempts = intent.attempts + 1
                is_dead = attempts >= MAX_DISPATCH_ATTEMPTS
                _LOG.warning(
                    "reaction dispatch %s failed (attempt %s): %s",
                    intent.delivery_key,
                    attempts,
                    error,
                )
                delay = min(self._cap, self._base * (2 ** min(attempts, 16)))
                await self._store.retry_dispatch(
                    scope,
                    intent,
                    lease_owner=self._owner,
                    retry_at=now + timedelta(seconds=delay),
                    dead=is_dead,
                )
                (dead if is_dead else retried).append(intent.activation_id)
                continue
            settled = await self._store.settle_dispatch(
                scope, intent, lease_owner=self._owner, outcome=outcome, at=now
            )
            if settled.state == "dispatched":
                dispatched.append(settled.activation_id)
                if receipt is not None:
                    receipts[settled.activation_id] = receipt
            elif settled.cancel_reason is not None:
                cancelled[settled.activation_id] = settled.cancel_reason
        return DispatchReport(
            dispatched=tuple(dispatched),
            cancelled=cancelled,
            retried=tuple(retried),
            dead=tuple(dead),
            receipts=receipts,
        )

    async def run_once(
        self, scope: str, *, now: datetime
    ) -> tuple[AdmissionReport, DispatchReport]:
        admitted = await self.admit_once(scope, now=now)
        return admitted, await self.dispatch_once(scope, now=now)

    async def _deliver(
        self, scope: str, intent: DispatchIntent, now: datetime
    ) -> tuple[DispatchOutcome, ReactionDispatchReceipt | None]:
        activation = await self._store.activation(scope, intent.activation_id)
        if activation is None:
            raise LookupError(f"reaction activation {intent.activation_id} is not visible")
        if activation.state == "dispatched":  # settled by an earlier delivery: acknowledge only
            return DispatchOutcome("dispatched", workflow_id=activation.workflow_id), None
        if activation.state != "admitted":
            return DispatchOutcome("cancelled", reason=activation.cancel_reason or "settled"), None
        binding = await self._store.binding(scope, activation.binding_id)
        authority = await self._authority.current(scope, activation.run_id)
        reason = dispatch_currency(activation, binding, authority, now=now)
        if reason is not None or binding is None:
            return DispatchOutcome("cancelled", reason=reason or "stale_generation"), None
        transition = await self._store.transition(scope, activation.transition_id)
        if transition is None:
            raise LookupError(f"reaction transition {activation.transition_id} is not visible")
        try:
            receipt = await self._operations.dispatch(scope, activation, binding, transition)
        except ReactionDispatchRefused as refused:
            return DispatchOutcome("cancelled", reason=refused.code.lower()), None
        return DispatchOutcome("dispatched", workflow_id=receipt.workflow_id), receipt


class ReactionRelayPump:
    """The relay as a bounded, cancellable worker loop over tenant scopes (one transaction scope
    each, as row-level security binds one tenant per transaction)."""

    def __init__(
        self,
        relay: ReactionRelay,
        request_scopes: Sequence[str],
        *,
        interval_seconds: float,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("the reaction relay pump needs a positive interval")
        self._relay = relay
        self._scopes = tuple(request_scopes)
        self._interval = interval_seconds
        self._clock = clock

    async def run_once(self) -> None:
        for scope in self._scopes:
            try:
                await self._relay.run_once(scope, now=self._clock())
            except Exception:  # one scope's outage never stops the others or the worker
                _LOG.exception("reaction relay pass failed for one tenant scope")

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.run_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._interval)


__all__ = [
    "DISPATCH_DESTINATION",
    "MAX_DISPATCH_ATTEMPTS",
    "AdmissionReport",
    "DispatchIntent",
    "DispatchOutcome",
    "DispatchReport",
    "ReactionAuthorityPort",
    "ReactionBindingService",
    "ReactionDispatchReceipt",
    "ReactionDispatchRefused",
    "ReactionOperationPort",
    "ReactionRelay",
    "ReactionRelayPump",
    "ReactionStore",
]

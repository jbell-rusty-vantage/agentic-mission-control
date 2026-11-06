"""Planning one reaction to one durable transition, and its dispatch-time currency (WI-22).

:func:`plan_activation` is called by the store inside the admission transaction, with the
binding row locked, so every limit is decided against what that binding has already admitted.
It returns ``None`` when the binding does not react (another kind or version, detached, armed
after the transition was captured, or the condition is false); otherwise one
:class:`~mission_control.domain.reactions.contracts.ReactionActivation`, admitted or refused with
the first limit it hits, in this order:

0. ``CAUSE_UNKNOWN``: the transition's cause names a reaction operation (``reaction-<id>``)
   that is no activation of this run; it fails closed rather than rooting a new chain;
1. ``TIME_LIMIT``: the binding's lifetime ended before admission;
2. ``RECURSION_LIMIT``: the transition was produced by a reaction operation whose chain is
   already ``max_depth`` deep (the self-trigger chain);
3. ``ACTIVATION_LIMIT``: the binding already admitted ``max_activations``;
4. ``RATE_LIMIT``: ``rate.count`` admissions inside the trailing ``rate.window_seconds``,
   counted by admission time (the database clock at admission, serialized per binding by its
   lock), so a source transaction that commits late cannot slip into an earlier window;
5. ``SPEND_LIMIT``: the reserved spend plus this activation's reservation exceeds ``max_tokens``.

A refused activation is durable too, so a duplicate of the same event stays refused once.
:func:`dispatch_currency` decides, just before dispatch, whether an admitted activation is still
current: a detached or re-attached binding (``stale_generation``), a run whose execution
generation moved on (``stale_run_generation``), a binding whose lifetime ended
(``lifetime_ended``), a stop-fenced run (``run_fenced``) or a finished run (``run_terminal``)
cancels it instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from mission_control.domain.programs.watcher_conditions import evaluate_condition
from mission_control.domain.reactions.contracts import (
    DurableTransition,
    ReactionActivation,
    ReactionBinding,
    activation_id_for,
)


@dataclass(frozen=True, slots=True)
class ActivationLedger:
    """What one binding has admitted so far (every activation that was not refused)."""

    admitted_at: Sequence[datetime] = ()
    reserved_tokens: int = 0

    @property
    def count(self) -> int:
        return len(self.admitted_at)


@dataclass(frozen=True, slots=True)
class CausalParent:
    """The activation whose operation produced the transition being planned."""

    activation_id: str
    root_activation_id: str
    depth: int


@dataclass(frozen=True, slots=True)
class RunAuthority:
    """The run's current authority as dispatch sees it."""

    execution_generation: int | None
    fenced: bool = False
    terminal: bool = False


def matches(binding: ReactionBinding, transition: DurableTransition) -> bool:
    descriptor = binding.descriptor
    if binding.state != "armed" or binding.run_id != transition.run_id:
        return False
    if descriptor.event is not transition.kind or descriptor.version != transition.version:
        return False
    if transition.captured_at < binding.armed_at:
        return False
    if descriptor.condition is None:
        return True
    return evaluate_condition(descriptor.condition, {"event": dict(transition.facts)})


def plan_activation(
    binding: ReactionBinding,
    transition: DurableTransition,
    ledger: ActivationLedger,
    *,
    parent: CausalParent | None,
    run_generation: int | None,
    now: datetime,
    cause_unknown: bool = False,
) -> ReactionActivation | None:
    """``now`` is the admission time; ``cause_unknown`` that the transition's cause names a
    reaction operation the run has no activation for."""

    if not matches(binding, transition):
        return None
    limits = binding.descriptor.limits
    activation_id = activation_id_for(binding.binding_id, transition.transition_id)
    at = max(now, transition.captured_at)
    depth = 1 if parent is None else parent.depth + 1
    window_start = at - timedelta(seconds=limits.rate.window_seconds)
    refusal: str | None = None
    if cause_unknown:
        refusal = "CAUSE_UNKNOWN"
    elif binding.deadline_at is not None and at >= binding.deadline_at:
        refusal = "TIME_LIMIT"
    elif depth > limits.max_depth:
        refusal = "RECURSION_LIMIT"
    elif ledger.count >= limits.max_activations:
        refusal = "ACTIVATION_LIMIT"
    elif sum(1 for t in ledger.admitted_at if window_start < t <= at) >= limits.rate.count:
        refusal = "RATE_LIMIT"
    elif ledger.reserved_tokens + limits.spend.tokens_per_activation > limits.spend.max_tokens:
        refusal = "SPEND_LIMIT"
    return ReactionActivation(
        activation_id=activation_id,
        binding_id=binding.binding_id,
        binding_generation=binding.generation,
        run_id=transition.run_id,
        reaction_id=binding.reaction_id,
        transition_id=transition.transition_id,
        event=transition.kind,
        depth=depth,
        root_activation_id=activation_id if parent is None else parent.root_activation_id,
        cause_activation_id=None if parent is None else parent.activation_id,
        run_generation=run_generation,
        state="refused" if refusal else "admitted",
        refusal_code=refusal,
        reserved_tokens=0 if refusal else limits.spend.tokens_per_activation,
        admitted_at=at,
    )


def dispatch_currency(
    activation: ReactionActivation,
    binding: ReactionBinding | None,
    authority: RunAuthority,
    *,
    now: datetime,
) -> str | None:
    """``None`` when the admitted activation may still be dispatched, else why it cancels."""

    if (
        binding is None
        or binding.state != "armed"
        or binding.generation != activation.binding_generation
    ):
        return "stale_generation"
    if binding.deadline_at is not None and now >= binding.deadline_at:
        return "lifetime_ended"
    if authority.terminal:
        return "run_terminal"
    if authority.fenced:
        return "run_fenced"
    if (
        activation.run_generation is not None
        and authority.execution_generation is not None
        and authority.execution_generation != activation.run_generation
    ):
        return "stale_run_generation"
    return None


__all__ = [
    "ActivationLedger",
    "CausalParent",
    "RunAuthority",
    "dispatch_currency",
    "matches",
    "plan_activation",
]

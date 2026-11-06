"""WI-22 / OVE-183: compiling durable transition reactions and planning their activations.

Pure rules: a declaration compiles with every bound resolved or refuses; one transition through
one binding is one activation (a duplicate event maps to the same id); the five transition kinds
stay distinct; and the admitted recursion, rate, activation, time and spend limits each refuse in
turn. Dispatch currency cancels a stale binding generation, a moved run generation, a fenced run
and a finished one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mission_control.domain.reactions.contracts import (
    TRANSITION_FACTS,
    DurableTransition,
    ReactionActivation,
    ReactionBinding,
    ReactionCompileError,
    ReactionDeclaration,
    TransitionKind,
    activation_id_for,
    binding_id_for,
    causing_activation,
    compile_reaction,
    reaction_operation_id,
    transition_id_for,
)
from mission_control.domain.reactions.planning import (
    ActivationLedger,
    CausalParent,
    RunAuthority,
    dispatch_currency,
    plan_activation,
)

AT = datetime(2026, 10, 28, 9, tzinfo=UTC)
SCOPE = "mc/00000000-0000-7000-8000-000000000001/biotech/00000000-0000-4000-8000-000000000002"
RUN = "22222222-2222-4222-8222-222222222222"


def declaration(**updates: object) -> ReactionDeclaration:
    values: dict[str, object] = {
        "id": "review-on-fulfillment",
        "on": {"event": "fulfillment.decided"},
        "where": "event.disposition == 'unfulfilled'",
        "operation": {"template": "reviewer", "purpose": "Repair the unmet obligation."},
        "outputs": ["report.repaired"],
        "limits": {
            "max_activations": 3,
            "max_depth": 2,
            "rate": {"count": 2, "window_seconds": 60},
            "time": {"lifetime_seconds": 3600, "operation_seconds": 120},
            "spend": {"tokens_per_activation": 100, "max_tokens": 250},
        },
    }
    values.update(updates)
    return ReactionDeclaration.model_validate(values)


def bind(decl: ReactionDeclaration | None = None, *, generation: int = 1) -> ReactionBinding:
    descriptor = compile_reaction(decl or declaration())
    lifetime = descriptor.limits.time.lifetime_seconds
    return ReactionBinding(
        binding_id=binding_id_for(SCOPE, RUN, descriptor.reaction_id),
        run_id=RUN,
        reaction_id=descriptor.reaction_id,
        generation=generation,
        descriptor=descriptor,
        armed_at=AT,
        deadline_at=None if lifetime is None else AT + timedelta(seconds=lifetime),
    )


def transition(
    source: str = "f-1",
    *,
    kind: TransitionKind = TransitionKind.FULFILLMENT_DECIDED,
    at: datetime = AT + timedelta(seconds=1),
    cause: str | None = None,
    **facts: object,
) -> DurableTransition:
    defaults = {
        TransitionKind.FULFILLMENT_DECIDED: {
            "obligation_key": "report",
            "disposition": "unfulfilled",
        },
        TransitionKind.OUTPUT_SUBMITTED: {"obligation_key": "report", "form": "text"},
        TransitionKind.ASSESSMENT_RECORDED: {"result": "fail"},
        TransitionKind.DELIVERY_RECORDED: {"result": "ready"},
        TransitionKind.SETTLEMENT_SETTLED: {"execution_outcome": "completed"},
    }[kind]
    return DurableTransition.of(
        kind,
        source,
        run_id=RUN,
        captured_at=at,
        cause_ref=cause,
        facts={**defaults, **facts},  # type: ignore[dict-item]
    )


def admitted_ledger(*times: datetime, tokens: int = 0) -> ActivationLedger:
    return ActivationLedger(admitted_at=times, reserved_tokens=tokens)


def plan(
    binding: ReactionBinding,
    event: DurableTransition,
    ledger: ActivationLedger | None = None,
    parent: CausalParent | None = None,
    *,
    now: datetime | None = None,
    cause_unknown: bool = False,
) -> ReactionActivation | None:
    return plan_activation(
        binding,
        event,
        ledger or ActivationLedger(),
        parent=parent,
        run_generation=1,
        now=now or event.captured_at,
        cause_unknown=cause_unknown,
    )


# ---------------------------------------------------------------- compile


def test_compile_resolves_bounds_and_a_stable_digest() -> None:
    descriptor = compile_reaction(declaration())
    assert descriptor.event is TransitionKind.FULFILLMENT_DECIDED
    assert descriptor.condition is not None
    assert descriptor.limits.spend.max_tokens == 250
    assert descriptor.digest == compile_reaction(declaration()).digest
    assert descriptor.digest != compile_reaction(declaration(where=None)).digest


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"on": {"event": "output.submitted", "version": 2}}, "UNSUPPORTED_EVENT_VERSION"),
        ({"where": "event.disposition =="}, "CONDITION_INVALID"),
        ({"where": "run.phase == 'active'"}, "CONDITION_PATH"),
        # A fact of another kind (assessment `result`) is not a fulfillment fact.
        ({"where": "event.result == 'fail'"}, "CONDITION_PATH"),
        ({"outputs": ["a", "a"]}, "OUTPUT_KEY_INVALID"),
    ],
)
def test_compile_refuses(updates: dict[str, object], code: str) -> None:
    with pytest.raises(ReactionCompileError) as refused:
        compile_reaction(declaration(**updates))
    assert refused.value.code == code


def test_compile_refuses_spend_above_the_ceiling_and_unbounded_spend() -> None:
    with pytest.raises(ReactionCompileError) as refused:
        compile_reaction(declaration(), spend_ceiling_tokens=200)
    assert refused.value.code == "SPEND_ABOVE_CEILING"
    with pytest.raises(ValueError, match="spend"):
        declaration(limits={"max_activations": 2})
    with pytest.raises(ValueError, match="per-activation"):
        declaration(limits={"spend": {"tokens_per_activation": 300, "max_tokens": 250}})


# ---------------------------------------------------------------- identity and distinct events


def test_a_duplicate_event_is_the_same_transition_and_the_same_activation() -> None:
    binding = bind()
    first, again = plan(binding, transition("f-1")), plan(binding, transition("f-1"))
    assert first is not None and again is not None
    assert first.activation_id == again.activation_id
    assert first.activation_id == activation_id_for(
        binding.binding_id, transition_id_for(TransitionKind.FULFILLMENT_DECIDED, "f-1")
    )
    other = plan(binding, transition("f-2"))
    assert other is not None and other.activation_id != first.activation_id


def test_the_five_transition_kinds_stay_distinct() -> None:
    ids = {transition_id_for(kind, "same-source") for kind in TransitionKind}
    assert len(ids) == 5
    assert set(TRANSITION_FACTS) == set(TransitionKind)
    binding = bind()  # bound to fulfillment.decided only
    for kind in TransitionKind:
        planned = plan(binding, transition("same-source", kind=kind))
        assert (planned is not None) == (kind is TransitionKind.FULFILLMENT_DECIDED)
    with pytest.raises(ValueError, match="carries no fact"):
        DurableTransition.of(
            TransitionKind.OUTPUT_SUBMITTED,
            "o-1",
            run_id=RUN,
            captured_at=AT,
            facts={"disposition": "fulfilled"},
        )


def test_condition_detach_and_capture_before_arming_do_not_react() -> None:
    binding = bind()
    assert plan(binding, transition(disposition="fulfilled")) is None
    detached = binding.model_copy(update={"state": "detached"})
    assert plan(detached, transition()) is None
    assert plan(binding, transition(at=AT - timedelta(seconds=1))) is None


def test_admitted_activation_reserves_its_spend_and_names_its_operation() -> None:
    activation = plan(bind(), transition())
    assert activation is not None
    assert activation.state == "admitted" and activation.reserved_tokens == 100
    assert activation.depth == 1 and activation.root_activation_id == activation.activation_id
    assert activation.operation_id == reaction_operation_id(activation.activation_id)
    semantic = f"{RUN}:operation:{activation.operation_id}:attempt:1"
    assert causing_activation(semantic) == activation.activation_id
    assert causing_activation(f"deep-agent:{semantic}") == activation.activation_id
    assert causing_activation("mc-inv:sha256:abc") is None


# ---------------------------------------------------------------- limits


def test_recursion_limit_stops_the_self_trigger_chain() -> None:
    binding = bind()
    root = plan(binding, transition("f-1"))
    assert root is not None
    second = plan(
        binding,
        transition("f-2", cause=root.operation_id),
        parent=CausalParent(root.activation_id, root.root_activation_id, root.depth),
    )
    assert second is not None and second.state == "admitted" and second.depth == 2
    assert second.cause_activation_id == root.activation_id
    assert second.root_activation_id == root.activation_id
    third = plan(
        binding,
        transition("f-3", cause=second.operation_id),
        parent=CausalParent(second.activation_id, second.root_activation_id, second.depth),
    )
    assert third is not None
    assert (third.state, third.refusal_code, third.depth) == ("refused", "RECURSION_LIMIT", 3)
    assert third.reserved_tokens == 0


def test_activation_rate_spend_and_time_limits_refuse_in_turn() -> None:
    binding = bind()
    late = AT + timedelta(minutes=10)
    ledger = admitted_ledger(AT, AT + timedelta(seconds=1), AT + timedelta(seconds=2))
    refused = plan(binding, transition(at=late), ledger)
    assert refused is not None and refused.refusal_code == "ACTIVATION_LIMIT"
    burst = admitted_ledger(late - timedelta(seconds=10), late - timedelta(seconds=5))
    refused = plan(binding, transition(at=late), burst)
    assert refused is not None and refused.refusal_code == "RATE_LIMIT"
    outside = admitted_ledger(late - timedelta(seconds=90), tokens=200)
    refused = plan(binding, transition(at=late), outside)
    assert refused is not None and refused.refusal_code == "SPEND_LIMIT"
    expired = plan(binding, transition(at=AT + timedelta(hours=2)))
    assert expired is not None and expired.refusal_code == "TIME_LIMIT"
    fits = plan(
        binding, transition(at=late), admitted_ledger(late - timedelta(seconds=90), tokens=100)
    )
    assert fits is not None and fits.state == "admitted"


# ---------------------------------------------------------------- dispatch currency


def test_dispatch_currency_cancels_stale_fenced_and_finished() -> None:
    binding = bind()
    activation = plan(binding, transition())
    assert activation is not None
    current = RunAuthority(execution_generation=1)
    assert dispatch_currency(activation, binding, current, now=AT) is None
    rebound = binding.model_copy(update={"generation": 2})
    assert dispatch_currency(activation, rebound, current, now=AT) == "stale_generation"
    detached = binding.model_copy(update={"state": "detached", "generation": 2})
    assert dispatch_currency(activation, detached, current, now=AT) == "stale_generation"
    assert dispatch_currency(activation, None, current, now=AT) == "stale_generation"
    moved = RunAuthority(execution_generation=2)
    assert dispatch_currency(activation, binding, moved, now=AT) == "stale_run_generation"
    fenced = RunAuthority(execution_generation=1, fenced=True)
    assert dispatch_currency(activation, binding, fenced, now=AT) == "run_fenced"
    done = RunAuthority(execution_generation=1, terminal=True)
    assert dispatch_currency(activation, binding, done, now=AT) == "run_terminal"


def test_an_unknown_reaction_cause_fails_closed() -> None:
    """S5: a cause naming a reaction operation the run has no activation for never roots a new
    chain at depth one."""

    forged = transition("f-1", cause="reaction-00000000-0000-4000-8000-000000000000")
    refused = plan(bind(), forged, cause_unknown=True)
    assert refused is not None
    assert (refused.state, refused.refusal_code, refused.reserved_tokens) == (
        "refused",
        "CAUSE_UNKNOWN",
        0,
    )


def test_the_rate_window_counts_admission_time_not_capture_time() -> None:
    """S3: a transition captured long ago but admitted now counts in the current window."""

    binding = bind()
    late = AT + timedelta(minutes=10)
    burst = admitted_ledger(late - timedelta(seconds=10), late - timedelta(seconds=5))
    early_capture = transition("f-old", at=AT + timedelta(seconds=1))
    refused = plan(binding, early_capture, burst, now=late)
    assert refused is not None and refused.refusal_code == "RATE_LIMIT"
    assert refused.admitted_at == late, "an activation is stamped with its admission time"


def test_dispatch_rechecks_the_binding_lifetime() -> None:
    """N3: an activation admitted inside the lifetime cancels when dispatch comes after it."""

    binding = bind()
    activation = plan(binding, transition())
    assert activation is not None and binding.deadline_at is not None
    current = RunAuthority(execution_generation=1)
    after = binding.deadline_at + timedelta(seconds=1)
    assert dispatch_currency(activation, binding, current, now=after) == "lifetime_ended"

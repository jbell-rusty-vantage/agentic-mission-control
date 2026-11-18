"""Builders, constants and fakes that other test files import.

Moved from tests/unit/reactions/test_reaction_planning.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mission_control.domain.reactions.contracts import (
    DurableTransition,
    ReactionActivation,
    ReactionBinding,
    ReactionDeclaration,
    TransitionKind,
    binding_id_for,
    compile_reaction,
)
from mission_control.domain.reactions.planning import (
    ActivationLedger,
    CausalParent,
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

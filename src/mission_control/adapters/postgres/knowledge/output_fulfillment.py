"""The production output service over PostgreSQL (WI-01/WI-02/WI-05; W1 OVE-169).

One factory composes `OutputFulfillmentService` for every route that needs it: launch registers
the admitted promises (`bootstrap/launch_promises.py`) and the GoalDirected worker decides the
run's fulfillment at its convergence boundary (`deployment_composition`). Fulfillment reads file
realizations from the sealed transfer plan receipts and effect receipts from the settled
knowledge journal, and re-decides fulfillment after every head move and recorded assessment, so
WI-19's `output.fulfilled` / `output.fulfillment_unmet` events come from the real writes.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
from mission_control.adapters.postgres.knowledge.operations import PostgresKnowledgeJournal
from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.knowledge.use_decisions import PostgresMemberDecisions
from mission_control.application.knowledge.effect_receipts import JournalEffectReceipts
from mission_control.application.outputs.adoption import OutputAdoptionService
from mission_control.application.outputs.fulfillment import (
    OutputFulfillmentService,
    TrustedReferenceUses,
)
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.recovery.fork_outputs import ForkOutputCarry
from mission_control.domain.knowledge.judgment import TRUSTED_BRIDGE_ACTOR


def compose_output_fulfillment(
    pool: asyncpg.Pool, *, trusted_validators: frozenset[str] | None
) -> OutputFulfillmentService:
    """``trusted_validators``: the Application Profile's ``assessment_pin`` (required; ``None``
    treats every collection member validator as trusted, fail closed; WI-07 review N1)."""

    store = PostgresOutputContractStore(pool)
    return OutputFulfillmentService(
        store,
        SubmissionService(store, contracts=store),
        # W1 D28: current official use of exact reference revisions from the trusted record.
        reference_uses=TrustedReferenceUses(store),
        realizations=PostgresTransferPlanStore(pool),
        effect_receipts=JournalEffectReceipts(PostgresKnowledgeJournal(pool)),
        refresh_on_change=True,
        trusted_validators=trusted_validators,
        # WI-07 review S2: cited member decisions verified against the recorded trusted decisions.
        member_decisions=PostgresMemberDecisions(pool, bridge_actor=TRUSTED_BRIDGE_ACTOR),
    )


def compose_fork_output_carry(
    pool: asyncpg.Pool, toolset: Any, *, trusted_validators: frozenset[str] | None
) -> ForkOutputCarry:
    """F1-G4: the carry of a reused unit's accepted named outputs into a fork-derived run,
    over the worker's knowledge toolset (invocation origin, pins, lineage) and this store."""

    from mission_control.application.knowledge.toolset import LiveInvocation

    store = PostgresOutputContractStore(pool)
    return ForkOutputCarry(
        invocations=toolset,
        finalization=toolset.submissions,
        adoption=OutputAdoptionService(
            outputs=store, submissions=toolset.submissions, lineage=toolset.lineage
        ),
        fulfillment=compose_output_fulfillment(pool, trusted_validators=trusted_validators),
        outputs=store,
        live_factory=LiveInvocation,
    )


__all__ = ["compose_fork_output_carry", "compose_output_fulfillment"]

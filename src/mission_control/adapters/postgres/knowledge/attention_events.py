"""Output/transfer attention events in the mission journal (WI-19, OUTPUT-CONTRACTS §12).

The output and transfer stores call :func:`emit_attention_event` inside the transaction that
records the state change, so the coordinator inbox (OVE-78, which reads only the mission
journal) is woken by exactly the default actionable transitions:

- ``output.fulfilled`` / ``output.fulfillment_unmet``: a promise's fulfillment disposition
  changed (unmet only for a required or expected promise; the final evaluation at run end is
  how an unmet promise reaches the coordinator);
- ``output.assessment_held`` / ``output.assessment_rejected``: a review or fail judgment;
- ``transfer.delivery_refused`` / ``transfer.delivery_waiting``: an input delivery attempt that
  was not ready.

One ledger commit per source record through the canonical writer (``append_events``: sequence
under the mission lock, outbox row), keyed by the source id, so a replay is the same event. A
record whose run has no ``mission_run`` row (a disposable fixture run) emits nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.domain.policies.contracts import ActorContext, DomainEventEnvelope
from mission_control.domain.subscriptions.significance import (
    OUTPUT_ASSESSMENT_HELD,
    OUTPUT_ASSESSMENT_REJECTED,
    OUTPUT_FULFILLED,
    OUTPUT_FULFILLMENT_UNMET,
    TRANSFER_DELIVERY_REFUSED,
    TRANSFER_DELIVERY_WAITING,
)


async def emit_attention_event(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    *,
    run_id: str,
    event_type: str,
    source_ref: str,
    payload: dict[str, object],
    actor_ref: str,
) -> bool:
    """Append one attention event for ``run_id`` in the caller's transaction (False: no run)."""

    # W1 (OVE-169): output and transfer records carry the public run id (`run_key`, what the
    # launch registers promises under); the row id is accepted too.
    run_key = await connection.fetchval(
        f"SELECT run_key FROM mission_control.mission_run WHERE {SCOPE} "
        "AND (run_key = $4 OR run_id::text = $4)",
        *args,
        run_id,
    )
    if run_key is None:
        return False
    now = datetime.now(UTC)
    key = f"output-attention:{event_type}:{source_ref}"
    await mc.append_events(
        connection,
        args,
        run_key=str(run_key),
        commit_key=key,
        expected_versions={},
        events=(
            DomainEventEnvelope(
                event_id=key,
                event_type=event_type,
                # One aggregate per source record: the outbox keys (aggregate, version,
                # sequence) never collide with the run's own lifecycle events.
                aggregate_id=key,
                aggregate_version=1,
                sequence=1,
                occurred_at=now,
                recorded_at=now,
                actor=ActorContext(actor_id=actor_ref),
                correlation_id=source_ref,
                payload=payload,
            ),
        ),
        actor_ref=actor_ref,
        run_hooks=False,
    )
    return True


__all__ = [
    "OUTPUT_ASSESSMENT_HELD",
    "OUTPUT_ASSESSMENT_REJECTED",
    "OUTPUT_FULFILLED",
    "OUTPUT_FULFILLMENT_UNMET",
    "TRANSFER_DELIVERY_REFUSED",
    "TRANSFER_DELIVERY_WAITING",
    "emit_attention_event",
]

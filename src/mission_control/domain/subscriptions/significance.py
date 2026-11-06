"""Significance kinds of public mission events (multi-provider SPEC-04, MP-15; SPEC-04 §5).

The coordinator inbox classifies committed events into these kinds
(`application/subscriptions/coordinator.py`), and a watcher's ``notify`` action names one of
them. The named event sets are the single source both read.
"""

from __future__ import annotations

from typing import Final, Literal

NotifyKind = Literal[
    "review_required",
    "blocked",
    "failed",
    "terminal_result",
    "accepted_output",
    "child_lifecycle",
    "review_closed",
    "progress",
]

# WI-19 (OUTPUT-CONTRACTS §12): output and transfer transitions the output stores journal in
# the transaction of the state change (`adapters/postgres/knowledge/attention_events.py`).
OUTPUT_FULFILLED: Final = "output.fulfilled"
OUTPUT_FULFILLMENT_UNMET: Final = "output.fulfillment_unmet"
OUTPUT_ASSESSMENT_HELD: Final = "output.assessment_held"
OUTPUT_ASSESSMENT_REJECTED: Final = "output.assessment_rejected"
TRANSFER_DELIVERY_REFUSED: Final = "transfer.delivery_refused"
TRANSFER_DELIVERY_WAITING: Final = "transfer.delivery_waiting"

REVIEW_REQUIRED_EVENTS: Final = frozenset({"human_task.opened", "human_task.escalated"})
REVIEW_CLOSED_EVENTS: Final = frozenset({"human_task.resolved", "human_task.cancelled"})
BLOCKED_EVENTS: Final = frozenset(
    {"human_task.expired", "command.in_doubt", "subscription.dead_lettered"}
)
FAILED_EVENTS: Final = frozenset({"session.continuation_failed", "watcher.failed"})
# The kinds the output/transfer attention events notify as. Kept apart from the named sets
# above, which authored `notifications` sugar expands into watchers (its compiled digest must
# not move): these reach a coordinator through the inbox's default profile only.
OUTPUT_ATTENTION_KINDS: Final[dict[str, str]] = {
    OUTPUT_FULFILLED: "accepted_output",
    OUTPUT_FULFILLMENT_UNMET: "blocked",
    OUTPUT_ASSESSMENT_HELD: "blocked",
    OUTPUT_ASSESSMENT_REJECTED: "failed",
    TRANSFER_DELIVERY_REFUSED: "blocked",
    TRANSFER_DELIVERY_WAITING: "blocked",
}
TERMINAL_EVENTS: Final = frozenset({"run.completed", "chain.completed"})
ACCEPTED_OUTPUT_EVENTS: Final = frozenset(
    {
        "workflow_run.record_output_evidence",
        "workflow_run.accept_finalization_plan",
        "workflow_run.record_finalization_result",
        "artifact.admitted",
    }
)

# The kinds a fixed event set defines; `child_lifecycle` and `progress` depend on the
# coordinator profile and on the event's facts, so they name no set here.
KIND_EVENTS: Final[dict[str, frozenset[str]]] = {
    "review_required": REVIEW_REQUIRED_EVENTS,
    "review_closed": REVIEW_CLOSED_EVENTS,
    "blocked": BLOCKED_EVENTS,
    "failed": FAILED_EVENTS,
    "terminal_result": TERMINAL_EVENTS,
    "accepted_output": ACCEPTED_OUTPUT_EVENTS,
}


def kind_of_event(public_event_type: str) -> str | None:
    """The kind a public event type always classifies as, or None when it depends on facts."""

    for kind, events in KIND_EVENTS.items():
        if public_event_type in events:
            return kind
    return None


__all__ = [
    "ACCEPTED_OUTPUT_EVENTS",
    "BLOCKED_EVENTS",
    "FAILED_EVENTS",
    "KIND_EVENTS",
    "OUTPUT_ASSESSMENT_HELD",
    "OUTPUT_ASSESSMENT_REJECTED",
    "OUTPUT_ATTENTION_KINDS",
    "OUTPUT_FULFILLED",
    "OUTPUT_FULFILLMENT_UNMET",
    "REVIEW_CLOSED_EVENTS",
    "REVIEW_REQUIRED_EVENTS",
    "TERMINAL_EVENTS",
    "TRANSFER_DELIVERY_REFUSED",
    "TRANSFER_DELIVERY_WAITING",
    "NotifyKind",
    "kind_of_event",
]

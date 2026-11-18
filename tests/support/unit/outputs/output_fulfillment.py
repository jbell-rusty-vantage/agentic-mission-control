"""Builders, constants and fakes that other test files import.

Moved from tests/unit/outputs/test_output_fulfillment.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.adapters.outputs.memory import InMemoryOutputContractStore
from mission_control.application.knowledge.access import InvocationAccess
from tests.support.knowledge.gateway import origin
from tests.unit.outputs.scenario import Stack, build_stack

AT = datetime(2026, 10, 27, 12, tzinfo=UTC)


def invocation(attempt: int = 1, **updates: object) -> InvocationAccess:
    return InvocationAccess(
        origin=origin(attempt, **updates),
        subject="mission-control-runtime",
        invocation_id=f"inv-{attempt:04d}",
        authenticated_at=AT,
    )


async def make_stack(*obligations, completion=None, **vocab) -> Stack:  # type: ignore[no-untyped-def]
    store = InMemoryOutputContractStore()
    return await build_stack(
        store, store.submissions, invocation(), *obligations, completion=completion, **vocab
    )

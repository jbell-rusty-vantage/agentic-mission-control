"""Builders, constants and fakes that other test files import.

Moved from tests/unit/context/test_wi07_current_set_transfer.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.application.context.materialization import MaterializeRequest
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.domain.context import transfer_builders as builders
from mission_control.domain.context.transfer import (
    BackendCapabilities,
    HostOverhead,
    ReceiverAttempt,
    ReceiverRef,
    ResourceBounds,
)
from mission_control.domain.outputs.current_set import with_current_set_index
from tests.support.knowledge.gateway import origin
from tests.unit.outputs.scenario import Stack, text

AT = datetime(2026, 10, 28, 12, tzinfo=UTC)
RUN = "22222222-2222-4222-8222-222222222222"
SANDBOX = BackendCapabilities(custody_backend="mc-custody", file_capable=True, binary_capable=True)
OVERHEAD = HostOverhead(host_state_tokens=800, tool_schema_tokens=400, skill_tokens=100)


def invocation(operation: str, attempt: int = 1) -> InvocationAccess:
    return InvocationAccess(
        origin=origin(attempt, operation_id=operation),
        subject="mission-control-runtime",
        invocation_id="inv-" + operation.replace("/", "-") + f"-{attempt}",
        authenticated_at=AT,
    )


def executor(iteration: int) -> str:
    return f"goal-iteration/{iteration}/executor"


class Backend:
    realized_backend = "fake:sandbox"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def write(self, files) -> None:  # type: ignore[no-untyped-def]
        self.files.update(files)

    async def read(self, path: str) -> bytes | None:
        return self.files.get(path)


def bounds() -> ResourceBounds:
    return ResourceBounds(
        window_tokens=64_000,
        generation_reserve_tokens=4_000,
        tool_result_reserve_tokens=2_000,
        inline_bytes_ceiling=16_000,
        file_bytes_ceiling=512_000,
        file_count_ceiling=16,
    )


def verifier_selection(iteration: int):  # type: ignore[no-untyped-def]
    base = builders.first_invocation("goal", bounds(), SANDBOX)
    judge = builders.evaluator(base, [("goal", "goal.reports")])
    return with_current_set_index(
        builders.for_producer(judge, executor(iteration)), purpose="evaluation_subject"
    )


def request(stack: Stack, selection, operation: str, attempt: int = 1) -> MaterializeRequest:  # type: ignore[no-untyped-def]
    access = invocation(operation, attempt)
    return MaterializeRequest(
        receiver=ReceiverRef(scope=stack.host.scope, run_id=RUN, operation_id=operation),
        attempt=ReceiverAttempt(
            operation_attempt=attempt, execution_generation=1, invocation_ref=f"inv-{attempt}"
        ),
        selection=selection,
        configuration_ref="erc:sha256:" + "0" * 64,
        host_state_ref="context-packet:p1@sha256:" + "1" * 64,
        overhead=OVERHEAD,
        access=access,
    )


async def iteration(stack: Stack, number: int, *items: tuple[str, str]) -> list[str]:
    """One executor iteration submits its reports and finalizes; returns revision ids."""

    access = invocation(executor(number))
    worker = await stack.start(access)
    ids: list[str] = []
    for deliverable, body in items:
        ack = await worker.submit(
            f"{number}-{deliverable}", "goal.reports", text(deliverable, body), position="goal"
        )
        assert ack.status == "accepted", ack.error
        ids.append(ack.revisions[0].revision_id)
    await stack.submissions.finalize(access.identity(("goal.reports",)))
    return ids


async def judge(stack: Stack, revision_id: str, verdict: str) -> None:
    revision = await stack.store.output_revision(stack.host.scope, revision_id)
    assert revision is not None
    receipt = await stack.judge(revision_id, revision.content_digest, assessed=verdict)
    assert receipt.status == "recorded", receipt.error

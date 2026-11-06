"""Tracing Stage 3 (R2-2): the API's `TemporalForkSeedRunner` over a fake Temporal client.

The worker's typed refusal reaches the client as
`WorkflowFailureError(cause=ActivityError(cause=ApplicationError))`; the runner unwraps the
activity error so the fork service sees the same `TimeTravelUnsupported` the in-process lane
raises (`cognitive_seed_unavailable` 503 for a saver outcome, never a 500). A copy that does
not finish in time is `copy_incomplete` (retryable), and the workflow keeps running.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError, RetryState

from mission_control.adapters.temporal.activities.fork_seed import (
    TIME_TRAVEL_UNSUPPORTED,
    ForkSeedOutcome,
    TemporalForkSeedRunner,
)
from mission_control.application.execution.harness.time_travel import (
    ForkSeedReceipt,
    ForkSeedRequest,
    TimeTravelUnsupported,
)
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionCoordinate,
    CognitionPointRecord,
    UnitLocationFacts,
    point_id_for,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey

DIGEST = "sha256:" + "5" * 64
UNIT_KEY = "bl-unit-v1:" + "ab" * 32


def request() -> ForkSeedRequest:
    key = QualifiedCheckpointKey(
        checkpointer_ref_digest=DIGEST, thread_id="thread", checkpoint_ns="", checkpoint_id="p"
    )
    return ForkSeedRequest(
        source=CognitionPointRecord(
            point_id=point_id_for("run-source", UNIT_KEY, 1, "checkpoint", "p"),
            coordinate=CognitionCoordinate(
                run_id="run-source",
                unit_key=UNIT_KEY,
                execution_generation=1,
                point=CheckpointPoint(key=key),
            ),
            lane_profile="deep_agents",
            location=UnitLocationFacts(family="stage_graph", node_key="S2", iteration=0, cycle=0),
            seedable=True,
            written_by="adapter",
            recorded_at=datetime.now(UTC),
        ),
        derived_run_id="run-derived",
        derived_unit_key=UNIT_KEY,
        derived_namespace="derived-thread",
        derived_invocation_id="sha256:" + "6" * 64,
        fork_request_id="fork-1",
    )


def activity_failure(reason: str, *, saver: str | None = DIGEST) -> WorkflowFailureError:
    refusal = ApplicationError(
        f"{reason} on lane profile deep_agents",
        {"lane_profile": "deep_agents", "reason": reason, "saver": saver},
        type=TIME_TRAVEL_UNSUPPORTED,
        non_retryable=True,
    )
    activity = ActivityError(
        "activity error",
        scheduled_event_id=5,
        started_event_id=6,
        identity="worker",
        activity_type="fork_seed.copy",
        activity_id="1",
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )
    activity.__cause__ = refusal
    failure = WorkflowFailureError(cause=activity)
    failure.__cause__ = activity
    return failure


class FakeHandle:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    async def result(self) -> Any:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if self.outcome == "hang":
            await asyncio.sleep(3600)
        return self.outcome


class FakeClient:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.started: list[str] = []

    async def start_workflow(self, workflow: str, arg: Any, **kwargs: Any) -> FakeHandle:
        self.started.append(kwargs["id"])
        return FakeHandle(self.outcome)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    ["saver_unreachable", "saver_not_served", "copy_incomplete", "checkpointer_not_registered"],
)
async def test_the_activitys_typed_refusal_reaches_the_fork_as_time_travel_unsupported(
    reason: str,
) -> None:
    runner = TemporalForkSeedRunner(FakeClient(activity_failure(reason)), task_queue="mc.maint")  # type: ignore[arg-type]
    with pytest.raises(TimeTravelUnsupported) as refused:
        await runner.seed_fork(request())
    assert refused.value.reason == reason
    assert refused.value.saver == DIGEST
    assert refused.value.lane_profile == "deep_agents"


@pytest.mark.asyncio
async def test_another_failure_propagates_unchanged() -> None:
    failure = WorkflowFailureError(cause=RuntimeError("boom"))
    runner = TemporalForkSeedRunner(FakeClient(failure), task_queue="mc.maint")  # type: ignore[arg-type]
    with pytest.raises(WorkflowFailureError):
        await runner.seed_fork(request())


@pytest.mark.asyncio
async def test_a_copy_that_does_not_finish_in_time_is_copy_incomplete() -> None:
    client = FakeClient("hang")
    runner = TemporalForkSeedRunner(client, task_queue="mc.maint", result_timeout_seconds=0.01)  # type: ignore[arg-type]
    with pytest.raises(TimeTravelUnsupported) as refused:
        await runner.seed_fork(request())
    assert refused.value.reason == "copy_incomplete"
    assert client.started == ["fork-seed/fork-1/" + UNIT_KEY]


@pytest.mark.asyncio
async def test_a_finished_copy_returns_its_receipt() -> None:
    seed = request()
    receipt = ForkSeedReceipt(
        restore_level="R3",
        derived=seed.source.coordinate.model_copy(update={"run_id": "run-derived"}),
        copied_checkpoints=3,
    )
    runner = TemporalForkSeedRunner(
        FakeClient(ForkSeedOutcome(receipt=receipt)),  # type: ignore[arg-type]
        task_queue="mc.maint",
    )
    assert await runner.seed_fork(seed) == receipt

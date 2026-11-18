"""Temporal test support: the time-skipping test server, captured-history inspection and the
fixture workflow and activity pieces Temporal tests share.

Registered as a pytest plugin in tests/conftest.py, so ``workflow_env`` is available to every
test. A Temporal test that cannot start the test server **fails**; it never skips, because a
skipped workflow proof reads as a passed one (tests/AGENTS.md).

History inspection: the Python SDK records ``workflow.patched`` as a ``core_patch`` marker
whose ``patch-data`` detail is the JSON ``{"id": ..., "deprecated": ...}``; the marker name
alone never names the patch.

Operation activities: since RRM-008 every ``OperationWorkflow`` reconciles a cancelled unit
through ``operation.cancel``, and a cancel reaches a running ``operation.execute`` only through
its heartbeat (``TRY_CANCEL``). A fake worker set therefore registers both Activities, and a
fake ``execute`` that waits heartbeats while it waits, so a cancel reaches it under the
time-skipping server instead of after a heartbeat or schedule-to-close timeout.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from temporalio import activity, workflow
from temporalio.client import WorkflowHistory
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment

from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationExecutionResult,
)
from mission_control.domain.programs.contracts import (
    BellLabsRunInput,
    StageGraphCompletionProposal,
    StageGraphRunInput,
    StageGraphRunResult,
)

# --- the time-skipping test server ------------------------------------------------------------

TEMPORAL_TEST_SERVER_ENV = "MISSION_CONTROL_TEST_TEMPORAL_SERVER"


async def start_workflow_env(**options: Any) -> WorkflowEnvironment:
    """Start Temporal's time-skipping test server, or fail the test with the reason.

    ``options`` go to ``WorkflowEnvironment.start_time_skipping``. Without an explicit
    ``test_server_existing_path``, the binary named by ``MISSION_CONTROL_TEST_TEMPORAL_SERVER``
    is used when set; otherwise the SDK downloads (and caches) the test server.
    """

    existing = os.environ.get(TEMPORAL_TEST_SERVER_ENV) or None
    options.setdefault("test_server_existing_path", existing)
    try:
        return await WorkflowEnvironment.start_time_skipping(**options)
    except (RuntimeError, OSError) as error:
        pytest.fail(
            f"Temporal time-skipping test server could not start: {error}. The SDK downloads it "
            f"on first use; offline, set {TEMPORAL_TEST_SERVER_ENV} to an existing test-server "
            "binary.",
            pytrace=False,
        )


@asynccontextmanager
async def workflow_environment(**options: Any) -> AsyncIterator[WorkflowEnvironment]:
    """``async with workflow_environment() as env``: a started test server, shut down on exit."""

    environment = await start_workflow_env(**options)
    async with environment:
        yield environment


@pytest_asyncio.fixture
async def workflow_env() -> AsyncIterator[WorkflowEnvironment]:
    """A time-skipping Temporal test server for one test; the test fails if it cannot start."""

    async with workflow_environment() as environment:
        yield environment


# --- captured history inspection -------------------------------------------------------------


def patch_ids(history: WorkflowHistory) -> set[str]:
    """The `workflow.patched` IDs recorded in a history."""

    ids: set[str] = set()
    for event in history.events:
        if not event.HasField("marker_recorded_event_attributes"):
            continue
        marker = event.marker_recorded_event_attributes
        if marker.marker_name != "core_patch":
            continue
        for payload in marker.details["patch-data"].payloads:
            ids.add(str(json.loads(payload.data)["id"]))
    return ids


def scheduled_activity_inputs(history: WorkflowHistory, activity_type: str) -> list[Any]:
    """The decoded JSON inputs of every scheduled activity of one type, in history order."""

    inputs: list[Any] = []
    for event in history.events:
        if not event.HasField("activity_task_scheduled_event_attributes"):
            continue
        attributes = event.activity_task_scheduled_event_attributes
        if attributes.activity_type.name == activity_type:
            inputs.extend(json.loads(item.data) for item in attributes.input.payloads)
    return inputs


def completed_activity_results(history: WorkflowHistory, activity_type: str) -> list[Any]:
    """The decoded JSON results of every completed activity of one type, in history order."""

    scheduled = {
        event.event_id
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
        and event.activity_task_scheduled_event_attributes.activity_type.name == activity_type
    }
    results: list[Any] = []
    for event in history.events:
        if not event.HasField("activity_task_completed_event_attributes"):
            continue
        attributes = event.activity_task_completed_event_attributes
        if attributes.scheduled_event_id in scheduled:
            results.extend(json.loads(item.data) for item in attributes.result.payloads)
    return results


# --- fake operation activities ---------------------------------------------------------------

HEARTBEAT_POLL_SECONDS = 0.25
CANCEL_REASON = "operation cancelled by the governed cancellation saga"


async def wait_heartbeating(event: asyncio.Event) -> None:
    """Wait for `event`, heartbeating so a requested cancel is delivered promptly."""

    while not event.is_set():
        activity.heartbeat()
        try:
            await asyncio.wait_for(event.wait(), timeout=HEARTBEAT_POLL_SECONDS)
        except TimeoutError:
            continue


async def sleep_heartbeating(seconds: float) -> None:
    """`asyncio.sleep(seconds)` that heartbeats while it sleeps."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while (remaining := deadline - loop.time()) > 0:
        activity.heartbeat()
        await asyncio.sleep(min(HEARTBEAT_POLL_SECONDS, remaining))


def cancelled_operation_result(request: dict[str, Any]) -> dict[str, Any]:
    """The operation boundary's public result of a unit settled `cancelled` before dispatch
    (`OperationExecutionService.cancel`): exact binding, no usage, no checkpoint."""

    binding = bind_operation_execution_request(OperationExecutionRequest.model_validate(request))
    return OperationExecutionResult(
        binding_id=binding.binding_id,
        semantic_attempt_key=binding.semantic_attempt_key,
        status="cancelled",
        failure_code="cancelled",
        failure_message=CANCEL_REASON,
        unit_key=binding.runtime_unit.unit_key if binding.runtime_unit is not None else None,
    ).model_dump(mode="json")


class RecordingOperationCancel:
    """A faithful fake `operation.cancel`: records each call and settles the unit
    `cancelled` with the operation boundary's result shape."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @activity.defn(name="operation.cancel")
    async def cancel(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(str(request["identity"]["operation_id"]))
        return cancelled_operation_result(request)


# --- fixture child workflow ------------------------------------------------------------------


@workflow.defn(name="belllabs.run.v1", sandboxed=False)
class FixtureChildWorkflow:
    """A ``belllabs.run.v1`` child that completes, fails (``child.fail``) or waits forever
    (``child.cancel``) by its blueprint's logical id."""

    @workflow.run
    async def run(self, root_input: BellLabsRunInput) -> StageGraphRunResult:
        run_input = StageGraphRunInput(**root_input.family_input)
        if run_input.blueprint.get("logical_id") == "child.fail":
            raise ApplicationError("fixture child failed", non_retryable=True)
        if run_input.blueprint.get("logical_id") == "child.cancel":
            await workflow.wait_condition(lambda: False)
        return StageGraphRunResult(
            run_id=run_input.run_id,
            workflow_cycles=0,
            execution_epoch=run_input.execution_epoch,
            family_version=1,
            output_refs={"child": ("artifact:child:exact-v1",)},
            reused_output_refs={},
            schedule_trace=("child",),
            completion_proposal=StageGraphCompletionProposal(
                required_obligations_accepted=True,
                pending_dependency_ids=(),
                open_producer_liability_ids=(),
                valid_output_refs=("artifact:child:exact-v1",),
            ),
        )

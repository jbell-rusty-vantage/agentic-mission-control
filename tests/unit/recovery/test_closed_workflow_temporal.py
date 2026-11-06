from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import WorkflowExecutionStatus
from tests.unit.recovery.test_closed_workflow import setup_recovery

from mission_control.adapters.temporal.closed_workflow import TemporalClosedWorkflowObserver
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.identities import mission_root_id
from mission_control.domain.programs.contracts import StageGraphRunInput


class Handle:
    def __init__(self, workflow_id, run_id, events, status):
        self.workflow_id, self.run_id, self.events, self.status = (
            workflow_id,
            run_id,
            events,
            status,
        )

    async def describe(self, **_kwargs):
        return SimpleNamespace(run_id=self.run_id, status=self.status)

    async def fetch_history_events(self, **_kwargs):
        for event in self.events:
            yield event


class Client:
    def __init__(self, handles, latest):
        self.handles, self.latest = handles, latest
        self.data_converter = SimpleNamespace(decode=AsyncMock())

    def get_workflow_handle(self, workflow_id, *, run_id=None):
        return self.handles[(workflow_id, run_id or self.latest[workflow_id])]


def history(
    *middle, terminal="workflow_execution_failed_event_attributes", previous="", successor=""
):
    first = HistoryEvent(event_id=1)
    first.workflow_execution_started_event_attributes.continued_execution_run_id = previous
    first.workflow_execution_started_event_attributes.workflow_type.name = "belllabs.stagegraph"
    events = [first, *middle]
    last = HistoryEvent(event_id=len(events) + 1)
    getattr(last, terminal).SetInParent()
    if successor:
        getattr(last, terminal).new_execution_run_id = successor
    events.append(last)
    for index, event in enumerate(events, 1):
        event.event_id = index
    return events


async def scenario():
    _, controls, _, _, _, _, run_id = await setup_recovery()
    scope = f"mc/{uuid4()}/app/{uuid4()}"
    run = await controls.get_run("tenant-1", run_id)
    root = mission_root_id(scope, run_id)
    run = run.model_copy(
        update={
            "request_scope": scope,
            "execution_target": run.execution_target.model_copy(update={"root_workflow_id": root}),
        }
    )
    handles = {
        (w, "exact-" + w): Handle(w, "exact-" + w, history(), WorkflowExecutionStatus.FAILED)
        for w in (root, "family", "producer")
    }
    client = Client(handles, dict(handles.keys()))
    observer = TemporalClosedWorkflowObserver(client)
    observer._validate_input = AsyncMock()
    return observer, client, run, root


@pytest.mark.asyncio
async def test_exact_closed_tree_retains_metadata_and_only_read_methods():
    observer, _, run, _ = await scenario()
    evidence = await observer.observe(run, ("producer",))
    assert len(evidence.executions) == 3
    assert all(
        item.latest and item.last_event_id == 2 and item.history_digest.startswith("sha256:")
        for item in evidence.executions
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["unstarted", "active_abandoned", "activity", "external", "truncated"]
)
async def test_no_unstarted_abandoned_external_or_active_liability(case):
    observer, client, run, root = await scenario()
    events = []
    if case in {"unstarted", "active_abandoned"}:
        event = HistoryEvent(event_id=2)
        event.start_child_workflow_execution_initiated_event_attributes.workflow_id = "child"
        events.append(event)
        if case == "active_abandoned":
            event = HistoryEvent(event_id=3)
            attrs = event.child_workflow_execution_started_event_attributes
            attrs.initiated_event_id = 2
            attrs.workflow_execution.workflow_id = "child"
            attrs.workflow_execution.run_id = "actual-child"
            events.append(event)
            client.handles[("child", "actual-child")] = Handle(
                "child", "actual-child", history(), WorkflowExecutionStatus.RUNNING
            )
            client.latest["child"] = "actual-child"
    if case == "activity":
        event = HistoryEvent(event_id=2)
        event.activity_task_scheduled_event_attributes.SetInParent()
        events.append(event)
    if case == "external":
        event = HistoryEvent(event_id=2)
        event.signal_external_workflow_execution_initiated_event_attributes.SetInParent()
        events.append(event)
    actual = history(*events)
    if case == "truncated":
        actual[0].event_id = 2
    client.handles[(root, client.latest[root])].events = actual
    with pytest.raises(MissionControlRejected):
        await observer.observe(run, ("producer",))


@pytest.mark.asyncio
async def test_continue_as_new_includes_prior_and_successor_and_recheck_refuses_reset():
    observer, client, run, root = await scenario()
    latest_id = client.latest[root]
    client.handles[(root, latest_id)].events = history(previous="previous")
    client.handles[(root, "previous")] = Handle(
        root,
        "previous",
        history(
            terminal="workflow_execution_continued_as_new_event_attributes", successor=latest_id
        ),
        WorkflowExecutionStatus.CONTINUED_AS_NEW,
    )
    evidence = await observer.observe(run, ("producer",))
    assert len(evidence.executions) == 4
    assert sum(item.latest for item in evidence.executions if item.workflow_id == root) == 1
    client.latest[root] = "reset"
    client.handles[(root, "reset")] = Handle(
        root, "reset", history(), WorkflowExecutionStatus.FAILED
    )
    with pytest.raises(MissionControlRejected, match="changed or reopened"):
        await observer.recheck(evidence)


@pytest.mark.asyncio
async def test_real_typed_family_scope_binding_validation():
    observer, client, run, _ = await scenario()
    observer = TemporalClosedWorkflowObserver(client)
    value = StageGraphRunInput(
        run_id=run.run_id,
        request_scope=run.request_scope,
        effective_configuration_digest=run.effective_configuration_digest,
        workflow_type_digest=run.workflow_type_ref.digest,
        blueprint_digest="sha256:" + "a" * 64,
        blueprint={},
    )
    client.data_converter.decode.return_value = [value]
    attributes = history()[0].workflow_execution_started_event_attributes
    await observer._validate_input(run, "family", attributes)
    client.data_converter.decode.return_value = [
        StageGraphRunInput(**{**value.__dict__, "request_scope": "foreign"})
    ]
    with pytest.raises(MissionControlRejected, match="scope/run/binding differs"):
        await observer._validate_input(run, "family", attributes)

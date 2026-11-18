"""FT-C4 on a real namespace (`WorkflowEnvironment.start_local`): run list over Visibility.

A mission-scoped StageGraph run (``mc.mission_run.v1`` root, family, ``mc.operation.v1``
operations; every workflow id under ``mc/<installation>/<application>/``) is submitted
under the `required` policy with its ledger mission. The family now upserts ``mc_phase``
(``executing`` at start, ``completed`` at its close, behind ``ft-c4-family-phase``); the
root carries ``mc_mission_id`` and ``mc_run_id``; operations carry ``mc_lane`` and
``mc_phase``. :class:`RunListService` over :class:`TemporalRunVisibility` lists the run for
``lane``, ``phase``, ``mission_id`` and ``status`` filters, enriched from the ledger, and
another application's scope lists nothing.

FT-G7 in the same server start: each operation writes ``mc_run_id``, ``mc_lane`` and
``mc_phase`` at its segment boundaries only (start ``executing``, close ``completed``, behind
``ft-g7-mc-visibility``), so the raw Visibility queries count the run's workflows by phase; a
fork submitted with ``parent_run_id`` starts its root with ``ForkedFromRunId``. The new
histories replay.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from temporalio import activity
from temporalio.client import Client, WorkflowHistory
from temporalio.common import SearchAttributeKey
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.search_attributes import (
    BELLLABS_SEARCH_ATTRIBUTE_KEYS,
    FAMILY_PHASE_PATCH,
    MC_VISIBILITY_PATCH,
)
from mission_control.adapters.temporal.submission import TemporalWorkflowSubmitter
from mission_control.adapters.temporal.visibility import TemporalRunVisibility
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.mission_run import MissionRunWorkflow
from mission_control.adapters.temporal.workflows.operation import MissionOperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import StageGraphWorkflow
from mission_control.application.coordinator.coordinator_results import (
    InMemoryWorkflowResultRepository,
    TerminalWorkflowCompletionService,
)
from mission_control.application.frames.search import RunListService
from mission_control.domain.coordinator.launch import (
    BlueprintFamily,
    TerminalWorkflowCompletion,
    WorkflowResultRecord,
)
from mission_control.domain.policies.contracts import ActorContext, RunOutcome, RunPhase
from tests.support.integration.temporal.search_attributes_visibility import (
    UnitBoundStageGraphActivities,
    _start_local,
)
from tests.support.integration.temporal.stage_graph_workflow_temporal import QUEUE, _blueprint
from tests.support.integration.temporal.stage_graph_workflow_temporal import (
    _run_input as stage_run_input,
)
from tests.support.run_control import request as run_request
from tests.support.run_control import service as run_control_service
from tests.support.temporal import patch_ids

INSTALLATION = UUID("0192a4f0-0000-7000-8000-00000000c404")
SCOPE = f"mc/{INSTALLATION}/biotech/1b0e1c4e-6d0f-5c6b-9a4e-0d6d6f1c2a01"
OTHER_APP_SCOPE = f"mc/{INSTALLATION}/ai-engineer/1b0e1c4e-6d0f-5c6b-9a4e-0d6d6f1c2a01"
READER = ActorContext(actor_id="reader", permissions=frozenset({"workflow_run.read"}))


def _key(name: str) -> SearchAttributeKey[Any]:
    return next(key for key in BELLLABS_SEARCH_ATTRIBUTE_KEYS if key.name == name)


def _mc_upserts(history: WorkflowHistory) -> list[dict[str, str]]:
    """The fast-track upserts of a history, decoded as `{name: raw json}`."""

    upserts: list[dict[str, str]] = []
    for event in history.events:
        if not event.HasField("upsert_workflow_search_attributes_event_attributes"):
            continue
        fields = event.upsert_workflow_search_attributes_event_attributes.search_attributes
        mc = {
            name: payload.data.decode("utf-8")
            for name, payload in fields.indexed_fields.items()
            if name.startswith("mc_")
        }
        if mc:
            upserts.append(mc)
    return upserts


async def _count(client: Client, query: str, expected: int) -> int:
    async with asyncio.timeout(30):
        while True:
            count = (await client.count_workflows(query)).count
            if count == expected:
                return count
            await asyncio.sleep(0.25)


class _Ledger:
    """The in-memory ledger admitted under `tenant-1`; served under the mission scope."""

    def __init__(self, authority: Any) -> None:
        self._authority = authority

    async def get_run(self, request_scope: str, run_id: str) -> Any:
        return await self._authority.get_run("tenant-1", run_id)


class _TerminalStandIn:
    """Stands in for the reducer's terminal run: the fake family never drives the ledger."""

    async def get_run(self, request_scope: str, run_id: str) -> Any:
        return SimpleNamespace(
            request_scope=request_scope,
            run_id=run_id,
            phase=RunPhase.TERMINAL,
            terminal_outcome=RunOutcome.COMPLETED,
            accepted_output_evidence=(),
            accepted_obligation_evidence=(),
        )


class _RunListActivities(UnitBoundStageGraphActivities):
    """The fake family queue plus the root's terminal result materializer.

    `MissionRunWorkflow` stays open until `coordinator.materialize_workflow_result` saves the
    typed result on the family queue, as the production StageGraph worker registers it."""

    def __init__(self) -> None:
        super().__init__()
        self.results = InMemoryWorkflowResultRepository()
        self.completions: list[TerminalWorkflowCompletion] = []

    @activity.defn(name="coordinator.materialize_workflow_result")
    async def materialize_workflow_result(
        self, completion: TerminalWorkflowCompletion
    ) -> WorkflowResultRecord:
        self.completions.append(completion)
        service = TerminalWorkflowCompletionService(runs=_TerminalStandIn(), results=self.results)
        return await service.complete(completion)

    @property
    def functions(self) -> list[object]:
        return [*super().functions, self.materialize_workflow_result]


async def _eventually(service: RunListService, query: str, expected: set[str]) -> Any:
    async with asyncio.timeout(30):
        while True:
            page = await service.list(query, actor=READER)
            if {row.run_id for row in page.rows} == expected:
                return page
            await asyncio.sleep(0.25)


@pytest.mark.asyncio
async def test_run_list_queries_typed_search_attributes_and_family_phase() -> None:
    authority, _runs = run_control_service()
    admitted = await authority.admit(run_request(request_id="ft-c4-run-list"))
    fork = await authority.admit(run_request(request_id="ft-c4-run-list-fork"))
    assert admitted.run_id is not None and fork.run_id is not None
    run_id, fork_id = admitted.run_id, fork.run_id
    activities = _RunListActivities()
    activities.slow_release.set()
    env = await _start_local()
    async with env:
        client = env.client
        async with Worker(
            client,
            task_queue=QUEUE,
            workflows=[MissionRunWorkflow, StageGraphWorkflow, MissionOperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            submitter = TemporalWorkflowSubmitter.for_production(
                client,
                stagegraph_task_queue=QUEUE,
                goal_directed_task_queue="ft-c4-goal-unused",
                search_attribute_policy="required",
                mission_installation_id=INSTALLATION,
                mission_application_id="biotech",
            )
            submission = await submitter.submit(
                replace(stage_run_input(_blueprint()), run_id=run_id, request_scope=SCOPE),
                workflow_id="ignored",
                blueprint_family=BlueprintFamily.STAGE_GRAPH,
                mission_id="mission-ft-c4",
            )
            assert submission.workflow_id.startswith(f"mc/{INSTALLATION}/biotech/run/")
            root = client.get_workflow_handle(submission.workflow_id)
            await asyncio.wait_for(root.result(), timeout=120)
        # The root delegated terminality to the ledger and saved exactly one typed result.
        (completion,) = activities.completions
        assert completion.run_id == run_id and completion.terminal_outcome is None
        assert await activities.results.get(completion.tenant_scope, SCOPE, run_id) is not None

        family_id = f"{submission.workflow_id}/family/1"
        family = client.get_workflow_handle(family_id)
        family_attributes = (await family.describe()).typed_search_attributes
        assert family_attributes.get(_key("mc_phase")) == "completed"
        family_history = await family.fetch_history()
        assert FAMILY_PHASE_PATCH in patch_ids(family_history)
        assert [item.get("mc_phase") for item in _mc_upserts(family_history)] == [
            '"executing"',
            '"completed"',
        ]

        service = RunListService(
            TemporalRunVisibility(client), _Ledger(authority), request_scope=SCOPE
        )
        by_phase = await _eventually(service, "phase='completed'", {run_id})
        row = by_phase.rows[0]
        assert row.mission_id == "mission-ft-c4"
        assert row.phases == ("completed",)
        assert row.temporal_status == "COMPLETED"
        assert row.lifecycle == "pending"  # the ledger is the authority (fake activities)
        await _eventually(service, "phase='completed' AND mission_id='mission-ft-c4'", {run_id})
        # The fixture's operations are native (no lane), so no execution carries `mc_lane`.
        assert (await service.list("lane='deep_agents'", actor=READER)).rows == ()
        await _eventually(service, "status='completed'", {run_id})
        assert (await service.list("phase='executing'", actor=READER)).rows == ()

        other = RunListService(
            TemporalRunVisibility(client), _Ledger(authority), request_scope=OTHER_APP_SCOPE
        )
        assert (await other.list(None, actor=READER)).rows == ()

        histories = [await root.fetch_history(), family_history]
        # Root, family and three operations; the family and the operations close `completed`.
        assert await _count(client, f"mc_run_id = '{run_id}'", 5) == 5
        listed_run = [item.id async for item in client.list_workflows(f"mc_run_id = '{run_id}'")]
        operation_ids = sorted(set(listed_run) - {submission.workflow_id, family_id})
        assert len(operation_ids) == 3
        # FT-G7: segment-boundary upserts only, never a re-upsert of an unchanged key.
        for operation_id in operation_ids:
            history = await client.get_workflow_handle(operation_id).fetch_history()
            assert MC_VISIBILITY_PATCH in patch_ids(history)
            upserts = _mc_upserts(history)
            assert [item.get("mc_phase") for item in upserts] == ['"executing"', '"completed"']
            assert '"mc_run_id"' not in str(upserts[1:]), "unchanged keys are not re-upserted"
            histories.append(history)
        assert await _count(client, f"mc_run_id = '{run_id}' AND mc_phase = 'completed'", 4) == 4
        assert await _count(client, f"mc_run_id = '{run_id}' AND mc_phase = 'executing'", 0) == 0
        # Root and family carry the mission; operations carry lane and phase instead.
        assert await _count(client, "mc_mission_id = 'mission-ft-c4'", 2) == 2

        # A fork of the run starts its root with `ForkedFromRunId`.
        async with Worker(
            client,
            task_queue=QUEUE,
            workflows=[MissionRunWorkflow, StageGraphWorkflow, MissionOperationWorkflow],
            workflow_runner=coordinator_workflow_runner(),
            activities=activities.functions,
        ):
            forked = await submitter.submit(
                replace(stage_run_input(_blueprint()), run_id=fork_id, request_scope=SCOPE),
                workflow_id="ignored",
                blueprint_family=BlueprintFamily.STAGE_GRAPH,
                parent_run_id=run_id,
                mission_id="mission-ft-c4",
            )
            await asyncio.wait_for(client.get_workflow_handle(forked.workflow_id).result(), 120)
        assert await _count(client, f"ForkedFromRunId = '{run_id}'", 1) == 1
        listed = [item async for item in client.list_workflows(f"ForkedFromRunId = '{run_id}'")]
        assert [item.id for item in listed] == [forked.workflow_id]
        assert listed[0].typed_search_attributes.get(_key("ForkedFromRunId")) == [run_id]
        assert listed[0].typed_search_attributes.get(_key("mc_run_id")) == [fork_id]
    replayer = Replayer(
        workflows=[MissionRunWorkflow, StageGraphWorkflow, MissionOperationWorkflow],
        workflow_runner=coordinator_workflow_runner(),
    )
    for history in histories:
        await replayer.replay_workflow(history)

"""MO-44: a chain-released consumer never launches without its Watcher Evaluator.

The starter starts the (idempotent) evaluator before the launch, so a delivery that fails
between the two is retried in full instead of being acknowledged as already started. The
launch is the real `RunLaunchService` over the real in-memory run control; the Temporal
submitter and the evaluator's start are the boundary doubles (OVE-238: replaces a
hand-written launch service).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from mission_control.application.chains.relay import ChainIntent, LaunchServiceChainStarter
from mission_control.application.execution.run_launch import RunLaunchService
from mission_control.domain.coordinator.launch import BlueprintFamily, WorkflowSubmission
from mission_control.domain.policies.contracts import CommandStatus, RunPhase, StartAction
from tests.support.run_control import command, request, service
from tests.support.unit.run_control.run_launch import SCOPE, _input


class Submitter:
    """The Temporal submission boundary: records each started root."""

    def __init__(self) -> None:
        self.started: list[str] = []

    async def submit(
        self,
        workflow_input: object,
        *,
        workflow_id: str,
        blueprint_family: BlueprintFamily,
        parent_run_id: str | None = None,
        mission_id: str | None = None,
    ) -> WorkflowSubmission:
        self.started.append(workflow_id)
        return WorkflowSubmission(workflow_id=workflow_id, temporal_run_id="temporal-run")


class Inputs:
    async def family_input(self, intent: ChainIntent) -> dict[str, Any]:
        return _input(intent.run_key)


class FlakyWatchers:
    """A ``WatcherStartPort`` whose first start fails, as a Temporal hiccup would; it records
    whether the root had been submitted when it started."""

    def __init__(self, submitter: Submitter) -> None:
        self.submitter = submitter
        self.started: list[tuple[str, bool]] = []
        self.failed = False

    async def start(self, request_scope: str, run_id: str) -> str:
        if not self.failed:
            self.failed = True
            raise ConnectionError("temporal unavailable for a moment")
        self.started.append((run_id, bool(self.submitter.started)))
        return f"watchers/{run_id}"


@pytest.mark.asyncio
async def test_a_failed_evaluator_start_is_retried_with_the_launch() -> None:
    run_control, _ = service()
    admitted = await run_control.admit(request(request_id=f"chain-watcher-{uuid.uuid4()}"))
    assert admitted.run_id is not None
    run_id = admitted.run_id
    intent = ChainIntent(
        intent_kind="start_run",
        delivery_key=f"chain-start:{run_id}",
        request_scope=SCOPE,
        chain_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        run_key=run_id,
        family="StageGraph",
        actor_ref="chain:test",
    )
    submitter = Submitter()
    watchers = FlakyWatchers(submitter)
    starter = LaunchServiceChainStarter(
        inputs=Inputs(),
        launches=RunLaunchService(run_control=run_control, submitter=submitter),
        watchers=watchers,
    )
    with pytest.raises(ConnectionError):
        await starter.start(intent)
    assert submitter.started == []  # nothing launched without its evaluator
    assert (await run_control.get_run(SCOPE, run_id)).phase == RunPhase.PENDING

    receipt = await starter.start(intent)  # the relay redelivers the intent
    assert not receipt.already_started
    assert len(submitter.started) == 1
    assert watchers.started == [(run_id, False)]  # started before the launch
    # The launched root's family starts the run: it leaves `pending`.
    run = await run_control.get_run(SCOPE, run_id)
    started = await run_control.execute(command(run_id, run.version, "start", StartAction()))
    assert started.status == CommandStatus.ACCEPTED

    again = await starter.start(intent)  # a later redelivery still reaches the evaluator
    assert again.already_started
    assert len(submitter.started) == 1
    assert watchers.started == [(run_id, False), (run_id, True)]

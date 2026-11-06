"""MO-44: a chain-released consumer never launches without its Watcher Evaluator.

The starter starts the (idempotent) evaluator before the launch, so a delivery that fails
between the two is retried in full instead of being acknowledged as already started.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest

from mission_control.application.chains.relay import ChainIntent, LaunchServiceChainStarter
from mission_control.application.execution.run_launch import (
    RunLaunchReceipt,
    RunLaunchRejected,
    RunLaunchRequest,
    RunLaunchService,
)
from mission_control.domain.policies.contracts import ActorContext

INTENT = ChainIntent(
    intent_kind="start_run",
    delivery_key="chain-start:run-1",
    request_scope="scope",
    chain_id=uuid.uuid4(),
    mission_id=uuid.uuid4(),
    run_id=uuid.uuid4(),
    run_key="run-1",
    family="GoalDirected",
    actor_ref="chain:test",
)


class Inputs:
    async def family_input(self, intent: ChainIntent) -> dict[str, Any]:
        return {}


class Launches:
    """A launch that leaves ``pending`` once: a second launch is ``run_not_pending``."""

    def __init__(self) -> None:
        self.launched: list[str] = []

    async def launch(self, request: RunLaunchRequest, actor: ActorContext) -> RunLaunchReceipt:
        if self.launched:
            raise RunLaunchRejected("run_not_pending", "the run is active")
        self.launched.append(request.run_id)
        return RunLaunchReceipt(
            run_id=request.run_id,
            request_scope=request.request_scope,
            family=request.family,
            workflow_id=f"belllabs-run/{request.run_id}",
            temporal_run_id="temporal-run",
            semantic_input_binding_ref="semantic-input:test",
            accepted_run_version=1,
        )


class FlakyWatchers:
    """A ``WatcherStartPort`` whose first start fails, as a Temporal hiccup would."""

    def __init__(self, launches: Launches) -> None:
        self.launches = launches
        self.started: list[tuple[str, bool]] = []
        self.failed = False

    async def start(self, request_scope: str, run_id: str) -> str:
        if not self.failed:
            self.failed = True
            raise ConnectionError("temporal unavailable for a moment")
        self.started.append((run_id, bool(self.launches.launched)))
        return f"watchers/{run_id}"


async def test_a_failed_evaluator_start_is_retried_with_the_launch() -> None:
    launches = Launches()
    watchers = FlakyWatchers(launches)
    starter = LaunchServiceChainStarter(
        inputs=Inputs(), launches=cast(RunLaunchService, launches), watchers=watchers
    )
    with pytest.raises(ConnectionError):
        await starter.start(INTENT)
    assert launches.launched == []  # nothing launched without its evaluator

    receipt = await starter.start(INTENT)  # the relay redelivers the intent
    assert not receipt.already_started
    assert launches.launched == ["run-1"]
    assert watchers.started == [("run-1", False)]  # started before the launch

    again = await starter.start(INTENT)  # a later redelivery still reaches the evaluator
    assert again.already_started
    assert watchers.started == [("run-1", False), ("run-1", True)]

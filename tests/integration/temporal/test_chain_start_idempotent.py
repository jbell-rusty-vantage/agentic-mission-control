"""FT-D2: the relay starts a released chain consumer idempotently (SPEC-04, ADR-0031).

Time-skipping Temporal environment: the chain relay delivers the same ``mc.chain.start_run``
intent twice (the acknowledgement of the first delivery is lost). The production starter goes
through the governed ``RunLaunchService`` and the mission-scoped ``TemporalWorkflowSubmitter``,
whose root id is derived from the admitted run and started with ``USE_EXISTING`` and
``REJECT_DUPLICATE``: both deliveries resolve to one workflow execution.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from mission_control.adapters.temporal.submission import TemporalWorkflowSubmitter
from mission_control.application.chains.relay import (
    ChainIntent,
    ChainIntentRelay,
    ChainStartReceipt,
    LaunchServiceChainStarter,
)
from mission_control.application.execution.run_launch import RunLaunchService
from mission_control.contracts.identities import mission_root_id, parse_request_scope
from tests.support.integration.temporal.chain_start_idempotent import (
    NOW,
    SCOPE,
    AdmittedRunInputs,
    OneShotStore,
)
from tests.support.run_control import request, service
from tests.support.temporal import workflow_environment


@pytest.mark.asyncio
async def test_delivering_the_same_start_intent_twice_yields_one_workflow() -> None:
    run_service, _ = service()
    admitted = await run_service.admit(request(request_scope=SCOPE, request_id=str(uuid4())))
    assert admitted.run_id is not None
    parsed = parse_request_scope(SCOPE)
    intent = ChainIntent(
        intent_kind="start_run",
        delivery_key=f"chain-start:{admitted.run_id}",
        request_scope=SCOPE,
        chain_id=uuid4(),
        mission_id=uuid4(),
        run_id=UUID(int=1),
        run_key=admitted.run_id,
        family="GoalDirected",
        initial_goal="Ingest the supplied evidence map",
        actor_ref="chain:test",
    )
    async with workflow_environment() as env:
        submitter = TemporalWorkflowSubmitter(
            env.client,
            stagegraph_task_queue="chain-test-stagegraph",
            goal_directed_task_queue="chain-test-goal",
            mission_installation_id=parsed.installation_id,
            mission_application_id=parsed.application_id,
        )
        inputs = AdmittedRunInputs(run_service)
        starter = LaunchServiceChainStarter(
            inputs=inputs,
            launches=RunLaunchService(run_control=run_service, submitter=submitter),
        )
        store = OneShotStore(intent)
        relay = ChainIntentRelay(store=store, starter=starter)
        first = await relay.relay_once(SCOPE, now=NOW)
        second = await relay.relay_once(SCOPE, now=NOW)
        assert first.delivered == second.delivered == (intent.delivery_key,)
        receipts: list[ChainStartReceipt] = [
            first.receipts[intent.delivery_key],
            second.receipts[intent.delivery_key],
        ]
        workflow_id = mission_root_id(SCOPE, admitted.run_id)
        assert {receipt.workflow_id for receipt in receipts} == {workflow_id}
        assert receipts[0].temporal_run_id == receipts[1].temporal_run_id
        description = await env.client.get_workflow_handle(workflow_id).describe()
        assert description.run_id == receipts[0].temporal_run_id
        assert inputs.calls == 2
        # A third delivery after acknowledgement finds nothing to deliver.
        assert (await relay.relay_once(SCOPE, now=NOW)).delivered == ()

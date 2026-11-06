"""WI-22 / OVE-183: a durable transition reaction runs as an ordinary admitted operation on
Temporal, once, across a relay crash after the start (time-skipping server, disposable
PostgreSQL 17 with 0061).

The reaction state (binding, captured transition, activation, ``mc.reaction.dispatch`` intent)
is on PostgreSQL. The production ``AdmittedReactionOperations`` binds the run's admitted
template to the activation: the Deep Agents lane rebinds its sealed binding (OC-R2), run control
reserves the activation's spend, and ``TemporalReactionStarter`` starts the ordinary
``mc.operation.v1`` under the run-derived operation id. The operation boundary is the RRM-004
harness (a real ``create_deep_agent`` graph with a scripted model and in-memory run control). The
first relay dies after Temporal accepted the start and before the acknowledgement commits; a
fresh relay re-delivers, the start attaches to the same workflow, and the operation runs one
cognition, its history replaying.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.postgres.reactions import (
    PostgresReactionAuthority,
    PostgresReactionStore,
)
from mission_control.adapters.temporal.operation_activities import (
    OperationExecutionActivities,
    parse_operation_result,
)
from mission_control.adapters.temporal.reaction_dispatch import TemporalReactionStarter
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import MissionOperationWorkflow
from mission_control.application.reactions.operations import (
    AdmittedReactionOperations,
    RunControlReactionBudget,
)
from mission_control.application.reactions.service import (
    ReactionBindingService,
    ReactionDispatchReceipt,
    ReactionRelay,
)
from mission_control.contracts.identities import mission_operation_id
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.reactions.contracts import (
    DurableTransition,
    ReactionActivation,
    ReactionBinding,
    ReactionDeclaration,
    TransitionKind,
)
from tests.fixtures.checkpoint_recovery import recovery_harness, stage_recovery_unit
from tests.fixtures.lane_bindings import LANE_REBINDERS
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    common_database,
    migration_paths_with,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "scripts/release_170/0061_durable_transition_reactions.sql"
)
WORKFLOW_QUEUE = "wi22-reaction-operations"
AT = datetime(2026, 10, 28, 9, tzinfo=UTC)


@pytest_asyncio.fixture
async def db() -> AsyncIterator[CommonDatabase]:
    async with common_database(paths=migration_paths_with(MIGRATION)) as database:
        yield database


@pytest_asyncio.fixture
async def pool(db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:
    created = await db.pool()
    try:
        yield created
    finally:
        await created.close()


async def _environment() -> WorkflowEnvironment:
    existing = os.environ.get("MISSION_CONTROL_TEST_TEMPORAL_SERVER") or None
    try:
        return await WorkflowEnvironment.start_time_skipping(test_server_existing_path=existing)
    except RuntimeError as error:
        pytest.skip(f"Temporal test server is unavailable: {error}")


class Crash(BaseException):
    """The relay process dying after Temporal accepted the start."""


class Templates:
    def __init__(self, template: OperationExecutionRequest) -> None:
        self._template = template

    async def get_template(self, **_: object) -> OperationExecutionRequest:
        return self._template


class CrashAfterStart:
    """The production port, killed once after its start returned."""

    def __init__(self, inner: AdmittedReactionOperations) -> None:
        self._inner = inner
        self.receipts: list[ReactionDispatchReceipt] = []
        self.requests: list[OperationWorkflowRequest] = []

    async def dispatch(
        self,
        scope: str,
        activation: ReactionActivation,
        binding: ReactionBinding,
        transition: DurableTransition,
    ) -> ReactionDispatchReceipt:
        self.requests.append(await self._inner.materialize(scope, activation, binding, transition))
        receipt = await self._inner.dispatch(scope, activation, binding, transition)
        self.receipts.append(receipt)
        if len(self.receipts) == 1:
            raise Crash("killed after the start, before the acknowledgement")
        return receipt


async def test_a_reaction_runs_once_as_an_ordinary_operation_across_a_relay_crash(
    db: CommonDatabase, pool: asyncpg.Pool
) -> None:
    scope = db.scope()
    environment = await _environment()
    async with environment:
        harness = await recovery_harness(request_scope=scope)
        template = await harness.request(
            stage_recovery_unit(harness.run_id, "reaction-template", request_scope=scope)
        )
        store = PostgresReactionStore(pool)
        [binding] = await ReactionBindingService(store).attach(
            scope,
            harness.run_id,
            [
                ReactionDeclaration.model_validate(
                    {
                        "id": "repair",
                        "on": {"event": "fulfillment.decided"},
                        "where": "event.disposition == 'unfulfilled'",
                        "operation": {"template": "reviewer", "purpose": "Repair the draft."},
                        "grants": {
                            "tools": sorted(tool.tool_id for tool in template.tools),
                            "mcp_servers": sorted(s.server_id for s in template.mcp_servers),
                        },
                        "limits": {
                            "time": {"operation_seconds": 60},
                            "spend": {"tokens_per_activation": 10, "max_tokens": 30},
                        },
                    }
                )
            ],
        )
        event = DurableTransition.of(
            TransitionKind.FULFILLMENT_DECIDED,
            "fulfillment-1",
            run_id=harness.run_id,
            captured_at=AT,
            facts={"obligation_key": "draft", "disposition": "unfulfilled"},
        )
        assert await store.record_transition(scope, event)
        assert await store.record_transition(scope, event) is False

        def relay(owner: str, operations: Any, relay_pool: asyncpg.Pool) -> ReactionRelay:
            return ReactionRelay(
                store=PostgresReactionStore(relay_pool),
                authority=PostgresReactionAuthority(relay_pool),
                operations=operations,
                lease_owner=owner,
            )

        def production() -> AdmittedReactionOperations:
            return AdmittedReactionOperations(
                templates=Templates(template),
                budget=RunControlReactionBudget(harness.run_control),
                starter=TemporalReactionStarter(environment.client, task_queue=WORKFLOW_QUEUE),
                operation_bindings=harness.bindings,
                lane_bindings=LANE_REBINDERS,
            )

        activities = OperationExecutionActivities(harness.service, worker_identity="wi22-worker")
        with environment.auto_time_skipping_disabled():
            async with (
                Worker(
                    environment.client,
                    task_queue=WORKFLOW_QUEUE,
                    workflows=[MissionOperationWorkflow],
                    workflow_runner=coordinator_workflow_runner(),
                ),
                Worker(
                    environment.client,
                    task_queue=harness.binding.task_queue,
                    activities=[activities.execute, activities.cancel],
                ),
            ):
                dying = CrashAfterStart(production())
                admitted = await relay("relay-1", dying, pool).admit_once(
                    scope, now=datetime.now(UTC)
                )
                [activation] = admitted.activations
                assert (
                    activation.state == "admitted" and activation.binding_id == binding.binding_id
                )
                with pytest.raises(Crash):
                    await relay("relay-1", dying, pool).dispatch_once(scope, now=datetime.now(UTC))
                pending = await store.activation(scope, activation.activation_id)
                assert pending is not None and pending.state == "admitted"
                # A fresh relay (new pool, new store, new port) after the dead lease expires.
                fresh_pool = await db.pool()
                try:
                    recovery = CrashAfterStart(production())
                    recovery.receipts.append(dying.receipts[0])  # the port no longer crashes
                    report = await relay("relay-2", recovery, fresh_pool).dispatch_once(
                        scope, now=datetime.now(UTC) + timedelta(seconds=61)
                    )
                finally:
                    await fresh_pool.close()
                assert report.dispatched == (activation.activation_id,)
                first, second = dying.receipts[0], recovery.receipts[-1]
                assert first.workflow_id == second.workflow_id
                handle = environment.client.get_workflow_handle_for(
                    MissionOperationWorkflow.run, first.workflow_id
                )
                result = await asyncio.wait_for(handle.result(), timeout=120)
                history = await handle.fetch_history()
                await Replayer(
                    workflows=[MissionOperationWorkflow],
                    workflow_runner=coordinator_workflow_runner(),
                ).replay_workflow(history)
                description = await handle.describe()
    request = dying.requests[0]
    operation = request.operation
    assert operation.identity.operation_id == activation.operation_id
    assert first.workflow_id == mission_operation_id(
        scope, harness.run_id, request.semantic_attempt_id
    )
    assert recovery.requests[-1] == request, "the redelivery materialized the same request"
    assert result.disposition == "completed", result
    settled = parse_operation_result(result.result)
    assert settled.status == "completed"
    # One cognition for one logical reaction: one agent invocation whose scripted model takes a
    # tool turn and then answers (one human message throughout, never a restarted run).
    assert harness.runtime.invocations == 1
    assert harness.model.calls == [(1, 0), (1, 1)]
    # The second start attached: the workflow's first execution is the one that ran.
    assert description.run_id == first.temporal_run_id == second.temporal_run_id
    budget = await harness.run_control.get_budget(scope, harness.run_id)
    assert f"reaction:{activation.activation_id}" in budget.model_dump_json()
    final = await store.activation(scope, activation.activation_id)
    assert final is not None and final.state == "dispatched"
    assert final.workflow_id == first.workflow_id
    print(
        "WI-22 EVIDENCE reaction dispatch:",
        {
            "workflow_id": first.workflow_id,
            "second_start_attached": second.workflow_id == first.workflow_id,
            "model_calls": harness.model.calls,
            "invocations": harness.runtime.invocations,
            "disposition": result.disposition,
            "history_events": len(history.events),
        },
    )

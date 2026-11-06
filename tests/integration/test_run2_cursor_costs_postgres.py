"""Disposable restricted PostgreSQL cost reconciliation with real journal/payload replay."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio

from mission_control.adapters.cursor.costs import (
    CursorCostReconciler,
)
from mission_control.adapters.postgres.cursor_costs import PostgresCursorCosts
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.operations.checkpoint_lineage import (
    PostgresCheckpointLineageRepository,
)
from mission_control.adapters.postgres.operations.operation_binding_repository import (
    PostgresOperationBindingRepository,
)
from mission_control.adapters.postgres.operations.operation_journal import (
    PostgresAtomicOperationJournalRepository,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.operation_execution import _binding_for
from mission_control.application.execution.operations.operation_journal import (
    OperationJournalService,
)
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import OperationSettlement, RuntimeUsage
from mission_control.domain.execution.cursor_costs import (
    COST_DIMENSION,
    CostRequest,
)
from mission_control.domain.execution.lanes import CursorExecutionBinding
from mission_control.domain.frames.contracts import FrameKind, FrameObservation, LaneProfile
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    BudgetDimensionLimit,
    BudgetEnvelope,
    StartAction,
)
from tests.fixtures.checkpoint_lineage import activity_attempt, namespace_claim, stage_unit
from tests.fixtures.lane_turns import cursor_operation
from tests.fixtures.mission_control_common_db import (
    CommonDatabase,
    create_common_database,
    drop_common_database,
)
from tests.fixtures.provider_frames import harness_start
from tests.integration.postgres.runtime_common import scoped_command, scoped_request
from tests.unit.run_control.test_run_control import actor, service

NOW = datetime(2026, 10, 14, tzinfo=UTC)
COMPONENT = (
    Path(__file__).resolve().parents[2]
    / "packages/mission-control-db-contract/releases/1.4.1/component"
)


@pytest_asyncio.fixture
async def common_db() -> AsyncIterator[CommonDatabase]:
    # Explicit successor SQL proof; the fixture's unqualified attestation is not
    # evidence of an installed release. The installer qualification owns that.
    paths = sorted((COMPONENT / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
    assert paths and (COMPONENT / "release-spec.json").is_file()
    database = await create_common_database(paths=paths, component_version="1.4.1")
    try:
        yield database
    finally:
        await drop_common_database(database)


@pytest.mark.asyncio
@pytest.mark.common_db
@pytest.mark.parametrize(
    "history",
    [
        "complete",
        "legacy",
        "drift",
        "missing_predecessor",
        "missing_current_generation",
        "subordinate_predecessor",
        "unidentified_predecessor",
        "unidentified_session",
        "overflow",
    ],
)
async def test_real_journal_payload_delayed_currency_replay(
    common_db: CommonDatabase, monkeypatch: pytest.MonkeyPatch, history: str
) -> None:
    pool = await common_db.pool("mission_control_runtime", max_size=4)
    try:
        scope = common_db.scope("tenant-1")
        run_control, _ = service(PostgresRunControlRepository(pool))
        request = scoped_request(common_db, request_id=f"cursor-cost-{uuid4()}")
        dimensions = tuple(
            BudgetDimensionLimit(
                dimension=COST_DIMENSION, applicability=BudgetApplicability.BOUNDED, hard_cap=1000
            )
            if d.dimension == COST_DIMENSION
            else d
            for d in request.budget_envelope.dimensions
        )
        request = request.model_copy(
            update={
                "budget_envelope": BudgetEnvelope(
                    dimensions=dimensions,
                    baseline_reservations={"tokens.total": 20, COST_DIMENSION: 100},
                )
            }
        )
        admission = await run_control.admit(request)
        assert admission.run_id is not None
        await run_control.execute(
            scoped_command(common_db, admission.run_id, 1, "start", StartAction())
        )
        unit = stage_unit(
            request_scope=scope, run_id=admission.run_id, operation_id="cursor-cost-operation"
        )
        operation = cursor_operation("cursor_cloud", request_scope=scope)
        operation = operation.model_copy(
            update={
                "identity": operation.identity.model_copy(
                    update={"run_id": admission.run_id, "operation_id": unit.semantic_operation_id}
                ),
                "runtime_unit": unit,
                "run_control_revision": 2,
                "budget_reservation_id": "baseline",
                "budget_limits": {COST_DIMENSION: 100},
            }
        )
        binding = _binding_for(operation, sha256_digest(operation))
        assert CursorExecutionBinding.carried_by(binding) is not None
        await PostgresOperationBindingRepository(pool).create_binding(binding, request_scope=scope)
        await PostgresCheckpointLineageRepository(pool).record_attempt(
            unit=unit,
            execution_generation=1,
            attempt=activity_attempt(1),
            binding_id=binding.binding_id,
            binding_digest=binding.effective_configuration_digest,
            namespace=namespace_claim(unit, binding_digest=binding.effective_configuration_digest),
            dispatching=True,
            observed_at=NOW,
        )
        frames = PostgresFrameRepository(pool)
        start = harness_start(
            request_scope=scope,
            run_key=admission.run_id,
            activation_key=unit.unit_key,
            lane=LaneProfile.CURSOR_CLOUD,
            native_session_ref="native-agent-1",
        )
        start = start.model_copy(
            update={
                "intended_binding_digest": CursorExecutionBinding.carried_by(
                    binding
                ).binding_digest,
                "native_identity": {"semantic_attempt_key": binding.semantic_attempt_key},
            }
        )
        writer = FrameWriter(frames, await frames.open_execution(start))
        await writer.write(
            [
                FrameObservation(
                    provider_key="cost-turn-1",
                    raw_kind="fixture.cost",
                    kind=FrameKind.STATUS,
                    native_session_ref="native-agent-1",
                    native_turn_ref="native-run-1",
                ),
            ]
        )
        # A technical restart retains the old run; duplicate native identity in the
        # new generation is evidence of the same bill, never a second charge.
        writer = FrameWriter(
            frames, await frames.open_execution(start.model_copy(update={"generation": 2}))
        )
        await writer.write(
            [
                FrameObservation(
                    provider_key="cost-turn-2",
                    raw_kind="fixture.cost",
                    kind=FrameKind.STATUS,
                    native_session_ref="native-agent-2",
                    native_turn_ref="native-run-2",
                ),
                FrameObservation(
                    provider_key="cost-turn-1-replay",
                    raw_kind="fixture.cost",
                    kind=FrameKind.STATUS,
                    native_session_ref="native-agent-1",
                    native_turn_ref="native-run-1",
                ),
                FrameObservation(
                    provider_key="subordinate",
                    raw_kind="fixture.cost",
                    kind=FrameKind.STATUS,
                    native_session_ref="child-agent",
                    native_turn_ref="child-run",
                    subordinate_ref="child",
                ),
            ]
        )
        if history == "complete":
            # Generations need not start at one. Another execution can reattach
            # to the same bill; a different semantic attempt must be excluded.
            for semantic, digest, native_run in [
                (
                    binding.semantic_attempt_key,
                    CursorExecutionBinding.carried_by(binding).binding_digest,
                    "native-run-1",
                ),
                ("other-semantic-attempt", "sha256:" + "e" * 64, "unrelated-run"),
            ]:
                extra = start.model_copy(
                    update={
                        "harness_execution_id": uuid4(),
                        "generation": 7,
                        "native_identity": {"semantic_attempt_key": semantic},
                        "intended_binding_digest": digest,
                    }
                )
                await FrameWriter(frames, await frames.open_execution(extra)).write(
                    [
                        FrameObservation(
                            provider_key="extra",
                            raw_kind="fixture.cost",
                            kind=FrameKind.STATUS,
                            native_session_ref="native-agent-1",
                            native_turn_ref=native_run,
                        )
                    ]
                )
        elif history == "missing_current_generation":
            await frames.open_execution(start.model_copy(update={"generation": 3}))
        elif history == "unidentified_session":
            await writer.write(
                [
                    FrameObservation(
                        provider_key="unidentified-session",
                        raw_kind="fixture.cost",
                        kind=FrameKind.STATUS,
                        native_session_ref="unknown-agent",
                    )
                ]
            )
        elif history == "overflow":
            monkeypatch.setattr(
                "mission_control.adapters.postgres.cursor_costs.MAX_BILLING_FRAMES", 2
            )
        elif history != "complete":
            predecessor = start.model_copy(update={"harness_execution_id": uuid4()})
            if history == "legacy":
                predecessor = predecessor.model_copy(update={"native_identity": {}})
            elif history == "drift":
                predecessor = predecessor.model_copy(
                    update={"intended_binding_digest": "sha256:" + "d" * 64}
                )
            predecessor_writer = FrameWriter(frames, await frames.open_execution(predecessor))
            if history != "missing_predecessor":
                await predecessor_writer.write(
                    [
                        FrameObservation(
                            provider_key="predecessor",
                            raw_kind="fixture.cost",
                            kind=FrameKind.STATUS,
                            native_session_ref="predecessor-agent",
                            native_turn_ref=(
                                None if history == "unidentified_predecessor" else "predecessor-run"
                            ),
                            subordinate_ref="child"
                            if history == "subordinate_predecessor"
                            else None,
                        )
                    ]
                )
        payloads = InMemoryArtifactPayloadStore()
        journal = PostgresAtomicOperationJournalRepository(pool)
        coordinator = JournaledOperationExecutionCoordinator(
            journal=OperationJournalService(journal),
            run_control=run_control,
            results=payloads,
            actor=actor(),
        )
        acquired = await coordinator.acquire(binding, claimed_by="cost-test")
        assert acquired.claim is not None
        initial = OperationSettlement(
            settlement_id="cursor-cost-settlement",
            binding_id=binding.binding_id,
            status="completed",
            output_text="immutable",
            usage=RuntimeUsage(
                amounts={COST_DIMENSION: 10}, pending_external_amounts={COST_DIMENSION: 90}
            ),
            settled_at=NOW,
        )
        await coordinator.settle(binding, acquired.claim, initial, started_at=NOW)
        snapshot = dict(payloads.payloads)
        # No operation.settlement/1 document is written: the coordinator's digest-bound
        # journal manifest is the source of the original immutable settlement.
        assert (
            await PostgresOperationBindingRepository(pool).get_settlement(
                binding.binding_id, request_scope=scope
            )
            is None
        )
        costs = AsyncMock(side_effect=[None, None, 20, 40])
        repository = PostgresCursorCosts(pool, coordinator.get_settlement)
        reconciler = CursorCostReconciler(repository, costs, coordinator, clock=lambda: NOW)
        cost_request = CostRequest(
            request_scope=scope, binding_id=binding.binding_id, activity_task_queue="fixture-lane"
        )
        if history != "complete":
            context = await repository.context(cost_request)
            assert not context.attributable and context.native_runs == ()
            for read_no in range(3):
                result = await reconciler.observe(cost_request, read_no)
                assert result.state == "unattributable" and result.observed_micros is None
            costs.assert_not_awaited()
            budget = await run_control.get_budget(scope, admission.run_id)
            assert budget.consumed[COST_DIMENSION] == 10
            assert budget.pending_settlement[COST_DIMENSION] == 90
            latest = await journal.get_settlement(scope, acquired.claim.effect_claim_id)
            assert latest is not None and latest.settlement_revision == 1
            assert payloads.payloads == snapshot
            return
        context = await repository.context(cost_request)
        assert context.attributable
        assert [(run.agent_id, run.run_id) for run in context.native_runs] == [
            ("native-agent-1", "native-run-1"),
            ("native-agent-2", "native-run-2"),
        ]
        assert (await reconciler.observe(cost_request, 0)).state == "unknown"
        assert (await reconciler.observe(cost_request, 1)).observed_micros == 60
        # New process-shaped adapter observes revision2 and never re-reads/debits again.
        replay = CursorCostReconciler(
            PostgresCursorCosts(pool, coordinator.get_settlement),
            costs,
            coordinator,
            clock=lambda: NOW,
        )
        assert (await replay.observe(cost_request, 1)).state == "settled"
        assert costs.await_count == 4
        budget = await run_control.get_budget(scope, admission.run_id)
        assert budget.consumed[COST_DIMENSION] == 60
        assert budget.pending_settlement[COST_DIMENSION] == 0
        assert payloads.payloads == snapshot
        latest = await journal.get_settlement(scope, acquired.claim.effect_claim_id)
        assert latest is not None and latest.settlement_revision == 2
    finally:
        await pool.close()

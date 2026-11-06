"""Restricted-role PG authority proof; scripted lane and Temporal port are fixtures.

No provider is contacted. All run/family/journal/binding/frame/native rows are created
through production repositories/services. Artifact custody and catalog are memory fixtures.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from mission_control.adapters.postgres.closed_workflow import PostgresClosedWorkflowAuthority
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
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
from mission_control.application.execution.harness.lane_turns import LaneTurnService
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
)
from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.operation_execution import (
    RunControlOperationAuthority,
)
from mission_control.application.execution.operations.operation_journal import (
    OperationJournalService,
)
from mission_control.application.programs.service import register_stagegraph_family_mutations
from mission_control.application.recovery.closed_workflow import (
    ClosedExecution,
    ClosedWorkflowEvidence,
    ClosedWorkflowRecovery,
)
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.contracts.identities import mission_root_id
from mission_control.contracts.runtime_contracts import ClosedWorkflowRecoveryRequest
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    ExecutionTarget,
    RecordUsageAction,
    RunOutcome,
    StartAction,
)
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    ProducerLiability,
    ResultDecision,
    StageCandidateIdentity,
    StageGraphAcceptedProjection,
    StageGraphDecisionMutation,
    StageInstanceProjection,
)
from tests.fixtures.checkpoint_recovery import (
    FixtureControlPlane,
    recovery_harness,
    stage_recovery_unit,
)
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.lane_turns import ScriptedSessionLane, cursor_operation, scripted_frames
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.unit.run_control.test_run_control import actor, command, service

pytestmark = pytest.mark.common_db


class TargetedControls:
    """Fixture specifies the real StartAction target; all authority remains RunControl."""

    def __init__(self, controls):
        self.controls = controls

    def __getattr__(self, name):
        return getattr(self.controls, name)

    async def execute(self, value):
        if isinstance(value.action, StartAction):
            root = mission_root_id(value.request_scope, value.run_id)
            value = value.model_copy(
                update={
                    "action": StartAction(
                        execution_target=ExecutionTarget(
                            family="StageGraph",
                            root_workflow_id=root,
                            family_workflow_id=root + "/family",
                        )
                    )
                }
            )
        return await self.controls.execute(value)


class Signals:
    def heartbeat(self, *_args):
        pass

    def prior_cursor(self):
        return None

    def cancel_requested(self):
        return False


async def test_real_restricted_pg_closed_native_authority_and_terminal_reducer(
    common_db: CommonDatabase,
):
    pool = await common_db.pool("mission_control_runtime")
    family_pool = await common_db.pool("mission_control_family_writer")
    try:
        controls, _ = service(PostgresRunControlRepository(pool, family_writer_pool=family_pool))
        register_stagegraph_family_mutations(controls._family_admissions)
        scope = common_db.scope()
        harness = await recovery_harness(
            run_control=TargetedControls(controls), request_scope=scope, real_authority=True
        )
        # Production lane admission's lineage observer creates the real activation/
        # attempt authority that PostgresFrameRepository.open_execution requires.
        lineage = PostgresCheckpointLineageRepository(pool)
        harness.service._lineage = CheckpointLineageService(lineage, clock=harness.clock)
        unit = stage_recovery_unit(harness.run_id, request_scope=scope)
        reserved = await harness.request(unit)
        operation = OperationExecutionRequest.model_validate(
            {
                **reserved.model_dump(mode="python"),
                "execution_runtime": "cursor",
                "lane_profile": "cursor_local",
                **lane_fields(None),
                "native_placement": None,
                **lane_fields(None),
                **lane_fields(CursorExecutionBinding.carried_by(cursor_operation())),
            }
        )
        bindings = PostgresOperationBindingRepository(pool)
        harness.service._bindings = bindings
        coordinator = JournaledOperationExecutionCoordinator(
            journal=OperationJournalService(PostgresAtomicOperationJournalRepository(pool)),
            run_control=controls,
            results=harness.results,
            actor=actor(),
        )
        harness.service._journal = coordinator
        harness.service._authority = RunControlOperationAuthority(
            controls, FixtureControlPlane(operation)
        )
        native_frames = scripted_frames(0)
        # This fixture's genuine terminal marker supplies the observed outcome;
        # an earlier usage-only TurnEndedUpdate correctly remains unknown in PG.
        native_frames = [
            (kind, {**body, "outcome": "succeeded"} if kind == "TurnEndedUpdate" else body)
            for kind, body in native_frames
        ]
        lane = ScriptedSessionLane(frames=native_frames)
        registry = LaneRegistry([lane], allow_unqualified=True)
        harness.service._lanes = registry
        turns = LaneTurnService(
            lanes=registry,
            boundary=harness.service,
            frames=PostgresFrameRepository(pool),
            states=PostgresLaneExecutionStateStore(pool),
            sessions=WorkerSessionManager(owner_ref="closed-recovery-fixture"),
            clock=harness.clock,
        )
        settled = await turns.turn(
            LaneTurnRequest(operation=operation, lane_profile="cursor_local", generation=1),
            Signals(),
            attempt=harness.attempt(operation),
        )
        assert settled.done and settled.operation_result is not None
        assert lane.sends and not lane.cancels
        binding = await bindings.get_binding(operation.identity.semantic_key, request_scope=scope)
        assert binding is not None
        run = await controls.get_run(scope, harness.run_id)
        budget = await controls.get_budget(scope, harness.run_id)
        release = {
            key: value for key, value in budget.reservations.get("baseline", {}).items() if value
        }
        request_ref = "operation-request:" + sha256_digest(binding.semantic_attempt_key)[7:]
        family = StageGraphAcceptedProjection(
            ExecutionIdentity(harness.run_id),
            1,
            run.version + 1,
            stages={
                "probe": StageInstanceProjection(
                    StageCandidateIdentity("draft", 0, "NO_MAPPED_INSTANCE", 0, 0, "default"),
                    status="completed",
                    semantic_attempt=1,
                    admitted_operation_request_ref=request_ref,
                )
            },
            producer_liabilities={
                binding.semantic_attempt_key: ProducerLiability(
                    binding.semantic_attempt_key,
                    operation.budget_reservation_id,
                    child_closed_or_quiesced=True,
                    reservations_and_usage_settled=True,
                    effects_settled=True,
                    cancellation_reconciled=True,
                    result_decision=ResultDecision.ADMIT,
                )
            },
        )
        mutation = StageGraphDecisionMutation(
            mutation_id="closed-fixture-result",
            request_scope=scope,
            run_id=harness.run_id,
            expected_family_version=0,
            exact_operation_request_ref=request_ref,
            decided_at=datetime.now(UTC),
            decision_kind="result_decided",
            prior_projection_digest="sha256:" + "0" * 64,
            next_projection_digest=family.digest,
            decision_payload={"projection": asdict(family)},
        )
        release_command = command(
            harness.run_id,
            run.version,
            "release-unused-baseline",
            RecordUsageAction(
                usage_id="unused-baseline",
                reservation_id="baseline",
                actual_amounts={},
                release_amounts=release,
            ),
        ).model_copy(update={"request_scope": scope})
        accepted = await controls.execute_family_admission(release_command, mutation)
        assert accepted.command_result.status == CommandStatus.ACCEPTED
        run = await controls.get_run(scope, harness.run_id)
        cancelled = await controls.execute(
            command(harness.run_id, run.version, "cancel-once", CancelAction()).model_copy(
                update={"request_scope": scope}
            )
        )
        assert cancelled.status == CommandStatus.ACCEPTED
        # Delivery remains pending until the real terminalizing commit applies cancel.
        from mission_control.domain.policies.contracts import BoundaryCommandReceipt, ReceiptState

        pending = await controls.list_boundary_commands(scope, harness.run_id)
        cancel = next(item for item in pending if item.command.command_id == "cancel-once")
        await controls.record_boundary_receipt(
            scope,
            BoundaryCommandReceipt(
                request_scope=scope,
                run_id=harness.run_id,
                command_id="cancel-once",
                idempotency_issuer=cancel.command.idempotency_issuer,
                ordinal=cancel.receipts[-1].ordinal + 1,
                state=ReceiptState.DELIVERED,
                recorded_by="fixture-delivery",
                recorded_at=datetime.now(UTC),
            ),
        )
        run = await controls.get_run(scope, harness.run_id)
        reader = PostgresClosedWorkflowAuthority(pool)
        authority = await reader.read(run)
        before_budget = await controls.get_budget(scope, harness.run_id)
        before_effects = await controls.get_effects(scope, harness.run_id)
        observer = AsyncMock()
        now = datetime.now(UTC)
        observer.observe.return_value = ClosedWorkflowEvidence(
            scope,
            harness.run_id,
            1,
            1,
            now,
            tuple(
                ClosedExecution(w, str(uuid4()), "FAILED", 16, "sha256:" + "f" * 64, True)
                for w in (
                    run.execution_target.root_workflow_id,
                    run.execution_target.family_workflow_id,
                    *authority.producer_workflow_ids,
                )
            ),
        )
        recovery = ClosedWorkflowRecovery(controls, reader, observer, clock=lambda: now)
        body = ClosedWorkflowRecoveryRequest(request_id=uuid4(), expected_version=run.version)
        result = await recovery.recover(scope, harness.run_id, body, actor())
        assert (
            result.status == CommandStatus.ACCEPTED
            and result.terminal_outcome == RunOutcome.CANCELLED
        )
        assert await controls.get_budget(scope, harness.run_id) == before_budget
        assert await controls.get_effects(scope, harness.run_id) == before_effects
        applied = await controls.get_boundary_command(
            scope, harness.run_id, cancel.command.idempotency_issuer, "cancel-once"
        )
        assert applied is not None and applied.state == ReceiptState.APPLIED
        assert await recovery.recover(scope, harness.run_id, body, actor()) == result
        replayed_turn = await turns.turn(
            LaneTurnRequest(operation=operation, lane_profile="cursor_local", generation=1),
            Signals(),
            attempt=harness.attempt(operation),
        )
        assert replayed_turn.done
        assert len(lane.sends) == 1 and not lane.cancels
    finally:
        await family_pool.close()
        await pool.close()

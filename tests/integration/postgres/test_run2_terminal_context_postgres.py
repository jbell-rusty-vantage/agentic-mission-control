"""Restricted-role adoption context SQL proof; workflow inputs and lane are fixtures.

No provider is contacted. All run/family/journal/binding/frame/native rows are created
through production repositories/services. Artifact custody and catalog are memory fixtures.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

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
from mission_control.adapters.postgres.terminal_adoption_context import (
    PostgresTerminalAdoptionContextReader,
)
from mission_control.adapters.temporal.terminal_adoption_inputs import TerminalWorkflowInputs
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
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
from mission_control.application.recovery.terminal_lane_adoption import (
    AdoptionIdentity,
    AdoptionInspectionRefused,
)
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.contracts.identities import mission_root_id
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
)
from mission_control.domain.execution.lane_turns import LaneTurnRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    ExecutionTarget,
    RecordUsageAction,
    ReserveBudgetAction,
    StartAction,
)
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    ProducerLiability,
    ResultDecision,
    StageCandidateIdentity,
    StageGraphAcceptedProjection,
    StageGraphDecisionMutation,
    StageGraphRunInput,
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
from tests.integration.postgres.runtime_common import owner_rows
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


async def test_restricted_context_recovers_historical_family_and_current_authority(
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
        historical = family
        advanced = replace(family, family_version=2, run_version=run.version + 1)
        next_mutation = mutation.model_copy(
            update={
                "mutation_id": "advanced-head",
                "expected_family_version": 1,
                "prior_projection_digest": historical.digest,
                "next_projection_digest": advanced.digest,
                "decision_payload": {"projection": asdict(advanced)},
            }
        )
        # The baseline was released above. Advance through a fresh, genuine
        # reservation; record_usage always requires an existing reservation.
        advance = await controls.execute_family_admission(
            command(
                harness.run_id,
                run.version,
                "advance-head",
                ReserveBudgetAction(
                    reservation_id="advance-head-fixture",
                    amounts={"tokens.total": 1},
                ),
            ).model_copy(update={"request_scope": scope}),
            next_mutation,
        )
        assert advance.command_result.status == CommandStatus.ACCEPTED, advance.command_result
        run = await controls.get_run(scope, harness.run_id)
        cancelled = await controls.execute(
            command(harness.run_id, run.version, "cancel-once", CancelAction()).model_copy(
                update={"request_scope": scope}
            )
        )
        assert cancelled.status == CommandStatus.ACCEPTED
        run = await controls.get_run(scope, harness.run_id)
        commands = await controls.list_boundary_commands(scope, harness.run_id)
        cancel = next(item for item in commands if item.command.command_id == "cancel-once")
        rows = await owner_rows(common_db, "SELECT run_id FROM mission_control.mission_run")
        assert len(rows) == 1
        hid = LaneExecutionIdentity.of(operation, "cursor_local", 1).harness_execution_id
        identity = AdoptionIdentity(
            scope, harness.run_id, str(rows[0]["run_id"]), str(hid), 1, "agent-fake-1", "run-fake-1"
        )
        graph = build_stagegraph_v2(
            logical_id="test.postgres.recovery",
            title="PostgreSQL recovery",
            description="Read a canonical typed admitted blueprint",
            stages=(StageGraphStageSpec("probe"),),
        )
        family_input = StageGraphRunInput(
            run_id=harness.run_id,
            request_scope=scope,
            effective_configuration_digest=operation.effective_configuration_digest,
            workflow_type_digest=run.workflow_type_ref.digest,
            blueprint_digest=sha256_digest(graph),
            blueprint=graph.model_dump(mode="json"),
            correlation_id="fixture-context",
        )
        inputs = TerminalWorkflowInputs(
            OperationWorkflowRequest(
                semantic_attempt_id=operation.identity.semantic_key,
                operation_kind="bound_operation",
                operation=operation,
            ),
            family_input,
            "fixture-operation-run",
            "fixture-family-run",
        )
        reader = PostgresTerminalAdoptionContextReader(
            pool,
            identity=identity,
            inputs=inputs,
            cancel_issuer=cancel.command.idempotency_issuer,
            cancel_command_id="cancel-once",
        )
        context = await reader.read(identity, historical.digest)
        assert context.operation == operation
        assert context.family.projection == historical
        assert context.family.projection.digest != advanced.digest
        assert context.authority.family_head_digest == advanced.digest
        assert context.authority.cancel_command_id == "cancel-once"
        assert context.authority.cancel_state == cancel.state.value
        assert context.authority.binding_id == binding.binding_id
        assert context.authority.claim_id and context.authority.dispatches_resolved
        assert context.authority.owner_epoch is not None
        assert context.handle.harness_execution_id == hid
        assert str(context.handle.run_id) == identity.internal_run_id
        assert context.family.correlation_id == "fixture-context"
        with pytest.raises(AdoptionInspectionRefused, match="outside approved composition"):
            await reader.read(replace(identity, internal_run_id=str(uuid4())), historical.digest)
        wrong_internal = replace(identity, internal_run_id=str(uuid4()))
        wrong_reader = PostgresTerminalAdoptionContextReader(
            pool,
            identity=wrong_internal,
            inputs=inputs,
            cancel_issuer=cancel.command.idempotency_issuer,
            cancel_command_id="cancel-once",
        )
        with pytest.raises(AdoptionInspectionRefused, match="internal run identity differs"):
            await wrong_reader.read(wrong_internal, historical.digest)
        with pytest.raises(AdoptionInspectionRefused, match="absent or ambiguous"):
            await reader.read(identity, "sha256:" + "f" * 64)
        # Pin the same approved identity but change a typed input: genuine binding SQL
        # must reject it, rather than trusting the constructor's supplied operation.
        changed = operation.model_copy(
            update={"run_control_revision": operation.run_control_revision + 1}
        )
        bad_inputs = replace(
            inputs, operation=inputs.operation.model_copy(update={"operation": changed})
        )
        bad_reader = PostgresTerminalAdoptionContextReader(
            pool,
            identity=identity,
            inputs=bad_inputs,
            cancel_issuer=cancel.command.idempotency_issuer,
            cancel_command_id="cancel-once",
        )
        with pytest.raises(AdoptionInspectionRefused, match="admitted binding"):
            await bad_reader.read(identity, historical.digest)
        # Reader is observational: neither current frontier nor accepted cancel changed.
        assert await controls.get_run(scope, harness.run_id) == run
    finally:
        await pool.close()
        await family_pool.close()

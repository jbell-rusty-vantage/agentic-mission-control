"""W1 D15 on PostgreSQL 17: a run whose family ended unterminalized becomes terminal, typed.

The real W1 runs stayed `running/active` (and two `cancelling`) in mission_control after their
family workflows failed. `FamilyFailureTerminalization` over the production
`PostgresRunControlRepository` under the restricted runtime role releases the unused baseline
and commits the reducer's `failed` (or `cancelled`) terminal transition with the typed cause; a
replay is a no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mission_control.adapters.postgres.run_control.inspection_repository import (
    PostgresUnitFailureReader,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.execution.family_failure import (
    FamilyFailureLiabilityPending,
    FamilyFailureTerminalization,
)
from mission_control.application.programs.service import orchestration_lifecycle_actor
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    ReconcileTerminalLiabilityAction,
    RecordUsageAction,
    ReserveBudgetAction,
    RunOutcome,
    RunPhase,
    StartAction,
    terminal_liability_condition_id,
)
from mission_control.domain.programs.family_failure import (
    LIABILITY_TERMINALIZATION_ATTEMPT,
    FamilyFailureTerminalizationRequest,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.runtime_common import scoped_command, scoped_request
from tests.unit.run_control.test_boundary_commands import TARGET
from tests.unit.run_control.test_run_control import service

pytestmark = pytest.mark.common_db

NOW = datetime(2026, 10, 28, 23, 0, tzinfo=UTC)


def _request(scope: str, run_id: str, cause: str) -> FamilyFailureTerminalizationRequest:
    return FamilyFailureTerminalizationRequest(
        request_scope=scope,
        run_id=run_id,
        execution_epoch=TARGET.execution_epoch,
        family=TARGET.family,
        family_workflow_id=TARGET.family_workflow_id or "family",
        cause=cause,
        cause_digest="sha256:" + "2" * 64,
        occurred_at=NOW,
    )


@pytest.mark.asyncio
async def test_failed_and_cancelling_runs_terminalize_on_postgres(
    common_db: CommonDatabase,
) -> None:
    db = common_db
    scope = db.scope("tenant-1")
    pool = await db.pool("mission_control_runtime")
    try:
        run_control, _ = service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
        terminalization = FamilyFailureTerminalization(run_control, orchestration_lifecycle_actor())
        outcomes = {}
        for request_id, cancel in (("w1-d15-active", False), ("w1-d15-cancelling", True)):
            admitted = await run_control.admit(scoped_request(db, request_id=request_id))
            assert admitted.run_id is not None
            run_id = admitted.run_id
            started = await run_control.execute(
                scoped_command(db, run_id, 1, "start", StartAction(execution_target=TARGET))
            )
            assert started.status == CommandStatus.ACCEPTED
            if cancel:
                cancelled = await run_control.execute(
                    scoped_command(db, run_id, 2, "cancel", CancelAction(urgency="normal"))
                )
                assert cancelled.status == CommandStatus.ACCEPTED
            cause = "terminated" if cancel else "application_error:goal_operation_unreported"
            result = await terminalization.terminalize(_request(scope, run_id, cause))
            assert result.accepted, result
            run = await run_control.get_run(scope, run_id)
            assert run.phase == RunPhase.TERMINAL
            outcomes[request_id] = run.terminal_outcome
            budget = await run_control.get_budget(scope, run_id)
            assert not any(budget.reserved.values())
            transitions = await run_control.list_transitions(scope, run_id)
            assert f"family-failure-cause:{cause}" in transitions[-1].evidence_refs
            # W1 D39: the public inspection names the typed cause (it lived only in Temporal).
            failures = await PostgresUnitFailureReader(pool).unit_failures(scope, run_id)
            assert [(item.reason, item.failure_ref) for item in failures] == [
                ("family_workflow_failed", f"family_workflow_failed:{cause}")
            ]
            assert failures[0].unit == f"family/{TARGET.family_workflow_id or 'family'}"
            # A replayed root / retried activity writes nothing more.
            again = await terminalization.terminalize(_request(scope, run_id, cause), attempt=2)
            assert (again.accepted, again.reason_code) == (True, "already_terminal")
            assert len(await run_control.list_transitions(scope, run_id)) == len(transitions)
        assert outcomes == {
            "w1-d15-active": RunOutcome.FAILED,
            "w1-d15-cancelling": RunOutcome.CANCELLED,
        }
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_d26_liability_close_and_operator_reconciliation_on_postgres(
    common_db: CommonDatabase,
) -> None:
    """W1 D26 on PostgreSQL: a unit reservation that never settles closes as a terminal
    liability (persisted waits), a late usage record is refused, and the operator's audited
    decisions release the reservation and acknowledge the pending settlement."""

    db = common_db
    scope = db.scope("tenant-1")
    pool = await db.pool("mission_control_runtime")
    try:
        run_control, _ = service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
        terminalization = FamilyFailureTerminalization(run_control, orchestration_lifecycle_actor())
        admitted = await run_control.admit(scoped_request(db, request_id="w1-d26-pg"))
        assert admitted.run_id is not None
        run_id = admitted.run_id
        steps = (
            StartAction(execution_target=TARGET),
            ReserveBudgetAction(reservation_id="unit-1", amounts={"tokens.total": 30}),
            RecordUsageAction(
                usage_id="unit-1-pending",
                actual_amounts={},
                reservation_id="unit-1",
                pending_external_amounts={"tokens.total": 4},
            ),
        )
        for index, action in enumerate(steps, start=1):
            result = await run_control.execute(
                scoped_command(db, run_id, index, f"d26-{index}", action)
            )
            assert result.status == CommandStatus.ACCEPTED, result.reason
        for attempt in range(1, LIABILITY_TERMINALIZATION_ATTEMPT):
            with pytest.raises(FamilyFailureLiabilityPending):
                await terminalization.terminalize(
                    _request(scope, run_id, "application_error:x"), attempt=attempt
                )
        closed = await terminalization.terminalize(
            _request(scope, run_id, "application_error:x"),
            attempt=LIABILITY_TERMINALIZATION_ATTEMPT,
        )
        assert closed.accepted and closed.terminal_outcome == RunOutcome.FAILED.value
        run = await run_control.get_run(scope, run_id)
        assert {wait.condition_id for wait in run.active_waits} == {
            terminal_liability_condition_id("reservation:unit-1"),
            terminal_liability_condition_id("pending_settlement"),
        }
        reserved = (await run_control.get_budget(scope, run_id)).reserved
        late = await run_control.execute(
            scoped_command(
                db,
                run_id,
                run.version,
                "d26-late",
                RecordUsageAction(
                    usage_id="late", actual_amounts={"tokens.total": 1}, reservation_id="unit-1"
                ),
            )
        )
        assert late.reason_code == "run_is_terminal"
        assert (await run_control.get_budget(scope, run_id)).reserved == reserved

        def operator(version: int, command_id: str, action: object):  # type: ignore[no-untyped-def]
            base = scoped_command(db, run_id, version, command_id, action)
            return base.model_copy(
                update={
                    "actor": base.actor.model_copy(
                        update={
                            "permissions": base.actor.permissions | {"workflow_run.reconcile_unit"}
                        }
                    )
                }
            )

        refused = await run_control.execute(
            operator(
                run.version,
                "d26-release",
                ReconcileTerminalLiabilityAction(
                    liability="reservation:unit-1", resolution="released", attestation="checked"
                ),
            )
        )
        assert refused.reason_code == "unsettled_usage_on_reservation"
        settled = await run_control.execute(
            operator(
                run.version,
                "d26-settle",
                ReconcileTerminalLiabilityAction(
                    liability="reservation:unit-1",
                    resolution="settled",
                    actual_amounts={"tokens.total": 3},
                    attestation="operator: provider export shows 3 tokens beyond the pending 4",
                ),
            )
        )
        assert settled.status == CommandStatus.ACCEPTED, settled.reason
        run = await run_control.get_run(scope, run_id)
        acknowledged = await run_control.execute(
            operator(
                run.version,
                "d26-ack",
                ReconcileTerminalLiabilityAction(
                    liability="pending_settlement",
                    resolution="acknowledged",
                    attestation="operator: pending provider charge confirmed out of band",
                ),
            )
        )
        assert acknowledged.status == CommandStatus.ACCEPTED, acknowledged.reason
        run = await run_control.get_run(scope, run_id)
        assert run.active_waits == () and run.acknowledged_liabilities == ("pending_settlement",)
        assert run.terminal_outcome == RunOutcome.FAILED
        assert "unit-1" not in (await run_control.get_budget(scope, run_id)).reservations
    finally:
        await pool.close()

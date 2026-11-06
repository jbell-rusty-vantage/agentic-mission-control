"""W1 (OVE-169) on PostgreSQL 17: explicit fulfillment at the convergence boundary.

A real admitted and started run registers a required, an expected and an optional promise under
its public run id (the launch registrar's id). The production output service
(`compose_output_fulfillment`, restricted runtime role) converges after the producing invocation
finalized:

- required submitted -> promoted at the boundary and `fulfilled`, with `output.fulfilled` in the
  mission journal from that real write;
- expected missing -> a visible shortfall, journaled `output.fulfillment_unmet`;
- optional missing -> silent (no event);
- required missing (a second run) -> `unfulfilled`, journaled unmet, completion not satisfied,
  so the verifier's acceptance cannot stand (`bind_fulfillment`).

A repeated convergence records nothing new and journals nothing again.
"""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from mission_control.adapters.postgres.knowledge.output_fulfillment import (
    compose_output_fulfillment,
)
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.fulfillment import HostAccess
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.programs.goal_directed import bind_fulfillment
from mission_control.domain.outputs.contracts import (
    Enforcement,
    OutputForm,
    SubmitOutput,
)
from mission_control.domain.programs.goal_directed_runtime import GoalVerifierObservation
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.test_mp15_coordinator_inbox_postgres import (
    owner_fetch,
    started_run,
)
from tests.unit.knowledge.test_gateway import origin
from tests.unit.outputs.scenario import obligation, promises, text

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]
AT = datetime(2026, 10, 28, 23, tzinfo=UTC)
OPERATION = "goal:1:executor"
PROMISES = promises(
    obligation("root.note", OutputForm.TEXT),
    obligation("root.summary", OutputForm.TEXT, enforcement=Enforcement.EXPECTED),
    obligation("root.caveats", OutputForm.TEXT, enforcement=Enforcement.OPTIONAL),
)


def _access(db: CommonDatabase, run_id: str) -> InvocationAccess:
    _mc, installation, application, tenant_id = db.scope().split("/")
    return InvocationAccess(
        origin=origin(
            1,
            installation_id=installation,
            application_id=application,
            tenant_id=tenant_id,
            run_id=run_id,
            operation_id=OPERATION,
        ),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=AT,
    )


async def _events(db: CommonDatabase, run_key: str) -> list[tuple[str, str]]:
    rows = await owner_fetch(
        db,
        "SELECT event.event_type, event.payload->'payload'->>'obligation_key' AS key "
        "FROM mission_control.mission_event event JOIN mission_control.mission_run run "
        "ON run.mission_id = event.mission_id AND run.run_key = $1 "
        "WHERE event.event_type LIKE 'output.fulfill%' ORDER BY event.event_type, key",
        run_key,
    )
    return [(row["event_type"], row["key"]) for row in rows]


async def _converge(service, db: CommonDatabase, run_key: str):  # type: ignore[no-untyped-def]
    host = HostAccess(
        scope=db.scope(), actor_ref="goal-directed-worker", origin_ref="mc-host:goal-convergence"
    )
    return await service.converge(host, run_key, operation_ref=OPERATION, generation=1)


def _accepted() -> GoalVerifierObservation:
    return GoalVerifierObservation(
        decision="accepted",
        progress_made=True,
        accepted_obligation_refs=("obligation:goal",),
        output_contract_ref="contract:report",
    )


async def test_convergence_records_fulfillment_and_journals_attention_on_postgres(
    common_db: CommonDatabase,
) -> None:
    db = common_db
    pool: asyncpg.Pool = await db.pool("mission_control_runtime")
    try:
        service = compose_output_fulfillment(
            pool, trusted_validators=frozenset({"knowledge.report.assess@1"})
        )
        host = HostAccess(scope=db.scope(), actor_ref="mc-launch", origin_ref="mc-host:launch")

        # Run 1: the required note is submitted by the executor and finalized.
        met_key, _mission, _uuid = await started_run(pool, db)
        await service.register_promises(
            host, met_key, PROMISES, configuration_digest="sha256:" + "5" * 64
        )
        access = _access(db, met_key)
        await service.pin_invocation(host, access)
        submissions = SubmissionService(service._store, contracts=service._store)
        ack = await submissions.submit_output(
            access,
            SubmitOutput(
                submission_key="s-note",
                obligation_key="root.note",
                items=(text("note", "progress: 2 of 3 checks reproduced"),),
            ),
            position="draft",
        )
        assert ack.status == "accepted", ack.error
        await submissions.finalize(access.identity(("root.note",)))

        met = await _converge(service, db, met_key)
        assert met is not None and met.completion == "satisfied"
        dispositions = {item.obligation_key: item.disposition for item in met.fulfillments}
        assert dispositions["root.note"] == "fulfilled"
        assert met.shortfalls == ("root.summary",)
        rows = await owner_fetch(
            db,
            "SELECT obligation_key, enforcement, disposition "
            "FROM mission_control.obligation_fulfillment WHERE output_set_id = $1::uuid "
            "ORDER BY obligation_key",
            met.set_id,
        )
        assert [(r["obligation_key"], r["enforcement"], r["disposition"]) for r in rows] == [
            ("root.caveats", "optional", "unfulfilled"),
            ("root.note", "required", "fulfilled"),
            ("root.summary", "expected", "unfulfilled"),
        ]
        assert await _events(db, met_key) == [
            ("output.fulfilled", "root.note"),
            ("output.fulfillment_unmet", "root.summary"),
        ]  # the optional absence is silent
        assert bind_fulfillment(_accepted(), met).decision == "accepted"

        again = await _converge(service, db, met_key)
        assert again is not None and again.set_id == met.set_id
        assert len(await _events(db, met_key)) == 2  # nothing journaled twice

        # Run 2: nothing submitted; the required promise is unmet and the run cannot accept.
        missing_key, _mission, _uuid = await started_run(pool, db)
        await service.register_promises(
            host, missing_key, PROMISES, configuration_digest="sha256:" + "5" * 64
        )
        missing = await _converge(service, db, missing_key)
        assert missing is not None and missing.completion != "satisfied"
        assert "root.note" in missing.blocking
        assert ("output.fulfillment_unmet", "root.note") in await _events(db, missing_key)
        bound = bind_fulfillment(_accepted(), missing)
        assert bound.decision == "rejected" and "output:root.note" in bound.unmet_obligations
    finally:
        await pool.close()

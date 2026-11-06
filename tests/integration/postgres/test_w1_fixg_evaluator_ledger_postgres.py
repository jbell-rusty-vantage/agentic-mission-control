"""W1 fix G (OVE-169) on real PostgreSQL: the evaluator attempt ledger is a compare-and-set.

Two settlement passes that read the same standing wait of one revision (forced with a barrier on
the assessment read) both record a billed judge attempt: the store serializes supersession of the
same prior (transaction advisory lock + rival check), the loser re-reads and records on top, so
exactly one wait stands and it counts both attempts (no undercount, no forked standing waits).
A third concurrent writer that loses twice gets the typed ``EvaluatorWaitConflict``. The operator
reset then records an audited superseding wait and frees the bound.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.application.knowledge.judgment import (
    ATTEMPTS_PREFIX,
    RESET_FINDING,
    EvaluatorAttemptReset,
    standing_wait,
)
from mission_control.application.ports.outputs import AssessmentSupersessionConflict
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_trusted_judgment_postgres import access_for
from tests.unit.knowledge.test_trusted_judgment import ScriptedRunner, world

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool(max_size=6)
    try:
        yield created
    finally:
        await created.close()


class BarrierStore(PostgresOutputContractStore):
    """The real store; the first ``parties`` assessment reads wait for each other, so the
    concurrent passes all read the same standing wait before any of them writes."""

    def __init__(self, pool: asyncpg.Pool, parties: int) -> None:
        super().__init__(pool)
        self.barrier = asyncio.Barrier(parties)
        self.remaining = parties

    async def output_assessments(self, scope: str, run_id: str) -> Any:
        rows = await super().output_assessments(scope, run_id)
        if self.remaining > 0:
            self.remaining -= 1
            await self.barrier.wait()
        return rows


async def test_concurrent_billed_attempts_serialize_on_the_standing_wait(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    w, subject = await world(
        common_db.application_id,
        store=PostgresOutputContractStore(pool),
        access=access_for(common_db),
    )
    host, use = w.stack.access, w.use()
    racing = BarrierStore(pool, 2)
    first, second = w.bridge(ScriptedRunner({})), w.bridge(ScriptedRunner({}))
    for bridge in (first, second):
        bridge._store = racing  # the waits are read through the racing store
    cause = "judge run failed: StructuredOutputValidationError: verdicts.0 Field required"
    recorded = await asyncio.gather(
        first._record_wait(subject, host, use, "judge", cause, billed=True),
        second._record_wait(subject, host, use, "judge", cause, billed=True),
    )
    assert all(item is not None for item in recorded)
    rows = await w.stack.store.output_assessments(host.scope, subject.run_id)
    mine = [row for row in rows if row.subject_id == subject.revision.revision_id]
    superseded = [row.supersedes for row in mine if row.supersedes]
    assert len(superseded) == len(set(superseded))  # never two successors of one prior
    wait = standing_wait(rows, subject.revision)
    assert wait is not None and f"{ATTEMPTS_PREFIX}judge:2" in wait.evidence_refs
    assert [row.assessment_id for row in mine if row.assessment_id not in superseded] == [
        wait.assessment_id
    ]

    # The store itself refuses a second supersession of the same prior (the compare-and-set).
    prior = wait.supersedes
    assert prior is not None
    with pytest.raises(AssessmentSupersessionConflict):
        await w.stack.store.record_output_assessment(
            host.scope,
            subject.run_id,
            wait.model_copy(
                update={
                    "assessment_id": "0192a4f0-0000-7000-8000-0000000fffff",
                    "evidence_refs": (*wait.evidence_refs, "fork"),
                }
            ),
            actor_ref="mission-control:trusted-bridge",
            at=w.clock.now,
        )

    # The bound is spent: a later pass runs no judge; the audited operator reset frees it.
    runner = ScriptedRunner({"judge": "full_support"})
    blocked = await w.bridge(runner).assess(
        subject, (w.evaluator("judge"), w.evaluator("auditor")), host, use
    )
    assert runner.calls == [] and blocked.exhausted
    reset = EvaluatorAttemptReset(w.stack.outputs, w.stack.store, clock=lambda: w.clock.now)
    recorded_reset = await reset.reset(
        host.scope,
        subject.run_id,
        subject.revision.revision_id,
        "judge",
        operator="operator-1",
        reason="schema fixed in models.toml; rerun once",
    )
    assert recorded_reset.supersedes == wait.assessment_id
    assert recorded_reset.assessor_origin_ref.endswith(":operator-1")
    assert any(
        f.code == RESET_FINDING and "operator-1" in f.message for f in recorded_reset.findings
    )
    assert not [ref for ref in recorded_reset.evidence_refs if ref.startswith(ATTEMPTS_PREFIX)]
    again = ScriptedRunner({"judge": "full_support"})
    passed = await w.bridge(again).assess(
        subject, (w.evaluator("judge"), w.evaluator("auditor")), host, use
    )
    assert again.calls == ["judge", "auditor"] and passed.result in {"pass", "review"}

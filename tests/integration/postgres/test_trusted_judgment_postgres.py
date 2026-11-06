"""WI-03 on real PostgreSQL: trusted assessments, supersession, promotion and recorded decisions.

The KS side is the deterministic trusted-transport double (its rules are proven store-backed in
Knowledge Services' ``trusted_assessment`` conformance check); every MC record is real: output
revisions, assessments, accepted heads (release 1.7.0) and recorded use decisions (0059). A
"restart" is a new gateway, handle store and bridge over the same database and KS state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.knowledge.use_decisions import PostgresUseDecisionStore
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.ports.knowledge import RecordedUseDecision
from mission_control.contracts.knowledge_protocol import Ref
from tests.fixtures.knowledge_binding import BINDING, SteppingClock
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.knowledge.test_gateway import origin
from tests.unit.knowledge.test_trusted_judgment import ScriptedRunner, evaluators, head_of, world

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


def access_for(db: CommonDatabase) -> InvocationAccess:
    """The database's own application (``MISSION_CONTROL_APPLICATION``: run once per app)."""

    _mc, installation, app, tenant_id = db.scope("tenant-1").split("/")
    return InvocationAccess(
        origin=origin(installation_id=installation, application_id=app, tenant_id=tenant_id),
        subject="mission-control-runtime",
        invocation_id="inv-producer",
        authenticated_at=SteppingClock().now,
    )


async def test_review_successor_after_restart_supersedes_and_promotes(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    w, subject = await world(
        common_db.application_id,
        store=PostgresOutputContractStore(pool),
        access=access_for(common_db),
    )
    host = w.stack.access
    waiting = await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
        subject, evaluators(w), host, w.use()
    )
    assert waiting.state == "waiting" and waiting.reason == "review_pending"
    assert await head_of(w, subject) is None
    assert waiting.resolution is not None
    decision = waiting.resolution.current
    w.ks.grants.add("reviewer-1")
    await w.bridge(ScriptedRunner({})).review(
        w.evaluator("human_reviewer", subject="reviewer-1"),
        Ref.model_validate(decision.model_dump()),
        outcome="approve",
        bound_effect_digest=w.ks.decisions[decision.id]["boundEffectDigest"],
        qualifiers_digest=None,
        rationale="reviewed",
    )
    # A fresh process over the same rows resolves the exact successor exactly once.
    resolved = await w.bridge(ScriptedRunner({})).resume(subject, host, w.use(), attempt=1)
    assert resolved.result == "pass" and resolved.promoted
    assert resolved.resolution is not None
    assert resolved.resolution.current.id == f"{decision.id}-rv"
    # Verdicts only: the evaluator wait rows (observe dispatch markers) precede them, superseded.
    every = await w.stack.store.output_assessments(host.scope, subject.run_id)
    rows = [row for row in every if row.result != "unavailable"]
    assert [row.result for row in rows] == ["review", "pass"]
    assert rows[1].supersedes == rows[0].assessment_id
    assert await head_of(w, subject) == subject.revision.revision_id
    again = await w.bridge(ScriptedRunner({})).resume(subject, host, w.use(), attempt=2)
    assert again.state == "settled"
    assert len(await w.stack.store.output_assessments(host.scope, subject.run_id)) == len(every)


async def test_recorded_use_decisions_are_durable_and_immutable(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    access = access_for(common_db)
    store = PostgresUseDecisionStore(pool)
    decision = RecordedUseDecision(
        handle="ud-handle-1",
        binding_id=BINDING,
        tenant_id=access.origin.tenant_id,
        use_decision_id="ud-run-1-abc",
        bound_effect_digest="sha256:" + "a" * 64,
        processed_epoch=3,
        plan={"intent": "add", "claims": ["c-1"]},
        normalized_values_digest="sha256:" + "b" * 64,
        use="knowledge_ingestion.apply",
        audience="official",
    )
    at = SteppingClock().now
    assert await store.record(access.scope, decision, actor_ref="test", at=at) == decision
    assert await store.record(access.scope, decision, actor_ref="test", at=at) == decision
    with pytest.raises(ValueError, match="another decision"):
        await store.record(
            access.scope, replace(decision, processed_epoch=4), actor_ref="test", at=at
        )
    # A restarted process reads the same decision.
    assert await PostgresUseDecisionStore(pool).get(access.scope, "ud-handle-1") == decision
    async with pool.acquire() as connection:
        with pytest.raises(asyncpg.PostgresError):
            await connection.execute(
                "UPDATE mission_control.knowledge_use_decision SET processed_epoch = 9"
            )

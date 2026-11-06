"""WI-03 / OVE-165: the trusted KS review wait across a worker restart (real Temporal + PG).

The `OperationWorkflow` (time-skipping server) drives the real operation boundary with the saved
provider result in `mission_control.invocation_settlement` (WI-04, release 1.7.0). The lane's
settler is the trusted knowledge bridge behind the WI-04 seam: every settlement pass builds a
*fresh* bridge (new gateway and handle store; a restarted process) over the same PostgreSQL output
records and the deterministic KS trusted-transport double (its rules are proven store-backed by
Knowledge Services' `trusted_assessment` conformance check; no model judges here).

Pass 1 (worker 1): separate judge and auditor observe, KS seals and decides the official use, the
decision waits on review -> `waiting/review_pending` naming the exact KS decision. While no
worker runs, a qualified reviewer approves in KS (a successor decision). Pass 2 (worker 2, after
the durable timer): the bridge re-resolves the exact decision, finds the successor, supersedes the
review assessment and promotes the revision through the expected-head CAS. Cognition ran once.
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
from mission_control.adapters.postgres.operations.invocation_settlement import (
    PostgresInvocationSettlementStore,
)
from mission_control.application.knowledge.judgment import JudgmentSubject
from mission_control.domain.execution.contracts import RuntimeInvocation
from mission_control.domain.execution.invocation_settlement import (
    SettlementOutcome,
    SettlementState,
    WaitReason,
)
from mission_control.domain.knowledge.judgment import cited_decisions
from tests.fixtures.checkpoint_recovery import recovery_harness, stage_recovery_unit
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.saved_settlement import DurableEffectDouble
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_trusted_judgment_postgres import access_for
from tests.integration.temporal.test_wi04_saved_settlement_restart import (
    _environment,
    _replays,
    _scheduled,
    _Stack,
)
from tests.unit.knowledge.test_trusted_judgment import (
    ScriptedRunner,
    World,
    evaluators,
    head_of,
    world,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    await common_db.add_tenants(["tenant-1"])
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


class TrustedReviewSettler:
    """The WI-04 `InvocationSettler` whose pass is the trusted bridge (fresh per pass)."""

    def __init__(self, w: World, subject: JudgmentSubject) -> None:
        self.w = w
        self.subject = subject
        self.passes: list[str] = []
        self.runner_calls: list[str] = []

    def applies(self, invocation: RuntimeInvocation) -> bool:
        del invocation
        return True

    async def settle(
        self, invocation: RuntimeInvocation, *, fenced: bool = False
    ) -> SettlementOutcome:
        del invocation, fenced
        runner = ScriptedRunner({"judge": "full_support"})
        bridge = self.w.bridge(runner)  # a fresh process: new gateway and handle store
        host = self.w.stack.access
        rows = await self.w.stack.store.output_assessments(host.scope, self.subject.run_id)
        if any(cited_decisions(row.evidence_refs) for row in rows):
            outcome = await bridge.resume(
                self.subject, host, self.w.use(), attempt=len(self.passes)
            )
        else:
            outcome = await bridge.assess(self.subject, evaluators(self.w), host, self.w.use())
        self.runner_calls.extend(runner.calls)
        self.passes.append(outcome.state)
        if outcome.reason == "review_pending":
            return SettlementOutcome(
                state="waiting",
                reason=WaitReason.REVIEW_PENDING,
                pending_reviews=outcome.pending_reviews,
            )
        return SettlementOutcome.done(fulfillment_refs=("obligation:draft.report",))


async def test_trusted_review_wait_survives_a_worker_restart_and_resolves_the_exact_successor(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    w, subject = await world(
        common_db.application_id,
        store=PostgresOutputContractStore(pool),
        access=access_for(common_db),
    )
    settler = TrustedReviewSettler(w, subject)
    effects = DurableEffectDouble(acknowledge_on_write=True)
    scope = common_db.scope("tenant-1")
    # The harness lineage is in memory: no PostgreSQL attempt row carries the unit's fence.
    store = PostgresInvocationSettlementStore(pool, require_unit_generation=False)
    harness = await recovery_harness(request_scope=scope, saved_results=store, settlers=(settler,))
    effects.attach(harness.model, answer_turns=(2, 4, 6))
    request = await harness.request(stage_recovery_unit(harness.run_id, request_scope=scope))
    environment = await _environment()
    async with environment:
        stack = _Stack(harness, environment, store)
        with environment.auto_time_skipping_disabled():
            async with stack.workflow_worker():
                async with stack.activity_worker("wi03-worker-1"):
                    handle = await stack.start(request, "wi03-trusted-review-restart")
                    waiting = await stack.until(request, SettlementState.WAITING)
                pending: Any = waiting.pending_reviews
                assert pending and waiting.next_action == "await_review"
                decision_id = pending[0].removeprefix("ks-use-decision:").split("@", 1)[0]
                # No worker runs: a qualified reviewer approves the exact decision in KS.
                w.ks.grants.add("reviewer-1")
                decision = w.ks.decisions[decision_id]
                await w.bridge(ScriptedRunner({})).review(
                    w.evaluator("human_reviewer", subject="reviewer-1"),
                    _decision_ref(w, decision_id),
                    outcome="approve",
                    bound_effect_digest=decision["boundEffectDigest"],
                    qualifiers_digest=None,
                    rationale="premises and evidence reviewed",
                )
                async with stack.activity_worker("wi03-worker-2"):
                    await environment.sleep(30)  # the durable timer fires
                    result = await asyncio.wait_for(handle.result(), timeout=120)
                    history = await _replays(handle)
    assert result.disposition == "completed"
    assert _scheduled(history) == ["operation.execute", "operation.execute"]
    assert len(harness.model.calls) == 2, "no second model turn"
    assert harness.runtime.invocations == 1, "the saved result was never redispatched"
    assert settler.passes == ["waiting", "settled"]
    assert settler.runner_calls == ["judge", "auditor"], "evaluators ran once, before the wait"
    every = await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id)
    rows = [row for row in every if row.result != "unavailable"]  # verdicts, not wait markers
    assert [row.result for row in rows] == ["review", "pass"]
    assert rows[1].supersedes == rows[0].assessment_id
    assert rows[1].evidence_refs[0].startswith(f"ks-use-decision:{decision_id}-rv@")
    assert await head_of(w, subject) == subject.revision.revision_id
    record = await stack.record(request)
    assert record is not None and record.settled
    print(
        "WI-03 EVIDENCE trusted review across restart:",
        {
            "scheduled": _scheduled(history),
            "passes": settler.passes,
            "successor": rows[1].evidence_refs[0].split("@", 1)[0],
        },
    )


def _decision_ref(w: World, decision_id: str):  # type: ignore[no-untyped-def]
    from mission_control.contracts.knowledge_protocol import Ref, digest_canonical

    report = Ref.model_validate(w.ks.decisions[decision_id]["report"])
    return Ref(
        kind="use_decision",
        id=decision_id,
        version="research-core.use_decision.v2",
        digest=digest_canonical(w.ks.decisions[decision_id]),
        tenant=report.tenant,
        binding=report.binding,
    )

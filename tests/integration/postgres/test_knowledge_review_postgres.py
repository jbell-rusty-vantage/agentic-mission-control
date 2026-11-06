"""W1 D2 review route on real PostgreSQL (OVE-169 review B1): one run identifier end to end.

A run admitted through the real run-control repository (its launcher is ``operator``) produces a
trusted assessment in the real output tables (release 1.7.0) citing a KS use decision of the
deterministic trusted double. ``KnowledgeReviewService`` over ``PostgresRunActors`` and
``PostgresOutputContractStore``, both on the restricted ``mission_control_runtime`` login, then
proves: the public run id and the internal ``mission_run.run_id`` resolve to the same run; the
launcher is refused; an unknown or non-UUID run is ``not_found`` (never a 500); another run's
review of this decision is ``decision_not_in_run``; a separate reviewer is relayed. Reading the
run's actors also proves the runtime login's SELECT on ``mission_run``, ``mission`` and
``mission_revision`` under RLS.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.knowledge.invocation_locator import (
    PostgresInvocationLocator,
)
from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.knowledge.run_actors import PostgresRunActors
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.judgment import ReviewRelay
from mission_control.application.knowledge.review import (
    REVIEW_PERMISSION,
    KnowledgeReviewRequest,
    KnowledgeReviewService,
    ReviewRejected,
)
from mission_control.contracts.knowledge_protocol import Ref
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.knowledge_binding import SteppingClock
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.knowledge.test_gateway import origin
from tests.unit.knowledge.test_trusted_judgment import PRODUCER, ScriptedRunner, evaluators, world
from tests.unit.run_control.test_run_control import request, service

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]

LAUNCHER = ActorContext(actor_id="operator", permissions=frozenset({REVIEW_PERMISSION}))
REVIEWER = ActorContext(actor_id="reviewer:sprint-oc", permissions=frozenset({REVIEW_PERMISSION}))


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


async def test_the_review_route_resolves_one_run_identifier_on_postgres(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    scope = common_db.scope("tenant-1")
    runs, _ = service(PostgresRunControlRepository(pool))
    admitted = await runs.admit(request(request_scope=scope))
    other = await runs.admit(request(request_scope=scope, request_id="request-2"))
    run_id, other_run = str(admitted.run_id), str(other.run_id)
    assert run_id and other_run and run_id != other_run

    _mc, installation, app, tenant_id = scope.split("/")
    # Provenance slice 1: origins name the run's ledger mission (never the run id).
    mission_id, activation_id = await PostgresInvocationLocator(pool).locate(scope, run_id, None)
    assert mission_id != run_id and activation_id is None
    producer = InvocationAccess(
        origin=origin(
            installation_id=installation,
            application_id=app,
            tenant_id=tenant_id,
            mission_id=mission_id,
            run_id=run_id,
        ),
        subject=PRODUCER.subject,
        invocation_id="inv-producer",
        authenticated_at=SteppingClock().now,
    )
    store = PostgresOutputContractStore(pool)
    w, subject = await world(app, store=store, access=producer)
    assert subject.run_id == run_id
    bridge = w.bridge(ScriptedRunner({"judge": "full_support"}))
    waiting = await bridge.assess(subject, evaluators(w), w.stack.access, w.use())
    assert waiting.state == "waiting" and waiting.reason == "review_pending"
    decision = Ref.model_validate(waiting.resolution.current.model_dump())  # type: ignore[union-attr]

    actors = PostgresRunActors(pool)
    by_key = await actors.resolve_run(scope, run_id)
    assert by_key is not None and by_key.run_key == run_id and by_key.mission_id == mission_id
    assert "operator" in by_key.actors  # the admitting launcher, read under the runtime login
    async with pool.acquire() as connection, connection.transaction():
        from mission_control.adapters.postgres.run_control import canonical as mc

        args = await mc.begin(connection, scope)
        internal = str(await mc.run_uuid(connection, args, run_id))
    assert internal != run_id
    by_internal = await actors.resolve_run(scope, internal)
    assert by_internal == by_key  # both identifiers resolve to the one public run id

    reviews = KnowledgeReviewService(
        ReviewRelay(bridge._gateway, clock=w.clock),  # type: ignore[attr-defined]
        runs=actors,
        assessments=store,
        request_scope=scope,
        issuer="mission-control",
        producer_subject=PRODUCER.subject,
        clock=w.clock,
    )
    body = KnowledgeReviewRequest.model_validate(
        {
            "decision": decision.model_dump(mode="json"),
            "outcome": "approve",
            "bound_effect_digest": w.ks.decisions[decision.id]["boundEffectDigest"],
            "rationale": "the cited quotes state the sizes",
        }
    )
    w.ks.grants.update({LAUNCHER.actor_id, REVIEWER.actor_id})
    sent = len(w.ks.calls)
    for named, actor, code in (
        (run_id, LAUNCHER, "unauthorized_review"),
        ("00000000-0000-4000-8000-000000000000", REVIEWER, "not_found"),
        ("not-a-run", REVIEWER, "not_found"),
        (other_run, REVIEWER, "decision_not_in_run"),
    ):
        with pytest.raises(ReviewRejected) as refused:
            await reviews.review(named, body, actor)
        assert refused.value.code == code, (named, refused.value)
    assert len(w.ks.calls) == sent  # nothing reached KS

    # The internal id resolves to the public one: the reviewer origin and the assessment read
    # name the same run.
    reviewed = await reviews.review(internal, body, REVIEWER)
    assert reviewed["run_id"] == run_id
    assert reviewed["review"]["successor"]["id"] == f"{decision.id}-rv"
    resolved = await w.bridge(ScriptedRunner({})).resume(
        subject, w.stack.access, w.use(), attempt=1
    )
    assert resolved.result == "pass" and resolved.promoted

"""Provenance slice 1 (OVE-204) on a disposable PostgreSQL 17: the true mission origin.

A run admitted through real run control records one runtime-unit attempt (the ``activation``
row attempt admission inserts for the unit key). ``PostgresInvocationLocator`` on the restricted
runtime login resolves the run's ledger ``mission_run.mission_id`` and that activation id; the
Deep Agents knowledge lane builds every origin of the attempt from them: the journal and handle
rows carry the ledger ids and the unit key, the K01 wire coordinates name them, the producer's
lineage actor ref is the invocation ref, and a settlement after a worker restart (a fresh lane
support re-locating from the binding alone) finalizes under the same invocation ref. An unknown
run, or a run of another tenant, fails closed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.deep_agents.knowledge_tools import KnowledgeLaneSupport
from mission_control.adapters.postgres.knowledge.invocation_locator import (
    PostgresInvocationLocator,
)
from mission_control.adapters.postgres.knowledge.lineage import PostgresContentLineageStore
from mission_control.adapters.postgres.knowledge.submissions import PostgresOutputSubmissionStore
from mission_control.application.knowledge.toolset import (
    TOOL_NAMES,
    KnowledgeToolset,
    LiveInvocation,
)
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.domain.knowledge.origin import MissionIdentityUnavailable
from tests.fixtures.knowledge_binding import model_report
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db, owner_rows  # noqa: F401
from tests.integration.postgres.test_knowledge_gateway_postgres import stack
from tests.unit.knowledge.test_knowledge_tools import _runtime_invocation

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool()
    try:
        yield created
    finally:
        await created.close()


async def test_the_deep_agents_origin_names_the_ledger_mission_and_activation(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    admitted = await admit_unit_attempt(pool, common_db)
    scope = common_db.scope("tenant-1")
    unit_key = admitted.unit.unit_key
    (ledger,) = await owner_rows(
        common_db,
        "SELECT run.mission_id::text AS mission_id, activation.activation_id::text AS activation "
        "FROM mission_control.mission_run AS run JOIN mission_control.activation AS activation "
        "ON activation.run_id = run.run_id "
        "WHERE run.run_key = $1 AND activation.activation_key = $2",
        admitted.run_key,
        unit_key,
    )
    mission, activation = ledger["mission_id"], ledger["activation"]
    assert mission != admitted.run_key

    locator = PostgresInvocationLocator(pool)
    assert await locator.locate(scope, admitted.run_key, unit_key) == (mission, activation)
    assert await locator.locate(scope, admitted.run_key, None) == (mission, None)
    assert await locator.locate(scope, admitted.run_key, "unit:absent") == (mission, None)
    with pytest.raises(MissionIdentityUnavailable):
        await locator.locate(scope, str(uuid4()), unit_key)
    with pytest.raises(MissionIdentityUnavailable):
        await locator.locate(common_db.scope("tenant-2"), admitted.run_key, unit_key)

    clock, _minter, _client, _journal, gateway = stack(pool)
    toolset = KnowledgeToolset(
        gateway=gateway(),
        submissions=SubmissionService(PostgresOutputSubmissionStore(pool)),
        issuer="mission-control",
        clock=clock,
        lineage=PostgresContentLineageStore(pool),
        locator=locator,
    )
    invocation = _runtime_invocation(
        LiveInvocation(
            request_scope=scope,
            run_id=admitted.run_key,
            operation_id="stage:collect",
            operation_attempt=1,
            execution_generation=1,
            lane="deep_agents",
            unit_key=unit_key,
        ),
        tool_names=TOOL_NAMES,
    )
    support = KnowledgeLaneSupport(toolset)
    begun = await support.begin(invocation)
    access = toolset.access(begun)
    ref = access.invocation_ref
    assert (access.origin.mission_id, access.origin.activation_id) == (mission, activation)
    wire = access.wire_origin().mission
    assert wire is not None
    assert (wire.missionId, wire.runId, wire.activationId) == (
        mission,
        admitted.run_key,
        activation,
    )

    with support.bind(invocation, begun):  # type: ignore[arg-type]
        registered = await toolset.dispatch(
            "report_register", {"report": model_report("r-origin")}, begun, tool_call_id="c-1"
        )
        verifying = await toolset.dispatch(
            "verify_claims", {"claims": [{"id": "claim-1"}]}, begun, tool_call_id="c-2"
        )
    assert registered["ok"], registered
    assert verifying["ok"], verifying

    journal = await owner_rows(
        common_db,
        "SELECT mission_id::text AS mission_id, activation_id::text AS activation, unit_key, "
        "originating_origin FROM mission_control.knowledge_operation_journal "
        "WHERE run_id = $1::uuid",
        admitted.run_key,
    )
    assert journal
    for row in journal:
        assert (row["mission_id"], row["activation"], row["unit_key"]) == (
            mission,
            activation,
            unit_key,
        )
        wired = json.loads(row["originating_origin"])["mission"]
        assert (wired["missionId"], wired["activationId"]) == (mission, activation)
    handles = await owner_rows(
        common_db,
        "SELECT mission_id::text AS mission_id, activation_id::text AS activation, unit_key, "
        "invocation_ref FROM mission_control.knowledge_operation_handle WHERE run_id = $1::uuid",
        admitted.run_key,
    )
    assert handles
    assert {tuple(row) for row in handles} == {(mission, activation, unit_key, ref)}
    producers = await owner_rows(
        common_db,
        "SELECT actor_ref, actor_origin FROM mission_control.content_lineage "
        "WHERE run_id = $1::uuid AND role = 'producer'",
        admitted.run_key,
    )
    assert producers
    for row in producers:
        assert row["actor_ref"] == ref
        origin = json.loads(row["actor_origin"])
        assert (origin["mission_id"], origin["activation_id"]) == (mission, activation)

    # A worker restart: a fresh lane support re-locates from the binding alone.
    outcome = await KnowledgeLaneSupport(toolset).settle(invocation)  # type: ignore[arg-type]
    assert outcome.finalization_ref is not None, outcome
    (finalized,) = await owner_rows(
        common_db,
        "SELECT invocation_ref FROM mission_control.invocation_finalization "
        "WHERE finalization_id = $1::uuid",
        outcome.finalization_ref.removeprefix("finalization:"),
    )
    assert finalized["invocation_ref"] == ref

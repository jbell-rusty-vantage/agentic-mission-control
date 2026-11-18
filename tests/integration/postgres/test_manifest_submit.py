"""FT-E3: Mission Manifest submit and start on a disposable PostgreSQL 17 (common component).

Compile resolves against the seeded catalog fixture (in memory, lexical); submit publishes the
lowered definitions and the Compiled Program into the installation catalog in PostgreSQL and
commits the revision, typed definition rows, authoring provenance and the admitted run (or the
chain) in one transaction under the restricted runtime role. Start goes through the governed
``RunLaunchService`` with a recording submitter (no Temporal, no provider).
"""

from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
import pytest

from mission_control.adapters.postgres.scope import apply_scope
from mission_control.application.authoring.manifest_submit import (
    ManifestBlocked,
    ManifestIdempotencyConflict,
    SubmitRequest,
    TenantNotProvisioned,
)
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.integration.postgres.manifest_submit import (
    MINIMAL,
    OWNER,
    ROOT,
    Stack,
    goal_loop_manifest,
    request,
    stack,  # noqa: F401
)

pytestmark = pytest.mark.common_db

MISSION_2 = (
    ROOT / "tests/fixtures/manifests/fast-track/02-research-ingestion-cursor-cloud-chain.yml"
)


@pytest.mark.asyncio
async def test_submit_commits_the_revision_and_admits_the_run_idempotently(stack: Stack) -> None:  # noqa: F811
    service = await stack.build()
    manifest = MINIMAL.read_text(encoding="utf-8")
    first_id = uuid4()
    receipt, replayed = await service.submit(request(manifest, first_id))
    assert not replayed and not receipt.unchanged and receipt.chain_id is None
    (mission,) = receipt.missions
    assert mission.family == "StageGraph" and mission.revision_no == 1
    assert mission.run_id is not None
    (run,) = await stack.fetch(
        "SELECT phase, mission_id, revision_id, created_by_actor_ref "
        "FROM mission_control.mission_run WHERE run_key = $1",
        mission.run_id,
    )
    assert (run["phase"], run["mission_id"], run["revision_id"]) == (
        "pending",
        mission.mission_id,
        mission.revision_id,
    )
    (snapshot,) = await stack.fetch(
        "SELECT snapshot.definition_contract_version, snapshot.definition_digest, "
        "snapshot.definition FROM mission_control.definition_snapshot AS snapshot "
        "JOIN mission_control.mission_revision AS revision "
        "ON revision.definition_snapshot_id = snapshot.definition_snapshot_id "
        "WHERE revision.revision_id = $1",
        mission.revision_id,
    )
    assert snapshot["definition_contract_version"] == "mc.mission_definition.v1"
    assert json.loads(snapshot["definition"])["mission_key"] == "minimal-sweep"
    program = json.loads(
        await stack.val(
            "SELECT program FROM mission_control.compiled_program WHERE revision_id = $1",
            mission.revision_id,
        )
    )
    assert program["effective_configuration_digest"] == mission.effective_configuration_digest
    assert program["definition_digest"] == snapshot["definition_digest"]
    # Typed definition rows of mig/0002.
    goals = await stack.fetch(
        "SELECT goal_key FROM mission_control.goal WHERE revision_id = $1", mission.revision_id
    )
    nodes = await stack.fetch(
        "SELECT node_key, parent_node_key, behavior_kind FROM mission_control.program_node "
        "WHERE revision_id = $1",
        mission.revision_id,
    )
    assert [row["goal_key"] for row in goals] == ["evidence_map"]
    assert {(row["node_key"], row["parent_node_key"], row["behavior_kind"]) for row in nodes} == {
        ("root", None, "stage_graph"),
        ("collect", "root", "goal_directed"),
        ("synthesize", "root", "operation"),
    }
    assert (
        await stack.val(
            "SELECT count(*) FROM mission_control.success_criterion WHERE revision_id = $1",
            mission.revision_id,
        )
        == 1
    )
    # Frozen run request: the admission receipt names the run.
    assert (
        await stack.val(
            "SELECT count(*) FROM mission_control.request_receipt "
            "WHERE action = 'mc.run.admit' AND resource_ref = $1",
            mission.run_id,
        )
        == 1
    )
    # Provenance with the revision; queryable and immutable.
    provenance = await stack.submissions.provenance(stack.scope, mission.revision_id)
    assert provenance is not None
    assert provenance["manifest_yaml"] == manifest
    assert provenance["resolution"]["schema_version"] == "mc.manifest_resolution.v1"
    assert provenance["resolution"]["catalog_resolution"] == "resolved"
    with pytest.raises(asyncpg.PostgresError):
        async with stack.pool.acquire() as connection, connection.transaction():
            await apply_scope(connection, stack.scope)
            await connection.execute(
                "UPDATE mission_control.authoring_provenance SET manifest_yaml = 'x' "
                "WHERE revision_id = $1",
                mission.revision_id,
            )

    # Replay: the same ids. A changed digest under the same id: IDEMPOTENCY_CONFLICT.
    again, replayed = await service.submit(request(manifest, first_id))
    assert replayed and again == receipt
    changed = manifest.replace("Minimal literature sweep", "Minimal literature sweep v2")
    with pytest.raises(ManifestIdempotencyConflict):
        await service.submit(request(changed, first_id))
    # A new request id with an equal digest returns the head unchanged.
    unchanged, replayed = await service.submit(request(manifest))
    assert not replayed and unchanged.unchanged
    assert unchanged.missions[0].revision_id == mission.revision_id
    assert unchanged.missions[0].run_id == mission.run_id
    # A changed manifest is the next revision of the same mission, with its own run.
    revised, _ = await service.submit(request(changed))
    assert revised.missions[0].mission_id == mission.mission_id
    assert revised.missions[0].revision_no == 2
    assert revised.missions[0].run_id not in {None, mission.run_id}
    head = await stack.val(
        "SELECT scheduling_head_revision_id FROM mission_control.mission WHERE mission_id = $1",
        mission.mission_id,
    )
    assert head == revised.missions[0].revision_id


@pytest.mark.asyncio
async def test_blockers_and_foreign_applications_write_nothing(stack: Stack) -> None:  # noqa: F811
    service = await stack.build()
    document = load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))
    document["mission"]["application"] = "ai-engineer"
    before = await stack.val("SELECT count(*) FROM mission_control.mission")
    with pytest.raises(ManifestBlocked) as blocked:
        await service.submit(request(canonical_manifest_bytes(document).decode("utf-8")))
    assert blocked.value.issues[0].code.value == "APPLICATION_FORBIDDEN"
    assert await stack.val("SELECT count(*) FROM mission_control.mission") == before
    with pytest.raises(ManifestBlocked) as unsponsored:
        await service.submit(
            SubmitRequest(
                manifest_yaml=MINIMAL.read_text(encoding="utf-8"),
                request_id=uuid4(),
                actor=OWNER,
                sponsorship_refs=frozenset(),
            )
        )
    assert unsponsored.value.issues[0].reason == "no_sponsorship"
    assert await stack.val("SELECT count(*) FROM mission_control.mission") == before


@pytest.mark.asyncio
async def test_chain_submit_arms_links_and_admits_only_the_first_mission(stack: Stack) -> None:  # noqa: F811
    service = await stack.build()
    receipt, _ = await service.submit(request(MISSION_2.read_text(encoding="utf-8")))
    assert receipt.chain_id is not None
    research, ingestion = receipt.missions
    assert (research.mission_key, ingestion.mission_key) == ("research", "ingestion")
    assert research.run_id is not None and ingestion.run_id is None
    links = await stack.fetch(
        "SELECT link_key, state, from_mission_id, to_mission_id FROM mission_control.chain_link "
        "WHERE chain_id = $1 ORDER BY link_key",
        receipt.chain_id,
    )
    assert [(row["link_key"], row["state"]) for row in links] == [
        ("research->ingestion:depends_on", "armed"),
        ("research->ingestion:supplies", "armed"),
    ]
    assert {row["to_mission_id"] for row in links} == {ingestion.mission_id}
    (frozen,) = await stack.fetch(
        "SELECT mission_key, family, initial_goal, autostart, run_request "
        "FROM mission_control.chain_member_admission WHERE chain_id = $1",
        receipt.chain_id,
    )
    assert (frozen["mission_key"], frozen["family"], frozen["autostart"]) == (
        "ingestion",
        "GoalDirected",
        True,
    )
    assert "knowledge graph" in frozen["initial_goal"]
    assert (
        await stack.val(
            "SELECT count(*) FROM mission_control.mission_run WHERE mission_id = $1",
            ingestion.mission_id,
        )
        == 0
    )
    provenance_chains = await stack.fetch(
        "SELECT mission_key, chain_id FROM mission_control.authoring_provenance "
        "WHERE chain_id = $1 ORDER BY mission_key",
        receipt.chain_id,
    )
    assert [row["mission_key"] for row in provenance_chains] == ["ingestion", "research"]


@pytest.mark.asyncio
async def test_start_launches_with_the_mission_id_and_registers_subscriptions(
    stack: Stack,  # noqa: F811
) -> None:
    service = await stack.build()
    receipt, _ = await service.submit(request(goal_loop_manifest()))
    (mission,) = receipt.missions
    assert mission.family == "GoalDirected" and mission.run_id is not None
    started = await service.start(mission.run_id, OWNER)
    (call,) = stack.submitter.calls
    assert call["mission_id"] == str(mission.mission_id)
    assert call["family"] == "GoalDirected"
    assert started.family == "GoalDirected" and started.workflow_id.startswith("wf:")
    (subscription,) = started.subscriptions
    assert subscription.channel == "stream_ticket"
    rows = await stack.fetch(
        "SELECT target_kind, run_id FROM mission_control.mission_subscription "
        "WHERE mission_id = $1",
        mission.mission_id,
    )
    assert [(row["target_kind"], row["run_id"]) for row in rows] == [("run", mission.run_uuid)]
    # A second start re-registers nothing (the submitter fake leaves the run pending).
    again = await service.start(mission.run_id, OWNER)
    assert again.subscriptions[0].subscription_id == subscription.subscription_id
    assert (
        await stack.val(
            "SELECT count(*) FROM mission_control.mission_subscription WHERE mission_id = $1",
            mission.mission_id,
        )
        == 1
    )
    assert await service.head_run(mission.mission_id) == mission.run_id


async def _row_counts(db: CommonDatabase) -> dict[str, int]:
    """Every common table's row count, read as the superuser owner (no RLS filtering)."""

    connection = await asyncpg.connect(db.owner_dsn)
    try:
        tables = await connection.fetch(
            "SELECT format('%I.%I', n.nspname, c.relname) AS name FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('mission_control', 'mission_control_search') AND c.relkind = 'r' "
            "ORDER BY 1"
        )
        return {
            row["name"]: await connection.fetchval(f"SELECT count(*) FROM {row['name']}")
            for row in tables
        }
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_a_submit_for_an_unprovisioned_tenant_is_refused_typed_before_any_write(
    stack: Stack,  # noqa: F811
) -> None:
    """W1 D8: without its `mission_control.tenant` row a submit used to fail on the mission
    foreign key as an untyped 500, after compile had already persisted definitions; it is now
    `TenantNotProvisioned` before compile and no common table gains a row."""

    stack.scope = stack.db.scope("tenant-never-provisioned")
    service = await stack.build()
    before = await _row_counts(stack.db)
    assert before, "the common schemas have tables"
    with pytest.raises(TenantNotProvisioned, match="mission-db tenant-apply"):
        await service.submit(request(MINIMAL.read_text(encoding="utf-8")))
    assert await _row_counts(stack.db) == before
    assert TenantNotProvisioned.code == "tenant_not_provisioned"
    # A provisioned tenant of the same installation still submits.
    stack.scope = stack.db.scope()
    receipt, _replayed = await (await stack.build()).submit(
        request(MINIMAL.read_text(encoding="utf-8"))
    )
    assert receipt.missions

"""Builders for tests on the common mission_control component (disposable PostgreSQL).

Scoped requests and commands, owner queries, admitted runtime units, lane units over
PostgreSQL, and the catalog seed helpers. The fixtures that create the databases live in
``tests.support.db_plugin``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.postgres.operations.checkpoint_lineage import (
    PostgresCheckpointLineageRepository,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.execution.service import RunControlService
from mission_control.contracts.identities import parse_request_scope, uuid7
from mission_control.domain.composition.chain import ChainScope, MissionChain
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
)
from mission_control.domain.frames.contracts import HarnessExecutionStart, LaneProfile
from mission_control.domain.graph_runtime.identities import RuntimeUnitIdentity
from mission_control.domain.policies.contracts import (
    CommandStatus,
    LifecycleCommand,
    RunRequest,
    StartAction,
)
from mission_control_db_contract.seeds import _apply_record
from tests.support.checkpoint_lineage import (
    LINEAGE_NOW,
    activity_attempt,
    namespace_claim,
    stage_unit,
)
from tests.support.db import COMPONENT_VERSION, CommonDatabase
from tests.support.ids import AI_ENGINEER_INSTALLATION_ID, catalog_scope
from tests.support.lanes import LaneStack, cursor_binding, cursor_operation, lane_stack
from tests.support.provider_frames import BINDING_DIGEST
from tests.support.run_control import command as unit_command
from tests.support.run_control import request as unit_request
from tests.support.run_control import service as run_control_service


def scoped_request(db: CommonDatabase, tenant: str = "tenant-1", **kwargs: Any) -> RunRequest:
    """The unit-test Run Request bound to a canonical scope of this database."""

    return unit_request(request_scope=db.scope(tenant), **kwargs)


def scoped_command(
    db: CommonDatabase,
    run_id: str,
    version: int,
    command_id: str,
    action: object,
    tenant: str = "tenant-1",
) -> LifecycleCommand:
    return unit_command(run_id, version, command_id, action).model_copy(
        update={"request_scope": db.scope(tenant)}
    )


async def owner_rows(db: CommonDatabase, query: str, *args: Any) -> list[asyncpg.Record]:
    """Owner-side inspection for lineage assertions (never used by the code under test)."""

    connection = await asyncpg.connect(db.owner_dsn)
    try:
        return list(await connection.fetch(query, *args))
    finally:
        await connection.close()


async def scoped_count(pool: asyncpg.Pool, scope: str | None, table: str) -> int:
    """Count rows visible to a restricted role with (or without) transaction scope."""

    from mission_control.adapters.postgres.scope import apply_scope

    async with pool.acquire() as connection, connection.transaction():
        if scope is not None:
            await apply_scope(connection, scope)
        return int(await connection.fetchval(f"SELECT count(*) FROM mission_control.{table}"))


async def assert_admission_lineage(db: CommonDatabase, run_key: str) -> None:
    """Exactly one mission/definition/revision/program/run linked by scoped keys, with a
    contiguous event sequence and outbox rows linked to events and their commit."""

    rows = await owner_rows(
        db,
        """
        SELECT run.run_id, run.mission_id, run.revision_id, run.scheduling_revision_id,
               rev.revision_no, rev.definition_snapshot_id, snap.definition_digest,
               prog.program_digest, m.next_event_seq, m.last_event_seq
        FROM mission_control.mission_run run
        JOIN mission_control.mission m USING (installation_id, application_id, tenant_id,
                                              mission_id)
        JOIN mission_control.mission_revision rev
          ON rev.installation_id = run.installation_id
         AND rev.application_id = run.application_id AND rev.tenant_id = run.tenant_id
         AND rev.revision_id = run.revision_id AND rev.mission_id = run.mission_id
        JOIN mission_control.definition_snapshot snap
          ON snap.installation_id = rev.installation_id
         AND snap.application_id = rev.application_id AND snap.tenant_id = rev.tenant_id
         AND snap.definition_snapshot_id = rev.definition_snapshot_id
        JOIN mission_control.compiled_program prog
          ON prog.installation_id = rev.installation_id
         AND prog.application_id = rev.application_id AND prog.tenant_id = rev.tenant_id
         AND prog.revision_id = rev.revision_id
        WHERE run.run_key = $1
        """,
        run_key,
    )
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["revision_no"] == 1
    assert row["scheduling_revision_id"] == row["revision_id"]
    counts = await owner_rows(
        db,
        """
        SELECT
          (SELECT count(*) FROM mission_control.definition_snapshot WHERE mission_id = $1) AS s,
          (SELECT count(*) FROM mission_control.mission_revision WHERE mission_id = $1) AS r,
          (SELECT count(*) FROM mission_control.mission_run WHERE mission_id = $1) AS runs
        """,
        row["mission_id"],
    )
    assert (counts[0]["s"], counts[0]["r"], counts[0]["runs"]) == (1, 1, 1)
    events = await owner_rows(
        db,
        """
        SELECT e.seq, e.event_id, e.ledger_commit_id, o.event_id AS outbox_event,
               o.ledger_commit_id AS outbox_commit, c.first_event_seq, c.last_event_seq
        FROM mission_control.mission_event e
        JOIN mission_control.outbox o
          ON o.installation_id = e.installation_id AND o.application_id = e.application_id
         AND o.tenant_id = e.tenant_id AND o.event_id = e.event_id
        JOIN mission_control.ledger_commit c
          ON c.installation_id = e.installation_id AND c.application_id = e.application_id
         AND c.tenant_id = e.tenant_id AND c.ledger_commit_id = e.ledger_commit_id
        WHERE e.mission_id = $1 ORDER BY e.seq
        """,
        row["mission_id"],
    )
    assert [item["seq"] for item in events] == list(range(1, len(events) + 1))
    assert events, "admission must append mission events"
    assert row["last_event_seq"] == len(events)
    assert row["next_event_seq"] == len(events) + 1
    for item in events:
        assert item["outbox_commit"] == item["ledger_commit_id"]
        assert item["first_event_seq"] <= item["seq"] <= item["last_event_seq"]


@dataclass(frozen=True)
class AdmittedUnit:
    run_key: str
    unit: RuntimeUnitIdentity
    run_control: RunControlService

    def start(
        self,
        *,
        generation: int = 1,
        lane: LaneProfile = LaneProfile.DEEP_AGENTS,
        native_session_ref: str | None = None,
    ) -> HarnessExecutionStart:
        from mission_control.application.frames.sink import harness_execution_id

        return HarnessExecutionStart(
            harness_execution_id=harness_execution_id(
                request_scope=self.unit.request_scope,
                run_key=self.run_key,
                activation_key=self.unit.unit_key,
                attempt_no=1,
                lane=lane.value,
            ),
            request_scope=self.unit.request_scope,
            run_key=self.run_key,
            activation_key=self.unit.unit_key,
            attempt_no=1,
            generation=generation,
            lane_profile=lane,
            native_session_ref=native_session_ref or f"thread:{self.unit.unit_key}",
            runtime_kind="deep_agent",
            provider_kind="langgraph",
            placement_kind="local_in_worker",
            intended_binding_digest=BINDING_DIGEST,
            launch_key="launch-1",
        )


async def admit_unit_attempt(
    pool: asyncpg.Pool, db: CommonDatabase, *, tenant: str = "tenant-1", start: bool = True
) -> AdmittedUnit:
    """Admit (and start) a run, then record one runtime-unit attempt (activation + attempt)."""

    run_control, _ = run_control_service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
    decision = await run_control.admit(scoped_request(db, tenant, request_id=f"frames-{uuid4()}"))
    assert decision.run_id is not None
    if start:
        started = await run_control.execute(
            scoped_command(db, decision.run_id, 1, f"start-{uuid4()}", StartAction(), tenant)
        )
        assert started.status == CommandStatus.ACCEPTED
    unit = stage_unit(
        request_scope=db.scope(tenant), run_id=decision.run_id, operation_id="stage:collect"
    )
    claim = namespace_claim(unit)
    await PostgresCheckpointLineageRepository(pool).record_attempt(
        unit=unit,
        execution_generation=1,
        attempt=activity_attempt(1, workflow_id=f"operation/{unit.unit_key}"),
        binding_id=f"binding:{unit.unit_key}:1",
        binding_digest=claim.binding_digest,
        namespace=claim,
        dispatching=True,
        observed_at=LINEAGE_NOW,
    )
    return AdmittedUnit(run_key=decision.run_id, unit=unit, run_control=run_control)


FIXTURE_ACTOR = "fixture:catalog-artifacts-tests"


BIOTECH_CATALOG = catalog_scope("biotech")


AI_ENGINEER_CATALOG = catalog_scope("ai-engineer")


ROOT = Path(__file__).resolve().parents[2]


SEEDS = ROOT / "packages" / "mission-control-db-contract" / "seeds"


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def add_disabled_installation(database: CommonDatabase) -> None:
    connection = await asyncpg.connect(database.owner_dsn)
    try:
        await connection.execute(
            """INSERT INTO mission_control.application_installation
               (installation_id, application_id, supabase_project_ref, environment,
                schema_component_version, state, created_at)
               VALUES ($1, 'ai-engineer', 'mcdisposableaieng', 'disposable', $2, 'disabled',
                       clock_timestamp())
               ON CONFLICT DO NOTHING""",
            AI_ENGINEER_INSTALLATION_ID,
            COMPONENT_VERSION,
        )
    finally:
        await connection.close()


async def apply_seed_bundle(database: CommonDatabase, bundle: dict[str, Any]) -> dict[str, int]:
    """Apply one seed bundle's records as the owner (the seed record writer, in one transaction)."""

    target = {
        "installation_id": str(database.installation_id),
        "application_id": database.application_id,
    }
    stats = {"created": 0, "reused": 0, "revoked": 0}
    connection = await asyncpg.connect(database.owner_dsn)
    try:
        async with connection.transaction():
            for record in bundle["records"]:
                await _apply_record(connection, target, bundle, record, stats)
    finally:
        await connection.close()
    return stats


def seeds_publish_module() -> Any:
    """``scripts/seeds_publish_bundles.py`` (FT-A7 custody upload of the agent-skill seeds)."""

    spec = importlib.util.spec_from_file_location(
        "ft_a7_publish_db", ROOT / "scripts" / "seeds_publish_bundles.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def insert_fixture_run(database: CommonDatabase, request_scope: str, run_key: str) -> UUID:
    """Owner-inserted canonical mission/revision/run chain (test setup only).

    Stands in for the runtime lane's admission so artifact custody can reference a real
    ``mission_run`` row; it is labeled fixture data and never used outside tests.
    """
    scope = parse_request_scope(request_scope)
    key = (scope.installation_id, scope.application_id, scope.tenant_id)
    now = datetime.now(UTC)
    mission_id, snapshot_id, revision_id, run_id = uuid7(), uuid7(), uuid7(), uuid7()
    definition = {"fixture": run_key}
    connection = await asyncpg.connect(database.owner_dsn)
    try:
        async with connection.transaction():
            await connection.execute(
                """INSERT INTO mission_control.mission
                   (installation_id, application_id, tenant_id, mission_id, mission_key, title,
                    owner_actor_ref, lifecycle, next_event_seq, version, updated_at,
                    last_event_seq, created_at, created_by_actor_ref)
                   VALUES ($1,$2,$3,$4,$5,'fixture mission',$6,'active',1,1,$7,0,$7,$6)""",
                *key,
                mission_id,
                "mission:" + run_key,
                FIXTURE_ACTOR,
                now,
            )
            await connection.execute(
                """INSERT INTO mission_control.definition_snapshot
                   (installation_id, application_id, tenant_id, definition_snapshot_id,
                    mission_id, definition_contract_version, definition, definition_digest,
                    created_at, created_by_actor_ref)
                   VALUES ($1,$2,$3,$4,$5,'fixture/1',$6::jsonb,$7,$8,$9)""",
                *key,
                snapshot_id,
                mission_id,
                json.dumps(definition),
                _digest(definition),
                now,
                FIXTURE_ACTOR,
            )
            await connection.execute(
                """INSERT INTO mission_control.mission_revision
                   (installation_id, application_id, tenant_id, revision_id, mission_id,
                    revision_no, definition_snapshot_id, policy_digest, binding_digest,
                    committed_at, created_at, created_by_actor_ref)
                   VALUES ($1,$2,$3,$4,$5,1,$6,$7,$7,$8,$8,$9)""",
                *key,
                revision_id,
                mission_id,
                snapshot_id,
                _digest("fixture-policy"),
                now,
                FIXTURE_ACTOR,
            )
            await connection.execute(
                """INSERT INTO mission_control.mission_run
                   (installation_id, application_id, tenant_id, run_id, run_key, mission_id,
                    revision_id, scheduling_revision_id, request_key, input_manifest_ref,
                    input_digest, admission_binding_ref, admission_binding_digest,
                    workflow_family, phase, lifecycle, execution_epoch, execution_generation,
                    technical_segment, admitted_policy_ref, admitted_build_ref,
                    projection_contract, projection, version, admitted_at, updated_at,
                    created_at, created_by_actor_ref)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$7,$8,'fixture://input',$9,'fixture://binding',
                           $9,'stagegraph','active','active',1,1,1,'fixture-policy',
                           'fixture-build','fixture.run/1','{}'::jsonb,1,$10,$10,$10,$11)""",
                *key,
                run_id,
                run_key,
                mission_id,
                revision_id,
                "request:" + run_key,
                _digest(definition),
                now,
                FIXTURE_ACTOR,
            )
    finally:
        await connection.close()
    return run_id


@dataclass
class PgLaneUnit:
    operation: OperationExecutionRequest
    stack: LaneStack
    frames: PostgresFrameRepository
    states: PostgresLaneExecutionStateStore

    @property
    def identity(self) -> LaneExecutionIdentity:
        return LaneExecutionIdentity.of(self.operation, "cursor_local", 1)

    @property
    def send_key(self) -> str:
        return f"{self.identity.harness_execution_id}:1:turn:1"

    def service(self, owner: str, *, min_lease_s: float = 1.0, **extra: Any) -> LaneTurnService:
        return LaneTurnService(
            lanes=self.stack.service._lanes,
            boundary=self.stack.boundary,
            frames=self.frames,
            states=self.states,
            frame_reader=self.frames,
            sessions=WorkerSessionManager(
                owner_ref=owner, min_lease=timedelta(seconds=min_lease_s)
            ),
            **extra,
        )


async def pg_lane_unit(
    pool: asyncpg.Pool, db: CommonDatabase, lane: Any, *, task_queue: str | None = None
) -> PgLaneUnit:
    admitted = await admit_unit_attempt(pool, db)
    unit = admitted.unit
    binding = cursor_binding(task_queue=task_queue) if task_queue else None
    payload = cursor_operation(binding=binding).model_dump(mode="python")
    payload.update(
        request_scope=unit.request_scope,
        identity=OperationAttemptIdentity(
            run_id=admitted.run_key,
            operation_id=unit.semantic_operation_id,
            operation_attempt=unit.semantic_attempt,
        ),
        runtime_unit=unit,
        idempotency_key=f"mp06:{unit.unit_key}",
    )
    operation = OperationExecutionRequest.model_validate(payload)
    stack = lane_stack(lane, operation=operation)
    return PgLaneUnit(
        operation=operation,
        stack=stack,
        frames=PostgresFrameRepository(pool),
        states=PostgresLaneExecutionStateStore(pool),
    )


# --- mission chains (migration 0028) ----------------------------------------------------------

CHAIN_MANIFEST = ROOT / "tests/fixtures/manifests/two-mission-chain.yml"
CHAIN_NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


async def insert_mission(connection: asyncpg.Connection, scope: ChainScope, key: str) -> UUID:
    """One draft `mission` row under `scope` (the caller's connection carries the scope)."""

    mission_id = uuid4()
    await connection.execute(
        """
        INSERT INTO mission_control.mission (installation_id, application_id, tenant_id,
            mission_id, mission_key, title, owner_actor_ref, lifecycle, next_event_seq,
            version, updated_at, last_event_seq, created_at, created_by_actor_ref)
        VALUES ($1, $2, $3, $4, $5, $5, 'actor:owner', 'draft', 1, 1, $6, 0, $6, 'actor:owner')
        """,
        scope.installation_id,
        scope.application_id,
        scope.tenant_id,
        mission_id,
        key,
        CHAIN_NOW,
    )
    return mission_id


async def insert_chain(connection: asyncpg.Connection, chain: MissionChain) -> None:
    """The `mission_chain` row and its `chain_link` rows, exactly as built."""

    scope = chain.scope
    await connection.execute(
        """
        INSERT INTO mission_control.mission_chain (installation_id, application_id, tenant_id,
            chain_id, chain_key, title, manifest_digest, lifecycle, phase, terminal_outcome,
            members, version, created_at, updated_at, created_by_actor_ref)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL, $10::jsonb, 1, $11, $11, $12)
        """,
        scope.installation_id,
        scope.application_id,
        scope.tenant_id,
        chain.chain_id,
        chain.chain_key,
        chain.title,
        chain.manifest_digest,
        chain.lifecycle.value,
        chain.phase.value,
        json.dumps([member.model_dump(mode="json") for member in chain.members]),
        chain.created_at,
        chain.created_by_actor_ref,
    )
    for link in chain.links:
        await connection.execute(
            """
            INSERT INTO mission_control.chain_link (installation_id, application_id, tenant_id,
                link_id, chain_id, link_key, from_mission_key, to_mission_key, from_mission_id,
                to_mission_id, kind, bindings, release_condition, on_upstream_cancel,
                on_upstream_not_accepted, state, version, created_at, updated_at,
                created_by_actor_ref)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb, $14,
                $15, $16, 1, $17, $17, $18)
            """,
            scope.installation_id,
            scope.application_id,
            scope.tenant_id,
            link.link_id,
            chain.chain_id,
            link.link_key,
            link.from_mission_key,
            link.to_mission_key,
            link.from_mission_id,
            link.to_mission_id,
            link.kind.value,
            json.dumps([binding.model_dump(mode="json") for binding in link.bindings]),
            json.dumps(link.on.model_dump(mode="json", exclude_none=True)),
            link.on_upstream_cancel.value,
            link.on_upstream_not_accepted,
            link.state.value,
            chain.created_at,
            chain.created_by_actor_ref,
        )

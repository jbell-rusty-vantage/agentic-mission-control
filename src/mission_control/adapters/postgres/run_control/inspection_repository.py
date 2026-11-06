"""PostgreSQL inspection reads (REQ-CP-RUN-011): one READ ONLY, scope-bound snapshot.

Every read runs in a single `READ ONLY` repeatable-read transaction with the composite
mission_control scope applied, so PostgreSQL itself refuses any write the read path might
attempt, forced RLS confines rows to the caller's installation, application and tenant,
and a run's projection, ledgers, units and journal are observed at one consistent point.
The queries select explicit columns and digest-bound payloads only: never message or
command payloads, checkpoint bodies, transcripts, or secrets.

The same queries serve the API's runtime pool (`mission_control_runtime`) and the
read-only inspection role (`mission_control_readonly`).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

import asyncpg

from mission_control.adapters.postgres.operations.checkpoint_lineage import (
    GENERATION_COLUMNS,
    GENERATION_JOIN,
    NAMESPACE_COLUMNS,
    fetch_rejections,
    generation_from_row,
    namespace_from_row,
    rejection_from_row,
)
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE, scoped
from mission_control.application.execution.inspection import RunRecord, RunSnapshot, UnitRecord
from mission_control.application.execution.operations.checkpoint_lineage import (
    NamespaceRecord,
    UnitGenerationRecord,
)
from mission_control.contracts.contracts import (
    BudgetDimensionView,
    BudgetView,
    UnitFailureView,
)
from mission_control.domain.execution.checkpoint_lineage import (
    ActivityAttemptObservation,
    CheckpointTransitionObservation,
    LineageWriteRejection,
    UnitReconciliationIncident,
    UnitResultObservation,
)
from mission_control.domain.graph_runtime.identities import RuntimeUnitIdentity
from mission_control.domain.policies.contracts import (
    BoundaryCommandReceipt,
    BoundaryCommandRecord,
    BoundaryCommandStatus,
    RunPhase,
    RunProjection,
)
from mission_control.domain.policies.inspection import (
    AsyncChildInspection,
    JournalClaimInspection,
    JournalSettlementSummary,
    TechnicalAttempt,
)

UNIT_INCIDENT_TYPE = "runtime_unit_in_doubt"
# W1 D39: the evidence prefix of the root's failed-family terminalization (`family_failure.py`).
FAMILY_FAILURE_CAUSE = "family-failure-cause:"


class PostgresInspectionReadRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_runs(
        self,
        request_scope: str,
        *,
        phases: frozenset[RunPhase],
        after_run_id: str | None,
        limit: int,
    ) -> tuple[tuple[RunRecord, ...], datetime]:
        async with self._pool.acquire() as connection:
            async with connection.transaction(readonly=True, isolation="repeatable_read"):
                args, observed_at = await _scope(connection, request_scope)
                rows = await connection.fetch(
                    f"""
                    SELECT projection, updated_at
                    FROM mission_control.mission_run
                    WHERE {SCOPE}
                      AND ($4::text IS NULL OR run_key > $4)
                      AND (cardinality($5::text[]) = 0 OR phase = ANY($5::text[]))
                    ORDER BY run_key
                    LIMIT $6
                    """,
                    *args,
                    after_run_id,
                    sorted(phase.value for phase in phases),
                    limit,
                )
        return (
            tuple(
                RunRecord(
                    projection=RunProjection.model_validate(_load(row["projection"])),
                    updated_at=row["updated_at"],
                )
                for row in rows
            ),
            observed_at,
        )

    async def read_run(
        self, request_scope: str, run_id: str, *, unit_key: str | None = None
    ) -> RunSnapshot | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction(readonly=True, isolation="repeatable_read"):
                args, observed_at = await _scope(connection, request_scope)
                run = await mc.run_row(connection, args, run_id)
                if run is None:
                    return None
                budget = await mc.budget_state(connection, args, run_key=run_id)
                effects = await mc.effect_state(connection, args, run_id)
                units = await _units(connection, args, request_scope, run_id, unit_key)
                children = await _async_children(connection, args, run_id)
                commands = await _boundary_commands(connection, args, run["run_id"])
                incomplete = await _points_incomplete(connection, args, run["run_id"])
        return RunSnapshot(
            run=RunRecord(
                projection=RunProjection.model_validate(_load(run["projection"])),
                updated_at=run["updated_at"],
            ),
            observed_at=observed_at,
            budget=budget,
            effects=effects,
            units=units,
            async_children=children,
            boundary_commands=commands,
            points_incomplete=incomplete,
        )


class PostgresPointsStatusReader:
    """`PointsStatusReader` over the cognition point rows (1.4.4, P6.1)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def points_incomplete(self, request_scope: str, run_id: str) -> tuple[str, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args, _observed_at = await _scope(connection, request_scope)
            run = await mc.run_row(connection, args, run_id)
            if run is None:
                return ()
            return await _points_incomplete(connection, args, run["run_id"])


class PostgresUnitFailureReader:
    """`UnitFailureReader` over the durable failure facts a run already records.

    - Goal Directed documents (tracing Stage 2, F-T3-1): every executor iteration and
      verification settled with an `irrecoverable_failure_ref`, its reason code being the
      reference's prefix (`output_unparseable:<evidence digest>`).
    - W1 D39/D40: every operation unit settled `failed` or `timed_out`, by its typed
      `failure_code` (`transient_transport`, `runtime_failed`, `context_delivery_blocked`, ...;
      R2-MC D1 read only the last). Provider text is never read (the settlement records none).
    - W1 D39: a family workflow that ended without terminalizing its run, by the typed cause
      the root's terminal transition records (`family-failure-cause:<cause>`): a unit that
      failed in Temporal with no settlement (a refused, exhausted `operation.execute`) is
      otherwise visible only in Temporal history.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def unit_failures(self, request_scope: str, run_id: str) -> tuple[UnitFailureView, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args, _observed_at = await _scope(connection, request_scope)
            rows = await connection.fetch(
                f"""
                SELECT d.contract,
                       coalesce(d.payload->'result', d.payload->'verification') AS body
                FROM mission_control.runtime_document d
                WHERE {scoped("d")}
                  AND d.contract IN ('goal.iteration/1', 'goal.verification/1')
                  AND d.identity LIKE $4
                  AND coalesce(
                      d.payload->'result'->>'irrecoverable_failure_ref',
                      d.payload->'verification'->>'irrecoverable_failure_ref',
                      ''
                  ) <> ''
                ORDER BY d.recorded_at
                """,
                *args,
                json.dumps([run_id])[:-1] + ",%",
            )
            # R2-MC D1: a dependent invocation whose required context could not be delivered
            # never started; its operation settled `context_delivery_blocked` (any family).
            # W1 D40: every other typed unit failure is read the same way.
            blocked = await connection.fetch(
                f"""
                SELECT DISTINCT claim.semantic_binding_key, claim.semantic_attempt_key,
                       coalesce(settlement.failure_code, settlement.status) AS failure_code
                FROM mission_control.operation_settlement settlement
                JOIN mission_control.operation_claim claim
                  ON claim.installation_id = settlement.installation_id
                 AND claim.application_id = settlement.application_id
                 AND claim.tenant_id = settlement.tenant_id
                 AND claim.claim_key = settlement.claim_key
                WHERE {scoped("settlement")}
                  AND claim.run_key = $4
                  AND settlement.status IN ('failed', 'timed_out')
                ORDER BY claim.semantic_attempt_key
                """,
                *args,
                run_id,
            )
            terminal = await connection.fetch(
                f"""
                SELECT t.transition->'evidence_refs' AS evidence_refs
                FROM mission_control.run_lifecycle_transition t
                WHERE {scoped("t")}
                  AND t.run_key = $4
                  AND t.transition->>'resulting_phase' = 'terminal'
                ORDER BY t.occurred_at
                """,
                *args,
                run_id,
            )
        failures: list[UnitFailureView] = []
        for row in blocked:
            code = str(row["failure_code"])
            failures.append(
                UnitFailureView(
                    unit=str(row["semantic_binding_key"]),
                    reason=code,
                    failure_ref=f"{code}:{row['semantic_attempt_key']}",
                )
            )
        failures.extend(_family_failures(terminal))
        for row in rows:
            body = row["body"]
            if isinstance(body, str):
                body = json.loads(body)
            ref = str(body["irrecoverable_failure_ref"])
            executor = row["contract"] == "goal.iteration/1"
            identity = body["identity"] if executor else body["executor_identity"]
            iteration = identity["iteration"]["goal_iteration"]
            failures.append(
                UnitFailureView(
                    unit=f"goal/{iteration}/{'executor' if executor else 'verifier'}",
                    reason=ref.split(":", 1)[0],
                    failure_ref=ref,
                )
            )
        return tuple(failures)


def _family_failures(rows: Any) -> list[UnitFailureView]:
    """W1 D39: the typed cause of a family that ended without terminalizing its run."""

    failures: list[UnitFailureView] = []
    for row in rows:
        refs = row["evidence_refs"]
        if isinstance(refs, str):
            refs = json.loads(refs)
        refs = [str(item) for item in refs or ()]
        family = next(
            (item.split(":", 1)[1] for item in refs if item.startswith("family-workflow:")),
            "family",
        )
        for item in refs:
            if item.startswith(FAMILY_FAILURE_CAUSE):
                cause = item[len(FAMILY_FAILURE_CAUSE) :]
                failures.append(
                    UnitFailureView(
                        unit=f"family/{family}",
                        reason="family_workflow_failed",
                        failure_ref=f"family_workflow_failed:{cause}",
                    )
                )
    return failures


class PostgresBudgetViewReader:
    """`BudgetViewReader` over the run's budget account (`canonical.budget_state`)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def budget(self, request_scope: str, run_id: str) -> BudgetView | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args, _observed_at = await _scope(connection, request_scope)
            state = await mc.budget_state(connection, args, run_key=run_id)
        if state is None:
            return None
        dimensions = tuple(
            BudgetDimensionView(
                dimension=limit.dimension,
                hard_cap=limit.hard_cap,
                reserved=int(state.reserved.get(limit.dimension, 0)),
                consumed=int(state.consumed.get(limit.dimension, 0)),
                pending=int(state.pending_settlement.get(limit.dimension, 0)),
                exhausted=limit.hard_cap is not None
                and int(state.consumed.get(limit.dimension, 0)) >= limit.hard_cap,
            )
            for limit in state.limits
        )
        return BudgetView(
            account_id=state.account_id,
            dimensions=dimensions,
            exhausted=tuple(item.dimension for item in dimensions if item.exhausted),
        )


async def _points_incomplete(
    connection: asyncpg.Connection, args: tuple[Any, ...], run_id: Any
) -> tuple[str, ...]:
    """1.4.4 (P6.1): units whose latest generation's result point records an incomplete
    points walk (`channel_facts.points_status`), the typed `points_incomplete` outcome."""

    rows = await connection.fetch(
        f"""
        SELECT DISTINCT p.unit_key
        FROM mission_control.cognition_point p
        WHERE {scoped("p")} AND p.run_id = $4 AND p.pruned_at IS NULL
          AND 'result' = ANY(p.roles)
          AND p.channel_facts->>'points_status' = 'incomplete'
          AND p.execution_generation = (
              SELECT max(q.execution_generation) FROM mission_control.cognition_point q
              WHERE {scoped("q")} AND q.run_id = p.run_id AND q.unit_key = p.unit_key
          )
        ORDER BY p.unit_key
        """,
        *args,
        run_id,
    )
    return tuple(str(row["unit_key"]) for row in rows)


async def _boundary_commands(
    connection: asyncpg.Connection, args: tuple[Any, ...], run_uuid: Any
) -> tuple[BoundaryCommandStatus, ...]:
    rows = await connection.fetch(
        f"""
        SELECT c.payload,
               (SELECT array_agg(r.detail ORDER BY (r.detail->>'ordinal')::integer)
                FROM mission_control.delivery_report r
                WHERE r.installation_id = c.installation_id
                  AND r.application_id = c.application_id AND r.tenant_id = c.tenant_id
                  AND r.command_id = c.command_id) AS receipts
        FROM mission_control.command c
        WHERE {scoped("c")} AND c.run_id = $4 AND c.target_kind IS NOT NULL
        ORDER BY c.sequence_space, c.target_sequence, c.created_at,
                 c.payload->'record'->>'command_id'
        """,
        *args,
        run_uuid,
    )
    statuses: list[BoundaryCommandStatus] = []
    for row in rows:
        payload = _load(row["payload"])
        statuses.append(
            BoundaryCommandStatus(
                command=BoundaryCommandRecord.model_validate(payload["record"]),
                receipts=(
                    BoundaryCommandReceipt.model_validate(payload["initial_receipt"]),
                    *(
                        BoundaryCommandReceipt.model_validate(_load(item))
                        for item in row["receipts"] or ()
                    ),
                ),
            )
        )
    return tuple(statuses)


async def _scope(
    connection: asyncpg.Connection, request_scope: str
) -> tuple[tuple[Any, ...], datetime]:
    args = await mc.begin(connection, request_scope)
    observed_at: datetime = await connection.fetchval("SELECT clock_timestamp()")
    return args, observed_at


async def _units(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    request_scope: str,
    run_id: str,
    unit_key: str | None,
) -> tuple[UnitRecord, ...]:
    identity_rows = await connection.fetch(
        f"""
        SELECT a.activation_key AS unit_key, a.governor_projection AS identity_payload
        FROM mission_control.activation a
        JOIN mission_control.mission_run run
          ON run.installation_id = a.installation_id AND run.application_id = a.application_id
         AND run.tenant_id = a.tenant_id AND run.run_id = a.run_id
        WHERE {scoped("a")} AND run.run_key = $4
          AND a.phase LIKE 'runtime_unit:%'
          AND ($5::text IS NULL OR a.activation_key = $5)
        ORDER BY a.created_at, a.activation_key
        """,
        *args,
        run_id,
        unit_key,
    )
    if not identity_rows:
        return ()
    keys = [row["unit_key"] for row in identity_rows]
    generations: dict[str, list[UnitGenerationRecord]] = defaultdict(list)
    for row in await connection.fetch(
        f"""
        SELECT {GENERATION_COLUMNS} {GENERATION_JOIN}
        WHERE {scoped("g")} AND g.unit_key = ANY($4::text[])
        ORDER BY g.unit_key, g.execution_generation
        """,
        *args,
        keys,
    ):
        generations[row["unit_key"]].append(generation_from_row(row))
    attempts = await _payloads(
        connection,
        f"""
        SELECT unit_key, observation_payload AS payload
        FROM mission_control.activity_attempt_observation
        WHERE {SCOPE} AND unit_key = ANY($4::text[])
        ORDER BY execution_generation, activity_attempt, observed_at
        """,
        *args,
        keys,
    )
    transitions = await _payloads(
        connection,
        f"""
        SELECT unit_key, transition_payload AS payload
        FROM mission_control.checkpoint_transition
        WHERE {SCOPE} AND unit_key = ANY($4::text[])
        ORDER BY execution_generation
        """,
        *args,
        keys,
    )
    results = await _payloads(
        connection,
        f"""
        SELECT unit_key, result_payload AS payload
        FROM mission_control.unit_result_observation
        WHERE {SCOPE} AND unit_key = ANY($4::text[])
        ORDER BY execution_generation
        """,
        *args,
        keys,
    )
    incidents = await _payloads(
        connection,
        f"""
        SELECT target_ref AS unit_key, detail AS payload
        FROM mission_control.reconciliation_case
        WHERE {SCOPE} AND target_kind = $5 AND target_ref = ANY($4::text[])
        ORDER BY (detail->>'execution_generation')::bigint,
                 COALESCE((detail->>'revision')::bigint, 1)
        """,
        *args,
        keys,
        UNIT_INCIDENT_TYPE,
    )
    rejections: dict[str, list[LineageWriteRejection]] = defaultdict(list)
    for row in await fetch_rejections(connection, args, keys):
        rejections[row["unit_key"]].append(rejection_from_row(row, request_scope))
    namespace_names = sorted(
        {
            record.namespace
            for records in generations.values()
            for record in records
            if record.namespace is not None
        }
    )
    namespaces: dict[str, NamespaceRecord] = {}
    for row in await connection.fetch(
        f"""
        SELECT {NAMESPACE_COLUMNS} FROM mission_control.cognitive_namespace
        WHERE {SCOPE} AND namespace_key = ANY($4::text[])
        """,
        *args,
        namespace_names,
    ):
        namespaces[row["namespace_key"]] = namespace_from_row(row)
    journal = await _journal(connection, args, keys)
    units: list[UnitRecord] = []
    for row in identity_rows:
        key = row["unit_key"]
        unit_namespaces = {
            record.namespace for record in generations[key] if record.namespace is not None
        }
        units.append(
            UnitRecord(
                identity=RuntimeUnitIdentity.model_validate(_load(row["identity_payload"])),
                generations=tuple(generations[key]),
                attempts=tuple(
                    ActivityAttemptObservation.model_validate(item) for item in attempts[key]
                ),
                transitions=tuple(
                    CheckpointTransitionObservation.model_validate(item)
                    for item in transitions[key]
                ),
                results=tuple(UnitResultObservation.model_validate(item) for item in results[key]),
                incidents=tuple(
                    UnitReconciliationIncident.model_validate(item) for item in incidents[key]
                ),
                rejections=tuple(rejections[key]),
                namespaces=tuple(
                    namespaces[name] for name in sorted(unit_namespaces) if name in namespaces
                ),
                journal=journal.get(key, ()),
            )
        )
    return tuple(units)


async def _payloads(connection: asyncpg.Connection, query: str, *args: Any) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in await connection.fetch(query, *args):
        grouped[row["unit_key"]].append(_load(row["payload"]))
    return grouped


async def _journal(
    connection: asyncpg.Connection, args: tuple[Any, ...], keys: list[str]
) -> dict[str, tuple[JournalClaimInspection, ...]]:
    claims = await connection.fetch(
        f"""
        SELECT claim_key, unit_key, semantic_binding_key, semantic_binding_digest, status,
               claimed_at
        FROM mission_control.operation_claim
        WHERE {SCOPE} AND unit_key = ANY($4::text[])
        ORDER BY claimed_at, claim_key
        """,
        *args,
        keys,
    )
    if not claims:
        return {}
    claim_ids = [row["claim_key"] for row in claims]
    attempts: dict[str, list[TechnicalAttempt]] = defaultdict(list)
    for row in await connection.fetch(
        f"""
        SELECT claim_key, technical_attempt, provider, disposition, retry_class,
               started_at, finished_at, failure_code
        FROM mission_control.operation_technical_attempt
        WHERE {SCOPE} AND claim_key = ANY($4::text[])
        ORDER BY technical_attempt
        """,
        *args,
        claim_ids,
    ):
        attempts[row["claim_key"]].append(
            TechnicalAttempt(
                technical_attempt=row["technical_attempt"],
                provider=row["provider"],
                disposition=row["disposition"],
                retry_class=row["retry_class"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                failure_code=row["failure_code"],
            )
        )
    settlements: dict[str, list[JournalSettlementSummary]] = defaultdict(list)
    for row in await connection.fetch(
        f"""
        SELECT claim_key, settlement_key, settlement_revision, status, result_manifest_ref,
               result_manifest_digest, failure_code, usage_payload,
               pending_external_usage_payload, settled_at
        FROM mission_control.operation_settlement
        WHERE {SCOPE} AND claim_key = ANY($4::text[])
        ORDER BY settlement_revision
        """,
        *args,
        claim_ids,
    ):
        settlements[row["claim_key"]].append(
            JournalSettlementSummary(
                settlement_id=row["settlement_key"],
                settlement_revision=row["settlement_revision"],
                status=row["status"],
                result_manifest_ref=row["result_manifest_ref"],
                result_manifest_digest=row["result_manifest_digest"],
                failure_code=row["failure_code"],
                usage=_int_map(row["usage_payload"]),
                pending_external_usage=_int_map(row["pending_external_usage_payload"]),
                settled_at=row["settled_at"],
            )
        )
    grouped: dict[str, list[JournalClaimInspection]] = defaultdict(list)
    for row in claims:
        claim_id = row["claim_key"]
        grouped[row["unit_key"]].append(
            JournalClaimInspection(
                effect_claim_id=claim_id,
                semantic_binding_id=row["semantic_binding_key"],
                semantic_binding_digest=row["semantic_binding_digest"],
                status=row["status"],
                claimed_at=row["claimed_at"],
                technical_attempts=tuple(attempts[claim_id]),
                settlements=tuple(settlements[claim_id]),
            )
        )
    return {key: tuple(items) for key, items in grouped.items()}


async def _async_children(
    connection: asyncpg.Connection, args: tuple[Any, ...], run_id: str
) -> tuple[AsyncChildInspection, ...]:
    rows = await connection.fetch(
        f"""
        SELECT subordinate_key, subordinate_id, parent_operation_key, link_key, contract_key,
               contract_digest, execution_generation, dependency_class, cancellation_requested,
               result_decision, result_manifest_digest, settlement_ref
        FROM mission_control.subordinate_admission
        WHERE {SCOPE} AND parent_run_key = $4
        ORDER BY created_at, subordinate_key
        """,
        *args,
        run_id,
    )
    if not rows:
        return ()
    lifecycle: dict[str, str] = {}
    for fact in await connection.fetch(
        f"""
        SELECT payload->>'child_execution_id' AS child_execution_id,
               payload->>'fact_ref' AS fact_ref
        FROM mission_control.native_observation
        WHERE {SCOPE} AND payload->>'fact_kind' = 'lifecycle'
          AND subordinate_id = ANY($4::uuid[])
        ORDER BY received_at, native_event_key
        """,
        *args,
        [row["subordinate_id"] for row in rows],
    ):
        # Latest recorded lifecycle fact wins; values are shown as recorded (tolerant of
        # lifecycle values introduced after this reader, such as `in_doubt`).
        lifecycle[fact["child_execution_id"]] = fact["fact_ref"]
    return tuple(
        AsyncChildInspection(
            child_execution_id=row["subordinate_key"],
            parent_operation_id=row["parent_operation_key"],
            link_id=row["link_key"],
            contract_id=row["contract_key"],
            binding_digest=row["contract_digest"],
            execution_generation=row["execution_generation"],
            dependency_class=row["dependency_class"],
            lifecycle=lifecycle.get(row["subordinate_key"]),
            result_decision=row["result_decision"],
            result_manifest_digest=row["result_manifest_digest"],
            settlement_ref=row["settlement_ref"],
            cancellation_requested=row["cancellation_requested"],
        )
        for row in rows
    )


def _int_map(value: Any) -> dict[str, int]:
    loaded = _load(value) or {}
    return {str(key): int(amount) for key, amount in loaded.items() if isinstance(amount, int)}


def _load(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value

"""The decision table writers (1.4.4, TRACING-PROPOSAL P3.8, P10 "Decision table").

`completion_candidate` and `completion_decision` (`M/0003:381-432`) predate the output-contract
and verification design; Stage 1 reuses them as they are, unused columns NULL. Two writers:

- `insert_completion_records` runs inside a transaction the caller owns: the family admission
  commit (`PostgresRunControlRepository.commit_family_admission`) calls it with the journal
  row, so a Stage Graph `result_decided` writes its decision and candidate atomically with the
  mutation.
- `PostgresCompletionRepository.record` opens its own transaction for writers that have no
  family transaction at hand (the Goal Directed verifier reconciliation).

Both are idempotent by key (`ON CONFLICT (…, candidate_key | decision_key) DO NOTHING`), so a
retried mutation or reconciliation re-issues the same rows harmlessly (P8). The candidate's
`activation_id` is resolved from its `activation_key` (the unit key the attempt's
`record_attempt` wrote); a candidate whose activation row is absent is not written, and the
decision then keeps `candidate_id` NULL rather than failing the family transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.contracts.identities import uuid7
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.programs.contracts import (
    CompletionCandidateRecord,
    CompletionDecisionRecord,
    CompletionRecords,
)


async def _activation_id(
    connection: asyncpg.Connection, args: tuple[Any, ...], activation_key: str | None
) -> UUID | None:
    if activation_key is None:
        return None
    value = await connection.fetchval(
        f"""
        SELECT activation_id FROM mission_control.activation
        WHERE {SCOPE} AND activation_key = $4
        """,
        *args,
        activation_key,
    )
    return value if isinstance(value, UUID) else None


async def _candidate_id(
    connection: asyncpg.Connection, args: tuple[Any, ...], candidate_key: str | None
) -> UUID | None:
    if candidate_key is None:
        return None
    value = await connection.fetchval(
        f"""
        SELECT candidate_id FROM mission_control.completion_candidate
        WHERE {SCOPE} AND candidate_key = $4
        """,
        *args,
        candidate_key,
    )
    return value if isinstance(value, UUID) else None


async def insert_candidate(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    record: CompletionCandidateRecord,
    *,
    actor_ref: str,
    recorded_at: datetime,
) -> UUID | None:
    """Insert one candidate; return its id (new or existing), or None when its activation row
    does not exist yet."""

    activation_id = await _activation_id(connection, args, record.activation_key)
    if activation_id is None:
        return None
    await connection.execute(
        """
        INSERT INTO mission_control.completion_candidate (
            installation_id, application_id, tenant_id, candidate_id, activation_id,
            attempt_id, candidate_key, execution_generation, candidate, candidate_digest,
            artifact_refs, evidence_refs, submitted_at, created_at, created_by_actor_ref
        )
        VALUES ($1, $2, $3, $4, $5, NULL, $6, $7, $8::jsonb, $9, $10::text[], $11::text[],
                $12, $13, $14)
        ON CONFLICT (installation_id, application_id, tenant_id, candidate_key) DO NOTHING
        """,
        *args,
        uuid7(),
        activation_id,
        record.candidate_key,
        record.execution_generation,
        mc.dump(record.candidate),
        sha256_digest(record.candidate),
        list(record.artifact_refs),
        list(record.evidence_refs),
        record.submitted_at or recorded_at,
        recorded_at,
        actor_ref,
    )
    return await _candidate_id(connection, args, record.candidate_key)


async def insert_decision(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    record: CompletionDecisionRecord,
    *,
    run_key: str,
    actor_ref: str,
    recorded_at: datetime,
    candidate_id: UUID | None = None,
) -> None:
    run_id = await mc.run_uuid(connection, args, run_key)
    activation_id = await _activation_id(connection, args, record.activation_key)
    if candidate_id is None:
        candidate_id = await _candidate_id(connection, args, record.candidate_key)
    await connection.execute(
        """
        INSERT INTO mission_control.completion_decision (
            installation_id, application_id, tenant_id, completion_decision_id, decision_key,
            run_id, activation_id, goal_id, candidate_id, policy_digest, contract_digest,
            result_disposition, requirement_refs, result_refs, reason_codes, decision,
            decided_at, created_at, created_by_actor_ref
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, NULL, $8, $9, $10, $11, $12::text[], $13::text[],
                $14::text[], $15::jsonb, $16, $17, $18)
        ON CONFLICT (installation_id, application_id, tenant_id, decision_key) DO NOTHING
        """,
        *args,
        uuid7(),
        record.decision_key,
        run_id,
        activation_id,
        candidate_id,
        record.policy_digest,
        record.contract_digest,
        record.result_disposition,
        list(record.requirement_refs),
        list(record.result_refs),
        list(record.reason_codes),
        mc.dump(record.decision),
        record.decided_at or recorded_at,
        recorded_at,
        actor_ref,
    )


async def insert_completion_records(
    connection: asyncpg.Connection,
    args: tuple[Any, ...],
    records: CompletionRecords,
    *,
    run_key: str,
    actor_ref: str,
    recorded_at: datetime,
) -> None:
    """Write the candidate (when its activation exists) and the decision in the caller's
    transaction; the decision names the candidate written with it."""

    candidate_id: UUID | None = None
    if records.candidate is not None:
        candidate_id = await insert_candidate(
            connection, args, records.candidate, actor_ref=actor_ref, recorded_at=recorded_at
        )
    if records.decision is not None:
        await insert_decision(
            connection,
            args,
            records.decision,
            run_key=run_key,
            actor_ref=actor_ref,
            recorded_at=recorded_at,
            candidate_id=candidate_id,
        )


class PostgresCompletionRepository:
    """`CompletionRecordPort` over the runtime pool: one transaction per call."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(
        self,
        request_scope: str,
        run_id: str,
        records: CompletionRecords,
        *,
        actor_ref: str,
        recorded_at: datetime,
    ) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            await insert_completion_records(
                connection,
                args,
                records,
                run_key=run_id,
                actor_ref=actor_ref,
                recorded_at=recorded_at,
            )

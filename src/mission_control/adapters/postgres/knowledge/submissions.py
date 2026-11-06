"""``OutputSubmissionStore`` over ``output_submission`` / ``invocation_finalization``.

Release 1.5.0 tables with the 1.6.0 assessment handoff: ``start_assessment`` moves a pending
submission to ``assessing`` naming the independent ``report.assess`` handle (operation id and
binding, fixed afterwards); ``record_assessment`` records the service's terminal verdict
(``assessed``/``held``/``rejected``); the finalization stores its ``outcome_basis``.

One transaction per act under transaction-local tenant scope and a per-invocation advisory
lock, so revisions are dense and a finalization is ordered after every accepted submission.
The ``output_submission_guard`` trigger refuses the same (invocation, obligation, key) with
another selection digest as ``SUBMISSION_CONFLICT`` (SQLSTATE MCE02) before the unique index
is consulted; an identical retry falls through ``ON CONFLICT DO NOTHING`` to the stored row.
``invocation_finalization`` is append-only and unique per invocation.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.ports.knowledge import (
    FinalizationCandidate,
    FinalizationRecord,
    JournalVersionConflict,
    SubmissionCandidate,
    SubmissionClosed,
    SubmissionConflict,
    SubmissionRecord,
)

SUBMISSION_CONFLICT_SQLSTATE = "MCE02"
_SUBMISSION = "mission_control.output_submission"
_FINALIZATION = "mission_control.invocation_finalization"


def _submission(row: asyncpg.Record) -> SubmissionRecord:
    return SubmissionRecord(
        submission_id=str(row["submission_id"]),
        invocation_ref=row["invocation_ref"],
        obligation_id=row["obligation_id"],
        submission_key=row["submission_key"],
        revision=int(row["revision"]),
        selection_digest=row["selection_digest"],
        assessment_state=row["assessment_state"],
        selection=mc.load(row["selection"]),
        version=int(row["version"]),
        assessment_operation_id=row["assessment_operation_id"],
        assessment_binding=row["assessment_binding"],
        assessment_ref=row["assessment_ref"],
        assessment_digest=row["assessment_digest"],
    )


def _finalization(row: asyncpg.Record) -> FinalizationRecord:
    report: dict[str, Any] = mc.load(row["report"])
    return FinalizationRecord(
        finalization_id=str(row["finalization_id"]),
        invocation_ref=row["invocation_ref"],
        outcome=row["outcome"],
        submission_ids=tuple(str(item) for item in row["submission_ids"]),
        report=report,
        report_digest=row["report_digest"],
        outcome_basis=row["outcome_basis"],
    )


async def _lock(connection: asyncpg.Connection, scope: str, invocation_ref: str) -> None:
    await mc.advisory_lock(connection, f"output_submission:{scope}:{invocation_ref}")


class PostgresOutputSubmissionStore:
    """RLS-scoped submissions and finalization for one runtime-role pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record_selection(self, candidate: SubmissionCandidate) -> SubmissionRecord:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, candidate.scope)
            await apply_actor(connection, candidate.actor_ref)
            await _lock(connection, candidate.scope, candidate.invocation_ref)
            if await connection.fetchval(
                f"SELECT 1 FROM {_FINALIZATION} WHERE {SCOPE} AND invocation_ref = $4",
                *args,
                candidate.invocation_ref,
            ):
                raise SubmissionClosed(f"invocation {candidate.invocation_ref} is finalized")
            revision = await connection.fetchval(
                f"SELECT COALESCE(max(revision), 0) + 1 FROM {_SUBMISSION} "
                f"WHERE {SCOPE} AND invocation_ref = $4 AND obligation_id = $5",
                *args,
                candidate.invocation_ref,
                candidate.obligation_id,
            )
            try:
                row = await connection.fetchrow(
                    f"INSERT INTO {_SUBMISSION} (installation_id, application_id, tenant_id, "
                    "submission_id, run_id, operation_ref, operation_attempt, "
                    "execution_generation, unit_key, invocation_ref, obligation_id, "
                    "submission_key, revision, selection, selection_digest, assessment_state, "
                    "version, submitted_at, updated_at, created_at, created_by_actor_ref) "
                    "VALUES ($1, $2, $3, $4, $5::uuid, $6, $7, $8, $9, $10, $11, $12, $13, "
                    "$14::jsonb, $15, 'pending', 1, $16, $16, $16, $17) "
                    "ON CONFLICT DO NOTHING RETURNING *",
                    *args,
                    uuid4(),
                    candidate.run_id,
                    candidate.operation_ref,
                    candidate.operation_attempt,
                    candidate.execution_generation,
                    candidate.unit_key,
                    candidate.invocation_ref,
                    candidate.obligation_id,
                    candidate.submission_key,
                    revision,
                    json.dumps(candidate.selection, sort_keys=True),
                    candidate.selection_digest,
                    candidate.at,
                    candidate.actor_ref,
                )
            except asyncpg.PostgresError as error:
                if getattr(error, "sqlstate", None) == SUBMISSION_CONFLICT_SQLSTATE:
                    raise SubmissionConflict(
                        f"SUBMISSION_CONFLICT {candidate.submission_key}"
                    ) from None
                raise
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT * FROM {_SUBMISSION} WHERE {SCOPE} AND invocation_ref = $4 "
                    "AND obligation_id = $5 AND submission_key = $6",
                    *args,
                    candidate.invocation_ref,
                    candidate.obligation_id,
                    candidate.submission_key,
                )
        if row is None:  # pragma: no cover - the conflicting row is visible in this scope
            raise SubmissionConflict(f"submission {candidate.submission_key} is not visible")
        return _submission(row)

    async def list_for_invocation(self, scope: str, invocation_ref: str) -> list[SubmissionRecord]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT * FROM {_SUBMISSION} WHERE {SCOPE} AND invocation_ref = $4 "
                "ORDER BY obligation_id, revision",
                *args,
                invocation_ref,
            )
        return [_submission(row) for row in rows]

    async def start_assessment(
        self,
        scope: str,
        submission_id: str,
        *,
        expected_version: int,
        operation_id: str,
        binding_id: str,
        actor_ref: str,
        at: datetime,
    ) -> SubmissionRecord:
        return await self._assessment(
            scope,
            submission_id,
            expected_version,
            actor_ref,
            "assessment_state = 'assessing', assessment_operation_id = $6, "
            "assessment_binding = $7, assessment_requested_at = $8",
            "assessment_state = 'pending'",
            (operation_id, binding_id, at),
            at,
        )

    async def record_assessment(
        self,
        scope: str,
        submission_id: str,
        *,
        expected_version: int,
        state: str,
        assessment_ref: str,
        assessment_digest: str | None,
        actor_ref: str,
        at: datetime,
    ) -> SubmissionRecord:
        return await self._assessment(
            scope,
            submission_id,
            expected_version,
            actor_ref,
            "assessment_state = $6, assessment_ref = $7, assessment_digest = $8, assessed_at = $9",
            "assessment_state = 'assessing'",
            (state, assessment_ref, assessment_digest, at),
            at,
        )

    async def _assessment(
        self,
        scope: str,
        submission_id: str,
        expected_version: int,
        actor_ref: str,
        assignments: str,
        state_guard: str,
        values: tuple[object, ...],
        at: datetime,
    ) -> SubmissionRecord:
        at_param = 6 + len(values)
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            row = await connection.fetchrow(
                f"UPDATE {_SUBMISSION} SET {assignments}, version = version + 1, "
                f"updated_at = GREATEST(${at_param}::timestamptz, updated_at) "
                f"WHERE {SCOPE} AND submission_id = $4::uuid AND version = $5 "
                f"AND {state_guard} RETURNING *",
                *args,
                submission_id,
                expected_version,
                *values,
                at,
            )
        if row is None:
            raise JournalVersionConflict(f"submission {submission_id} moved on")
        return _submission(row)

    async def finalize(self, candidate: FinalizationCandidate) -> FinalizationRecord:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, candidate.scope)
            await apply_actor(connection, candidate.actor_ref)
            await _lock(connection, candidate.scope, candidate.invocation_ref)
            row = await connection.fetchrow(
                f"INSERT INTO {_FINALIZATION} (installation_id, application_id, tenant_id, "
                "finalization_id, run_id, operation_ref, operation_attempt, "
                "execution_generation, invocation_ref, outcome, submission_ids, report, "
                "report_digest, finalized_at, created_at, created_by_actor_ref, outcome_basis) "
                "VALUES ($1, $2, $3, $4, $5::uuid, $6, $7, $8, $9, $10, $11::uuid[], "
                "$12::jsonb, $13, $14, $14, $15, $16) "
                "ON CONFLICT DO NOTHING RETURNING *",
                *args,
                uuid4(),
                candidate.run_id,
                candidate.operation_ref,
                candidate.operation_attempt,
                candidate.execution_generation,
                candidate.invocation_ref,
                candidate.outcome,
                [UUID(item) for item in candidate.submission_ids],
                json.dumps(candidate.report, sort_keys=True),
                candidate.report_digest,
                candidate.at,
                candidate.actor_ref,
                candidate.outcome_basis,
            )
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT * FROM {_FINALIZATION} WHERE {SCOPE} AND invocation_ref = $4",
                    *args,
                    candidate.invocation_ref,
                )
        if row is None:  # pragma: no cover - the unique row is visible in this scope
            raise RuntimeError(f"finalization of {candidate.invocation_ref} is not visible")
        return _finalization(row)


__all__ = ["SUBMISSION_CONFLICT_SQLSTATE", "PostgresOutputSubmissionStore"]

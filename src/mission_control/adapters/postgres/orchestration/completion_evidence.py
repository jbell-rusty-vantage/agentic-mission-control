"""Bounded reads of completion checks from the existing atomic family journal."""

import json

import asyncpg
from pydantic import JsonValue, TypeAdapter, ValidationError

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.missions.completion_evidence import CompletionEvidenceCorrupt
from mission_control.contracts.run_evidence import (
    CompletionDecisionEvidence,
    CompletionEvidencePage,
)
from mission_control.domain.authoring.canonical import contract_fingerprint
from mission_control.domain.programs.completion import CompletionValidation
from mission_control.domain.programs.contracts import StageGraphDecisionMutation


class PostgresCompletionEvidenceReader:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list(
        self,
        request_scope: str,
        run_id: str,
        *,
        after_family_version: int = 0,
        limit: int = 100,
    ) -> CompletionEvidencePage:
        if after_family_version < 0 or not 1 <= limit <= 100:
            raise ValueError("invalid completion evidence page bounds")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            rows = await connection.fetch(
                f"""
                SELECT family_version, mutation_key, mutation_fingerprint, mutation,
                       decided_at
                FROM mission_control.family_admission_journal
                WHERE {mc.SCOPE} AND run_key = $4 AND family_kind = 'stagegraph'
                  AND family_version > $5
                  AND mutation->'decision_payload' ? 'completion_validation'
                ORDER BY family_version ASC LIMIT $6
                """,
                *args,
                run_id,
                after_family_version,
                limit + 1,
            )
        decisions = tuple(_decision(row, request_scope, run_id) for row in rows[:limit])
        return CompletionEvidencePage(
            run_id=run_id,
            status="recorded" if decisions else "not_recorded",
            decisions=decisions,
            next_after_family_version=(decisions[-1].family_version if len(rows) > limit else None),
        )


def _decision(row: asyncpg.Record, request_scope: str, run_id: str) -> CompletionDecisionEvidence:
    try:
        raw = row["mutation"]
        mutation = StageGraphDecisionMutation.model_validate(
            json.loads(raw) if isinstance(raw, str) else raw
        )
        fingerprint = contract_fingerprint(mutation, exclude={"decided_at"})
        if (
            mutation.request_scope != request_scope
            or mutation.run_id != run_id
            or mutation.expected_family_version + 1 != row["family_version"]
            or mutation.mutation_id != row["mutation_key"]
            or fingerprint != row["mutation_fingerprint"]
            or mutation.decided_at != row["decided_at"]
        ):
            raise CompletionEvidenceCorrupt("completion receipt identity or digest mismatch")
        validation = TypeAdapter(dict[str, JsonValue]).validate_python(
            mutation.decision_payload["completion_validation"]
        )
        checked: CompletionValidation | dict[str, JsonValue] = validation
        if validation.get("schema_version") == "mc.stage_completion_validation.v2":
            checked = CompletionValidation.model_validate(validation)
        return CompletionDecisionEvidence(
            request_scope=request_scope,
            run_id=run_id,
            family_version=row["family_version"],
            mutation_id=mutation.mutation_id,
            mutation_fingerprint=fingerprint,
            exact_operation_request_ref=mutation.exact_operation_request_ref,
            decided_at=mutation.decided_at,
            validation=checked,
        )
    except (ValidationError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CompletionEvidenceCorrupt("invalid completion receipt") from exc

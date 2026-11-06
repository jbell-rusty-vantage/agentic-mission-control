"""``CandidateInstallStore`` over ``context_candidate_install`` and its outcome (0060; ADR-0062).

A claim is inserted once per receiver path (``ON CONFLICT DO NOTHING`` on the unique (run,
receiver operation, attempt, generation, path) key) and the stored claim is returned, so a
same-path race has one winner and a retry in the same attempt finds its own claim. An outcome
is inserted once per claim and the stored one returned, so crash recovery records an
installation exactly once. Nothing is updated or deleted; every statement runs under the
request's row-level scope.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.context.hook_contributions import InstallClaim, InstallOutcome
from mission_control.domain.context.contributions import AttributedCandidate

_CLAIM = "mission_control.context_candidate_install"
_OUTCOME = "mission_control.context_candidate_install_outcome"
_CLAIM_COLUMNS = (
    "install_id::text AS install_id, run_id, receiver_operation_ref, receiver_attempt, "
    "target_path, candidate, custody_ref, workspace_generation, boundary, claimed_at"
)
_OUTCOME_COLUMNS = (
    "install_id::text AS install_id, candidate_id::text AS candidate_id, candidate_digest, "
    "realized_backend, probe, recovered, installed_at"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _load(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _claim(row: asyncpg.Record) -> InstallClaim:
    return InstallClaim(
        install_id=row["install_id"],
        run_id=row["run_id"],
        operation_ref=row["receiver_operation_ref"],
        path=row["target_path"],
        candidate=AttributedCandidate.model_validate(_load(row["candidate"])),
        custody_ref=row["custody_ref"],
        attempt=row["receiver_attempt"],
        generation=row["workspace_generation"],
        boundary=row["boundary"],
        claimed_at=row["claimed_at"],
    )


def _outcome(row: asyncpg.Record) -> InstallOutcome:
    return InstallOutcome(
        install_id=row["install_id"],
        candidate_id=row["candidate_id"],
        digest=row["candidate_digest"],
        realized_backend=row["realized_backend"],
        probe=row["probe"],
        recovered=row["recovered"],
        installed_at=row["installed_at"],
    )


class PostgresCandidateInstallStore:
    """RLS-scoped hook candidate claims and outcomes for one runtime-role pool."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        actor_ref: str = "mission-control:hook-contributions",
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._pool = pool
        self._actor_ref = actor_ref
        self._clock = clock

    async def claim(self, scope: str, claim: InstallClaim) -> InstallClaim:
        candidate = claim.candidate
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, self._actor_ref)
            await connection.execute(
                f"INSERT INTO {_CLAIM} (installation_id, application_id, tenant_id, install_id, "
                "run_id, receiver_operation_ref, receiver_attempt, target_path, candidate_id, "
                "candidate_digest, size_bytes, custody_ref, hook_id, hook_event, candidate, "
                "workspace_generation, boundary, claimed_at, created_at, created_by_actor_ref) "
                "VALUES ($1, $2, $3, $4::uuid, $5, $6, $7, $8, $9::uuid, $10, $11, $12, $13, "
                "$14, $15::jsonb, $16, $17, $18, $19, $20) ON CONFLICT DO NOTHING",
                *args,
                claim.install_id,
                claim.run_id,
                claim.operation_ref,
                claim.attempt,
                claim.path,
                candidate.candidate_id,
                candidate.digest,
                candidate.size_bytes,
                claim.custody_ref,
                candidate.origin.hook_id,
                candidate.origin.event.value,
                json.dumps(candidate.model_dump(mode="json"), sort_keys=True),
                claim.generation,
                claim.boundary,
                claim.claimed_at,
                self._clock(),
                self._actor_ref,
            )
            row = await connection.fetchrow(
                f"SELECT {_CLAIM_COLUMNS} FROM {_CLAIM} WHERE {SCOPE} AND run_id = $4 "
                "AND receiver_operation_ref = $5 AND receiver_attempt = $6 "
                "AND workspace_generation = $7 AND target_path = $8",
                *args,
                claim.run_id,
                claim.operation_ref,
                claim.attempt,
                claim.generation,
                claim.path,
            )
        if row is None:  # pragma: no cover - the unique row is visible in this scope
            raise RuntimeError("hook candidate claim is not visible")
        return _claim(row)

    async def outcome(self, scope: str, install_id: str) -> InstallOutcome | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT {_OUTCOME_COLUMNS} FROM {_OUTCOME} WHERE {SCOPE} "
                "AND install_id = $4::uuid",
                *args,
                install_id,
            )
        return None if row is None else _outcome(row)

    async def record_outcome(self, scope: str, outcome: InstallOutcome) -> InstallOutcome:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, self._actor_ref)
            await connection.execute(
                f"INSERT INTO {_OUTCOME} (installation_id, application_id, tenant_id, "
                "install_id, candidate_id, candidate_digest, observed_digest, realized_backend, "
                "probe, recovered, installed_at, created_at, created_by_actor_ref) VALUES ($1, "
                "$2, $3, $4::uuid, $5::uuid, $6, $6, $7, $8, $9, $10, $11, $12) "
                "ON CONFLICT DO NOTHING",
                *args,
                outcome.install_id,
                outcome.candidate_id,
                outcome.digest,
                outcome.realized_backend,
                outcome.probe,
                outcome.recovered,
                outcome.installed_at,
                self._clock(),
                self._actor_ref,
            )
            row = await connection.fetchrow(
                f"SELECT {_OUTCOME_COLUMNS} FROM {_OUTCOME} WHERE {SCOPE} "
                "AND install_id = $4::uuid",
                *args,
                outcome.install_id,
            )
        if row is None:  # pragma: no cover - the unique row is visible in this scope
            raise RuntimeError("hook candidate outcome is not visible")
        return _outcome(row)

    async def claims_for(
        self, scope: str, run_id: str, operation_ref: str, attempt: int, generation: int
    ) -> tuple[InstallClaim, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT {_CLAIM_COLUMNS} FROM {_CLAIM} WHERE {SCOPE} AND run_id = $4 "
                "AND receiver_operation_ref = $5 AND receiver_attempt = $6 "
                "AND workspace_generation = $7 ORDER BY claimed_at, install_id",
                *args,
                run_id,
                operation_ref,
                attempt,
                generation,
            )
        return tuple(_claim(row) for row in rows)


__all__ = ["PostgresCandidateInstallStore"]

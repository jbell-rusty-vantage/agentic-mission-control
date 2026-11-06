"""The ledger identity of a live knowledge invocation (provenance slice 1, OVE-204).

Implements :class:`~mission_control.application.ports.knowledge.InvocationLocator`: one scoped
read of ``mission_run.mission_id`` by the run's public key and of the ``activation`` row attempt
admission (``record_attempt``) inserted for the runtime unit key before the lane executed. Both
values are stable per attempt, so every origin of one attempt (begin, dispatch, settlement,
settlement after a worker restart) names the same mission and activation.

A run absent from the request scope raises
:class:`~mission_control.domain.knowledge.origin.MissionIdentityUnavailable` (fail closed); the
activation is ``None`` without a unit key or without that row.
"""

from __future__ import annotations

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.domain.knowledge.origin import MissionIdentityUnavailable


class PostgresInvocationLocator:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def locate(
        self, request_scope: str, run_key: str, unit_key: str | None
    ) -> tuple[str, str | None]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            row = await connection.fetchrow(
                f"""
                SELECT run.mission_id, activation.activation_id
                FROM mission_control.mission_run AS run
                LEFT JOIN mission_control.activation AS activation
                  ON {mc.scoped("activation")}
                 AND activation.run_id = run.run_id
                 AND activation.activation_key = $5
                WHERE {mc.scoped("run")} AND run.run_key = $4
                """,
                *args,
                run_key,
                unit_key,
            )
        if row is None:
            raise MissionIdentityUnavailable(
                f"run {run_key} is not in request scope {request_scope}: no ledger mission id"
            )
        activation = row["activation_id"]
        return str(row["mission_id"]), None if activation is None else str(activation)


__all__ = ["PostgresInvocationLocator"]

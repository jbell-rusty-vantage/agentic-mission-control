"""Resolve a run in its tenant scope and who launched or revised it (W1 review S3/S4, B1).

The operator review route refuses a reviewer who admitted the run (``mission_run``), owns or
created its mission, or authored one of the mission's revisions: those actors may not approve
their own run's KS use decision. The route names a run by its public run id (``run_key``, the
id every output record and invocation origin carries); the internal ``mission_run.run_id`` is
accepted too and resolved to that same key once, so the actors and the output assessments are
read for one identifier. ``None`` means the run does not exist in this tenant.

A runtime login without ``SELECT`` on ``mission_run``, ``mission`` or ``mission_revision`` fails
closed with :class:`RunActorsUnavailable` naming the table (never an untyped 500).
"""

from __future__ import annotations

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.knowledge.review import ResolvedRun, RunActorsUnavailable

# Longest first: PostgreSQL names the table ("permission denied for table mission_run").
_TABLES = ("mission_revision", "mission_run", "mission")


class PostgresRunActors:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def resolve_run(self, request_scope: str, run_id: str) -> ResolvedRun | None:
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                args = await mc.begin(connection, request_scope)
                row = await connection.fetchrow(
                    """
                    SELECT run.run_key,
                           run.mission_id,
                           run.created_by_actor_ref AS run_actor,
                           mission.owner_actor_ref AS owner_actor,
                           mission.created_by_actor_ref AS mission_actor,
                           ARRAY(
                               SELECT revision.created_by_actor_ref
                               FROM mission_control.mission_revision AS revision
                               WHERE revision.installation_id = run.installation_id
                                 AND revision.application_id = run.application_id
                                 AND revision.tenant_id = run.tenant_id
                                 AND revision.mission_id = run.mission_id
                           ) AS revision_actors
                    FROM mission_control.mission_run AS run
                    JOIN mission_control.mission AS mission
                      ON mission.installation_id = run.installation_id
                     AND mission.application_id = run.application_id
                     AND mission.tenant_id = run.tenant_id
                     AND mission.mission_id = run.mission_id
                    WHERE run.installation_id = $1 AND run.application_id = $2
                      AND run.tenant_id = $3
                      AND (run.run_key = $4 OR run.run_id::text = $4)
                    ORDER BY (run.run_key = $4) DESC
                    LIMIT 1
                    """,
                    *args,
                    run_id,
                )
        except asyncpg.InsufficientPrivilegeError as error:
            missing = next((name for name in _TABLES if name in str(error)), "?")
            raise RunActorsUnavailable(
                f"the runtime login lacks SELECT on mission_control.{missing}"
            ) from None
        if row is None:
            return None
        return ResolvedRun(
            run_key=row["run_key"],
            mission_id=str(row["mission_id"]),
            actors=frozenset(
                {
                    row["run_actor"],
                    row["owner_actor"],
                    row["mission_actor"],
                    *row["revision_actors"],
                }
            ),
        )


__all__ = ["PostgresRunActors"]

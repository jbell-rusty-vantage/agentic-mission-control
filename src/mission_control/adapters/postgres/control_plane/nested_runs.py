"""Admission of a nested body's child run into its parent's mission revision (OVE-176).

The child run executes part of the parent's committed program, so it is admitted under the
parent run's mission and revision (same installation, application and tenant), through exactly
the accepted admission mutation run control commits (``accepted_admission_mutation`` over a
request run control has verified). Idempotent per request: a redelivered activation returns the
child run its first admission created.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from mission_control.adapters.postgres.control_plane.mission_revisions import (
    admit_run_for_revision,
)
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.execution.service import accepted_admission_mutation
from mission_control.application.programs.nested_bodies import NestedLaunchRefused
from mission_control.domain.policies.contracts import RunRequest

WRITER_REF = "mission-control-runtime/nested-runs"


class PostgresNestedRunAdmissions:
    def __init__(self, pool: asyncpg.Pool, *, actor_ref: str = WRITER_REF) -> None:
        self._pool = pool
        self._actor = actor_ref

    async def admit(
        self, request_scope: str, parent_run_id: str, request: RunRequest, verified: Any
    ) -> str:
        mutation = accepted_admission_mutation(request, verified)
        decision = mutation.decision
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            await mc.advisory_lock(connection, f"nested-run:{request.request_id}")
            prior = await mc.receipt_row(
                connection,
                args,
                actor_ref=decision.idempotency_issuer,
                action=mc.ADMIT_ACTION,
                request_key=decision.request_id,
            )
            if prior is not None:
                if prior["payload_digest"] != decision.request_fingerprint:
                    raise NestedLaunchRefused(
                        "nested_admission_conflict", "the nested request was admitted differently"
                    )
                return str(mc.load(prior["result"])["run_id"])
            parent = await connection.fetchrow(
                f"SELECT mission_id, revision_id FROM mission_control.mission_run "
                f"WHERE {mc.SCOPE} AND run_key = $4",
                *args,
                parent_run_id,
            )
            if parent is None:
                raise NestedLaunchRefused(
                    "nested_parent_not_manifest", "the parent run has no mission revision"
                )
            await admit_run_for_revision(
                connection,
                args,
                mutation,
                mission_id=parent["mission_id"],
                revision_id=parent["revision_id"],
                created_by=self._actor,
            )
        assert decision.run_id is not None
        return decision.run_id


__all__ = ["PostgresNestedRunAdmissions"]

"""PostgreSQL Workspace Closures with content-addressed body custody (OVE-204 slice 5).

`mission_control.workspace_closure` holds one row per closure (the `mc.workspace_closure.v1`
manifest, its digest and its counts); `mission_control.workspace_closure_entry` one row per
file (path, raw-byte digest, slot, destination, body state and, for a promoted body, its object
reference). Promoted bodies are staged in the artifact payload store first (content-addressed:
two closures with the same bytes share one object), then the header and entries are inserted in
one transaction, idempotent by `closure_id`.

Rows are append-only (an UPDATE guard refuses changes; no role holds DELETE): the frames
`expire` pass removes closures past `retain_until` of completed runs through the definer
`expire_workspace_closures`. Payload bytes are never deleted here (shared across runs; byte
cleanup needs reference counting).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control.canonical import SCOPE, begin
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadPort
from mission_control.application.frames.artifact_bodies import FrameBodyRecord
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.errors import WorkspaceDigestMismatch
from mission_control.domain.execution.workspace_closure import (
    WorkspaceClosure,
    WorkspaceClosureSummary,
)
from mission_control.domain.policies.errors import IdempotencyConflict

_SERVICE_ACTOR = "service:mission-control-workspace-closures"


class WorkspaceClosureRunMissing(LookupError):
    """The closure names a run key the scope does not hold."""


class PostgresWorkspaceClosures:
    """`WorkspaceClosurePort`, `WorkspaceClosureReader` and `ClosureBodyIndex` over PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool, payloads: ArtifactPayloadPort | None = None) -> None:
        self._pool = pool
        # Reads need no payload store (the API composes the reader without one).
        self._payloads = payloads

    async def put(
        self,
        closure: WorkspaceClosure,
        bodies: Mapping[str, bytes],
        *,
        request_scope: str,
        retain_until: datetime | None,
    ) -> None:
        if not request_scope.strip():
            raise ValueError("workspace closures require explicit request scope")
        if self._payloads is None:
            raise ValueError("recording workspace closures requires the payload store")
        scope_digest = sha256(request_scope.encode("utf-8")).hexdigest()
        object_refs: dict[str, str] = {}
        for item in closure.files:
            if item.body_state != "promoted" or item.digest in object_refs:
                continue
            content = bodies.get(item.digest)
            if content is None:
                raise WorkspaceDigestMismatch("a promoted closure body was not supplied")
            address = await self._payloads.stage(
                artifact_id=f"workspace-closure:{scope_digest}:{closure.closure_id}:{item.digest}",
                content=content,
                content_digest=item.digest,
                media_type=item.media_type,
            )
            if address.content_digest != item.digest or address.size_bytes != item.size_bytes:
                raise WorkspaceDigestMismatch("workspace closure staged address mismatch")
            object_refs[item.digest] = address.object_ref
        manifest = closure.model_dump(mode="json")
        manifest_digest = sha256_digest(manifest)
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            run_uuid = await _run_uuid(connection, args, closure.run_id)
            if run_uuid is None:
                raise WorkspaceClosureRunMissing(closure.run_id)
            status = await connection.execute(
                """INSERT INTO mission_control.workspace_closure
                   (installation_id, application_id, tenant_id, closure_id, run_id, unit_key,
                    execution_generation, harness_execution_id, point_id, boundary, backend,
                    manifest, manifest_digest, manifest_object_ref, file_count, total_bytes,
                    promoted_bytes, complete, retain_until, recorded_at, created_at,
                    created_by_actor_ref)
                   VALUES ($1,$2,$3,$4::uuid,$5,$6,$7,$8::uuid,$9::uuid,$10,$11,$12::jsonb,$13,
                           NULL,$14,$15,$16,$17,$18,$19,clock_timestamp(),$20)
                   ON CONFLICT (installation_id, application_id, tenant_id, closure_id)
                   DO NOTHING""",
                *args,
                closure.closure_id,
                run_uuid,
                closure.unit_key,
                closure.execution_generation,
                _uuid_or_none(closure.harness_execution_id),
                closure.point_id,
                closure.boundary,
                closure.backend,
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                manifest_digest,
                len(closure.files),
                closure.total_bytes,
                closure.promoted_bytes,
                closure.complete,
                retain_until,
                closure.recorded_at,
                _SERVICE_ACTOR,
            )
            if status.endswith(" 0"):
                stored = await connection.fetchval(
                    f"""SELECT manifest_digest FROM mission_control.workspace_closure
                        WHERE {SCOPE} AND closure_id = $4::uuid""",
                    *args,
                    closure.closure_id,
                )
                if stored is None:
                    raise IdempotencyConflict("workspace closure conflicts with another key")
                # Same coordinate, same boundary: a retry. Its files may differ only in what a
                # later capture saw; the first recorded closure stands.
                return
            await connection.executemany(
                """INSERT INTO mission_control.workspace_closure_entry
                   (installation_id, application_id, tenant_id, closure_id, run_id, path,
                    size_bytes, digest, slot, destination, body_state, object_ref, media_type,
                    candidate_id)
                   VALUES ($1,$2,$3,$4::uuid,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
                [
                    (
                        *args,
                        closure.closure_id,
                        run_uuid,
                        item.path,
                        item.size_bytes,
                        item.digest,
                        item.slot,
                        item.destination,
                        item.body_state,
                        object_refs.get(item.digest) if item.body_state == "promoted" else None,
                        item.media_type,
                        item.candidate_id,
                    )
                    for item in closure.files
                ],
            )

    async def get(self, request_scope: str, closure_id: str) -> WorkspaceClosure | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            row = await connection.fetchrow(
                f"""SELECT manifest, manifest_digest FROM mission_control.workspace_closure
                    WHERE {SCOPE} AND closure_id = $4::uuid""",
                *args,
                _uuid_text(closure_id),
            )
        return _closure(row) if row is not None else None

    async def for_point(
        self, request_scope: str, run_key: str, point_id: str
    ) -> tuple[WorkspaceClosure, ...]:
        """The closures recorded for one result point, oldest first (one per boundary)."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            rows = await connection.fetch(
                """SELECT c.manifest, c.manifest_digest
                    FROM mission_control.workspace_closure c
                    JOIN mission_control.mission_run r
                      ON r.installation_id = c.installation_id
                     AND r.application_id = c.application_id
                     AND r.tenant_id = c.tenant_id AND r.run_id = c.run_id
                    WHERE c.installation_id = $1 AND c.application_id = $2
                      AND c.tenant_id = $3 AND r.run_key = $4 AND c.point_id = $5::uuid
                    ORDER BY c.recorded_at, c.closure_id""",
                *args,
                run_key,
                _uuid_text(point_id),
            )
        return tuple(_closure(row) for row in rows)

    async def list_for_run(
        self, request_scope: str, run_key: str
    ) -> tuple[WorkspaceClosureSummary, ...]:
        """Every closure of the run (summaries, oldest first); the newest is the mission end's."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            rows = await connection.fetch(
                """SELECT c.manifest, c.manifest_digest, c.retain_until
                    FROM mission_control.workspace_closure c
                    JOIN mission_control.mission_run r
                      ON r.installation_id = c.installation_id
                     AND r.application_id = c.application_id
                     AND r.tenant_id = c.tenant_id AND r.run_id = c.run_id
                    WHERE c.installation_id = $1 AND c.application_id = $2
                      AND c.tenant_id = $3 AND r.run_key = $4
                    ORDER BY c.recorded_at, c.closure_id""",
                *args,
                run_key,
            )
        return tuple(
            WorkspaceClosureSummary.of(_closure(row), retain_until=row["retain_until"])
            for row in rows
        )

    async def run_closure_body(
        self, request_scope: str, run_key: str, digest: str
    ) -> FrameBodyRecord | None:
        """`ClosureBodyIndex`: the size and media type of a promoted body the run's closures
        reference; None otherwise (a tenant cannot read another run's body by digest)."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            row = await connection.fetchrow(
                """SELECT e.size_bytes, e.media_type
                    FROM mission_control.workspace_closure_entry e
                    JOIN mission_control.mission_run r
                      ON r.installation_id = e.installation_id
                     AND r.application_id = e.application_id
                     AND r.tenant_id = e.tenant_id AND r.run_id = e.run_id
                    WHERE e.installation_id = $1 AND e.application_id = $2
                      AND e.tenant_id = $3 AND r.run_key = $4 AND e.digest = $5
                      AND e.body_state = 'promoted'
                    LIMIT 1""",
                *args,
                run_key,
                digest,
            )
        if row is None:
            return None
        return FrameBodyRecord(
            size_bytes=int(row["size_bytes"]),
            media_type=str(row["media_type"] or "application/octet-stream"),
        )


async def _run_uuid(
    connection: asyncpg.Connection, args: tuple[Any, ...], run_key: str
) -> UUID | None:
    value = await connection.fetchval(
        f"SELECT run_id FROM mission_control.mission_run WHERE {SCOPE} AND run_key = $4",
        *args,
        run_key,
    )
    return value if isinstance(value, UUID) else None


def _closure(row: asyncpg.Record) -> WorkspaceClosure:
    manifest = row["manifest"]
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    if sha256_digest(manifest) != row["manifest_digest"]:
        raise WorkspaceDigestMismatch("workspace closure manifest digest mismatch")
    return WorkspaceClosure.model_validate(manifest)


def _uuid_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _uuid_text(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        # Not a UUID: matches no row (never a SQL cast error the caller would see as 500).
        return "00000000-0000-0000-0000-000000000000"


__all__ = ["PostgresWorkspaceClosures", "WorkspaceClosureRunMissing"]

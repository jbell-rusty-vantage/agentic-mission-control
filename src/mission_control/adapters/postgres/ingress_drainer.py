"""Worker-only PostgreSQL ingress claims and LISTEN hints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from mission_control.adapters.postgres.run_control.canonical import SCOPE, begin, dump
from mission_control.application.signals.drainer import DrainBatch, DrainItem

CREDENTIAL_LIVE_SQL = """(
 EXISTS(SELECT 1 FROM mission_control.ingress_credential c
   WHERE c.installation_id=u.installation_id AND c.application_id=u.application_id
     AND c.tenant_id=u.tenant_id AND u.credential_ref='credential:'||c.credential_id::text
     AND c.revoked_at IS NULL AND c.expires_at>clock_timestamp())
 OR EXISTS(SELECT 1 FROM mission_control.ingress_session_binding b
   WHERE b.installation_id=u.installation_id AND b.application_id=u.application_id
     AND b.tenant_id=u.tenant_id AND u.credential_ref='session:'||b.session_binding_id::text
     AND b.revoked_at IS NULL AND b.expires_at>clock_timestamp())
)"""

# Worker-only drain adapter. Use a dedicated pool: effects acquire the runtime pool.


class _PostgresDrainBatch:
    def __init__(
        self, connection: asyncpg.Connection, args: tuple[Any, ...], items: list[DrainItem]
    ) -> None:
        self._connection, self._args = connection, args
        self.items: Sequence[DrainItem] = items

    async def defer(self, item: DrainItem, outcome: Mapping[str, Any]) -> None:
        await self._connection.execute(
            """UPDATE mission_control.ingress_inbox
            SET outcome=$5::jsonb || jsonb_build_object(
                    'reconciliation_retry_after', clock_timestamp() + interval '5 seconds'),
                last_error=NULL
            WHERE installation_id=$1 AND application_id=$2
              AND (tenant_id=$3 OR tenant_id IS NULL) AND ingress_id=$4 AND state='pending'""",
            *self._args,
            item.ingress_id,
            dump(dict(outcome)),
        )

    async def settle(
        self, item: DrainItem, state: str, outcome: Mapping[str, Any], error: str | None = None
    ) -> None:
        if state not in {"pending", "drained", "rejected", "dead"}:
            raise ValueError("invalid ingress settlement")
        await self._connection.execute(
            """UPDATE mission_control.ingress_inbox
            SET state=$5, attempts=attempts+1,
                drained_at=CASE WHEN $5='pending' THEN NULL ELSE clock_timestamp() END,
                outcome=$6::jsonb, last_error=$7
            WHERE installation_id=$1 AND application_id=$2
              AND (tenant_id=$3 OR tenant_id IS NULL) AND ingress_id=$4 AND state='pending'""",
            *self._args,
            item.ingress_id,
            state,
            dump(dict(outcome)),
            error,
        )


class PostgresIngressDrainStore:
    """Scoped SKIP LOCKED claims held until effects and acknowledgement finish.

    The pool MUST be dedicated to inbox claims, separate from effects' repository pool.
    Cancellation rolls back and releases claims; retry uses immutable effect identities.
    """

    def __init__(self, pool: asyncpg.Pool, request_scope: str) -> None:
        self._pool, self._scope = pool, request_scope

    @asynccontextmanager
    async def claim_batch(self, limit: int) -> AsyncIterator[DrainBatch]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid ingress batch bound")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, self._scope)
            rows = await connection.fetch(
                """SELECT * FROM mission_control.ingress_inbox
                WHERE installation_id=$1 AND application_id=$2
                  AND (tenant_id=$3 OR tenant_id IS NULL) AND state='pending'
                  AND (NOT (COALESCE(outcome, '{}'::jsonb) ? 'reconciliation_retry_after')
                    OR (outcome->>'reconciliation_retry_after')::timestamptz <= clock_timestamp())
                ORDER BY COALESCE((outcome->>'reconciliation_retry_after')::timestamptz,
                                  received_at), received_at, ingress_id
                LIMIT $4 FOR UPDATE SKIP LOCKED""",
                *args,
                limit,
            )
            items = [
                DrainItem(
                    ingress_id=row["ingress_id"],
                    request_scope=self._scope if row["tenant_id"] is not None else None,
                    installation_id=row["installation_id"],
                    application_id=row["application_id"],
                    kind=row["kind"],
                    credential_ref=row["credential_ref"],
                    dedupe_key=row["dedupe_key"],
                    payload=json.loads(row["payload"])
                    if isinstance(row["payload"], str)
                    else dict(row["payload"]),
                    received_at=row["received_at"],
                    run_key=row["run_key"],
                    unit_key=row["unit_key"],
                    generation=row["generation"],
                    attempts=row["attempts"],
                    outcome=(
                        json.loads(row["outcome"])
                        if isinstance(row["outcome"], str)
                        else row["outcome"]
                    )
                    or {},
                )
                for row in rows
            ]
            yield _PostgresDrainBatch(connection, args, items)


@asynccontextmanager
async def listen_ingress(connection: asyncpg.Connection) -> AsyncIterator[Any]:
    """Session/direct connection only, never a transaction-pooler connection.

    Notification payload is ignored. LISTEN is a hint; durable rows are polled every 5 s.
    """

    notified = asyncio.Event()

    def notify(*args: Any) -> None:
        notified.set()

    await connection.add_listener("mc_ingress", notify)
    try:
        yield notified
    finally:
        await connection.remove_listener("mc_ingress", notify)


class PostgresUploadAuthority:
    """Registers verified byte custody, with no assessment/publication authority."""

    def __init__(self, pool: asyncpg.Pool, request_scope: str) -> None:
        self._pool, self._scope = pool, request_scope

    async def rejected(self, upload: Any, reason: str) -> None:
        if upload.request_scope != self._scope:
            raise ValueError("cross-scope artifact cleanup")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, self._scope)
            await connection.execute(
                f"""UPDATE mission_control.ingress_artifact_upload
                SET state='rejected',settled_at=clock_timestamp() WHERE {SCOPE}
                AND artifact_upload_id=$4 AND state='committed'""",
                *args,
                upload.upload_id,
            )

    async def load(self, item: DrainItem) -> Any:
        from uuid import UUID

        from mission_control.application.signals.artifacts import CommittedUpload
        from mission_control.application.signals.drainer import DrainRejected

        if item.request_scope != self._scope:
            raise DrainRejected("artifact_cross_scope_or_stale")
        try:
            upload_id = UUID(str(item.payload["artifact_upload_id"]))
        except (KeyError, ValueError):
            raise DrainRejected("artifact_upload_unknown") from None
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, self._scope)
            row = await connection.fetchrow(
                f"""SELECT * FROM mission_control.ingress_artifact_upload
                WHERE {SCOPE} AND artifact_upload_id=$4""",
                *args,
                upload_id,
            )
        if (
            row is None
            or row["credential_ref"] != item.credential_ref
            or row["run_key"] != item.run_key
            or row["unit_key"] != item.unit_key
            or row["generation"] != item.generation
        ):
            raise DrainRejected("artifact_cross_scope_or_stale")
        return CommittedUpload(
            upload_id,
            self._scope,
            row["run_key"],
            row["generation"],
            row["artifact_ref"],
            row["storage_key"],
            row["declared_sha256"],
            row["size_bytes"],
            row["media_type"],
            row["expires_at"],
        )

    async def require_current(self, upload: Any) -> None:
        from mission_control.application.signals.drainer import DrainRejected

        if upload.request_scope != self._scope:
            raise DrainRejected("artifact_cross_scope_or_stale")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, self._scope)
            row = await connection.fetchrow(
                f"""SELECT u.state, u.declared_sha256, u.size_bytes,
                EXISTS(SELECT 1 FROM mission_control.harness_execution h
                  JOIN mission_control.attempt a ON a.attempt_id=h.attempt_id
                  JOIN mission_control.activation n ON n.activation_id=a.activation_id
                  JOIN mission_control.mission_run r ON r.run_id=h.run_id
                  WHERE h.installation_id=u.installation_id AND h.application_id=u.application_id
                    AND h.tenant_id=u.tenant_id AND r.run_key=u.run_key
                    AND n.activation_key=u.unit_key AND h.generation=u.generation
                    AND h.lifecycle='live') AS current
                FROM mission_control.ingress_artifact_upload u WHERE u.installation_id=$1
                AND u.application_id=$2 AND u.tenant_id=$3 AND u.artifact_upload_id=$4
                AND u.expires_at>clock_timestamp() AND {CREDENTIAL_LIVE_SQL}""",
                *args,
                upload.upload_id,
            )
        if (
            row is None
            or row["state"] not in {"committed", "verified"}
            or not row["current"]
            or (row["declared_sha256"], row["size_bytes"]) != (upload.digest, upload.size_bytes)
        ):
            raise DrainRejected("artifact_cross_scope_or_stale")

    async def existing(self, upload: Any) -> Any:
        from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress

        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, self._scope)
            row = await connection.fetchrow(
                f"""SELECT object_key, content_digest, byte_size
                FROM mission_control.artifact WHERE {SCOPE} AND artifact_key=$4
                AND custody_state='registered' AND artifact_version=1""",
                *args,
                f"ingress-upload:{upload.upload_id}",
            )
        return (
            ArtifactPayloadAddress(
                object_ref=row["object_key"],
                content_digest=row["content_digest"],
                size_bytes=row["byte_size"],
            )
            if row
            else None
        )

    async def verified(self, upload: Any, address: Any) -> None:
        from uuid import NAMESPACE_URL, uuid5

        from mission_control.application.signals.drainer import DrainRejected

        await self.require_current(upload)
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, self._scope)
            current = await connection.fetchval(
                f"""SELECT h.harness_execution_id
                FROM mission_control.ingress_artifact_upload u
                JOIN mission_control.mission_run r ON r.installation_id=u.installation_id
                  AND r.application_id=u.application_id AND r.tenant_id=u.tenant_id
                  AND r.run_key=u.run_key
                JOIN mission_control.harness_execution h ON h.run_id=r.run_id
                JOIN mission_control.attempt a ON a.attempt_id=h.attempt_id
                JOIN mission_control.activation n ON n.activation_id=a.activation_id
                WHERE u.installation_id=$1 AND u.application_id=$2 AND u.tenant_id=$3
                  AND u.artifact_upload_id=$4 AND u.state IN ('committed','verified')
                  AND n.activation_key=u.unit_key AND h.generation=u.generation
                  AND h.lifecycle='live' AND u.expires_at>clock_timestamp()
                  AND {CREDENTIAL_LIVE_SQL} FOR UPDATE OF h,u""",
                *args,
                upload.upload_id,
            )
            if current is None:
                raise DrainRejected("artifact_cross_scope_or_stale")
            key = f"ingress-upload:{upload.upload_id}"
            await connection.execute(
                """INSERT INTO mission_control.artifact
                (installation_id,application_id,tenant_id,artifact_id,artifact_key,producer_run_id,
                 kind,media_type,content_digest,byte_size,storage_kind,object_key,artifact_version,
                 custody_state,detail,updated_at,created_at,created_by_actor_ref)
                SELECT $1,$2,$3,$4,$5,r.run_id,'ingress_upload',$6,$7,$8,'object_store',$9,
                  1,'registered',$10::jsonb,clock_timestamp(),clock_timestamp(),'ingress-custody'
                FROM mission_control.mission_run r WHERE r.installation_id=$1
                  AND r.application_id=$2 AND r.tenant_id=$3 AND r.run_key=$11
                ON CONFLICT (installation_id,application_id,tenant_id,artifact_key) DO NOTHING""",
                *args,
                uuid5(NAMESPACE_URL, f"{self._scope}/{key}"),
                key,
                upload.media_type,
                upload.digest,
                upload.size_bytes,
                address.object_ref,
                dump(
                    {
                        "artifact_upload_id": str(upload.upload_id),
                        "artifact_ref": upload.artifact_ref,
                        "review_state": "unreviewed",
                        "generation": upload.generation,
                    }
                ),
                upload.run_key,
            )
            prior = await connection.fetchrow(
                f"""SELECT content_digest,byte_size,object_key
                FROM mission_control.artifact WHERE {SCOPE} AND artifact_key=$4""",
                *args,
                key,
            )
            if prior is None or (
                prior["content_digest"],
                prior["byte_size"],
                prior["object_key"],
            ) != (upload.digest, upload.size_bytes, address.object_ref):
                raise DrainRejected("custody_address_mismatch")
            await connection.execute(
                f"""UPDATE mission_control.ingress_artifact_upload
                SET state='verified',settled_at=clock_timestamp() WHERE {SCOPE}
                AND artifact_upload_id=$4 AND state='committed'""",
                *args,
                upload.upload_id,
            )

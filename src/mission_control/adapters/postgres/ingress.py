"""PostgreSQL Signal Ingress (migration 0035; SPEC-10 section 3; ADR-0045).

Two sides of the same tables:

* `PostgresIngressStore` is the edge's `IngressStore`. It connects as an `mc_ingress_<app>`
  login (a member of `mission_control_ingress`, which holds no table grant) and makes exactly
  one SECURITY DEFINER function call per request. The functions bind the transaction scope
  themselves from the credential they resolve, so no `apply_scope` precedes them, and each call
  is its own transaction: the pool works through a transaction-mode pooler when its
  connections disable the statement cache (`statement_cache_size=0`).
* `PostgresMintedCredentialStore` (the Secret Broker's `MintedCredentialStore`, ADR-0043) and
  `PostgresSessionBindings` run on the worker as `mission_control_runtime` under one tenant
  scope: they mint and revoke credentials and bind provider sessions, which the edge then
  verifies. Revocation is one UPDATE, so it takes effect at the edge on the next request.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control.canonical import SCOPE, begin, dump
from mission_control.application.secrets.minting import (
    CredentialBinding,
    LaunchBinding,
    MintedCredential,
)
from mission_control.application.signals.ports import (
    AcceptOutcome,
    ArtifactSlotOutcome,
    GateCall,
    GateOutcome,
    InboxItem,
    Principal,
    RequestOutcome,
    RequestStatusOutcome,
    SessionBinding,
)

ACTOR_REF: Final = "mission-control-runtime/secret-broker"


def _item(item: InboxItem) -> dict[str, Any]:
    return {
        "ingress_id": str(item.ingress_id),
        "kind": item.kind,
        "dedupe_key": item.dedupe_key,
        "body_sha256": item.body_sha256,
        "payload": dict(item.payload),
        "seq": item.seq,
    }


class PostgresIngressStore:
    def __init__(self, pool: asyncpg.Pool, *, installation_id: UUID, application_id: str) -> None:
        self._pool = pool
        self._installation_id = installation_id
        self._application_id = application_id

    @property
    def application_id(self) -> str:
        return self._application_id

    async def _row(self, query: str, *args: Any) -> asyncpg.Record:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                query, self._installation_id, self._application_id, *args
            )
        if row is None:
            raise RuntimeError("an ingress function returned no row")
        return row

    async def accept(self, principal: Principal, items: Sequence[InboxItem]) -> AcceptOutcome:
        row = await self._row(
            "SELECT * FROM mission_control.ingress_accept($1, $2, $3, $4, $5, $6, $7, $8::jsonb)",
            principal.tier.value,
            principal.credential,
            principal.provider,
            principal.environment_ref,
            principal.nonce_hash,
            dump([_item(item) for item in items]),
        )
        return AcceptOutcome(row["outcome"], row["accepted"], row["duplicates"])

    async def gate(self, principal: Principal, call: GateCall) -> GateOutcome:
        row = await self._row(
            "SELECT * FROM mission_control.ingress_gate("
            "$1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
            principal.tier.value,
            principal.credential,
            principal.provider,
            call.ingress_id,
            call.dedupe_key,
            call.hook_event,
            call.effect_ref,
            call.effect_kind,
            call.tool,
            call.input_digest,
            call.body_sha256,
        )
        return GateOutcome(row["outcome"], row["decision"], row["reason"])

    async def webhook(self, provider: str, route_ref: str | None, item: InboxItem) -> str:
        row = await self._row(
            "SELECT mission_control.ingress_webhook($1, $2, $3, $4, $5, $6, $7, $8::jsonb) "
            "AS outcome",
            provider,
            route_ref,
            item.ingress_id,
            item.dedupe_key,
            item.body_sha256,
            dump(dict(item.payload)),
        )
        return str(row["outcome"])

    async def prepare_artifact(
        self,
        principal: Principal,
        artifact_upload_id: UUID,
        *,
        artifact_ref: str,
        sha256: str,
        size_bytes: int,
        media_type: str,
        ttl_seconds: int,
    ) -> ArtifactSlotOutcome:
        row = await self._row(
            "SELECT * FROM mission_control.ingress_artifact_prepare("
            "$1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
            principal.tier.value,
            principal.credential,
            principal.provider,
            artifact_upload_id,
            artifact_ref,
            sha256,
            size_bytes,
            media_type,
            ttl_seconds,
        )
        return ArtifactSlotOutcome(
            row["outcome"], row["artifact_upload_id"], row["storage_key"], row["expires_at"]
        )

    async def commit_artifact(
        self, principal: Principal, ingress_id: UUID, artifact_upload_id: UUID
    ) -> RequestOutcome:
        row = await self._row(
            "SELECT * FROM mission_control.ingress_artifact_commit($1, $2, $3, $4, $5, $6, $7)",
            principal.tier.value,
            principal.credential,
            principal.provider,
            ingress_id,
            artifact_upload_id,
        )
        return RequestOutcome(row["outcome"], row["ingress_id"])

    async def request_mission(
        self, principal: Principal, item: InboxItem, *, manifest_ref: str
    ) -> RequestOutcome:
        row = await self._row(
            "SELECT * FROM mission_control.ingress_mission_request("
            "$1, $2, $3, $4, $5, $6, $7, $8::jsonb)",
            principal.credential,
            item.ingress_id,
            item.dedupe_key,
            manifest_ref,
            item.body_sha256,
            dump(dict(item.payload)),
        )
        return RequestOutcome(row["outcome"], row["request_id"])

    async def mission_request_status(
        self, principal: Principal, request_id: UUID
    ) -> RequestStatusOutcome:
        row = await self._row(
            "SELECT * FROM mission_control.ingress_mission_request_status($1, $2, $3, $4)",
            principal.credential,
            request_id,
        )
        return RequestStatusOutcome(
            row["outcome"], row["state"], row["mission_id"], row["reason"], row["lifecycle"]
        )


def _credential(row: asyncpg.Record, request_scope: str) -> MintedCredential:
    binding: CredentialBinding | LaunchBinding = (
        CredentialBinding(
            request_scope=request_scope,
            run_id=row["run_key"],
            unit_id=row["unit_key"],
            generation=row["generation"],
        )
        if row["run_key"] is not None
        else LaunchBinding(request_scope)
    )
    context = row["context"]
    return MintedCredential(
        credential_id=str(row["credential_id"]),
        purpose=row["purpose"],
        digest=row["credential_hash"],
        binding=binding,
        scopes=tuple(row["scopes"]),
        issued_at=row["issued_at"],
        expires_at=row["expires_at"],
        rate_limit_per_minute=row["rate_limit"],
        revoked_at=row["revoked_at"],
        context=json.loads(context) if isinstance(context, str) else dict(context),
    )


class PostgresMintedCredentialStore:
    """`MintedCredentialStore` over `ingress_credential` for one tenant scope."""

    def __init__(
        self, pool: asyncpg.Pool, request_scope: str, *, actor_ref: str = ACTOR_REF
    ) -> None:
        self._pool = pool
        self._scope = request_scope
        self._actor_ref = actor_ref

    def _require_scope(self, request_scope: str) -> None:
        if request_scope != self._scope:
            raise ValueError("this credential store serves another request scope")

    async def insert(self, record: MintedCredential) -> None:
        self._require_scope(record.binding.request_scope)
        run = record.binding if isinstance(record.binding, CredentialBinding) else None
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, self._scope)
            await connection.execute(
                """
                INSERT INTO mission_control.ingress_credential (
                    installation_id, application_id, tenant_id, credential_id, purpose,
                    credential_hash, run_key, unit_key, generation, scopes, context,
                    rate_limit, rate_window_started_at, rate_window_count, issued_at,
                    expires_at, revoked_at, created_by_actor_ref
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, 0, $13,
                        $14, NULL, $15)
                """,
                *args,
                UUID(record.credential_id),
                record.purpose,
                record.digest,
                run.run_id if run else None,
                run.unit_id if run else None,
                run.generation if run else None,
                list(record.scopes),
                dump(dict(record.context)),
                record.rate_limit_per_minute,
                record.issued_at,
                record.expires_at,
                self._actor_ref,
            )

    async def by_digest(self, digest: str) -> MintedCredential | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, self._scope)
            row = await connection.fetchrow(
                f"""
                SELECT credential_id, purpose, credential_hash, run_key, unit_key, generation,
                       scopes, context, rate_limit, issued_at, expires_at, revoked_at
                FROM mission_control.ingress_credential
                WHERE {SCOPE} AND credential_hash = $4
                """,
                *args,
                digest,
            )
        return _credential(row, self._scope) if row is not None else None

    async def revoke(
        self,
        request_scope: str,
        run_id: str,
        *,
        at: datetime,
        unit_id: str | None = None,
        below_generation: int | None = None,
    ) -> int:
        self._require_scope(request_scope)
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, self._scope)
            result = await connection.execute(
                f"""
                UPDATE mission_control.ingress_credential
                SET revoked_at = greatest($5, issued_at)
                WHERE {SCOPE} AND run_key = $4 AND revoked_at IS NULL
                  AND ($6::text IS NULL OR unit_key = $6)
                  AND ($7::integer IS NULL OR generation < $7)
                """,
                *args,
                run_id,
                at,
                unit_id,
                below_generation,
            )
        return int(result.split()[-1])


class PostgresSessionBindings:
    """Provider sessions bound to run generations (`ingress_session_binding`)."""

    def __init__(self, pool: asyncpg.Pool, *, actor_ref: str = ACTOR_REF) -> None:
        self._pool = pool
        self._actor_ref = actor_ref

    async def register(self, binding: SessionBinding, binding_id: UUID) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, binding.request_scope)
            await connection.execute(
                """
                INSERT INTO mission_control.ingress_session_binding (
                    installation_id, application_id, tenant_id, session_binding_id, trust_tier,
                    provider, environment_ref, session_id, nonce_hash, run_key, unit_key,
                    generation, context, rate_limit, rate_window_started_at, rate_window_count,
                    created_at, bound_at, expires_at, revoked_at, created_by_actor_ref
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14,
                        clock_timestamp(), 0, clock_timestamp(),
                        CASE WHEN $8::text IS NULL THEN NULL ELSE clock_timestamp() END,
                        $15, NULL, $16)
                """,
                *args,
                binding_id,
                binding.tier.value,
                binding.provider,
                binding.environment_ref,
                binding.session_id,
                binding.nonce_hash,
                binding.run_key,
                binding.unit_key,
                binding.generation,
                dump(dict(binding.context)),
                binding.rate_limit_per_minute,
                binding.expires_at,
                self._actor_ref,
            )

    async def revoke(
        self,
        request_scope: str,
        run_key: str,
        *,
        at: datetime,
        below_generation: int | None = None,
    ) -> int:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            result = await connection.execute(
                f"""
                UPDATE mission_control.ingress_session_binding
                SET revoked_at = greatest($5, created_at)
                WHERE {SCOPE} AND run_key = $4 AND revoked_at IS NULL
                  AND ($6::integer IS NULL OR generation < $6)
                """,
                *args,
                run_key,
                at,
                below_generation,
            )
        return int(result.split()[-1])


__all__ = ["PostgresIngressStore", "PostgresMintedCredentialStore", "PostgresSessionBindings"]

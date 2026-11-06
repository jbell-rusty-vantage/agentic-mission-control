"""``ContentLineageStore`` over ``mission_control.content_lineage`` (release 1.5.0, 0051).

Append-only provenance facts in the seven SP-10 roles. Each fact gets a deterministic id
(UUIDv5 of subject, role, actor and fact digest), so a replayed write is the same row
(``ON CONFLICT (lineage_id) DO NOTHING``, targeted so that the table's own rules still refuse
a second producer of a subject, a producer fact for an adoption and a role held by the wrong
actor kind). Joins to application
stores are by handle, receipt reference, effect key and digest only, never by key.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.ports.knowledge import LineageEntry
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.knowledge.lineage import ActorKind, LineageFact, ProvenanceRole
from mission_control.domain.knowledge.origin import InvocationOrigin

_TABLE = "mission_control.content_lineage"
_NAMESPACE = uuid5(NAMESPACE_URL, "mission-control:content-lineage")


def lineage_id(entry: LineageEntry) -> str:
    fact = entry.fact
    material = {
        "subject": fact.subject_handle,
        "role": fact.role.value,
        "actor_kind": fact.actor_kind.value,
        "actor_ref": fact.actor_ref,
        "fact": sha256_digest(dict(fact.fact)),
    }
    return str(uuid5(_NAMESPACE, sha256_digest(material)))


class PostgresContentLineageStore:
    """RLS-scoped content lineage for one runtime-role pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(
        self, scope: str, entries: Sequence[LineageEntry], *, actor_ref: str, at: datetime
    ) -> int:
        return await self._record(scope, entries, actor_ref=actor_ref, at=at, registration=False)

    async def record_registration(
        self, scope: str, entries: Sequence[LineageEntry], *, actor_ref: str, at: datetime
    ) -> int:
        return await self._record(scope, entries, actor_ref=actor_ref, at=at, registration=True)

    async def _record(
        self,
        scope: str,
        entries: Sequence[LineageEntry],
        *,
        actor_ref: str,
        at: datetime,
        registration: bool,
    ) -> int:
        written = 0
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            # One ordering across every writer: concurrent identical-byte registrations retain
            # exactly one creator, including races with the strict generic lineage writer.
            handles = sorted({entry.fact.subject_handle for entry in entries})
            for handle in handles:
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    json.dumps(["content-lineage", scope, handle], separators=(",", ":")),
                )
            producers: set[str] = set()
            if registration:
                for handle in handles:
                    incoming = [entry for entry in entries if entry.fact.subject_handle == handle]
                    identities = {(entry.subject_kind, entry.subject_digest) for entry in incoming}
                    if len(identities) != 1 or any(
                        entry.subject_digest is None for entry in incoming
                    ):
                        raise ValueError("registration lineage requires one exact kind and digest")
                    if any(
                        entry.fact.role
                        not in {
                            ProvenanceRole.PRODUCER,
                            ProvenanceRole.CALLER,
                            ProvenanceRole.RECEIPT,
                        }
                        for entry in incoming
                    ):
                        raise ValueError(
                            "registration lineage cannot assert other provenance roles"
                        )
                    rows = await connection.fetch(
                        f"SELECT subject_kind, subject_digest, role FROM {_TABLE} "
                        f"WHERE {SCOPE} AND subject_handle = $4",
                        *args,
                        handle,
                    )
                    if any(
                        (row["subject_kind"], row["subject_digest"]) not in identities
                        for row in rows
                    ):
                        raise ValueError(
                            "registration lineage differs from immutable subject identity"
                        )
                    if any(row["role"] == "producer" for row in rows):
                        producers.add(handle)
            for entry in entries:
                if registration and entry.fact.role is ProvenanceRole.PRODUCER:
                    if entry.fact.subject_handle in producers:
                        continue
                    producers.add(entry.fact.subject_handle)
                fact = entry.fact
                status = await connection.execute(
                    f"INSERT INTO {_TABLE} (installation_id, application_id, tenant_id, "
                    "lineage_id, subject_handle, subject_kind, subject_digest, role, actor_kind, "
                    "actor_ref, actor_origin, run_id, knowledge_operation_id, effect_key, fact, "
                    "recorded_at, created_at, created_by_actor_ref) VALUES ($1, $2, $3, $4::uuid, "
                    "$5, $6, $7, $8, $9, $10, $11::jsonb, $12::uuid, $13::uuid, $14, $15::jsonb, "
                    "$16, $16, $17) ON CONFLICT (lineage_id) DO NOTHING",
                    *args,
                    lineage_id(entry),
                    fact.subject_handle,
                    entry.subject_kind,
                    entry.subject_digest,
                    fact.role.value,
                    fact.actor_kind.value,
                    fact.actor_ref,
                    None
                    if fact.actor_origin is None
                    else json.dumps(fact.actor_origin.model_dump(mode="json")),
                    entry.run_id,
                    entry.knowledge_operation_id,
                    entry.effect_key,
                    json.dumps(dict(fact.fact), sort_keys=True),
                    at,
                    actor_ref,
                )
                written += int(status.rsplit(" ", 1)[-1])
        return written

    async def facts(self, scope: str, subject_handle: str) -> list[LineageFact]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT role, actor_kind, actor_ref, actor_origin, fact FROM {_TABLE} "
                f"WHERE {SCOPE} AND subject_handle = $4 ORDER BY recorded_at, lineage_id",
                *args,
                subject_handle,
            )
        return [
            LineageFact(
                subject_handle=subject_handle,
                role=ProvenanceRole(row["role"]),
                actor_kind=ActorKind(row["actor_kind"]),
                actor_ref=row["actor_ref"],
                actor_origin=None
                if row["actor_origin"] is None
                else InvocationOrigin.model_validate(mc.load(row["actor_origin"])),
                fact=mc.load(row["fact"]),
            )
            for row in rows
        ]


__all__ = ["PostgresContentLineageStore", "lineage_id"]

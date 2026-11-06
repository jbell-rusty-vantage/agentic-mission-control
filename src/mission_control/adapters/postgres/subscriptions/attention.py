"""PostgreSQL delivery-stage observations of coordinator notices (WI-19, migration 0063).

`coordinator_delivery_observation` holds the transport, idle-host wake, model-visible and
retrieval observations of a sealed notification; notice and acknowledgment stay the
notification row's own facts. Rows are inserted once per (notification, stage, key) and never
updated; a repeated key returns the stored row. Every call runs in its own transaction under the
transaction-local tenant scope (forced RLS). Migration 0063 is unregistered until MC 1.8.0:
:meth:`installed` probes for the table so a 1.7.0 database answers "unavailable" instead of
failing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Final
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.adapters.postgres.subscriptions.coordinator_inbox import (
    PostgresCoordinatorInboxStore,
)
from mission_control.application.subscriptions.coordinator import CoordinatorNotification
from mission_control.application.subscriptions.coordinator_ports import (
    NewObservation,
    SealedNotice,
    StoredObservation,
)
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.coordinator.attention import (
    MAX_TRANSPORT_OBSERVATIONS,
    DeliveryStage,
    StageObservation,
)

TABLE: Final = "mission_control.coordinator_delivery_observation"
RELEASE_CANDIDATE: Final = "scripts/release_180/0063_coordinator_delivery_observations.sql"
_NOTIFICATION_COLUMNS: Final = """
    n.notification_id, n.inbox_seq, n.state, n.suppressed_reason, n.body, n.sealed_at,
    n.acknowledged_at, n.prompt_request_id, n.prompt_state, n.prompt_request, n.prompt_detail,
    n.acknowledged_by_actor_ref
"""
_OBSERVATION_COLUMNS: Final = (
    "notification_id, stage, channel, observer, result, observation_key, notice_digest, "
    "observed_at, received_at, created_by_actor_ref, evidence, delivery_nonce_digest, "
    "transport_key"
)


def _observation(row: asyncpg.Record) -> StageObservation:
    return StageObservation(
        stage=DeliveryStage(row["stage"]),
        channel=row["channel"],
        observer=row["observer"],
        result=row["result"],
        received_at=row["received_at"],
        observed_at=row["observed_at"] if row["observer"] == "host" else None,
        actor_ref=row["created_by_actor_ref"],
        observation_key=row["observation_key"],
        evidence=dict(mc.load(row["evidence"]) or {}),
        nonce_digest=row["delivery_nonce_digest"],
        transport_key=row["transport_key"],
    )


class PostgresAttentionStore:
    def __init__(self, pool: asyncpg.Pool, request_scope: str) -> None:
        parse_request_scope(request_scope)
        self._pool = pool
        self._scope = request_scope
        self._installed: bool | None = None

    @property
    def request_scope(self) -> str:
        return self._scope

    async def installed(self) -> bool:
        if self._installed is None:
            async with self._pool.acquire() as connection:
                self._installed = bool(
                    await connection.fetchval(f"SELECT to_regclass('{TABLE}') IS NOT NULL")
                )
        return self._installed

    async def record(self, observation: NewObservation) -> StoredObservation:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, self._scope)
            await apply_actor(connection, observation.actor_ref)
            row = await connection.fetchrow(
                f"""
                INSERT INTO {TABLE} (
                    installation_id, application_id, tenant_id, subscription_id,
                    notification_id, stage, observation_key, channel, observer, result,
                    notice_digest, attempt, evidence, observed_at, created_at,
                    created_by_actor_ref, received_at, delivery_nonce_digest, transport_key
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14,
                          clock_timestamp(), $15, $16, $17, $18)
                ON CONFLICT (installation_id, application_id, tenant_id, notification_id, stage,
                             observation_key) DO NOTHING
                RETURNING {_OBSERVATION_COLUMNS}
                """,
                *args,
                observation.subscription_id,
                observation.notification_id,
                observation.stage.value,
                observation.observation_key,
                observation.channel,
                observation.observer,
                observation.result,
                observation.notice_digest,
                observation.attempt,
                mc.dump(dict(observation.evidence)),
                observation.observed_at,
                observation.actor_ref,
                observation.received_at,
                observation.nonce_digest,
                observation.transport_key,
            )
            created = row is not None
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT {_OBSERVATION_COLUMNS} FROM {TABLE} WHERE {mc.SCOPE} "
                    "AND notification_id = $4 AND stage = $5 AND observation_key = $6",
                    *args,
                    observation.notification_id,
                    observation.stage.value,
                    observation.observation_key,
                )
            assert row is not None
            return StoredObservation(_observation(row), row["notice_digest"], created)

    async def record_transport(
        self,
        subscription_id: UUID,
        notices: tuple[tuple[UUID, str, str], ...],
        *,
        channel: str,
        actor_ref: str,
        at: datetime,
    ) -> tuple[UUID, ...]:
        """`<channel>:<n>` keys, n = this channel's next count for the notification; at most
        :data:`MAX_TRANSPORT_OBSERVATIONS` per notification (a long-poll loop stays bounded)."""

        recorded: list[UUID] = []
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, self._scope)
            await apply_actor(connection, actor_ref)
            for notification_id, digest, nonce in notices:
                status = await connection.execute(
                    f"""
                    INSERT INTO {TABLE} (
                        installation_id, application_id, tenant_id, subscription_id,
                        notification_id, stage, observation_key, channel, observer, result,
                        notice_digest, evidence, observed_at, created_at, created_by_actor_ref,
                        received_at, delivery_nonce_digest
                    )
                    SELECT $1, $2, $3, $4, $5, 'transport', $6 || ':' || (count(*) + 1), $6,
                           'server', 'delivered', $7, '{{}}'::jsonb, $8, clock_timestamp(), $9,
                           $8, $11
                    FROM {TABLE}
                    WHERE {mc.SCOPE} AND notification_id = $5 AND stage = 'transport'
                      AND channel = $6
                    HAVING count(*) < $10
                    ON CONFLICT (installation_id, application_id, tenant_id, notification_id,
                                 stage, observation_key) DO NOTHING
                    """,
                    *args,
                    subscription_id,
                    notification_id,
                    channel,
                    digest,
                    at,
                    actor_ref,
                    MAX_TRANSPORT_OBSERVATIONS,
                    nonce,
                )
                if int(status.rsplit(" ", 1)[-1]):
                    recorded.append(notification_id)
        return tuple(recorded)

    async def observations(
        self, subscription_id: UUID, notification_ids: tuple[UUID, ...]
    ) -> Mapping[UUID, tuple[StageObservation, ...]]:
        if not notification_ids:
            return {}
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, self._scope)
            rows = await connection.fetch(
                f"SELECT {_OBSERVATION_COLUMNS} FROM {TABLE} WHERE {mc.SCOPE} "
                "AND subscription_id = $4 AND notification_id = ANY($5::uuid[]) "
                "ORDER BY received_at, observation_key",
                *args,
                subscription_id,
                list(notification_ids),
            )
        found: dict[UUID, list[StageObservation]] = {}
        for row in rows:
            found.setdefault(row["notification_id"], []).append(_observation(row))
        return {key: tuple(value) for key, value in found.items()}

    async def sealed(
        self, subscription_id: UUID, *, after_inbox_seq: int, limit: int
    ) -> tuple[SealedNotice, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, self._scope)
            rows = await connection.fetch(
                f"""
                SELECT {_NOTIFICATION_COLUMNS}
                FROM mission_control.coordinator_notification n
                WHERE {mc.scoped("n")} AND n.subscription_id = $4
                  AND n.state IN ('pending', 'acknowledged') AND n.inbox_seq > $5
                ORDER BY n.inbox_seq
                LIMIT $6
                """,
                *args,
                subscription_id,
                after_inbox_seq,
                limit,
            )
        return tuple(
            SealedNotice(
                PostgresCoordinatorInboxStore._notification(row), row["acknowledged_by_actor_ref"]
            )
            for row in rows
        )

    async def awaiting_transport(
        self, subscription_id: UUID, *, channel: str, limit: int
    ) -> tuple[CoordinatorNotification, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, self._scope)
            rows = await connection.fetch(
                f"""
                SELECT {_NOTIFICATION_COLUMNS}
                FROM mission_control.coordinator_notification n
                WHERE {mc.scoped("n")} AND n.subscription_id = $4 AND n.state = 'pending'
                  AND NOT EXISTS (
                      SELECT 1 FROM {TABLE} o
                      WHERE {mc.scoped("o")} AND o.notification_id = n.notification_id
                        AND o.stage = 'transport' AND o.channel = $5 AND o.result = 'delivered')
                ORDER BY n.inbox_seq
                LIMIT $6
                """,
                *args,
                subscription_id,
                channel,
                limit,
            )
        return tuple(PostgresCoordinatorInboxStore._notification(row) for row in rows)


__all__ = ["RELEASE_CANDIDATE", "TABLE", "PostgresAttentionStore"]

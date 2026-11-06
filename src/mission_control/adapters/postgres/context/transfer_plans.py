"""``TransferPlanStore`` over the 1.7.0 ``transfer_plan`` and attempt receipts (0057; ADR-0061).

``transfer_plan`` holds one immutable sealed plan per receiver key: a second seal with the same
digest returns the stored plan, another digest is :class:`TransferPlanConflict`. Receipts are
appended under the next per-plan ``sequence`` (a concurrent append retries on the unique key),
with one ``transfer_member_delivery`` row per member. Nothing is updated or deleted.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import asyncpg

from mission_control.adapters.postgres.knowledge.attention_events import (
    TRANSFER_DELIVERY_REFUSED,
    TRANSFER_DELIVERY_WAITING,
    emit_attention_event,
)
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.context.materialization import TransferPlanConflict
from mission_control.domain.context.transfer import DeliveryReceipt, SealedTransferPlan

_PLAN = "mission_control.transfer_plan"
_RECEIPT = "mission_control.transfer_delivery_receipt"
_MEMBER = "mission_control.transfer_member_delivery"
_ATTEMPTS = 5


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _load(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class PostgresTransferPlanStore:
    """RLS-scoped sealed plans and attempt receipts for one runtime-role pool."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        actor_ref: str = "mission-control:context-transfer",
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._pool = pool
        self._actor_ref = actor_ref
        self._clock = clock

    async def seal(self, plan: SealedTransferPlan) -> SealedTransferPlan:
        document = plan.model_dump(mode="json")
        resources = plan.resource_plan
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, plan.receiver.scope)
            await apply_actor(connection, self._actor_ref)
            at = self._clock()
            await connection.execute(
                f"INSERT INTO {_PLAN} (installation_id, application_id, tenant_id, "
                "transfer_plan_id, receiver_key, run_id, receiver_operation_ref, "
                "receiver_position, boundary, isolation, configuration_ref, "
                "selection_authority_ref, host_state_ref, profile_pin, plan, plan_digest, "
                "member_count, total_tokens, context_window_tokens, file_bytes, sealed_at, "
                "created_at, created_by_actor_ref) VALUES ($1, $2, $3, $4::uuid, $5, $6::uuid, "
                "$7, $8, $9, $10, $11, $12, $13, $14, $15::jsonb, $16, $17, $18, $19, $20, $21, "
                "$21, $22) ON CONFLICT DO NOTHING",
                *args,
                plan.plan_id,
                plan.receiver_key,
                plan.receiver.run_id,
                plan.receiver.operation_id,
                plan.receiver_position,
                plan.boundary.value,
                plan.isolation,
                plan.configuration_ref,
                plan.selection_authority_ref,
                plan.host_state_ref,
                plan.profile_pin,
                json.dumps(document, sort_keys=True),
                plan.digest,
                len(plan.exact_sources),
                resources.total_tokens,
                resources.bounds.window_tokens,
                resources.file_bytes,
                at,
                self._actor_ref,
            )
            row = await connection.fetchrow(
                f"SELECT plan, plan_digest FROM {_PLAN} WHERE {SCOPE} AND receiver_key = $4",
                *args,
                plan.receiver_key,
            )
        if row is None:  # pragma: no cover - the unique row is visible in this scope
            raise RuntimeError("sealed transfer plan is not visible")
        if row["plan_digest"] != plan.digest:
            raise TransferPlanConflict(f"receiver {plan.receiver_key} has another sealed plan")
        return SealedTransferPlan.model_validate(_load(row["plan"]))

    async def plan_for(self, scope: str, receiver_key: str) -> SealedTransferPlan | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            value = await connection.fetchval(
                f"SELECT plan FROM {_PLAN} WHERE {SCOPE} AND receiver_key = $4",
                *args,
                receiver_key,
            )
        return None if value is None else SealedTransferPlan.model_validate(_load(value))

    async def get(self, scope: str, plan_id: str) -> SealedTransferPlan | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            value = await connection.fetchval(
                f"SELECT plan FROM {_PLAN} WHERE {SCOPE} AND transfer_plan_id = $4::uuid",
                *args,
                plan_id,
            )
        return None if value is None else SealedTransferPlan.model_validate(_load(value))

    async def append_receipt(self, scope: str, receipt: DeliveryReceipt) -> DeliveryReceipt:
        for _attempt in range(_ATTEMPTS):
            try:
                return await self._append(scope, receipt)
            except asyncpg.UniqueViolationError:
                continue  # a concurrent append took the sequence: read the next one again
        raise RuntimeError(f"could not append a receipt to transfer plan {receipt.plan_id}")

    async def _append(self, scope: str, receipt: DeliveryReceipt) -> DeliveryReceipt:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, self._actor_ref)
            sequence = await connection.fetchval(
                f"SELECT COALESCE(max(sequence), 0) + 1 FROM {_RECEIPT} "
                f"WHERE {SCOPE} AND transfer_plan_id = $4::uuid",
                *args,
                receipt.plan_id,
            )
            plan_row = await connection.fetchrow(
                f"SELECT plan, run_id, receiver_position FROM {_PLAN} "
                f"WHERE {SCOPE} AND transfer_plan_id = $4::uuid",
                *args,
                receipt.plan_id,
            )
            plan = None if plan_row is None else plan_row["plan"]
            if plan is None:
                raise ValueError(f"no sealed transfer plan {receipt.plan_id} in this scope")
            sources = {
                item["member_key"]: item["source_ref"] for item in _load(plan)["exact_sources"]
            }
            stored = receipt.model_copy(update={"sequence": int(sequence)})
            at = self._clock()
            attempt = stored.receiver_attempt
            await connection.execute(
                f"INSERT INTO {_RECEIPT} (installation_id, application_id, tenant_id, "
                "delivery_receipt_id, transfer_plan_id, plan_digest, sequence, "
                "operation_attempt, execution_generation, receiver_invocation_ref, "
                "realized_backend, result, total_tokens, headroom_tokens, receipt, "
                "correlation_id, received_at, created_at, created_by_actor_ref) VALUES ($1, $2, "
                "$3, $4::uuid, $5::uuid, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15::jsonb, "
                # created_at is the transaction start: members are written with the receipt.
                "$16, $17, now(), $18)",
                *args,
                stored.receipt_id,
                stored.plan_id,
                stored.plan_digest,
                stored.sequence,
                attempt.operation_attempt,
                attempt.execution_generation,
                attempt.invocation_ref,
                stored.realized_backend,
                stored.result,
                stored.resource_usage.total_tokens,
                stored.resource_usage.headroom_tokens,
                json.dumps(stored.model_dump(mode="json"), sort_keys=True),
                stored.correlation_id,
                at,
                self._actor_ref,
            )
            await connection.executemany(
                f"INSERT INTO {_MEMBER} (installation_id, application_id, tenant_id, "
                "delivery_receipt_id, member_key, source_ref, placement, path_or_handle, "
                "required_digest, observed_digest, size_bytes, probe, readable, access_ok, "
                "access_ref, code, created_at) VALUES ($1, $2, $3, $4::uuid, $5, $6, $7, $8, $9, "
                "$10, $11, $12, $13, $14, $15, $16, $17)",
                [
                    (
                        *args,
                        stored.receipt_id,
                        item.member_key,
                        sources.get(item.member_key, item.member_key),
                        item.placement,
                        item.path_or_handle,
                        item.required_digest,
                        item.observed_digest,
                        item.size_bytes,
                        item.probe,
                        item.readable,
                        item.access_ok,
                        item.access_ref,
                        item.code,
                        at,
                    )
                    for item in stored.delivered
                ],
            )
            if stored.result != "ready":
                # WI-19: a refused or waiting input delivery is a default actionable notice.
                assert plan_row is not None
                await emit_attention_event(
                    connection,
                    args,
                    run_id=str(plan_row["run_id"]),
                    event_type=TRANSFER_DELIVERY_REFUSED
                    if stored.result == "refused"
                    else TRANSFER_DELIVERY_WAITING,
                    source_ref=stored.receipt_id,
                    payload={
                        "transfer_plan_id": stored.plan_id,
                        "receiver_position": plan_row["receiver_position"],
                        "result": stored.result,
                        "reason": ",".join(
                            sorted({item.code for item in stored.delivered if item.code})
                        )[:256]
                        or None,
                    },
                    actor_ref=self._actor_ref,
                )
        return stored

    async def receipts(self, scope: str, plan_id: str) -> tuple[DeliveryReceipt, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT receipt FROM {_RECEIPT} WHERE {SCOPE} AND transfer_plan_id = $4::uuid "
                "ORDER BY sequence",
                *args,
                plan_id,
            )
        return tuple(DeliveryReceipt.model_validate(_load(row["receipt"])) for row in rows)

    async def file_realizations(self, scope: str, source_refs: Sequence[str]) -> Mapping[str, str]:
        if not source_refs:
            return {}
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT DISTINCT ON (member.source_ref) member.source_ref, "
                "member.delivery_receipt_id::text AS receipt_id, member.path_or_handle "
                f"FROM {_MEMBER} member WHERE member.installation_id = $1 "
                "AND member.application_id = $2 AND member.tenant_id = $3 "
                "AND member.source_ref = ANY($4::text[]) AND member.placement = 'file' "
                "AND member.readable AND member.access_ok AND member.digest_verified "
                "ORDER BY member.source_ref, member.created_at",
                *args,
                list(source_refs),
            )
        return {
            row["source_ref"]: f"transfer-receipt:{row['receipt_id']}#{row['path_or_handle']}"
            for row in rows
        }


__all__ = ["PostgresTransferPlanStore"]

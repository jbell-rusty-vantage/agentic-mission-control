"""``ReactionStore`` and ``ReactionAuthorityPort`` over migration 0061 (WI-22; ADR-0004, ADR-0062).

- **attach/detach** move a ``reaction_binding`` to its next generation by compare-and-set (the
  table's guard refuses any other change); re-attaching the same armed descriptor is a no-op.
- **record_transition** is the explicit capture for a caller that owns the commit; the 0061
  triggers capture the five table-backed transitions inside their own transactions. Either way a
  transition is recorded only while its run has an armed binding of that kind, once per source.
- **admit_pending** takes one due transition per transaction (``FOR UPDATE SKIP LOCKED``), locks
  the run's armed bindings of that kind, reads each binding's ledger, plans with the pure
  :func:`~mission_control.domain.reactions.planning.plan_activation`, inserts the activation
  (unique per binding and transition) and, when admitted, its ``mc.reaction.dispatch`` outbox
  intent, then marks the transition admitted: admission and dispatch intent commit together.
  Admission is stamped and rate-limited by the database clock of that transaction. A
  transition whose cause names a ``reaction-`` operation with no activation of the run is
  refused ``CAUSE_UNKNOWN``. A transition captured before a binding was armed (or re-armed)
  is marked admitted with no activation for that binding: arming is a cutoff, not a replay.
- **lease/settle/retry** are the outbox relay: an activation moves forward (from ``admitted``) in
  the same transaction that acknowledges its intent, so a lost lease rolls both back.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.reactions.service import (
    DISPATCH_DESTINATION,
    AdmissionReport,
    DispatchIntent,
    DispatchOutcome,
)
from mission_control.contracts.identities import uuid7
from mission_control.domain.reactions.contracts import (
    DurableTransition,
    ReactionActivation,
    ReactionBinding,
    ReactionDescriptor,
    TransitionKind,
    causing_activation,
)
from mission_control.domain.reactions.planning import (
    ActivationLedger,
    CausalParent,
    RunAuthority,
    plan_activation,
)

_BINDING = "mission_control.reaction_binding"
_TRANSITION = "mission_control.reaction_transition"
_ACTIVATION = "mission_control.reaction_activation"
_BINDING_COLUMNS = (
    "binding_id::text AS binding_id, run_id::text AS run_id, reaction_id, generation, state, "
    "descriptor, armed_at, deadline_at, semantic_input_binding_ref, data_class"
)
_TRANSITION_COLUMNS = (
    "transition_id::text AS transition_id, run_id::text AS run_id, event_kind, event_version, "
    "source_ref, cause_ref, execution_generation, facts, captured_at"
)
_ACTIVATION_COLUMNS = (
    "activation_id::text AS activation_id, binding_id::text AS binding_id, binding_generation, "
    "run_id::text AS run_id, reaction_id, transition_id::text AS transition_id, event_kind, "
    "depth, root_activation_id::text AS root_activation_id, "
    "cause_activation_id::text AS cause_activation_id, run_generation, state, refusal_code, "
    "cancel_reason, reserved_tokens, admitted_at, workflow_id, dispatched_at"
)


class DispatchLeaseLost(RuntimeError):
    """Another relay re-leased the intent; this delivery's settlement is rolled back."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _load(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _binding(row: asyncpg.Record) -> ReactionBinding:
    return ReactionBinding(
        binding_id=row["binding_id"],
        run_id=row["run_id"],
        reaction_id=row["reaction_id"],
        generation=row["generation"],
        state=row["state"],
        descriptor=ReactionDescriptor.model_validate(_load(row["descriptor"])),
        armed_at=row["armed_at"],
        deadline_at=row["deadline_at"],
        semantic_input_binding_ref=row["semantic_input_binding_ref"],
        data_class=row["data_class"],
    )


def _transition(row: asyncpg.Record) -> DurableTransition:
    return DurableTransition(
        transition_id=row["transition_id"],
        kind=TransitionKind(row["event_kind"]),
        version=row["event_version"],
        source_ref=row["source_ref"],
        run_id=row["run_id"],
        cause_ref=row["cause_ref"],
        execution_generation=row["execution_generation"],
        facts=_load(row["facts"]),
        captured_at=row["captured_at"],
    )


def _activation(row: asyncpg.Record) -> ReactionActivation:
    return ReactionActivation(
        activation_id=row["activation_id"],
        binding_id=row["binding_id"],
        binding_generation=row["binding_generation"],
        run_id=row["run_id"],
        reaction_id=row["reaction_id"],
        transition_id=row["transition_id"],
        event=TransitionKind(row["event_kind"]),
        depth=row["depth"],
        root_activation_id=row["root_activation_id"],
        cause_activation_id=row["cause_activation_id"],
        run_generation=row["run_generation"],
        state=row["state"],
        refusal_code=row["refusal_code"],
        cancel_reason=row["cancel_reason"],
        reserved_tokens=row["reserved_tokens"],
        admitted_at=row["admitted_at"],
        workflow_id=row["workflow_id"],
        dispatched_at=row["dispatched_at"],
    )


class PostgresReactionStore:
    """RLS-scoped reaction bindings, transitions, activations and dispatch intents."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        actor_ref: str = "mission-control:reactions",
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._pool = pool
        self._actor_ref = actor_ref
        self._clock = clock

    async def _begin(self, connection: asyncpg.Connection, scope: str) -> tuple[Any, ...]:
        args = await mc.begin(connection, scope)
        await apply_actor(connection, self._actor_ref)
        return args

    # ------------------------------------------------------------ bindings

    async def attach(self, scope: str, binding: ReactionBinding) -> ReactionBinding:
        descriptor = binding.descriptor
        document = json.dumps(descriptor.model_dump(mode="json"), sort_keys=True)
        lifetime = descriptor.limits.time.lifetime_seconds
        async with self._pool.acquire() as connection, connection.transaction():
            args = await self._begin(connection, scope)
            now = self._clock()
            # Arming time and lifetime are on the database clock, the clock that stamps every
            # captured transition (a host clock behind it would miss the first transitions).
            armed_at: datetime = await connection.fetchval("SELECT clock_timestamp()")
            deadline_at = None if lifetime is None else armed_at + timedelta(seconds=lifetime)
            inserted = await connection.fetchrow(
                f"INSERT INTO {_BINDING} (installation_id, application_id, tenant_id, binding_id, "
                "run_id, reaction_id, event_kind, event_version, generation, state, descriptor, "
                "descriptor_digest, semantic_input_binding_ref, armed_at, deadline_at, version, "
                "created_at, created_by_actor_ref, updated_at, data_class) VALUES ($1, $2, $3, "
                "$4::uuid, $5::uuid, $6, $7, $8, 1, 'armed', $9::jsonb, $10, $11, $12, $13, 1, "
                f"$14, $15, $14, $16) ON CONFLICT DO NOTHING RETURNING {_BINDING_COLUMNS}",
                *args,
                binding.binding_id,
                binding.run_id,
                binding.reaction_id,
                descriptor.event.value,
                descriptor.version,
                document,
                binding.descriptor_digest,
                binding.semantic_input_binding_ref,
                armed_at,
                deadline_at,
                now,
                self._actor_ref,
                binding.data_class,
            )
            if inserted is not None:
                return _binding(inserted)
            current = await connection.fetchrow(
                f"SELECT {_BINDING_COLUMNS}, descriptor_digest FROM {_BINDING} WHERE {SCOPE} "
                "AND run_id = $4::uuid AND reaction_id = $5 FOR UPDATE",
                *args,
                binding.run_id,
                binding.reaction_id,
            )
            if current is None:  # pragma: no cover - the conflicting row is in this scope
                raise RuntimeError("reaction binding is not visible")
            if (
                current["state"] == "armed"
                and current["descriptor_digest"] == binding.descriptor_digest
                and current["data_class"] == binding.data_class
            ):
                return _binding(current)
            moved = await connection.fetchrow(
                f"UPDATE {_BINDING} SET event_kind = $5, event_version = $6, "
                "generation = generation + 1, state = 'armed', descriptor = $7::jsonb, "
                "descriptor_digest = $8, semantic_input_binding_ref = $9, armed_at = $10, "
                "deadline_at = $11, version = version + 1, updated_at = $12, data_class = $13 "
                f"WHERE {SCOPE} AND binding_id = $4::uuid RETURNING {_BINDING_COLUMNS}",
                *args,
                current["binding_id"],
                descriptor.event.value,
                descriptor.version,
                document,
                binding.descriptor_digest,
                binding.semantic_input_binding_ref,
                armed_at,
                deadline_at,
                now,
                binding.data_class,
            )
        assert moved is not None
        return _binding(moved)

    async def detach(self, scope: str, binding_id: str, *, at: datetime) -> ReactionBinding | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await self._begin(connection, scope)
            row = await connection.fetchrow(
                f"UPDATE {_BINDING} SET state = 'detached', generation = generation + 1, "
                "version = version + 1, updated_at = $5 "
                f"WHERE {SCOPE} AND binding_id = $4::uuid AND state = 'armed' "
                f"RETURNING {_BINDING_COLUMNS}",
                *args,
                binding_id,
                at,
            )
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT {_BINDING_COLUMNS} FROM {_BINDING} WHERE {SCOPE} "
                    "AND binding_id = $4::uuid",
                    *args,
                    binding_id,
                )
        return None if row is None else _binding(row)

    async def binding(self, scope: str, binding_id: str) -> ReactionBinding | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT {_BINDING_COLUMNS} FROM {_BINDING} WHERE {SCOPE} "
                "AND binding_id = $4::uuid",
                *args,
                binding_id,
            )
        return None if row is None else _binding(row)

    # ------------------------------------------------------------ transitions

    async def record_transition(self, scope: str, transition: DurableTransition) -> bool:
        """Stamped with the database clock, as the capture triggers stamp theirs."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await self._begin(connection, scope)
            row = await connection.fetchrow(
                f"INSERT INTO {_TRANSITION} (installation_id, application_id, tenant_id, "
                "transition_id, run_id, event_kind, event_version, source_ref, cause_ref, "
                "execution_generation, facts, captured_at, admitted_at, created_by_actor_ref) "
                "SELECT $1, $2, $3, $4::uuid, $5::uuid, $6, $7, $8, $9, $10, $11::jsonb, "
                "clock_timestamp(), NULL, $12 WHERE EXISTS (SELECT 1 FROM "
                "mission_control.reaction_binding AS b "
                "WHERE b.installation_id = $1 AND b.application_id = $2 AND b.tenant_id = $3 "
                "AND b.run_id = $5::uuid AND b.event_kind = $6 AND b.state = 'armed') "
                "ON CONFLICT DO NOTHING RETURNING transition_id",
                *args,
                transition.transition_id,
                transition.run_id,
                transition.kind.value,
                transition.version,
                transition.source_ref,
                transition.cause_ref,
                transition.execution_generation,
                json.dumps(transition.facts, sort_keys=True),
                self._actor_ref,
            )
        return row is not None

    async def transition(self, scope: str, transition_id: str) -> DurableTransition | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT {_TRANSITION_COLUMNS} FROM {_TRANSITION} WHERE {SCOPE} "
                "AND transition_id = $4::uuid",
                *args,
                transition_id,
            )
        return None if row is None else _transition(row)

    async def transitions(self, scope: str, run_id: str) -> tuple[DurableTransition, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT {_TRANSITION_COLUMNS} FROM {_TRANSITION} WHERE {SCOPE} "
                "AND run_id = $4::uuid ORDER BY captured_at, transition_id",
                *args,
                run_id,
            )
        return tuple(_transition(row) for row in rows)

    # ------------------------------------------------------------ admission

    async def admit_pending(self, scope: str, *, now: datetime, limit: int) -> AdmissionReport:
        del now  # admission is stamped by the database clock (never before the capture)
        admitted: list[ReactionActivation] = []
        count = 0
        for _ in range(limit):
            async with self._pool.acquire() as connection, connection.transaction():
                args = await self._begin(connection, scope)
                row = await connection.fetchrow(
                    f"SELECT {_TRANSITION_COLUMNS} FROM {_TRANSITION} WHERE {SCOPE} "
                    "AND admitted_at IS NULL ORDER BY captured_at, transition_id LIMIT 1 "
                    "FOR UPDATE SKIP LOCKED",
                    *args,
                )
                if row is None:
                    break
                transition = _transition(row)
                at: datetime = await connection.fetchval("SELECT clock_timestamp()")
                admitted.extend(await self._admit(connection, args, transition, at))
                await connection.execute(
                    f"UPDATE {_TRANSITION} SET admitted_at = greatest(clock_timestamp(), "
                    f"captured_at) WHERE {SCOPE} AND transition_id = $4::uuid",
                    *args,
                    transition.transition_id,
                )
                count += 1
        return AdmissionReport(transitions=count, activations=tuple(admitted))

    async def _admit(
        self,
        connection: asyncpg.Connection,
        args: tuple[Any, ...],
        transition: DurableTransition,
        at: datetime,
    ) -> list[ReactionActivation]:
        bindings = await connection.fetch(
            f"SELECT {_BINDING_COLUMNS} FROM {_BINDING} WHERE {SCOPE} AND run_id = $4::uuid "
            "AND event_kind = $5 AND state = 'armed' ORDER BY binding_id FOR UPDATE",
            *args,
            transition.run_id,
            transition.kind.value,
        )
        if not bindings:
            return []
        run_generation = await connection.fetchval(
            f"SELECT execution_generation FROM mission_control.mission_run WHERE {SCOPE} "
            "AND run_key = $4",
            *args,
            transition.run_id,
        )
        parent: CausalParent | None = None
        cause = causing_activation(transition.cause_ref)
        if cause is not None:
            found = await connection.fetchrow(
                f"SELECT activation_id::text AS activation_id, "
                "root_activation_id::text AS root_activation_id, depth "
                f"FROM {_ACTIVATION} WHERE {SCOPE} AND activation_id = $4::uuid "
                "AND run_id = $5::uuid",
                *args,
                cause,
                transition.run_id,
            )
            if found is not None:
                parent = CausalParent(
                    activation_id=found["activation_id"],
                    root_activation_id=found["root_activation_id"],
                    depth=found["depth"],
                )
        cause_unknown = cause is not None and parent is None
        planned: list[ReactionActivation] = []
        for record in bindings:
            binding = _binding(record)
            ledger_rows = await connection.fetch(
                f"SELECT admitted_at, state, reserved_tokens FROM {_ACTIVATION} WHERE {SCOPE} "
                "AND binding_id = $4::uuid AND state <> 'refused' ORDER BY admitted_at",
                *args,
                binding.binding_id,
            )
            ledger = ActivationLedger(
                admitted_at=tuple(item["admitted_at"] for item in ledger_rows),
                reserved_tokens=sum(
                    int(item["reserved_tokens"])
                    for item in ledger_rows
                    if item["state"] in {"admitted", "dispatched"}
                ),
            )
            activation = plan_activation(
                binding,
                transition,
                ledger,
                parent=parent,
                run_generation=None if run_generation is None else int(run_generation),
                now=at,
                cause_unknown=cause_unknown,
            )
            if activation is None:
                continue
            stored = await self._insert_activation(connection, args, activation)
            if stored is not None:
                planned.append(stored)
        return planned

    async def _insert_activation(
        self, connection: asyncpg.Connection, args: tuple[Any, ...], activation: ReactionActivation
    ) -> ReactionActivation | None:
        now = self._clock()
        row = await connection.fetchrow(
            f"INSERT INTO {_ACTIVATION} (installation_id, application_id, tenant_id, "
            "activation_id, binding_id, binding_generation, run_id, reaction_id, transition_id, "
            "event_kind, depth, root_activation_id, cause_activation_id, run_generation, state, "
            "refusal_code, cancel_reason, reserved_tokens, operation_ref, workflow_id, "
            "admitted_at, dispatched_at, cancelled_at, version, created_at, "
            "created_by_actor_ref, updated_at) VALUES ($1, $2, $3, $4::uuid, $5::uuid, $6, "
            "$7::uuid, $8, $9::uuid, $10, $11, $12::uuid, $13::uuid, $14, $15, $16, NULL, $17, "
            "$18, NULL, $19, NULL, NULL, 1, $20, $21, $20) ON CONFLICT DO NOTHING "
            f"RETURNING {_ACTIVATION_COLUMNS}",
            *args,
            activation.activation_id,
            activation.binding_id,
            activation.binding_generation,
            activation.run_id,
            activation.reaction_id,
            activation.transition_id,
            activation.event.value,
            activation.depth,
            activation.root_activation_id,
            activation.cause_activation_id,
            activation.run_generation,
            activation.state,
            activation.refusal_code,
            activation.reserved_tokens,
            activation.operation_id,
            activation.admitted_at,
            now,
            self._actor_ref,
        )
        if row is None:  # the same (binding, transition) was admitted before: one reaction
            return None
        if activation.state == "admitted":
            payload = {
                "schema_version": "mc.reaction_dispatch.v1",
                "activation_id": activation.activation_id,
                "run_id": activation.run_id,
                "binding_id": activation.binding_id,
                "transition_id": activation.transition_id,
            }
            await connection.execute(
                "INSERT INTO mission_control.outbox (installation_id, application_id, tenant_id, "
                "outbox_id, ledger_commit_id, event_id, delivery_key, destination_kind, "
                "event_type, aggregate_key, aggregate_version, aggregate_sequence, payload, "
                "payload_ref, delivery_state, attempts, next_attempt_at, version, created_at, "
                "created_by_actor_ref) VALUES ($1, $2, $3, $4, NULL, NULL, $5, $6, "
                "'reaction.admitted', NULL, NULL, NULL, $7::jsonb, NULL, 'pending', 0, $8, 1, "
                "$8, $9) ON CONFLICT DO NOTHING",
                *args,
                uuid7(),
                f"reaction.dispatch:{activation.activation_id}",
                DISPATCH_DESTINATION,
                json.dumps(payload, sort_keys=True),
                now,
                self._actor_ref,
            )
        return _activation(row)

    async def activation(self, scope: str, activation_id: str) -> ReactionActivation | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT {_ACTIVATION_COLUMNS} FROM {_ACTIVATION} WHERE {SCOPE} "
                "AND activation_id = $4::uuid",
                *args,
                activation_id,
            )
        return None if row is None else _activation(row)

    async def activations(self, scope: str, run_id: str) -> tuple[ReactionActivation, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT {_ACTIVATION_COLUMNS} FROM {_ACTIVATION} WHERE {SCOPE} "
                "AND run_id = $4::uuid ORDER BY admitted_at, activation_id",
                *args,
                run_id,
            )
        return tuple(_activation(row) for row in rows)

    # ------------------------------------------------------------ dispatch relay

    async def lease_dispatches(
        self,
        scope: str,
        *,
        lease_owner: str,
        lease_until: datetime,
        now: datetime,
        limit: int,
    ) -> tuple[DispatchIntent, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"""
                WITH due AS (
                    SELECT outbox_id FROM mission_control.outbox
                    WHERE {SCOPE} AND destination_kind = $8
                      AND (delivery_state = 'pending'
                           OR (delivery_state = 'leased' AND lease_expires_at <= $6))
                      -- Due by the relay's clock or the database clock that stamped the
                      -- admission (a relay clock slightly behind never hides a new intent).
                      AND next_attempt_at <= greatest($6, clock_timestamp())
                    ORDER BY global_position
                    LIMIT $7
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE mission_control.outbox AS box
                SET delivery_state = 'leased', lease_owner = $4, lease_expires_at = $5,
                    version = box.version + 1
                FROM due
                WHERE {mc.scoped("box")} AND box.outbox_id = due.outbox_id
                RETURNING box.global_position, box.delivery_key, box.payload, box.attempts
                """,
                *args,
                lease_owner,
                lease_until,
                now,
                limit,
                DISPATCH_DESTINATION,
            )
        intents = []
        for row in sorted(rows, key=lambda item: item["global_position"]):
            payload = _load(row["payload"])
            intents.append(
                DispatchIntent(
                    delivery_key=row["delivery_key"],
                    activation_id=payload["activation_id"],
                    run_id=payload["run_id"],
                    attempts=int(row["attempts"]),
                )
            )
        return tuple(intents)

    async def settle_dispatch(
        self,
        scope: str,
        intent: DispatchIntent,
        *,
        lease_owner: str,
        outcome: DispatchOutcome,
        at: datetime,
    ) -> ReactionActivation:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await self._begin(connection, scope)
            current = await connection.fetchrow(
                f"SELECT state FROM {_ACTIVATION} WHERE {SCOPE} AND activation_id = $4::uuid "
                "FOR UPDATE",
                *args,
                intent.activation_id,
            )
            if current is None:
                raise LookupError(f"reaction activation {intent.activation_id} is not visible")
            if current["state"] == "admitted":
                if outcome.kind == "dispatched":
                    await connection.execute(
                        f"UPDATE {_ACTIVATION} SET state = 'dispatched', workflow_id = $5, "
                        "dispatched_at = $6, version = version + 1, updated_at = $6 "
                        f"WHERE {SCOPE} AND activation_id = $4::uuid",
                        *args,
                        intent.activation_id,
                        outcome.workflow_id,
                        at,
                    )
                else:
                    await connection.execute(
                        f"UPDATE {_ACTIVATION} SET state = 'cancelled', cancel_reason = $5, "
                        "cancelled_at = $6, version = version + 1, updated_at = $6 "
                        f"WHERE {SCOPE} AND activation_id = $4::uuid",
                        *args,
                        intent.activation_id,
                        outcome.reason,
                        at,
                    )
            acknowledged = await connection.execute(
                "UPDATE mission_control.outbox SET attempts = attempts + 1, delivered_at = $6, "
                "delivery_state = 'delivered', lease_owner = NULL, lease_expires_at = NULL, "
                f"version = version + 1 WHERE {SCOPE} AND delivery_key = $4 "
                "AND lease_owner = $5 AND delivery_state = 'leased'",
                *args,
                intent.delivery_key,
                lease_owner,
                at,
            )
            if acknowledged != "UPDATE 1":
                raise DispatchLeaseLost(f"reaction dispatch lease lost: {intent.delivery_key}")
            row = await connection.fetchrow(
                f"SELECT {_ACTIVATION_COLUMNS} FROM {_ACTIVATION} WHERE {SCOPE} "
                "AND activation_id = $4::uuid",
                *args,
                intent.activation_id,
            )
        assert row is not None
        return _activation(row)

    async def retry_dispatch(
        self,
        scope: str,
        intent: DispatchIntent,
        *,
        lease_owner: str,
        retry_at: datetime,
        dead: bool,
    ) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await connection.execute(
                "UPDATE mission_control.outbox SET attempts = attempts + 1, "
                "next_attempt_at = $6, delivery_state = CASE WHEN $7 THEN 'dead' ELSE "
                "'pending' END, lease_owner = NULL, lease_expires_at = NULL, "
                f"version = version + 1 WHERE {SCOPE} AND delivery_key = $4 "
                "AND lease_owner = $5",
                *args,
                intent.delivery_key,
                lease_owner,
                retry_at,
                dead,
            )


class PostgresReactionAuthority:
    """``ReactionAuthorityPort``: the run's execution generation, lifecycle and stop fence.

    A reaction's run id is the public run identity (``mission_run.run_key``), the one the
    output, transfer and settlement tables and every operation identity carry."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def current(self, scope: str, run_id: str) -> RunAuthority:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                "SELECT run.execution_generation, run.lifecycle, EXISTS ("
                "SELECT 1 FROM mission_control.stop_fence AS fence "
                f"WHERE {mc.scoped('fence')} AND fence.run_id = run.run_id "
                "AND fence.generation >= run.execution_generation) AS fenced "
                f"FROM mission_control.mission_run AS run WHERE {mc.scoped('run')} "
                "AND run.run_key = $4",
                *args,
                run_id,
            )
        if row is None:
            return RunAuthority(execution_generation=None)
        return RunAuthority(
            execution_generation=int(row["execution_generation"]),
            fenced=bool(row["fenced"]),
            terminal=row["lifecycle"] == "completed",
        )


__all__ = ["DispatchLeaseLost", "PostgresReactionAuthority", "PostgresReactionStore"]

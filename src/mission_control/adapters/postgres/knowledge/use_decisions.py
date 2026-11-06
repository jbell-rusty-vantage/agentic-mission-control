"""Recorded exact use decisions (release 1.7.0, migration 0059; Sprint OC WI-03).

``PostgresUseDecisionStore`` replaces the process-memory decision store ``knowledge_apply``
resolved: immutable rows the trusted knowledge bridge records, one per handle
(``mission_control.knowledge_use_decision``). The agent names only the handle; current
eligibility is re-checked through Knowledge Services before use. Every statement runs in an
explicit transaction under transaction-local tenant scope.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.adapters.postgres.scope import apply_actor
from mission_control.application.ports.knowledge import RecordedUseDecision

_DECISIONS = "mission_control.knowledge_use_decision"
_LOG = logging.getLogger(__name__)


def _json(value: Mapping[str, Any] | None) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"))


def _decision(row: asyncpg.Record) -> RecordedUseDecision:
    return RecordedUseDecision(
        handle=row["handle"],
        binding_id=row["binding_id"],
        tenant_id=str(row["tenant_id"]),
        use_decision_id=row["use_decision_id"],
        bound_effect_digest=row["bound_effect_digest"],
        processed_epoch=int(row["processed_epoch"]),
        plan=mc.load(row["plan"]),
        normalized_values_digest=row["normalized_values_digest"],
        proposals_ref=row["proposals_ref"],
        use=row["use_name"],
        audience=row["audience"],
        # 0072 columns (absent on a release before 2.0.0: NULL).
        subject_ref=row.get("subject_ref"),
        invocation_ref=row.get("invocation_ref"),
        decision_digest=row.get("decision_digest"),
    )


class PostgresUseDecisionStore:
    """Recorded exact use decisions by handle (immutable; one row per handle)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(
        self, scope: str, decision: RecordedUseDecision, *, actor_ref: str, at: datetime
    ) -> RecordedUseDecision:
        decision_ref = {"kind": "use_decision", "id": decision.use_decision_id}
        # The 0072 columns are written only for a plan-level native decision (so a store on a
        # release before 2.0.0 keeps recording the decisions it always could).
        native = decision.subject_ref is not None or decision.invocation_ref is not None
        columns = ", subject_ref, invocation_ref, decision_digest" if native else ""
        values = ", $17, $18, $19" if native else ""
        extra = (
            (decision.subject_ref, decision.invocation_ref, decision.decision_digest)
            if native
            else ()
        )
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            await apply_actor(connection, actor_ref)
            row = await connection.fetchrow(
                f"INSERT INTO {_DECISIONS} (installation_id, application_id, tenant_id, handle, "
                "binding_id, use_decision_id, decision_ref, bound_effect_digest, "
                "processed_epoch, plan, normalized_values_digest, proposals_ref, use_name, "
                f"audience, recorded_at, created_by_actor_ref{columns}) VALUES ($1, $2, $3, $4, "
                "$5, $6, $7::jsonb, $8, $9, $10::jsonb, $11, $12, $13, $14, $15, "
                f"$16{values}) ON CONFLICT DO NOTHING RETURNING *",
                *args,
                decision.handle,
                decision.binding_id,
                decision.use_decision_id,
                _json(decision_ref),
                decision.bound_effect_digest,
                decision.processed_epoch,
                _json(dict(decision.plan)),
                decision.normalized_values_digest,
                decision.proposals_ref,
                decision.use,
                decision.audience,
                at,
                actor_ref,
                *extra,
            )
            if row is None:
                row = await connection.fetchrow(
                    f"SELECT * FROM {_DECISIONS} WHERE {SCOPE} AND handle = $4",
                    *args,
                    decision.handle,
                )
        if row is None:  # pragma: no cover
            raise RuntimeError(f"use decision {decision.handle} is not visible")
        stored = _decision(row)
        if stored != decision:
            raise ValueError(f"decision handle {decision.handle!r} already names another decision")
        return stored

    async def get(self, scope: str, handle: str) -> RecordedUseDecision | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT * FROM {_DECISIONS} WHERE {SCOPE} AND handle = $4", *args, handle
            )
        return None if row is None else _decision(row)

    async def for_invocation(
        self, scope: str, invocation_ref: str
    ) -> tuple[RecordedUseDecision, ...]:
        """The plan-level decisions of exactly this invocation (needs 0072)."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"SELECT * FROM {_DECISIONS} WHERE {SCOPE} AND invocation_ref = $4 ORDER BY handle",
                *args,
                invocation_ref,
            )
        return tuple(_decision(row) for row in rows)


def member_binding(ref: str, digest: str) -> dict[str, Any]:
    """The plan a recorded decision carries when it decides one exact collection member (WI-07):
    the trusted bridge records ``{"kind": "collection_member", "member": {"ref", "digest"}}``."""

    return {"kind": "collection_member", "member": {"ref": ref, "digest": digest}}


class PostgresMemberDecisions:
    """``MemberDecisionPort`` over the recorded trusted use decisions (0059; WI-07 review S2).

    A cited decision counts for an exact member only when a row with that ``use_decision_id``
    exists, was recorded by the trusted bridge actor, and its plan binds exactly that member's
    ref and digest. Rows are immutable; revocation is the bridge's superseding assessment, after
    which the revoked citation is no longer standing (``domain.outputs.collections``). A read that
    fails answers nothing verified: the requirement waits (fail closed).
    """

    def __init__(self, pool: asyncpg.Pool, *, bridge_actor: str) -> None:
        self._pool = pool
        self._bridge_actor = bridge_actor

    async def standing_member_decisions(
        self, scope: str, cited: Sequence[tuple[str, str, str]]
    ) -> Mapping[tuple[str, str], frozenset[str]]:
        if not cited:
            return {}
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                args = await mc.begin(connection, scope)
                rows = await connection.fetch(
                    f"SELECT use_decision_id, plan FROM {_DECISIONS} WHERE {SCOPE} "
                    "AND use_decision_id = ANY($4::text[]) AND created_by_actor_ref = $5",
                    *args,
                    sorted({decision for _, _, decision in cited}),
                    self._bridge_actor,
                )
        except (asyncpg.PostgresError, OSError):
            _LOG.warning("recorded use decisions are unreadable; members wait", exc_info=True)
            return {}
        bound: dict[str, list[Any]] = {}
        for row in rows:
            bound.setdefault(row["use_decision_id"], []).append(mc.load(row["plan"]))
        verified: dict[tuple[str, str], set[str]] = {}
        for ref, digest, decision in cited:
            if member_binding(ref, digest) in bound.get(decision, ()):
                verified.setdefault((ref, digest), set()).add(decision)
        return {key: frozenset(value) for key, value in verified.items()}


__all__ = ["PostgresMemberDecisions", "PostgresUseDecisionStore", "member_binding"]

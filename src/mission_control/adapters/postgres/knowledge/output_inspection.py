"""Read-only ``OutputInspectionReader`` over the 1.7.0 output-contract and transfer tables (WI-19).

Every read runs in one transaction under the transaction-local tenant scope (forced RLS), so a
run of another tenant reads as absent. Nothing here writes: the views are the immutable rows of
0053/0056/0057 (promise revisions and heads, output revisions and accepted heads, sets,
assessments, fulfillment decisions, sealed plans and attempt receipts) projected as they are.
"""

from __future__ import annotations

import json
from typing import Any, Final

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.outputs.inspection import (
    AcceptedView,
    AssessmentView,
    Cursor,
    DecisionView,
    FindingView,
    FulfillmentView,
    ObligationView,
    OutputEvent,
    PlanSummary,
    ReceiptView,
    RevisionView,
)

_REVISION_COLUMNS: Final = """
    r.output_revision_id, r.obligation_key, r.obligation_revision, r.deliverable_id, r.revision,
    r.form, r.content_digest, r.producer_origin_ref, r.submission_id, r.submitted_at,
    s.operation_ref, s.operation_attempt, s.execution_generation
"""
_REVISION_FROM: Final = """
    FROM mission_control.output_revision r
    JOIN mission_control.output_submission s
      ON s.installation_id = r.installation_id AND s.application_id = r.application_id
     AND s.tenant_id = r.tenant_id AND s.submission_id = r.submission_id
"""
# Revisions of one promise in a stable total order (immutable rows): submission time, then
# deliverable, revision and id, so equal timestamps never reorder between pages.
_REVISION_SORT: Final = (
    "r.deliverable_id || '/' || lpad(r.revision::text, 10, '0') || '/' "
    "|| r.output_revision_id::text"
)
_PLAN_COLUMNS: Final = """
    p.transfer_plan_id, p.plan_digest, p.receiver_operation_ref, p.receiver_position, p.boundary,
    p.isolation, p.profile_pin, p.member_count, p.total_tokens, p.context_window_tokens,
    p.file_bytes, p.sealed_at
"""
_RECEIPT_COLUMNS: Final = """
    d.delivery_receipt_id, d.sequence, d.operation_attempt, d.execution_generation,
    d.receiver_invocation_ref, d.realized_backend, d.result, d.total_tokens, d.headroom_tokens,
    d.received_at
"""


def _load(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _finding_details(value: object, limit: int = 8) -> tuple[FindingView, ...]:
    """W1 D20: the first recorded findings (a KS refusal's code and issues), bounded."""

    rows = _load(value) or []
    return tuple(
        FindingView(
            code=str(item.get("code", ""))[:128],
            message=str(item.get("message", ""))[:500],
            pointer=None if item.get("pointer") is None else str(item["pointer"])[:200],
        )
        for item in rows[:limit]
        if isinstance(item, dict)
    )


def _revision(row: asyncpg.Record, *, accepted: bool = False) -> RevisionView:
    return RevisionView(
        revision_id=str(row["output_revision_id"]),
        obligation_key=row["obligation_key"],
        obligation_revision=row["obligation_revision"],
        deliverable_id=row["deliverable_id"],
        revision=row["revision"],
        form=row["form"],
        content_digest=row["content_digest"],
        producer_origin_ref=row["producer_origin_ref"],
        submission_id=str(row["submission_id"]),
        operation_ref=row["operation_ref"],
        operation_attempt=row["operation_attempt"],
        execution_generation=row["execution_generation"],
        submitted_at=row["submitted_at"],
        accepted=accepted,
    )


def _receipt(row: asyncpg.Record, prefix: str = "") -> ReceiptView:
    return ReceiptView(
        receipt_id=str(row[f"{prefix}delivery_receipt_id"]),
        sequence=row[f"{prefix}sequence"],
        operation_attempt=row[f"{prefix}operation_attempt"],
        execution_generation=row[f"{prefix}execution_generation"],
        receiver_invocation_ref=row[f"{prefix}receiver_invocation_ref"],
        realized_backend=row[f"{prefix}realized_backend"],
        result=row[f"{prefix}result"],
        total_tokens=row[f"{prefix}total_tokens"],
        headroom_tokens=row[f"{prefix}headroom_tokens"],
        received_at=row[f"{prefix}received_at"],
    )


def _plan(row: asyncpg.Record, receipts: int, latest: ReceiptView | None) -> PlanSummary:
    return PlanSummary(
        plan_id=str(row["transfer_plan_id"]),
        plan_digest=row["plan_digest"],
        receiver_operation_ref=row["receiver_operation_ref"],
        receiver_position=row["receiver_position"],
        boundary=row["boundary"],
        isolation=row["isolation"],
        profile_pin=row["profile_pin"],
        member_count=row["member_count"],
        total_tokens=row["total_tokens"],
        window_tokens=row["context_window_tokens"],
        file_bytes=row["file_bytes"],
        sealed_at=row["sealed_at"],
        receipts=receipts,
        latest_receipt=latest,
    )


class PostgresOutputInspectionReader:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def obligations(self, scope: str, run_id: str) -> tuple[ObligationView, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"""
                SELECT o.obligation_key, o.revision, o.owner_position, o.form, o.enforcement,
                       o.evaluation_scope, o.obligation_digest,
                       (SELECT max(later.revision)
                          FROM mission_control.output_obligation_revision later
                         WHERE {mc.scoped("later")} AND later.run_id = h.run_id
                           AND later.obligation_key = h.obligation_key
                           AND later.revision > h.active_revision) AS pending_revision
                FROM mission_control.output_obligation_head h
                JOIN mission_control.output_obligation_revision o
                  ON o.installation_id = h.installation_id
                 AND o.application_id = h.application_id AND o.tenant_id = h.tenant_id
                 AND o.run_id = h.run_id AND o.obligation_key = h.obligation_key
                 AND o.revision = h.active_revision
                WHERE {mc.scoped("h")} AND h.run_id = $4::uuid
                ORDER BY h.ordinal, h.obligation_key
                """,
                *args,
                run_id,
            )
        return tuple(
            ObligationView(
                obligation_key=row["obligation_key"],
                revision=row["revision"],
                owner_position=row["owner_position"],
                form=row["form"],
                enforcement=row["enforcement"],
                evaluation_scope=row["evaluation_scope"],
                obligation_digest=row["obligation_digest"],
                pending_revision=row["pending_revision"],
            )
            for row in rows
        )

    async def accepted(self, scope: str, run_id: str) -> tuple[AcceptedView, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"""
                SELECT {_REVISION_COLUMNS}, h.generation, h.promoted_at, h.promoted_by_actor_ref
                FROM mission_control.output_accepted_head h
                JOIN mission_control.output_revision r
                  ON r.installation_id = h.installation_id
                 AND r.application_id = h.application_id AND r.tenant_id = h.tenant_id
                 AND r.output_revision_id = h.output_revision_id
                JOIN mission_control.output_submission s
                  ON s.installation_id = r.installation_id AND s.application_id = r.application_id
                 AND s.tenant_id = r.tenant_id AND s.submission_id = r.submission_id
                WHERE {mc.scoped("h")} AND h.run_id = $4::uuid
                ORDER BY h.obligation_key, h.deliverable_id
                """,
                *args,
                run_id,
            )
        return tuple(
            AcceptedView(
                obligation_key=row["obligation_key"],
                deliverable_id=row["deliverable_id"],
                generation=row["generation"],
                promoted_at=row["promoted_at"],
                promoted_by=row["promoted_by_actor_ref"],
                revision=_revision(row, accepted=True),
            )
            for row in rows
        )

    async def revisions(
        self, scope: str, run_id: str, obligation_key: str, *, after: Cursor | None, limit: int
    ) -> tuple[RevisionView, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"""
                SELECT {_REVISION_COLUMNS},
                       EXISTS (SELECT 1 FROM mission_control.output_accepted_head h
                                WHERE {mc.scoped("h")}
                                  AND h.output_revision_id = r.output_revision_id) AS accepted
                {_REVISION_FROM}
                WHERE {mc.scoped("r")} AND r.run_id = $4::uuid AND r.obligation_key = $5
                  AND ($6::timestamptz IS NULL OR (r.submitted_at, {_REVISION_SORT}) > ($6, $7))
                ORDER BY r.submitted_at, {_REVISION_SORT}
                LIMIT $8
                """,
                *args,
                run_id,
                obligation_key,
                None if after is None else after[0],
                "" if after is None else after[1],
                limit,
            )
        return tuple(_revision(row, accepted=row["accepted"]) for row in rows)

    async def fulfillment(self, scope: str, run_id: str) -> FulfillmentView | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            pinned = await connection.fetchrow(
                f"""
                SELECT output_set_id, revision, membership_digest, created_at
                FROM mission_control.output_set
                WHERE {mc.SCOPE} AND run_id = $4::uuid
                ORDER BY revision DESC LIMIT 1
                """,
                *args,
                run_id,
            )
            if pinned is None:
                return None
            rows = await connection.fetch(
                f"""
                SELECT DISTINCT ON (obligation_key) obligation_key, obligation_revision,
                       enforcement, disposition, distinct_count, decision_digest, decision
                FROM mission_control.obligation_fulfillment
                WHERE {mc.SCOPE} AND output_set_id = $4
                ORDER BY obligation_key, created_at DESC, fulfillment_id
                """,
                *args,
                pinned["output_set_id"],
            )
        return FulfillmentView(
            output_set_id=str(pinned["output_set_id"]),
            set_revision=pinned["revision"],
            membership_digest=pinned["membership_digest"],
            pinned_at=pinned["created_at"],
            decisions=tuple(
                DecisionView(
                    obligation_key=row["obligation_key"],
                    obligation_revision=row["obligation_revision"],
                    enforcement=row["enforcement"],
                    disposition=row["disposition"],
                    distinct_count=row["distinct_count"],
                    decision_digest=row["decision_digest"],
                    decision=_load(row["decision"]),
                )
                for row in rows
            ),
        )

    async def assessments(self, scope: str, run_id: str) -> tuple[AssessmentView, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"""
                SELECT a.assessment_id, a.subject_kind, a.subject_ref, a.subject_digest, a.result,
                       a.method_pin, a.policy_pin, jsonb_array_length(a.findings) AS findings,
                       a.findings AS finding_rows,
                       a.supersedes, a.created_at,
                       EXISTS (SELECT 1 FROM mission_control.output_assessment later
                                WHERE {mc.scoped("later")}
                                  AND later.supersedes = a.assessment_id) AS superseded
                FROM mission_control.output_assessment a
                WHERE {mc.scoped("a")} AND a.run_id = $4::uuid
                ORDER BY a.recorded_seq
                """,
                *args,
                run_id,
            )
        return tuple(
            AssessmentView(
                assessment_id=str(row["assessment_id"]),
                subject_kind=row["subject_kind"],
                subject_ref=row["subject_ref"],
                subject_digest=row["subject_digest"],
                result=row["result"],
                method_pin=row["method_pin"],
                policy_pin=row["policy_pin"],
                findings=row["findings"],
                finding_details=_finding_details(row["finding_rows"]),
                supersedes=None if row["supersedes"] is None else str(row["supersedes"]),
                superseded=row["superseded"],
                recorded_at=row["created_at"],
            )
            for row in rows
        )

    async def plans(self, scope: str, run_id: str) -> tuple[PlanSummary, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"""
                SELECT {_PLAN_COLUMNS},
                       (SELECT count(*) FROM mission_control.transfer_delivery_receipt c
                         WHERE {mc.scoped("c")}
                           AND c.transfer_plan_id = p.transfer_plan_id) AS receipts,
                       latest.*
                FROM mission_control.transfer_plan p
                LEFT JOIN LATERAL (
                    SELECT d.delivery_receipt_id AS l_delivery_receipt_id,
                           d.sequence AS l_sequence, d.operation_attempt AS l_operation_attempt,
                           d.execution_generation AS l_execution_generation,
                           d.receiver_invocation_ref AS l_receiver_invocation_ref,
                           d.realized_backend AS l_realized_backend, d.result AS l_result,
                           d.total_tokens AS l_total_tokens,
                           d.headroom_tokens AS l_headroom_tokens,
                           d.received_at AS l_received_at
                    FROM mission_control.transfer_delivery_receipt d
                    WHERE {mc.scoped("d")} AND d.transfer_plan_id = p.transfer_plan_id
                    ORDER BY d.sequence DESC LIMIT 1
                ) latest ON true
                WHERE {mc.scoped("p")} AND p.run_id = $4::uuid
                ORDER BY p.sealed_at, p.transfer_plan_id
                """,
                *args,
                run_id,
            )
        return tuple(
            _plan(
                row,
                row["receipts"],
                _receipt(row, "l_") if row["l_delivery_receipt_id"] is not None else None,
            )
            for row in rows
        )

    async def plan(
        self, scope: str, plan_id: str
    ) -> tuple[PlanSummary, dict[str, Any], tuple[dict[str, Any], ...]] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            row = await connection.fetchrow(
                f"SELECT {_PLAN_COLUMNS}, p.plan FROM mission_control.transfer_plan p "
                f"WHERE {mc.scoped('p')} AND p.transfer_plan_id = $4::uuid",
                *args,
                plan_id,
            )
            if row is None:
                return None
            receipts = await connection.fetch(
                f"SELECT {_RECEIPT_COLUMNS}, d.receipt "
                "FROM mission_control.transfer_delivery_receipt d "
                f"WHERE {mc.scoped('d')} AND d.transfer_plan_id = $4::uuid ORDER BY d.sequence",
                *args,
                plan_id,
            )
        latest = _receipt(receipts[-1]) if receipts else None
        return (
            _plan(row, len(receipts), latest),
            _load(row["plan"]),
            tuple(_load(item["receipt"]) for item in receipts),
        )

    async def events(
        self, scope: str, run_id: str, *, after: Cursor | None, limit: int
    ) -> tuple[OutputEvent, ...]:
        """The run's output/transfer transitions, ordered by (time, kind/ref) behind a cursor."""

        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                f"""
                WITH events AS (
                    SELECT 'output.submitted' AS kind, r.submitted_at AS at,
                           r.output_revision_id::text AS ref, o.owner_position AS position,
                           r.obligation_key, s.operation_ref, s.operation_attempt,
                           s.execution_generation, r.content_digest AS digest,
                           NULL::text AS result,
                           jsonb_build_object('deliverable_id', r.deliverable_id,
                               'revision', r.revision, 'form', r.form) AS detail
                    {_REVISION_FROM}
                    JOIN mission_control.output_obligation_revision o
                      ON o.installation_id = r.installation_id
                     AND o.application_id = r.application_id AND o.tenant_id = r.tenant_id
                     AND o.run_id = r.run_id AND o.obligation_key = r.obligation_key
                     AND o.revision = r.obligation_revision
                    WHERE {mc.scoped("r")} AND r.run_id = $4::uuid
                    UNION ALL
                    SELECT 'assessment.recorded', a.created_at, a.assessment_id::text, NULL,
                           NULL, NULL, NULL, NULL, a.subject_digest, a.result,
                           jsonb_build_object('subject_kind', a.subject_kind,
                               'subject_ref', a.subject_ref, 'method_pin', a.method_pin)
                    FROM mission_control.output_assessment a
                    WHERE {mc.scoped("a")} AND a.run_id = $4::uuid
                    UNION ALL
                    SELECT 'fulfillment.decided', f.created_at, f.fulfillment_id::text,
                           o.owner_position, f.obligation_key, NULL, NULL, NULL,
                           f.decision_digest, f.disposition,
                           jsonb_build_object('output_set_id', f.output_set_id,
                               'enforcement', f.enforcement,
                               'distinct_count', f.distinct_count)
                    FROM mission_control.obligation_fulfillment f
                    JOIN mission_control.output_obligation_revision o
                      ON o.installation_id = f.installation_id
                     AND o.application_id = f.application_id AND o.tenant_id = f.tenant_id
                     AND o.run_id = f.run_id AND o.obligation_key = f.obligation_key
                     AND o.revision = f.obligation_revision
                    WHERE {mc.scoped("f")} AND f.run_id = $4::uuid
                    UNION ALL
                    SELECT 'delivery.recorded', d.received_at, d.delivery_receipt_id::text,
                           p.receiver_position, NULL, p.receiver_operation_ref,
                           d.operation_attempt, d.execution_generation, d.plan_digest, d.result,
                           jsonb_build_object('transfer_plan_id', d.transfer_plan_id,
                               'sequence', d.sequence, 'realized_backend', d.realized_backend,
                               'receiver_invocation_ref', d.receiver_invocation_ref)
                    FROM mission_control.transfer_delivery_receipt d
                    JOIN mission_control.transfer_plan p
                      ON p.installation_id = d.installation_id
                     AND p.application_id = d.application_id AND p.tenant_id = d.tenant_id
                     AND p.transfer_plan_id = d.transfer_plan_id
                    WHERE {mc.scoped("d")} AND p.run_id = $4::uuid
                )
                SELECT * FROM events
                WHERE $5::timestamptz IS NULL OR (at, kind || '/' || ref) > ($5, $6)
                ORDER BY at, kind || '/' || ref
                LIMIT $7
                """,
                *args,
                run_id,
                None if after is None else after[0],
                "" if after is None else after[1],
                limit,
            )
        return tuple(
            OutputEvent(
                kind=row["kind"],
                at=row["at"],
                ref=row["ref"],
                run_id=run_id,
                position=row["position"],
                obligation_key=row["obligation_key"],
                operation_ref=row["operation_ref"],
                operation_attempt=row["operation_attempt"],
                execution_generation=row["execution_generation"],
                digest=row["digest"],
                result=row["result"],
                detail=_load(row["detail"]) or {},
            )
            for row in rows
        )


__all__ = ["PostgresOutputInspectionReader"]

"""Builders, constants and fakes that other test files import.

Moved from tests/unit/subscriptions/test_wi19_interfaces.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from mission_control.application.outputs.inspection import (
    AcceptedView,
    AssessmentView,
    DecisionView,
    FulfillmentView,
    ObligationView,
    OutputEvent,
    PlanSummary,
    ReceiptView,
    RevisionView,
    revision_sort_key,
)

T = datetime(2026, 10, 28, 12, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def _revision(revision: int, *, accepted: bool) -> RevisionView:
    return RevisionView(
        revision_id=f"rev-{revision}",
        obligation_key="report.summary",
        obligation_revision=1,
        deliverable_id="summary",
        revision=revision,
        form="text",
        content_digest=DIGEST,
        producer_origin_ref="mission-invocation:p",
        submission_id=str(uuid4()),
        operation_ref="op-1",
        operation_attempt=1,
        execution_generation=1,
        submitted_at=T + timedelta(seconds=revision),
        accepted=accepted,
    )


class FakeReader:
    async def obligations(self, scope: str, run_id: str) -> tuple[ObligationView, ...]:
        return (
            ObligationView(
                obligation_key="report.summary",
                revision=1,
                owner_position="draft",
                form="text",
                enforcement="required",
                evaluation_scope="invocation",
                obligation_digest=DIGEST,
            ),
        )

    async def accepted(self, scope: str, run_id: str) -> tuple[AcceptedView, ...]:
        return (
            AcceptedView(
                obligation_key="report.summary",
                deliverable_id="summary",
                generation=1,
                promoted_at=T,
                promoted_by="host:test",
                revision=_revision(2, accepted=True),
            ),
        )

    async def revisions(self, scope, run_id, key, *, after, limit):  # type: ignore[no-untyped-def]
        rows = (_revision(1, accepted=False), _revision(2, accepted=True))
        if after is not None:
            rows = tuple(
                item for item in rows if (item.submitted_at, revision_sort_key(item)) > after
            )
        return rows[:limit]

    async def fulfillment(self, scope: str, run_id: str) -> FulfillmentView:
        return FulfillmentView(
            output_set_id="set-1",
            set_revision=1,
            membership_digest=DIGEST,
            pinned_at=T,
            decisions=(
                DecisionView(
                    obligation_key="report.summary",
                    obligation_revision=1,
                    enforcement="required",
                    disposition="unfulfilled",
                    distinct_count=1,
                    decision_digest=DIGEST,
                    decision={"unmet": [{"code": "REQUIREMENT_HELD"}]},
                ),
            ),
        )

    async def assessments(self, scope: str, run_id: str) -> tuple[AssessmentView, ...]:
        return (
            AssessmentView(
                assessment_id="a-1",
                subject_kind="output_revision",
                subject_ref="rev-2",
                subject_digest=DIGEST,
                result="review",
                method_pin="m",
                policy_pin="p",
                findings=1,
                recorded_at=T,
            ),
        )

    async def plans(self, scope: str, run_id: str) -> tuple[PlanSummary, ...]:
        return (_plan(),)

    async def plan(self, scope: str, plan_id: str):  # type: ignore[no-untyped-def]
        if plan_id != "00000000-0000-4000-8000-0000000000aa":
            return None
        return _plan(), {"schema_version": "mc.sealed_transfer_plan.v1"}, ({"sequence": 1},)

    async def events(self, scope, run_id, *, after, limit):  # type: ignore[no-untyped-def]
        rows = tuple(
            OutputEvent(
                kind="output.submitted",
                at=T + timedelta(seconds=i),
                ref=f"e-{i}",
                run_id=run_id,
                position="draft",
            )
            for i in range(3)
        )
        if after is not None:
            rows = tuple(item for item in rows if (item.at, f"{item.kind}/{item.ref}") > after)
        return rows[:limit]


def _plan() -> PlanSummary:
    return PlanSummary(
        plan_id="00000000-0000-4000-8000-0000000000aa",
        plan_digest=DIGEST,
        receiver_operation_ref="op-2",
        receiver_position="review",
        boundary="dependent_stage",
        isolation="shared",
        profile_pin="report-review@v1",
        member_count=2,
        total_tokens=100,
        window_tokens=1000,
        file_bytes=10,
        sealed_at=T,
        receipts=1,
        latest_receipt=ReceiptView(
            receipt_id="r-1",
            sequence=1,
            operation_attempt=1,
            execution_generation=1,
            receiver_invocation_ref="inv-2",
            realized_backend="state",
            result="refused",
            total_tokens=100,
            headroom_tokens=900,
            received_at=T,
        ),
    )

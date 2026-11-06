"""Exact output, fulfillment and transfer inspection (OUTPUT-CONTRACTS §3, §12; WI-19 / OVE-182).

Focused public reads over the immutable WI-01/WI-02 records, never a recomputation:

- ``outputs``: the run's active promises (with any pending successor), the accepted head of every
  deliverable as its exact revision, the decisions of the newest pinned output set, standing
  assessments and the *actionable* items a coordinator must attend (a required or expected
  promise unmet or blocked, a held or rejected assessment, an input delivery refused or
  waiting);
- ``revisions``: one promise's submitted history, oldest first, behind a stable cursor;
- ``events``: the attributable output/transfer transitions of the run (submitted, assessed,
  decided, delivered), each joinable by position, operation, attempt and exact record;
- ``transfer_plans`` / ``transfer_plan``: sealed plans of the run and one plan with every
  attempt receipt.

HTTP, ``missionctl`` and the operator MCP call these handlers; they share one permission
(``workflow_run.read``). Content bodies are not here: bounded content is the coordinator inbox's
explicit retrieval.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, Final, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from mission_control.domain.policies.contracts import ActorContext

READ_PERMISSION: Final = "workflow_run.read"
MAX_PAGE: Final = 200
EventKind = Literal[
    "output.submitted", "assessment.recorded", "fulfillment.decided", "delivery.recorded"
]


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObligationView(_View):
    obligation_key: str
    revision: int = Field(ge=1)
    owner_position: str
    form: str
    enforcement: str
    evaluation_scope: str
    obligation_digest: str
    pending_revision: int | None = None


class RevisionView(_View):
    revision_id: str
    obligation_key: str
    obligation_revision: int
    deliverable_id: str
    revision: int
    form: str
    content_digest: str
    producer_origin_ref: str
    submission_id: str
    operation_ref: str
    operation_attempt: int
    execution_generation: int
    submitted_at: AwareDatetime
    accepted: bool = False


class AcceptedView(_View):
    obligation_key: str
    deliverable_id: str
    generation: int
    promoted_at: AwareDatetime
    promoted_by: str
    revision: RevisionView


class DecisionView(_View):
    obligation_key: str
    obligation_revision: int
    enforcement: str
    disposition: str
    distinct_count: int
    decision_digest: str
    decision: dict[str, JsonValue]


class FulfillmentView(_View):
    output_set_id: str
    set_revision: int
    membership_digest: str
    pinned_at: AwareDatetime
    decisions: tuple[DecisionView, ...]


class FindingView(_View):
    code: str
    message: str
    pointer: str | None = None


class AssessmentView(_View):
    assessment_id: str
    subject_kind: str
    subject_ref: str
    subject_digest: str
    result: str
    method_pin: str
    policy_pin: str
    findings: int
    # W1 D20: the first findings themselves (a KS refusal's code and issues), not only a count.
    finding_details: tuple[FindingView, ...] = ()
    supersedes: str | None = None
    superseded: bool = False
    recorded_at: AwareDatetime


class ReceiptView(_View):
    receipt_id: str
    sequence: int
    operation_attempt: int
    execution_generation: int
    receiver_invocation_ref: str
    realized_backend: str
    result: str
    total_tokens: int
    headroom_tokens: int
    received_at: AwareDatetime


class PlanSummary(_View):
    plan_id: str
    plan_digest: str
    receiver_operation_ref: str
    receiver_position: str
    boundary: str
    isolation: str
    profile_pin: str
    member_count: int
    total_tokens: int
    window_tokens: int
    file_bytes: int
    sealed_at: AwareDatetime
    receipts: int = 0
    latest_receipt: ReceiptView | None = None


class ActionableItem(_View):
    code: str
    ref: str
    obligation_key: str | None = None
    position: str | None = None
    detail: str | None = None


class RunOutputs(_View):
    schema_version: Literal["mc.run_outputs.v1"] = "mc.run_outputs.v1"
    run_id: str
    obligations: tuple[ObligationView, ...]
    accepted: tuple[AcceptedView, ...]
    fulfillment: FulfillmentView | None
    assessments: tuple[AssessmentView, ...]
    transfer_plans: tuple[PlanSummary, ...]
    actionable: tuple[ActionableItem, ...]


class RevisionPage(_View):
    run_id: str
    obligation_key: str
    revisions: tuple[RevisionView, ...]
    next_cursor: str | None


class OutputEvent(_View):
    kind: EventKind
    at: AwareDatetime
    ref: str
    run_id: str
    position: str | None = None
    obligation_key: str | None = None
    operation_ref: str | None = None
    operation_attempt: int | None = None
    execution_generation: int | None = None
    digest: str | None = None
    result: str | None = None
    detail: dict[str, JsonValue] = Field(default_factory=dict)


class EventPage(_View):
    run_id: str
    events: tuple[OutputEvent, ...]
    next_cursor: str | None


class TransferPlanDetail(_View):
    schema_version: Literal["mc.transfer_inspection.v1"] = "mc.transfer_inspection.v1"
    summary: PlanSummary
    plan: dict[str, JsonValue]
    receipts: tuple[dict[str, JsonValue], ...]


class InspectionRejected(Exception):
    """Typed refusal: unauthorized, invalid, not_found."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


Cursor = tuple[datetime, str]


class OutputInspectionReader(Protocol):
    """Scoped reads of the immutable output and transfer records (adapters/postgres)."""

    async def obligations(self, scope: str, run_id: str) -> tuple[ObligationView, ...]: ...

    async def accepted(self, scope: str, run_id: str) -> tuple[AcceptedView, ...]: ...

    async def revisions(
        self, scope: str, run_id: str, obligation_key: str, *, after: Cursor | None, limit: int
    ) -> tuple[RevisionView, ...]: ...

    async def fulfillment(self, scope: str, run_id: str) -> FulfillmentView | None: ...

    async def assessments(self, scope: str, run_id: str) -> tuple[AssessmentView, ...]: ...

    async def plans(self, scope: str, run_id: str) -> tuple[PlanSummary, ...]: ...

    async def plan(
        self, scope: str, plan_id: str
    ) -> tuple[PlanSummary, dict[str, Any], tuple[dict[str, Any], ...]] | None: ...

    async def events(
        self, scope: str, run_id: str, *, after: Cursor | None, limit: int
    ) -> tuple[OutputEvent, ...]: ...


def encode_cursor(at: datetime, ref: str) -> str:
    raw = json.dumps([at.isoformat(), ref], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> Cursor | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, ref = json.loads(base64.urlsafe_b64decode(padded.encode()))
        moment = datetime.fromisoformat(at)
        if moment.tzinfo is None or not isinstance(ref, str):
            raise ValueError
        return moment, ref
    except (ValueError, TypeError, json.JSONDecodeError):
        raise InspectionRejected("invalid", "the cursor is not one this service issued") from None


def revision_sort_key(revision: RevisionView) -> str:
    """The stable order of one promise's revisions after their submission time."""

    return f"{revision.deliverable_id}/{revision.revision:010d}/{revision.revision_id}"


def _run(run_id: str) -> str:
    try:
        return str(UUID(run_id))
    except ValueError:
        raise InspectionRejected("invalid", "run_id is a run uuid") from None


def actionable_items(
    obligations: tuple[ObligationView, ...],
    fulfillment: FulfillmentView | None,
    assessments: tuple[AssessmentView, ...],
    plans: tuple[PlanSummary, ...],
) -> tuple[ActionableItem, ...]:
    """The default attention items (OUTPUT-CONTRACTS §12): unmet promises, held or rejected
    assessments and refused or waiting input deliveries. Optional absence is silent."""

    positions = {item.obligation_key: item.owner_position for item in obligations}
    items: list[ActionableItem] = []
    if fulfillment is not None:
        for decision in fulfillment.decisions:
            if decision.enforcement == "optional" or decision.disposition not in {
                "unfulfilled",
                "blocked",
            }:
                continue
            unmet = decision.decision.get("unmet")
            codes = (
                [str(entry.get("code")) for entry in unmet if isinstance(entry, dict)]
                if isinstance(unmet, list)
                else []
            )
            items.append(
                ActionableItem(
                    code="OBLIGATION_BLOCKED"
                    if decision.disposition == "blocked"
                    else "OBLIGATION_UNMET",
                    ref=f"{fulfillment.output_set_id}#{decision.obligation_key}",
                    obligation_key=decision.obligation_key,
                    position=positions.get(decision.obligation_key),
                    detail=",".join(codes)[:256] or decision.enforcement,
                )
            )
    for assessment in assessments:
        if assessment.superseded or assessment.result not in {"fail", "review"}:
            continue
        items.append(
            ActionableItem(
                code="ASSESSMENT_REJECTED" if assessment.result == "fail" else "ASSESSMENT_HELD",
                ref=assessment.assessment_id,
                detail=f"{assessment.subject_kind}:{assessment.subject_ref}",
            )
        )
    for plan in plans:
        latest = plan.latest_receipt
        if latest is None or latest.result == "ready":
            continue
        items.append(
            ActionableItem(
                code="INPUT_DELIVERY_REFUSED"
                if latest.result == "refused"
                else "INPUT_DELIVERY_WAITING",
                ref=latest.receipt_id,
                position=plan.receiver_position,
                detail=f"plan {plan.plan_id} attempt {latest.operation_attempt}",
            )
        )
    return tuple(items)


class OutputInspectionService:
    def __init__(self, reader: OutputInspectionReader, *, request_scope: str) -> None:
        self._reader = reader
        self.request_scope = request_scope

    @staticmethod
    def _require(actor: ActorContext) -> None:
        if READ_PERMISSION not in actor.permissions:
            raise InspectionRejected("unauthorized", f"actor lacks {READ_PERMISSION}")

    async def outputs(self, run_id: str, actor: ActorContext) -> RunOutputs:
        self._require(actor)
        run = _run(run_id)
        scope = self.request_scope
        obligations = await self._reader.obligations(scope, run)
        accepted = await self._reader.accepted(scope, run)
        fulfillment = await self._reader.fulfillment(scope, run)
        assessments = await self._reader.assessments(scope, run)
        plans = await self._reader.plans(scope, run)
        if not (obligations or accepted or plans):
            raise InspectionRejected("not_found", "no output promises or transfer plans")
        return RunOutputs(
            run_id=run,
            obligations=obligations,
            accepted=accepted,
            fulfillment=fulfillment,
            assessments=assessments,
            transfer_plans=plans,
            actionable=actionable_items(obligations, fulfillment, assessments, plans),
        )

    async def revisions(
        self,
        run_id: str,
        obligation_key: str,
        actor: ActorContext,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> RevisionPage:
        self._require(actor)
        if not 1 <= limit <= MAX_PAGE:
            raise InspectionRejected("invalid", f"limit is 1..{MAX_PAGE}")
        run = _run(run_id)
        rows = await self._reader.revisions(
            self.request_scope, run, obligation_key, after=decode_cursor(cursor), limit=limit + 1
        )
        page = rows[:limit]
        return RevisionPage(
            run_id=run,
            obligation_key=obligation_key,
            revisions=page,
            next_cursor=encode_cursor(page[-1].submitted_at, revision_sort_key(page[-1]))
            if len(rows) > limit
            else None,
        )

    async def events(
        self, run_id: str, actor: ActorContext, *, cursor: str | None = None, limit: int = 100
    ) -> EventPage:
        self._require(actor)
        if not 1 <= limit <= MAX_PAGE:
            raise InspectionRejected("invalid", f"limit is 1..{MAX_PAGE}")
        run = _run(run_id)
        rows = await self._reader.events(
            self.request_scope, run, after=decode_cursor(cursor), limit=limit + 1
        )
        page = rows[:limit]
        return EventPage(
            run_id=run,
            events=page,
            next_cursor=encode_cursor(page[-1].at, f"{page[-1].kind}/{page[-1].ref}")
            if len(rows) > limit
            else None,
        )

    async def transfer_plans(self, run_id: str, actor: ActorContext) -> tuple[PlanSummary, ...]:
        self._require(actor)
        return await self._reader.plans(self.request_scope, _run(run_id))

    async def transfer_plan(self, plan_id: str, actor: ActorContext) -> TransferPlanDetail:
        self._require(actor)
        try:
            plan = str(UUID(plan_id))
        except ValueError:
            raise InspectionRejected("invalid", "plan_id is a plan uuid") from None
        found = await self._reader.plan(self.request_scope, plan)
        if found is None:
            raise InspectionRejected("not_found", "no sealed transfer plan with that id")
        summary, document, receipts = found
        return TransferPlanDetail(summary=summary, plan=document, receipts=receipts)


__all__ = [
    "READ_PERMISSION",
    "AcceptedView",
    "ActionableItem",
    "AssessmentView",
    "DecisionView",
    "EventPage",
    "FindingView",
    "FulfillmentView",
    "InspectionRejected",
    "ObligationView",
    "OutputEvent",
    "OutputInspectionReader",
    "OutputInspectionService",
    "PlanSummary",
    "ReceiptView",
    "RevisionPage",
    "RevisionView",
    "RunOutputs",
    "TransferPlanDetail",
    "actionable_items",
    "decode_cursor",
    "encode_cursor",
    "revision_sort_key",
]

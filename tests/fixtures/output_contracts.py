"""In-memory ``OutputContractStore`` with the release 1.7.0 rules, for unit tests.

It shares the submission rows with :class:`InMemorySubmissionStore` (same scoped key, same
``SubmissionConflict`` / ``SubmissionClosed``) and mirrors the SQL guards: immutable revisions,
pins, assessments, sets and decisions; CAS obligation and accepted heads; pending successors
that activate only at their declared boundary; one row per association step. The PostgreSQL
proof is ``tests/integration/postgres/test_output_contracts_postgres.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from tests.fixtures.knowledge_binding import InMemorySubmissionStore

from mission_control.application.ports.knowledge import (
    SubmissionCandidate,
    SubmissionClosed,
    SubmissionConflict,
)
from mission_control.application.ports.outputs import (
    AcceptedHead,
    AssessmentSupersessionConflict,
    OlderRevision,
    PromisesConflict,
    RecordedSubmission,
    StaleGeneration,
    StaleHead,
    StaleObligationRevision,
    SubmissionAct,
)
from mission_control.domain.outputs.contracts import (
    Assessment,
    ExactOutput,
    Fulfillment,
    OutputForm,
    OutputObligation,
    OutputPromiseSet,
    OutputSet,
    SubmittedRevision,
    membership_digest,
)


@dataclass
class InMemoryOutputContractStore:
    submissions: InMemorySubmissionStore = field(default_factory=InMemorySubmissionStore)
    promise_sets: dict[tuple[str, str], OutputPromiseSet] = field(default_factory=dict)
    revisions: dict[tuple[str, str, str, int], OutputObligation] = field(default_factory=dict)
    pending_boundary: dict[tuple[str, str, str, int], str] = field(default_factory=dict)
    order: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    heads: dict[tuple[str, str, str], int] = field(default_factory=dict)
    pins: dict[tuple[str, str], dict[str, int]] = field(default_factory=dict)
    outputs: dict[tuple[str, str], ExactOutput] = field(default_factory=dict)
    by_submission: dict[tuple[str, str], tuple[SubmittedRevision, ...]] = field(
        default_factory=dict
    )
    submission_attempts: dict[str, tuple[int, int]] = field(default_factory=dict)
    accepted: dict[tuple[str, str, str, str], AcceptedHead] = field(default_factory=dict)
    sets: dict[tuple[str, str], OutputSet] = field(default_factory=dict)
    recorded_assessments: list[tuple[str, str, Assessment]] = field(default_factory=list)
    fulfillments: dict[tuple[str, str, str, str], Fulfillment] = field(default_factory=dict)
    steps: dict[tuple[str, str, str, str], Mapping[str, Any]] = field(default_factory=dict)

    async def register_promises(
        self,
        scope: str,
        run_id: str,
        promises: OutputPromiseSet,
        *,
        configuration_digest: str | None,
        actor_ref: str,
        at: datetime,
    ) -> tuple[OutputObligation, ...]:
        key = (scope, run_id)
        existing = self.promise_sets.get(key)
        if existing is not None:
            if existing.digest != promises.digest:
                raise PromisesConflict(f"run {run_id} registered other promises")
            return await self.active_obligations(scope, run_id)
        self.promise_sets[key] = promises
        self.order[key] = [item.key for item in promises.obligations]
        for item in promises.obligations:
            self.revisions[(scope, run_id, item.key, item.revision)] = item
            self.heads[(scope, run_id, item.key)] = item.revision
        return promises.obligations

    async def promise_set(self, scope: str, run_id: str) -> OutputPromiseSet | None:
        return self.promise_sets.get((scope, run_id))

    async def active_obligations(self, scope: str, run_id: str) -> tuple[OutputObligation, ...]:
        return tuple(
            self.revisions[(scope, run_id, key, self.heads[(scope, run_id, key)])]
            for key in self.order.get((scope, run_id), ())
        )

    async def obligation_revision(
        self, scope: str, run_id: str, obligation_key: str, revision: int
    ) -> OutputObligation | None:
        return self.revisions.get((scope, run_id, obligation_key, revision))

    async def pin_invocation(
        self, scope: str, run_id: str, invocation_ref: str, *, actor_ref: str, at: datetime
    ) -> Mapping[str, int]:
        pinned = self.pins.setdefault((scope, invocation_ref), {})
        for item in await self.active_obligations(scope, run_id):
            pinned.setdefault(item.key, item.revision)
        return dict(pinned)

    async def invocation_pins(self, scope: str, invocation_ref: str) -> Mapping[str, int]:
        return dict(self.pins.get((scope, invocation_ref), {}))

    async def propose_successor(
        self,
        scope: str,
        run_id: str,
        successor: OutputObligation,
        *,
        expected_prior_revision: int,
        proposal: Mapping[str, Any],
        boundary: str,
        actor_ref: str,
        at: datetime,
    ) -> OutputObligation:
        current = self.heads.get((scope, run_id, successor.key))
        key = (scope, run_id, successor.key, successor.revision)
        if current != expected_prior_revision or key in self.revisions:
            raise StaleObligationRevision("head moved or a successor is pending", current=current)
        self.revisions[key] = successor
        self.pending_boundary[key] = boundary
        return successor

    async def activate_pending(
        self,
        scope: str,
        run_id: str,
        *,
        boundary: str,
        boundary_ref: str,
        actor_ref: str,
        at: datetime,
    ) -> tuple[OutputObligation, ...]:
        activated: list[OutputObligation] = []
        for obligation_key in self.order.get((scope, run_id), ()):
            head = (scope, run_id, obligation_key)
            nxt = (scope, run_id, obligation_key, self.heads[head] + 1)
            if self.pending_boundary.get(nxt) == boundary:
                self.heads[head] += 1
                activated.append(self.revisions[nxt])
        return tuple(activated)

    async def record_submission(self, act: SubmissionAct) -> RecordedSubmission:
        for row in self.submissions.rows.values():
            if (
                self.submissions.scopes[row.submission_id] == act.scope
                and row.invocation_ref == act.invocation_ref
                and row.obligation_id == act.obligation_key
                and row.submission_key == act.submission_key
            ):  # an identical retry returns the stored receipt, even after finalization
                if row.selection_digest != act.selection_digest:
                    raise SubmissionConflict(act.submission_key)
                return RecordedSubmission(
                    row.submission_id, self.by_submission[(act.scope, row.submission_id)], True
                )
        if (act.scope, act.invocation_ref) in self.submissions.finalizations:
            raise SubmissionClosed(act.invocation_ref)
        expected = act.selection.get("submit", {}).get("expected_head")
        if expected is not None:
            for item in act.items:
                head = await self.accepted_head(
                    act.scope, act.run_id, act.obligation_key, item.deliverable_id
                )
                current = None if head is None else head.revision_id
                if current != expected:
                    raise StaleHead("accepted head changed", current=current)
        row = await self.submissions.record_selection(
            SubmissionCandidate(
                scope=act.scope,
                run_id=act.run_id,
                operation_ref=act.operation_ref,
                operation_attempt=act.operation_attempt,
                execution_generation=act.execution_generation,
                invocation_ref=act.invocation_ref,
                obligation_id=act.obligation_key,
                submission_key=act.submission_key,
                selection=dict(act.selection),
                selection_digest=act.selection_digest,
                actor_ref=act.actor_ref,
                at=act.at,
                unit_key=act.unit_key,
            )
        )
        revisions: list[SubmittedRevision] = []
        for item in act.items:
            number = 1 + sum(
                1
                for (scope, _), output in self.outputs.items()
                if scope == act.scope
                and output.run_id == act.run_id
                and output.obligation_key == act.obligation_key
                and output.deliverable_id == item.deliverable_id
            )
            output = ExactOutput(
                revision_id=str(uuid4()),
                run_id=act.run_id,
                obligation_key=act.obligation_key,
                obligation_revision=act.obligation_revision,
                deliverable_id=item.deliverable_id,
                revision=number,
                form=OutputForm(item.form),
                content_digest=item.content_digest,
                candidate=dict(item.candidate),
                producer_origin_ref=act.producer_origin_ref,
            )
            self.outputs[(act.scope, output.revision_id)] = output
            revisions.append(
                SubmittedRevision(
                    revision_id=output.revision_id,
                    deliverable_id=output.deliverable_id,
                    revision=output.revision,
                    content_digest=output.content_digest,
                )
            )
        self.submission_attempts[row.submission_id] = (
            act.operation_attempt,
            act.execution_generation,
        )
        self.by_submission[(act.scope, row.submission_id)] = tuple(revisions)
        return RecordedSubmission(row.submission_id, tuple(revisions))

    async def output_revision(self, scope: str, revision_id: str) -> ExactOutput | None:
        return self.outputs.get((scope, revision_id))

    async def submitted_outputs(
        self,
        scope: str,
        run_id: str,
        obligation_key: str,
        *,
        operation_ref: str,
        operation_attempt: int | None = None,
        execution_generation: int | None = None,
    ) -> tuple[ExactOutput, ...]:
        newest: dict[str, ExactOutput] = {}
        for (stored_scope, submission_id), revisions in self.by_submission.items():
            row = self.submissions.rows.get(submission_id)
            if stored_scope != scope or row is None:
                continue
            if self.submissions.meta.get(submission_id, ("", "", 0))[1] != operation_ref:
                continue
            attempt, generation = self.submission_attempts.get(submission_id, (0, 0))
            if operation_attempt is not None and operation_attempt != attempt:
                continue
            if execution_generation is not None and execution_generation != generation:
                continue
            final = self.submissions.finalizations.get((scope, row.invocation_ref))
            if final is None or final.outcome_basis == "attempt_failed":
                continue
            for item in revisions:
                output = self.outputs[(scope, item.revision_id)]
                if output.run_id != run_id or output.obligation_key != obligation_key:
                    continue
                if any(
                    stored_scope == scope
                    and assessment.subject_kind == "output_revision"
                    and assessment.subject_id == output.revision_id
                    and assessment.subject_digest == output.content_digest
                    and assessment.result in {"fail", "review"}
                    for _, _, assessment in self.recorded_assessments
                ):
                    continue
                prior = newest.get(output.deliverable_id)
                if prior is None or output.revision > prior.revision:
                    newest[output.deliverable_id] = output
        return tuple(newest[key] for key in sorted(newest))

    async def finalized_subject_outputs(
        self,
        scope: str,
        run_id: str,
        obligation_key: str,
        *,
        operation_ref: str,
        operation_attempt: int,
        execution_generation: int,
    ) -> tuple[ExactOutput, ...]:
        newest: dict[str, ExactOutput] = {}
        for (stored_scope, submission_id), revisions in self.by_submission.items():
            row = self.submissions.rows.get(submission_id)
            if stored_scope != scope or row is None:
                continue
            if self.submissions.meta.get(submission_id, ("", "", 0))[1] != operation_ref:
                continue
            attempt, generation = self.submission_attempts.get(submission_id, (0, 0))
            if operation_attempt is not None and operation_attempt != attempt:
                continue
            if execution_generation is not None and execution_generation != generation:
                continue
            final = self.submissions.finalizations.get((scope, row.invocation_ref))
            if final is None or final.outcome_basis == "attempt_failed":
                continue
            for item in revisions:
                output = self.outputs[(scope, item.revision_id)]
                if output.run_id != run_id or output.obligation_key != obligation_key:
                    continue
                prior = newest.get(output.deliverable_id)
                if prior is None or output.revision > prior.revision:
                    newest[output.deliverable_id] = output
        return tuple(newest[key] for key in sorted(newest))

    async def finalized_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        found: list[ExactOutput] = []
        for (stored_scope, submission_id), revisions in self.by_submission.items():
            row = self.submissions.rows.get(submission_id)
            if stored_scope != scope or row is None:
                continue
            final = self.submissions.finalizations.get((scope, row.invocation_ref))
            if final is None or final.outcome_basis == "attempt_failed":
                continue
            found.extend(
                output
                for item in revisions
                if (output := self.outputs[(scope, item.revision_id)]).run_id == run_id
            )
        return tuple(
            sorted(
                found, key=lambda item: (item.obligation_key, item.deliverable_id, item.revision)
            )
        )

    async def accepted_head(
        self, scope: str, run_id: str, obligation_key: str, deliverable_id: str
    ) -> AcceptedHead | None:
        return self.accepted.get((scope, run_id, obligation_key, deliverable_id))

    async def promote(
        self,
        scope: str,
        run_id: str,
        revision: ExactOutput,
        *,
        expected_head: str | None,
        generation: int,
        actor_ref: str,
        at: datetime,
    ) -> AcceptedHead:
        key = (scope, run_id, revision.obligation_key, revision.deliverable_id)
        current = self.accepted.get(key)
        if (None if current is None else current.revision_id) != expected_head:
            raise StaleHead("head moved", current=None if current is None else current.revision_id)
        if current is not None:
            if generation < current.generation:
                raise StaleGeneration(f"generation {generation} is older than {current.generation}")
            if self.outputs[(scope, current.revision_id)].revision > revision.revision:
                raise OlderRevision("an older revision cannot replace a newer accepted head")
        head = AcceptedHead(
            obligation_key=revision.obligation_key,
            deliverable_id=revision.deliverable_id,
            revision_id=revision.revision_id,
            version=1 if current is None else current.version + 1,
            generation=generation,
        )
        self.accepted[key] = head
        return head

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        return tuple(
            self.outputs[(scope, head.revision_id)]
            for (head_scope, head_run, _, _), head in sorted(self.accepted.items())
            if head_scope == scope and head_run == run_id
        )

    async def pin_set(self, scope: str, run_id: str, *, actor_ref: str, at: datetime) -> OutputSet:
        refs = tuple(
            (item.key, item.revision) for item in await self.active_obligations(scope, run_id)
        )
        members = await self.accepted_outputs(scope, run_id)
        digest = membership_digest(refs, members)
        mine = sorted(
            (
                item
                for (s, _), item in self.sets.items()
                if s == scope and item.set_id.startswith(run_id)
            ),
            key=lambda item: item.revision,
        )
        if mine and mine[-1].membership_digest == digest:
            return mine[-1]
        pinned = OutputSet(
            set_id=f"{run_id}:{uuid4()}",
            revision=len(mine) + 1,
            obligation_refs=refs,
            members=members,
            membership_digest=digest,
            prior_set_id=mine[-1].set_id if mine else None,
        )
        self.sets[(scope, pinned.set_id)] = pinned
        return pinned

    async def output_set(self, scope: str, set_id: str) -> OutputSet | None:
        return self.sets.get((scope, set_id))

    async def record_output_assessment(
        self, scope: str, run_id: str, assessment: Assessment, *, actor_ref: str, at: datetime
    ) -> Assessment:
        for stored_scope, _, stored in self.recorded_assessments:
            if stored_scope == scope and stored.assessment_id == assessment.assessment_id:
                return stored
        mine = [stored for s, _, stored in self.recorded_assessments if s == scope]
        if assessment.supersedes is not None:
            for stored in mine:
                if stored.supersedes == assessment.supersedes:
                    raise AssessmentSupersessionConflict(
                        f"assessment {assessment.supersedes} is already superseded",
                        prior=assessment.supersedes,
                        rival=stored.assessment_id,
                    )
        elif assessment.result == "unavailable":
            superseded = {stored.supersedes for stored in mine}
            for stored in mine:
                if (
                    (stored.subject_kind, stored.subject_id, stored.subject_digest)
                    == (assessment.subject_kind, assessment.subject_id, assessment.subject_digest)
                    and stored.result == "unavailable"
                    and stored.assessment_id not in superseded
                ):
                    raise AssessmentSupersessionConflict(
                        "a standing unavailable assessment already exists",
                        prior="",
                        rival=stored.assessment_id,
                    )
        self.recorded_assessments.append((scope, run_id, assessment))
        return assessment

    async def output_assessments(self, scope: str, run_id: str) -> tuple[Assessment, ...]:
        return tuple(a for s, r, a in self.recorded_assessments if s == scope and r == run_id)

    async def record_fulfillment(
        self,
        scope: str,
        run_id: str,
        set_id: str,
        fulfillment: Fulfillment,
        *,
        actor_ref: str,
        at: datetime,
    ) -> str:
        key = (scope, set_id, fulfillment.obligation_key, fulfillment.digest)
        self.fulfillments.setdefault(key, fulfillment)
        return fulfillment.digest

    async def latest_fulfillment(
        self, scope: str, run_id: str, obligation_key: str, obligation_revision: int
    ) -> tuple[str, Fulfillment] | None:
        for (stored_scope, set_id, key, _), decision in reversed(self.fulfillments.items()):
            frontier = self.sets.get((scope, set_id))
            if (
                stored_scope == scope
                and frontier is not None
                and set_id.startswith(f"{run_id}:")
                and key == obligation_key
                and decision.obligation_revision == obligation_revision
            ):
                return set_id, decision
        return None

    async def association_steps(
        self, scope: str, invocation_ref: str, obligation_key: str
    ) -> frozenset[str]:
        return frozenset(
            step
            for (s, inv, key, step) in self.steps
            if s == scope and inv == invocation_ref and key == obligation_key
        )

    async def record_association_step(
        self,
        scope: str,
        run_id: str,
        invocation_ref: str,
        obligation_key: str,
        step: str,
        detail: Mapping[str, Any],
        *,
        actor_ref: str,
        at: datetime,
    ) -> bool:
        key = (scope, invocation_ref, obligation_key, step)
        if key in self.steps:
            return False
        self.steps[key] = detail
        return True


__all__ = ["InMemoryOutputContractStore"]

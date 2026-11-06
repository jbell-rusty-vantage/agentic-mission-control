"""Port of the output-contract store (OUTPUT-CONTRACTS §4; common release 1.7.0).

Obligation revisions, the admitted promise set (with its closed completion), invocation pins,
output revisions, sets/members, assessments and fulfillment decisions are immutable facts; only
the obligation head and the accepted head per deliverable are mutable pointers, each moved by
compare-and-set. Every act that reads or moves heads for a run (register, pin, propose,
activate, promote, pin a frontier) serializes on one per-run lock, so a pinned frontier is one
consistent snapshot. The submission act itself reuses ``output_submission`` (stable scoped key,
same key + other bytes is ``SubmissionConflict``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from mission_control.domain.outputs.contracts import (
    Assessment,
    ExactOutput,
    Fulfillment,
    OutputObligation,
    OutputPromiseSet,
    OutputSet,
    SubmittedRevision,
)


class PromisesConflict(RuntimeError):
    """The run already registered different promises; change them by a governed successor."""


class AssessmentSupersessionConflict(RuntimeError):
    """Another assessment already supersedes the named prior (W1 fix G S1): supersession is a
    compare-and-set on the standing head of one subject, so two writers that read the same
    standing assessment never both replace it. Re-read the standing assessment and decide again."""

    def __init__(self, message: str, *, prior: str, rival: str) -> None:
        super().__init__(message)
        self.prior = prior
        self.rival = rival


class StaleObligationRevision(RuntimeError):
    """The obligation head moved, or a successor is already pending for the next revision."""

    def __init__(self, message: str, *, current: int | None = None) -> None:
        super().__init__(message)
        self.current = current


class StaleHead(RuntimeError):
    """Promotion named an expected head that is no longer the accepted head."""

    def __init__(self, message: str, *, current: str | None = None) -> None:
        super().__init__(message)
        self.current = current


class StaleGeneration(RuntimeError):
    """Promotion from an older execution generation than the current accepted head's."""


class OlderRevision(RuntimeError):
    """Promotion of an older revision number over a newer accepted head of the deliverable."""


@dataclass(frozen=True)
class SubmittedItem:
    deliverable_id: str
    form: str
    candidate: Mapping[str, Any]
    content_digest: str


@dataclass(frozen=True)
class SubmissionAct:
    """One ``submit_output`` act: the scoped submission row plus its output revisions."""

    scope: str
    run_id: str
    operation_ref: str
    operation_attempt: int
    execution_generation: int
    invocation_ref: str
    obligation_key: str
    obligation_revision: int
    submission_key: str
    selection: Mapping[str, Any]
    selection_digest: str
    items: tuple[SubmittedItem, ...]
    producer_origin_ref: str
    caller_origin_ref: str
    actor_ref: str
    at: datetime
    unit_key: str | None = None


@dataclass(frozen=True)
class RecordedSubmission:
    submission_id: str
    revisions: tuple[SubmittedRevision, ...]
    replayed: bool = False


@dataclass(frozen=True)
class AcceptedHead:
    obligation_key: str
    deliverable_id: str
    revision_id: str
    version: int
    generation: int


class OutputContractStore(Protocol):
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
        """The admitted set and revision 1 of every obligation; same set again is a no-op."""
        ...

    async def promise_set(self, scope: str, run_id: str) -> OutputPromiseSet | None:
        """The admitted set as registered (its completion is the only completion used)."""
        ...

    async def active_obligations(self, scope: str, run_id: str) -> tuple[OutputObligation, ...]:
        """The obligation each head points at, in registration order."""
        ...

    async def obligation_revision(
        self, scope: str, run_id: str, obligation_key: str, revision: int
    ) -> OutputObligation | None:
        """One exact recorded revision (a pin or a pinned frontier keeps its own)."""
        ...

    async def pin_invocation(
        self, scope: str, run_id: str, invocation_ref: str, *, actor_ref: str, at: datetime
    ) -> Mapping[str, int]:
        """Pin the active revision of every promise for an invocation at its start (idempotent:
        an existing pin is never moved by a later activation)."""
        ...

    async def invocation_pins(self, scope: str, invocation_ref: str) -> Mapping[str, int]: ...

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
        """Record a pending successor revision; the head does not move
        (``StaleObligationRevision`` when the head moved or one is already pending)."""
        ...

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
        """At a boundary actually reached, move each head whose pending successor waits for
        this boundary kind to that successor, by compare-and-set."""
        ...

    async def record_submission(self, act: SubmissionAct) -> RecordedSubmission:
        """Idempotent per scoped key (an identical retry returns the stored receipt even after
        finalization); ``SubmissionConflict`` / ``SubmissionClosed``. A non-null expected_head
        in selection.submit is checked atomically with recording, serialized with promotion;
        stale values raise ``StaleHead``. Replay lookup precedes that check."""
        ...

    async def output_revision(self, scope: str, revision_id: str) -> ExactOutput | None: ...

    async def accepted_head(
        self, scope: str, run_id: str, obligation_key: str, deliverable_id: str
    ) -> AcceptedHead | None: ...

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
        """Move one deliverable's accepted head by CAS (``StaleHead``/``StaleGeneration``/
        ``OlderRevision``)."""
        ...

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        """The exact revision every accepted head points at."""
        ...

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
        """The newest revision per deliverable of ``obligation_key`` submitted by the exact
        producing operation ``operation_ref`` in a finalized invocation (never a failed or running
        attempt's draft, never a rejected or held revision). WI-02."""
        ...

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
        """Exact successful finalized attempt subjects, including held or rejected revisions.

        Caller must authorize evaluator/repair use; this grants no accepted-head authority.
        """
        ...

    async def finalized_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        """Every revision of the run whose producing invocation was finalized (not a failed
        attempt), whatever its assessment: the current-set index labels held, rejected and
        pending candidates beside the accepted heads (WI-07). Ordered by promise, deliverable
        and revision."""
        ...

    async def pin_set(self, scope: str, run_id: str, *, actor_ref: str, at: datetime) -> OutputSet:
        """Atomically read the promise and accepted heads and pin them as the next set revision
        (or return the latest one when its membership digest is equal)."""
        ...

    async def output_set(self, scope: str, set_id: str) -> OutputSet | None: ...

    async def record_output_assessment(
        self, scope: str, run_id: str, assessment: Assessment, *, actor_ref: str, at: datetime
    ) -> Assessment:
        """Insert once per deterministic assessment id (a retry returns the stored row).

        A row naming ``supersedes`` is a compare-and-set: when another assessment already
        supersedes that prior, raise :class:`AssessmentSupersessionConflict` (serialized per
        prior, so two concurrent supersessions of one standing row never both land)."""
        ...

    async def output_assessments(self, scope: str, run_id: str) -> tuple[Assessment, ...]:
        """In recording order."""
        ...

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
        """Immutable decision row; the same decision for the same set is recorded once."""
        ...

    async def latest_fulfillment(
        self, scope: str, run_id: str, obligation_key: str, obligation_revision: int
    ) -> tuple[str, Fulfillment] | None:
        """Latest recorded decision and exact frontier for this pinned obligation revision.

        A historical decision is not a fresh evaluation of the current accepted heads.
        """
        ...

    async def association_steps(
        self, scope: str, invocation_ref: str, obligation_key: str
    ) -> frozenset[str]: ...

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
        """``False`` when the step was already taken (each step happens at most once)."""
        ...


__all__ = [
    "AcceptedHead",
    "AssessmentSupersessionConflict",
    "OlderRevision",
    "OutputContractStore",
    "PromisesConflict",
    "RecordedSubmission",
    "StaleGeneration",
    "StaleHead",
    "StaleObligationRevision",
    "SubmissionAct",
    "SubmittedItem",
]

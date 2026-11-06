"""Bounded worker history requests; webhook payloads are never execution evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

MAX_HISTORY_FRAMES = 5_000
HISTORY_TIMEOUT_SECONDS = 15
HISTORY_POLL_SECONDS = 1
HISTORY_RETRY_SECONDS = 5
MAX_HISTORY_TURN_RECEIPTS = 64


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HistoryRequest(_Strict):
    schema_version: Literal["mc.history-reconciliation-request.v1"] = (
        "mc.history-reconciliation-request.v1"
    )
    request_scope: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=512)
    harness_execution_id: UUID
    generation: int = Field(ge=1)
    lane_profile: Literal["claude_managed", "codex_agents", "cursor_cloud"]
    session_binding_id: UUID
    workflow_id: str = Field(min_length=1, max_length=2048)
    native_session_ref: str = Field(min_length=1, max_length=512)
    native_turn_ref: str = Field(min_length=1, max_length=512)
    ingress_id: UUID
    received_at: AwareDatetime

    @property
    def watermark(self) -> tuple[AwareDatetime, int]:
        return self.received_at, self.ingress_id.int

    @property
    def binding(self) -> tuple[object, ...]:
        return (
            self.request_scope,
            self.run_id,
            self.harness_execution_id,
            self.generation,
            self.lane_profile,
            self.session_binding_id,
            self.workflow_id,
            self.native_session_ref,
        )


class HistoryAcknowledgment(_Strict):
    request: HistoryRequest
    acknowledged_at: AwareDatetime
    persisted_cursor: str | None = Field(default=None, max_length=4096)


class HistoryRejection(_Strict):
    request: HistoryRequest
    rejected_at: AwareDatetime
    reason: Literal["binding_unavailable"] = "binding_unavailable"


class HistoryJournal(_Strict):
    schema_version: Literal["mc.history-reconciliation-journal.v1"] = (
        "mc.history-reconciliation-journal.v1"
    )
    requested: HistoryRequest
    acknowledgments: tuple[HistoryAcknowledgment, ...] = Field(
        default=(), max_length=MAX_HISTORY_TURN_RECEIPTS
    )

    rejection: HistoryRejection | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )

    @model_validator(mode="after")
    def exact_receipts(self) -> HistoryJournal:
        turns: set[tuple[object, ...]] = set()
        for receipt in self.acknowledgments:
            request = receipt.request
            key = (*request.binding, request.native_turn_ref)
            if (
                request.request_scope != self.requested.request_scope
                or request.harness_execution_id != self.requested.harness_execution_id
                or request.run_id != self.requested.run_id
                or request.watermark > self.requested.watermark
                or key in turns
            ):
                raise ValueError("history receipt binding, ordering or native turn differs")
            turns.add(key)
        if self.rejection is not None:
            request = self.rejection.request
            if (
                request.request_scope != self.requested.request_scope
                or request.harness_execution_id != self.requested.harness_execution_id
                or request.run_id != self.requested.run_id
                or request.watermark > self.requested.watermark
                or self.covers(request)
            ):
                raise ValueError("history rejection authority or disposition differs")
        return self

    def receipt_for(self, request: HistoryRequest) -> HistoryAcknowledgment | None:
        return next(
            (
                receipt
                for receipt in self.acknowledgments
                if receipt.request.binding == request.binding
                and receipt.request.native_turn_ref == request.native_turn_ref
                and receipt.request.watermark >= request.watermark
            ),
            None,
        )

    def covers(self, request: HistoryRequest) -> bool:
        return self.receipt_for(request) is not None

    def rejects(self, request: HistoryRequest) -> bool:
        rejected = None if self.rejection is None else self.rejection.request
        return (
            rejected is not None
            and rejected.binding == request.binding
            and rejected.native_turn_ref == request.native_turn_ref
            and rejected.watermark >= request.watermark
            and not self.covers(request)
        )

    @property
    def pending(self) -> bool:
        return not self.covers(self.requested) and not self.rejects(self.requested)


def enqueue_history(journal: HistoryJournal | None, request: HistoryRequest) -> HistoryJournal:
    if journal is None:
        return HistoryJournal(requested=request)
    if (
        journal.requested.request_scope != request.request_scope
        or journal.requested.harness_execution_id != request.harness_execution_id
        or journal.requested.run_id != request.run_id
    ):
        raise ValueError("history request execution differs")
    if journal.covers(request):
        return journal
    if journal.rejects(request):
        raise ValueError("history request was rejected")
    if (
        journal.requested.binding != request.binding
        or journal.requested.native_turn_ref != request.native_turn_ref
    ):
        if journal.pending:
            raise HistoryDeferred("prior_native_history_pending")
        if request.watermark <= journal.requested.watermark:
            raise ValueError("delayed history request names a superseded native turn")
    elif request.watermark <= journal.requested.watermark:
        return journal
    # Retain proof for crash-after-ack/before-wake retries. Saturation never evicts it.
    if len(journal.acknowledgments) >= MAX_HISTORY_TURN_RECEIPTS and not any(
        r.request.binding == request.binding
        and r.request.native_turn_ref == request.native_turn_ref
        for r in journal.acknowledgments
    ):
        raise HistoryDeferred("history_receipt_capacity")
    return journal.model_copy(update={"requested": request})


class HistoryDeferred(Exception):
    """A valid request is waiting for its owner, not a failed provider delivery."""

    def __init__(self, reason: str = "native_history_pending") -> None:
        super().__init__(reason)
        self.reason = reason


class HistoryReplayIncomplete(Exception):
    """No finite authoritative history boundary was established within the pass bounds."""


@dataclass(frozen=True, slots=True)
class HistoryReplayComplete:
    """Internal iterator marker; emitted only after finite native history was read.

    Never a provider frame and never persisted as native evidence. The owner acknowledges
    only after persisting all preceding frames (or verifying its existing durable cursor).
    """

"""Saved provider results and their durable settlement (Sprint OC WI-04; OUTPUT-CONTRACTS §4).

``mc.invocation_settlement.v1`` realizes the settlement half of ``InvocationFinalization@1``:
the completed provider result of one bound unit generation is **saved before** any
post-execution assessment, effect or review wait, and one durable record then owns the
settlement of that saved result:

* ``saved_result`` / ``saved_result_digest`` / ``saved_result_ref``: the lane's exact
  ``RuntimeResult`` (output, usage, captured checkpoint, cognition points), immutable;
* ``execution_outcome``: what cognition did (``completed``), never rewritten by a wait;
* ``settlement``: ``pending`` (saved, not yet settled) -> ``waiting`` (a typed reason and the
  pending review/effect references) -> ``settled`` (terminal);
* ``recovery_owner``: the operation workflow that owns the wait (``mc.operation.v1``), the only
  reconciler that advances it through ``operation.execute`` / ``operation.cancel``;
* ``claim_fence``: the unit generation's claim fence of the last writer (monotonic: a fenced-out
  holder cannot advance the record); ``stop_fence``: ``cancelled`` once a cancellation fenced
  the saved result (no new evaluation starts; already committed work is still reconciled).

Lifecycle (the operation settlement), execution outcome, obligation fulfillment (the
finalization report and fulfillment decisions it references) and this settlement stay four
separate facts. A retry, restart or replacement worker consumes the saved result and never
dispatches cognition again for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import AwareDatetime, Field, model_validator

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import Contract
from mission_control.domain.authoring.identity import stable_id
from mission_control.domain.execution.contracts import RuntimeResult

INVOCATION_SETTLEMENT_SCHEMA: Final = "mc.invocation_settlement.v1"
DIGEST_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
# The durable wait between settlement passes: exponential from the first delay, capped (the
# cap is the boundary's configuration, default one hour; never above a week). The operation
# workflow sleeps on a Temporal timer between passes (woken early by a cancel).
FIRST_WAIT_SECONDS: Final = 5
DEFAULT_WAIT_CAP_SECONDS: Final = 3_600
MAX_WAIT_SECONDS: Final = 7 * 86_400
MAX_REFS: Final = 256
# Durable settlement events (`invocation_settlement_event`): a periodic alarm while a review
# holds the result, and the deadline after which an effect wait becomes an operator incident.
SettlementEventKind = Literal["review_alarm", "effect_deadline"]


class SettlementState(StrEnum):
    PENDING = "pending"
    WAITING = "waiting"
    SETTLED = "settled"


class WaitReason(StrEnum):
    """Why a saved result is not settled yet (a typed reason, not a run-wide blocked state)."""

    REVIEW_PENDING = "review_pending"
    EFFECT_PENDING = "effect_pending"
    SETTLEMENT_UNAVAILABLE = "settlement_unavailable"


NextAction = Literal["settle", "await_review", "await_effect", "retry_settlement"]
_NEXT_ACTION: Final[dict[WaitReason, NextAction]] = {
    WaitReason.REVIEW_PENDING: "await_review",
    WaitReason.EFFECT_PENDING: "await_effect",
    WaitReason.SETTLEMENT_UNAVAILABLE: "retry_settlement",
}


class SettlementOutcome(Contract):
    """What one settlement pass of a lane reported for a saved result.

    ``settled``: the post-execution work is complete (fulfillment refs name what it recorded);
    ``waiting``: a review or effect is still pending, or the pass could not run (a transient
    failure of the settlement service is a wait, never a cognition failure).
    """

    state: Literal["settled", "waiting"]
    reason: WaitReason | None = None
    pending_reviews: tuple[str, ...] = Field(default=(), max_length=MAX_REFS)
    pending_effects: tuple[str, ...] = Field(default=(), max_length=MAX_REFS)
    fulfillment_refs: tuple[str, ...] = Field(default=(), max_length=MAX_REFS)
    finalization_ref: str | None = Field(default=None, min_length=1, max_length=512)
    detail: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _typed_wait(self) -> SettlementOutcome:
        if self.state == "waiting" and self.reason is None:
            raise ValueError("a waiting settlement names its reason")
        if self.state == "settled" and self.reason is not None:
            raise ValueError("a settled outcome carries no wait reason")
        if self.reason is WaitReason.REVIEW_PENDING and not self.pending_reviews:
            raise ValueError("a review wait names its pending reviews")
        if self.reason is WaitReason.EFFECT_PENDING and not self.pending_effects:
            raise ValueError("an effect wait names its pending effects")
        return self

    @classmethod
    def done(cls, **fields: Any) -> SettlementOutcome:
        return cls(state="settled", **fields)

    @classmethod
    def unavailable(cls, error: BaseException) -> SettlementOutcome:
        """A pass that raised: the saved result waits. W1 D20: a typed refusal also names its
        code, reason and bounded issues (duck-typed: ``code``/``reason``/``issues`` attributes),
        so a KS refusal is legible where the wait is read."""

        detail: dict[str, Any] = {"error_type": type(error).__name__}
        code, reason = getattr(error, "code", None), getattr(error, "reason", None)
        issues = getattr(error, "issues", ())
        if isinstance(code, str):
            detail["code"] = code[:128]
        if isinstance(reason, str):
            detail["reason"] = reason[:128]
        if isinstance(issues, tuple | list) and issues:
            detail["issues"] = [str(item)[:300] for item in issues[:20]]
        return cls(state="waiting", reason=WaitReason.SETTLEMENT_UNAVAILABLE, detail=detail)


def invocation_settlement_id(binding_id: str) -> str:
    """The one saved-result settlement of a bound operation attempt."""

    return stable_id("invocation-settlement", binding_id)


def saved_result_digest(result: RuntimeResult) -> str:
    return sha256_digest(result.model_dump(mode="json"))


def wait_seconds(waits: int, cap: int = DEFAULT_WAIT_CAP_SECONDS) -> int:
    """The durable wait before the next settlement pass (``waits`` passes so far)."""

    bound = max(FIRST_WAIT_SECONDS, min(cap, MAX_WAIT_SECONDS))
    if waits <= 1:
        return FIRST_WAIT_SECONDS
    return min(bound, FIRST_WAIT_SECONDS * 2 ** min(waits - 1, 20))


# K01's Id permits both '/' and '@'; the final '@<schema-version>' is the delimiter.
_REFERENCE_PATTERN: Final = (
    r"^(?:kh:)?[a-z][a-z0-9_.-]{0,119}/[a-z_]+/"
    r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}@[a-z][a-z0-9_.-]*\.v[0-9]+$"
)


class NativeEffectReference(Contract):
    """Bounded reference metadata from the host's native-effect settlement.

    This is inspection evidence, never native admission or fulfillment authority.
    Raw receipt bodies, model output, credentials and arbitrary pass detail are excluded.
    """

    decision: str = Field(min_length=1, max_length=2048, pattern=_REFERENCE_PATTERN)
    subject_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        pattern=r"^kh:[a-z][a-z0-9_.-]{0,119}/[a-z_]+/[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}"
        r"@[a-z][a-z0-9_.-]*\.v[0-9]+#sha256:[0-9a-f]{64}$",
    )
    state: Literal["applied", "noop", "partial", "pending_review", "pending_effect", "refused"]
    effect_key: str | None = Field(default=None, max_length=512, pattern=r"^ek1:[0-9a-f]{64}$")
    receipt_ref: str | None = Field(default=None, max_length=2048, pattern=_REFERENCE_PATTERN)
    receipt_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    journal_state: (
        Literal["prepared", "dispatched", "applied", "noop", "partial", "rejected", "uncertain"]
        | None
    ) = None
    refusal_code: str | None = Field(default=None, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$")


def _native_references(value: object) -> tuple[NativeEffectReference, ...]:
    if not isinstance(value, (tuple, list)) or len(value) > MAX_REFS:
        raise ValueError("native effect evidence is a bounded list of reference metadata")
    references = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("native effect evidence entries are reference metadata objects")
        # Copy only this closed model's fields; no nested input object is retained or changed.
        references.append(
            NativeEffectReference.model_validate(
                {key: item[key] for key in NativeEffectReference.model_fields if key in item}
            )
        )
    return tuple(references)


class InvocationSettlement(Contract):
    """``mc.invocation_settlement.v1``: one saved provider result and its settlement owner."""

    schema_version: Literal["mc.invocation_settlement.v1"] = INVOCATION_SETTLEMENT_SCHEMA
    settlement_id: str = Field(min_length=1)
    request_scope: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    operation_ref: str = Field(min_length=1)
    operation_attempt: int = Field(ge=1)
    unit_key: str = Field(min_length=1)
    execution_generation: int = Field(ge=1)
    saved_result: RuntimeResult
    saved_result_digest: str = Field(pattern=DIGEST_PATTERN)
    execution_outcome: Literal["completed"] = "completed"
    settlement: SettlementState = SettlementState.PENDING
    reason: WaitReason | None = None
    pending_reviews: tuple[str, ...] = Field(default=(), max_length=MAX_REFS)
    pending_effects: tuple[str, ...] = Field(default=(), max_length=MAX_REFS)
    fulfillment_refs: tuple[str, ...] = Field(default=(), max_length=MAX_REFS)
    finalization_ref: str | None = None
    recovery_owner: str = Field(min_length=1, max_length=1024)
    next_action: NextAction | None = "settle"
    claim_fence: int = Field(ge=1)
    stop_fence: Literal["none", "cancelled"] = "none"
    waits: int = Field(default=0, ge=0)
    version: int = Field(default=1, ge=1)
    saved_at: AwareDatetime
    updated_at: AwareDatetime
    settled_at: AwareDatetime | None = None
    # When the current effect wait began (a review or unavailable pass before it does not
    # count), and the operator decision that last restarted it; durable across cycles.
    effect_wait_since: AwareDatetime | None = None
    effect_wait_decision: str | None = Field(default=None, min_length=1, max_length=256)
    # Latest explicit native-reference snapshot, separate from immutable saved cognition.
    # Old records default empty; a transient pass without this key preserves the snapshot.
    native_effects: tuple[NativeEffectReference, ...] = Field(default=(), max_length=MAX_REFS)

    @model_validator(mode="after")
    def _consistent(self) -> InvocationSettlement:
        if self.settlement_id != invocation_settlement_id(self.binding_id):
            raise ValueError("settlement id is not the binding's saved-result settlement")
        if self.saved_result_digest != saved_result_digest(self.saved_result):
            raise ValueError("saved result bytes differ from their digest")
        if self.saved_result.checkpoint is None and self.saved_result.cognition_points:
            raise ValueError("cognition points travel with their captured checkpoint")
        settled = self.settlement is SettlementState.SETTLED
        if settled != (self.settled_at is not None):
            raise ValueError("only a settled record carries its settlement time")
        if settled and (self.reason is not None or self.next_action is not None):
            raise ValueError("a settled record has no wait reason or next action")
        if self.settlement is SettlementState.WAITING and self.reason is None:
            raise ValueError("a waiting record names its typed reason")
        return self

    @property
    def saved_result_ref(self) -> str:
        return f"saved-result:{self.settlement_id}#{self.saved_result_digest}"

    @property
    def settled(self) -> bool:
        return self.settlement is SettlementState.SETTLED

    @classmethod
    def save(
        cls,
        *,
        request_scope: str,
        run_id: str,
        binding_id: str,
        operation_ref: str,
        operation_attempt: int,
        unit_key: str,
        execution_generation: int,
        result: RuntimeResult,
        recovery_owner: str,
        claim_fence: int,
        at: datetime,
    ) -> InvocationSettlement:
        """The record saved right after cognition completed, before any settlement wait."""

        return cls(
            settlement_id=invocation_settlement_id(binding_id),
            request_scope=request_scope,
            run_id=run_id,
            binding_id=binding_id,
            operation_ref=operation_ref,
            operation_attempt=operation_attempt,
            unit_key=unit_key,
            execution_generation=execution_generation,
            saved_result=result,
            saved_result_digest=saved_result_digest(result),
            recovery_owner=recovery_owner,
            claim_fence=claim_fence,
            saved_at=at,
            updated_at=at,
        )

    def advanced(
        self,
        outcome: SettlementOutcome,
        *,
        claim_fence: int,
        at: datetime,
        recovery_owner: str | None = None,
        stop_fence: Literal["none", "cancelled"] | None = None,
        resumed_by: str | None = None,
    ) -> InvocationSettlement:
        """The successor state after one settlement pass (the store applies it by version).

        A settled record never changes; a fence older than the record's refuses (a holder
        fenced out by a takeover cannot advance it); a stop fence is never lifted.
        """

        if self.settled:
            raise ValueError("a settled saved result never changes")
        if claim_fence < self.claim_fence:
            raise ValueError("a fenced-out holder cannot advance the saved result")
        fence = stop_fence or self.stop_fence
        if self.stop_fence == "cancelled" and fence != "cancelled":
            raise ValueError("a stop fence is never lifted")
        settled = outcome.state == "settled"
        # The effect wait's anchor: kept while the wait continues (an unavailable pass in
        # between keeps it), set when an effect wait starts, restarted once per operator
        # decision that resumed the result after an effect-deadline incident.
        anchor: datetime | None = None
        decision = self.effect_wait_decision
        if outcome.reason in {WaitReason.EFFECT_PENDING, WaitReason.SETTLEMENT_UNAVAILABLE}:
            anchor = self.effect_wait_since
            if outcome.reason is WaitReason.EFFECT_PENDING and anchor is None:
                anchor = at
            if resumed_by is not None and resumed_by != decision:
                anchor, decision = (at if anchor is not None else None), resumed_by
        return self.model_copy(
            update={
                "settlement": SettlementState.SETTLED if settled else SettlementState.WAITING,
                "reason": outcome.reason,
                "pending_reviews": outcome.pending_reviews,
                "pending_effects": outcome.pending_effects,
                "fulfillment_refs": outcome.fulfillment_refs or self.fulfillment_refs,
                "finalization_ref": outcome.finalization_ref or self.finalization_ref,
                "next_action": None if settled else _NEXT_ACTION[outcome.reason],  # type: ignore[index]
                "recovery_owner": recovery_owner or self.recovery_owner,
                "claim_fence": claim_fence,
                "stop_fence": fence,
                "waits": self.waits + (0 if settled else 1),
                "version": self.version + 1,
                "updated_at": at,
                "settled_at": at if settled else None,
                "effect_wait_since": None if settled else anchor,
                "effect_wait_decision": decision,
                "native_effects": _native_references(outcome.detail["native_effects"])
                if "native_effects" in outcome.detail
                else self.native_effects,
            }
        )

    def evidence(self) -> dict[str, object]:
        """The settlement's event payload: references only, never the saved bytes."""

        return {
            "invocation_settlement": {
                "schema_version": INVOCATION_SETTLEMENT_SCHEMA,
                "settlement_id": self.settlement_id,
                "saved_result_ref": self.saved_result_ref,
                "execution_outcome": self.execution_outcome,
                "settlement": self.settlement.value,
                "stop_fence": self.stop_fence,
                "finalization_ref": self.finalization_ref,
                "fulfillment_refs": list(self.fulfillment_refs),
                "pending_effects": list(self.pending_effects),
                "settlement_passes": self.waits + 1,
                "recovery_owner": self.recovery_owner,
                **(
                    {
                        "native_effects": [
                            item.model_dump(mode="json", exclude_none=True)
                            for item in self.native_effects
                        ]
                    }
                    if self.native_effects
                    else {}
                ),
            }
        }


class SettlementWait(Contract):
    """The typed wait an unsettled operation result carries back to its workflow."""

    settlement_id: str = Field(min_length=1)
    reason: WaitReason
    next_action: NextAction
    pending_reviews: tuple[str, ...] = ()
    pending_effects: tuple[str, ...] = ()
    wait_seconds: int = Field(ge=1, le=MAX_WAIT_SECONDS)
    stop_fence: Literal["none", "cancelled"] = "none"

    @classmethod
    def of(
        cls, record: InvocationSettlement, *, cap: int = DEFAULT_WAIT_CAP_SECONDS
    ) -> SettlementWait:
        assert record.reason is not None and record.next_action is not None
        return cls(
            settlement_id=record.settlement_id,
            reason=record.reason,
            next_action=record.next_action,
            pending_reviews=record.pending_reviews,
            pending_effects=record.pending_effects,
            wait_seconds=wait_seconds(record.waits, cap),
            stop_fence=record.stop_fence,
        )


__all__ = [
    "DEFAULT_WAIT_CAP_SECONDS",
    "FIRST_WAIT_SECONDS",
    "INVOCATION_SETTLEMENT_SCHEMA",
    "MAX_WAIT_SECONDS",
    "InvocationSettlement",
    "NativeEffectReference",
    "SettlementEventKind",
    "SettlementOutcome",
    "SettlementState",
    "SettlementWait",
    "WaitReason",
    "invocation_settlement_id",
    "saved_result_digest",
    "wait_seconds",
]

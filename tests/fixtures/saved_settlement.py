"""WI-04 generic durable waits: a native-write double and a settler double (no KS, no provider).

``DurableEffectDouble`` stands in for every post-execution wait the saved-result settlement
must survive (OUTPUT-CONTRACTS §4): cognition performs one native write per answer turn (the
scripted model's hook calls :meth:`write`, so a repeated cognition would write again); the
write is acknowledged only when the test delivers its receipt (:meth:`acknowledge`), possibly
late; an independent review holds the result until :meth:`verdict`. Its state is durable for
the test: every "worker" (service attempt) shares it, exactly like a KS journal and a review
service outlive a worker. :meth:`crash_on_pass` loses the worker at a chosen settlement pass.
Real KS and native paths are WI-03/WI-05.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from tests.fixtures.checkpoint_recovery import ScriptedRecoveryModel, SimulatedWorkerCrash

from mission_control.domain.execution.contracts import RuntimeInvocation
from mission_control.domain.execution.invocation_settlement import SettlementOutcome, WaitReason

REVIEW = "review:report"


@dataclass
class DurableEffectDouble:
    review_required: bool = False
    # The native receipt arrives with the write (no effect wait), e.g. for a review-only proof.
    acknowledge_on_write: bool = False
    writes: list[str] = field(default_factory=list)
    receipts: set[str] = field(default_factory=set)
    reviewed: bool = False
    passes: list[bool] = field(default_factory=list)
    unavailable_passes: int = 0
    _crash_on: set[int] = field(default_factory=set)
    _gates: dict[int, tuple[asyncio.Event, asyncio.Event]] = field(default_factory=dict)

    def attach(self, model: ScriptedRecoveryModel, *, answer_turns: tuple[int, ...]) -> None:
        """One native write in every answer turn of cognition (a rerun would write again)."""

        for call in answer_turns:
            model.before_call(call, self.write)

    async def write(self) -> None:
        self.writes.append(f"native-write:{len(self.writes) + 1}")
        if self.acknowledge_on_write:
            self.receipts.add(self.writes[-1])

    def acknowledge(self) -> None:
        """The native receipt arrives (late, after the worker that waited for it is gone)."""

        self.receipts.update(self.writes)

    def verdict(self) -> None:
        self.reviewed = True

    def crash_on_pass(self, number: int) -> None:
        self._crash_on.add(number)

    def gate_on_pass(self, number: int) -> tuple[asyncio.Event, asyncio.Event]:
        """Hold the given pass (entered, release): a Temporal worker can be shut down in it."""

        gate = (asyncio.Event(), asyncio.Event())
        self._gates[number] = gate
        return gate

    def applies(self, invocation: RuntimeInvocation) -> bool:
        del invocation
        return True

    async def settle(
        self, invocation: RuntimeInvocation, *, fenced: bool = False
    ) -> SettlementOutcome:
        del invocation
        self.passes.append(fenced)
        if len(self.passes) in self._crash_on:
            raise SimulatedWorkerCrash(f"worker lost in settlement pass {len(self.passes)}")
        gate = self._gates.get(len(self.passes))
        if gate is not None:
            gate[0].set()
            await gate[1].wait()
        if self.unavailable_passes:
            self.unavailable_passes -= 1
            raise ConnectionError("settlement service unavailable")
        pending = tuple(item for item in self.writes if item not in self.receipts)
        if pending:
            return SettlementOutcome(
                state="waiting", reason=WaitReason.EFFECT_PENDING, pending_effects=pending
            )
        if self.review_required and not self.reviewed and not fenced:
            return SettlementOutcome(
                state="waiting",
                reason=WaitReason.REVIEW_PENDING,
                pending_reviews=(REVIEW,),
                finalization_ref="finalization:double",
            )
        return SettlementOutcome.done(
            finalization_ref="finalization:double", fulfillment_refs=("obligation:report",)
        )


__all__ = ["REVIEW", "DurableEffectDouble"]

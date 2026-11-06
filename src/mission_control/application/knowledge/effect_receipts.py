"""WI-05 (OVE-167): effect-receipt fulfillment evidence from the host knowledge journal.

An ``effect_receipt`` output names a knowledge effect by its key (and optionally its receipt).
It fulfills only when that exact effect settled ``applied`` from its K01 protocol receipt: a
Biotech dispatch settles only after its verified delivery, and an effect whose acknowledgment was
lost settles from the receipt Knowledge Services reconstructs for the ORIGINAL dispatch. Pending
dispatch and an uncertain effect wait; rejected, partial or unknown effects never fulfill
(OUTPUT-CONTRACTS §5, OC-D117, RV-06). The journal is the only source: the producer's candidate
document is a claim, never proof.

Run identity: the effect must have been journaled by THIS run. Its originating origin must carry
mission coordinates whose ``runId`` equals the output revision's ``run_id`` (both are the Mission
Control run id the invocation was admitted under). A standalone or recovery origin refuses
``EFFECT_ORIGIN_UNPROVEN``; any other run, including a forked run or a child run that applied the
effect, refuses ``EFFECT_FOREIGN_RUN``: its effect reaches this run only through an explicit link
or adoption, never by naming its key.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mission_control.application.ports.knowledge import KnowledgeJournal
from mission_control.domain.knowledge.effects import JournalState
from mission_control.domain.outputs.contracts import ExactOutput
from mission_control.domain.outputs.fulfillment import EffectReceiptProof

_UNRESOLVED = frozenset({JournalState.PREPARED, JournalState.DISPATCHED, JournalState.UNCERTAIN})


class JournalEffectReceipts:
    """Implements ``EffectReceiptPort`` over the scoped knowledge journal."""

    def __init__(self, journal: KnowledgeJournal) -> None:
        self._journal = journal

    async def effect_receipts(
        self, scope: str, members: Sequence[ExactOutput]
    ) -> Mapping[str, EffectReceiptProof]:
        proofs: dict[str, EffectReceiptProof] = {}
        for member in members:
            proofs[member.revision_id] = await self._proof(scope, member)
        return proofs

    async def _proof(self, scope: str, member: ExactOutput) -> EffectReceiptProof:
        effect_key = member.candidate.get("effect_key")
        if not isinstance(effect_key, str):
            return EffectReceiptProof("not_applied", reason="the output names no effect key")
        record = await self._journal.lookup(scope, effect_key)
        if record is None:
            return EffectReceiptProof("not_applied", reason="the host journaled no such effect")
        mission = record.originating_origin.mission
        if mission is None:
            return EffectReceiptProof(
                "not_applied",
                code="EFFECT_ORIGIN_UNPROVEN",
                reason="the effect has no mission run coordinates (standalone or recovery origin)",
            )
        if mission.runId != member.run_id:
            return EffectReceiptProof(
                "not_applied",
                code="EFFECT_FOREIGN_RUN",
                reason=(
                    "the effect was applied by another run (a fork, a child or an earlier run); "
                    "link or adopt it instead"
                ),
            )
        if record.state in _UNRESOLVED:
            return EffectReceiptProof("unresolved")
        if record.state is not JournalState.APPLIED or record.terminal_receipt_ref is None:
            return EffectReceiptProof("not_applied", reason=f"the effect settled {record.state}")
        named = member.candidate.get("receipt_ref")
        if isinstance(named, str) and named != record.terminal_receipt_ref:
            return EffectReceiptProof(
                "not_applied", reason="the output names another receipt than the settled one"
            )
        return EffectReceiptProof("applied", ref=record.terminal_receipt_ref)


__all__ = ["JournalEffectReceipts"]

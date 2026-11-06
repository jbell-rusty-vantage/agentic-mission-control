"""Review binds only declared accepted heads, never unrelated or stale output refs."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mission_control.application.human_tasks.packets import NamedOutputReviewPackets
from mission_control.domain.outputs.contracts import ExactOutput, OutputForm, OutputObligation
from mission_control.domain.programs.human_gate import NamedReviewPacketRequest
from tests.unit.human_tasks.fixtures import activation, spec
from tests.unit.outputs.scenario import obligation


def output(key: str, revision: str, *, obligation_revision: int = 1) -> ExactOutput:
    return ExactOutput(
        revision_id=revision,
        run_id="run-1",
        obligation_key=key,
        obligation_revision=obligation_revision,
        deliverable_id=revision,
        revision=1,
        form=OutputForm.TEXT,
        content_digest="sha256:" + "a" * 64,
        candidate={"text": revision},
        producer_origin_ref="producer-attempt",
    )


@dataclass
class Outputs:
    obligations: tuple[OutputObligation, ...]
    accepted: tuple[ExactOutput, ...]

    async def active_obligations(self, scope: str, run_id: str) -> tuple[OutputObligation, ...]:
        assert (scope, run_id) == ("tenant-1", "run-1")
        return self.obligations

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        assert (scope, run_id) == ("tenant-1", "run-1")
        return self.accepted


async def test_review_freezes_exact_named_accepted_heads_and_digest() -> None:
    original = activation(gate=spec(packet_sources=("produce.report",)))
    store = Outputs(
        (obligation("produce.report", OutputForm.TEXT),),
        (output("produce.report", "report-v2"), output("produce.note", "unrelated")),
    )
    prepared = await NamedOutputReviewPackets(store).prepare(
        NamedReviewPacketRequest(activation=original, sources=("produce.report",))
    )
    assert len(prepared.packet) == 1
    item = prepared.packet[0]
    assert item.source == "produce.report"
    assert item.ref == "output-revision:report-v2#digest=" + item.digest
    assert prepared.packet_digest != original.packet_digest
    assert prepared.human_task_id == original.human_task_id
    assert prepared.opened_at == original.opened_at
    store.accepted = (output("produce.report", "report-v3"),)
    assert "report-v2" in prepared.packet[0].ref


@pytest.mark.parametrize("case", ["missing", "unknown", "stale-obligation", "other-run"])
async def test_review_refuses_missing_or_unbound_sources(case: str) -> None:
    promise = obligation("produce.report", OutputForm.TEXT)
    accepted = output("produce.report", "report-v1")
    if case == "stale-obligation":
        accepted = accepted.model_copy(update={"obligation_revision": 2})
    if case == "other-run":
        accepted = accepted.model_copy(update={"run_id": "other-run"})
    store = Outputs(
        () if case == "unknown" else (promise,), () if case == "missing" else (accepted,)
    )
    with pytest.raises(ValueError, match="review source produce.report"):
        await NamedOutputReviewPackets(store).prepare(
            NamedReviewPacketRequest(activation=activation(), sources=("produce.report",))
        )


async def test_review_preserves_multiple_deliverables_for_one_named_source() -> None:
    store = Outputs(
        (obligation("produce.report", OutputForm.TEXT),),
        (output("produce.report", "b"), output("produce.report", "a")),
    )
    prepared = await NamedOutputReviewPackets(store).prepare(
        NamedReviewPacketRequest(activation=activation(), sources=("produce.report",))
    )
    assert [item.ref.split("#")[0] for item in prepared.packet] == [
        "output-revision:a",
        "output-revision:b",
    ]

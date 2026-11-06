"""Break the actual recovery cycle without replacing a pending Temporal decision."""

from dataclasses import replace

import pytest
from tests.unit.recovery.test_terminal_evidence_adoption import adoption_actor, adoption_stack

from mission_control.application.recovery.terminal_evidence_adoption import PendingFamilyResult
from mission_control.application.recovery.terminal_lane_adoption import AdoptionInspectionRefused


async def pending_stack(*, currency=0):
    service, request, fixture, stack, journal, payloads = await adoption_stack(currency=currency)
    original = replace(
        fixture.result,
        observation=replace(
            fixture.result.observation,
            operation_result={},
            operation_disposition="failed",
            child_closed_or_quiesced=True,
        ),
    )
    pending = PendingFamilyResult(
        "exact-operation", "exact-family", 33, "3", "exact-queue", original
    )
    contexts = service._contexts

    class Contexts:
        async def read(self, identity, family_digest):
            context = await contexts.read(identity, family_digest)
            return replace(context, family=original, pending_family_result=pending)

    service._contexts = Contexts()
    return (
        service,
        replace(request, pending_family_result_digest=pending.digest),
        fixture,
        stack,
        journal,
        payloads,
        pending,
    )


async def test_original_claim_then_genuine_pending_request_quarantines_without_digest_poison():
    service, request, fixture, stack, journal, payloads, pending = await pending_stack()
    head = (await fixture.journal()).next_projection_digest
    # Starting the old activity before recovery cannot settle its reservation.
    with pytest.raises(ValueError, match="usage reservation"):
        await fixture.service.decide_result(pending.request)
    assert (await fixture.journal()).next_projection_digest == head
    result = await service.adopt(request, adoption_actor())
    assert result.operation.status == "completed" and result.family is None
    assert result.remaining_liabilities == ("normal_family_activity_pending",)
    assert result.operation.usage.amounts == {"tokens.total": 1}
    assert (await fixture.journal()).next_projection_digest == head
    assert len(journal.settlements) == 1 and stack.lane.calls == []
    assert await payloads.retrieve(result.response)
    replay = await service.adopt(request, adoption_actor())
    assert replay.operation == result.operation and replay.frames.new == 0
    # Only the exact genuinely pending request owns the family mutation identity.
    normal = await fixture.service.decide_result(pending.request)
    assert normal.accepted and normal.proposal.decision.value == "quarantine"
    assert normal.proposal.quarantine_reason == "run_cancelling"
    assert (await fixture.service.decide_result(pending.request)) == normal
    after = await service.adopt(request, adoption_actor())
    assert after.family is None and after.operation == result.operation
    assert len(journal.settlements) == 1 and stack.lane.calls == []


@pytest.mark.parametrize("change", ["mode", "pending_digest"])
async def test_mode_and_original_pending_request_are_bound_before_custody(change):
    service, request, _, stack, journal, payloads, _ = await pending_stack()
    changed = replace(
        request,
        pending_family_result_digest=None if change == "mode" else "sha256:" + "f" * 64,
    )
    with pytest.raises(AdoptionInspectionRefused, match="pending family mode"):
        await service.adopt(changed, adoption_actor())
    assert not journal.settlements and not payloads.payloads and stack.lane.calls == []


@pytest.mark.parametrize("crash_after_settlement", [False, True])
async def test_crash_replays_same_settlement_only_intent_without_family_write(
    monkeypatch, crash_after_settlement
):
    service, request, fixture, stack, journal, _, _ = await pending_stack()
    head = (await fixture.journal()).next_projection_digest
    original = stack.boundary.settle_lane_session

    async def crash(*args, **kwargs):
        if crash_after_settlement:
            await original(*args, **kwargs)
        raise RuntimeError("owned recovery crash")

    monkeypatch.setattr(stack.boundary, "settle_lane_session", crash)
    with pytest.raises(RuntimeError, match="owned recovery crash"):
        await service.adopt(request, adoption_actor())
    assert len(journal.settlements) == int(crash_after_settlement)
    monkeypatch.setattr(stack.boundary, "settle_lane_session", original)
    result = await service.adopt(request, adoption_actor())
    assert result.family is None and len(journal.settlements) == 1
    assert (await fixture.journal()).next_projection_digest == head and stack.lane.calls == []


async def test_unknown_cost_keeps_positive_currency_pending_before_normal_family_can_close():
    service, request, fixture, stack, journal, _, pending = await pending_stack(currency=10)
    result = await service.adopt(request, adoption_actor())
    assert result.operation.usage.pending_external_amounts == {"currency.estimated_micros": 10}
    assert result.remaining_liabilities == (
        "normal_family_activity_pending",
        "admitted_external_usage_pending",
    )
    normal = await fixture.service.decide_result(pending.request)
    assert normal.accepted and normal.proposal.decision.value == "quarantine"
    assert any(
        not liability.closed for liability in normal.projection.producer_liabilities.values()
    )
    budget = await fixture.run_control.get_budget(
        request.identity.request_scope, request.identity.public_run_key
    )
    assert budget.pending_settlement["currency.estimated_micros"] == 10
    assert len(journal.settlements) == 1 and stack.lane.calls == []

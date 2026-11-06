from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from mission_control.application.recovery.terminal_lane_adoption import (
    AdoptionAuthority,
    AdoptionIdentity,
    AdoptionInspectionRefused,
    AdoptionInspectionRequest,
    TerminalLaneAdoption,
    TerminalLaneEvidence,
)


def fixture():
    identity = AdoptionIdentity("scope", "public", "internal", "harness", 1, "agent", "run")
    authority = AdoptionAuthority(
        identity,
        5,
        "cancelling",
        "live",
        "claimed",
        "binding",
        "binding-digest",
        "claim",
        3,
        2,
        4,
        "dispatch-digest",
        True,
        "family-digest",
        "cancel",
        2,
        "delivered",
        None,
    )
    evidence = TerminalLaneEvidence(
        identity,
        "FINISHED",
        "evidence-digest",
        "result-digest",
        2946,
        926070,
        None,
        None,
        None,
        None,
        False,
    )

    class Reader:
        def __init__(self, value):
            self.value = value
            self.next = value
            self.calls = 0

        async def read(self, requested):
            assert requested == identity
            self.calls += 1
            return self.value if self.calls == 1 else self.next

        def __getattr__(self, name):
            raise AssertionError(f"forbidden provider/writer operation: {name}")

    return AdoptionInspectionRequest(identity, 5, 2), Reader(authority), Reader(evidence)


async def test_captured_shape_preserves_finished_unknown_cost_and_delivered_cancel():
    request, authority, evidence = fixture()
    plan = await TerminalLaneAdoption(authority, evidence).inspect(request)
    assert plan.evidence.native_status == "FINISHED"
    assert plan.evidence.total_tokens == 926070 and plan.evidence.cost_micros_usd is None
    assert plan.authority.cancel_state == "delivered"
    assert not plan.provider_acknowledged and not plan.writer_available
    assert plan.blockers == (
        "immutable_result_custody_missing",
        "admitted_currency_unknown",
    )
    assert "cancel_applies_at_terminalization" in plan.warnings
    assert authority.calls == 2 and evidence.calls == 1
    with pytest.raises(FrozenInstanceError):
        plan.digest = "changed"


async def test_missing_revisions_remain_explicit_blockers():
    request, authority, evidence = fixture()
    authority.value = authority.next = replace(
        authority.value,
        harness_revision=None,
        dispatch_revision=None,
        cancel_receipt_revision=None,
    )
    plan = await TerminalLaneAdoption(authority, evidence).inspect(request)
    assert "authority_frontier_missing" in plan.blockers
    assert "cancel_command_frontier_missing" in plan.blockers


@pytest.mark.parametrize(
    "field", ["run_version", "owner_epoch", "dispatch_revision", "dispatch_digest", "identity"]
)
async def test_authority_drift_refuses(field):
    request, authority, evidence = fixture()
    changed = {
        "run_version": 6,
        "owner_epoch": 3,
        "dispatch_revision": 5,
        "dispatch_digest": "changed",
        "identity": replace(request.identity, native_turn_ref="other"),
    }
    authority.next = replace(authority.next, **{field: changed[field]})
    with pytest.raises(AdoptionInspectionRefused, match="authority changed"):
        await TerminalLaneAdoption(authority, evidence).inspect(request)


@pytest.mark.parametrize(
    ("field", "value"), [("expected_run_version", 4), ("expected_owner_epoch", 1)]
)
async def test_stale_request_refuses_before_evidence(field, value):
    request, authority, evidence = fixture()
    with pytest.raises(AdoptionInspectionRefused):
        await TerminalLaneAdoption(authority, evidence).inspect(replace(request, **{field: value}))
    assert evidence.calls == 0


async def test_foreign_native_identity_refuses():
    request, authority, evidence = fixture()
    evidence.value = replace(evidence.value, identity=replace(request.identity, generation=2))
    with pytest.raises(AdoptionInspectionRefused, match="native evidence identity"):
        await TerminalLaneAdoption(authority, evidence).inspect(request)


async def test_plan_digest_stable_and_no_writer_even_when_facts_complete():
    plans = []
    for _ in range(2):
        request, authority, evidence = fixture()
        authority.value = authority.next = replace(authority.value, cancel_state="applied")
        evidence.value = replace(
            evidence.value,
            cost_micros_usd=0,
            custody_ref="artifact",
            custody_immutable=True,
            custody_digest="result-digest",
            custody_size=2946,
        )
        plans.append(await TerminalLaneAdoption(authority, evidence).inspect(request))
    assert plans[0] == plans[1] and not plans[0].blockers
    assert not plans[0].writer_available and not plans[0].provider_acknowledged


async def test_retained_currency_does_not_turn_unknown_cost_into_zero():
    request, authority, evidence = fixture()
    authority.value = authority.next = replace(
        authority.value, currency_liability_retained=True, admitted_currency_micros=100
    )
    plan = await TerminalLaneAdoption(authority, evidence).inspect(request)
    assert "external_billing_unknown" in plan.warnings
    assert "unknown_cost_liability_unproven" not in plan.blockers
    assert plan.evidence.cost_micros_usd is None


@pytest.mark.parametrize(
    "state", ["accepted", "delivered", "applied", "rejected", "expired", "failed", "superseded"]
)
async def test_terminal_command_disposition_never_implies_provider_acknowledgement(state):
    request, authority, evidence = fixture()
    authority.value = authority.next = replace(authority.value, cancel_state=state)
    plan = await TerminalLaneAdoption(authority, evidence).inspect(request)
    assert plan.authority.cancel_state == state
    assert "cancel_command_unresolved" not in plan.blockers
    assert not plan.provider_acknowledged and not plan.writer_available
    assert "external_billing_unknown" in plan.warnings
    assert ("cancel_applies_at_terminalization" in plan.warnings) == (
        state in {"accepted", "delivered"}
    )


async def test_unknown_command_disposition_remains_a_blocker():
    request, authority, evidence = fixture()
    authority.value = authority.next = replace(authority.value, cancel_state="queued")
    plan = await TerminalLaneAdoption(authority, evidence).inspect(request)
    assert "cancel_command_unresolved" in plan.blockers
    assert "cancel_applies_at_terminalization" not in plan.warnings


@pytest.mark.parametrize("currency", [None, 0, 100])
async def test_unknown_billing_only_blocks_unknown_or_unretained_admitted_currency(currency):
    request, authority, evidence = fixture()
    authority.value = authority.next = replace(authority.value, admitted_currency_micros=currency)
    plan = await TerminalLaneAdoption(authority, evidence).inspect(request)
    assert "external_billing_unknown" in plan.warnings
    assert ("admitted_currency_unknown" in plan.blockers) == (currency is None)
    assert ("unknown_cost_liability_unproven" in plan.blockers) == (currency == 100)

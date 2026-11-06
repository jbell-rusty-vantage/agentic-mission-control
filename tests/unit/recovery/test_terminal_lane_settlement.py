"""Terminal evidence uses real settlement/journal/run-control cores, memory ports only."""

from __future__ import annotations

import hashlib
import json

import pytest
from tests.fixtures.checkpoint_recovery import FixtureControlPlane
from tests.fixtures.lane_turns import SCOPE, cursor_operation, lane_stack
from tests.unit.operations.test_lane_admission_rejection import RejectionJournal
from tests.unit.run_control.test_run_control import (
    ConfigurationVerifier,
    actor,
    command,
    request,
    service,
)

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.operation_execution import (
    RunControlOperationAuthority,
    bind_operation_execution_request,
)
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.execution.lanes import UsageReport
from mission_control.domain.policies.contracts import (
    BudgetApplicability,
    BudgetDimensionLimit,
    CommandStatus,
    StartAction,
)


@pytest.mark.parametrize("currency", [0, 100])
async def test_finished_unknown_billing_preserves_evidence_and_only_admitted_liability(currency):
    controls, _ = service()
    admission = request(request_scope=SCOPE)
    limits = {"concurrency.slots": 1, "operation.attempts": 1}
    if currency:
        limits["currency.estimated_micros"] = currency
    declared = {**limits, "tokens.total": 2_000_000}

    class FixtureConfiguration(ConfigurationVerifier):
        async def verify(self, run_request):
            verified = await super().verify(run_request)
            return verified.model_copy(update={"effective_budget_ceilings": declared})

    controls._configuration_verifier = FixtureConfiguration()
    dimensions = tuple(
        BudgetDimensionLimit(
            dimension=dimension.dimension,
            applicability=BudgetApplicability.BOUNDED,
            hard_cap=declared[dimension.dimension],
        )
        if dimension.dimension in declared
        else dimension
        for dimension in admission.budget_envelope.dimensions
    )
    admission = admission.model_copy(
        update={
            "budget_envelope": admission.budget_envelope.model_copy(
                update={"dimensions": dimensions, "baseline_reservations": limits}
            )
        }
    )
    admitted = await controls.admit(admission)
    assert admitted.run_id
    started = await controls.execute(
        command(admitted.run_id, 1, "start", StartAction()).model_copy(
            update={"request_scope": SCOPE}
        )
    )
    assert started.status == CommandStatus.ACCEPTED
    operation = cursor_operation().model_copy(
        update={
            "identity": cursor_operation().identity.model_copy(update={"run_id": admitted.run_id}),
            "run_control_revision": 2,
            "budget_reservation_id": "baseline",
            "budget_limits": limits,
        }
    )
    stack = lane_stack(operation=operation)
    binding = bind_operation_execution_request(operation)
    await stack.bindings.create_binding(binding)
    journal = RejectionJournal()
    payloads = InMemoryArtifactPayloadStore()
    stack.boundary._journal = JournaledOperationExecutionCoordinator(
        journal=journal, run_control=controls, results=payloads, actor=actor()
    )
    stack.boundary._authority = RunControlOperationAuthority(
        controls, FixtureControlPlane(operation)
    )
    stack.boundary._cursor_cost_settlement = True

    class FenceRecorder:
        def __init__(self):
            self.milestones = []

        async def record_milestone(self, *args, **kwargs):
            self.milestones.append(args[3])

    fences = FenceRecorder()
    stack.boundary._stop_fences = fences
    facts = ClosingFacts(
        native_status="finished",
        cost_disposition="unknown",
        usage=UsageReport(
            disposition="estimated",
            input_tokens=456013,
            output_tokens=14072,
            total_tokens=926070,
            cache_read_tokens=417705,
            cache_write_tokens=38280,
        ),
        result_text_ref="artifact:verified-result",
    )
    first = await stack.boundary.settle_lane_session(
        operation, facts, native_turn_ref="native-run", cancelled_by_command=False
    )
    replay = await stack.boundary.settle_lane_session(
        operation, facts, native_turn_ref="native-run", cancelled_by_command=False
    )
    assert replay == first and first.status == "completed"
    budget = await controls.get_budget(SCOPE, admitted.run_id)
    assert len(budget.usage_records) == len(journal.settlements) == 1
    usage = next(iter(budget.usage_records.values()))
    assert usage.actual_amounts == {"tokens.total": 926070}
    assert usage.release_amounts == {"concurrency.slots": 1, "operation.attempts": 1}
    settlement = next(iter(journal.settlements.values()))
    if currency:
        assert settlement.status == "reconciliation_required"
        assert settlement.pending_external_usage == {"currency.estimated_micros": currency}
        assert {key: value for key, value in budget.pending_settlement.items() if value} == {
            "currency.estimated_micros": currency
        }
    else:
        assert settlement.status == "completed" and not settlement.pending_external_usage
        assert not budget.reservations and not any(budget.pending_settlement.values())
        effects = await controls.get_effects(SCOPE, admitted.run_id)
        assert all(effect.settlement is not None for effect in effects.claims.values())
    assert fences.milestones == [] and stack.lane.calls == []
    manifest = json.loads(payloads.payloads[settlement.result_manifest_ref])
    output_bytes = payloads.payloads[manifest["output_payload_ref"]]
    assert "sha256:" + hashlib.sha256(output_bytes).hexdigest() == manifest["output_payload_digest"]
    closing = json.loads(output_bytes)["event_payloads"][0]["lane_closing_facts"]
    assert closing["native_status"] == "finished" and closing["cost_disposition"] == "unknown"
    assert closing["usage"]["total_tokens"] == 926070
    assert closing["usage"]["cost_micros_usd"] is None

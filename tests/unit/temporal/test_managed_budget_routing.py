"""Only a delivery that carries a managed budget gate opts in to budget routing.

The routing itself runs inside a workflow on Temporal in
tests/integration/temporal/test_managed_budget_routing.py."""

from __future__ import annotations

from mission_control.adapters.temporal.workflows import budget_controls as routing
from mission_control.domain.programs.contracts import BoundaryCommandDelivery


def delivery(*, enabled=True):
    return BoundaryCommandDelivery(
        command_id="hold-1",
        kind="pause",
        target_sequence=1,
        execution_epoch=1,
        execution_generation=1,
        accepted_run_version=5,
        payload={
            "kind": "pause",
            "decision": {
                "decision_id": "pause-1",
                "scope": ["run"],
                **(
                    {
                        "budget_gate": {
                            "schema_version": "mc.managed-budget-control.v1",
                            "mode": "budget_gate",
                        }
                    }
                    if enabled
                    else {}
                ),
            },
        },
        payload_digest="sha256:" + "a" * 64,
        idempotency_issuer="operator",
    )


def test_legacy_delivery_does_not_opt_in():
    assert not routing.budget_gate(delivery(enabled=False))
    assert routing.budget_gate(delivery())

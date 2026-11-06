"""Opt-in family routing keeps per-child receipts and cancellation distinct."""

from __future__ import annotations

from tests.unit.harness.test_managed_budget_controls import queue, stack

from mission_control.adapters.temporal.workflows import budget_controls as routing
from mission_control.domain.execution.contracts import OperationWorkflowRequest
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


def work(operation, suffix=""):
    if suffix:
        operation = operation.model_copy(
            update={
                "identity": operation.identity.model_copy(
                    update={"operation_id": operation.identity.operation_id + suffix}
                )
            }
        )
    return OperationWorkflowRequest(
        semantic_attempt_id=operation.identity.semantic_key,
        operation_kind="bound_operation",
        operation=operation,
    )


def test_legacy_delivery_does_not_opt_in():
    assert not routing.budget_gate(delivery(enabled=False))
    assert routing.budget_gate(delivery())


async def test_routes_exact_child_payload_and_task_queue(monkeypatch):
    s = await stack()
    record = await queue(s)
    calls = []
    request = work(s.operation)

    async def activity(name, payload, **options):
        calls.append((name, payload, options))
        return record.model_copy(update={"phase": "boundary_observed"}).model_dump(mode="json")

    monkeypatch.setattr(routing.workflow, "patched", lambda name: True)
    monkeypatch.setattr(routing.workflow, "execute_activity", activity)
    rejection, receipts = await routing.route_budget_gate(delivery(), [request], lambda: False)
    assert rejection == "" and len(receipts) == 1
    name, payload, options = calls[0]
    assert name == "lane.budget_control"
    assert payload["operation"] == s.operation.model_dump(mode="json")
    assert payload["generation"] == request.execution_generation
    assert options["task_queue"] == request.activity_task_queue


async def test_partial_fanout_refusal_retains_first_child_receipt(monkeypatch):
    s = await stack()
    record = await queue(s)
    count = 0

    async def activity(*args, **kwargs):
        nonlocal count
        count += 1
        return record.model_copy(
            update={"phase": "boundary_observed" if count == 1 else "rejected"}
        ).model_dump(mode="json")

    monkeypatch.setattr(routing.workflow, "patched", lambda name: True)
    monkeypatch.setattr(routing.workflow, "execute_activity", activity)
    rejection, receipts = await routing.route_budget_gate(
        delivery(), [work(s.operation), work(s.operation, ":second")], lambda: False
    )
    assert rejection == "not_applicable"
    assert [r["phase"] for r in receipts] == ["boundary_observed", "rejected"]
    assert count == 2


async def test_stop_while_polling_leaves_confirmed_cap_pending(monkeypatch):
    s = await stack()
    record = await queue(s)
    stopped = False

    async def activity(*args, **kwargs):
        return record.model_copy(update={"phase": "cap_confirmed"}).model_dump(mode="json")

    async def wait(*args, **kwargs):
        nonlocal stopped
        stopped = True

    monkeypatch.setattr(routing.workflow, "patched", lambda name: True)
    monkeypatch.setattr(routing.workflow, "execute_activity", activity)
    monkeypatch.setattr(routing.workflow, "wait_condition", wait)
    rejection, receipts = await routing.route_budget_gate(
        delivery(), [work(s.operation)], lambda: stopped
    )
    assert rejection == "superseded" and receipts[0]["phase"] == "cap_confirmed"


async def test_no_targets_never_claims_provider_hold(monkeypatch):
    monkeypatch.setattr(routing.workflow, "patched", lambda name: True)
    assert await routing.route_budget_gate(delivery(), [], lambda: False) == ("not_applicable", [])

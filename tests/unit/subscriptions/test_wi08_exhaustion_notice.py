"""OVE-171 / WI-08: a Stage Graph's held wait for an exhausted route or Revisit Region reaches the
coordinator inbox as an actionable blocked notice (the WI-19 inbox path), named by its condition
id in the journaled `workflow_run.observe_wait` event; an ordinary declared wait is not promoted."""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.application.subscriptions.coordinator import NotificationKind, extract_facts
from mission_control.domain.policies.contracts import SetWaitAction, StartAction, WaitCondition
from tests.unit.run_control.test_run_control import command, request, service
from tests.unit.subscriptions.test_mp15_coordinator import classify_type


@pytest.mark.parametrize("condition", ["route-exhausted:triage_route", "revisit-exhausted:refine"])
def test_an_exhaustion_hold_is_an_actionable_blocked_notice(condition: str) -> None:
    kind, actionable, _public = classify_type(
        "workflow_run.observe_wait", condition_id=condition, condition_kind="external_result"
    )
    assert (kind, actionable) == (NotificationKind.BLOCKED, True)


def test_an_ordinary_declared_wait_is_not_promoted() -> None:
    found = classify_type("workflow_run.observe_wait", condition_id="stagegraph-wait:review")
    assert found is None or found[0] is not NotificationKind.BLOCKED


def _payloads(items: Any) -> list[dict[str, Any]]:
    found = []
    for item in items:
        envelope = getattr(item, "envelope", None) or getattr(item, "event", None) or item
        dumped = envelope.model_dump(mode="json") if hasattr(envelope, "model_dump") else envelope
        found.append(dumped)
    return found


@pytest.mark.asyncio
async def test_the_reducer_journals_the_held_condition_for_the_inbox() -> None:
    run_service, _repository = service()
    admitted = await run_service.admit(request())
    assert admitted.run_id
    await run_service.execute(command(admitted.run_id, 1, "start", StartAction()))
    held = await run_service.execute(
        command(
            admitted.run_id,
            2,
            "route-exhausted",
            SetWaitAction(
                condition=WaitCondition(
                    condition_id="route-exhausted:triage_route",
                    kind="external_result",
                    scope=frozenset({"stage:deep"}),
                    verification_ref="route-exhausted:triage_route",
                    timeout_policy_ref="timeout:none",
                ),
                runnable_work_remains=False,
            ),
        )
    )
    assert held.phase.value == "waiting"
    events = [
        item
        for item in _payloads(await run_service.pending_outbox("tenant-1"))
        if "observe_wait" in str(item)
    ]
    assert events, "the held wait is journaled"
    facts = extract_facts(events[-1].get("payload", events[-1]))
    assert facts["condition_id"] == "route-exhausted:triage_route"
    assert facts["condition_kind"] == "external_result"

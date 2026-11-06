"""MO-44: a watcher's `notify` reaches the coordinator inbox as one notification of its kind,
never a second notification of one fact; a `watcher.failed` is a failure (SPEC-04 §5.1)."""

from __future__ import annotations

from typing import Any, get_args

from mission_control.application.subscriptions.coordinator import (
    CoordinatorProfile,
    JournalEvent,
    NotificationKind,
    PlanInput,
    classify,
    extract_facts,
    plan,
)
from mission_control.domain.programs.watchers import (
    ActionOutcome,
    Firing,
    TriggerRef,
    WatcherSpec,
    action_request_id,
    compile_watcher,
    firing_payload,
)
from mission_control.domain.subscriptions.significance import NotifyKind
from tests.unit.subscriptions.coordinator_fakes import MISSION, T0, journal_event
from tests.unit.watchers.fakes import RUN_ID

SUB = journal_event(1, "x").event_id


def payload(trigger_type: str, then: list[dict[str, Any]], *, ok: bool = True) -> dict[str, Any]:
    descriptor = compile_watcher(
        WatcherSpec.model_validate({"on": {"event": trigger_type}, "then": then}),
        watcher_id="stalled",
        origin="manifest",
        pointer="/mission/controls/watchers/0",
    )
    request_id = action_request_id(RUN_ID, "stalled", "event:e1", 0)
    firing = Firing(
        watcher=descriptor,
        trigger_key="event:e1",
        trigger=TriggerRef(kind="event", ref="e1", type=trigger_type, seq=1),
        at=T0,
        depth=1,
        actions=(),
    )
    outcome = ActionOutcome(0, "notify", request_id, "recorded" if ok else "failed")
    return firing_payload(firing, (outcome,))


def classified(event_type: str, body: dict[str, Any]) -> Any:
    found = classify(
        JournalEvent(journal_event(2, event_type), extract_facts({"payload": body})),
        CoordinatorProfile(),
    )
    return None if found is None else (found.kind, found.actionable)


def test_notify_is_one_notification_of_its_declared_kind_with_its_message() -> None:
    body = payload("artifact.admitted", [{"notify": {"kind": "blocked", "text": "look now"}}])
    assert classified("watcher.fired", body) == (NotificationKind.BLOCKED, True)
    facts = extract_facts({"payload": body})
    assert facts == {
        "watcher_id": "stalled",
        "trigger_type": "artifact.admitted",
        "notify_kind": "blocked",
        "message": "look now",
        "outcome": "fired",
    }
    sealed = plan(
        PlanInput(
            subscription_id=SUB,
            mission_id=MISSION,
            profile=CoordinatorProfile(),
            cursor_seq=0,
            next_inbox_seq=1,
            open=(),
            recent_sealed={},
            depths={},
            events=(JournalEvent(journal_event(1, "watcher.fired"), facts),),
            now=T0,
        )
    ).sealed
    (notification,) = sealed
    assert notification.kind is NotificationKind.BLOCKED and notification.facts["message"] == (
        "look now"
    )


def test_a_trigger_already_notified_as_that_kind_is_not_notified_twice() -> None:
    same = payload("run.completed", [{"notify": {"kind": "terminal_result"}}])
    assert classified("watcher.fired", same) is None
    promoted = payload("run.completed", [{"notify": {"kind": "blocked"}}])
    assert classified("watcher.fired", promoted) == (NotificationKind.BLOCKED, True)


def test_failures_and_plain_firings_classify_by_the_shared_significance_sets() -> None:
    failed = payload("artifact.admitted", [{"probe": {}}], ok=False)
    assert classified("watcher.failed", failed) == (NotificationKind.FAILED, True)
    plain = payload("artifact.admitted", [{"probe": {}}])
    assert classified("watcher.fired", plain) == (NotificationKind.PROGRESS, False)


def test_every_notify_kind_is_an_inbox_notification_kind() -> None:
    assert set(get_args(NotifyKind)) == {item.value for item in NotificationKind} - {
        NotificationKind.RATE_LIMITED.value
    }

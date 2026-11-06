from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mission_control.adapters.temporal.workflows import operation as module


def subject():
    value = object.__new__(module.OperationWorkflow)
    value._cancel_requested = False
    value._reconciliation_nudges = 0
    value._ingress_wakes = 0
    value._ingress_wakes_seen = 0
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(("enabled", "hints", "expected"), [(True, 2, 1), (False, 2, 0)])
async def test_duplicate_hints_coalesce_and_old_history_keeps_handle(
    monkeypatch, enabled, hints, expected
):
    value = subject()
    handle = SimpleNamespace(done=lambda: finished[0], cancel=lambda: pytest.fail("cancelled"))
    finished = [False]
    for _ in range(hints):
        value.ingress_wake("duplicate")
    monkeypatch.setattr(module.workflow, "patched", lambda _: enabled)
    monkeypatch.setattr(value, "_lane_payload", lambda *_: {})
    monkeypatch.setattr(
        module.LaneStatusRequest,
        "model_validate",
        lambda _: SimpleNamespace(model_dump=lambda **_: {}),
    )

    async def wait(predicate):
        if not enabled:
            finished[0] = True
        assert predicate()

    async def status(*args, **kwargs):
        assert args[0] == "lane.status"
        assert kwargs["task_queue"] == "exact-lane"
        finished[0] = True
        return {"done": True}  # Observations never replace the original turn handle.

    call = AsyncMock(side_effect=status)
    monkeypatch.setattr(module.workflow, "wait_condition", wait)
    monkeypatch.setattr(module.workflow, "execute_activity", call)
    await value._wait_active_turn(
        SimpleNamespace(activity_task_queue="exact-lane"), object(), handle
    )
    assert call.await_count == expected
    assert handle.done()


@pytest.mark.asyncio
async def test_active_status_is_bounded_even_with_new_hints(monkeypatch):
    value = subject()
    finished = [False]
    handle = SimpleNamespace(done=lambda: finished[0])
    monkeypatch.setattr(module.workflow, "patched", lambda _: True)
    monkeypatch.setattr(value, "_lane_payload", lambda *_: {})
    monkeypatch.setattr(
        module.LaneStatusRequest,
        "model_validate",
        lambda _: SimpleNamespace(model_dump=lambda **_: {}),
    )
    call = AsyncMock(return_value={"done": True})

    async def wait(predicate):
        value.ingress_wake()
        if call.await_count == 3:
            assert not predicate()  # A fourth hint cannot trigger another read.
            finished[0] = True
        assert predicate()

    monkeypatch.setattr(module.workflow, "wait_condition", wait)
    monkeypatch.setattr(module.workflow, "execute_activity", call)
    await value._wait_active_turn(SimpleNamespace(activity_task_queue="lane"), object(), handle)
    assert call.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_hint_during_segment_is_preserved_only_with_replay_patch(monkeypatch, enabled):
    value = subject()
    monkeypatch.setattr(module.workflow, "patched", lambda _: enabled)
    monkeypatch.setattr(module._SegmentLoop, "start", lambda _: SimpleNamespace(phase="start"))
    monkeypatch.setattr(value, "_visibility", lambda *_: None)
    calls = [0]

    async def segment(*_):
        calls[0] += 1
        if calls[0] == 1:
            value.ingress_wake()
            return {"status": "in_doubt"}
        return {"status": "completed"}

    async def wait(predicate):
        assert predicate() is enabled
        if not enabled:
            value.ingress_wake()  # Historical behavior needs another hint.
        assert predicate()

    monkeypatch.setattr(value, "_next_segment", segment)
    monkeypatch.setattr(module.workflow, "wait_condition", wait)
    assert await value._run_segments(object()) == {"status": "completed"}

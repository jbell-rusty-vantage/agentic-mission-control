"""The probe pauses only real source terminal transport, without replacing its result."""

import asyncio
from types import SimpleNamespace

from mission_control.application.programs.service import RunControlLifecycleGateway
from mission_control.domain.programs.contracts import LifecycleCommandRequest
from tests.fixtures.overnight_linked_cancellation import LinkedCancellationProbe


async def test_source_terminal_pause_preserves_actual_gateway_result(monkeypatch):
    calls = []
    result = object()

    async def execute(self, request):
        calls.append(request)
        return result

    async def settle(live, *, fenced=False):
        return live

    monkeypatch.setattr(RunControlLifecycleGateway, "execute", execute)
    probe = LinkedCancellationProbe("pending")
    lane = SimpleNamespace(toolset=SimpleNamespace(settle_saved=settle))
    probe.install(lane, monkeypatch, SimpleNamespace(source_run="source"))
    request = LifecycleCommandRequest(
        command_id="goal:terminalization:actual",
        expected_run_version=7,
        action={"kind": "terminalize"},
        reason="actual",
        run_id="source",
    )
    task = asyncio.create_task(RunControlLifecycleGateway.execute(None, request))
    await asyncio.wait_for(probe.source_entered.wait(), timeout=1)
    assert not calls and not task.done()
    assert probe.source_terminal_request["expected_run_version"] == 7
    probe.source_release.set()
    assert await task is result and calls == [request]
    # The later cancellation saga terminal request must run normally.
    assert await RunControlLifecycleGateway.execute(None, request) is result


async def test_consumer_pause_occurs_before_settlement_and_fenced_path_is_not_held(monkeypatch):
    calls = []

    async def settle(live, *, fenced=False):
        calls.append((live, fenced))
        return "settled"

    probe = LinkedCancellationProbe("continue")
    lane = SimpleNamespace(toolset=SimpleNamespace(settle_saved=settle))
    probe.install(lane, monkeypatch, SimpleNamespace(source_run="source"))
    live = SimpleNamespace(operation_id="run:stage:consume:1")
    task = asyncio.create_task(lane.toolset.settle_saved(live))
    await asyncio.wait_for(probe.entered.wait(), timeout=1)
    assert not calls
    assert await lane.toolset.settle_saved(live, fenced=True) == "settled"
    probe.release.set()
    assert await task == "settled"
    assert calls == [(live, True), (live, False)]

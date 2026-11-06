"""Run 2 worker, auth, workflow and accounting boundaries; no live service calls."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mission_control.adapters.provider_auth.preflight import SubprocessStatusRunner
from mission_control.adapters.temporal import worker
from mission_control.adapters.temporal.workflows import operation as workflow_module
from mission_control.application.execution.operations.operation_execution import (
    _lane_settlement,
    bind_operation_execution_request,
)
from mission_control.bootstrap.provider_auth import selected_auth_environment, worker_auth_context
from mission_control.bootstrap.worker import wait_worker_background
from mission_control.domain.execution.lane_turns import ClosingFacts
from mission_control.domain.execution.lanes import UsageReport
from tests.fixtures.isolated_settings import isolated_settings
from tests.fixtures.lane_turns import cursor_operation


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "-coordinator-family-stagegraph",
        "-coordinator-family-goal-directed",
        "-generic-artifact",
        "-watchers",
        "-linked-runs",
        "-maintenance",
        "-agent-cognitive",
        "-ingestion-io",
    ],
)
def test_lane_worker_refuses_every_base_queue(suffix, monkeypatch):
    monkeypatch.setattr(worker, "Worker", lambda *a, **k: pytest.fail("must not poll"))
    settings = isolated_settings(
        mission_control_worker_role="lane",
        temporal_task_queue="base",
        mission_control_lane_task_queues=("base" + suffix,),
    )
    with pytest.raises(ValueError, match="non-base"):
        worker.create_production_workers(None, settings, SimpleNamespace())


def test_selected_owner_home_wins_over_inherited_home(tmp_path):
    settings = isolated_settings(
        mission_control_codex_home_mode="owner",
        mission_control_codex_owner_home=tmp_path / "selected",
    )
    inherited = {"CODEX_HOME": str(tmp_path / "wrong"), "OPENAI_API_KEY": "fixture-only"}
    selected = selected_auth_environment(settings, inherited)
    assert selected["CODEX_HOME"] == str(tmp_path / "selected")
    assert inherited["CODEX_HOME"] == str(tmp_path / "wrong")
    assert worker_auth_context(settings, inherited).path_env["CODEX_HOME"] == selected["CODEX_HOME"]


async def test_auth_status_uses_the_configured_codex_executable(monkeypatch):
    process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"", b"")))
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    runner = SubprocessStatusRunner({"CODEX_HOME": "selected"}, binaries={"codex": "/pinned/codex"})
    assert await runner.run(("codex", "login", "status")) is not None
    assert spawn.call_args.args == ("/pinned/codex", "login", "status")
    assert spawn.call_args.kwargs["env"] == {"CODEX_HOME": "selected"}


@pytest.mark.parametrize(("cost", "expected"), [(None, "pending"), (0, "settled"), (25, "settled")])
def test_unknown_cursor_currency_retains_reservation_and_explicit_zero_settles(cost, expected):
    binding = bind_operation_execution_request(
        cursor_operation().model_copy(update={"budget_limits": {"currency.estimated_micros": 100}})
    )
    facts = ClosingFacts(
        native_status="finished",
        usage=UsageReport(disposition="unknown", cost_micros_usd=cost),
        cost_disposition="unknown" if cost is None else "settled",
    )
    result = _lane_settlement(binding, facts, native_turn_ref="run", settle_cursor_cost=True)
    if expected == "pending":
        assert result.usage.pending_external_amounts == {"currency.estimated_micros": 100}
        assert result.usage.amounts == {}
    else:
        assert result.usage.pending_external_amounts == {}
        assert result.usage.amounts == {"currency.estimated_micros": cost}


@pytest.mark.parametrize("patched", [True, False])
async def test_delayed_cost_child_uses_base_workflow_queue_and_exact_lane_activity(
    patched, monkeypatch
):
    start = AsyncMock()
    monkeypatch.setattr(workflow_module.workflow, "start_child_workflow", start)
    monkeypatch.setattr(workflow_module.workflow, "patched", lambda _: patched)
    monkeypatch.setattr(
        workflow_module.workflow, "info", lambda: SimpleNamespace(task_queue="family")
    )
    operation = cursor_operation()
    request = SimpleNamespace(operation=operation, activity_task_queue="lane")
    result = {
        "binding_id": "bound",
        "usage": {"pending_external_amounts": {"currency.estimated_micros": 100}},
    }
    flow = object.__new__(workflow_module.OperationWorkflow)
    assert await flow._settled_lane_result(request, result) is result
    if patched:
        args, kwargs = start.call_args
        assert args[1].request_scope == operation.request_scope
        assert args[1].activity_task_queue == "lane"
        assert kwargs["task_queue"] == "family"
        assert kwargs["parent_close_policy"] == workflow_module.workflow.ParentClosePolicy.ABANDON
    else:
        start.assert_not_called()


async def test_background_failure_fails_worker_and_no_tasks_waits_for_stop():
    async def fail():
        raise RuntimeError("drainer failed")

    stop = asyncio.Event()
    task = asyncio.create_task(fail())
    with pytest.raises(RuntimeError, match="drainer failed"):
        await wait_worker_background(stop, (task,))
    stop.set()
    await wait_worker_background(stop, ())

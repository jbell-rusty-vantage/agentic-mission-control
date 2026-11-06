"""Queued instructions continue the same bounded Deep Agents operation at its native boundary."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from mission_control.application.execution.operations.operation_execution import (
    OperationStopFencePending,
)
from mission_control.contracts.contracts import MissionCommandRequest
from mission_control.domain.execution.contracts import OperationExecutionRequest, RuntimeUsage
from mission_control.domain.execution.errors import RuntimeInvocationFailure
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandStatus,
    PauseAction,
    PauseDecision,
    ReceiptState,
    ReserveBudgetAction,
    ResumeAction,
    ResumeDecision,
)
from tests.fixtures.checkpoint_lineage import bind_unit
from tests.fixtures.checkpoint_recovery import (
    SimulatedWorkerCrash,
    recovery_harness,
    stage_recovery_unit,
)
from tests.fixtures.lane_bindings import lane_fields
from tests.unit.operations.test_ft_f2_interrupt_and_inject import (
    FAST,
    RecordingModel,
    facade,
    harness_with_injections,
    operator,
    states,
    status_of,
)
from tests.unit.run_control.test_run_control import command

MARKER = "QUEUED-NATIVE-FOLLOWUP-EXACT-67142"


async def roomy_request(harness: Any) -> OperationExecutionRequest:
    unit = stage_recovery_unit(harness.run_id)
    original = await harness.request(unit)
    run = await harness.run_control.get_run("tenant-1", harness.run_id)
    reservation = f"queued-reservation:{unit.unit_key}"
    accepted = await harness.run_control.execute(
        command(
            run.run_id,
            run.version,
            "reserve-follow-up-capacity",
            ReserveBudgetAction(reservation_id=reservation, amounts={"tokens.total": 20}),
        )
    )
    bound = bind_unit(
        harness.binding,
        unit,
        control_revision=accepted.resulting_run_version,
        reservation_id=reservation,
        workspace=original.workspace,
    )
    return OperationExecutionRequest.model_validate(
        {
            **original.model_dump(mode="python"),
            **lane_fields(bound),
            "run_control_revision": accepted.resulting_run_version,
            "budget_reservation_id": reservation,
            "budget_limits": {"tokens.total": 20},
        }
    )


async def queue(harness: Any, *, boundary: str = "next_turn", node: str = "draft") -> Any:
    run = await harness.run_control.get_run("tenant-1", harness.run_id)
    return await facade(harness).command(
        harness.run_id,
        MissionCommandRequest.model_validate(
            {
                "request_id": str(uuid4()),
                "expected_version": run.version,
                "expected_generation": 1,
                "target": {"kind": "run", "id": harness.run_id},
                "kind": "queue_instruction",
                "payload": {"content": {"text": MARKER}, "boundary": boundary, "node_key": node},
                "reason": "deliver at native completion without cancelling the current turn",
            }
        ),
        operator(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("crash", [None, "after_claim", "before_append", "after_append"])
async def test_queue_while_running_continues_once_and_recovers_native_input(
    monkeypatch: pytest.MonkeyPatch,
    crash: str | None,
) -> None:
    harness = await harness_with_injections()
    request = await roomy_request(harness)
    entered, gate = harness.model.gate_on(1)
    original = harness.runtime.execute
    crashed = False

    async def execute(invocation: Any, secrets: Any) -> Any:
        nonlocal crashed
        if (
            invocation.follow_up_kind == "queued_instruction"
            and crash in {"before_append", "after_append"}
            and not crashed
        ):
            crashed = True
            if crash == "before_append":
                raise SimulatedWorkerCrash("before queued native input")
            await original(invocation, secrets)
            raise SimulatedWorkerCrash("after queued native completion")
        return await original(invocation, secrets)

    monkeypatch.setattr(harness.runtime, "execute", execute)
    advance = harness.mailbox._advance

    async def advance_receipt(*args: Any, **kwargs: Any) -> Any:
        nonlocal crashed
        if crash == "after_claim" and not crashed and args[2] == ReceiptState.DELIVERED:
            crashed = True
            raise SimulatedWorkerCrash("after queued claim, before delivered receipt")
        return await advance(*args, **kwargs)

    monkeypatch.setattr(harness.mailbox, "_advance", advance_receipt)
    running = asyncio.create_task(harness.run(request))
    await asyncio.wait_for(entered.wait(), 20)
    receipt = await queue(harness)
    assert receipt.admission.status is CommandStatus.ACCEPTED
    assert len(harness.model.calls) == 1
    gate.set()
    if crash is not None:
        with pytest.raises(SimulatedWorkerCrash):
            await asyncio.wait_for(running, 30)
        harness.saver.recover()
        harness.clock.advance(timedelta(minutes=10))
        result = await asyncio.wait_for(harness.run(request), 30)
    else:
        result = await asyncio.wait_for(running, 30)
    assert result.status == "completed"
    assert len(harness.model.calls) == 3, "original two calls plus one queued follow-up"
    assert len(harness.model.humans[-1]) == 2 and MARKER in harness.model.humans[-1][-1]
    assert result.usage.amounts["tokens.total"] == 15
    status = await status_of(harness, receipt)
    assert states(status) == ["accepted", "queued", "delivered", "observed", "applied"]
    reports = [item.delivery_report for item in status.receipts if item.delivery_report is not None]
    assert all(item.delivered_semantics == "turn_boundary_guaranteed" for item in reports)
    assert all(item.native_refs.cancelled_turn_ref is None for item in reports)
    # An already completed operation replays its result, not another queued model call.
    assert await harness.run(request) == result
    assert len(harness.model.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("boundary", "node"), [("next_iteration", "draft"), ("next_turn", "other")]
)
async def test_turn_boundary_does_not_take_another_node_or_iteration(
    boundary: str,
    node: str,
) -> None:
    harness = await harness_with_injections()
    request = await harness.request(stage_recovery_unit(harness.run_id))
    entered, gate = harness.model.gate_on(1)
    running = asyncio.create_task(harness.run(request))
    await asyncio.wait_for(entered.wait(), 20)
    receipt = await queue(harness, boundary=boundary, node=node)
    gate.set()
    result = await asyncio.wait_for(running, 30)
    assert result.status == "completed" and len(harness.model.calls) == 2
    assert states(await status_of(harness, receipt)) == ["accepted", "queued"]


@pytest.mark.asyncio
async def test_queued_turn_at_exact_cap_preserves_completed_spend_and_checkpoint() -> None:
    harness = await harness_with_injections()
    request = await harness.request(stage_recovery_unit(harness.run_id))
    entered, gate = harness.model.gate_on(1)
    running = asyncio.create_task(harness.run(request))
    await asyncio.wait_for(entered.wait(), 20)
    receipt = await queue(harness)
    gate.set()
    result = await asyncio.wait_for(running, 30)
    assert result.status == "failed" and result.failure_code == "budget_exceeded"
    assert result.usage.amounts["tokens.total"] == 10
    assert result.result_checkpoint is not None
    assert len(harness.model.calls) == 2
    assert "applied" not in states(await status_of(harness, receipt))


class FailingQueuedModel(RecordingModel):
    async def _agenerate(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
        if len(self.calls) == 2:
            self._observe(messages)
            return self._reply(0)  # a completed, charged follow-up model/tool call
        if len(self.calls) >= 3:
            raise ConnectionError("queued follow-up provider failure")
        return await super()._agenerate(messages, *args, **kwargs)


@pytest.mark.asyncio
async def test_failed_queued_follow_up_charges_original_and_new_completed_calls() -> None:
    harness = await recovery_harness(model=FailingQueuedModel(), injection_settings=FAST)
    request = await roomy_request(harness)
    entered, gate = harness.model.gate_on(1)
    running = asyncio.create_task(harness.run(request))
    await asyncio.wait_for(entered.wait(), 20)
    receipt = await queue(harness)
    gate.set()
    result = await asyncio.wait_for(running, 30)
    assert result.status == "failed", result
    assert result.usage.amounts["tokens.total"] == 15
    assert result.result_checkpoint is not None
    latest = await harness.saver.aget_tuple(
        {
            "configurable": {
                "thread_id": result.result_checkpoint.thread_id,
                "checkpoint_ns": "",
            }
        }
    )
    assert latest is not None
    assert latest.checkpoint["id"] == result.result_checkpoint.checkpoint_id
    assert states(await status_of(harness, receipt))[-1] == "failed"


@pytest.mark.asyncio
async def test_early_follow_up_failure_cannot_replace_known_usage_with_empty_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await harness_with_injections()
    request = await roomy_request(harness)
    execute = harness.runtime.execute

    async def fail_early(invocation: Any, secrets: Any) -> Any:
        if invocation.follow_up_kind == "queued_instruction":
            raise RuntimeInvocationFailure(
                "EarlyInstrumentationFailure", terminal_result_observed=False, usage=RuntimeUsage()
            )
        return await execute(invocation, secrets)

    monkeypatch.setattr(harness.runtime, "execute", fail_early)
    entered, gate = harness.model.gate_on(1)
    running = asyncio.create_task(harness.run(request))
    await asyncio.wait_for(entered.wait(), 20)
    receipt = await queue(harness)
    gate.set()
    result = await asyncio.wait_for(running, 30)
    assert result.status == "failed" and result.usage.amounts["tokens.total"] == 10
    assert result.result_checkpoint is not None and len(harness.model.calls) == 2
    assert states(await status_of(harness, receipt))[-1] == "failed"


@pytest.mark.asyncio
async def test_paused_boundary_starts_no_queued_turn_until_resume() -> None:
    harness = await recovery_harness(
        model=RecordingModel(),
        injection_settings=FAST,
        real_authority=True,
    )
    request = await roomy_request(harness)
    entered, gate = harness.model.gate_on(1)
    running = asyncio.create_task(harness.run(request))
    await asyncio.wait_for(entered.wait(), 20)
    receipt = await queue(harness)
    run = await harness.run_control.get_run("tenant-1", harness.run_id)
    paused = await harness.run_control.execute(
        command(
            run.run_id,
            run.version,
            "pause-queued",
            PauseAction(
                decision=PauseDecision(
                    decision_id="pause",
                    scope=frozenset({"run"}),
                    reason="hold",
                    authority_ref="authority:lifecycle",
                ),
                runnable_work_remains=False,
            ),
        )
    )
    assert paused.status is CommandStatus.ACCEPTED
    gate.set()
    for _ in range(100):
        if len(harness.model.calls) == 2:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.15)
    assert len(harness.model.calls) == 2 and not running.done()
    assert "applied" not in states(await status_of(harness, receipt))
    resumed = await harness.run_control.execute(
        command(
            run.run_id,
            paused.resulting_run_version,
            "resume-queued",
            ResumeAction(
                decision=ResumeDecision(
                    decision_id="resume",
                    pause_decision_id="pause",
                    reason="release",
                    authority_ref="authority:lifecycle",
                )
            ),
        )
    )
    assert resumed.status is CommandStatus.ACCEPTED
    result = await asyncio.wait_for(running, 30)
    assert result.status == "completed" and result.usage.amounts["tokens.total"] == 15
    assert states(await status_of(harness, receipt))[-1] == "applied"


@pytest.mark.asyncio
async def test_cancel_at_completed_boundary_runs_no_queued_follow_up_and_retains_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await recovery_harness(
        model=RecordingModel(),
        injection_settings=FAST,
        real_authority=True,
    )
    request = await roomy_request(harness)
    authority = harness.service._authority
    verify = authority.verify_continuation
    cancelled = False

    async def verify_after_cancel(*args: Any, **kwargs: Any) -> None:
        nonlocal cancelled
        if len(harness.model.calls) == 2 and not cancelled:
            cancelled = True
            run = await harness.run_control.get_run("tenant-1", harness.run_id)
            await harness.run_control.execute(
                command(run.run_id, run.version, "cancel-at-boundary", CancelAction())
            )
        await verify(*args, **kwargs)

    monkeypatch.setattr(authority, "verify_continuation", verify_after_cancel)
    entered, gate = harness.model.gate_on(1)
    running = asyncio.create_task(harness.run(request))
    await asyncio.wait_for(entered.wait(), 20)
    receipt = await queue(harness)
    gate.set()
    with pytest.raises(OperationStopFencePending):
        await asyncio.wait_for(running, 30)
    harness.clock.advance(timedelta(minutes=10))
    result = await harness.service.cancel(request, harness.attempt(request))
    assert result.status == "cancelled" and result.usage.amounts["tokens.total"] == 10
    assert len(harness.model.calls) == 2
    assert "applied" not in states(await status_of(harness, receipt))

"""Codex accounting joins: all turns, durable attribution and cancellation tails."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from mission_control.adapters.codex.describe import CODEX_DESCRIBE
from mission_control.adapters.codex.usage import CodexNativeRunUsage, observed_usage
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    execution_start,
)
from mission_control.application.execution.harness.native_run_usage import summarize_usage
from mission_control.application.frames.lineage import usage_body
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import OperationExecutionResult
from mission_control.domain.execution.lane_turns import (
    ClosingFacts,
    LaneCancelRequest,
    LaneSegmentBounds,
    LaneTurnRequest,
)
from mission_control.domain.execution.lanes import LaneFrame, SessionHandle, TurnHandle, UsageReport
from mission_control.domain.frames.contracts import FrameKind, FrameObservation, LaneProfile
from tests.fixtures.lane_turns import RecordingSignals, ScriptedSessionLane, lane_stack
from tests.unit.codex.support import codex_operation


def _body(turn, inputs, outputs):
    return {
        "threadId": "thread",
        "turnId": turn,
        "usage": {
            "disposition": "estimated",
            "input_tokens": inputs,
            "output_tokens": outputs,
            "total_tokens": inputs + outputs,
        },
        "codex_usage_provenance": {
            "schema_version": "mc.codex.turn_usage.v1",
            "root_thread_id": "thread",
            "baseline_source": "fresh_thread",
            "monotonic": True,
            "baseline_total": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
            "current_total": {
                "inputTokens": inputs,
                "outputTokens": outputs,
                "totalTokens": inputs + outputs,
            },
        },
    }


def _frame(turn, kind, body=None, **changes):
    encoded = json.dumps(body or {})
    return SimpleNamespace(
        lane_profile=LaneProfile.CODEX,
        native_session_ref="thread",
        native_turn_ref=turn,
        kind=kind,
        subordinate_ref=None,
        body_excerpt=encoded,
        body_bytes=len(encoded.encode()),
        lifecycle_body={},
        **changes,
    )


def test_replayed_turn_snapshots_count_original_and_replacement_once():
    frames = [
        _frame("old", FrameKind.USAGE, _body("old", 15254, 413)),
        _frame("old", FrameKind.TURN_ENDED),
        _frame("new", FrameKind.USAGE, _body("new", 203693, 1862)),
        _frame("new", FrameKind.USAGE, _body("new", 226257, 2565)),
        _frame("new", FrameKind.TURN_ENDED),
    ]
    report = summarize_usage(observed_usage(frames + frames)).report
    assert (report.input_tokens, report.output_tokens, report.total_tokens) == (
        241511,
        2978,
        244489,
    )
    assert report.cost_micros_usd is None
    assert usage_body(LaneProfile.CODEX, _body("new", 226257, 2565)) == {}
    assert usage_body(LaneProfile.CODEX, {"tokenUsage": {"last": {"inputTokens": 7}}}) == {
        "input_tokens": 7
    }


def test_missing_tail_or_baseline_is_unknown_not_a_free_turn():
    known = _frame("old", FrameKind.USAGE, _body("old", 10, 2))
    assert observed_usage([known])[("thread", "old")].disposition == "unknown"
    frames = [known, _frame("old", FrameKind.TURN_ENDED), _frame("new", FrameKind.TURN_ENDED)]
    assert summarize_usage(observed_usage(frames)).report.disposition == "unknown"


def test_equal_counters_do_not_upgrade_a_native_unknown_report_to_free_execution():
    report = observed_usage(
        [
            _frame("old", FrameKind.USAGE, _body("old", 0, 0)),
            _frame("old", FrameKind.TURN_ENDED),
        ]
    )[("thread", "old")]
    assert report.disposition == "unknown"


@pytest.mark.parametrize("field", ["root_thread_id", "turnId"])
def test_malformed_marked_companion_cannot_leave_an_earlier_lower_total_valid(field):
    body = _body("old", 30, 4)
    target = body["codex_usage_provenance"] if field == "root_thread_id" else body
    target[field] = "different"
    report = observed_usage(
        [
            _frame("old", FrameKind.USAGE, _body("old", 10, 2)),
            _frame("old", FrameKind.USAGE, body),
            _frame("old", FrameKind.TURN_ENDED),
        ]
    )[("thread", "old")]
    assert report.disposition == "unknown"


def test_regression_is_sticky_even_after_replay_of_a_known_snapshot():
    known = _frame("old", FrameKind.USAGE, _body("old", 10, 2))
    bad = _body("old", 9, 2)
    bad["codex_usage_provenance"]["monotonic"] = False
    report = observed_usage(
        [
            known,
            _frame("old", FrameKind.USAGE, bad),
            known,
            _frame("old", FrameKind.TURN_ENDED),
        ]
    )[("thread", "old")]
    assert report.disposition == "unknown"


def test_reattach_uses_persisted_baseline_for_newer_counter_without_adding_snapshots():
    newer = _body("old", 30, 4)
    newer["codex_usage_provenance"].update(baseline_total=None, baseline_source="unknown")
    report = observed_usage(
        [
            _frame("old", FrameKind.USAGE, _body("old", 10, 2)),
            _frame("old", FrameKind.USAGE, newer),
            _frame("old", FrameKind.TURN_ENDED),
        ]
    )[("thread", "old")]
    assert report.total_tokens == 34


@pytest.mark.parametrize("missing_predecessor", [False, True])
@pytest.mark.parametrize("live_disagrees", [False, True])
async def test_scoped_settlement_uses_completed_persisted_predecessor_after_reattach(
    missing_predecessor,
    live_disagrees,
):
    operation = codex_operation()
    stack = lane_stack(operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    handle = await stack.frames.open_execution(execution_start(operation, identity, 1, "thread"))
    writer = FrameWriter(stack.frames, handle)
    observations = []
    if not missing_predecessor:
        observations.append(
            FrameObservation(
                provider_key="old:usage:attributed",
                raw_kind="thread/tokenUsage/updated",
                kind=FrameKind.USAGE,
                native_turn_ref="old",
                body=_body("old", 15254, 413),
            )
        )
    observations.append(
        FrameObservation(
            provider_key="old:end",
            raw_kind="turn/completed",
            kind=FrameKind.TURN_ENDED,
            native_turn_ref="old",
            body={},
        )
    )
    observations += [
        FrameObservation(
            provider_key="new:usage:attributed",
            raw_kind="thread/tokenUsage/updated",
            kind=FrameKind.USAGE,
            native_turn_ref="new",
            body=_body("new", 226257, 2565),
        ),
        FrameObservation(
            provider_key="new:end",
            raw_kind="turn/completed",
            kind=FrameKind.TURN_ENDED,
            native_turn_ref="new",
            body={},
        ),
    ]
    await writer.write(observations)

    class Harness(CodexNativeRunUsage):
        async def usage(self, request):
            if request.turn.native_turn_ref == "old":
                return UsageReport(disposition="unknown")  # fresh process has no old baseline
            return UsageReport(
                disposition="estimated",
                input_tokens=226257 if not live_disagrees else 1,
                output_tokens=2565,
                total_tokens=228822 if not live_disagrees else 2566,
            )

    session = SessionHandle(
        lane_profile="codex",
        harness_execution_id=str(identity.harness_execution_id),
        generation=1,
        native_session_ref="thread",
    )
    turn = TurnHandle(session=session, turn_no=2, native_turn_ref="new")
    fields = stack.service._fields(operation, identity, 1, "settle")
    facts = await stack.service._settled_usage(
        Harness(),
        fields,
        turn,
        ClosingFacts(native_status="cancelled"),
        identity=identity,
        semantic_attempt_key=operation.identity.semantic_key,
        binding_digest=operation.effective_configuration_digest,
    )
    if missing_predecessor or live_disagrees:
        assert facts.usage.disposition == "unknown"
    else:
        assert facts.usage.total_tokens == 244489


class _CancelTailLane(CodexNativeRunUsage, ScriptedSessionLane):
    """Status acknowledges cancellation before its buffered observation tail is drained.

    It is the Codex lane's fake: Codex usage attribution and its cancelled close (OC-R3)."""

    cancelled_close = "observe_or_stored"
    unknown = False

    async def observe(self, request):
        self.calls.append(f"observe:{request.after}")
        frames = [
            ("thread/started", {"thread": {"id": "agent-fake-1"}}),
            ("turn/started", {"turn": {"id": "run-fake-1"}}),
        ]
        if self.cancelled:
            body = _body("run-fake-1", 40, 3)
            body["threadId"] = "agent-fake-1"
            body["codex_usage_provenance"]["root_thread_id"] = "agent-fake-1"
            if self.unknown:
                body["usage"] = {"disposition": "unknown"}
                body["codex_usage_provenance"]["baseline_total"] = None
                body["codex_usage_provenance"]["baseline_source"] = "unknown"
            frames += [
                ("thread/tokenUsage/updated", body),
                ("turn/completed", {"turn": {"id": "run-fake-1", "status": "interrupted"}}),
                ("turn/completed.result", {"turn": {"id": "run-fake-1", "status": "interrupted"}}),
            ]
        for index, (kind, body) in enumerate(frames):
            if request.after is not None and index <= int(request.after):
                continue
            yield LaneFrame(
                harness_execution_id=request.harness_execution_id,
                generation=request.generation,
                provider_key=f"fake:{index}",
                cursor=str(index),
                kind=kind,
                raw_kind=kind,
                body=body,
                digest=sha256_digest(body),
                native_turn_ref="run-fake-1",
                terminal=kind == "turn/completed.result",
            )

    async def usage(self, request):
        self.calls.append("usage")
        return (
            UsageReport(disposition="unknown")
            if self.unknown
            else UsageReport(
                disposition="estimated", input_tokens=40, output_tokens=3, total_tokens=43
            )
        )

    def closing_facts(self, turn, frame):
        return ClosingFacts(native_status="cancelled")


@pytest.mark.parametrize("unknown", [False, True])
async def test_cancel_drains_final_usage_and_terminal_frames_before_cleanup(unknown):
    operation = codex_operation()
    lane = _CancelTailLane(describe_matrix=CODEX_DESCRIBE)
    lane.unknown = unknown
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    first = await stack.service.turn(
        LaneTurnRequest(
            operation=operation,
            lane_profile="codex",
            generation=1,
            segment=LaneSegmentBounds(max_frames=2),
        ),
        RecordingSignals(stack.frames, identity.harness_execution_id),
    )
    assert not first.done
    cancelled = await stack.service.cancel(
        LaneCancelRequest(operation=operation, lane_profile="codex", generation=1)
    )
    stored = await stack.frames.frames_for_execution(
        identity.request_scope, identity.harness_execution_id, 1
    )
    assert [f.kind for f in stored][-3:] == [
        FrameKind.USAGE,
        FrameKind.TURN_ENDED,
        FrameKind.RUN_RESULT,
    ]
    assert lane.calls.index("observe:1") < lane.calls.index("end_session")
    result = OperationExecutionResult.model_validate(cancelled.operation_result)
    if unknown:
        assert not cancelled.settled and result.status == "in_doubt"
        assert not stack.budget.settlements
    else:
        assert cancelled.settled and result.status == "cancelled"
        assert result.usage.amounts["tokens.total"] == 43


class _BufferedCancelLane(_CancelTailLane):
    """A persisted prefix larger than a cancellation drain's 256-frame bound."""

    prefix_count = 320

    async def observe(self, request):
        self.calls.append(f"observe:{request.after}")
        prefix = (
            [
                ("turn/started", {"turn": {"id": "run-fake-1"}}),
                *[("item/agentMessage/delta", {"delta": "x"})] * (self.prefix_count - 1),
            ]
            if self.prefix_count
            else []
        )
        frames = prefix
        if self.cancelled:
            body = _body("run-fake-1", 40, 3)
            body["threadId"] = "agent-fake-1"
            body["codex_usage_provenance"]["root_thread_id"] = "agent-fake-1"
            if self.unknown:
                body["usage"] = {"disposition": "unknown"}
                body["codex_usage_provenance"].update(
                    baseline_total=None, baseline_source="unknown"
                )
            frames = [
                *prefix,
                ("thread/tokenUsage/updated", body),
                ("turn/completed", {"turn": {"id": "run-fake-1", "status": "interrupted"}}),
                (
                    "turn/completed.result",
                    {"turn": {"id": "run-fake-1", "status": "interrupted"}},
                ),
            ]
        for index, (kind, body) in enumerate(frames):
            if request.after is not None and index <= int(request.after):
                continue
            yield LaneFrame(
                harness_execution_id=request.harness_execution_id,
                generation=request.generation,
                provider_key=f"buffered:{index}",
                cursor=str(index),
                kind=kind,
                raw_kind=kind,
                body=body,
                digest=sha256_digest(body),
                native_turn_ref="run-fake-1",
                terminal=kind == "turn/completed.result",
            )
        if not self.cancelled:
            self.held.set()
            await self.released.wait()


@pytest.mark.parametrize("unknown", [False, True])
async def test_requested_cancel_flushes_stored_prefix_before_draining_complete_tail(unknown):
    operation = codex_operation()
    lane = _BufferedCancelLane(describe_matrix=CODEX_DESCRIBE)
    lane.unknown = unknown
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    signals = RecordingSignals(stack.frames, identity.harness_execution_id, cancel=True)
    task = asyncio.create_task(
        stack.service.turn(
            LaneTurnRequest(operation=operation, lane_profile="codex", generation=1), signals
        )
    )
    await asyncio.wait_for(lane.held.wait(), timeout=5)
    task.cancel("requested-stop")
    with pytest.raises(asyncio.CancelledError, match="requested-stop"):
        await task
    state = await stack.states.load(identity.request_scope, identity.harness_execution_id)
    assert state.provider_cursor == "319"
    cancelled = await stack.service.cancel(
        LaneCancelRequest(operation=operation, lane_profile="codex", generation=1)
    )
    assert lane.calls.count("observe:None") == 1
    assert "observe:319" in lane.calls
    stored = await stack.frames.frames_for_execution(
        identity.request_scope, identity.harness_execution_id, 1
    )
    assert len(stored) == 323
    assert [frame.kind for frame in stored[-3:]] == [
        FrameKind.USAGE,
        FrameKind.TURN_ENDED,
        FrameKind.RUN_RESULT,
    ]
    result = OperationExecutionResult.model_validate(cancelled.operation_result)
    if unknown:
        assert not cancelled.settled and result.status == "in_doubt"
        assert not stack.budget.settlements
    else:
        assert cancelled.settled and result.status == "cancelled"
        assert result.usage.amounts["tokens.total"] == 43


@pytest.mark.parametrize("prior", [None, "prior-safe-cursor"])
@pytest.mark.parametrize(
    ("prefix_count", "requested", "stale"),
    [(0, True, False), (4, False, False), (4, True, True)],
)
async def test_cancel_without_owned_durable_progress_preserves_prior_cursor(
    prefix_count, requested, stale, prior, monkeypatch
):
    from mission_control.application.execution.harness.dispatch import StaleSessionOwner
    from mission_control.application.execution.harness.state import LaneExecutionUpdate

    operation = codex_operation()
    lane = _BufferedCancelLane(describe_matrix=CODEX_DESCRIBE)
    lane.prefix_count = prefix_count
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    signals = RecordingSignals(stack.frames, identity.harness_execution_id, cancel=requested)
    task = asyncio.create_task(
        stack.service.turn(
            LaneTurnRequest(operation=operation, lane_profile="codex", generation=1), signals
        )
    )
    await asyncio.wait_for(lane.held.wait(), timeout=5)
    await stack.states.record(
        identity.request_scope,
        identity.harness_execution_id,
        LaneExecutionUpdate(provider_cursor=prior),
    )
    if stale:

        async def lost(*args):
            raise StaleSessionOwner("owner changed before cancellation cursor flush")

        monkeypatch.setattr(stack.states, "assert_owner", lost)
    task.cancel("original-cancellation")
    with pytest.raises(asyncio.CancelledError, match="original-cancellation"):
        await task
    state = await stack.states.load(identity.request_scope, identity.harness_execution_id)
    assert state.provider_cursor == prior
    assert lane.cancels == (["command"] if requested else [])
    assert not stack.budget.settlements


async def test_takeover_between_cancel_owner_check_and_cursor_write_keeps_successor_cursor(
    monkeypatch,
):
    from mission_control.application.execution.harness.state import LaneExecutionUpdate

    operation = codex_operation()
    lane = _BufferedCancelLane(describe_matrix=CODEX_DESCRIBE)
    lane.prefix_count = 4
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    scope, heid = identity.request_scope, identity.harness_execution_id
    signals = RecordingSignals(stack.frames, heid, cancel=True)
    task = asyncio.create_task(
        stack.service.turn(
            LaneTurnRequest(operation=operation, lane_profile="codex", generation=1), signals
        )
    )
    await asyncio.wait_for(lane.held.wait(), timeout=5)
    prior_record = stack.states.record
    takeover = None

    async def raced_record(request_scope, harness_execution_id, update, *, owner=None):
        nonlocal takeover
        assert owner is not None, "cancel cursor write must carry its owner into the locked store"
        takeover = await stack.states.claim_owner(
            scope,
            heid,
            owner_ref="successor-worker",
            generation=1,
            now=owner.lease_expires_at + timedelta(seconds=1),
            lease=timedelta(seconds=30),
        )
        await prior_record(scope, heid, LaneExecutionUpdate(provider_cursor="successor-cursor"))
        return await prior_record(request_scope, harness_execution_id, update, owner=owner)

    monkeypatch.setattr(stack.states, "record", raced_record)
    task.cancel("original-cancellation")
    with pytest.raises(asyncio.CancelledError, match="original-cancellation"):
        await task
    state = await stack.states.load(scope, heid)
    assert takeover is not None and state.owner == takeover
    assert state.provider_cursor == "successor-cursor"
    assert not stack.budget.settlements


async def _persist_closed_cancel_turn(stack, lane, operation, identity, *, unknown=False):
    """The interrupted activity stored its tail but never flushed the segment cursor."""
    lane.cancelled = True
    body = _body("run-fake-1", 40, 3)
    body["threadId"] = "agent-fake-1"
    body["codex_usage_provenance"]["root_thread_id"] = "agent-fake-1"
    if unknown:
        body["usage"] = {"disposition": "unknown"}
        body["codex_usage_provenance"]["baseline_total"] = None
        body["codex_usage_provenance"]["baseline_source"] = "unknown"
    handle = await stack.frames.open_execution(
        execution_start(operation, identity, 1, "agent-fake-1")
    )
    await FrameWriter(stack.frames, handle).write(
        [
            FrameObservation(
                provider_key=f"durable:{index}",
                kind=kind,
                raw_kind=raw,
                body=value,
                native_session_ref="agent-fake-1",
                native_turn_ref="run-fake-1",
            )
            for index, (kind, raw, value) in enumerate(
                [
                    (FrameKind.USAGE, "thread/tokenUsage/updated", body),
                    (
                        FrameKind.TURN_ENDED,
                        "turn/completed",
                        {"turn": {"id": "run-fake-1", "status": "interrupted"}},
                    ),
                    (
                        FrameKind.RUN_RESULT,
                        "turn/completed.result",
                        {"turn": {"id": "run-fake-1", "status": "interrupted"}},
                    ),
                ]
            )
        ]
    )


@pytest.mark.parametrize("unknown", [False, True])
async def test_cancel_reuses_durable_close_with_stale_cursor_without_native_replay(
    unknown, monkeypatch
):
    operation = codex_operation()
    lane = _CancelTailLane(describe_matrix=CODEX_DESCRIBE)
    lane.unknown = unknown
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    await stack.service.turn(
        LaneTurnRequest(
            operation=operation,
            lane_profile="codex",
            generation=1,
            segment=LaneSegmentBounds(max_frames=2),
        ),
        RecordingSignals(stack.frames, identity.harness_execution_id),
    )
    await _persist_closed_cancel_turn(stack, lane, operation, identity, unknown=unknown)

    async def no_replay(request):
        raise AssertionError("the complete durable close must not replay the native backlog")
        yield

    monkeypatch.setattr(lane, "observe", no_replay)
    cancelled = await stack.service.cancel(
        LaneCancelRequest(operation=operation, lane_profile="codex", generation=1)
    )
    result = OperationExecutionResult.model_validate(cancelled.operation_result)
    assert "end_session" in lane.calls
    if unknown:
        assert not cancelled.settled and result.status == "in_doubt"
        assert not stack.budget.settlements
    else:
        assert cancelled.settled and result.status == "cancelled"
        assert result.usage.amounts["tokens.total"] == 43


@pytest.mark.parametrize(
    "mismatch",
    ["session", "turn", "generation", "subordinate", "body_turn", "status", "missing_terminal"],
)
async def test_cancel_durable_close_refuses_inexact_or_incomplete_evidence(mismatch, monkeypatch):
    operation = codex_operation()
    lane = _CancelTailLane(describe_matrix=CODEX_DESCRIBE)
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    await stack.service.turn(
        LaneTurnRequest(
            operation=operation,
            lane_profile="codex",
            generation=1,
            segment=LaneSegmentBounds(max_frames=2),
        ),
        RecordingSignals(stack.frames, identity.harness_execution_id),
    )
    await _persist_closed_cancel_turn(stack, lane, operation, identity)
    read = stack.frames.frames_for_execution

    async def incorrect(*args, **kwargs):
        frames = await read(*args, **kwargs)
        result = []
        for frame in frames:
            if frame.kind != FrameKind.RUN_RESULT:
                result.append(frame)
                continue
            if mismatch == "missing_terminal":
                continue
            if mismatch in {"body_turn", "status"}:
                body = {
                    "turn": {
                        "id": "wrong" if mismatch == "body_turn" else "run-fake-1",
                        "status": "running" if mismatch == "status" else "interrupted",
                    }
                }
                raw = json.dumps(body)
                update = {
                    "body_excerpt": raw,
                    "body_bytes": len(raw.encode()),
                    "lifecycle_body": {},
                }
            else:
                update = {
                    {
                        "session": "native_session_ref",
                        "turn": "native_turn_ref",
                        "generation": "generation",
                        "subordinate": "subordinate_ref",
                    }[mismatch]: 2 if mismatch == "generation" else "wrong"
                }
            result.append(frame.model_copy(update=update))
        return tuple(result)

    async def empty_tail(request):
        lane.calls.append("empty_tail")
        if False:
            yield

    monkeypatch.setattr(stack.frames, "frames_for_execution", incorrect)
    monkeypatch.setattr(lane, "observe", empty_tail)
    cancelled = await stack.service.cancel(
        LaneCancelRequest(operation=operation, lane_profile="codex", generation=1)
    )
    assert not cancelled.settled and "empty_tail" in lane.calls
    assert "end_session" not in lane.calls and not stack.budget.settlements


async def test_cancel_durable_close_is_fenced_after_read_owner_takeover(monkeypatch):
    from mission_control.application.execution.harness.dispatch import StaleSessionOwner

    operation = codex_operation()
    lane = _CancelTailLane(describe_matrix=CODEX_DESCRIBE)
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    await stack.service.turn(
        LaneTurnRequest(
            operation=operation,
            lane_profile="codex",
            generation=1,
            segment=LaneSegmentBounds(max_frames=2),
        ),
        RecordingSignals(stack.frames, identity.harness_execution_id),
    )
    await _persist_closed_cancel_turn(stack, lane, operation, identity)
    read, asserted = stack.frames.frames_for_execution, stack.states.assert_owner
    lost = False

    async def takeover(*args, **kwargs):
        nonlocal lost
        frames = await read(*args, **kwargs)
        lost = True
        return frames

    async def check(*args):
        if lost:
            raise StaleSessionOwner("owner changed during durable close read")
        await asserted(*args)

    monkeypatch.setattr(stack.frames, "frames_for_execution", takeover)
    monkeypatch.setattr(stack.states, "assert_owner", check)
    with pytest.raises(StaleSessionOwner):
        await stack.service.cancel(
            LaneCancelRequest(operation=operation, lane_profile="codex", generation=1)
        )
    assert "end_session" not in lane.calls and not stack.budget.settlements


@pytest.mark.parametrize("changed", ["intended", "in_doubt", "current_turn"])
async def test_cancel_durable_close_retains_liability_after_dispatch_state_changes(
    changed, monkeypatch
):
    operation = codex_operation()
    lane = _CancelTailLane(describe_matrix=CODEX_DESCRIBE)
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    await stack.service.turn(
        LaneTurnRequest(
            operation=operation,
            lane_profile="codex",
            generation=1,
            segment=LaneSegmentBounds(max_frames=2),
        ),
        RecordingSignals(stack.frames, identity.harness_execution_id),
    )
    await _persist_closed_cancel_turn(stack, lane, operation, identity)
    read, load_state = stack.frames.frames_for_execution, stack.states.load
    read_finished = False

    async def read_then_change(*args, **kwargs):
        nonlocal read_finished
        frames = await read(*args, **kwargs)
        read_finished = True
        return frames

    async def changed_state(*args):
        state = await load_state(*args)
        if not read_finished:
            return state
        if changed == "current_turn":
            return state.model_copy(update={"native_turn_ref": "new-current-turn"})
        dispatches = dict(state.dispatches)
        key = next(key for key, value in dispatches.items() if value.kind == "send")
        dispatches[key] = dispatches[key].model_copy(update={"phase": changed})
        return state.model_copy(update={"dispatches": dispatches})

    monkeypatch.setattr(stack.frames, "frames_for_execution", read_then_change)
    monkeypatch.setattr(stack.states, "load", changed_state)
    cancelled = await stack.service.cancel(
        LaneCancelRequest(operation=operation, lane_profile="codex", generation=1)
    )
    assert not cancelled.settled and not stack.budget.settlements
    assert "end_session" not in lane.calls


@pytest.mark.parametrize("takeover_at", ["tail", "usage"])
async def test_cancel_does_not_cleanup_or_settle_after_owner_takeover(takeover_at, monkeypatch):
    from mission_control.application.execution.harness.dispatch import StaleSessionOwner

    operation = codex_operation()
    lane = _CancelTailLane(describe_matrix=CODEX_DESCRIBE)
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "codex", 1)
    await stack.service.turn(
        LaneTurnRequest(
            operation=operation,
            lane_profile="codex",
            generation=1,
            segment=LaneSegmentBounds(max_frames=2),
        ),
        RecordingSignals(stack.frames, identity.harness_execution_id),
    )
    lost = False
    prior_assert = stack.states.assert_owner
    prior_observe, prior_usage = lane.observe, lane.usage

    async def assert_owner(*args):
        if lost:
            raise StaleSessionOwner("test owner was replaced")
        await prior_assert(*args)

    async def observe(request):
        nonlocal lost
        async for frame in prior_observe(request):
            if takeover_at == "tail":
                lost = True
            yield frame

    async def usage(request):
        nonlocal lost
        report = await prior_usage(request)
        if takeover_at == "usage":
            lost = True
        return report

    monkeypatch.setattr(stack.states, "assert_owner", assert_owner)
    monkeypatch.setattr(lane, "observe", observe)
    monkeypatch.setattr(lane, "usage", usage)
    with pytest.raises(StaleSessionOwner):
        await stack.service.cancel(
            LaneCancelRequest(operation=operation, lane_profile="codex", generation=1)
        )
    assert "end_session" not in lane.calls
    assert not stack.budget.settlements

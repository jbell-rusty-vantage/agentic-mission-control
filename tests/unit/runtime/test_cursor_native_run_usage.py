from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mission_control.adapters.cursor.usage import CursorNativeRunUsage, observed_usage
from mission_control.application.execution.harness.native_run_usage import summarize_usage
from mission_control.domain.execution.lanes import CursorExecutionBinding, UsageReport
from mission_control.domain.frames.contracts import FrameKind


def _frame(session, run, kind, usage=None):
    body = json.dumps({"usage": usage} if usage is not None else {})
    return SimpleNamespace(
        native_session_ref=session,
        native_turn_ref=run,
        subordinate_ref=None,
        kind=kind,
        body_excerpt=body,
        body_bytes=len(body.encode()),
        lifecycle_body=None,
    )


def test_dual_sse_replay_and_cancelled_continuation_runs_count_once():
    usage = {
        "inputTokens": 11,
        "outputTokens": 7,
        "totalTokens": 18,
        "cacheReadTokens": 2,
        "cacheWriteTokens": 3,
    }
    frames = [
        _frame("source", "cancelled", FrameKind.TURN_ENDED, usage),
        _frame("source", "cancelled", FrameKind.USAGE, usage),
        _frame("source", "cancelled", FrameKind.RUN_RESULT, usage),
        _frame("source", "replacement", FrameKind.RUN_RESULT, usage),
        _frame("target", "continuation", FrameKind.RUN_RESULT, usage),
    ]
    reports = observed_usage(frames + frames)
    summary = summarize_usage(reports)
    assert len(reports) == 3 and summary.report.total_tokens == 54
    assert summary.report.cache_read_tokens == 6 and summary.report.cache_write_tokens == 9
    assert summary.report.disposition == "estimated" and summary.report.cost_micros_usd is None


def test_unknown_run_is_not_a_zero_summand_or_settled_aggregate():
    reports = {
        ("a", "known"): UsageReport(
            disposition="settled",
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
            cost_micros_usd=12,
        ),
        ("a", "unknown"): UsageReport(disposition="unknown"),
    }
    summary = summarize_usage(reports)
    assert summary.report.disposition == "unknown"
    assert summary.unknown_runs == (("a", "unknown"),)
    assert summary.partial_token_totals["total_tokens"] == 18
    assert summary.report.cost_micros_usd is None and summary.report.cache_read_tokens is None


def test_explicit_zero_cost_settles_and_duplicate_native_identity_cannot_charge_twice():
    report = UsageReport(
        disposition="settled",
        input_tokens=1,
        total_tokens=1,
        cost_micros_usd=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    summary = summarize_usage({("a", "r"): report})
    assert summary.report.cost_micros_usd == 0 and summary.cost_disposition == "settled"
    assert summary.report.cache_read_tokens == 0


def test_missing_token_counter_remains_unknown_even_with_reported_total():
    reports = observed_usage([_frame("a", "r", FrameKind.RUN_RESULT, {"totalTokens": 20})])
    assert reports[("a", "r")].disposition == "unknown"
    assert summarize_usage(reports).cost_disposition == "unknown"


@pytest.mark.parametrize("limit", [1, 2])
async def test_missing_output_followup_uses_one_durable_dispatch_and_sums_both_runs(limit):
    from mission_control.adapters.cursor.describe import CURSOR_CLOUD_DESCRIBE
    from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.execution.lane_turns import LaneTurnRequest
    from mission_control.domain.execution.lanes import LaneFrame, TurnHandle
    from tests.fixtures.lane_turns import (
        RecordingSignals,
        ScriptedSessionLane,
        cursor_operation,
        lane_stack,
    )

    class Lane(CursorNativeRunUsage, ScriptedSessionLane):
        def stage_turn(self, execution, reference, text):
            self.staged_text = text

        async def send_turn(self, request):
            self.sends.append(request.idempotency_key)
            return TurnHandle(
                session=request.session,
                turn_no=request.turn_no,
                native_turn_ref=f"run-{len(self.sends)}",
            )

        async def observe(self, request):
            run = request.turn.native_turn_ref
            body = {"status": "finished", "usage": {"inputTokens": 10, "outputTokens": 5}}
            yield LaneFrame(
                harness_execution_id=request.harness_execution_id,
                generation=request.generation,
                provider_key=f"{run}:result",
                cursor=f"{run}@result",
                kind="result",
                raw_kind="result",
                body=body,
                terminal=True,
                digest=sha256_digest(body),
                native_turn_ref=run,
            )

        def closing_facts(self, turn, frame):
            return (
                super()
                .closing_facts(turn, frame)
                .model_copy(update={"missing_outputs": ("outputs/report.md",)})
            )

        async def missing_output_followup(self, turn, facts):
            return "Produce outputs/report.md" if turn.turn_no == 1 else None

    lane = Lane(describe_matrix=CURSOR_CLOUD_DESCRIBE)
    operation = cursor_operation("cursor_cloud")
    operation = operation.model_copy(
        update={
            "budget_limits": {
                **operation.budget_limits,
                "model.turns": limit,
            }
        }
    )
    stack = lane_stack(lane, operation=operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    request = LaneTurnRequest(
        operation=operation, lane_profile="cursor_cloud", generation=1, turn_no=1, segment_no=1
    )
    result = await stack.service.turn(
        request, RecordingSignals(stack.frames, identity.harness_execution_id)
    )
    assert result.done and result.closing_facts.usage.total_tokens == 15 * limit
    assert len(lane.sends) == limit
    if limit == 2:
        assert lane.sends[-1].endswith(":missing-outputs:1")
    state = await stack.states.load(identity.request_scope, identity.harness_execution_id)
    assert state.native_turn_ref == f"run-{limit}"
    assert state.dispatch("send", lane.sends[-1]).phase == "acknowledged"
    assert len(stack.budget.settlements) == 1
    replay = await stack.service.turn(
        request, RecordingSignals(stack.frames, identity.harness_execution_id)
    )
    assert replay.done and len(lane.sends) == limit and len(stack.budget.settlements) == 1


async def test_production_reader_union_accounts_two_generations_and_excludes_other_attempt():
    from uuid import uuid4

    from mission_control.application.execution.harness.lane_turns import (
        LaneExecutionIdentity,
        execution_start,
    )
    from mission_control.application.frames.writer import FrameWriter
    from mission_control.domain.execution.lane_turns import ClosingFacts
    from mission_control.domain.execution.lanes import SessionHandle, TurnHandle
    from mission_control.domain.frames.contracts import FrameObservation
    from tests.fixtures.cursor_controls import harness_fields
    from tests.fixtures.lane_turns import cursor_operation, lane_stack

    operation = cursor_operation("cursor_cloud")
    stack = lane_stack(operation=operation)
    reader = stack.frames
    identities = [
        LaneExecutionIdentity.of(operation, "cursor_cloud", generation) for generation in (1, 2)
    ]
    for generation, identity in enumerate(identities, 1):
        start = execution_start(operation, identity, generation, f"agent-{generation}")
        handle = await reader.open_execution(start)
        writer = FrameWriter(reader, handle)
        observation = FrameObservation(
            provider_key=f"native-{generation}:final",
            raw_kind="result",
            kind=FrameKind.RUN_RESULT,
            native_turn_ref=f"native-{generation}",
            native_session_ref=f"agent-{generation}",
            body={"usage": {"inputTokens": generation * 10, "outputTokens": 1}},
        )
        await writer.write([observation])
        await writer.write([observation])  # durable replay, not a second summand
    other = operation.model_copy(
        update={"identity": operation.identity.model_copy(update={"operation_attempt": 2})}
    )
    other_identity = LaneExecutionIdentity.of(other, "cursor_cloud", 3)
    other_start = execution_start(other, other_identity, 3, "other-agent")
    other_handle = await reader.open_execution(other_start)
    await FrameWriter(reader, other_handle).write(
        [
            FrameObservation(
                provider_key="other:final",
                raw_kind="result",
                kind=FrameKind.RUN_RESULT,
                native_session_ref="other-agent",
                native_turn_ref="other-native",
                body={"usage": {"inputTokens": 99999, "outputTokens": 1}},
            )
        ]
    )

    class Harness(CursorNativeRunUsage):
        calls = []

        async def usage(self, request):
            pair = (request.session.native_session_ref, request.turn.native_turn_ref)
            self.calls.append(pair)
            amount = {("agent-1", "native-1"): 11, ("agent-2", "native-2"): 17}[pair]
            return UsageReport(
                disposition="settled",
                input_tokens=amount,
                total_tokens=amount,
                cost_micros_usd=amount,
            )

    harness = Harness()
    target = identities[1]
    session = SessionHandle(
        lane_profile="cursor_cloud",
        harness_execution_id=str(target.harness_execution_id),
        generation=2,
        native_session_ref="agent-2",
    )
    turn = TurnHandle(session=session, turn_no=1, native_turn_ref="native-2")
    fields = harness_fields(operation, str(target.harness_execution_id), "cursor_cloud")
    # harness_fields defaults are overwritten explicitly: same semantic attempt, new generation.
    fields["generation"] = 2
    facts = await stack.service._settled_usage(
        harness,
        fields,
        turn,
        ClosingFacts(native_status="finished"),
        identity=target,
        semantic_attempt_key=operation.identity.semantic_key,
        binding_digest=CursorExecutionBinding.carried_by(operation).binding_digest,
    )
    assert facts.usage.total_tokens == 28 and facts.usage.cost_micros_usd == 28
    assert set(harness.calls) == {("agent-1", "native-1"), ("agent-2", "native-2")}
    assert len(harness.calls) == 2
    with pytest.raises(ValueError, match="bound"):
        await reader.frames_for_semantic_attempt(
            target.request_scope,
            target.run_key,
            target.activation_key,
            operation.identity.semantic_key,
            CursorExecutionBinding.carried_by(operation).binding_digest,
            "cursor_cloud",
            limit=1,
        )

    legacy = execution_start(operation, target, 4, "legacy-agent").model_copy(
        update={
            "harness_execution_id": uuid4(),
            "native_identity": {"operation_id": operation.identity.operation_id},
            "intended_binding_digest": "sha256:" + "8" * 64,
        }
    )
    await reader.open_execution(legacy)
    with pytest.raises(ValueError, match="historical semantic-attempt"):
        await reader.frames_for_semantic_attempt(
            target.request_scope,
            target.run_key,
            target.activation_key,
            operation.identity.semantic_key,
            CursorExecutionBinding.carried_by(operation).binding_digest,
            "cursor_cloud",
        )
    # Remove only this synthetic legacy row before the separate binding-drift assertion.
    reader._executions.pop(legacy.harness_execution_id)

    drift = execution_start(operation, target, 4, "drift-agent").model_copy(
        update={"harness_execution_id": uuid4(), "intended_binding_digest": "sha256:" + "9" * 64}
    )
    await reader.open_execution(drift)
    with pytest.raises(ValueError, match="binding drift"):
        await reader.frames_for_semantic_attempt(
            target.request_scope,
            target.run_key,
            target.activation_key,
            operation.identity.semantic_key,
            CursorExecutionBinding.carried_by(operation).binding_digest,
            "cursor_cloud",
        )


async def test_known_cost_can_coexist_with_unknown_tokens_without_zero_fill():
    report = UsageReport(disposition="unknown", cost_micros_usd=19)
    summary = summarize_usage({("a", "run"): report})
    assert summary.report.disposition == "unknown"
    assert summary.report.cost_micros_usd == 19 and summary.cost_disposition == "settled"
    assert summary.unknown_runs == (("a", "run"),)


@pytest.mark.parametrize("reverse", [False, True])
def test_cumulative_result_beats_per_turn_usage_in_either_order(reverse):
    cumulative = {
        "inputTokens": 10,
        "outputTokens": 5,
        "cacheReadTokens": 20,
        "cacheWriteTokens": 4,
        "totalTokens": 39,
    }
    frames = [
        _frame("a", "r", FrameKind.RUN_RESULT, cumulative),
        _frame("a", "r", FrameKind.USAGE, {"inputTokens": 2, "outputTokens": 1, "totalTokens": 3}),
    ]
    if reverse:
        frames.reverse()
    assert observed_usage(frames + frames)[("a", "r")].total_tokens == 39


@pytest.mark.parametrize("kind", [FrameKind.USAGE, FrameKind.TURN_ENDED])
def test_per_turn_only_evidence_cannot_attest_native_run_total(kind):
    report = observed_usage(
        [_frame("a", "r", kind, {"inputTokens": 2, "outputTokens": 1, "totalTokens": 3})]
    )[("a", "r")]
    assert report.disposition == "unknown"


@pytest.mark.parametrize(
    ("usage", "total", "disposition"),
    [
        (
            {
                "inputTokens": 10,
                "outputTokens": 5,
                "cacheReadTokens": 20,
                "cacheWriteTokens": 4,
                "reasoningTokens": 2,
            },
            39,
            "estimated",
        ),
        ({"inputTokens": 10, "outputTokens": 5}, 0, "unknown"),
        ({"inputTokens": 10, "outputTokens": 5, "totalTokens": 0}, 0, "estimated"),
        ({"inputTokens": 10, "totalTokens": 12}, 0, "unknown"),
    ],
)
def test_run_total_requires_explicit_total_or_all_cursor_dimensions(usage, total, disposition):
    from mission_control.adapters.cursor.frames import closing_facts

    frame = _frame("a", "r", FrameKind.RUN_RESULT, usage)
    observed = observed_usage([frame])[("a", "r")]
    closing = closing_facts({"status": "finished", "usage": usage}).usage
    assert (observed.total_tokens, observed.disposition) == (total, disposition)
    assert (closing.total_tokens, closing.disposition) == (total, disposition)


@pytest.mark.parametrize(
    ("authority", "expected", "disposition"),
    [("failure", 39, "estimated"), ("known", 50, "settled"), ("unknown", 0, "unknown")],
)
async def test_cancelled_run_observation_and_authoritative_read_policy(
    authority, expected, disposition
):
    from mission_control.application.execution.harness.lane_turns import (
        LaneExecutionIdentity,
        execution_start,
    )
    from mission_control.application.frames.writer import FrameWriter
    from mission_control.domain.execution.lane_turns import ClosingFacts
    from mission_control.domain.execution.lanes import SessionHandle, TurnHandle
    from mission_control.domain.frames.contracts import FrameObservation
    from tests.fixtures.cursor_controls import harness_fields
    from tests.fixtures.lane_turns import cursor_operation, lane_stack

    operation = cursor_operation("cursor_cloud")
    stack = lane_stack(operation=operation)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    handle = await stack.frames.open_execution(execution_start(operation, identity, 1, "agent"))
    writer = FrameWriter(stack.frames, handle)
    for key, kind, usage in [
        (
            "final",
            FrameKind.RUN_RESULT,
            {
                "inputTokens": 10,
                "outputTokens": 5,
                "cacheReadTokens": 20,
                "cacheWriteTokens": 4,
                "totalTokens": 39,
            },
        ),
        ("late-turn", FrameKind.USAGE, {"inputTokens": 2, "outputTokens": 1, "totalTokens": 3}),
    ]:
        await writer.write(
            [
                FrameObservation(
                    provider_key=key,
                    raw_kind="result" if key == "final" else "usage",
                    kind=kind,
                    native_turn_ref="run",
                    native_session_ref="agent",
                    body={"usage": usage},
                )
            ]
        )
    cancelled = await stack.service._turn_usage(CursorNativeRunUsage(), identity, 1, "run")  # type: ignore[arg-type]
    assert cancelled.total_tokens == 39

    class Harness(CursorNativeRunUsage):
        async def usage(self, request):
            if authority == "failure":
                raise RuntimeError("fixture unavailable")
            if authority == "unknown":
                return UsageReport(disposition="unknown")
            return UsageReport(
                disposition="settled", input_tokens=40, output_tokens=10, total_tokens=50
            )

    session = SessionHandle(
        lane_profile="cursor_cloud",
        harness_execution_id=str(identity.harness_execution_id),
        generation=1,
        native_session_ref="agent",
    )
    facts = await stack.service._settled_usage(
        Harness(),
        harness_fields(operation, str(identity.harness_execution_id), "cursor_cloud"),
        TurnHandle(session=session, turn_no=1, native_turn_ref="run"),
        ClosingFacts(native_status="cancelled"),
        identity=identity,
        semantic_attempt_key=operation.identity.semantic_key,
        binding_digest=CursorExecutionBinding.carried_by(operation).binding_digest,
    )
    assert (facts.usage.total_tokens, facts.usage.disposition) == (expected, disposition)

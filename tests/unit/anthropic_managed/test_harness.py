"""The `claude_managed` Session Lane over the fake Managed Agents API (SPEC-06 section 4.2).

Each lifecycle operation against `FakeManagedAgentsApi` (HL-23 event shapes): prepare from the
pack and the launch readiness gate (MO-16), the budgeted session and its dispatch metadata,
sends gated on idle, observe from the stream and the turn's history, reattach after a lost
worker with no frame stored twice, cancel by interrupt, the budget-gate pause, usage settled
from `list_cost`, and end as interrupt, archive, then deletion ordered after retention.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.anthropic_managed.harness import (
    ClaudeManagedHarness,
    ManagedSessionDeleter,
)
from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.operations.conformance import ConformanceRuntime
from mission_control.application.agentic_components.placement import LaneProjectionError
from mission_control.application.environments.preparation import (
    EnvironmentPreparationService,
    InMemoryEnvironmentPreparationRepository,
)
from mission_control.application.execution.harness.dispatch import DispatchRecord
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
    harness_scope,
)
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationExecutionResult,
)
from mission_control.domain.execution.environment_preparation import ReadinessLevel
from mission_control.domain.execution.lane_turns import LaneSegmentBounds, LaneTurnRequest
from mission_control.domain.execution.lanes import (
    CancelTurnRequest,
    EndSessionRequest,
    PrepareRequest,
    SendTurnRequest,
    SessionHandle,
    StartRequest,
    StatusRequest,
    TurnHandle,
    UsageRequest,
)
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.lane_turns import LaneStack, RecordingSignals, SimulatedWorkerLoss, lane_stack
from tests.fixtures.managed_agents import MODEL_USAGE, TURN_LIST_COST
from tests.fixtures.managed_lane import (
    MAX_LIST_COST,
    PROFILE,
    ManagedStack,
    managed_harness,
    managed_stack,
)

BOUNDS = LaneSegmentBounds(
    max_frames=500,
    max_duration_s=20,
    start_to_close_s=40,
    heartbeat_timeout_s=3,
    status_poll_limit=2,
    status_poll_interval_s=1,
    busy_wait_s=10,
)
WITHIN_S = 20.0
TURN_TOKENS = sum(MODEL_USAGE.values())


def _identity(operation: OperationExecutionRequest) -> LaneExecutionIdentity:
    return LaneExecutionIdentity.of(operation, PROFILE, 1)


def _fields(operation: OperationExecutionRequest, key: str) -> dict[str, Any]:
    identity = _identity(operation)
    assert ProviderExecutionBinding.carried_by(operation) is not None
    return {
        "scope": harness_scope(identity.request_scope),
        "lane_profile": PROFILE,
        "harness_execution_id": str(identity.harness_execution_id),
        "binding_digest": ProviderExecutionBinding.carried_by(operation).binding_digest,
        "idempotency_key": f"{identity.harness_execution_id}:1:{key}",
        "generation": 1,
    }


def _turn_request(operation: OperationExecutionRequest, **changes: Any) -> LaneTurnRequest:
    return LaneTurnRequest.model_validate(
        {"operation": operation, "lane_profile": PROFILE, "generation": 1, "segment": BOUNDS}
        | changes
    )


def _settled(result: Any) -> OperationExecutionResult:
    return OperationExecutionResult.model_validate(result.operation_result)


async def _started(stack: ManagedStack) -> tuple[str, SessionHandle]:
    operation = stack.operation
    heid = str(_identity(operation).harness_execution_id)
    stack.harness.stage(heid, operation)
    prepared = await stack.harness.prepare(
        PrepareRequest(
            **_fields(operation, "turn:1"),
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
        )
    )
    session = await stack.harness.start(
        StartRequest(**_fields(operation, "turn:1"), prepared=prepared)
    )
    return heid, session


async def _sent(stack: ManagedStack, session: SessionHandle, turn_no: int = 1) -> TurnHandle:
    return await stack.harness.send_turn(
        SendTurnRequest(
            **_fields(stack.operation, f"turn:{turn_no}"),
            session=session,
            turn_no=turn_no,
            instruction_ref=f"operation:test:turn:{turn_no}",
        )
    )


def _lanes(stack: ManagedStack, **changes: Any) -> LaneStack:
    return lane_stack(stack.harness, operation=stack.operation, **changes)


async def _frames(lanes: LaneStack, operation: OperationExecutionRequest) -> tuple[Any, ...]:
    identity = _identity(operation)
    return await lanes.frames.frames_for_execution(
        identity.request_scope, identity.harness_execution_id, 1, limit=1_000
    )


# --- prepare and the launch readiness gate (MO-16) ---------------------------------------------


async def test_prepare_syncs_the_pack_and_names_the_provider_environment(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    operation = stack.operation
    heid = str(_identity(operation).harness_execution_id)
    stack.harness.stage(heid, operation)
    prepared = await stack.harness.prepare(
        PrepareRequest(
            **_fields(operation, "turn:1"),
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
        )
    )
    (environment,) = stack.api.environments
    (agent,) = stack.api.agents
    assert prepared.workspace_ref == f"provider_environment:{environment}"
    assert prepared.materialization_ref == f"agent:{agent}@1"
    digests = prepared.projection_digests
    assert digests["materialization_digest"] == stack.pack.materialization_digest
    assert {"kit_digest", "agent_readback_digest", "secret_set_digest"} <= set(digests)


async def test_a_binding_pinning_another_materialization_is_refused_before_any_sync(
    tmp_path: Path,
) -> None:
    stack = managed_stack(
        tmp_path, binding_changes={"materialization_digest": "sha256:" + "e" * 64}
    )
    with pytest.raises(LaneProjectionError, match="CAPABILITY_DRIFT"):
        await _started(stack)
    assert not stack.api.agents and not stack.api.requests


def test_a_code_mission_keeps_multiagent_off(tmp_path: Path) -> None:
    """DECISIONS R33: subagents and workflows only on read-only knowledge work."""

    stack = managed_stack(
        tmp_path,
        binding_changes={
            "provider_options": {
                "provider": PROFILE,
                "max_list_cost_minor_units": MAX_LIST_COST,
                "multiagent": True,
            },
            "repo_url": "https://github.com/acme/service",
            "repo_commit": "0123456789abcdef",
        },
    )
    with pytest.raises(ValueError, match="keeps multiagent off"):
        stack.harness.stage("heid", stack.operation)


async def test_a_launch_is_admitted_at_delivered_readiness_by_the_default_cloud_policy(
    tmp_path: Path,
) -> None:
    """MO-16 hazard: the default cloud minimum is `delivered`; the provider environment the
    pack was synced into is that delivery, so the session starts."""

    stack = managed_stack(tmp_path)
    repository = InMemoryEnvironmentPreparationRepository()
    lanes = _lanes(stack, preparations=EnvironmentPreparationService(repository))
    identity = _identity(stack.operation)
    result = await lanes.service.turn(
        _turn_request(stack.operation),
        RecordingSignals(lanes.frames, identity.harness_execution_id),
    )
    assert result.done and _settled(result).status == "completed"
    (record,) = repository.records.values()
    assert record.readiness == ReadinessLevel.DELIVERED
    (delivery,) = record.deliveries
    assert delivery.channel == "provider_environment"
    assert delivery.ref == f"provider_environment:{next(iter(stack.api.environments))}"
    assert any("receipt signal" in omission for omission in record.omissions)


# --- start, send, observe, settle --------------------------------------------------------------


async def test_start_creates_one_budgeted_session_stamped_for_reconciliation(
    tmp_path: Path,
) -> None:
    stack = managed_stack(tmp_path)
    heid, session = await _started(stack)
    created = stack.api.sessions[session.native_session_ref or ""]
    (agent_id,) = stack.api.agents
    assert created["agent"]["id"] == agent_id and created["agent"]["version"] == 1
    assert created["agent"]["type"] == "agent_with_overrides"
    assert "system" in created["agent"]
    assert all(
        segment.content in created["agent"]["system"]
        for segment in stack.operation.prompt_segments
        if segment.trust_class.value in {"system_authority", "authored_instruction"}
    )
    assert created["environment_id"] == next(iter(stack.api.environments))
    assert created["vault_ids"] == list(stack.api.vaults)
    assert created["budget"] == {
        "type": "limit",
        "max_list_cost": {"amount": str(MAX_LIST_COST), "currency": "USD"},
    }
    identity = _identity(stack.operation)
    assert created["metadata"] == {
        "mc_run": identity.run_key,
        "mc_generation": "1",
        "mc_dispatch": f"{heid}:1:turn:1",
        "mc_unit": identity.activation_key,
    }
    assert created["status"] == "idle" and not stack.api.messages(), "no turn before send_turn"


async def test_drill_labels_are_stamped_on_the_session(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    stack.harness = managed_harness(stack.api, stack.pack, labels={"mc_run": "run1-HL-08"})
    _heid, session = await _started(stack)
    assert stack.api.sessions[session.native_session_ref or ""]["metadata"]["mc_run"] == (
        "run1-HL-08"
    )


async def test_a_turn_runs_settles_from_its_closing_idle_and_ends_after_custody(
    tmp_path: Path,
) -> None:
    stack = managed_stack(tmp_path)
    lanes = _lanes(stack)
    identity = _identity(stack.operation)
    result = await lanes.service.turn(
        _turn_request(stack.operation),
        RecordingSignals(lanes.frames, identity.harness_execution_id),
    )
    assert result.done and _settled(result).status == "completed"
    facts = result.closing_facts
    assert facts is not None and facts.native_status == "finished"
    assert facts.result_excerpt == "Done: report.md"
    assert (facts.usage.disposition, facts.usage.total_tokens) == ("settled", TURN_TOKENS)
    assert facts.usage.cost_micros_usd == TURN_LIST_COST * 10_000
    assert facts.cost_disposition == "settled"
    (sent,) = stack.api.messages()
    assert sent[1] == "Summarize the release notes.", "inputs only: no packet files in the sandbox"
    frames = await _frames(lanes, stack.operation)
    keys = [frame.provider_key for frame in frames]
    assert len(keys) == len(set(keys))
    kinds = [frame.kind for frame in frames]
    assert kinds.count(FrameKind.RUN_RESULT) == 1 and kinds[-1] == FrameKind.RUN_RESULT
    assert FrameKind.MESSAGE in kinds and FrameKind.USAGE in kinds
    assert FrameKind.UNKNOWN not in kinds
    assert "session.status_running" not in {frame.raw_kind for frame in frames}, (
        "events before the turn's message was processed are not this turn's"
    )
    # End: archived, the manifest in custody, deletion ordered after the retention interval.
    (session_id,) = stack.api.sessions
    assert stack.api.archived() == [session_id]
    (order,) = stack.deletions.orders.values()
    assert order.session_ref == session_id and order.lane_profile == PROFILE
    (manifest,) = stack.artifacts.staged.values()
    captured = json.loads(manifest[1])
    assert captured["provenance"]["provider_session_ref"] == session_id
    assert set(captured["turns"].values().__iter__().__next__()) >= {"status", "usage"}


async def test_usage_unreported_by_the_provider_stays_unknown(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path, scripts=("no_usage",))
    lanes = _lanes(stack)
    identity = _identity(stack.operation)
    result = await lanes.service.turn(
        _turn_request(stack.operation),
        RecordingSignals(lanes.frames, identity.harness_execution_id),
    )
    facts = result.closing_facts
    assert facts is not None and facts.native_status == "finished"
    assert facts.usage.disposition == "unknown" and facts.cost_disposition == "unknown"


async def test_a_second_turn_costs_only_what_it_added(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path, scripts=("full", "full"))
    _heid, session = await _started(stack)
    for turn_no in (1, 2):
        turn = await _sent(stack, session, turn_no)
        assert turn.native_turn_ref is not None
        async for _frame in stack.harness.observe(_observe(stack, turn, f"observe:{turn_no}")):
            pass
        report = await stack.harness.usage(
            UsageRequest(**_fields(stack.operation, "usage"), session=session, turn=turn)
        )
        assert report.total_tokens == TURN_TOKENS
        assert report.cost_micros_usd == TURN_LIST_COST * 10_000, f"turn {turn_no}"


def _observe(stack: ManagedStack, turn: TurnHandle, key: str, after: str | None = None) -> Any:
    from mission_control.domain.execution.lanes import ObserveRequest

    return ObserveRequest(**_fields(stack.operation, key), turn=turn, after=after)


async def test_a_message_is_not_sent_while_a_turn_runs(tmp_path: Path) -> None:
    """Q-M1: a message sent while running would steer the current turn, so it waits."""

    stack = managed_stack(tmp_path, scripts=("held", "full"))
    _heid, session = await _started(stack)
    first = await _sent(stack, session)
    assert first.status == "accepted"
    busy = await _sent(stack, session, 2)
    assert busy.status == "busy" and busy.native_turn_ref is None
    assert len(stack.api.messages()) == 1
    stack.api.release()
    assert (await _sent(stack, session, 2)).status == "accepted"


# --- reattach after a lost worker --------------------------------------------------------------


async def test_a_reattach_after_the_worker_died_stores_no_frame_twice(tmp_path: Path) -> None:
    """The worker dies between a persisted frame and its heartbeat; another worker (a fresh
    harness process, no in-process state) takes the expired session over, resumes from the
    persisted frames' position and settles the turn: one session, one message, each event
    stored once."""

    stack = managed_stack(tmp_path)
    lanes = _lanes(stack)
    identity = _identity(stack.operation)
    dying = RecordingSignals(lanes.frames, identity.harness_execution_id, fail_on=4)
    with pytest.raises(SimulatedWorkerLoss):
        await lanes.service.turn(_turn_request(stack.operation), dying)
    stored = len(await _frames(lanes, stack.operation))
    assert stored > 0

    successor = managed_harness(stack.api, stack.pack, deletions=stack.deletions)
    later = datetime.now(UTC) + timedelta(minutes=5)
    service = LaneTurnService(
        lanes=LaneRegistry(
            [DeepAgentsHarness(ConformanceRuntime()), successor], allow_unqualified=True
        ),
        boundary=lanes.boundary,
        frames=lanes.frames,
        states=lanes.states,
        sessions=WorkerSessionManager(owner_ref="worker-b"),
        clock=lambda: later,
    )
    result = await service.turn(
        _turn_request(stack.operation, phase="resume"),
        RecordingSignals(lanes.frames, identity.harness_execution_id),
    )
    assert result.done and _settled(result).status == "completed"
    assert len(stack.api.sessions) == 1 and len(stack.api.messages()) == 1
    frames = await _frames(lanes, stack.operation)
    keys = [frame.provider_key for frame in frames]
    assert len(keys) == len(set(keys)), "the resumed segment stored no frame twice"
    assert [frame.kind for frame in frames].count(FrameKind.RUN_RESULT) == 1
    events = [frame.raw_kind for frame in frames if frame.raw_kind != "status"]
    turn_events = [
        event["type"]
        for event in stack.api.events[next(iter(stack.api.sessions))]
        if event["type"] != "session.status_running"
    ]
    assert events == turn_events, "every event of the turn stored once, in order"


# --- dispatch reconciliation --------------------------------------------------------------------


def _record(kind: str, key: str) -> DispatchRecord:
    return DispatchRecord.model_validate(
        {
            "kind": kind,
            "idempotency_key": key,
            "expected_generation": 1,
            "instruction_digest": "sha256:" + "a" * 64,
            "owner_ref": "worker-a",
            "owner_epoch": 1,
            "intended_at": datetime.now(UTC),
        }
    )


async def test_a_lost_create_is_found_by_its_dispatch_metadata(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    heid, session = await _started(stack)
    found = await stack.harness.reconcile_dispatch(
        _record("create", f"{heid}:1:turn:1"), session=None
    )
    assert (found.outcome, found.native_ref) == ("found", session.native_session_ref)
    other = await stack.harness.reconcile_dispatch(
        _record("create", f"{heid}:2:turn:1"), session=None
    )
    assert other.outcome == "unknown", "absence from a listing is not authoritative"


async def test_a_lost_first_send_is_the_sessions_only_message(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    heid, session = await _started(stack)
    turn = await _sent(stack, session)
    successor = managed_harness(stack.api, stack.pack)
    successor.stage(heid, stack.operation)
    found = await successor.reconcile_dispatch(_record("send", f"{heid}:1:turn:1"), session=session)
    assert (found.outcome, found.native_ref) == ("found", turn.native_turn_ref)


# --- cancel, status and the budget gate ---------------------------------------------------------


async def test_cancel_interrupts_and_the_turn_closes_cancelled(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path, scripts=("held",))
    _heid, session = await _started(stack)
    turn = await _sent(stack, session)
    receipt = await stack.harness.cancel_turn(
        CancelTurnRequest(**_fields(stack.operation, "cancel"), turn=turn, reason="operator")
    )
    assert receipt.acknowledged and not receipt.already_terminal
    assert receipt.native_status == "idle" and stack.api.interrupts() == 1
    status = await stack.harness.status(
        StatusRequest(**_fields(stack.operation, "status"), session=session, turn=turn)
    )
    assert status.terminal and status.status == "end_turn"
    closing = [
        frame
        async for frame in stack.harness.observe(_observe(stack, turn, "observe"))
        if frame.terminal
    ]
    facts = stack.harness.closing_facts(turn, closing[-1])
    assert facts.native_status == "cancelled"
    again = await stack.harness.cancel_turn(
        CancelTurnRequest(**_fields(stack.operation, "cancel"), turn=turn, reason="operator")
    )
    assert again.already_terminal and stack.api.interrupts() == 1, "a closed turn is not resent"


async def test_the_budget_gate_pauses_before_the_next_model_request_and_resumes(
    tmp_path: Path,
) -> None:
    stack = managed_stack(tmp_path)
    heid, session = await _started(stack)
    assert await stack.harness.hold_budget(heid, True) == 1, "one cent above the spend"
    turn = await _sent(stack, session)
    session_id = session.native_session_ref or ""
    assert stack.api.sessions[session_id]["budget"]["max_list_cost"]["amount"] == "1"
    status = await stack.harness.status(
        StatusRequest(**_fields(stack.operation, "status"), session=session, turn=turn)
    )
    assert (status.status, status.terminal, status.idle) == ("budget_reached", False, False)
    assert (await _sent(stack, session, 2)).status == "busy", "nothing new starts at the cap"
    assert await stack.harness.hold_budget(heid, False) == MAX_LIST_COST
    closing = [
        frame
        async for frame in stack.harness.observe(_observe(stack, turn, "observe"))
        if frame.terminal
    ]
    assert stack.harness.closing_facts(turn, closing[-1]).native_status == "finished"


async def test_usage_is_unknown_until_the_turn_closes(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path, scripts=("held",))
    _heid, session = await _started(stack)
    turn = await _sent(stack, session)
    report = await stack.harness.usage(
        UsageRequest(**_fields(stack.operation, "usage"), session=session, turn=turn)
    )
    assert report.disposition == "unknown" and report.total_tokens == 0


# --- end and deletion ---------------------------------------------------------------------------


async def test_end_interrupts_a_running_session_before_archiving_it(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path, scripts=("held",))
    _heid, session = await _started(stack)
    await _sent(stack, session)
    receipt = await stack.harness.end_session(
        EndSessionRequest(**_fields(stack.operation, "end"), session=session, reason="cancelled")
    )
    assert receipt.released and len(receipt.artifact_refs) == 1
    assert stack.api.interrupts() == 1 and stack.api.archived() == [session.native_session_ref]
    assert len(stack.deletions.orders) == 1


async def test_the_deleter_deletes_once_and_then_finds_the_session_absent(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    _heid, session = await _started(stack)
    deleter = ManagedSessionDeleter(stack.api.client())
    session_id = session.native_session_ref or ""
    assert await deleter.delete_session(session_id) == "deleted"
    assert await deleter.delete_session(session_id) == "absent"
    assert session_id not in stack.api.sessions


async def test_session_requests_carry_the_beta_header_and_bracketed_filters(
    tmp_path: Path,
) -> None:
    stack = managed_stack(tmp_path)
    lanes = _lanes(stack)
    identity = _identity(stack.operation)
    await asyncio.wait_for(
        lanes.service.turn(
            _turn_request(stack.operation),
            RecordingSignals(lanes.frames, identity.harness_execution_id),
        ),
        WITHIN_S,
    )
    session_requests = [r for r in stack.api.requests if r.path.startswith("/v1/sessions")]
    assert session_requests and all(
        r.beta_query and r.headers.get("anthropic-beta") == "managed-agents-2026-04-01"
        for r in session_requests
    )
    assert stack.api.stream_opens >= 1
    assert isinstance(stack.harness, ClaudeManagedHarness)


@pytest.mark.parametrize("with_input", [False, True])
async def test_instruction_only_turn_has_nonempty_trigger(tmp_path: Path, with_input: bool):
    from mission_control.domain.execution.contracts import PromptTrustClass

    stack = managed_stack(tmp_path)
    authored = stack.operation.prompt_segments[0].model_copy(
        update={"trust_class": PromptTrustClass.AUTHORED_INSTRUCTION}
    )
    segments = (authored,)
    if with_input:
        segments += (authored.model_copy(update={"trust_class": PromptTrustClass.ADMITTED_INPUT}),)
    stack.operation = stack.operation.model_copy(update={"prompt_segments": segments})
    _heid, session = await _started(stack)
    await _sent(stack, session)
    created = stack.api.sessions[session.native_session_ref]
    assert authored.content in created["agent"]["system"]
    assert stack.api.messages()[-1][1] == (
        authored.content.strip() if with_input else "Execute the admitted operation instructions."
    )


async def test_finite_history_replay_is_bounded_and_sends_no_native_messages(tmp_path, monkeypatch):
    from mission_control.domain.execution.history_reconciliation import (
        HistoryReplayComplete,
        HistoryReplayIncomplete,
    )
    from mission_control.domain.execution.lanes import ObserveRequest

    stack = managed_stack(tmp_path)
    _, session = await _started(stack)
    turn = await _sent(stack, session)
    request = ObserveRequest(**_fields(stack.operation, "history"), turn=turn)
    before = len(stack.api.requests)
    replay = [frame async for frame in stack.harness.reconcile_history(request)]
    assert isinstance(replay[-1], HistoryReplayComplete)
    assert any(getattr(frame, "terminal", False) for frame in replay)
    assert all(record.method == "GET" for record in stack.api.requests[before:])
    monkeypatch.setattr("mission_control.adapters.anthropic_managed.harness.MAX_HISTORY_FRAMES", 1)
    with pytest.raises(HistoryReplayIncomplete):
        _ = [frame async for frame in stack.harness.reconcile_history(request)]


async def test_legacy_hold_helper_refuses_unknown_cost(tmp_path):
    stack = managed_stack(tmp_path)
    heid, session = await _started(stack)
    stack.api.sessions[session.native_session_ref]["usage"] = {}
    with pytest.raises(ValueError, match="USD"):
        await stack.harness.hold_budget(heid, True)

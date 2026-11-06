"""Cross-provider control: the `codex` lane's time travel (`adapters/codex/time_travel.py`).

`read_as_of` at R1 from the persisted frames and at R3 from `thread/read` of a thread the
harness still holds; `seed_fork` through the FIXTURE app-server's `thread/fork` (R3 native at a
turn boundary, R3 reconstructed inside a turn, R1 transcript without a live thread), idempotent
per fork request; a derived harness whose `prepare`/`start` honour the `LaneSeedHead`
(`thread/resume` of the fork, else a fresh thread carrying the hydration preamble ahead of its
first turn); `collect_points` re-deriving the settlement's fold. No Codex runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.codex import cognition_points as points
from mission_control.adapters.codex.continuation import WORKSPACE_SNAPSHOT_PREFIX
from mission_control.adapters.codex.time_travel import (
    A_DERIVED_THREAD,
    A_HYDRATION_REF,
    A_LAST_TURN,
    A_SEED_HEAD,
    A_SEED_KIND,
    A_SOURCE_THREAD,
    SEED_KIND_THREAD_FORK,
    SEED_KIND_TRANSCRIPT,
    CodexTimeTravel,
    hydration_text,
)
from mission_control.adapters.codex.time_travel import (
    WORKSPACE_SNAPSHOT_PREFIX as TIME_TRAVEL_SNAPSHOT_PREFIX,
)
from mission_control.application.execution.harness.points import TurnPointsRequest
from mission_control.application.execution.harness.time_travel import (
    SEED_HEAD_MESSAGE_COUNT,
    ForkSeedRequest,
    ScopedTimeTravelLane,
    TimeTravelLane,
    TimeTravelRegistry,
    TimeTravelUnsupported,
)
from mission_control.domain.execution.cognition_points import (
    CognitionCoordinate,
    CognitionPointObservation,
    CognitionPointRecord,
    UnitLocationFacts,
    point_id_for,
)
from mission_control.domain.execution.lane_turns import NativeRefs
from mission_control.domain.execution.lanes import LaneSeedHead, PrepareRequest, StartRequest
from tests.fixtures.lane_turns import SCOPE
from tests.unit.codex.drive import fields, observed, sent, started
from tests.unit.codex.support import CodexStack, codex_operation, codex_stack

UNIT_KEY = "bl-unit-v1:" + "a" * 64
DERIVED_UNIT_KEY = "bl-unit-v1:" + "b" * 64


async def _live_turn(tmp_path: Path, *scripts: str) -> tuple[CodexStack, str, str]:
    """A turn driven directly on the harness: the session stays live afterwards, and the
    observed frames are persisted the way `lane.turn` persists them (the fold reads the store)."""

    stack = codex_stack(tmp_path, *scripts)
    session = await started(stack)
    turn = await sent(stack, session)
    frames = await observed(stack, turn)
    assert frames[-1].terminal
    assert session.native_session_ref is not None and turn.native_turn_ref is not None
    await _persist(stack, frames, session.native_session_ref)
    return stack, session.native_session_ref, turn.native_turn_ref


async def _persist(stack: CodexStack, frames: list[Any], thread: str) -> None:
    from mission_control.application.execution.harness.lane_turns import execution_start
    from mission_control.application.frames.kinds import classify
    from mission_control.application.frames.writer import FrameWriter
    from mission_control.domain.frames.contracts import FrameObservation, LaneProfile

    handle = await stack.lanes.frames.open_execution(
        execution_start(stack.operation, stack.identity, 1, thread)
    )
    writer = FrameWriter(stack.lanes.frames, handle)
    for frame in frames:
        raw_kind = frame.raw_kind or frame.kind
        body = frame.body if frame.body is not None else {}
        await writer.write(
            [
                FrameObservation(
                    provider_key=frame.provider_key,
                    raw_kind=raw_kind,
                    kind=classify(LaneProfile.CODEX, raw_kind, body).kind,
                    body=body,
                    native_turn_ref=frame.native_turn_ref,
                    tool_call_ref=frame.tool_call_ref,
                    native_session_ref=thread,
                    subordinate_ref=frame.subordinate_ref,
                )
            ]
        )


def _points(stack: CodexStack, thread: str, turn: str) -> tuple[CognitionPointObservation, ...]:
    frames = tuple(stack.frames())
    return points.turn_points(
        TurnPointsRequest(
            operation=stack.operation,
            lane_profile="codex",
            harness_execution_id=stack.heid,
            generation=1,
            native=NativeRefs(session_ref=thread, turn_ref=turn),
            turn_no=1,
            frames=frames,
            facts=points.closing_facts_of(frames),
        )
    )


def _record(stack: CodexStack, observation: CognitionPointObservation) -> CognitionPointRecord:
    run_id = stack.operation.identity.run_id
    return CognitionPointRecord(
        point_id=point_id_for(run_id, UNIT_KEY, 1, observation.point.kind, observation.locator),
        coordinate=CognitionCoordinate(
            run_id=run_id,
            unit_key=UNIT_KEY,
            execution_generation=1,
            harness_execution_id=stack.heid,
            turn_no=1,
            point=observation.point,
        ),
        lane_profile="codex",
        location=UnitLocationFacts(
            family="stage_graph", node_key="implement", iteration=1, cycle=1
        ),
        parent_locator=observation.parent_locator,
        ordinal=observation.ordinal,
        source=observation.source,
        roles=observation.roles,
        channel_facts=observation.channel_facts,
        usage_delta=observation.usage_delta,
        seedable=observation.seedable,
        written_by="adapter",
        recorded_at=datetime.now(UTC),
    )


def _lane(stack: CodexStack, *, provider: bool = True) -> CodexTimeTravel:
    return CodexTimeTravel(
        stack.lanes.frames,
        stack.artifacts,
        provider=stack.harness if provider else None,
        request_scope=SCOPE,
    )


def _seed_request(
    stack: CodexStack, record: CognitionPointRecord, **changes: Any
) -> ForkSeedRequest:
    values: dict[str, Any] = {
        "source": record,
        "derived_run_id": "run-forked",
        "derived_unit_key": DERIVED_UNIT_KEY,
        "derived_namespace": "forked-namespace",
        "derived_invocation_id": "inv-forked",
        "fork_request_id": "fork-req-1",
        "request_scope": SCOPE,
    }
    values.update(changes)
    return ForkSeedRequest.model_validate(values)


# --- read_as_of -------------------------------------------------------------------------------


async def test_read_as_of_reconstructs_the_messages_to_the_point_from_frames(
    tmp_path: Path,
) -> None:
    stack, thread, turn = await _live_turn(tmp_path, "turn_full")
    folded = _points(stack, thread, turn)
    tool_point, message_point = folded[1], folded[2]
    lane = _lane(stack, provider=False)
    assert isinstance(lane, TimeTravelLane) and isinstance(lane, ScopedTimeTravelLane)

    at_tool = await lane.read_as_of(_record(stack, tool_point))
    assert at_tool.restore_level == "R1" and at_tool.history == "reconstructed"
    assert [m.role for m in at_tool.state.messages] == ["tool"]
    (tool,) = at_tool.state.messages
    assert tool.name == "commandExecution" and tool.tool_call_id == "item-cmd-1"
    assert tool.text is not None and tool.text.startswith("$ ls outputs")
    assert tool.tool_calls[0].arguments == {"command": "ls outputs"}
    assert at_tool.usage_to_point == {}

    at_message = await lane.read_as_of(_record(stack, message_point))
    assert [m.role for m in at_message.state.messages] == ["tool", "assistant"]
    assert at_message.state.messages[1].text == "Wrote outputs/report.md as asked."
    assert at_message.state.messages[1].text_digest is not None
    assert at_message.state.channels["thread_id"] == thread
    assert at_message.state.channels["turn_id"] == turn
    assert at_message.state.channels["item_id"] == "item-msg-1"
    assert at_message.state.step == message_point.ordinal
    assert "secret_values_unknown_at_read: pattern redaction only" in at_message.state.withheld
    result = await lane.read_as_of(_record(stack, folded[-1]))
    assert result.usage_to_point == {"tokens.input": 120, "tokens.output": 40, "tokens.total": 160}


async def test_read_as_of_reaches_r3_from_the_live_thread_history(tmp_path: Path) -> None:
    stack, thread, turn = await _live_turn(tmp_path, "turn_full")
    folded = _points(stack, thread, turn)
    lane = _lane(stack)
    state = await lane.read_as_of(_record(stack, folded[2]))
    assert state.restore_level == "R3" and state.history == "native"
    # `thread/read` history holds the user message the live stream never itemised.
    assert [m.role for m in state.state.messages] == ["user", "tool", "assistant"]
    assert state.state.messages[-1].id == "item-msg-1"
    methods = [method for method, _params in stack.launcher.server.records]
    assert "thread/read" in methods


async def test_read_as_of_adds_the_turns_workspace_snapshot_files_at_r2(tmp_path: Path) -> None:
    stack, thread, turn = await _live_turn(tmp_path, "turn_full")
    assert TIME_TRAVEL_SNAPSHOT_PREFIX == WORKSPACE_SNAPSHOT_PREFIX
    manifest_ref = await stack.artifacts.stage(
        request_scope=SCOPE,
        name="codex-local/continuation/run/workspace-snapshot.json",
        content=(
            b'{"manifest": {"/outputs/report.md": "sha256:' + b"1" * 64 + b'"}, '
            b'"durable_refs": {"/outputs/report.md": "obj#sha256:' + b"1" * 64 + b':17"}, '
            b'"total_bytes": 17}'
        ),
        media_type="application/json",
    )
    folded = _points(stack, thread, turn)
    record = _record(stack, folded[-1]).model_copy(
        update={"workspace_checkpoint_ref": f"{WORKSPACE_SNAPSHOT_PREFIX}{manifest_ref}"}
    )
    state = await _lane(stack, provider=False).read_as_of(record)
    assert state.restore_level == "R2"
    (file,) = state.state.files
    assert file.path == "/outputs/report.md" and file.size_bytes == 17 and file.source == "closure"
    assert state.state.channels["workspace_snapshot_ref"].startswith(WORKSPACE_SNAPSHOT_PREFIX)


async def test_an_unscoped_lane_refuses_and_a_scoped_binding_reads(tmp_path: Path) -> None:
    stack, thread, turn = await _live_turn(tmp_path, "turn_full")
    unscoped = CodexTimeTravel(stack.lanes.frames, stack.artifacts, provider=stack.harness)
    record = _record(stack, _points(stack, thread, turn)[-1])
    with pytest.raises(TimeTravelUnsupported, match="request_scope_required"):
        await unscoped.read_as_of(record)
    registry = TimeTravelRegistry().register_all([unscoped])
    scoped = registry.lane("codex", request_scope=SCOPE)
    assert (await scoped.read_as_of(record)).restore_level == "R3"


# --- seed_fork --------------------------------------------------------------------------------


async def test_a_turn_boundary_point_forks_the_thread_natively_and_is_idempotent(
    tmp_path: Path,
) -> None:
    stack, thread, turn = await _live_turn(tmp_path, "turn_full")
    result_point = _points(stack, thread, turn)[-1]
    lane = _lane(stack)
    request = _seed_request(stack, _record(stack, result_point), message="Now add tests.")

    receipt = await lane.seed_fork(request)

    assert receipt.restore_level == "R3" and receipt.history == "native"
    artifacts = receipt.native_artifacts
    assert artifacts[A_SEED_KIND] == SEED_KIND_THREAD_FORK
    assert artifacts[A_SOURCE_THREAD] == thread and artifacts[A_LAST_TURN] == turn
    derived_thread = artifacts[A_DERIVED_THREAD]
    assert derived_thread != thread
    assert receipt.derived.point.locator == f"{derived_thread}#fork-seed:fork-req-1"
    assert receipt.derived.run_id == "run-forked" and receipt.derived.execution_generation == 1
    assert (
        artifacts[A_SEED_HEAD] == "injected_message" and artifacts[SEED_HEAD_MESSAGE_COUNT] == "1"
    )
    preamble = stack.artifacts.stored[artifacts[A_HYDRATION_REF]].decode("utf-8")
    assert "# Injected message" in preamble and "Now add tests." in preamble
    assert "# Forked session history" in preamble and "$ ls" not in preamble, (
        "a native fork reconstructs no steps"
    )
    server = stack.launcher.server
    (fork,) = server.forks
    assert (
        fork["threadId"] == thread and fork["lastTurnId"] == turn and fork["excludeTurns"] is True
    )
    assert server.disk.threads[derived_thread]["forkedFromId"] == thread
    assert [t["id"] for t in server.disk.threads[derived_thread]["turns"]] == [turn]
    # The source thread is untouched; a repeat with the same fork request forks nothing more.
    assert [t["id"] for t in server.disk.threads[thread]["turns"]] == [turn]
    again = await lane.seed_fork(request)
    assert again == receipt and len(server.forks) == 1
    assert (await lane.for_scope(SCOPE).seed_fork(request)) == receipt


async def test_a_point_inside_the_first_turn_seeds_a_reconstructed_transcript(
    tmp_path: Path,
) -> None:
    stack, thread, turn = await _live_turn(tmp_path, "turn_full")
    tool_point = _points(stack, thread, turn)[1]
    receipt = await _lane(stack).seed_fork(_seed_request(stack, _record(stack, tool_point)))
    assert receipt.restore_level == "R1" and receipt.history == "reconstructed"
    artifacts = receipt.native_artifacts
    assert artifacts[A_SEED_KIND] == SEED_KIND_TRANSCRIPT and A_DERIVED_THREAD not in artifacts
    assert receipt.derived.point.locator == "seed:fork-req-1#fork-seed:fork-req-1"
    assert receipt.copied_checkpoints == 1 and artifacts[SEED_HEAD_MESSAGE_COUNT] == "1"
    preamble = stack.artifacts.stored[artifacts[A_HYDRATION_REF]].decode("utf-8")
    assert "$ ls outputs" in preamble and "report.md" in preamble
    assert "Wrote outputs/report.md" not in preamble, "nothing after the point is seeded"
    assert stack.launcher.server.forks == [], "no previous turn to fork through"


async def test_a_point_inside_a_later_turn_forks_through_the_previous_turn(tmp_path: Path) -> None:
    stack = codex_stack(tmp_path, "turn_full", "turn_steer")
    session = await started(stack)
    first = await sent(stack, session, key="turn:1", turn_no=1)
    first_frames = await observed(stack, first)
    second = await sent(stack, session, key="turn:2", turn_no=2)
    server = stack.launcher.server
    import asyncio

    await asyncio.wait_for(server.held.wait(), timeout=5)
    server.steer_received.set()
    second_frames = await observed(stack, second)
    await _persist(stack, [*first_frames, *second_frames], session.native_session_ref or "")
    assert session.native_session_ref and first.native_turn_ref and second.native_turn_ref
    frames = tuple(stack.frames())
    whole = points.generation_points(
        frames, harness_execution_id=stack.heid, generation=1, facts=points.closing_facts_of(frames)
    )
    assert points.turn_order(frames) == (first.native_turn_ref, second.native_turn_ref)
    inside_second = next(
        p
        for p in whole
        if p.native_turn_ref == second.native_turn_ref and "tool_call_ref" in p.channel_facts
    )
    receipt = await _lane(stack).seed_fork(_seed_request(stack, _record(stack, inside_second)))
    assert receipt.restore_level == "R3" and receipt.history == "reconstructed"
    assert receipt.native_artifacts[A_LAST_TURN] == first.native_turn_ref
    (fork,) = server.forks
    assert fork["lastTurnId"] == first.native_turn_ref
    derived = receipt.native_artifacts[A_DERIVED_THREAD]
    assert [t["id"] for t in server.disk.threads[derived]["turns"]] == [first.native_turn_ref]
    preamble = stack.artifacts.stored[receipt.native_artifacts[A_HYDRATION_REF]].decode("utf-8")
    assert "git status" in preamble and "Applied the steering instruction" not in preamble


async def test_without_a_live_thread_the_seed_is_a_transcript(tmp_path: Path) -> None:
    stack, thread, turn = await _live_turn(tmp_path, "turn_full")
    result_point = _points(stack, thread, turn)[-1]
    receipt = await _lane(stack, provider=False).seed_fork(
        _seed_request(stack, _record(stack, result_point))
    )
    assert (
        receipt.restore_level == "R1"
        and receipt.native_artifacts[A_SEED_KIND] == SEED_KIND_TRANSCRIPT
    )
    assert receipt.copied_checkpoints == 2


# --- the derived harness honours the seed -----------------------------------------------------


def _derived_operation() -> Any:
    return codex_operation(
        identity={"run_id": "run-forked", "operation_id": "op-forked", "operation_attempt": 1}
    )


def _seed_head(receipt: Any, record: CognitionPointRecord, message: str | None) -> LaneSeedHead:
    return LaneSeedHead(
        source_run_id=record.coordinate.run_id,
        source_unit_key=record.coordinate.unit_key,
        source_execution_generation=1,
        point_kind=record.coordinate.kind,
        point_locator=record.coordinate.locator,
        point=record.coordinate.point.model_dump(mode="json"),
        restore_level=receipt.restore_level,
        history=receipt.history,
        native_artifacts=dict(receipt.native_artifacts),
        message=message,
        fork_request_id="fork-req-1",
    )


async def _derived_start(
    tmp_path: Path, source: CodexStack, seed: LaneSeedHead
) -> tuple[CodexStack, Any]:
    derived = codex_stack(
        tmp_path / "derived",
        "turn_full",
        launcher=source.launcher,
        operation=_derived_operation(),
        artifacts=source.artifacts,
        inputs=source.artifacts,
    )
    values = fields(derived)
    derived.harness.stage(derived.heid, derived.operation)
    prepared = await derived.harness.prepare(
        PrepareRequest(
            **values,
            run_id=derived.operation.identity.run_id,
            operation_id=derived.operation.identity.operation_id,
            attempt_no=1,
            seed=seed,
        )
    )
    handle = await derived.harness.start(StartRequest(**values, prepared=prepared, seed=seed))
    return derived, handle


async def test_a_forked_thread_seed_is_resumed_by_the_derived_start(tmp_path: Path) -> None:
    stack, thread, turn = await _live_turn(tmp_path / "source", "turn_full")
    record = _record(stack, _points(stack, thread, turn)[-1])
    receipt = await _lane(stack).seed_fork(_seed_request(stack, record, message="Now add tests."))
    derived, handle = await _derived_start(
        tmp_path, stack, _seed_head(receipt, record, "Now add tests.")
    )
    assert handle.native_session_ref == receipt.native_artifacts[A_DERIVED_THREAD]
    assert handle.native_details["seed_restore"] == "R3"
    assert handle.native_details["forked_from"] == thread
    derived_server = derived.launcher.launches[-1].server
    methods = [method for method, _params in derived_server.records]
    assert "thread/resume" in methods and "thread/start" not in methods
    # The first turn carries the injected message ahead of its own text; the second does not.
    first = await sent(derived, handle, key="turn:1", turn_no=1)
    await observed(derived, first)
    (turn_start,) = [p for m, p in derived_server.records if m == "turn/start"]
    text = turn_start["input"][0]["text"]
    assert text.startswith("# Forked session history") and "Now add tests." in text
    assert "Read .mission/context.md" in text or "outputs" in text
    assert [t["id"] for t in derived_server.disk.threads[thread]["turns"]] == [turn], (
        "source untouched"
    )


async def test_a_transcript_seed_starts_a_fresh_thread_with_the_preamble(tmp_path: Path) -> None:
    stack, thread, turn = await _live_turn(tmp_path / "source", "turn_full")
    record = _record(stack, _points(stack, thread, turn)[1])
    receipt = await _lane(stack).seed_fork(_seed_request(stack, record))
    derived, handle = await _derived_start(tmp_path, stack, _seed_head(receipt, record, None))
    assert handle.native_details["seed_restore"] == "R1"
    assert handle.native_session_ref not in {thread, None}
    derived_server = derived.launcher.launches[-1].server
    assert "thread/resume" not in [m for m, _p in derived_server.records]
    first = await sent(derived, handle, key="turn:1", turn_no=1)
    await observed(derived, first)
    (turn_start,) = [p for m, p in derived_server.records if m == "turn/start"]
    assert turn_start["input"][0]["text"].startswith("# Forked session history")
    assert "$ ls outputs" in turn_start["input"][0]["text"]


async def test_a_fork_the_server_cannot_resume_falls_back_to_a_fresh_thread(tmp_path: Path) -> None:
    stack, thread, turn = await _live_turn(tmp_path / "source", "turn_full")
    record = _record(stack, _points(stack, thread, turn)[-1])
    receipt = await _lane(stack).seed_fork(_seed_request(stack, record))
    head = _seed_head(receipt, record, None)
    head = head.model_copy(
        update={"native_artifacts": {**head.native_artifacts, A_DERIVED_THREAD: "thr-gone"}}
    )
    _derived, handle = await _derived_start(tmp_path, stack, head)
    assert handle.native_details["seed_restore"] == "R1" and handle.native_session_ref != "thr-gone"


# --- collect_points ---------------------------------------------------------------------------


async def test_collect_points_re_derives_the_settlements_fold(tmp_path: Path) -> None:
    stack, thread, turn = await _live_turn(tmp_path, "turn_full")
    folded = _points(stack, thread, turn)
    observed_again = await _lane(stack).collect_points(
        namespace=stack.heid,
        checkpointer_ref_digest="1",
        source_locator=None,
        result_locator=folded[-1].locator,
    )
    assert [p.locator for p in observed_again] == [p.locator for p in folded]
    assert [p.roles for p in observed_again] == [p.roles for p in folded]
    assert [p.usage_delta for p in observed_again] == [p.usage_delta for p in folded]
    with pytest.raises(TimeTravelUnsupported, match="generation_not_numeric"):
        await _lane(stack).collect_points(
            namespace=stack.heid,
            checkpointer_ref_digest="x",
            source_locator=None,
            result_locator="r",
        )


def test_hydration_text_labels_history_and_the_injected_message() -> None:
    text = hydration_text((), message="Do X", source_thread="thr-1")
    assert text.startswith("# Forked session history") and text.rstrip().endswith("Do X")

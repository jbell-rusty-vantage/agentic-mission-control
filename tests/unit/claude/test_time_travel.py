"""Cross-provider control: the `claude_agent_sdk` lane's time travel
(`adapters/claude/time_travel.py`).

`read_as_of` at R1 from the persisted frames and at R3 from the state-root transcript mirror
the harness still holds; `seed_fork` truncating that mirror at the point under a new,
deterministic session id (R3 reconstructed; R1 rebuilt from frames without a mirror),
idempotent per fork request; a derived harness whose `prepare` writes the staged transcript
into its own state root and whose `start` resumes it (the FIXTURE client refuses a resume the
store never mirrored, as the CLI does), the injected message ahead of the first turn; the
fresh-session fallback; `collect_points` re-deriving the settlement's fold. No Claude Code runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.claude import cognition_points as points
from mission_control.adapters.claude.continuation import WORKSPACE_SNAPSHOT_PREFIX
from mission_control.adapters.claude.harness import turn_reference
from mission_control.adapters.claude.time_travel import (
    A_DERIVED_SESSION,
    A_SEED_HEAD,
    A_SEED_KIND,
    A_SOURCE_SESSION,
    A_TRANSCRIPT_ENTRIES,
    A_TRANSCRIPT_REF,
    A_TRUNCATED_AT,
    A_TRUNCATION,
    SEED_KIND_FRAMES,
    SEED_KIND_MIRROR,
    ClaudeTimeTravel,
    derived_session_id,
    entries_from_frames,
    truncate_entries,
)
from mission_control.adapters.claude.time_travel import (
    WORKSPACE_SNAPSHOT_PREFIX as TIME_TRAVEL_SNAPSHOT_PREFIX,
)
from mission_control.adapters.claude.workspace import StateRootSessionStore
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
from mission_control.domain.execution.lanes import (
    LaneSeedHead,
    ObserveRequest,
    PrepareRequest,
    SendTurnRequest,
    SessionHandle,
    StartRequest,
    TurnHandle,
)
from tests.fixtures.lane_turns import SCOPE
from tests.unit.claude.fixtures import SESSION_ID, ClaudeStack, claude_operation, claude_stack
from tests.unit.claude.test_claude_harness import _fields, _identity
from tests.unit.codex.support import MemoryArtifacts

UNIT_KEY = "bl-unit-v1:" + "a" * 64
DERIVED_UNIT_KEY = "bl-unit-v1:" + "b" * 64


# --- a live turn whose frames are persisted ------------------------------------------------


async def _started(stack: ClaudeStack, seed: LaneSeedHead | None = None) -> SessionHandle:
    harness = stack.harness
    heid = str(_identity(stack).harness_execution_id)
    harness.stage(heid, stack.operation)
    values = _fields(stack, "test")
    prepared = await harness.prepare(
        PrepareRequest(
            **values,
            run_id=stack.operation.identity.run_id,
            operation_id=stack.operation.identity.operation_id,
            attempt_no=1,
            seed=seed,
        )
    )
    return await harness.start(StartRequest(**values, prepared=prepared, seed=seed))


async def _sent(stack: ClaudeStack, session: SessionHandle, key: str = "turn:1") -> TurnHandle:
    return await stack.harness.send_turn(
        SendTurnRequest(
            **_fields(stack, key),
            session=session,
            turn_no=1,
            instruction_ref=f"operation:{stack.operation.identity.semantic_key}:{key}",
        )
    )


async def _observed(stack: ClaudeStack, turn: TurnHandle) -> list[Any]:
    frames: list[Any] = []
    async for frame in stack.harness.observe(
        ObserveRequest(**_fields(stack, "observe"), turn=turn, max_frames=500)
    ):
        frames.append(frame)
        if frame.terminal:
            break
    return frames


async def _persist(stack: ClaudeStack, frames: list[Any]) -> None:
    from mission_control.application.execution.harness.lane_turns import execution_start
    from mission_control.application.frames.kinds import classify
    from mission_control.application.frames.writer import FrameWriter
    from mission_control.domain.frames.contracts import FrameObservation, LaneProfile

    identity = _identity(stack)
    handle = await stack.frames.open_execution(
        execution_start(stack.operation, identity, 1, SESSION_ID)
    )
    writer = FrameWriter(stack.frames, handle)
    for frame in frames:
        raw_kind = frame.raw_kind or frame.kind
        body = frame.body if frame.body is not None else {}
        await writer.write(
            [
                FrameObservation(
                    provider_key=frame.provider_key,
                    raw_kind=raw_kind,
                    kind=classify(LaneProfile.CLAUDE_AGENT_SDK, raw_kind, body).kind,
                    body=body,
                    native_turn_ref=frame.native_turn_ref,
                    tool_call_ref=frame.tool_call_ref,
                    native_session_ref=SESSION_ID,
                    subordinate_ref=frame.subordinate_ref,
                )
            ]
        )


async def _live_turn(tmp_path: Path, script: str = "full_run") -> tuple[ClaudeStack, str]:
    stack = claude_stack(tmp_path, script, inputs=MemoryArtifacts())
    session = await _started(stack)
    turn = await _sent(stack, session)
    frames = await _observed(stack, turn)
    assert frames[-1].terminal and turn.native_turn_ref is not None
    await _persist(stack, frames)
    return stack, turn.native_turn_ref


def _frames(stack: ClaudeStack) -> list[Any]:
    execution = stack.frames._executions[_identity(stack).harness_execution_id]
    return sorted(execution.frames.values(), key=lambda frame: frame.arrival_ordinal)


def _points(stack: ClaudeStack, turn: str) -> tuple[CognitionPointObservation, ...]:
    frames = tuple(_frames(stack))
    return points.turn_points(
        TurnPointsRequest(
            operation=stack.operation,
            lane_profile="claude_agent_sdk",
            harness_execution_id=str(_identity(stack).harness_execution_id),
            generation=1,
            native=NativeRefs(session_ref=SESSION_ID, turn_ref=turn),
            turn_no=1,
            frames=frames,
            facts=points.closing_facts_of(frames),
        )
    )


def _record(stack: ClaudeStack, observation: CognitionPointObservation) -> CognitionPointRecord:
    run_id = stack.operation.identity.run_id
    heid = str(_identity(stack).harness_execution_id)
    return CognitionPointRecord(
        point_id=point_id_for(run_id, UNIT_KEY, 1, observation.point.kind, observation.locator),
        coordinate=CognitionCoordinate(
            run_id=run_id,
            unit_key=UNIT_KEY,
            execution_generation=1,
            harness_execution_id=heid,
            turn_no=1,
            point=observation.point,
        ),
        lane_profile="claude_agent_sdk",
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


def _store(stack: ClaudeStack) -> MemoryArtifacts:
    store = stack.harness._inputs  # the stack's shared custody (FIXTURE)
    assert isinstance(store, MemoryArtifacts)
    return store


def _lane(stack: ClaudeStack, *, transcripts: bool = True) -> ClaudeTimeTravel:
    return ClaudeTimeTravel(
        stack.frames,
        _store(stack),
        transcripts=stack.harness if transcripts else None,
        request_scope=SCOPE,
    )


def _seed_request(
    stack: ClaudeStack, record: CognitionPointRecord, **changes: Any
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
    stack, turn = await _live_turn(tmp_path)
    folded = _points(stack, turn)
    lane = _lane(stack, transcripts=False)
    assert isinstance(lane, TimeTravelLane) and isinstance(lane, ScopedTimeTravelLane)

    at_first = await lane.read_as_of(_record(stack, folded[0]))
    assert at_first.restore_level == "R1" and at_first.history == "reconstructed"
    (assistant,) = at_first.state.messages
    assert assistant.role == "assistant" and assistant.id == "a-0001"
    assert assistant.text == "Listing the inputs first."
    assert [call.name for call in assistant.tool_calls] == ["Bash"]
    assert assistant.tool_calls[0].arguments == {"command": "ls inputs"}
    assert assistant.usage == {"tokens.input": 120, "tokens.output": 9, "tokens.total": 129}
    assert at_first.usage_to_point == {"tokens.input": 120, "tokens.output": 9, "tokens.total": 129}

    at_tool = await lane.read_as_of(_record(stack, folded[1]))
    assert [m.role for m in at_tool.state.messages] == ["assistant", "tool"]
    tool = at_tool.state.messages[1]
    assert tool.tool_call_id == "toolu_bash_01" and tool.text == "sources/\n"
    assert at_tool.state.channels["session_id"] == SESSION_ID
    assert at_tool.state.channels["turn_uuid"] == turn
    assert at_tool.state.channels["step_ref"] == "u-0002:0:user.tool_result"
    assert at_tool.state.channels["message_uuid"] == "u-0002"
    result = await lane.read_as_of(_record(stack, folded[-1]))
    assert [m.role for m in result.state.messages] == [
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]
    assert result.usage_to_point["tokens.total"] == 3 * 129
    assert "secret_values_unknown_at_read: pattern redaction only" in result.state.withheld


async def test_read_as_of_reaches_r3_from_the_transcript_mirror(tmp_path: Path) -> None:
    stack, turn = await _live_turn(tmp_path)
    folded = _points(stack, turn)
    mirrored = await stack.harness.transcript_entries(SESSION_ID)
    assert mirrored is not None and [e["uuid"] for e in mirrored if e["type"] != "summary"] == [
        "a-0001",
        "u-0002",
        "a-0003",
        "u-0004",
        "a-0005",
    ]
    state = await _lane(stack).read_as_of(_record(stack, folded[2]))
    assert state.restore_level == "R3" and state.history == "native"
    assert [m.role for m in state.state.messages] == ["assistant", "tool", "assistant"]
    assert state.state.messages[-1].id == "a-0003"
    assert state.state.messages[-1].text == "Writing the report."
    # A point the mirror does not hold (the result frame) falls back to the frames.
    result = await _lane(stack).read_as_of(_record(stack, folded[-1]))
    assert result.restore_level == "R1"
    assert any("does not hold" in note for note in result.state.withheld)


async def test_read_as_of_adds_the_turns_workspace_snapshot_files_at_r2(tmp_path: Path) -> None:
    stack, turn = await _live_turn(tmp_path)
    assert TIME_TRAVEL_SNAPSHOT_PREFIX == WORKSPACE_SNAPSHOT_PREFIX
    manifest_ref = await _store(stack).stage(
        request_scope=SCOPE,
        name="claude-agent-sdk/continuation/run/workspace-snapshot.json",
        content=(
            b'{"manifest": {"/outputs/report.md": "sha256:' + b"1" * 64 + b'"}, '
            b'"durable_refs": {"/outputs/report.md": "obj#sha256:' + b"1" * 64 + b':9"}, '
            b'"total_bytes": 9}'
        ),
        media_type="application/json",
    )
    record = _record(stack, _points(stack, turn)[-1]).model_copy(
        update={"workspace_checkpoint_ref": f"{WORKSPACE_SNAPSHOT_PREFIX}{manifest_ref}"}
    )
    state = await _lane(stack, transcripts=False).read_as_of(record)
    assert state.restore_level == "R2"
    (file,) = state.state.files
    assert file.path == "/outputs/report.md" and file.size_bytes == 9


async def test_an_unscoped_lane_refuses_and_a_scoped_binding_reads(tmp_path: Path) -> None:
    stack, turn = await _live_turn(tmp_path)
    unscoped = ClaudeTimeTravel(stack.frames, _store(stack), transcripts=stack.harness)
    record = _record(stack, _points(stack, turn)[0])
    with pytest.raises(TimeTravelUnsupported, match="request_scope_required"):
        await unscoped.read_as_of(record)
    registry = TimeTravelRegistry().register_all([unscoped])
    scoped = registry.lane("claude_agent_sdk", request_scope=SCOPE)
    assert (await scoped.read_as_of(record)).restore_level == "R3"


# --- seed_fork --------------------------------------------------------------------------------


async def test_seed_fork_truncates_the_mirror_under_a_new_session_id_and_is_idempotent(
    tmp_path: Path,
) -> None:
    stack, turn = await _live_turn(tmp_path)
    folded = _points(stack, turn)
    lane = _lane(stack)
    request = _seed_request(stack, _record(stack, folded[2]), message="Now add tests.")

    receipt = await lane.seed_fork(request)

    assert receipt.restore_level == "R3" and receipt.history == "reconstructed"
    artifacts = receipt.native_artifacts
    derived = derived_session_id("fork-req-1")
    assert artifacts[A_SEED_KIND] == SEED_KIND_MIRROR and artifacts[A_TRUNCATION] == "exact"
    assert artifacts[A_SOURCE_SESSION] == SESSION_ID and artifacts[A_DERIVED_SESSION] == derived
    assert artifacts[A_TRUNCATED_AT] == "a-0003" and artifacts[A_TRANSCRIPT_ENTRIES] == "4"
    assert (
        artifacts[A_SEED_HEAD] == "injected_message" and artifacts[SEED_HEAD_MESSAGE_COUNT] == "4"
    )
    assert receipt.derived.point.locator == f"{derived}#fork-seed:fork-req-1"
    assert receipt.copied_checkpoints == 4
    lines = _store(stack).stored[artifacts[A_TRANSCRIPT_REF]].decode("utf-8").splitlines()
    entries = [json.loads(line) for line in lines]
    assert [e["uuid"] for e in entries] == ["mirror-init", "a-0001", "u-0002", "a-0003"]
    assert all(e.get("sessionId") in {derived, None} for e in entries)
    assert all(e.get("sessionId") == derived for e in entries if e["type"] != "summary")
    assert "Writing the report." in lines[-1] and "BINDING-OK" not in "".join(lines)
    # The source mirror is untouched; the same request returns the same receipt.
    source = await stack.harness.transcript_entries(SESSION_ID)
    assert source is not None and len(source) == 6
    assert await lane.seed_fork(request) == receipt
    assert await lane.for_scope(SCOPE).seed_fork(request) == receipt
    assert sum(1 for name in _store(stack).stored if derived in name) == 1


async def test_without_a_mirror_the_transcript_is_rebuilt_from_frames(tmp_path: Path) -> None:
    stack, turn = await _live_turn(tmp_path)
    receipt = await _lane(stack, transcripts=False).seed_fork(
        _seed_request(stack, _record(stack, _points(stack, turn)[2]))
    )
    assert receipt.restore_level == "R1" and receipt.history == "reconstructed"
    assert receipt.native_artifacts[A_SEED_KIND] == SEED_KIND_FRAMES
    lines = _store(stack).stored[receipt.native_artifacts[A_TRANSCRIPT_REF]].decode().splitlines()
    entries = [json.loads(line) for line in lines]
    assert [e["uuid"] for e in entries] == ["a-0001", "u-0002", "a-0003"]
    assert all(e["reconstructed_from"] == "frames" for e in entries)
    assert [e.get("parentUuid") for e in entries] == [None, "a-0001", "u-0002"]


def test_truncation_never_guesses_a_later_cut() -> None:
    entries = [{"uuid": "a"}, {"uuid": "b"}, {"uuid": "c"}]
    assert truncate_entries(entries, "b") == [{"uuid": "a"}, {"uuid": "b"}]
    assert truncate_entries(entries, "zzz") is None and truncate_entries(entries, None) is None
    assert entries_from_frames((), session_id="s") == []


# --- the derived harness honours the seed -----------------------------------------------------


def _derived_operation() -> Any:
    from mission_control.domain.execution.contracts import OperationExecutionRequest

    base = claude_operation()
    payload = base.model_dump(mode="python")
    payload["identity"] = {
        "run_id": "run-forked",
        "operation_id": "op-forked",
        "operation_attempt": 1,
    }
    return OperationExecutionRequest.model_validate(payload)


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


async def test_the_derived_start_resumes_the_staged_transcript(tmp_path: Path) -> None:
    stack, turn = await _live_turn(tmp_path / "source")
    record = _record(stack, _points(stack, turn)[2])
    receipt = await _lane(stack).seed_fork(_seed_request(stack, record, message="Now add tests."))
    derived_id = receipt.native_artifacts[A_DERIVED_SESSION]
    derived = claude_stack(
        tmp_path / "derived", "full_run", operation=_derived_operation(), inputs=_store(stack)
    )
    seed = _seed_head(receipt, record, "Now add tests.")

    handle = await _started(derived, seed)

    assert handle.native_session_ref == derived_id
    assert handle.native_details["seed_restore"] == "R3"
    assert handle.native_details["forked_from"] == SESSION_ID
    client = derived.factory.last
    assert client.options.resume == derived_id and client.options.fork_session is False
    # `prepare` wrote the staged transcript into the derived state root under the new id.
    (lease,) = derived.workspace.registry.values()
    store = StateRootSessionStore(Path(lease.path) / ".mission" / "state" / "claude")
    assert store.transcript_present(derived_id)
    (path,) = store.transcript_paths(derived_id)
    written = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    # The staged entries are the file's prefix; the derived client mirrors after them.
    assert [entry["uuid"] for entry in written][:4] == ["mirror-init", "a-0001", "u-0002", "a-0003"]
    # The injected message travels ahead of the first turn's own text, once.
    first = await _sent(derived, handle, key="turn:1")
    await _observed(derived, first)
    (sent,) = client.sent
    assert sent[1].startswith("Now add tests.") and "Read .mission/context.md" in sent[1]
    assert sent[0] == turn_reference(f"{_identity(derived).harness_execution_id}:1:turn:1")
    # The source session was never resumed nor written.
    assert all(c.options.resume != SESSION_ID for c in derived.factory.clients)
    source_entries = await stack.harness.transcript_entries(SESSION_ID)
    assert source_entries is not None and len(source_entries) == 6


async def test_a_seed_without_a_transcript_starts_a_fresh_session(tmp_path: Path) -> None:
    stack, turn = await _live_turn(tmp_path / "source")
    record = _record(stack, _points(stack, turn)[2])
    receipt = await _lane(stack).seed_fork(_seed_request(stack, record, message="Only this."))
    head = _seed_head(receipt, record, "Only this.")
    head = head.model_copy(
        update={
            "native_artifacts": {
                k: v for k, v in head.native_artifacts.items() if k != A_TRANSCRIPT_REF
            }
        }
    )
    derived = claude_stack(
        tmp_path / "derived", "full_run", operation=_derived_operation(), inputs=_store(stack)
    )
    handle = await _started(derived, head)
    assert handle.native_session_ref == SESSION_ID, "the script's own fresh session"
    assert handle.native_details["seed_restore"] == "R1"
    first = await _sent(derived, handle)
    await _observed(derived, first)
    assert derived.factory.last.sent[0][1].startswith("Only this.")


async def test_a_resume_the_cli_refuses_falls_back_to_a_fresh_session(tmp_path: Path) -> None:
    """The FIXTURE refuses `resume` of a session the store never mirrored, as the CLI exits
    non-zero without a transcript; the derived start then records R1."""

    stack, turn = await _live_turn(tmp_path / "source")
    record = _record(stack, _points(stack, turn)[2])
    receipt = await _lane(stack).seed_fork(_seed_request(stack, record))
    head = _seed_head(receipt, record, None)
    derived = claude_stack(
        tmp_path / "derived", "full_run", operation=_derived_operation(), inputs=None
    )
    handle = await _started(derived, head)
    assert handle.native_details["seed_restore"] == "R1"
    assert handle.native_session_ref == SESSION_ID
    assert len(derived.factory.clients) == 1, "no transcript was written: no resume was tried"


# --- collect_points ---------------------------------------------------------------------------


async def test_collect_points_re_derives_the_settlements_fold(tmp_path: Path) -> None:
    stack, turn = await _live_turn(tmp_path)
    folded = _points(stack, turn)
    observed_again = await _lane(stack).collect_points(
        namespace=str(_identity(stack).harness_execution_id),
        checkpointer_ref_digest="1",
        source_locator=None,
        result_locator=folded[-1].locator,
    )
    assert [p.locator for p in observed_again] == [p.locator for p in folded]
    assert [p.usage_delta for p in observed_again] == [p.usage_delta for p in folded]
    with pytest.raises(TimeTravelUnsupported, match="frames_missing"):
        await _lane(stack).collect_points(
            namespace=str(_identity(stack).harness_execution_id),
            checkpointer_ref_digest="2",
            source_locator=None,
            result_locator="x",
        )

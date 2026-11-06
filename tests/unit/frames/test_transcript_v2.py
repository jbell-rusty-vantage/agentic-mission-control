"""1.4.4 (TRACING-PROPOSAL P3.2, P4.1, P4.2): `mc.transcript_entry.v2`, placement by unit and
point, the grouping levels, the point/unit filters, body states, the projection store port,
and the HTTP, CLI and MCP surfaces of `--by`, `--point` and `--unit`."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from mission_control.application.execution.cognition_points import (
    InMemoryCognitionPointRepository,
)
from mission_control.application.frames.transcript import (
    MissionEventRecord,
    TranscriptService,
    group_entries,
    render_groups_jsonl,
    render_groups_markdown,
)
from mission_control.domain.execution.cognition_points import (
    AttemptFacts,
    CheckpointPoint,
    CognitionCoordinate,
    CognitionPointRecord,
    FrameRange,
    UnitLocationFacts,
    point_id_for,
)
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.frames.transcript import (
    TranscriptEntry,
    TranscriptQuery,
    transcript_json_schema,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.cli import main as cli
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal, _principal_call
from mission_control.interfaces.mcp.transcript_tools import (
    TRANSCRIPT_TOOL,
    ScopedTranscripts,
    register_transcript_tools,
)
from tests.fixtures.provider_frames import (
    FIXTURE_ACTIVATION,
    FIXTURE_HARNESS,
    FRAME_NOW,
    INSTALLATION,
    SCOPE,
    TENANT,
    provider_frame,
)
from tests.fixtures.transcripts import (
    READER,
    RUN_KEY,
    SECRET_VALUE,
    InMemoryMissionEvents,
    StaticFrames,
    transcript_events,
    transcript_frames,
)
from tests.unit.frames.test_transcript_interfaces import _cli_transport, http_app

UNIT = "bl-unit-v1:" + "7c" * 32
OTHER_UNIT = "bl-unit-v1:" + "0f" * 32
ACTIVATION = str(FIXTURE_ACTIVATION)
HARNESS = str(FIXTURE_HARNESS)
CHECKPOINTER = "sha256:" + "c" * 64
ARTIFACT_REF = "frame-body://sha256:" + "d" * 64 + "?bytes=48213&type=application%2Fjson"
LOCATION = UnitLocationFacts(family="stage_graph", node_key="collect", iteration=0, cycle=2)
ATTEMPT = AttemptFacts(
    activity_attempt_observation_id="obs-1",
    temporal_workflow_id="mc:wf:run-transcript-1",
    temporal_run_id="3f3f3f3f",
    temporal_activity_id="op-exec-7",
    activity_attempt=1,
    task_queue="mc-deep-agents-ops",
)


def point(
    locator: str,
    frames: tuple[int, int] | None,
    *,
    roles: tuple[str, ...] = (),
    parent: str | None = None,
    subordinate: str | None = None,
    attempt: AttemptFacts | None = ATTEMPT,
) -> CognitionPointRecord:
    key = QualifiedCheckpointKey(
        checkpointer_ref_digest=CHECKPOINTER,
        thread_id="thread-1",
        checkpoint_ns="tools:call-1" if subordinate else "",
        checkpoint_id=locator,
    )
    return CognitionPointRecord(
        point_id=point_id_for(RUN_KEY, UNIT, 1, "checkpoint", locator),
        coordinate=CognitionCoordinate(
            run_id=RUN_KEY,
            unit_key=UNIT,
            execution_generation=1,
            harness_execution_id=HARNESS,
            point=CheckpointPoint(key=key, subordinate_ref=subordinate),
        ),
        lane_profile="deep_agents",
        location=LOCATION,
        parent_point_id=parent,
        roles=roles,  # type: ignore[arg-type]
        attempt=attempt,
        frames=FrameRange(from_ordinal=frames[0], to_ordinal=frames[1]) if frames else None,
        written_by="adapter",
        recorded_at=FRAME_NOW,
    )


P_INPUT = point("cp-input", (1, 3), roles=("input",))
P_STEP = point("cp-step", (4, 7), roles=("result",), parent=P_INPUT.point_id)
P_CHILD = point(
    "cp-child",
    (9, 9),
    roles=("input", "subagent_root"),
    parent=P_STEP.point_id,
    subordinate="researcher",
)
POINTS = (P_INPUT, P_STEP, P_CHILD)


def point_ref(checkpoint_id: str, relation: str) -> dict[str, Any]:
    return {
        "kind": "checkpoint",
        "thread_id": "thread-1",
        "checkpoint_ns": "",
        "checkpoint_id": checkpoint_id,
        "relation": relation,
    }


def v2_frames() -> list[Any]:
    """The C3 fixture frames plus a subagent frame (9) in the child's range, an oversized
    frame (10) promoted to a `frame-body://` reference, keyed by the root point it followed
    (Deep Agents key shape), and a capped frame (11) nobody promoted."""

    frames = transcript_frames()
    frames.append(
        provider_frame(
            9,
            FrameKind.MESSAGE,
            {"text": "ranking the candidates"},
            subordinate_ref="researcher",
        )
    )
    promoted = provider_frame(10, FrameKind.MESSAGE, {"text": "x" * 40}).model_copy(
        update={
            "provider_key": "thread-1::cp-step:3:0:message",
            "body_bytes": 48_213,
            "body_artifact_ref": ARTIFACT_REF,
        }
    )
    frames.append(promoted)
    capped = provider_frame(11, FrameKind.MESSAGE, {"text": "y" * 40}).model_copy(
        update={"provider_key": "thread-1::cp-step:3:1:message", "body_bytes": 9_000}
    )
    frames.append(capped)
    return frames


def v2_events(frames: list[Any], *, include_expired: bool = False) -> list[MissionEventRecord]:
    """The C3 fixture events stamped the 1.4.4 way (`unit_key`, `activation_id`, `point_ref`
    at the envelope level) plus a family admission event of the unit."""

    events = []
    for record in transcript_events(frames, include_expired=include_expired):
        envelope = dict(record.payload)
        if record.event_type in {"session.turn_started", "tool_call.completed"} or (
            record.event_type == "session.turn_completed"
        ):
            envelope["unit_key"] = UNIT
            envelope["activation_id"] = ACTIVATION
        if record.event_type == "tool_call.completed":
            envelope["point_ref"] = point_ref("cp-step", "after")
        if record.event_type == "session.turn_completed":
            envelope["point_ref"] = point_ref("cp-step", "result")
        events.append(replace(record, payload=envelope))
    last = events[-1]
    events.append(
        MissionEventRecord(
            seq=last.seq + 1,
            event_id="00000000-0000-7000-8000-000000000099",
            event_type="workflow_run.apply_authority_batch",
            recorded_at=last.recorded_at,
            actor_ref="mission-control",
            payload={
                "event_type": "workflow_run.apply_authority_batch",
                "unit_key": UNIT,
                "payload": {
                    "command_id": "stagegraph:mutation-1",
                    "prior_phase": "active",
                    "resulting_phase": "active",
                    "terminal_outcome": None,
                    "authority_batch_digest": "sha256:" + "b" * 64,
                    "action_identity_summary": ["admit_stage_operation"],
                },
            },
        )
    )
    return events


def repository(
    points: tuple[CognitionPointRecord, ...] = POINTS,
) -> InMemoryCognitionPointRepository:
    repo = InMemoryCognitionPointRepository()
    for record in points:
        repo.rows[(SCOPE, record.point_id)] = record
    return repo


def service(
    *,
    points: InMemoryCognitionPointRepository | None = None,
    frames: list[Any] | None = None,
    include_expired: bool = False,
    drop_frames: tuple[int, ...] = (),
    **kw: Any,
) -> TranscriptService:
    frames = frames if frames is not None else v2_frames()
    events = v2_events(frames, include_expired=include_expired)
    kept = [frame for frame in frames if frame.arrival_ordinal not in drop_frames]
    return TranscriptService(
        InMemoryMissionEvents(events),
        StaticFrames(kept),  # type: ignore[arg-type]
        request_scope=SCOPE,
        secret_values=(SECRET_VALUE,),
        points=points,
        **kw,
    )


def by_ordinal(entries: tuple[TranscriptEntry, ...]) -> dict[int, TranscriptEntry]:
    return {
        entry.execution.arrival_ordinal: entry
        for entry in entries
        if not entry.canonical
        and entry.kind != "frame_expired"
        and entry.execution
        and entry.execution.arrival_ordinal
    }


def by_kind(entries: tuple[TranscriptEntry, ...]) -> dict[str, TranscriptEntry]:
    return {entry.kind: entry for entry in entries if entry.canonical}


@pytest.mark.asyncio
async def test_frames_carry_point_and_unit_from_the_points_frame_range() -> None:
    page = await service(points=repository()).materialize(RUN_KEY, actor=READER)
    entries = page.entries
    assert [entry.entry_seq for entry in entries] == list(range(1, len(entries) + 1))
    assert all(entry.schema_version == "mc.transcript_entry.v2" for entry in entries)
    frames = by_ordinal(entries)
    first = frames[2]
    assert first.point_id == P_INPUT.point_id and first.parent_point_id is None
    assert (first.unit_key, first.node_key, first.cycle, first.iteration) == (
        UNIT,
        "collect",
        2,
        0,
    )
    assert first.session_generation is None and first.reused_from is None
    step = frames[5]
    assert step.point_id == P_STEP.point_id and step.parent_point_id == P_INPUT.point_id
    assert step.execution is not None and step.execution.temporal is not None
    assert step.execution.harness_execution_id == HARNESS and step.execution.generation == 1
    assert step.execution.native_turn_ref == "turn-1"
    assert step.execution.temporal.model_dump() == {
        "workflow_id": ATTEMPT.temporal_workflow_id,
        "run_id": ATTEMPT.temporal_run_id,
        "activity_id": ATTEMPT.temporal_activity_id,
        "attempt": 1,
    }
    child = frames[9]
    assert child.point_id == P_CHILD.point_id and child.parent_point_id == P_STEP.point_id
    assert child.subordinate_ref == "researcher"
    # Outside every range and keyed by the fixture, not the recorder: the unit still comes
    # from the activation's events, the location from the unit's points.
    result = frames[8]
    assert result.point_id is None and result.unit_key == UNIT and result.node_key == "collect"
    assert result.cycle == 2
    # Outside every range but keyed by the root point it followed (`after_point_ref`).
    assert frames[10].point_id == P_STEP.point_id and frames[11].point_id == P_STEP.point_id
    # The v1 order (frames by time under the governing event) is unchanged.
    assert [entry.kind for entry in entries[:9]] == [
        "workflow_run.admit",
        "workflow_run.start",
        "session_init",
        "session.turn_started",
        "turn_started",
        "message_delta",
        "tool_call_started",
        "tool_call_completed",
        "tool_call.completed",
    ]


@pytest.mark.asyncio
async def test_events_carry_their_unit_and_resolve_point_ref_to_a_point() -> None:
    page = await service(points=repository()).materialize(RUN_KEY, actor=READER)
    events = by_kind(page.entries)
    admit = events["workflow_run.admit"]
    assert admit.unit_key is None and admit.point_id is None and admit.execution is None
    assert admit.body.state == "inline" and admit.body.media_type == "application/json"
    tool = events["tool_call.completed"]
    assert tool.unit_key == UNIT and tool.activation_id == ACTIVATION
    assert tool.point_id == P_STEP.point_id and tool.parent_point_id == P_INPUT.point_id
    assert tool.refs.point_ref == point_ref("cp-step", "after")
    assert (tool.node_key, tool.cycle, tool.iteration) == ("collect", 2, 0)
    assert tool.execution is not None and tool.execution.temporal is not None
    assert tool.execution.temporal.activity_id == ATTEMPT.temporal_activity_id
    assert tool.execution.arrival_ordinal == 5 and tool.execution.native_turn_ref == "turn-1"
    completed = events["session.turn_completed"]
    assert completed.point_id == P_STEP.point_id and completed.refs.point_ref is not None
    assert completed.refs.point_ref["relation"] == "result"
    admission = events["workflow_run.apply_authority_batch"]
    assert admission.unit_key == UNIT and admission.point_id is None
    assert admission.node_key == "collect" and admission.cycle == 2
    # The started event has no point ref: unit from its envelope, location from the unit.
    started = events["session.turn_started"]
    assert started.point_id is None and started.unit_key == UNIT and started.cycle == 2


@pytest.mark.asyncio
async def test_without_a_point_repository_point_fields_stay_none() -> None:
    page = await service().materialize(RUN_KEY, actor=READER)
    assert all(entry.point_id is None and entry.parent_point_id is None for entry in page.entries)
    assert all(entry.cycle is None for entry in page.entries)
    tool = by_kind(page.entries)["tool_call.completed"]
    assert tool.unit_key == UNIT and tool.refs.point_ref is not None
    assert tool.node_key == "collect", "the v1 node rule (payload, then activation) still holds"
    assert by_ordinal(page.entries)[5].unit_key == UNIT, "unit from the activation's events"


@pytest.mark.asyncio
async def test_by_step_yields_one_group_per_point_with_its_cursors() -> None:
    svc = service(points=repository())
    flat = await svc.materialize(RUN_KEY, actor=READER)
    page = await svc.materialize(RUN_KEY, actor=READER, query=TranscriptQuery(by="step"))
    assert page.entries == flat.entries, "the flat entries contract is kept"
    assert [group.key for group in page.groups] == [
        "-",
        P_INPUT.point_id,
        P_STEP.point_id,
        P_CHILD.point_id,
    ]
    step = next(group for group in page.groups if group.key == P_STEP.point_id)
    expected = [entry.cursor for entry in flat.entries if entry.point_id == P_STEP.point_id]
    assert list(step.entry_cursors) == expected and expected
    assert step.level == "step" and step.point_id == P_STEP.point_id
    assert (step.unit_key, step.node_key, step.cycle, step.iteration) == (UNIT, "collect", 2, 0)
    assert step.facts["child_points"] == [P_CHILD.point_id]
    assert step.facts["events"] == 2 and step.facts["frames"] == len(expected) - 2
    assert "tool_call.completed" in {
        entry.kind for entry in flat.entries if entry.cursor in step.entry_cursors
    }
    unplaced = page.groups[0]
    assert unplaced.point_id is None and unplaced.title == "entries without a point"
    assert sum(len(group.entry_cursors) for group in page.groups) == len(flat.entries)


@pytest.mark.asyncio
async def test_point_and_unit_filters() -> None:
    svc = service(points=repository())
    page = await svc.materialize(
        RUN_KEY, actor=READER, query=TranscriptQuery(point=P_STEP.point_id)
    )
    assert page.entries and all(
        P_STEP.point_id in (entry.point_id, entry.parent_point_id) for entry in page.entries
    )
    assert any(entry.point_id == P_CHILD.point_id for entry in page.entries), "children too"
    assert not any(entry.point_id == P_INPUT.point_id for entry in page.entries)
    unit = await svc.materialize(RUN_KEY, actor=READER, query=TranscriptQuery(unit=UNIT))
    assert unit.entries and all(entry.unit_key == UNIT for entry in unit.entries)
    assert not any(entry.kind == "workflow_run.admit" for entry in unit.entries)
    nobody = await svc.materialize(RUN_KEY, actor=READER, query=TranscriptQuery(unit=OTHER_UNIT))
    assert nobody.entries == ()
    shortcut = await svc.materialize(
        RUN_KEY, actor=READER, query=TranscriptQuery(by="step", point=P_INPUT.point_id)
    )
    # `point` includes the point's children: P_STEP is P_INPUT's child, P_CHILD is not.
    assert [group.key for group in shortcut.groups] == [P_INPUT.point_id, P_STEP.point_id]


@pytest.mark.asyncio
async def test_body_states_inline_excerpt_artifact_expired_and_full_bodies() -> None:
    svc = service(points=repository(), include_expired=True, drop_frames=(3,))
    page = await svc.materialize(RUN_KEY, actor=READER)
    frames = by_ordinal(page.entries)
    assert frames[5].body.state == "inline" and frames[5].body.bytes == len(
        frames[5].body_excerpt.encode("utf-8")  # type: ignore[union-attr]
    )
    assert frames[5].body.media_type == "application/json"
    assert frames[10].body.state == "artifact" and frames[10].body.artifact_ref == ARTIFACT_REF
    assert frames[10].body.bytes == 48_213 and frames[10].refs.artifact_ref == ARTIFACT_REF
    assert frames[11].body.state == "excerpt" and frames[11].body.artifact_ref is None
    expired = [entry for entry in page.entries if entry.kind == "frame_expired"]
    assert expired and all(entry.body.state == "expired" for entry in expired)
    assert all(entry.point_id == P_STEP.point_id for entry in expired if entry.point_id)
    artifact = by_kind(page.entries)["artifact.registered"]
    assert artifact.body.state == "artifact"
    assert artifact.body.artifact_ref == "mc://artifacts/biotech/run-transcript-1/sources.json"
    assert artifact.body.media_type == "application/json"

    class Bodies:
        async def read(self, request_scope: str, actor: ActorContext, artifact_ref: str) -> str:
            assert request_scope == SCOPE and actor is READER
            if artifact_ref.startswith("frame-body://"):
                return "{" + '"text": "' + "x" * 48_000 + f' {SECRET_VALUE}"' + "}"
            raise LookupError(artifact_ref)

    full = await svc.with_artifacts(Bodies()).materialize(RUN_KEY, actor=READER, full=True)
    whole = by_ordinal(full.entries)[10]
    assert whole.body.state == "artifact" and whole.body_excerpt is not None
    assert len(whole.body_excerpt) > 40_000 and SECRET_VALUE not in whole.body_excerpt
    kept = by_kind(full.entries)["artifact.registered"]
    assert kept.body_excerpt == artifact.body_excerpt, "a missing body keeps the excerpt"


@pytest.mark.asyncio
async def test_entry_store_is_read_before_materializing_when_current() -> None:
    materialized = await service(points=repository()).materialize(RUN_KEY, actor=READER)
    stored = tuple(
        entry.model_copy(update={"title": f"stored {entry.title}"})
        for entry in materialized.entries
    )

    class Store:
        def __init__(self, entries: tuple[TranscriptEntry, ...] | None) -> None:
            self.entries = entries
            self.calls: list[tuple[str, str]] = []

        async def current_entries(
            self, request_scope: str, run_key: str
        ) -> tuple[TranscriptEntry, ...] | None:
            self.calls.append((request_scope, run_key))
            return self.entries

        async def projected_entries(
            self, request_scope: str, run_key: str
        ) -> tuple[TranscriptEntry, ...]:
            del request_scope, run_key
            return ()

    current = Store(stored)
    page = await service(entry_store=current).materialize(
        RUN_KEY, actor=READER, query=TranscriptQuery(by="step", point=P_STEP.point_id)
    )
    assert current.calls == [(SCOPE, RUN_KEY)]
    assert page.entries and all(entry.title.startswith("stored ") for entry in page.entries)
    assert [group.key for group in page.groups] == [P_STEP.point_id, P_CHILD.point_id]
    behind = Store(None)
    page = await service(points=repository(), entry_store=behind).materialize(RUN_KEY, actor=READER)
    assert behind.calls == [(SCOPE, RUN_KEY)]
    assert page.entries == materialized.entries, "a projection behind is materialized"
    # The projection source (what the activity persists) is the placed v2 list.
    projected = await service(points=repository()).entries_v2(RUN_KEY)
    assert projected == materialized.entries


@pytest.mark.asyncio
async def test_other_levels_and_group_renderers() -> None:
    svc = service(points=repository())
    page = await svc.materialize(RUN_KEY, actor=READER)
    entries = page.entries
    turn = group_entries(entries, "turn", run_id=RUN_KEY)
    assert [group.key for group in turn] == ["-", f"{HARNESS}:turn-1"]
    assert turn[1].title.startswith("turn turn-1 · execution ")
    attempt = group_entries(entries, "attempt", run_id=RUN_KEY)
    assert [group.key for group in attempt] == ["-", f"{ACTIVATION}:1"]
    stage = group_entries(entries, "stage", run_id=RUN_KEY)
    assert [group.key for group in stage] == ["-", UNIT]
    unit = stage[1]
    assert unit.title == f"stage · collect cycle 2 · unit {UNIT[-12:]}"
    assert unit.facts["admissions"] == [
        {
            "command_id": "stagegraph:mutation-1",
            "prior_phase": "active",
            "resulting_phase": "active",
            "actions": ["admit_stage_operation"],
            "cursor": by_kind(entries)["workflow_run.apply_authority_batch"].cursor,
        }
    ]
    assert unit.facts["points"] == sorted({P_INPUT.point_id, P_STEP.point_id, P_CHILD.point_id})
    assert unit.facts["decisions"] == []
    iteration = group_entries(entries, "iteration", run_id=RUN_KEY)
    assert [group.key for group in iteration] == ["-", "0"]
    mission = group_entries(entries, "mission", run_id=RUN_KEY)
    assert len(mission) == 1 and mission[0].key == RUN_KEY
    assert len(mission[0].entry_cursors) == len(entries)
    grouped = page.model_copy(update={"groups": stage})
    lines = render_groups_jsonl(grouped).splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[1]["key"] == UNIT and len(records[1]["entries"]) == len(unit.entry_cursors)
    assert all(
        line
        == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for line in lines
    )
    markdown = render_groups_markdown(grouped, run_id=RUN_KEY)
    assert markdown.startswith(f"# Transcript · run {RUN_KEY} · by stage")
    assert markdown.count("\n## ") == 2 and "- ✓ " in markdown and "- · " in markdown
    assert SECRET_VALUE not in markdown and SECRET_VALUE not in "".join(lines)


def test_v2_schema_is_exported() -> None:
    schema = transcript_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["schema_version"]["const"] == "mc.transcript_entry.v2"
    for name in (
        "entry_seq",
        "unit_key",
        "cycle",
        "iteration",
        "session_generation",
        "point_id",
        "parent_point_id",
        "reused_from",
        "body",
        "execution",
    ):
        assert name in properties
    assert "iteration_id" not in properties


# --- HTTP, CLI and MCP -----------------------------------------------------------------------


def v2_app(permissions: frozenset[str] = frozenset({"workflow_run.read"})) -> FastAPI:
    app = http_app(permissions)
    app.state.mission_control_transcript_services = {
        (INSTALLATION, "biotech", TENANT): service(points=repository())
    }
    app.dependency_overrides[get_mission_principal] = lambda: MissionPrincipal(
        installation_id=INSTALLATION,
        application_id="biotech",
        tenant_id=TENANT,
        issuer="https://issuer.invalid",
        audiences=frozenset({"authenticated"}),
        actor=ActorContext(actor_id="reader", permissions=permissions),
    )
    return app


PATH = f"/v1/applications/biotech/runs/{RUN_KEY}/transcript"


def test_http_by_point_unit_and_the_point_transcript_route() -> None:
    client = TestClient(v2_app())
    flat = [json.loads(line) for line in client.get(PATH).text.splitlines()]
    assert all(line["schema_version"] == "mc.transcript_entry.v2" for line in flat)
    grouped = client.get(PATH, params={"by": "step"})
    assert grouped.status_code == 200
    lines = [json.loads(line) for line in grouped.text.splitlines()]
    assert [line["key"] for line in lines] == [
        "-",
        P_INPUT.point_id,
        P_STEP.point_id,
        P_CHILD.point_id,
    ]
    assert sum(len(line["entries"]) for line in lines) == len(flat)
    page = client.get(PATH, params={"by": "stage", "unit": UNIT, "format": "json"}).json()
    assert [group["key"] for group in page["groups"]] == [UNIT]
    assert page["groups"][0]["facts"]["admissions"][0]["command_id"] == "stagegraph:mutation-1"
    assert all(entry["unit_key"] == UNIT for entry in page["entries"])
    markdown = client.get(PATH, params={"by": "attempt"}, headers={"Accept": "text/markdown"})
    assert markdown.text.startswith(f"# Transcript · run {RUN_KEY} · by attempt")
    shortcut = client.get(
        f"/v1/applications/biotech/runs/{RUN_KEY}/points/{P_STEP.point_id}/transcript",
        params={"format": "json"},
    )
    assert shortcut.status_code == 200
    body = shortcut.json()
    assert [group["key"] for group in body["groups"]] == [P_STEP.point_id, P_CHILD.point_id]
    assert all(
        P_STEP.point_id in (entry.get("point_id"), entry.get("parent_point_id"))
        for entry in body["entries"]
    )
    assert client.get(PATH, params={"by": "chapter"}).status_code == 422
    assert client.get(PATH.replace(RUN_KEY, "missing"), params={"by": "step"}).status_code == 404
    assert (
        client.get(
            f"/v1/applications/biotech/runs/{RUN_KEY}/points/{P_STEP.point_id}/transcript",
            params={"full": "true"},
        ).status_code
        == 501
    )


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "token")
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION_ID", "biotech")
    monkeypatch.setattr(cli.httpx, "Client", _cli_transport(v2_app()))


def test_cli_by_point_and_unit(cli_env: None, capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    assert cli.main(["run", "transcript", RUN_KEY, "--by", "step", "--point", P_STEP.point_id]) == 0
    lines = [json.loads(line) for line in capsysbinary.readouterr().out.decode().splitlines()]
    assert [line["key"] for line in lines] == [P_STEP.point_id, P_CHILD.point_id]
    assert all("entries" in line for line in lines)
    assert (
        cli.main(["run", "transcript", RUN_KEY, "--by", "stage", "--unit", UNIT, "--format", "md"])
        == 0
    )
    out = capsysbinary.readouterr().out.decode("utf-8")
    assert out.startswith(f"# Transcript · run {RUN_KEY} · by stage") and out.count("\n## ") == 1
    with pytest.raises(SystemExit):
        cli.main(["run", "transcript", RUN_KEY, "--by", "chapter"])


@pytest.mark.asyncio
async def test_mcp_tool_takes_by_point_and_unit() -> None:
    principal = CoordinatorPrincipal(
        actor_id="coordinator",
        tenant_scope=SCOPE,
        roles=frozenset(),
        permissions=frozenset({"workflow.result.read"}),
        request_scope=SCOPE,
    )

    class Principals:
        async def resolve(self, context: Any) -> CoordinatorPrincipal:
            del context
            return principal

    server = FastMCP("transcript-v2-test")
    register_transcript_tools(
        server,
        ScopedTranscripts({SCOPE: service(points=repository())}),
        Principals(),
        call=_principal_call,
    )
    async with Client(server) as client:
        tool = {tool.name: tool for tool in await client.list_tools()}[TRANSCRIPT_TOOL]
        assert {"by", "point", "unit"} <= set(tool.inputSchema["properties"])
        result = await client.call_tool(
            TRANSCRIPT_TOOL,
            {"run_id": RUN_KEY, "format": "json", "by": "step", "point": P_STEP.point_id},
        )
        envelope = result.structured_content
        assert envelope is not None and envelope["ok"] is True
        data = envelope["data"]
        assert data["by"] == "step"
        assert [group["key"] for group in data["groups"]] == [P_STEP.point_id, P_CHILD.point_id]
        assert all(entry["schema_version"] == "mc.transcript_entry.v2" for entry in data["entries"])
        jsonl = await client.call_tool(
            TRANSCRIPT_TOOL, {"run_id": RUN_KEY, "by": "stage", "unit": UNIT}
        )
        content = jsonl.structured_content
        assert content is not None
        lines = str(content["data"]["content"]).splitlines()
        assert len(lines) == 1 and json.loads(lines[0])["key"] == UNIT

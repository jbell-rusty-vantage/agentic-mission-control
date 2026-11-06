"""1.4.4 (tracing Stage 1, WP-TR-3 stream R2): frames by point and the dry-run replay.

An in-memory frame reader, point repository and payload store; a `model_request` frame whose
batch is one promoted system object, one promoted human object, one AI `message` frame and
one `tool_call_completed` frame. The replay reconstructs the batch from those and reproduces
the recorded batch digest (`exact: true`); a tampered object yields `exact: false` with the
first differing message; the HTTP routes and the MCP tools answer the same shapes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.execution.cognition_point_reads import (
    CognitionPointReadService,
    FrameReaderUnavailable,
    PointFramesUnavailable,
)
from mission_control.application.execution.cognition_points import (
    InMemoryCognitionPointRepository,
    compose_batch,
)
from mission_control.application.frames.artifact_bodies import GrantedArtifactBodyReader
from mission_control.application.frames.body_refs import frame_body_ref
from mission_control.application.frames.replay import (
    REPLAY_REPORT_SCHEMA,
    ModelRequestNotFound,
    ReplayDenied,
    ReplayService,
    ReplayUnavailable,
)
from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
)
from mission_control.domain.execution.checkpoint_lineage import cognitive_session_namespace
from mission_control.domain.execution.cognition_points import (
    CheckpointPoint,
    CognitionPointObservation,
)
from mission_control.domain.frames.body import batch_frame_body, frame_body
from mission_control.domain.frames.contracts import FrameKind, ProviderFrame
from mission_control.domain.graph_runtime.identities import (
    QualifiedCheckpointKey,
    RuntimeUnitIdentity,
    StageGraphUnitLocation,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.http.cognition_points import router
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from mission_control.interfaces.mcp.cognition_point_tools import (
    POINT_FRAMES_TOOL,
    REPLAY_TOOL,
    ScopedCognitionPoints,
    register_cognition_point_tools,
)
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal, _principal_call
from tests.fixtures.provider_frames import (
    FIXTURE_HARNESS,
    FIXTURE_RUN,
    INSTALLATION,
    SCOPE,
    TENANT,
    provider_frame,
)

RUN = str(FIXTURE_RUN)
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
DIGEST = "sha256:" + "ab" * 32
READ = frozenset({"workflow_run.read"})
FULL = READ | {"workflow.result.read"}
ACTOR = ActorContext(actor_id="operator", permissions=FULL)
JSON = "application/json"

SYSTEM_BODY: dict[str, Any] = {"type": "system", "id": None, "name": None, "content": "Be brief."}
HUMAN_BODY: dict[str, Any] = {"type": "human", "id": "msg-h1", "name": None, "content": "hi"}
AI_BODY: dict[str, Any] = {
    "type": "ai",
    "id": "msg-ai1",
    "name": None,
    "content": "",
    "tool_calls": [{"id": "call-1", "name": "lookup", "args": {"q": "x"}}],
}
TOOL_BODY: dict[str, Any] = {
    "type": "tool",
    "id": "msg-t1",
    "name": "lookup",
    "content": "found",
    "tool_call_id": "call-1",
    "status": "success",
    "result_digest": "sha256:" + "cd" * 32,
}
BATCH = [SYSTEM_BODY, HUMAN_BODY, AI_BODY, TOOL_BODY]


def stage_unit() -> RuntimeUnitIdentity:
    return RuntimeUnitIdentity(
        request_scope=SCOPE,
        belllabs_run_id=RUN,
        execution_epoch=1,
        family="stage_graph",
        unit_kind="stage_operation",
        semantic_operation_id="stage:review:cycle:0",
        semantic_attempt=1,
        location=StageGraphUnitLocation(
            stage_id="review",
            mapped_instance_id="NO_MAPPED_INSTANCE",
            workflow_cycle_ordinal=0,
            stage_cycle_ordinal=0,
            operation_slot_id="main",
        ),
    )


class FakeFrames:
    """A frame reader over a tuple, scoped like the Postgres repository."""

    def __init__(self, frames: tuple[ProviderFrame, ...]) -> None:
        self.frames = frames

    async def frames_for_execution(
        self,
        request_scope: str,
        harness_execution_id: UUID,
        generation: int,
        *,
        after_ordinal: int = 0,
        closing_only: bool = False,
        limit: int = 1_000,
    ) -> tuple[ProviderFrame, ...]:
        assert request_scope == SCOPE
        rows = sorted(
            (
                frame
                for frame in self.frames
                if frame.harness_execution_id == harness_execution_id
                and frame.generation == generation
                and frame.arrival_ordinal > after_ordinal
                and (frame.closing or not closing_only)
            ),
            key=lambda frame: frame.arrival_ordinal,
        )
        return tuple(rows[:limit])

    async def frames_for_run(
        self, request_scope: str, run_id: UUID, *, closing_only: bool = False, limit: int = 10_000
    ) -> tuple[ProviderFrame, ...]:
        assert request_scope == SCOPE
        return tuple(frame for frame in self.frames if frame.run_id == run_id)

    async def current_generation(self, request_scope: str, harness_execution_id: UUID) -> int:
        return 1


class NoMetadata:
    async def get_by_artifact(self, artifact_id: str) -> None:
        return None


async def promote(payloads: InMemoryArtifactPayloadStore, body: dict[str, Any]) -> str:
    canonical = frame_body(body)
    await payloads.stage(
        artifact_id="frame-body",
        content=canonical.canonical,
        content_digest=canonical.digest,
        media_type=JSON,
    )
    return frame_body_ref(digest=canonical.digest, size_bytes=canonical.body_bytes, media_type=JSON)


def entry(body: dict[str, Any], ref: str | None = None) -> dict[str, Any]:
    canonical = frame_body(body)
    item: dict[str, Any] = {
        "id": body.get("id"),
        "type": body["type"],
        "digest": canonical.digest,
        "bytes": canonical.body_bytes,
    }
    if ref is not None:
        item["ref"] = ref
    return item


def model_request(
    *, system_ref: str, human_ref: str, call_index: int = 0, batch: list[dict[str, Any]] = BATCH
) -> dict[str, Any]:
    whole = batch_frame_body(batch)
    system = entry(SYSTEM_BODY, system_ref)
    return {
        "langgraph": {"step": 3, "node": "model", "checkpoint_ns": ""},
        "model": {"name": "gpt-test", "provider": "scripted", "invocation_params_digest": DIGEST},
        "system": {"digest": system["digest"], "bytes": system["bytes"], "ref": system_ref},
        "messages": [entry(HUMAN_BODY, human_ref), entry(AI_BODY), entry(TOOL_BODY)],
        "tools": [{"name": "lookup", "schema_digest": DIGEST}],
        "tool_choice": None,
        "follow_up": False,
        "batch_digest": whole.digest,
        "batch_bytes": whole.body_bytes,
        "call_index": call_index,
    }


class World:
    """Frames 2..6 are keyed to the point (its range spans those present); 1 and 7 are not."""

    def __init__(self, requests: tuple[dict[str, Any], ...] | None = None) -> None:
        self.payloads = InMemoryArtifactPayloadStore()
        self.points = InMemoryCognitionPointRepository()
        self.reader = GrantedArtifactBodyReader(NoMetadata(), self.payloads, request_scope=SCOPE)
        self.requests = requests
        self.frames: FakeFrames | None = None
        self.point_id = ""

    async def build(self) -> World:
        system_ref = await promote(self.payloads, SYSTEM_BODY)
        human_ref = await promote(self.payloads, HUMAN_BODY)
        requests = self.requests or (model_request(system_ref=system_ref, human_ref=human_ref),)
        rows: list[ProviderFrame] = [
            provider_frame(1, FrameKind.STATUS, {"before": True}),
            provider_frame(3, FrameKind.MESSAGE, AI_BODY, raw_kind="updates.ai_message"),
            provider_frame(
                4,
                FrameKind.TOOL_CALL_COMPLETED,
                TOOL_BODY,
                raw_kind="updates.tool_message",
                tool_call_ref="call-1",
            ),
            provider_frame(7, FrameKind.STATUS, {"after": True}),
        ]
        ordinal = 2
        for request in requests:
            rows.append(
                provider_frame(ordinal, FrameKind.MODEL_REQUEST, request, raw_kind="model.request")
            )
            ordinal = 5 if ordinal == 2 else ordinal + 1
        self.frames = FakeFrames(tuple(rows))
        unit = stage_unit()
        thread = cognitive_session_namespace(unit, 1)
        keys = tuple(frame.provider_key for frame in rows if 2 <= frame.arrival_ordinal <= 6)
        self.points.frame_ordinals = {frame.provider_key: frame.arrival_ordinal for frame in rows}
        observed = CognitionPointObservation(
            point=CheckpointPoint(
                key=QualifiedCheckpointKey(
                    checkpointer_ref_digest=DIGEST,
                    thread_id=thread,
                    checkpoint_id="cp-3",
                    parent_checkpoint_id="cp-2",
                )
            ),
            ordinal=3,
            source="loop",
            roles=("leaf", "result"),
            harness_execution_id=str(FIXTURE_HARNESS),
            frame_keys=keys,
            message_count=4,
        )
        bare = observed.model_copy(
            update={
                "point": CheckpointPoint(
                    key=QualifiedCheckpointKey(
                        checkpointer_ref_digest=DIGEST,
                        thread_id=thread,
                        checkpoint_id="cp-0",
                        parent_checkpoint_id=None,
                    )
                ),
                "ordinal": 0,
                "source": "input",
                "roles": ("input",),
                "frame_keys": (),
            }
        )
        batch = compose_batch(
            (bare, observed),
            unit=unit,
            execution_generation=1,
            lane_profile="deep_agents",
            attempt=None,
            written_by="adapter",
            recorded_at=NOW,
        )
        stored = await self.points.record(
            SCOPE, batch.records, frame_keys=batch.frame_keys, turn_refs=batch.turn_refs
        )
        self.bare_point_id = stored[0].point_id
        self.point_id = stored[1].point_id
        assert stored[1].frames is not None
        last = max(self.points.frame_ordinals[key] for key in keys)
        assert (stored[1].frames.from_ordinal, stored[1].frames.to_ordinal) == (2, last)
        return self

    def service(self, *, frames: bool = True, artifacts: bool = True) -> CognitionPointReadService:
        return CognitionPointReadService(
            self.points,
            request_scope=SCOPE,
            frames=self.frames if frames else None,
            artifacts=self.reader if artifacts else None,
        )


# --- the read service -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frames_for_point_returns_the_range_in_arrival_order() -> None:
    world = await World().build()
    frames = await world.service().frames_for_point(RUN, world.point_id)
    assert [frame.arrival_ordinal for frame in frames] == [2, 3, 4]
    assert frames[0].kind is FrameKind.MODEL_REQUEST
    with pytest.raises(PointFramesUnavailable):
        await world.service().frames_for_point(RUN, world.bare_point_id)
    with pytest.raises(FrameReaderUnavailable):
        await world.service(frames=False).frames_for_point(RUN, world.point_id)


@pytest.mark.asyncio
async def test_replay_reconstructs_the_exact_batch_from_frames_and_objects() -> None:
    world = await World().build()
    report = await ReplayService(world.service()).dry_run(SCOPE, ACTOR, RUN, world.point_id)
    assert report.schema_version == REPLAY_REPORT_SCHEMA
    assert report.exact is True and report.first_difference is None
    assert report.batch_digest_reconstructed == report.batch_digest_recorded
    assert report.batch_digest_recorded == batch_frame_body(BATCH).digest
    assert report.model == "gpt-test" and report.call_index == 0
    assert [(item.type, item.source) for item in report.messages] == [
        ("system", "object"),
        ("human", "object"),
        ("ai", "frame"),
        ("tool", "frame"),
    ]
    assert all(item.reconstructed_digest == item.digest for item in report.messages)
    assert report.messages[2].frame_id is not None and report.messages[1].ref is not None
    # The batch is exactly what the observer digested, in order.
    assert report.batch == [json.loads(frame_body(body).canonical.decode()) for body in BATCH]


@pytest.mark.asyncio
async def test_a_tampered_object_is_not_exact_and_names_the_first_difference() -> None:
    world = World()
    other = await promote(world.payloads, {**HUMAN_BODY, "content": "hi there"})
    system_ref = await promote(world.payloads, SYSTEM_BODY)
    world.requests = (model_request(system_ref=system_ref, human_ref=other),)
    await world.build()
    report = await ReplayService(world.service()).dry_run(SCOPE, ACTOR, RUN, world.point_id)
    assert report.exact is False and report.batch is None
    assert report.batch_digest_reconstructed != report.batch_digest_recorded
    assert report.first_difference is not None
    assert report.first_difference.index == 1 and report.first_difference.id == "msg-h1"
    assert report.first_difference.recorded_digest == frame_body(HUMAN_BODY).digest
    assert (
        report.first_difference.reconstructed_digest
        == frame_body({**HUMAN_BODY, "content": "hi there"}).digest
    )
    # Asked for, the reconstructed batch is still returned.
    with_batch = await ReplayService(world.service()).dry_run(
        SCOPE, ACTOR, RUN, world.point_id, include_batch=True
    )
    assert with_batch.batch is not None and with_batch.batch[1]["content"] == "hi there"


@pytest.mark.asyncio
async def test_a_missing_object_is_reported_without_a_reconstructed_digest() -> None:
    world = World()
    system_ref = await promote(world.payloads, SYSTEM_BODY)
    absent = frame_body_ref(digest="sha256:" + "ef" * 32, size_bytes=12, media_type=JSON)
    world.requests = (model_request(system_ref=system_ref, human_ref=absent),)
    await world.build()
    report = await ReplayService(world.service()).dry_run(SCOPE, ACTOR, RUN, world.point_id)
    assert report.exact is False and report.batch_digest_reconstructed is None
    human = report.messages[1]
    assert human.source == "missing" and human.reconstructed_digest is None
    assert human.reason is not None and human.reason.startswith("object_unavailable")
    assert report.first_difference is not None and report.first_difference.index == 1


@pytest.mark.asyncio
async def test_call_index_selects_the_request_and_the_last_is_the_default() -> None:
    world = World()
    system_ref = await promote(world.payloads, SYSTEM_BODY)
    human_ref = await promote(world.payloads, HUMAN_BODY)
    world.requests = (
        model_request(system_ref=system_ref, human_ref=human_ref, call_index=0),
        model_request(system_ref=system_ref, human_ref=human_ref, call_index=1, batch=BATCH[:2]),
    )
    await world.build()
    replay = ReplayService(world.service())
    latest = await replay.dry_run(SCOPE, ACTOR, RUN, world.point_id)
    assert latest.call_index == 1 and latest.arrival_ordinal == 5
    assert latest.exact is False  # call 1 recorded a two-message batch digest
    first = await replay.dry_run(SCOPE, ACTOR, RUN, world.point_id, call_index=0)
    assert first.call_index == 0 and first.exact is True
    with pytest.raises(ModelRequestNotFound):
        await replay.dry_run(SCOPE, ACTOR, RUN, world.point_id, call_index=7)


@pytest.mark.asyncio
async def test_replay_requires_the_grant_the_scope_and_a_body_reader() -> None:
    world = await World().build()
    replay = ReplayService(world.service())
    with pytest.raises(ReplayDenied):
        await replay.dry_run(
            SCOPE, ActorContext(actor_id="viewer", permissions=READ), RUN, world.point_id
        )
    with pytest.raises(ReplayDenied):
        await replay.dry_run("mc/other/biotech/scope", ACTOR, RUN, world.point_id)
    with pytest.raises(ReplayUnavailable):
        await ReplayService(world.service(artifacts=False)).dry_run(
            SCOPE, ACTOR, RUN, world.point_id
        )
    with pytest.raises(PointFramesUnavailable):
        await replay.dry_run(SCOPE, ACTOR, RUN, world.bare_point_id)


# --- HTTP --------------------------------------------------------------------------------------


def http_app(world: World, permissions: frozenset[str]) -> FastAPI:
    registry = ApplicationRegistry(
        (
            ApplicationBinding.seal(
                application_id="biotech",
                installation_id=INSTALLATION,
                binding_version="1",
                supabase_project_ref="project",
                database_secret_ref="TEST_DATABASE_URL",
                accepted_issuers={"https://issuer.invalid"},
                accepted_audiences={"authenticated"},
                required_component_version="1",
            ),
        )
    )
    registry.observe(
        "biotech", InstallationObservation(INSTALLATION, "biotech", "project", frozenset({"1"}))
    )
    app = FastAPI()
    app.include_router(router)
    app.state.mission_control_registry = registry
    app.state.mission_control_cognition_point_services = {
        (INSTALLATION, "biotech", TENANT): world.service()
    }
    app.state.mission_control_artifact_body_readers = {
        (INSTALLATION, "biotech", TENANT): world.reader
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


@pytest.mark.asyncio
async def test_http_frames_by_point_and_replay() -> None:
    world = await World().build()
    base = f"/v1/applications/biotech/runs/{RUN}/points"
    client = TestClient(http_app(world, FULL))
    frames = client.get(f"{base}/{world.point_id}/frames")
    assert frames.status_code == 200, frames.text
    rows = frames.json()["frames"]
    assert [row["arrival_ordinal"] for row in rows] == [2, 3, 4]
    assert all(row["schema_version"] == "mc.provider_frame.v1" for row in rows)
    assert rows[0]["kind"] == "model_request" and "body_excerpt" in rows[0]
    assert client.get(f"{base}/{world.bare_point_id}/frames").status_code == 404
    assert client.get(f"{base}/{world.bare_point_id}/frames").json()["detail"]["code"] == (
        "point_frames_unavailable"
    )
    assert client.get(f"{base}/unknown/frames").status_code == 404

    replay = client.get(f"{base}/{world.point_id}/replay")
    assert replay.status_code == 200, replay.text
    report = replay.json()
    assert report["schema_version"] == REPLAY_REPORT_SCHEMA and report["exact"] is True
    assert report["application_id"] == "biotech" and len(report["batch"]) == 4
    assert client.get(f"{base}/{world.point_id}/replay", params={"call_index": 9}).status_code == (
        404
    )
    assert client.get(f"{base}/{world.bare_point_id}/replay").status_code == 404

    viewer = TestClient(http_app(world, READ))
    assert viewer.get(f"{base}/{world.point_id}/frames").status_code == 200
    denied = viewer.get(f"{base}/{world.point_id}/replay")
    assert denied.status_code == 403
    assert denied.json()["detail"]["permission"] == "workflow.result.read"


# --- MCP ---------------------------------------------------------------------------------------


class Principals:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.permissions = permissions

    async def resolve(self, context: Any) -> CoordinatorPrincipal:
        return CoordinatorPrincipal(
            actor_id="mcp-operator",
            tenant_scope=SCOPE,
            roles=frozenset(),
            permissions=self.permissions,
            request_scope=SCOPE,
        )


@pytest.mark.asyncio
async def test_mcp_point_frames_and_replay_tools() -> None:
    world = await World().build()
    server = FastMCP("points-test")
    points = ScopedCognitionPoints({SCOPE: world.service()})
    register_cognition_point_tools(server, points, Principals(FULL), call=_principal_call)
    async with Client(server) as client:
        frames = await client.call_tool(
            POINT_FRAMES_TOOL, {"run_id": RUN, "point_id": world.point_id}
        )
        envelope = frames.structured_content
        assert envelope is not None and envelope["ok"] is True
        assert [row["arrival_ordinal"] for row in envelope["data"]["frames"]] == [2, 3, 4]
        replay = await client.call_tool(REPLAY_TOOL, {"run_id": RUN, "point_id": world.point_id})
        envelope = replay.structured_content
        assert envelope is not None and envelope["ok"] is True
        report = envelope["data"]
        assert report["exact"] is True and report["schema_version"] == REPLAY_REPORT_SCHEMA
        paid = await client.call_tool(
            REPLAY_TOOL, {"run_id": RUN, "point_id": world.point_id, "dry_run": False}
        )
        envelope = paid.structured_content
        assert envelope is not None and envelope["ok"] is False
        assert "paid_replay_not_available" in json.dumps(envelope)


def test_cli_run_replay_requires_dry_run_and_prints_the_report(tmp_path: Any, capsys: Any) -> None:
    import argparse

    import httpx

    from mission_control.interfaces.cli import main as cli

    report = {"schema_version": REPLAY_REPORT_SCHEMA, "exact": True, "batch": [{"type": "ai"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/points/p-1/replay")
        assert request.url.params.get("include_batch") == "true"
        assert request.url.params.get("call_index") == "2"
        return httpx.Response(200, json=report)

    transport = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://mc.test")
    client = cli.MissionClient(transport, "biotech")
    paid = argparse.Namespace(run_id=RUN, point_id="p-1", dry_run=False)
    assert cli.run_replay(client, paid) == 2
    assert json.loads(capsys.readouterr().out) == {"error": "paid_replay_not_available"}
    out = tmp_path / "replay.json"
    args = argparse.Namespace(
        run_id=RUN, point_id="p-1", dry_run=True, call_index=2, include_batch=False, out=str(out)
    )
    assert cli.run_replay(client, args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["exact"] is True and "batch" not in printed and printed["out"] == str(out)
    assert json.loads(out.read_text(encoding="utf-8")) == report

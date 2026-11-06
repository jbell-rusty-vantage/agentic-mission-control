"""WP-TR-3 (stream R3) on the common component (release 1.4.4): the persisted Transcript
projection (`transcript_entry`, `transcript_projection_state`), its settlement-released
outbox intents, and the retention classes (FX-TR-RETAIN).

Frames are written through the Native Event Store, facts are projected into the ledger,
the `mc.transcript_entry.v2` entries are projected into the table under the restricted
runtime login and read back by the transcript service when current; another tenant sees
nothing. Retention deletes delta frames by `retain_days` and step frames only when
`step_retain_days` is set and the run is terminal.

Tracing Stage 3: the marks carry the run's frame count and an older pass never moves the
state backwards (R4-F7, R4-F8); retention projects a run before deleting its frames, keeps
the frames of a run it cannot project, and invalidates and re-queues the projection of every
run it deletes from (R4-F1, R4-F2); a `frame-body://` digest is bound to the runs whose
frames reference it (R4-F6).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.frames.retention import (
    FrameRetentionPolicy,
    PostgresFrameRetention,
)
from mission_control.adapters.postgres.frames.transcript_entries import (
    TRANSCRIPT_PROJECTION_VERSION,
    PostgresTranscriptEntries,
    PostgresTranscriptProjectionIntents,
    insert_transcript_projection_intent,
)
from mission_control.adapters.postgres.frames.transcript_projection import (
    PostgresTranscriptDocuments,
)
from mission_control.adapters.postgres.frames.transcript_reads import (
    PostgresFrameBodyIndex,
    PostgresMissionEventReader,
)
from mission_control.adapters.postgres.operations.cognition_points import (
    PostgresCognitionPointRepository,
)
from mission_control.adapters.postgres.run_control.canonical import begin
from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.adapters.storage.frame_body_promoter import PayloadStoreFrameBodyPromoter
from mission_control.application.frames.body_refs import frame_body_ref
from mission_control.application.frames.projection_trigger import (
    TranscriptProjectionIntent,
    TranscriptProjectionRelay,
    transcript_projection_intent,
)
from mission_control.application.frames.reducer import (
    CompletionEvidence,
    FrameFactProjector,
    FrameFactTarget,
)
from mission_control.application.frames.search import TranscriptProjector
from mission_control.application.frames.transcript import TranscriptService
from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.provider_frames import FRAME_NOW, StepClock, observation, turn_observations
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.runtime_common import owner_rows
from tests.unit.run_control.test_run_control import ALL_PERMISSIONS, actor

pytestmark = pytest.mark.common_db

READER = ActorContext(
    actor_id="reader", authority_refs=frozenset(), permissions=frozenset({"workflow_run.read"})
)
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


async def _count(db: CommonDatabase, table: str, run_key: str) -> int:
    rows = await owner_rows(
        db,
        f"""
        SELECT count(*) AS n FROM mission_control.{table} AS t
        JOIN mission_control.mission_run AS r ON r.run_id = t.run_id
        WHERE r.run_key = $1
        """,
        run_key,
    )
    return int(rows[0]["n"])


@pytest.mark.asyncio
async def test_projection_replaces_by_run_tracks_the_sources_and_is_tenant_scoped(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool(max_size=4)
    try:
        scope = common_db.scope()
        admitted = await admit_unit_attempt(pool, common_db)
        frames = PostgresFrameRepository(pool)
        handle = await frames.open_execution(admitted.start())
        await FrameWriter(frames, handle, clock=StepClock()).write(turn_observations())
        facts = FrameFactProjector(
            frames,
            admitted.run_control,
            actor=actor().model_copy(
                update={"permissions": ALL_PERMISSIONS | {"workflow_run.apply_frame_facts"}}
            ),
        )
        await facts.project(
            FrameFactTarget.from_handle(handle, run_key=admitted.run_key),
            completion=CompletionEvidence(),
        )
        service = TranscriptService(
            PostgresMissionEventReader(pool),
            frames,
            request_scope=scope,
            points=PostgresCognitionPointRepository(pool),
        )
        store = PostgresTranscriptEntries(pool)

        # Replace by run: the rows, the state row and the marks.
        marks = await store.live_marks(scope, admitted.run_key)
        assert marks.projected_through_seq > 0 and marks.projected_through_frame is not None
        assert marks.projected_through_frame["frame_count"] == 9  # R4-F1/R4-F7
        entries = await service.entries_v2(admitted.run_key)
        assert entries and all(
            entry.schema_version == "mc.transcript_entry.v2" for entry in entries
        )
        receipt = await store.replace(
            scope,
            admitted.run_key,
            entries,
            projected_through_seq=marks.projected_through_seq,
            projected_through_frame=marks.projected_through_frame,
        )
        assert (receipt.entries, receipt.projection_version) == (
            len(entries),
            TRANSCRIPT_PROJECTION_VERSION,
        )
        state = await store.state(scope, admitted.run_key)
        assert state is not None
        assert (state.entry_count, state.projected_through_seq, state.projected_through_frame) == (
            len(entries),
            marks.projected_through_seq,
            marks.projected_through_frame,
        )
        assert await _count(common_db, "transcript_entry", admitted.run_key) == len(entries)
        typed = await owner_rows(
            common_db,
            """
            SELECT t.entry_seq, t.cursor, t.kind, t.source, t.body_state, t.unit_key, t.point_id
            FROM mission_control.transcript_entry AS t
            JOIN mission_control.mission_run AS r ON r.run_id = t.run_id
            WHERE r.run_key = $1 ORDER BY t.entry_seq
            """,
            admitted.run_key,
        )
        assert [row["entry_seq"] for row in typed] == list(range(1, len(entries) + 1))
        assert [row["cursor"] for row in typed] == [entry.cursor for entry in entries]
        assert [row["body_state"] for row in typed] == [entry.body.state for entry in entries]
        assert [row["unit_key"] for row in typed] == [entry.unit_key for entry in entries]
        assert [str(row["point_id"]) if row["point_id"] else None for row in typed] == [
            entry.point_id for entry in entries
        ]

        # Current: the rows come back as the same entries and the service serves them.
        current = await store.current_entries(scope, admitted.run_key)
        assert current == entries
        served = TranscriptService(
            PostgresMissionEventReader(pool),
            frames,
            request_scope=scope,
            points=PostgresCognitionPointRepository(pool),
            entry_store=store,
        )
        page = await served.materialize(admitted.run_key, actor=READER)
        assert page.entries == entries

        # Idempotent replay: the same projection again changes nothing.
        again = await store.replace(
            scope,
            admitted.run_key,
            entries,
            projected_through_seq=marks.projected_through_seq,
            projected_through_frame=marks.projected_through_frame,
        )
        assert again == receipt
        assert await store.current_entries(scope, admitted.run_key) == entries
        assert await _count(common_db, "transcript_entry", admitted.run_key) == len(entries)

        # R4-F8: a pass that read older marks never moves the state (or the rows) back.
        older = await store.replace(
            scope,
            admitted.run_key,
            entries[:-1],
            projected_through_seq=marks.projected_through_seq - 1,
            projected_through_frame=None,
        )
        assert older.superseded and older.entries == len(entries)
        assert await store.current_entries(scope, admitted.run_key) == entries

        # A new frame leaves the projection behind: the reader falls back to the view.
        later = FrameWriter(frames, handle, clock=StepClock(FRAME_NOW + timedelta(minutes=5)))
        await later.write(
            [
                observation(
                    "turn-2:start",
                    FrameKind.TURN_STARTED,
                    {"invocation_id": "turn-2"},
                    turn="turn-2",
                )
            ]
        )
        assert await store.current_entries(scope, admitted.run_key) is None
        behind = await served.materialize(admitted.run_key, actor=READER)
        assert len(behind.entries) == len(entries) + 1

        # The projector (the `transcript.project` activity's work) catches up: search
        # documents and entries, marks read before the entries.
        projector = TranscriptProjector(service, PostgresTranscriptDocuments(pool), entries=store)
        caught_up = await projector.project(admitted.run_key)
        assert caught_up.entries == len(entries) + 1
        assert caught_up.projected_through_seq == marks.projected_through_seq
        refreshed = await store.current_entries(scope, admitted.run_key)
        assert refreshed is not None and len(refreshed) == len(entries) + 1

        # A new mission event (the second turn's facts) leaves it behind again.
        await later.write(
            [
                observation(
                    "turn-2:end", FrameKind.TURN_ENDED, {"invocation_id": "turn-2"}, turn="turn-2"
                ),
            ]
        )
        await facts.project(
            FrameFactTarget.from_handle(handle, run_key=admitted.run_key),
            completion=CompletionEvidence(),
        )
        fresh = await store.live_marks(scope, admitted.run_key)
        assert fresh.projected_through_seq > marks.projected_through_seq
        assert await store.current_entries(scope, admitted.run_key) is None

        # Another tenant sees nothing: no state, no rows, no entries.
        other = common_db.scope("tenant-2")
        assert await store.current_entries(other, admitted.run_key) is None
        assert await store.state(other, admitted.run_key) is None
        async with pool.acquire() as connection, connection.transaction():
            args = await begin(connection, other)
            visible = await connection.fetchval(
                "SELECT count(*) FROM mission_control.transcript_entry "
                "WHERE installation_id = $1 AND application_id = $2 AND tenant_id = $3",
                *args,
            )
        assert visible == 0
        assert await _count(common_db, "transcript_entry", admitted.run_key) == len(entries) + 1
    finally:
        await pool.close()


class _RecordingStarter:
    def __init__(self) -> None:
        self.started: list[str] = []

    async def project(self, intent: TranscriptProjectionIntent) -> str:
        self.started.append(intent.run_key)
        return f"wf:{intent.run_key}"


@pytest.mark.asyncio
async def test_projection_intents_are_leased_and_acknowledged_once(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool(max_size=4)
    try:
        scope = common_db.scope()
        admitted = await admit_unit_attempt(pool, common_db)
        intent = transcript_projection_intent(
            request_scope=scope, run_key=admitted.run_key, settlement_id="settlement-1"
        )
        async with pool.acquire() as connection, connection.transaction():
            args = await begin(connection, scope)
            # The settlement transaction writes it; a replayed commit writes nothing.
            await insert_transcript_projection_intent(
                connection, args, intent, at=NOW, actor_ref="mission-control-runtime/1"
            )
            await insert_transcript_projection_intent(
                connection, args, intent, at=NOW, actor_ref="mission-control-runtime/1"
            )
        rows = await owner_rows(
            common_db,
            "SELECT delivery_state, aggregate_key, event_type, attempts "
            "FROM mission_control.outbox WHERE destination_kind = 'transcript_projection'",
        )
        assert [dict(row) for row in rows] == [
            {
                "delivery_state": "pending",
                "aggregate_key": admitted.run_key,
                "event_type": "transcript.project",
                "attempts": 0,
            }
        ]
        starter = _RecordingStarter()
        relay = TranscriptProjectionRelay(
            store=PostgresTranscriptProjectionIntents(pool), starter=starter
        )
        first = await relay.relay_once(scope, now=NOW + timedelta(seconds=1))
        second = await relay.relay_once(scope, now=NOW + timedelta(seconds=3))
        assert first.delivered == (intent.delivery_key,) and second.delivered == ()
        assert starter.started == [admitted.run_key]
        delivered = await owner_rows(
            common_db,
            "SELECT delivery_state, attempts FROM mission_control.outbox "
            "WHERE destination_kind = 'transcript_projection'",
        )
        assert [dict(row) for row in delivered] == [{"delivery_state": "delivered", "attempts": 1}]
        # Another tenant's relay leases nothing.
        other = TranscriptProjectionRelay(
            store=PostgresTranscriptProjectionIntents(pool), starter=starter
        )
        assert (await other.relay_once(common_db.scope("tenant-2"), now=NOW)).delivered == ()
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_retention_classes_delete_deltas_by_retain_days_and_steps_only_for_terminal_runs(
    common_db: CommonDatabase,
) -> None:
    pool = await common_db.pool(max_size=4)
    try:
        scope = common_db.scope()
        admitted = await admit_unit_attempt(pool, common_db)
        frames = PostgresFrameRepository(pool)
        handle = await frames.open_execution(admitted.start())
        await FrameWriter(frames, handle, clock=StepClock(FRAME_NOW)).write(turn_observations())
        written = await frames.frames_for_run(scope, handle.run_id)
        deltas = [frame for frame in written if frame.kind is FrameKind.MESSAGE_DELTA]
        assert len(written) == 9 and len(deltas) == 1
        events_before = await owner_rows(
            common_db, "SELECT count(*) AS n FROM mission_control.mission_event"
        )
        store = PostgresTranscriptEntries(pool)

        def projector(request_scope: str) -> TranscriptProjector:
            return TranscriptProjector(
                TranscriptService(
                    PostgresMissionEventReader(pool),
                    frames,
                    request_scope=request_scope,
                    points=PostgresCognitionPointRepository(pool),
                ),
                PostgresTranscriptDocuments(pool),
                entries=store,
            )

        # R4-F2: a run that was never projected keeps its expiring frames without projectors.
        unprojected = await PostgresFrameRetention(pool).expire(
            scope, now=FRAME_NOW + timedelta(days=31)
        )
        assert (unprojected.expired_delta, unprojected.skipped_unprojected) == (0, 1)
        assert len(await frames.frames_for_run(scope, handle.run_id)) == 9
        retention = PostgresFrameRetention(pool, projectors=projector)

        # FX-TR-RETAIN: the delta clock deletes only delta-class frames.
        early = await retention.expire(scope, now=FRAME_NOW + timedelta(days=29))
        assert (early.expired_delta, early.expired_step) == (0, 0)
        report = await retention.expire(scope, now=FRAME_NOW + timedelta(days=31))
        assert (report.expired_delta, report.expired_step) == (1, 0)
        assert (report.deleted_non_closing, report.deleted_closing) == (1, 0)
        assert report.step_cutoff is None and report.policy.step_retain_days is None
        assert (report.skipped_unprojected, report.invalidated_projections) == (0, 1)
        remaining = await frames.frames_for_run(scope, handle.run_id)
        assert len(remaining) == 8
        assert all(frame.kind is not FrameKind.MESSAGE_DELTA for frame in remaining)
        assert sum(1 for frame in remaining if frame.closing) == 5

        # R4-F1: the projection was invalidated and re-queued in the delete's transaction;
        # rows holding the deleted delta are never served as current.
        assert await store.state(scope, admitted.run_key) is None
        assert await store.current_entries(scope, admitted.run_key) is None
        queued = await owner_rows(
            common_db,
            "SELECT delivery_key FROM mission_control.outbox "
            "WHERE destination_kind = 'transcript_projection' AND aggregate_key = $1",
            admitted.run_key,
        )
        assert [row["delivery_key"] for row in queued] == [
            f"transcript-projection:{admitted.run_key}:expire:{report.cutoff.isoformat()}"
        ]
        # The re-projection keeps the deleted delta as a placeholder without a body.
        await projector(scope).project(admitted.run_key)
        rows = await store.current_entries(scope, admitted.run_key)
        assert rows is not None
        (expired,) = [entry for entry in rows if entry.body.state == "expired"]
        assert expired.kind == "frame_expired" and expired.body_excerpt is None
        assert expired.refs.artifact_ref is None and expired.refs.frame_id == str(
            deltas[0].frame_id
        )

        # The step clock is off by default; turning it on expires nothing for a live run.
        await retention.set_policy(scope, FrameRetentionPolicy(retain_days=30, step_retain_days=30))
        policy = await retention.policy(scope)
        assert (policy.retain_days, policy.step_retain_days, policy.prune_mode) == (
            30,
            30,
            "delete",
        )
        live = await retention.expire(scope, now=FRAME_NOW + timedelta(days=31))
        assert (live.expired_delta, live.expired_step) == (0, 0)
        assert live.step_cutoff == FRAME_NOW + timedelta(days=1)
        assert len(await frames.frames_for_run(scope, handle.run_id)) == 8

        # A terminal run: tombstone mode is reserved (prunes nothing), delete mode expires
        # every step frame past the step clock.
        await owner_rows(
            common_db,
            """
            UPDATE mission_control.mission_run
            SET phase = 'terminal', lifecycle = 'completed', terminal_outcome = 'cancelled',
                projection = jsonb_set(jsonb_set(projection, '{phase}', '"terminal"'),
                                       '{terminal_outcome}', '"cancelled"')
            WHERE run_key = $1
            RETURNING 1
            """,
            admitted.run_key,
        )
        await retention.set_policy(
            scope, FrameRetentionPolicy(step_retain_days=30, prune_mode="tombstone")
        )
        assert (await retention.policy(scope)).prune_mode == "tombstone"
        reserved = await retention.expire(scope, now=FRAME_NOW + timedelta(days=31))
        assert (reserved.expired_delta, reserved.expired_step) == (0, 0)
        assert len(await frames.frames_for_run(scope, handle.run_id)) == 8
        await retention.set_policy(scope, FrameRetentionPolicy(step_retain_days=30))
        gone = await retention.expire(scope, now=FRAME_NOW + timedelta(days=31))
        assert (gone.expired_delta, gone.expired_step) == (0, 8)
        assert await frames.frames_for_run(scope, handle.run_id) == ()

        # Mission events are never touched by either clock.
        events_after = await owner_rows(
            common_db, "SELECT count(*) AS n FROM mission_control.mission_event"
        )
        assert events_after[0]["n"] == events_before[0]["n"]
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_a_frame_body_digest_is_bound_to_the_runs_that_reference_it(
    common_db: CommonDatabase,
) -> None:
    """R4-F6: the download route's index answers only for a run whose frame promoted the
    digest (size and media type from the row) or whose `model_request` names it."""

    pool = await common_db.pool(max_size=4)
    try:
        scope = common_db.scope()
        admitted = await admit_unit_attempt(pool, common_db)
        frames = PostgresFrameRepository(pool)
        handle = await frames.open_execution(admitted.start())
        promoter = PayloadStoreFrameBodyPromoter(InMemoryArtifactPayloadStore())
        writer = FrameWriter(
            frames, handle, clock=StepClock(), excerpt_cap_bytes=256, promoter=promoter
        )
        message = "sha256:" + sha256(b"message").hexdigest()
        message_ref = frame_body_ref(digest=message, size_bytes=7, media_type="text/plain")
        await writer.write(
            [
                observation(
                    "big:completed",
                    FrameKind.TOOL_CALL_COMPLETED,
                    {"tool_call_id": "call-9", "content": "x" * 4_096},
                    tool_call_ref="call-9",
                ),
                observation(
                    "request:1",
                    FrameKind.MODEL_REQUEST,
                    {"messages": [{"type": "human", "digest": message, "ref": message_ref}]},
                ),
            ]
        )
        written = await frames.frames_for_run(scope, handle.run_id)
        (big,) = [frame for frame in written if frame.kind is FrameKind.TOOL_CALL_COMPLETED]
        assert big.body_artifact_ref is not None
        index = PostgresFrameBodyIndex(pool)
        found = await index.run_frame_body(scope, admitted.run_key, big.body_digest)
        assert found is not None
        assert (found.size_bytes, found.media_type) == (big.body_bytes, big.body_media_type)
        named = await index.run_frame_body(scope, admitted.run_key, message)
        assert named is not None and (named.size_bytes, named.media_type) == (7, "text/plain")
        assert await index.run_frame_body(scope, "no-such-run", big.body_digest) is None
        assert await index.run_frame_body(scope, admitted.run_key, "sha256:" + "0" * 64) is None
        other = common_db.scope("tenant-2")
        assert await index.run_frame_body(other, admitted.run_key, big.body_digest) is None
    finally:
        await pool.close()

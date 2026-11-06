"""WP-TR-3 (stream R3): the Transcript projection released by the settlement outbox (TR-D10).

A settlement commit writes exactly one `transcript_projection` outbox intent (the in-memory
journal records it like the Postgres journal inserts it); the relay delivers each intent
once, acknowledges after the start, retries failures with backoff and dead-letters them;
the projector persists the v2 entries beside the search documents; the Temporal starter
derives one workflow id per settlement and treats an already-started workflow as delivered.

Tracing Stage 3 (R4-F3, R4-F8): the projector merges the run once for both consumers, beats
between its phases, and queues its own catch-up when the sources moved while it ran (never
after a superseded write); the activity's last failed attempt queues a retry; a failed
workflow can be started again under its id.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import ActivityEnvironment

from mission_control.adapters.temporal.activities.transcript_projection import (
    PROJECT_MAX_ATTEMPTS,
    TRANSCRIPT_PROJECT_WORKFLOW,
    TemporalTranscriptProjectionStarter,
    TranscriptProjectInput,
    TranscriptProjectionActivities,
    transcript_projection_workflow_id,
)
from mission_control.application.execution.operations.operation_journal import (
    InMemoryAtomicOperationJournalRepository,
    OperationJournalMutation,
    OperationJournalService,
)
from mission_control.application.frames.projection_trigger import (
    MAX_DELIVERY_ATTEMPTS,
    TRANSCRIPT_PROJECTION_DESTINATION,
    TranscriptProjectionIntent,
    TranscriptProjectionPump,
    TranscriptProjectionRelay,
    transcript_projection_delivery_key,
    transcript_projection_intent,
)
from mission_control.application.frames.search import (
    ProjectionMarks,
    ProjectionReceipt,
    TranscriptDocument,
    TranscriptEntryReceipt,
    TranscriptProjector,
    TranscriptSearchService,
)
from mission_control.domain.frames.transcript import TranscriptEntry
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.provider_frames import SCOPE
from tests.fixtures.transcripts import RUN_KEY
from tests.integration.postgres.test_operation_journal_stage1 import (
    _SCOPE,
    attempt,
    authority_command,
    authority_event,
    authority_result,
    claim,
    settlement,
)
from tests.unit.frames.test_transcript_interfaces import transcript_service

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
READER = ActorContext(actor_id="reader", permissions=frozenset({"workflow_run.read"}))


# --------------------------------------------------------------------------------------
# The settlement writes the intent (in-memory journal)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_settlement_commit_writes_the_projection_intent_once() -> None:
    repository = InMemoryAtomicOperationJournalRepository()
    journal = OperationJournalService(repository)
    accepted_command = authority_command(run_id="run-1")
    accepted_result = authority_result(run_id="run-1")
    repository.seed_authority_proof(
        accepted_command, accepted_result, authority_event(accepted_command, accepted_result)
    )
    mutation = OperationJournalMutation(
        request_scope=_SCOPE[0],
        belllabs_run_id="run-1",
        expected_run_version=2,
        claim=claim(),
        attempt=attempt(),
        settlement=settlement(),
        authority_command=accepted_command,
        authority_result=accepted_result,
    )
    assert repository.projection_intents == ()
    first = await journal.commit(mutation)
    replay = await journal.commit(mutation)
    assert (first.status, replay.status) == ("acquired", "existing")
    (intent,) = repository.projection_intents
    assert intent == transcript_projection_intent(
        request_scope=_SCOPE[0], run_key="run-1", settlement_id="settlement-1"
    )
    assert intent.delivery_key == "transcript-projection:run-1:settlement-1"
    assert intent.schema_version == "mc.transcript_projection_intent.v1"
    assert TRANSCRIPT_PROJECTION_DESTINATION == "transcript_projection"


def test_delivery_key_names_the_run_and_settlement_and_a_reconciled_revision() -> None:
    assert transcript_projection_delivery_key("run-1", "s-1") == "transcript-projection:run-1:s-1"
    assert (
        transcript_projection_delivery_key("run-1", "s-1", settlement_revision=2)
        == "transcript-projection:run-1:s-1:r2"
    )


# --------------------------------------------------------------------------------------
# The relay delivers once and acknowledges after the start
# --------------------------------------------------------------------------------------


class _Store:
    def __init__(self, intents: Sequence[TranscriptProjectionIntent]) -> None:
        self.pending = list(intents)
        self.delivered: list[str] = []
        self.failed: list[tuple[str, datetime, bool]] = []
        self.leased: list[str] = []

    async def lease(
        self,
        request_scope: str,
        *,
        lease_owner: str,
        lease_until: datetime,
        now: datetime,
        limit: int,
    ) -> tuple[TranscriptProjectionIntent, ...]:
        due = [item for item in self.pending if item.delivery_key not in self.delivered][:limit]
        self.leased.extend(item.delivery_key for item in due)
        return tuple(due)

    async def mark_delivered(
        self, request_scope: str, delivery_key: str, *, lease_owner: str, delivered_at: datetime
    ) -> None:
        self.delivered.append(delivery_key)

    async def mark_failed(
        self,
        request_scope: str,
        delivery_key: str,
        *,
        lease_owner: str,
        retry_at: datetime,
        dead: bool,
    ) -> None:
        self.failed.append((delivery_key, retry_at, dead))
        self.pending = [
            item.model_copy(update={"attempts": item.attempts + 1})
            if item.delivery_key == delivery_key
            else item
            for item in self.pending
            if not (dead and item.delivery_key == delivery_key)
        ]


class _Starter:
    def __init__(self, *, fail: bool = False) -> None:
        self.started: list[str] = []
        self.fail = fail

    async def project(self, intent: TranscriptProjectionIntent) -> str:
        if self.fail:
            raise RuntimeError("temporal unreachable")
        self.started.append(intent.run_key)
        return f"wf:{intent.run_key}"


def _intent(run: str, settlement_id: str = "s-1", attempts: int = 0) -> TranscriptProjectionIntent:
    return transcript_projection_intent(
        request_scope=SCOPE, run_key=run, settlement_id=settlement_id
    ).model_copy(update={"attempts": attempts})


@pytest.mark.asyncio
async def test_relay_starts_each_intent_once_and_acknowledges_after_the_start() -> None:
    store = _Store([_intent("run-a"), _intent("run-b", "s-2")])
    starter = _Starter()
    relay = TranscriptProjectionRelay(store=store, starter=starter)
    first = await relay.relay_once(SCOPE, now=NOW)
    second = await relay.relay_once(SCOPE, now=NOW + timedelta(seconds=2))
    assert first.delivered == (
        "transcript-projection:run-a:s-1",
        "transcript-projection:run-b:s-2",
    )
    assert first.handles["transcript-projection:run-a:s-1"] == "wf:run-a"
    assert second.delivered == () and starter.started == ["run-a", "run-b"]
    assert store.delivered == list(first.delivered) and store.failed == []


@pytest.mark.asyncio
async def test_relay_retries_a_failed_start_with_backoff_and_dead_letters_the_last() -> None:
    store = _Store([_intent("run-a"), _intent("run-dead", attempts=MAX_DELIVERY_ATTEMPTS - 1)])
    relay = TranscriptProjectionRelay(store=store, starter=_Starter(fail=True))
    report = await relay.relay_once(SCOPE, now=NOW)
    assert report.delivered == ()
    assert report.failed == ("transcript-projection:run-a:s-1",)
    assert report.dead == ("transcript-projection:run-dead:s-1",)
    (retry, dead) = store.failed
    assert retry[1] == NOW + timedelta(seconds=4.0) and retry[2] is False
    assert dead[2] is True
    assert store.delivered == []
    # The pump never raises out of a scope's pass; the failing scope is retried next pass.
    pump = TranscriptProjectionPump(relay, [SCOPE], clock=lambda: NOW)
    assert len(await pump.run_once()) == 1


# --------------------------------------------------------------------------------------
# The projector persists the v2 entries beside the search documents
# --------------------------------------------------------------------------------------


class _Documents:
    def __init__(self) -> None:
        self.rows: dict[str, TranscriptDocument] = {}

    async def replace(
        self, request_scope: str, run_key: str, documents: Sequence[TranscriptDocument]
    ) -> ProjectionReceipt:
        self.rows = {document.cursor: document for document in documents}
        return ProjectionReceipt(
            run_id=run_key, upserted=len(documents), deleted=0, documents=len(documents)
        )

    async def search(
        self, request_scope: str, run_key: str, text: str, *, limit: int
    ) -> tuple[tuple[str, float], ...]:
        return ()


class _Entries:
    def __init__(self) -> None:
        self.replaced: list[
            tuple[str, tuple[TranscriptEntry, ...], int, dict[str, Any] | None]
        ] = []
        self.marks_reads = 0

    async def projected_entries(
        self, request_scope: str, run_key: str
    ) -> tuple[TranscriptEntry, ...]:
        del request_scope, run_key
        return ()

    async def live_marks(self, request_scope: str, run_key: str) -> ProjectionMarks:
        self.marks_reads += 1
        return ProjectionMarks(
            projected_through_seq=7,
            projected_through_frame={
                "harness_execution_id": "h",
                "generation": 1,
                "arrival_ordinal": 3,
            },
        )

    async def replace(
        self,
        request_scope: str,
        run_key: str,
        entries: Sequence[TranscriptEntry],
        *,
        projected_through_seq: int,
        projected_through_frame: dict[str, Any] | None,
    ) -> TranscriptEntryReceipt:
        self.replaced.append(
            (run_key, tuple(entries), projected_through_seq, projected_through_frame)
        )
        return TranscriptEntryReceipt(
            run_id=run_key,
            entries=len(entries),
            projected_through_seq=projected_through_seq,
            projected_through_frame=projected_through_frame,
            projection_version=2,
        )


@pytest.mark.asyncio
async def test_projector_persists_v2_entries_with_the_marks_read_before_them() -> None:
    service = transcript_service()
    documents, entries = _Documents(), _Entries()
    receipt = await TranscriptProjector(service, documents, entries=entries).project(RUN_KEY)
    expected = await service.entries_v2(RUN_KEY)
    ((run_key, persisted, seq, frame),) = entries.replaced
    assert run_key == RUN_KEY and persisted == expected and len(expected) > 0
    assert all(entry.schema_version == "mc.transcript_entry.v2" for entry in persisted)
    assert (seq, frame) == (7, {"harness_execution_id": "h", "generation": 1, "arrival_ordinal": 3})
    assert (receipt.entries, receipt.projected_through_seq) == (len(expected), 7)
    assert receipt.documents == len(documents.rows) > 0
    # Without an entry store the receipt keeps the search-only shape.
    plain = await TranscriptProjector(service, _Documents()).project(RUN_KEY)
    assert (plain.entries, plain.projected_through_seq) == (0, None)


@pytest.mark.asyncio
async def test_refresh_projects_the_entries_too() -> None:
    entries = _Entries()
    search = TranscriptSearchService(transcript_service(), _Documents(), entries=entries)
    receipt = await search.refresh(RUN_KEY, actor=READER)
    assert len(entries.replaced) == 1 and receipt.entries == len(entries.replaced[0][1]) > 0


# --------------------------------------------------------------------------------------
# The Temporal starter: one workflow per settlement on the maintenance queue
# --------------------------------------------------------------------------------------


class _Client:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []

    async def start_workflow(self, name: str, arg: Any, **kwargs: Any) -> None:
        if any(start["id"] == kwargs["id"] for start in self.starts):
            raise WorkflowAlreadyStartedError(kwargs["id"], name)
        self.starts.append({"name": name, "arg": arg, **kwargs})


@pytest.mark.asyncio
async def test_starter_starts_the_projection_once_per_settlement_on_the_queue() -> None:
    client = _Client()
    starter = TemporalTranscriptProjectionStarter(client, task_queue="q-maintenance")  # type: ignore[arg-type]
    intent = _intent("run-a")
    first = await starter.project(intent)
    again = await starter.project(intent)
    assert first == again == transcript_projection_workflow_id(intent)
    assert first == f"{SCOPE}/run/run-a/transcript-projection/s-1"
    (start,) = client.starts
    assert start["name"] == TRANSCRIPT_PROJECT_WORKFLOW
    assert start["arg"] == TranscriptProjectInput(request_scope=SCOPE, run_ids=("run-a",))
    assert start["task_queue"] == "q-maintenance"
    revised = intent.model_copy(update={"settlement_revision": 2})
    assert transcript_projection_workflow_id(revised).endswith("/s-1:r2")
    # R4-F3: a failed projection can be started again under its id.
    assert start["id_reuse_policy"] is WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY


# --------------------------------------------------------------------------------------
# Tracing Stage 3: one merge, heartbeats, catch-up and retry (R4-F3, R4-F8)
# --------------------------------------------------------------------------------------


class _MovingEntries(_Entries):
    """Marks that move between the start and the end of a pass (a terminal event landed)."""

    def __init__(self, *, superseded: bool = False) -> None:
        super().__init__()
        self.superseded = superseded
        self.requests: list[tuple[str, str, datetime]] = []

    async def live_marks(self, request_scope: str, run_key: str) -> ProjectionMarks:
        marks = await super().live_marks(request_scope, run_key)
        if self.marks_reads == 1:
            return marks
        return marks.model_copy(update={"projected_through_seq": 8})

    async def replace(self, *args: Any, **kwargs: Any) -> TranscriptEntryReceipt:
        receipt = await super().replace(*args, **kwargs)
        return receipt.model_copy(update={"superseded": self.superseded})

    async def request_projection(
        self, request_scope: str, run_key: str, *, reason: str, not_before: datetime
    ) -> None:
        self.requests.append((run_key, reason, not_before))


class _CountingService:
    """The transcript service, counting merges."""

    def __init__(self) -> None:
        self.inner = transcript_service()
        self.request_scope = self.inner.request_scope
        self.merges = 0

    async def entries_v2(self, run_key: str) -> tuple[TranscriptEntry, ...]:
        self.merges += 1
        return await self.inner.entries_v2(run_key)


@pytest.mark.asyncio
async def test_projector_merges_once_beats_and_queues_a_catch_up_when_behind() -> None:
    service, entries, beats = _CountingService(), _MovingEntries(), []
    projector = TranscriptProjector(service, _Documents(), entries=entries)  # type: ignore[arg-type]
    before = datetime.now(UTC)
    await projector.project(RUN_KEY, heartbeat=beats.append)
    assert service.merges == 1 and entries.marks_reads == 2
    assert beats == ["merged", "documents", "entries"]
    ((run_key, reason, not_before),) = entries.requests
    behind = ProjectionMarks(
        projected_through_seq=8,
        projected_through_frame={
            "harness_execution_id": "h",
            "generation": 1,
            "arrival_ordinal": 3,
        },
    )
    assert run_key == RUN_KEY and reason == behind.catch_up_reason()
    assert reason.startswith("catch-up:") and not_before >= before + timedelta(seconds=30)
    # A pass whose write another pass superseded leaves the catch-up to that pass.
    superseded = _MovingEntries(superseded=True)
    await TranscriptProjector(service, _Documents(), entries=superseded).project(RUN_KEY)  # type: ignore[arg-type]
    assert superseded.requests == []
    # Current at the end: nothing queued.
    steady = _Entries()
    steady.request_projection = None  # type: ignore[attr-defined]  # never called
    await TranscriptProjector(service, _Documents(), entries=steady).project(RUN_KEY)  # type: ignore[arg-type]


class _FailingProjector:
    def __init__(self) -> None:
        self.later: list[tuple[str, str, timedelta]] = []

    async def project(self, run_key: str, **_kwargs: Any) -> ProjectionReceipt:
        raise RuntimeError(f"projection of {run_key} failed")

    async def request_later(self, run_key: str, *, reason: str, delay: timedelta) -> bool:
        self.later.append((run_key, reason, delay))
        return True


@pytest.mark.asyncio
async def test_the_last_failed_attempt_queues_one_retry() -> None:
    projector = _FailingProjector()
    activities = TranscriptProjectionActivities(lambda _scope: projector)  # type: ignore[arg-type,return-value]
    request = TranscriptProjectInput(request_scope=SCOPE, run_ids=("run-a",))
    early = ActivityEnvironment()
    early.info = dataclasses.replace(early.info, attempt=1)
    with pytest.raises(RuntimeError):
        await early.run(activities.project, request)
    assert projector.later == []
    last = ActivityEnvironment()
    last.info = dataclasses.replace(last.info, attempt=PROJECT_MAX_ATTEMPTS)
    with pytest.raises(RuntimeError):
        await last.run(activities.project, request)
    ((run_key, reason, delay),) = projector.later
    assert run_key == "run-a" and reason.startswith("retry:") and delay > timedelta(0)

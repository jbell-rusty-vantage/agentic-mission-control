"""Run list and transcript search (SPEC-03 "Run list and search", ticket C4).

- :class:`RunListService` translates the bounded filter grammar into a Temporal Visibility
  filter bound to the caller's installation prefix and scope hash, lists through the
  :class:`RunVisibility` port and enriches every run from the ledger (``lifecycle``,
  ``terminal_outcome``). The ledger stays the authority: a run Visibility shows but the
  ledger does not know (lag, another tenant's leftovers, a deleted fixture) is dropped and
  counted, never shown.
- :class:`TranscriptProjector` keeps ``mission_control_search.transcript_document`` (one
  row per canonical entry and per closing-frame entry of a run) in step with the
  materialized transcript, idempotently: a rebuild upserts the current rows and deletes
  rows the transcript no longer has. The projection is never an authorization store.
- :class:`TranscriptSearchService` authorizes (``workflow_run.read``), refreshes the run's
  projection, ranks with ``websearch_to_tsquery`` + ``ts_rank_cd`` and returns
  ``mc.transcript_entry.v2`` entries with the cursor that opens their neighbourhood
  through ``run transcript --since``.
- With a :class:`TranscriptEntryStoreWriter` composed, :class:`TranscriptProjector` also
  persists the run's ``mc.transcript_entry.v2`` rows and the projection marks (TR-D10);
  the settlement outbox and ``POST transcript/refresh`` trigger it
  (``application/frames/projection_trigger.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from mission_control.application.frames.transcript import (
    READ_PERMISSION,
    TranscriptDenied,
    TranscriptService,
    keep_expired,
)
from mission_control.domain.authoring.canonical import stable_json_digest
from mission_control.domain.frames.contracts import CLOSING_KINDS
from mission_control.domain.frames.run_query import (
    RunQuery,
    parse_run_query,
    root_filter,
    visibility_filter,
)
from mission_control.domain.frames.transcript import TranscriptEntry
from mission_control.domain.policies.contracts import ActorContext, RunProjection
from mission_control.domain.policies.errors import RunControlNotFound

MAX_LIST_ROWS = 500
MAX_VISIBILITY_ROWS = 5_000
MAX_SEARCH_HITS = 100
CATCH_UP_DELAY = timedelta(seconds=30)
"""Tracing Stage 3 (R4-F3): how long a projection that ended behind waits before the
catch-up pass (a live run is re-projected at most this often by its own catch-ups)."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------------------
# Run list
# --------------------------------------------------------------------------------------


class VisibilityExecution(_Record):
    """One Temporal execution as Visibility reports it (evidence, not authority)."""

    workflow_id: str
    run_key: str
    workflow_kind: str | None = None
    status: str
    mission_id: str | None = None
    lane: str | None = None
    phase: str | None = None
    forked_from: tuple[str, ...] = ()
    started_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None


class RunVisibility(Protocol):
    async def list(self, query: str, *, limit: int) -> tuple[VisibilityExecution, ...]: ...


class RunLedger(Protocol):
    async def get_run(self, request_scope: str, run_id: str) -> RunProjection: ...


class RunListRow(_Record):
    schema_version: Literal["mc.run_list_row.v1"] = "mc.run_list_row.v1"
    run_id: str
    mission_id: str | None = None
    lanes: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()
    """Latest visible phase per execution kind (family and operations)."""
    temporal_status: str | None = None
    """The root execution's Visibility status, when the root is visible."""
    forked_from: tuple[str, ...] = ()
    started_at: AwareDatetime | None = None
    lifecycle: str
    """Ledger lifecycle (authoritative)."""
    terminal_outcome: str | None = None
    run_version: int


class RunListPage(_Record):
    query: str
    rows: tuple[RunListRow, ...]
    visibility_executions: int
    dropped_missing_from_ledger: int = 0
    truncated: bool = False


class RunListUnavailable(RuntimeError):
    """Temporal Visibility is not composed or not reachable for this application."""


class RunListService:
    """``GET /v1/applications/{app}/runs?query=`` and ``missionctl run list``."""

    def __init__(
        self,
        visibility: RunVisibility | None,
        ledger: RunLedger,
        *,
        request_scope: str,
        max_rows: int = MAX_LIST_ROWS,
    ) -> None:
        self._visibility = visibility
        self._ledger = ledger
        self.request_scope = request_scope
        self._max_rows = max_rows

    def filter_for(self, query: str | None) -> tuple[RunQuery, str]:
        parsed = parse_run_query(query)
        return parsed, visibility_filter(parsed, self.request_scope)

    async def list(
        self, query: str | None, *, actor: ActorContext, limit: int | None = None
    ) -> RunListPage:
        if READ_PERMISSION not in actor.permissions:
            raise TranscriptDenied("actor lacks workflow_run.read")
        _parsed, temporal_filter = self.filter_for(query)
        if self._visibility is None:
            raise RunListUnavailable("Temporal Visibility is not composed for this application")
        executions = await self._visibility.list(temporal_filter, limit=MAX_VISIBILITY_ROWS)
        by_run: dict[str, list[VisibilityExecution]] = {}
        for item in executions:
            by_run.setdefault(item.run_key, []).append(item)
        rows: list[RunListRow] = []
        dropped = 0
        cap = min(limit or self._max_rows, self._max_rows)
        ordered = sorted(
            by_run.items(),
            key=lambda pair: (
                -max(
                    (item.started_at.timestamp() for item in pair[1] if item.started_at),
                    default=0.0,
                ),
                pair[0],
            ),
        )
        truncated = len(ordered) > cap
        selected = ordered[:cap]
        rootless = tuple(
            run_key
            for run_key, items in selected
            if not any(item.workflow_kind == "root" for item in items)
        )
        if rootless:
            # The filter may match only families or operations; the root's status is
            # looked up for exactly the listed runs, under the same scope bindings.
            roots = await self._visibility.list(
                root_filter(rootless, self.request_scope), limit=len(rootless)
            )
            for root in roots:
                by_run.setdefault(root.run_key, []).append(root)
        for run_key, _items in selected:
            try:
                projection = await self._ledger.get_run(self.request_scope, run_key)
            except RunControlNotFound:
                dropped += 1
                continue
            rows.append(_row(run_key, by_run[run_key], projection))
        return RunListPage(
            query=query or "",
            rows=tuple(rows),
            visibility_executions=len(executions),
            dropped_missing_from_ledger=dropped,
            truncated=truncated,
        )


def _row(
    run_key: str, items: Sequence[VisibilityExecution], projection: RunProjection
) -> RunListRow:
    root = next((item for item in items if item.workflow_kind == "root"), None)
    started = [item.started_at for item in items if item.started_at is not None]
    return RunListRow(
        run_id=run_key,
        mission_id=next((item.mission_id for item in items if item.mission_id), None),
        lanes=tuple(sorted({item.lane for item in items if item.lane})),
        phases=tuple(sorted({item.phase for item in items if item.phase})),
        temporal_status=root.status if root is not None else None,
        forked_from=next((item.forked_from for item in items if item.forked_from), ()),
        started_at=(root.started_at if root is not None else None) or min(started, default=None),
        lifecycle=projection.phase.value,
        terminal_outcome=(
            projection.terminal_outcome.value if projection.terminal_outcome is not None else None
        ),
        run_version=projection.version,
    )


# --------------------------------------------------------------------------------------
# Transcript projection and search
# --------------------------------------------------------------------------------------


class TranscriptDocument(_Record):
    """One row of ``mission_control_search.transcript_document``."""

    run_key: str
    cursor: str
    kind: str
    role: str | None = None
    title: str
    body_excerpt: str | None = None
    canonical: bool
    recorded_at: datetime


class ProjectionReceipt(_Record):
    run_id: str
    upserted: int
    deleted: int
    documents: int
    entries: int = 0
    """Rows of the persisted ``mc.transcript_entry.v2`` projection (0 without an entry store)."""
    projected_through_seq: int | None = None
    """The run's ``mission_event.seq`` the persisted projection covers (TR-D10)."""


class ProjectionMarks(_Record):
    """Where the live sources stand when a projection starts (read before the entries, so a
    row that arrives during the rebuild leaves the marks behind and the reader falls back
    to the view, never the other way round)."""

    projected_through_seq: int = 0
    projected_through_frame: dict[str, Any] | None = None
    """``{harness_execution_id, generation, arrival_ordinal, frame_count}``: the latest frame
    and the run's frame count (Tracing Stage 3, R4-F1/R4-F7: a deleted or late frame moves
    the count even when the latest frame stays the same)."""

    def catch_up_reason(self) -> str:
        """The outbox reason of a catch-up to exactly these marks (one intent per target)."""

        return "catch-up:" + stable_json_digest(self).removeprefix("sha256:")[:16]


class TranscriptEntryReceipt(_Record):
    run_id: str
    entries: int
    projected_through_seq: int
    projected_through_frame: dict[str, Any] | None = None
    projection_version: int
    superseded: bool = False
    """Tracing Stage 3 (R4-F8): nothing was written, a pass with later marks already had."""


class TranscriptEntryStoreWriter(Protocol):
    """The persisted Transcript projection, write side (``transcript_entry`` rows)."""

    async def live_marks(self, request_scope: str, run_key: str) -> ProjectionMarks: ...

    async def projected_entries(
        self, request_scope: str, run_key: str
    ) -> tuple[TranscriptEntry, ...]: ...

    async def replace(
        self,
        request_scope: str,
        run_key: str,
        entries: Sequence[TranscriptEntry],
        *,
        projected_through_seq: int,
        projected_through_frame: dict[str, Any] | None,
    ) -> TranscriptEntryReceipt:
        """Make the run's rows equal ``entries`` and advance the projection state."""
        ...

    async def request_projection(
        self, request_scope: str, run_key: str, *, reason: str, not_before: datetime
    ) -> None:
        """Queue one more projection of the run, due at ``not_before`` (R4-F3)."""
        ...


class TranscriptDocumentStore(Protocol):
    async def replace(
        self, request_scope: str, run_key: str, documents: Sequence[TranscriptDocument]
    ) -> ProjectionReceipt:
        """Make the run's rows equal ``documents`` (upsert by cursor, delete the rest)."""
        ...

    async def search(
        self, request_scope: str, run_key: str, text: str, *, limit: int
    ) -> tuple[tuple[str, float], ...]:
        """``(cursor, rank)`` by ``ts_rank_cd`` over ``websearch_to_tsquery``, best first."""
        ...


_CLOSING_FRAME_KINDS = frozenset(kind.value for kind in CLOSING_KINDS)


def projected(entry: TranscriptEntry) -> bool:
    """Canonical entries and closing-frame entries are indexed; deltas and starts are not."""

    return entry.canonical or entry.kind in _CLOSING_FRAME_KINDS


def transcript_documents(entries: Sequence[TranscriptEntry]) -> tuple[TranscriptDocument, ...]:
    return tuple(
        TranscriptDocument(
            run_key=entry.run_id,
            cursor=entry.cursor,
            kind=entry.kind,
            role=entry.role,
            title=entry.title,
            body_excerpt=entry.body_excerpt,
            canonical=entry.canonical,
            recorded_at=entry.at,
        )
        for entry in entries
        if projected(entry)
    )


class TranscriptProjector:
    """The projection job of one tenant scope (also run before a search).

    With an ``entries`` store composed it also persists the run's ``mc.transcript_entry.v2``
    rows (TR-D10): the marks are read first, then the entries, so a settlement that lands
    during the rebuild leaves ``projected_through_seq`` behind and the next trigger (or
    ``POST transcript/refresh``) catches up; the reader serves the view meanwhile.

    Tracing Stage 3: the run is merged once and feeds both the search documents and the
    persisted entries; ``heartbeat`` is called between the phases (the activity's liveness);
    and a pass whose sources moved while it ran queues its own catch-up (R4-F3), because the
    settlement trigger never fires for what lands after a run's last settlement.
    """

    def __init__(
        self,
        transcripts: TranscriptService,
        documents: TranscriptDocumentStore,
        *,
        entries: TranscriptEntryStoreWriter | None = None,
    ) -> None:
        self._transcripts = transcripts
        self._documents = documents
        self._entries = entries
        self.request_scope = transcripts.request_scope

    async def project(
        self, run_key: str, *, heartbeat: Callable[[str], None] | None = None
    ) -> ProjectionReceipt:
        beat = heartbeat or _no_heartbeat
        if self._entries is None:
            entries = await self._transcripts.entries_v2(run_key)
            beat("merged")
            return await self._documents.replace(
                self.request_scope, run_key, transcript_documents(entries)
            )
        marks = await self._entries.live_marks(self.request_scope, run_key)
        entries = await self._transcripts.entries_v2(run_key)
        beat("merged")
        receipt = await self._documents.replace(
            self.request_scope, run_key, transcript_documents(entries)
        )
        beat("documents")
        # F-S2-5: frames retention deleted since the last pass stay as placeholders.
        previous = await self._entries.projected_entries(self.request_scope, run_key)
        persisted = await self._entries.replace(
            self.request_scope,
            run_key,
            keep_expired(previous, entries),
            projected_through_seq=marks.projected_through_seq,
            projected_through_frame=marks.projected_through_frame,
        )
        beat("entries")
        if not persisted.superseded:
            after = await self._entries.live_marks(self.request_scope, run_key)
            if after != marks:
                await self._entries.request_projection(
                    self.request_scope,
                    run_key,
                    reason=after.catch_up_reason(),
                    not_before=datetime.now(UTC) + CATCH_UP_DELAY,
                )
        return receipt.model_copy(
            update={
                "entries": persisted.entries,
                "projected_through_seq": persisted.projected_through_seq,
            }
        )

    async def request_later(self, run_key: str, *, reason: str, delay: timedelta) -> bool:
        """Queue a later projection of the run (a failed pass's retry, R4-F3); False when no
        entry store is composed (nothing persisted, nothing to retry)."""

        if self._entries is None:
            return False
        await self._entries.request_projection(
            self.request_scope, run_key, reason=reason, not_before=datetime.now(UTC) + delay
        )
        return True


def _no_heartbeat(_stage: str) -> None:
    return None


class TranscriptSearchHit(_Record):
    rank: float
    entry: TranscriptEntry
    open_cursor: str | None = None
    """Pass to ``run transcript --since`` to read from this entry onwards."""


class TranscriptSearchPage(_Record):
    run_id: str
    query: str
    hits: tuple[TranscriptSearchHit, ...]
    projection: ProjectionReceipt | None = None


class TranscriptSearchInvalid(ValueError):
    code = "invalid_search_query"


class TranscriptSearchService:
    """``GET .../runs/{id}/transcript/search?q=`` and ``missionctl run search``."""

    def __init__(
        self,
        transcripts: TranscriptService,
        documents: TranscriptDocumentStore,
        *,
        refresh: bool = True,
        entries: TranscriptEntryStoreWriter | None = None,
    ) -> None:
        self._transcripts = transcripts
        self._documents = documents
        self._projector = TranscriptProjector(transcripts, documents, entries=entries)
        self._refresh = refresh
        self.request_scope = transcripts.request_scope

    async def refresh(self, run_key: str, *, actor: ActorContext) -> ProjectionReceipt:
        """Re-project the run's transcript documents now (the projection job, on demand)."""

        if READ_PERMISSION not in actor.permissions:
            raise TranscriptDenied("actor lacks workflow_run.read")
        return await self._projector.project(run_key)

    async def search(
        self, run_key: str, text: str, *, actor: ActorContext, limit: int = 20
    ) -> TranscriptSearchPage:
        if READ_PERMISSION not in actor.permissions:
            raise TranscriptDenied("actor lacks workflow_run.read")
        if not text or not text.strip() or len(text) > 512:
            raise TranscriptSearchInvalid("search text must be 1 to 512 characters")
        if not 1 <= limit <= MAX_SEARCH_HITS:
            raise TranscriptSearchInvalid(f"limit must be between 1 and {MAX_SEARCH_HITS}")
        entries = await self._transcripts.entries_v2(run_key)
        receipt = (
            await self._documents.replace(
                self.request_scope, run_key, transcript_documents(entries)
            )
            if self._refresh
            else None
        )
        ranked = await self._documents.search(self.request_scope, run_key, text, limit=limit)
        positions = {entry.cursor: index for index, entry in enumerate(entries)}
        hits: list[TranscriptSearchHit] = []
        for cursor, rank in ranked:
            index = positions.get(cursor)
            if index is None:
                continue  # projected before a rebuild removed it; never shown stale
            hits.append(
                TranscriptSearchHit(
                    rank=rank,
                    entry=entries[index],
                    open_cursor=entries[index - 1].cursor if index > 0 else None,
                )
            )
        return TranscriptSearchPage(
            run_id=run_key, query=text, hits=tuple(hits), projection=receipt
        )


__all__ = [
    "ProjectionMarks",
    "ProjectionReceipt",
    "RunListPage",
    "RunListRow",
    "RunListService",
    "RunListUnavailable",
    "TranscriptDocument",
    "TranscriptEntryReceipt",
    "TranscriptEntryStoreWriter",
    "TranscriptProjector",
    "TranscriptSearchHit",
    "TranscriptSearchInvalid",
    "TranscriptSearchPage",
    "TranscriptSearchService",
    "VisibilityExecution",
]

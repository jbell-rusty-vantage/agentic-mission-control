"""Transcript materialization: mission events + provider frames + artifacts (SPEC-03, C3).

`materialize` is a streaming-shaped merge of three ordered sources for one run:

1. mission events by `seq` (canonical; `artifact.*` events are the artifact source,
   enriched with digest and media type from their payload; `human_task.*` render as
   `human`, commands and lifecycle results as `mission_control`);
2. provider frames by arrival order, each placed under its governing event (the latest
   mission event recorded at or before the frame was observed), never canonical;
3. `frame_expired` placeholders for events whose cited frame has left the Native Event
   Store under retention, carrying the digest the event recorded.

Entries carry an opaque cursor that increases strictly within the run; `since` resumes
after a cursor, and a cursor older than retention simply yields canonical entries plus
placeholders.

1.4.4 (TRACING-PROPOSAL P3.2, P4.1, P4.2): placement **by unit and point when known, by time
otherwise**. The cursor keeps the v1 rule (a frame sorts by time under its governing event),
so ordering is unchanged; what v2 adds is *where* each entry belongs: a frame's `point_id`
is the cognition point whose frame range (same harness execution and generation) contains
its arrival ordinal, else the root point its Deep Agents key names (`after_point_ref`); its
unit, node, cycle, iteration and session generation come from that point's record, or from
the activation when no point is known (the events of an activation carry `unit_key`). A
mission event carries its own `unit_key`, `activation_id` and `point_ref` (TR-D7); its
`point_id` is the ref resolved against the run's points by locator. The point index is read
through `CognitionPointRepository.list_points` when the service is composed with one;
**without a repository every point field stays None** (unit fields still come from events).

The Transcript is a view; the persisted projection (`transcript_entry`, P3.9) is written by
the projection activity from `entries_v2` and served through `TranscriptEntryStore` when it
is current, else materialized here.
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from mission_control.application.execution.cognition_points import (
    MAX_PAGE_SIZE,
    CognitionPointRepository,
)
from mission_control.application.frames.lineage import (
    Coverage,
    SubordinateNode,
    counts_usage_frame,
    provider_subordinates,
    usage_body,
    usage_rule,
)
from mission_control.application.frames.reducer import provider_result
from mission_control.application.frames.sink import FrameReader
from mission_control.application.frames.streams import deep_agents_after_point_ref
from mission_control.domain.execution.cognition_points import (
    CognitionPointFilter,
    CognitionPointRecord,
    UnitLocationFacts,
)
from mission_control.domain.frames.body import frame_body_object, redact_text
from mission_control.domain.frames.contracts import (
    FULL_BODY_KINDS,
    NATIVE_EVENT_REF_PREFIX,
    FrameKind,
    LaneProfile,
    ProviderFrame,
    frame_id_from_native_event_ref,
)
from mission_control.domain.frames.render import CANONICAL_MARK, FRAME_MARK, redacted_entry
from mission_control.domain.frames.transcript import (
    EVENT_TAG,
    CursorExpired,
    TranscriptBody,
    TranscriptBodyState,
    TranscriptCursor,
    TranscriptEntry,
    TranscriptExecution,
    TranscriptGroup,
    TranscriptGroupLevel,
    TranscriptPage,
    TranscriptQuery,
    TranscriptRefs,
    TranscriptRole,
    TranscriptSource,
    TranscriptTemporal,
)
from mission_control.domain.frames.usage import UsageReport, usage_report
from mission_control.domain.policies.contracts import ActorContext

READ_PERMISSION = "workflow_run.read"
EXCERPT_CHARS = 2_048
MAX_EVENTS = 20_000
MAX_FRAMES = 50_000
MAX_POINT_PAGES = 200
FULL_PAGE_BODY_BUDGET_BYTES = 16 * 1024 * 1024
"""Tracing Stage 3 (R4-F5): the bodies one `full=true` page may inline; past it an entry
keeps the bare reference and `body.truncated`."""
UNPLACED_KEY = "-"
ADMISSION_EVENT = "workflow_run.apply_authority_batch"
# Payload keys the family admission, result and cycle events may carry about a unit's
# lifecycle; what they lack (the proposal's `released_by` and `continues_from`, the
# completion decision row) lives in the journal and the completion tables, not in events.
STAGE_FACT_KEYS = (
    "decision",
    "disposition",
    "execution_disposition",
    "evaluation",
    "released_by",
    "continues_from",
    "completion_decision",
    "cycle_ordinal",
)

_AGENT_FRAMES = frozenset({FrameKind.MESSAGE, FrameKind.MESSAGE_DELTA, FrameKind.THINKING_DELTA})
_TOOL_FRAMES = frozenset(
    {
        FrameKind.TOOL_CALL_STARTED,
        FrameKind.TOOL_CALL_DELTA,
        FrameKind.TOOL_CALL_COMPLETED,
        FrameKind.TOOL_CALL_FAILED,
    }
)
_HUMAN_FRAMES = frozenset({FrameKind.APPROVAL_REQUESTED, FrameKind.APPROVAL_RESOLVED})


class TranscriptDenied(PermissionError):
    code = "unauthorized"


class TranscriptRunNotFound(LookupError):
    code = "resource_not_found"


class FullBodyUnavailable(RuntimeError):
    """`--full` needs an artifact read path that checks the caller's grant; none is wired."""

    code = "full_body_unavailable"


class ArtifactBodyReader(Protocol):
    """Reads a referenced body artifact under the caller's artifact read grant."""

    async def read(self, request_scope: str, actor: ActorContext, artifact_ref: str) -> str: ...


class FamilyFactsReader(Protocol):
    """The lifecycle facts of a run's units that live outside the event stream (1.4.4,
    P4.2 `--by stage`): the family journal's proposals (`released_by`, `continues_from`,
    the cycle decisions) and the completion decision rows, keyed by unit key."""

    async def unit_facts(
        self, request_scope: str, run_key: str
    ) -> Mapping[str, Mapping[str, Any]]: ...


class TranscriptEntryStore(Protocol):
    """The persisted Transcript projection (1.4.4 `transcript_entry`, P3.9), read side.

    `current_entries` returns the run's whole projected transcript in order when the
    projection is current (its state row names the run's latest settled event and frame),
    and None when it is behind or absent, in which case the service materializes.
    """

    async def current_entries(
        self, request_scope: str, run_key: str
    ) -> tuple[TranscriptEntry, ...] | None: ...

    async def projected_entries(
        self, request_scope: str, run_key: str
    ) -> tuple[TranscriptEntry, ...]:
        """The persisted rows whether or not they are current (empty when none)."""
        ...


@dataclass(frozen=True)
class MissionEventRecord:
    """One persisted mission event of the run (the ledger's `mission_event` row): `payload`
    is the envelope as written (`DomainEventEnvelope`, with `unit_key`, `activation_id` and
    `point_ref` at its top level when the writer knew them)."""

    seq: int
    event_id: str
    event_type: str
    recorded_at: datetime
    actor_ref: str
    payload: Mapping[str, Any]


class MissionEventReader(Protocol):
    async def run_identity(self, request_scope: str, run_key: str) -> UUID | None: ...

    async def events_for_run(
        self, request_scope: str, run_key: str, *, limit: int = MAX_EVENTS
    ) -> tuple[MissionEventRecord, ...]: ...


@dataclass(frozen=True)
class SessionSummary:
    """Per harness execution summary for inspection (F6 consumes `summarize_sessions`)."""

    harness_execution_id: str
    lane_profile: str
    generation: int
    native_session_refs: tuple[str, ...]
    turns_closed: int
    tool_calls: int
    last_frame_kind: str | None
    last_observed_at: datetime | None
    run_result_status: str | None
    usage: UsageReport | None
    subordinates: tuple[SubordinateNode, ...] = ()
    usage_coverage: Coverage = "complete"


@dataclass
class _FullReads:
    """Tracing Stage 3 (R4-F5): one `materialize(full=True)` call's body reads: each
    reference is read once (`texts`), and what the page inlines is bounded (`remaining`)."""

    remaining: int = FULL_PAGE_BODY_BUDGET_BYTES
    texts: dict[str, str | None] = field(default_factory=dict)

    def admit(self, text: str) -> bool:
        size = len(text.encode("utf-8"))
        if size > self.remaining:
            self.remaining = 0
            return False
        self.remaining -= size
        return True


@dataclass
class _Placed:
    cursor: TranscriptCursor
    entry: TranscriptEntry


@dataclass(frozen=True)
class _EventView:
    record: MissionEventRecord
    envelope: Mapping[str, Any]
    payload: Mapping[str, Any]
    execution: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Placement:
    """What a point (or, failing one, an activation's unit) says about an entry."""

    unit_key: str | None = None
    node_key: str | None = None
    cycle: int | None = None
    iteration: int | None = None
    session_generation: int | None = None
    point_id: str | None = None
    parent_point_id: str | None = None
    reused_from: str | None = None
    temporal: TranscriptTemporal | None = None
    harness_execution_id: str | None = None
    generation: int | None = None


@dataclass(frozen=True)
class _PointIndex:
    """The run's cognition points, indexed for placement (pure)."""

    by_id: Mapping[str, CognitionPointRecord]
    by_locator: Mapping[tuple[str, str], CognitionPointRecord]
    ranges: tuple[CognitionPointRecord, ...]
    location_by_unit: Mapping[str, UnitLocationFacts]

    @classmethod
    def build(cls, points: Iterable[CognitionPointRecord]) -> _PointIndex:
        by_id: dict[str, CognitionPointRecord] = {}
        by_locator: dict[tuple[str, str], CognitionPointRecord] = {}
        ranges: list[CognitionPointRecord] = []
        location_by_unit: dict[str, UnitLocationFacts] = {}
        for record in points:
            by_id[record.point_id] = record
            locator = (record.coordinate.kind, record.coordinate.locator)
            # A nested point shares no locator with a root one in practice; prefer the root.
            if locator not in by_locator or record.subordinate_ref is None:
                by_locator[locator] = record
            if record.frames is not None:
                ranges.append(record)
            location_by_unit.setdefault(record.coordinate.unit_key, record.location)
        return cls(by_id, by_locator, tuple(ranges), location_by_unit)

    def for_frame(self, frame: ProviderFrame, unit_key: str | None) -> CognitionPointRecord | None:
        harness = str(frame.harness_execution_id)
        candidates = [
            record
            for record in self.ranges
            if record.frames is not None
            and record.coordinate.execution_generation == frame.generation
            and (
                record.coordinate.harness_execution_id == harness
                if record.coordinate.harness_execution_id is not None
                else unit_key is not None and record.coordinate.unit_key == unit_key
            )
            and record.frames.from_ordinal <= frame.arrival_ordinal <= record.frames.to_ordinal
        ]
        if candidates:
            same = [r for r in candidates if r.subordinate_ref == frame.subordinate_ref]
            pool = same or candidates
            return min(pool, key=_range_width)
        after = deep_agents_after_point_ref(frame)
        if after is None:
            return None
        return self.by_locator.get(("checkpoint", str(after["checkpoint_id"])))

    def for_ref(self, ref: Mapping[str, Any]) -> CognitionPointRecord | None:
        kind = ref.get("kind")
        if not isinstance(kind, str):
            return None
        locator = ref.get("checkpoint_id") if kind == "checkpoint" else ref.get("locator")
        if not isinstance(locator, str) or not locator:
            return None
        return self.by_locator.get((kind, locator))


def _range_width(record: CognitionPointRecord) -> int:
    assert record.frames is not None
    return record.frames.to_ordinal - record.frames.from_ordinal


@dataclass(frozen=True)
class _MergeContext:
    points: _PointIndex
    unit_by_activation: Mapping[str, str]
    node_by_activation: Mapping[str, str]
    secret_values: Sequence[str]

    def from_point(self, record: CognitionPointRecord) -> _Placement:
        attempt = record.attempt
        return _Placement(
            unit_key=record.coordinate.unit_key,
            node_key=record.location.node_key,
            cycle=record.location.cycle,
            iteration=record.location.iteration,
            session_generation=record.location.session_generation,
            point_id=record.point_id,
            parent_point_id=record.parent_point_id,
            reused_from=_reused_from(record),
            temporal=(
                TranscriptTemporal(
                    workflow_id=attempt.temporal_workflow_id,
                    run_id=attempt.temporal_run_id,
                    activity_id=attempt.temporal_activity_id,
                    attempt=attempt.activity_attempt,
                )
                if attempt is not None
                else None
            ),
            harness_execution_id=record.coordinate.harness_execution_id,
            generation=record.coordinate.execution_generation,
        )

    def from_unit(self, unit_key: str | None, activation: str | None) -> _Placement:
        location = self.points.location_by_unit.get(unit_key) if unit_key else None
        if location is not None:
            return _Placement(
                unit_key=unit_key,
                node_key=location.node_key,
                cycle=location.cycle,
                iteration=location.iteration,
                session_generation=location.session_generation,
            )
        return _Placement(
            unit_key=unit_key,
            node_key=self.node_by_activation.get(activation) if activation else None,
        )


def _reused_from(record: CognitionPointRecord) -> str | None:
    if "reused" not in record.roles:
        return None
    if record.parent_point_id is not None:
        return record.parent_point_id
    parent = record.parent_coordinate
    if parent is None:
        return None
    return f"{parent.run_id}/{parent.unit_key}/{parent.execution_generation}/{parent.locator}"


def _excerpt(value: Any, secret_values: Sequence[str]) -> str | None:
    if value is None or value == {} or value == "":
        return None
    text = value if isinstance(value, str) else _canonical_json(value)
    return redact_text(text[:EXCERPT_CHARS], secret_values)[0]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _str(value: Any) -> str | None:
    return str(value) if isinstance(value, str | int) and str(value) else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _event_source_role(event_type: str) -> tuple[TranscriptSource, TranscriptRole]:
    family = event_type.split(".", 1)[0]
    if family == "artifact":
        return "artifact", "mission_control"
    if family == "human_task":
        return "human", "human"
    if family in {"command", "workflow_run"}:
        return "command", "mission_control"
    if family == "tool_call":
        return "mission_event", "tool"
    if family == "session":
        return "mission_event", "agent"
    return "mission_event", "mission_control"


def _event_title(event_type: str, payload: Mapping[str, Any]) -> str:
    parts = [event_type]
    if event_type == "tool_call.completed":
        parts.append(f"{payload.get('name') or payload.get('tool_call_ref') or 'tool'}")
        parts.append(str(payload.get("status") or ""))
    elif event_type in {"session.turn_started", "session.turn_completed"}:
        parts.append(f"turn {payload.get('turn_ordinal')}")
    elif event_type == "attempt.completed":
        parts.append(str(payload.get("outcome")))
        if payload.get("failure_class"):
            parts.append(f"({payload['failure_class']})")
    elif event_type.startswith("activation."):
        parts.append(str(payload.get("phase") or payload.get("lifecycle") or ""))
    elif event_type.startswith("workflow_run.") and (
        payload.get("prior_phase") or payload.get("resulting_phase")
    ):
        parts.append(
            f"{payload.get('prior_phase') or ''} -> {payload.get('resulting_phase') or ''}"
        )
    title = " ".join(part for part in parts if part and part != "None")
    return title[:512]


def _frame_role(kind: FrameKind) -> TranscriptRole:
    if kind in _AGENT_FRAMES:
        return "agent"
    if kind in _TOOL_FRAMES:
        return "tool"
    if kind in _HUMAN_FRAMES:
        return "human"
    return "system"


def _frame_title(frame: ProviderFrame, body: Mapping[str, Any]) -> str:
    parts = [frame.kind.value]
    name = body.get("name") or body.get("tool_name")
    if isinstance(name, str) and name:
        parts.append(name)
    if frame.tool_call_ref:
        parts.append(f"[{frame.tool_call_ref}]")
    status = body.get("status")
    if isinstance(status, str) and status and frame.kind != FrameKind.STATUS:
        parts.append(status)
    if frame.kind == FrameKind.STATUS and isinstance(status, str):
        parts.append(status)
    if frame.kind == FrameKind.UNKNOWN:
        parts.append(f"({frame.raw_kind})")
    return " ".join(parts)[:512]


def _usage_from_payload(payload: Mapping[str, Any]) -> UsageReport | None:
    usage = payload.get("usage")
    if isinstance(usage, Mapping) and "dimensions" in usage:
        try:
            return UsageReport.model_validate(usage)
        except ValueError:
            return None
    return None


def _cited_digest(payload: Mapping[str, Any]) -> str | None:
    for key in ("result_digest", "summary_digest", "args_digest"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("sha256:"):
            return value
    return None


def _event_body(
    source: TranscriptSource,
    payload: Mapping[str, Any],
    body: Mapping[str, Any],
    artifact_ref: str | None,
) -> TranscriptBody:
    if source == "artifact" and artifact_ref:
        return TranscriptBody(
            state="artifact",
            bytes=_int(payload.get("size_bytes")),
            media_type=_str(payload.get("media_type")),
            artifact_ref=artifact_ref,
        )
    text = _canonical_json(body)
    return TranscriptBody(
        state="inline" if len(text) <= EXCERPT_CHARS else "excerpt",
        bytes=len(text.encode("utf-8")),
        media_type="application/json",
    )


def keep_expired(
    projected: Sequence[TranscriptEntry], fresh: Sequence[TranscriptEntry]
) -> tuple[TranscriptEntry, ...]:
    """The fresh entries plus a `frame_expired` placeholder, at its own cursor, for every
    provider frame an earlier projection held and the Native Event Store no longer has
    (tracing Stage 2, F-S2-5).

    Retention deletes frames (the delta class, and step frames of terminal runs after their
    clock); no mission event cites a delta, so the cited-frame placeholder of `merge` never
    covers them and they would simply vanish from the Transcript. Arrival ordinals are not a
    substitute: the frame store leaves gaps where deduplicated provider keys kept their
    allocated ordinals. The projection is the record of what was there; a placeholder already
    written by an earlier pass is kept as it is.
    """

    present = {entry.refs.frame_id for entry in fresh if entry.refs.frame_id}
    cursors = {entry.cursor for entry in fresh}
    kept: list[TranscriptEntry] = []
    for entry in projected:
        frame_id = entry.refs.frame_id
        if (
            entry.source != "provider_frame"
            or not frame_id
            or frame_id in present
            or entry.cursor in cursors
        ):
            continue
        if entry.kind == "frame_expired":
            kept.append(entry)
            continue
        kept.append(
            entry.model_copy(
                update={
                    "kind": "frame_expired",
                    "role": "system",
                    "title": f"(frame expired: {entry.kind})",
                    "body_excerpt": None,
                    # Tracing Stage 3 (R4-F1): no reference survives either, so `--full`
                    # cannot re-read the promoted body of an expired frame.
                    "body": entry.body.model_copy(
                        update={"state": "expired", "artifact_ref": None}
                    ),
                    "refs": entry.refs.model_copy(update={"artifact_ref": None}),
                    "usage": None,
                }
            )
        )
    if not kept:
        return tuple(fresh)
    ordered = sorted([*fresh, *kept], key=lambda item: item.position)
    return tuple(
        entry.model_copy(update={"entry_seq": position})
        for position, entry in enumerate(ordered, start=1)
    )


def _entry_excerpt(frame: ProviderFrame) -> str:
    """The entry's excerpt: a full-body kind (model request, message, tool result, run result)
    keeps the whole body the frame stored, other kinds the list cap.

    Tracing Stage 2 (F-S2-8): the entry's `body.state` is computed from the frame's own
    excerpt (`inline` when it holds the whole body), so cutting a full-body kind at the list
    cap left `inline` entries whose JSON was truncated (34 of 54 live model requests), and a
    full read had nothing to resolve.
    """

    if frame.kind in FULL_BODY_KINDS:
        return frame.body_excerpt
    return frame.body_excerpt[:EXCERPT_CHARS]


def _frame_body(frame: ProviderFrame, excerpt: str) -> TranscriptBody:
    """Tracing Stage 3 (R4-F4): `inline` only when the entry's own `excerpt` (the list cap
    cuts a kind outside `FULL_BODY_KINDS`) holds the whole body, else `excerpt`."""

    state: TranscriptBodyState
    if frame.body_artifact_ref:
        state = "artifact"
    elif len(excerpt.encode("utf-8")) >= frame.body_bytes:
        state = "inline"
    else:
        state = "excerpt"
    return TranscriptBody(
        state=state,
        bytes=frame.body_bytes,
        media_type=frame.body_media_type,
        artifact_ref=frame.body_artifact_ref,
    )


class TranscriptService:
    """Materializes one tenant scope's run transcripts; authority: `workflow_run.read`.

    `points` (the cognition point index) places entries by unit and point; without it the
    point fields of every entry stay None. `entry_store` (the persisted projection) is read
    before materializing when present and current.
    """

    def __init__(
        self,
        events: MissionEventReader,
        frames: FrameReader,
        *,
        request_scope: str,
        secret_values: Sequence[str] = (),
        artifacts: ArtifactBodyReader | None = None,
        points: CognitionPointRepository | None = None,
        entry_store: TranscriptEntryStore | None = None,
        family_facts: FamilyFactsReader | None = None,
    ) -> None:
        self._events = events
        self._frames = frames
        self.request_scope = request_scope
        self._secrets = tuple(secret_values)
        self._artifacts = artifacts
        self._points = points
        self._entry_store = entry_store
        self._family_facts = family_facts

    def _authorize(self, actor: ActorContext) -> None:
        if READ_PERMISSION not in actor.permissions:
            raise TranscriptDenied("actor lacks workflow_run.read")

    async def _sources(
        self, run_key: str
    ) -> tuple[tuple[MissionEventRecord, ...], tuple[ProviderFrame, ...]]:
        run_uuid = await self._events.run_identity(self.request_scope, run_key)
        if run_uuid is None:
            raise TranscriptRunNotFound(f"run not found: {run_key}")
        events = await self._events.events_for_run(self.request_scope, run_key)
        frames = await self._frames.frames_for_run(self.request_scope, run_uuid, limit=MAX_FRAMES)
        return events, frames

    async def _run_points(self, run_key: str) -> tuple[CognitionPointRecord, ...]:
        """Every point of the run (`list_points`, empty filter, paged to completion)."""

        if self._points is None:
            return ()
        records: list[CognitionPointRecord] = []
        cursor: str | None = None
        for _ in range(MAX_POINT_PAGES):
            page = await self._points.list_points(
                self.request_scope,
                run_key,
                selection=CognitionPointFilter(),
                limit=MAX_PAGE_SIZE,
                cursor=cursor,
            )
            records.extend(page.entries)
            if page.next_cursor is None or not page.entries:
                break
            cursor = page.next_cursor
        return tuple(records)

    async def entries_v2(self, run_key: str) -> tuple[TranscriptEntry, ...]:
        """Every `mc.transcript_entry.v2` entry of the run, placed by unit and point, in
        transcript order: what the projection activity persists. No actor: the projection
        job indexes; reads authorize."""

        events, frames = await self._sources(run_key)
        points = await self._run_points(run_key)
        return tuple(
            item.entry
            for item in merge(run_key, events, frames, secret_values=self._secrets, points=points)
        )

    async def _current_entries(self, run_key: str) -> tuple[TranscriptEntry, ...]:
        if self._entry_store is not None:
            stored = await self._entry_store.current_entries(self.request_scope, run_key)
            if stored is not None:
                return stored
            # A stale projection still records frames retention has since deleted.
            projected = await self._entry_store.projected_entries(self.request_scope, run_key)
            return keep_expired(projected, await self.entries_v2(run_key))
        return await self.entries_v2(run_key)

    async def materialize(
        self,
        run_key: str,
        *,
        actor: ActorContext,
        query: TranscriptQuery | None = None,
        full: bool = False,
    ) -> TranscriptPage:
        self._authorize(actor)
        if full and self._artifacts is None:
            raise FullBodyUnavailable("full bodies need the artifact read API under the grant")
        query = query or TranscriptQuery()
        since = TranscriptCursor.decode(query.since) if query.since else None
        entries = await self._current_entries(run_key)
        selected: list[TranscriptEntry] = []
        has_more = False
        for entry in entries:
            if since is not None and entry.position <= since:
                continue
            if not _matches(entry, query):
                continue
            if len(selected) >= query.limit:
                has_more = True
                break
            selected.append(entry)
        if full and self._artifacts is not None:
            reads = _FullReads(remaining=FULL_PAGE_BODY_BUDGET_BYTES)
            selected = [await self._with_full_body(entry, actor, reads) for entry in selected]
        next_cursor = selected[-1].cursor if selected else query.since
        return TranscriptPage(
            run_id=run_key,
            entries=tuple(selected),
            next_cursor=next_cursor,
            has_more=has_more,
            groups=(
                group_entries(
                    selected,
                    query.by,
                    run_id=run_key,
                    unit_facts=(
                        await self._family_facts.unit_facts(self.request_scope, run_key)
                        if query.by == "stage" and self._family_facts is not None
                        else None
                    ),
                )
                if query.by
                else ()
            ),
        )

    @property
    def reads_full_bodies(self) -> bool:
        return self._artifacts is not None

    def with_artifacts(self, artifacts: ArtifactBodyReader) -> TranscriptService:
        """The same transcript view with `full=True` reading bodies through `artifacts`."""

        return TranscriptService(
            self._events,
            self._frames,
            request_scope=self.request_scope,
            secret_values=self._secrets,
            artifacts=artifacts,
            points=self._points,
            entry_store=self._entry_store,
            family_facts=self._family_facts,
        )

    async def _with_full_body(
        self, entry: TranscriptEntry, actor: ActorContext, reads: _FullReads
    ) -> TranscriptEntry:
        """A denied read fails the request; a missing or unadmitted body keeps the excerpt.
        A resolved body is whole in `body_excerpt` and `body.state` says `artifact`. A
        `model_request` also gets its system and message bodies (tracing Stage 2, F-S2-3).
        Past the page's body budget a body stays a reference and `body.truncated` is set."""

        if entry.body.state in {"expired", "pruned"}:
            # Tracing Stage 3 (R4-F1): retention removed the body; never resolve it again.
            return entry
        ref = entry.refs.artifact_ref
        if ref is not None and self._artifacts is not None:
            body = await self._read_body(actor, ref, reads)
            if body is not None and not reads.admit(body):
                entry = _truncated(entry)
            elif body is not None:
                entry = entry.model_copy(
                    update={
                        "body_excerpt": redact_text(body, self._secrets)[0],
                        "body": entry.body.model_copy(
                            update={
                                "state": "artifact",
                                "artifact_ref": entry.body.artifact_ref or ref,
                            }
                        ),
                    }
                )
        if entry.kind == "model_request":
            entry = await self._with_request_bodies(entry, actor, reads)
        return entry

    async def _read_body(self, actor: ActorContext, ref: str, reads: _FullReads) -> str | None:
        assert self._artifacts is not None
        if ref in reads.texts:
            return reads.texts[ref]
        try:
            text: str | None = await self._artifacts.read(self.request_scope, actor, ref)
        except PermissionError as error:
            raise TranscriptDenied(f"artifact read denied: {error}") from None
        except LookupError:
            text = None
        reads.texts[ref] = text
        return text

    async def _with_request_bodies(
        self, entry: TranscriptEntry, actor: ActorContext, reads: _FullReads
    ) -> TranscriptEntry:
        """The model request with what the model saw inline (tracing Stage 2, F-S2-3).

        The recorder promotes the system prompt and every message of the batch as their own
        `frame-body://` bodies and the `model_request` frame names them by reference, so a
        full read that resolves only the frame's own body still cannot show the prompt.
        Each resolved body is added beside its reference as `body` (parsed JSON when it is
        JSON); an unreadable one keeps the reference alone. Tracing Stage 3 (R4-F5): every
        reference is read once per page (a conversation repeats its earlier messages in each
        request) and the page's body budget bounds what is inlined.
        """

        try:
            request = json.loads(entry.body_excerpt or "")
        except ValueError:
            return entry
        if not isinstance(request, dict):
            return entry
        parts = [request.get("system"), *(request.get("messages") or [])]
        resolved = 0
        truncated = False
        for part in parts:
            ref = part.get("ref") if isinstance(part, dict) else None
            if not isinstance(ref, str) or not ref.startswith("frame-body://"):
                continue
            text = await self._read_body(actor, ref, reads)
            if text is None:
                continue
            if not reads.admit(text):
                truncated = True
                continue
            try:
                part["body"] = json.loads(text)
            except ValueError:
                part["body"] = text
            resolved += 1
        if truncated:
            entry = _truncated(entry)
        if not resolved:
            return entry
        rendered = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return entry.model_copy(update={"body_excerpt": redact_text(rendered, self._secrets)[0]})

    async def projection_entries(self, run_key: str) -> tuple[TranscriptEntry, ...]:
        """Every entry of the run, redacted, in transcript order (the C4 search projection
        source and the 1.4.4 transcript projection source; `entries_v2`)."""

        return await self.entries_v2(run_key)

    async def tail_frames(
        self,
        run_key: str,
        *,
        actor: ActorContext,
        after: str | None = None,
        limit: int = 500,
    ) -> TranscriptPage:
        """Non-canonical live tail over the Native Event Store (dashboards, `--follow`)."""

        page = await self.materialize(
            run_key,
            actor=actor,
            query=TranscriptQuery(since=after, limit=limit),
        )
        frames_only = tuple(entry for entry in page.entries if not entry.canonical)
        return page.model_copy(update={"entries": frames_only})

    async def inspection_summary(self, run_key: str, *, actor: ActorContext) -> RunFrameSummary:
        """FT-F6: sessions and the transcript cursor from persisted frames and events only."""

        self._authorize(actor)
        events, frames = await self._sources(run_key)
        placed = merge(run_key, events, frames, secret_values=self._secrets)
        return RunFrameSummary(
            sessions=summarize_sessions(frames),
            frame_count=len(frames),
            last_arrival_ordinal=max((frame.arrival_ordinal for frame in frames), default=None),
            transcript_cursor=placed[-1].entry.cursor if placed else None,
        )


def _truncated(entry: TranscriptEntry) -> TranscriptEntry:
    return entry.model_copy(update={"body": entry.body.model_copy(update={"truncated": True})})


def _matches(entry: TranscriptEntry, query: TranscriptQuery) -> bool:
    if query.canonical_only and not entry.canonical:
        return False
    if query.activation and entry.activation_id != query.activation:
        return False
    if query.node and entry.node_key != query.node:
        return False
    if query.kinds and entry.kind not in query.kinds:
        return False
    if query.unit and entry.unit_key != query.unit:
        return False
    if query.point and query.point not in (entry.point_id, entry.parent_point_id):
        return False
    return not (query.subordinate and entry.subordinate_ref != query.subordinate)


def _event_view(record: MissionEventRecord) -> _EventView:
    envelope = record.payload
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), Mapping) else envelope
    assert isinstance(payload, Mapping)
    execution = payload.get("execution")
    return _EventView(
        record=record,
        envelope=envelope,
        payload=payload,
        execution=execution if isinstance(execution, Mapping) else {},
    )


def _event_activation(view: _EventView) -> str | None:
    return _str(
        view.envelope.get("activation_id")
        or view.execution.get("activation_id")
        or view.payload.get("activation_id")
    )


def merge(
    run_key: str,
    events: Iterable[MissionEventRecord],
    frames: Iterable[ProviderFrame],
    *,
    secret_values: Sequence[str] = (),
    points: Iterable[CognitionPointRecord] = (),
) -> list[_Placed]:
    """The ordered transcript of one run (pure; deterministic for the same inputs).

    Order is the v1 cursor rule; `points` (the run's cognition point index, possibly empty)
    decides each entry's unit and point fields. `entry_seq` is the 1-based position in the
    merged list.
    """

    views = sorted((_event_view(record) for record in events), key=lambda item: item.record.seq)
    frame_list = sorted(
        frames,
        key=lambda frame: (
            str(frame.harness_execution_id),
            frame.generation,
            frame.arrival_ordinal,
        ),
    )
    stored = {str(frame.frame_id) for frame in frame_list}
    node_by_activation: dict[str, str] = {}
    unit_by_activation: dict[str, str] = {}
    for view in views:
        activation = _event_activation(view)
        node = _str(view.payload.get("node_key") or view.payload.get("stage_id"))
        unit = _str(view.envelope.get("unit_key"))
        if activation and node:
            node_by_activation.setdefault(activation, node)
        if activation and unit:
            unit_by_activation.setdefault(activation, unit)
    context = _MergeContext(
        points=_PointIndex.build(points),
        unit_by_activation=unit_by_activation,
        node_by_activation=node_by_activation,
        secret_values=secret_values,
    )
    placed: list[_Placed] = []
    recorded = [view.record.recorded_at for view in views]
    for view in views:
        placed.extend(_event_entries(run_key, view, stored, context))
    # Effective observation time is monotonic within one execution generation, so a
    # writer clock step backwards cannot reorder frames against their arrival order.
    effective: dict[tuple[str, int], datetime] = {}
    for frame in frame_list:
        if frame.lane_profile == "cursor_cloud" and frame.raw_kind == "raw.interaction_update":
            # The native store retains the duplicate rich-event family for audit; only
            # the selected interaction-delta family materializes transcript content.
            continue
        key = (str(frame.harness_execution_id), frame.generation)
        at = max(frame.observed_at, effective.get(key, frame.observed_at))
        effective[key] = at
        index = bisect.bisect_right(recorded, at) - 1
        seq = views[index].record.seq if index >= 0 else 0
        cursor = TranscriptCursor(
            seq=seq,
            observed_us=int(at.timestamp() * 1_000_000),
            ordinal=frame.arrival_ordinal,
            tag=frame.harness_execution_id.hex[:8],
        )
        placed.append(_Placed(cursor, _frame_entry(run_key, frame, cursor, context)))
    placed.sort(key=lambda item: item.cursor)
    return [
        _Placed(item.cursor, item.entry.model_copy(update={"entry_seq": position}))
        for position, item in enumerate(placed, start=1)
    ]


def _event_entries(
    run_key: str,
    view: _EventView,
    stored: set[str],
    context: _MergeContext,
) -> list[_Placed]:
    record, payload, execution = view.record, view.payload, view.execution
    secret_values = context.secret_values
    source, role = _event_source_role(record.event_type)
    cursor = TranscriptCursor(seq=record.seq)
    source_ref = payload.get("source")
    native_ref = (
        _str(source_ref.get("native_event_ref")) if isinstance(source_ref, Mapping) else None
    )
    body = {
        key: value for key, value in payload.items() if key not in {"execution", "source", "usage"}
    }
    artifact_ref = (
        _str(payload.get("artifact_ref") or payload.get("durable_reference") or payload.get("ref"))
        if source == "artifact"
        else None
    )
    activation = _event_activation(view)
    unit_key = _str(view.envelope.get("unit_key")) or (
        context.unit_by_activation.get(activation) if activation else None
    )
    point_ref = view.envelope.get("point_ref")
    point_ref = dict(point_ref) if isinstance(point_ref, Mapping) else None
    point = context.points.for_ref(point_ref) if point_ref is not None else None
    placement = (
        context.from_point(point) if point is not None else context.from_unit(unit_key, activation)
    )
    node_key = (
        placement.node_key
        or _str(payload.get("node_key") or payload.get("stage_id"))
        or (context.node_by_activation.get(activation) if activation else None)
    )
    harness = _str(execution.get("harness_execution_id")) or placement.harness_execution_id
    generation = _int(execution.get("generation")) or placement.generation
    entry = TranscriptEntry(
        cursor=cursor.encode(),
        run_id=run_key,
        unit_key=placement.unit_key or unit_key,
        activation_id=activation,
        attempt_no=_int(execution.get("attempt_no")),
        node_key=node_key,
        cycle=placement.cycle,
        iteration=(
            placement.iteration
            if placement.iteration is not None
            else _int(payload.get("goal_iteration") or payload.get("iteration"))
        ),
        session_generation=placement.session_generation,
        point_id=placement.point_id,
        parent_point_id=placement.parent_point_id,
        subordinate_ref=_str(payload.get("subordinate_ref")),
        reused_from=placement.reused_from,
        at=record.recorded_at,
        source=source,
        kind=record.event_type,
        role=role,
        title=redact_text(_event_title(record.event_type, payload), secret_values)[0],
        body_excerpt=_excerpt(body, secret_values),
        body=_event_body(source, payload, body, artifact_ref),
        execution=(
            TranscriptExecution(
                harness_execution_id=harness,
                generation=generation,
                arrival_ordinal=_int(execution.get("arrival_ordinal")),
                native_turn_ref=_str(execution.get("native_turn_ref")),
                temporal=placement.temporal,
            )
            if harness and generation
            else None
        ),
        refs=TranscriptRefs(
            event_id=record.event_id,
            native_event_ref=native_ref,
            artifact_ref=artifact_ref,
            tool_call_ref=_str(payload.get("tool_call_ref")),
            command_id=_str(payload.get("command_id")),
            human_task_id=_str(payload.get("human_task_id")),
            body_digest=(
                _str(payload.get("content_digest") or payload.get("digest"))
                if source == "artifact"
                else _cited_digest(payload)
            ),
            point_ref=point_ref,
        ),
        usage=_usage_from_payload(payload),
        canonical=True,
    )
    placed = [_Placed(cursor, entry)]
    if native_ref and native_ref.startswith(NATIVE_EVENT_REF_PREFIX):
        frame_id = str(frame_id_from_native_event_ref(native_ref))
        if frame_id not in stored:
            digest = _cited_digest(payload)
            marker = TranscriptCursor(seq=record.seq, tag="e" + frame_id.replace("-", "")[:7])
            placed.append(
                _Placed(
                    marker,
                    entry.model_copy(
                        update={
                            "cursor": marker.encode(),
                            "source": "provider_frame",
                            "kind": "frame_expired",
                            "role": "system",
                            "title": (
                                f"(frame expired, digest {digest})" if digest else "(frame expired)"
                            ),
                            "body_excerpt": None,
                            "body": TranscriptBody(state="expired"),
                            "refs": TranscriptRefs(
                                frame_id=frame_id, native_event_ref=native_ref, body_digest=digest
                            ),
                            "usage": None,
                            "canonical": False,
                        }
                    ),
                )
            )
    return placed


def _frame_entry(
    run_key: str,
    frame: ProviderFrame,
    cursor: TranscriptCursor,
    context: _MergeContext,
) -> TranscriptEntry:
    secret_values = context.secret_values
    body = frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body)
    usage = (
        usage_report(frame.lane_profile, [(str(frame.frame_id), body)])
        if frame.kind in (FrameKind.TURN_ENDED, FrameKind.USAGE) and body
        else None
    )
    if usage is not None and all(item.value is None for item in usage.dimensions.values()):
        usage = None
    activation = str(frame.activation_id)
    unit_key = context.unit_by_activation.get(activation)
    point = context.points.for_frame(frame, unit_key)
    placement = (
        context.from_point(point) if point is not None else context.from_unit(unit_key, activation)
    )
    excerpt = _entry_excerpt(frame)
    return TranscriptEntry(
        cursor=cursor.encode(),
        run_id=run_key,
        unit_key=placement.unit_key or unit_key,
        activation_id=activation,
        attempt_no=frame.attempt_no,
        node_key=placement.node_key,
        cycle=placement.cycle,
        iteration=placement.iteration,
        session_generation=placement.session_generation,
        point_id=placement.point_id,
        parent_point_id=placement.parent_point_id,
        subordinate_ref=frame.subordinate_ref,
        reused_from=placement.reused_from,
        at=frame.observed_at,
        source="provider_frame",
        kind=frame.kind.value,
        role=_frame_role(frame.kind),
        title=redact_text(_frame_title(frame, body), secret_values)[0],
        body_excerpt=redact_text(excerpt, secret_values)[0] or None,
        body=_frame_body(frame, excerpt),
        execution=TranscriptExecution(
            harness_execution_id=str(frame.harness_execution_id),
            generation=frame.generation,
            arrival_ordinal=frame.arrival_ordinal,
            native_turn_ref=frame.native_turn_ref,
            temporal=placement.temporal,
        ),
        refs=TranscriptRefs(
            frame_id=str(frame.frame_id),
            native_event_ref=frame.native_event_ref,
            artifact_ref=frame.body_artifact_ref,
            tool_call_ref=frame.tool_call_ref,
            body_digest=frame.body_digest,
        ),
        usage=usage,
        canonical=False,
    )


# --- Grouping (P4.2) -----------------------------------------------------------------------


def _group_key(entry: TranscriptEntry, level: TranscriptGroupLevel, run_id: str) -> str:
    if level == "step":
        return entry.point_id or UNPLACED_KEY
    if level == "turn":
        execution = entry.execution
        if execution is None or not execution.native_turn_ref:
            return UNPLACED_KEY
        return f"{execution.harness_execution_id}:{execution.native_turn_ref}"
    if level == "attempt":
        if entry.activation_id is None:
            return UNPLACED_KEY
        return f"{entry.activation_id}:{entry.attempt_no or '-'}"
    if level == "stage":
        return entry.unit_key or UNPLACED_KEY
    if level == "iteration":
        return str(entry.iteration) if entry.iteration is not None else UNPLACED_KEY
    return run_id


def _payload_of(entry: TranscriptEntry) -> dict[str, Any]:
    if not entry.canonical or not entry.body_excerpt:
        return {}
    try:
        value = json.loads(entry.body_excerpt)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _group_title(level: TranscriptGroupLevel, key: str, first: TranscriptEntry, run_id: str) -> str:
    if key == UNPLACED_KEY:
        return f"entries without a {'point' if level == 'step' else level}"
    where = ""
    if first.node_key:
        where = f" · {first.node_key}"
        if first.cycle is not None:
            where += f" cycle {first.cycle}"
    if level == "step":
        title = f"step {key[:8]}{where}"
        if first.subordinate_ref:
            title += f" · subagent {first.subordinate_ref}"
        return title
    if level == "turn":
        assert first.execution is not None
        return f"turn {first.execution.native_turn_ref} · execution {key[:8]}{where}"
    if level == "attempt":
        return f"activation {first.activation_id} attempt {first.attempt_no or '-'}{where}"
    if level == "stage":
        return f"stage{where or ' ?'} · unit {key[-12:]}"
    if level == "iteration":
        return f"iteration {key}"
    return f"run {run_id}"


def _stage_facts(items: Sequence[TranscriptEntry]) -> dict[str, Any]:
    """What the unit's events say (`released_by`/`continues_from` and the completion
    decision row are journal and table facts, outside the event stream)."""

    admissions: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for entry in items:
        payload = _payload_of(entry)
        if not payload:
            continue
        if entry.kind == ADMISSION_EVENT:
            admissions.append(
                {
                    "command_id": payload.get("command_id"),
                    "prior_phase": payload.get("prior_phase"),
                    "resulting_phase": payload.get("resulting_phase"),
                    "actions": payload.get("action_identity_summary"),
                    "cursor": entry.cursor,
                }
            )
        facts = {key: payload[key] for key in STAGE_FACT_KEYS if key in payload}
        if facts:
            decisions.append({"kind": entry.kind, "cursor": entry.cursor, **facts})
    return {"admissions": admissions, "decisions": decisions}


def group_entries(
    entries: Sequence[TranscriptEntry],
    level: TranscriptGroupLevel,
    *,
    run_id: str,
    unit_facts: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[TranscriptGroup, ...]:
    """The page's entries grouped at `level`, in order of first appearance (pure).

    `step` groups by point (one group per point: its frames and the lifecycle events whose
    `point_ref` names it); `turn` by harness execution and native turn; `attempt` by
    activation and attempt; `stage` by unit key with the admission and decision facts its
    events carry; `iteration` by the Goal iteration (a Stage Graph's workflow cycle);
    `mission` is one group. Entries the level cannot place share the `-` group.
    """

    buckets: dict[str, list[TranscriptEntry]] = {}
    for entry in entries:
        buckets.setdefault(_group_key(entry, level, run_id), []).append(entry)
    groups: list[TranscriptGroup] = []
    for key, items in buckets.items():
        first = items[0]
        canonical = sum(1 for item in items if item.canonical)
        facts: dict[str, Any] = {
            "entries": len(items),
            "events": canonical,
            "frames": len(items) - canonical,
            "points": sorted({item.point_id for item in items if item.point_id}),
            "activations": sorted({item.activation_id for item in items if item.activation_id}),
        }
        if level == "step" and key != UNPLACED_KEY:
            facts["child_points"] = sorted(
                {
                    item.point_id
                    for item in entries
                    if item.parent_point_id == key and item.point_id and item.point_id != key
                }
            )
        if level == "stage":
            facts.update(_stage_facts(items))
            # The journal's proposal and the completion row of the unit (P4.2): released-by,
            # continues-from, the decision and the cycle it took part in.
            if unit_facts is not None and first.unit_key is not None:
                facts.update(unit_facts.get(first.unit_key, {}))
        groups.append(
            TranscriptGroup(
                level=level,
                key=key,
                title=_group_title(level, key, first, run_id),
                unit_key=first.unit_key,
                point_id=first.point_id if level == "step" and key != UNPLACED_KEY else None,
                node_key=first.node_key,
                cycle=first.cycle,
                iteration=first.iteration,
                entry_cursors=tuple(item.cursor for item in items),
                facts=facts,
            )
        )
    return tuple(groups)


def render_groups_jsonl(page: TranscriptPage, *, secret_values: Sequence[str] = ()) -> str:
    """One JSON object per group with its entries inline (sorted keys, no whitespace)."""

    by_cursor = {entry.cursor: entry for entry in page.entries}
    lines = []
    for group in page.groups:
        record = group.model_dump(mode="json", exclude_none=True)
        record["entries"] = [
            redacted_entry(by_cursor[cursor], secret_values).model_dump(
                mode="json", exclude_none=True
            )
            for cursor in group.entry_cursors
            if cursor in by_cursor
        ]
        lines.append(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return "".join(f"{line}\n" for line in lines)


def render_groups_markdown(
    page: TranscriptPage, *, run_id: str, secret_values: Sequence[str] = ()
) -> str:
    """A heading per group, one bullet per entry (`✓` canonical, `·` provider frame)."""

    level = page.groups[0].level if page.groups else "mission"
    by_cursor = {entry.cursor: entry for entry in page.entries}
    lines = [
        f"# Transcript · run {run_id} · by {level}",
        "",
        f"_Legend: {CANONICAL_MARK} canonical mission event; {FRAME_MARK} provider frame "
        "(evidence, not state)_",
    ]
    for group in page.groups:
        lines.extend(["", f"## {group.title}", "", f"_key: `{group.key}`_"])
        facts = {
            key: value
            for key, value in group.facts.items()
            if key not in {"entries", "events", "frames"} and value
        }
        if facts:
            lines.append(f"_facts: `{_canonical_json(facts)}`_")
        lines.append("")
        for cursor in group.entry_cursors:
            raw = by_cursor.get(cursor)
            if raw is None:
                continue
            entry = redacted_entry(raw, secret_values)
            mark = CANONICAL_MARK if entry.canonical else FRAME_MARK
            clock = entry.at.strftime("%H:%M:%S")
            line = f"- {mark} {clock} · {entry.role or 'system'} · {entry.title}"
            if entry.body.state == "artifact" and entry.body.artifact_ref:
                line += f" _(body: {entry.body.artifact_ref})_"
            elif entry.body.state in {"expired", "pruned"}:
                line += f" _({entry.body.state})_"
            lines.append(line)
    lines.append("")
    return "\n".join(lines)


@dataclass(frozen=True)
class RunFrameSummary:
    """What inspection reads from the Native Event Store (never a provider call)."""

    sessions: tuple[SessionSummary, ...]
    frame_count: int
    last_arrival_ordinal: int | None
    transcript_cursor: str | None


def _known_usage(
    lane: LaneProfile, bodies: Sequence[tuple[str, Mapping[str, Any]]]
) -> UsageReport | None:
    if not bodies:
        return None
    report = usage_report(lane, bodies)
    known = any(item.value is not None for item in report.dimensions.values())
    return report if known else None


def summarize_sessions(frames: Sequence[ProviderFrame]) -> tuple[SessionSummary, ...]:
    """Per harness execution: lane, generation, sessions, turns, tool calls, usage.

    Turns, tool calls and the run result are the parent's own; provider subagents are listed
    in `subordinates` with their visibility. Usage folds a subagent's usage frames only where
    the lane's writer reports them as separate model calls (`lineage.usage_rule`), and says
    when the provider total excludes subagents.
    """

    grouped: dict[tuple[str, int], list[ProviderFrame]] = {}
    for frame in frames:
        grouped.setdefault((str(frame.harness_execution_id), frame.generation), []).append(frame)
    summaries: list[SessionSummary] = []
    for (harness, generation), items in sorted(grouped.items()):
        items.sort(key=lambda frame: frame.arrival_ordinal)
        lane = items[0].lane_profile
        own = [frame for frame in items if frame.subordinate_ref is None]
        subordinates = provider_subordinates(items)
        usage_bodies = [
            (
                str(frame.frame_id),
                usage_body(
                    lane,
                    frame_body_object(frame.body_excerpt, frame.body_bytes, frame.lifecycle_body),
                ),
            )
            for frame in items
            if frame.kind == FrameKind.USAGE and counts_usage_frame(lane, frame.subordinate_ref)
        ]
        turn_ends = list(
            {
                (frame.native_turn_ref or str(frame.frame_id)): frame
                for frame in own
                if frame.kind == FrameKind.TURN_ENDED
            }.values()
        )
        if not usage_bodies:
            usage_bodies = [
                (
                    str(frame.frame_id),
                    usage_body(
                        lane,
                        frame_body_object(
                            frame.body_excerpt, frame.body_bytes, frame.lifecycle_body
                        ),
                    ),
                )
                for frame in turn_ends
            ]
            usage_bodies = [(frame_id, body) for frame_id, body in usage_bodies if body]
        result = next(
            (frame for frame in reversed(own) if frame.kind == FrameKind.RUN_RESULT), None
        )
        status = (
            provider_result(
                lane,
                frame_body_object(result.body_excerpt, result.body_bytes, result.lifecycle_body),
            )[0]
            if result is not None
            else None
        )
        excludes = bool(subordinates) and usage_rule(lane, "provider_subagent").tokens in {
            "unattributable",
            "provider_inclusive",
        }
        summaries.append(
            SessionSummary(
                harness_execution_id=harness,
                lane_profile=lane.value,
                generation=generation,
                native_session_refs=tuple(
                    dict.fromkeys(frame.native_session_ref for frame in own or items)
                ),
                turns_closed=len(turn_ends),
                tool_calls=len(
                    {
                        frame.tool_call_ref
                        for frame in own
                        if frame.tool_call_ref
                        and frame.kind
                        in (FrameKind.TOOL_CALL_COMPLETED, FrameKind.TOOL_CALL_FAILED)
                    }
                ),
                last_frame_kind=items[-1].kind.value,
                last_observed_at=items[-1].observed_at,
                run_result_status=status if status and status != "unknown" else None,
                usage=_known_usage(lane, usage_bodies),
                subordinates=subordinates,
                usage_coverage="excludes_subordinates" if excludes else "complete",
            )
        )
    return tuple(summaries)


__all__ = [
    "EVENT_TAG",
    "CursorExpired",
    "MissionEventReader",
    "MissionEventRecord",
    "RunFrameSummary",
    "SessionSummary",
    "TranscriptDenied",
    "TranscriptEntryStore",
    "TranscriptRunNotFound",
    "TranscriptService",
    "group_entries",
    "merge",
    "render_groups_jsonl",
    "render_groups_markdown",
    "summarize_sessions",
]

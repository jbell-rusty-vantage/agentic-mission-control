"""`mc.transcript_entry.v2`: one line of a run's materialized Transcript (SPEC-03 C3; 1.4.4 P4.1).

The Transcript is a read view, never state: it merges the run's canonical mission events
(by `seq`) with provider frames (by arrival order, placed under their governing event)
into entries with an opaque cursor that increases strictly within a run.

Cursor: ``tc1:<seq>:<observed_us>:<ordinal>:<tag>`` (fixed-width, so it also sorts as a
string). A mission event is ``(seq, 0, 0, "00000000")``; a frame is ``(seq of its
governing event, effective observed time in microseconds, arrival ordinal, first eight
hex digits of its harness execution)``; a `frame_expired` placeholder sits right after the
event that cites the expired frame. The governing mission `seq` comes first, so the
transcript and the canonical event stream advance together. The cursor is unchanged by v2.

v2 is additive over v1 (TRACING-PROPOSAL P4.1): every entry says which unit, activation,
attempt and cognition point it belongs to (`unit_key`, `activation_id`, `attempt_no`,
`node_key`, `cycle`, `iteration`, `session_generation`, `point_id`, `parent_point_id`,
`subordinate_ref`, `reused_from`), its position in the run's merged list (`entry_seq`, 1-based),
where its body is (`body`), and the harness execution and Temporal attempt that produced it
(`execution`). `iteration_id` (v1, a string nobody read) is replaced by the integer
`iteration` of the unit's location. Entries can be grouped at six granularities (P4.2
`--by`); a `TranscriptGroup` names its level, its key and the cursors of its entries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from mission_control.domain.frames.contracts import FrameContract
from mission_control.domain.frames.usage import UsageReport

TRANSCRIPT_ENTRY_SCHEMA = "mc.transcript_entry.v2"
CURSOR_PATTERN = re.compile(r"^tc1:(\d{12}):(\d{17}):(\d{12}):([0-9a-z]{8})$")
EVENT_TAG = "00000000"

TranscriptSource = Literal["mission_event", "provider_frame", "artifact", "human", "command"]
TranscriptRole = Literal["system", "agent", "tool", "human", "mission_control"]
TranscriptBodyState = Literal["inline", "excerpt", "artifact", "expired", "pruned"]
TranscriptGroupLevel = Literal["step", "turn", "attempt", "stage", "iteration", "mission"]
GROUP_LEVELS: tuple[TranscriptGroupLevel, ...] = (
    "step",
    "turn",
    "attempt",
    "stage",
    "iteration",
    "mission",
)


class CursorExpired(ValueError):
    """`CURSOR_EXPIRED`: the cursor is malformed or names no position in this run."""

    code = "CURSOR_EXPIRED"


@dataclass(frozen=True, order=True)
class TranscriptCursor:
    seq: int
    observed_us: int = 0
    ordinal: int = 0
    tag: str = EVENT_TAG

    def encode(self) -> str:
        return f"tc1:{self.seq:012d}:{self.observed_us:017d}:{self.ordinal:012d}:{self.tag}"

    @classmethod
    def decode(cls, value: str) -> TranscriptCursor:
        match = CURSOR_PATTERN.fullmatch(value or "")
        if match is None:
            raise CursorExpired("transcript cursor is malformed")
        seq, observed, ordinal, tag = match.groups()
        return cls(int(seq), int(observed), int(ordinal), tag)


class TranscriptRefs(FrameContract):
    event_id: str | None = None
    frame_id: str | None = None
    native_event_ref: str | None = None
    artifact_ref: str | None = None
    tool_call_ref: str | None = None
    command_id: str | None = None
    human_task_id: str | None = None
    body_digest: str | None = None
    # 1.4.4 (TR-D7): the cognition point reference the mission event carried verbatim
    # (`{"kind": "checkpoint", "thread_id", "checkpoint_ns", "checkpoint_id", "relation"}`);
    # `point_id` on the entry is its resolution against the run's point index.
    point_ref: dict[str, Any] | None = None


class TranscriptBody(FrameContract):
    """Where the entry's body is (P4.1): `inline` (the whole body is the excerpt), `excerpt`
    (capped, nothing more to read), `artifact` (the whole body resolves through
    `artifact_ref`; `full=true` inlines it), `expired` (a delta frame left the Native Event
    Store under retention), `pruned` (reserved for the pruning session, TR-D17)."""

    state: TranscriptBodyState
    bytes: int | None = Field(default=None, ge=0)
    media_type: str | None = None
    artifact_ref: str | None = None
    truncated: bool | None = None
    """Tracing Stage 3 (R4-F5): a `full=true` read hit the page's body budget, so a body
    this entry references (its own, or a model request's message) kept the bare reference.
    Absent otherwise; never persisted (projections are not full reads)."""


class TranscriptTemporal(FrameContract):
    """The Temporal activity attempt that wrote the entry's point (`AttemptFacts`)."""

    workflow_id: str
    run_id: str
    activity_id: str
    attempt: int = Field(ge=1)


class TranscriptExecution(FrameContract):
    """The harness execution the entry came from; a mission event without one has None."""

    harness_execution_id: str
    generation: int = Field(ge=1)
    arrival_ordinal: int | None = Field(default=None, ge=1)
    native_turn_ref: str | None = None
    temporal: TranscriptTemporal | None = None


class TranscriptEntry(FrameContract):
    """`TranscriptEntry@2` (`mc.transcript_entry.v2`)."""

    schema_version: Literal["mc.transcript_entry.v2"] = "mc.transcript_entry.v2"
    cursor: str = Field(pattern=CURSOR_PATTERN.pattern)
    # 1-based position in the run's merged transcript; None for an entry built outside a merge.
    entry_seq: int | None = Field(default=None, ge=1)
    run_id: str = Field(min_length=1)
    unit_key: str | None = None
    activation_id: str | None = None
    attempt_no: int | None = None
    node_key: str | None = None
    cycle: int | None = Field(default=None, ge=0)
    iteration: int | None = Field(default=None, ge=0)
    session_generation: int | None = Field(default=None, ge=1)
    point_id: str | None = None
    parent_point_id: str | None = None
    subordinate_ref: str | None = None
    # P5.5: the source run's result point a `reused` unit was settled by reference to.
    reused_from: str | None = None
    at: AwareDatetime
    source: TranscriptSource
    kind: str = Field(min_length=1)
    role: TranscriptRole | None = None
    title: str = Field(min_length=1, max_length=512)
    body_excerpt: str | None = None
    body: TranscriptBody
    execution: TranscriptExecution | None = None
    refs: TranscriptRefs = Field(default_factory=TranscriptRefs)
    usage: UsageReport | None = None
    canonical: bool

    @property
    def position(self) -> TranscriptCursor:
        return TranscriptCursor.decode(self.cursor)


class TranscriptQuery(FrameContract):
    """Filters shared by the CLI, HTTP and MCP surfaces.

    `by` asks for groups at one granularity (P4.2) beside the flat entries; `point`
    restricts to one point's entries and its children's (`parent_point_id`); `unit` to one
    unit key.
    """

    since: str | None = None
    activation: str | None = None
    node: str | None = None
    kinds: frozenset[str] = frozenset()
    canonical_only: bool = False
    subordinate: str | None = None
    limit: int = Field(default=500, ge=1, le=5_000)
    by: TranscriptGroupLevel | None = None
    point: str | None = None
    unit: str | None = None


class TranscriptGroup(FrameContract):
    """One group of a page's entries at the level asked (`entry_cursors` name them)."""

    level: TranscriptGroupLevel
    key: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=512)
    unit_key: str | None = None
    point_id: str | None = None
    node_key: str | None = None
    cycle: int | None = None
    iteration: int | None = None
    entry_cursors: tuple[str, ...] = ()
    facts: dict[str, Any] = Field(default_factory=dict)


class TranscriptPage(FrameContract):
    run_id: str
    entries: tuple[TranscriptEntry, ...]
    next_cursor: str | None = None
    has_more: bool = False
    # Present only when the query asked `by`; every cursor names an entry of this page.
    groups: tuple[TranscriptGroup, ...] = ()


def transcript_json_schema() -> dict[str, object]:
    return TranscriptEntry.model_json_schema()

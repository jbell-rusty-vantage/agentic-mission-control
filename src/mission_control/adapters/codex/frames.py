"""App-server events to `LaneFrame`s and closing facts (MP-08; SPEC-03 frames).

Every notification and server request of the connection becomes a frame of the Native Event
Store through MP-13's `codex_observations` (raw kind = the JSON-RPC method, kind from the
`CODEX_KINDS` table, dedupe key `codex:<thread>:<turn>:<item>:<method>`, child threads as
`subordinate_ref`). Methods the table does not know classify `unknown` and are still stored.
Two lane-specific rules on top of MP-13:

- a per-item delta (`.../delta`, `.../progress`, `outputDelta`) is keyed with the event
  sequence as well, so a stream of deltas of one item stores every delta instead of the first;
- `turn/completed` of the observed turn yields `turn/completed` (TURN_ENDED) and the synthetic
  `turn/completed.result` (RUN_RESULT); the latter is the terminal frame whose body (the
  `Turn`) becomes `ClosingFacts`.

Cursors name a position a later segment resumes from (MP-08 failure B and unresolved 7):

- live `<turnId>@<connection epoch>:<seq>`: after event `seq` of one app-server process. When
  one event yields several frames (`turn/completed` -> TURN_ENDED + RUN_RESULT), every frame
  but the last resumes BEFORE the event (failure B): `<seq>/<k>` names "events before `seq`
  and the first `k` frames of event `seq` were taken", so a segment cut between them re-reads
  the event from its `k`-th frame instead of skipping the rest of it. (The diagnosed `seq - 1`
  alone livelocks at `max_frames=1`: every segment would re-take the event's first frame.)
- history `<turnId>@<connection epoch>:h<n>`: the first `n` frames of the turn's `thread/read`
  history were taken. History positions belong to the thread, not to the connection, so they
  survive a relaunch; another epoch's live cursor resynchronizes from history first.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, NamedTuple

from mission_control.adapters.codex.protocol import (
    N_TURN_COMPLETED,
    TERMINAL_TURN_STATUSES,
    ThreadTokenUsage,
    TokenUsageBreakdown,
    Turn,
    codex_error_info,
    limit_signal_from_error_info,
)
from mission_control.adapters.codex.transport import InboundEvent
from mission_control.application.frames.kinds import UnknownKindCounter, bounded_key
from mission_control.application.frames.provider_mapping import codex_observations
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.pressure import ContextOccupancy
from mission_control.domain.execution.lane_turns import (
    MAX_EXCERPT_CHARS,
    ClosingFacts,
    NativeStatus,
)
from mission_control.domain.execution.lanes import LaneFrame, UsageReport
from mission_control.domain.frames.contracts import FrameObservation

RESULT_SUFFIX: Final = ".result"
_DELTA_MARKERS: Final = ("/delta", "Delta", "/progress", "/outputDelta", "/patchUpdated")
_STATUS: Final[Mapping[str, NativeStatus]] = {
    "completed": "finished",
    "interrupted": "cancelled",
    "failed": "error",
}
CAPACITY_ERROR_CODE: Final = "capacity"


HISTORY_MARK: Final = "h"


PART_MARK: Final = "/"


class ParsedCursor(NamedTuple):
    turn_id: str
    epoch: str
    # The live event sequence (live cursors) or -1 (history cursors).
    seq: int
    # How many history frames of the turn were taken (history cursors) or None (live).
    history: int | None = None
    # Live: how many frames of event `seq` were taken (0 = the whole event was taken).
    taken: int = 0

    @property
    def resume_after(self) -> int:
        """The event sequence a live observation resumes after."""

        return self.seq - 1 if self.taken else self.seq


def composite_cursor(turn_id: str, epoch: str, seq: int, taken: int = 0) -> str:
    """After event `seq` (`taken` = 0) or after its first `taken` frames (`taken` > 0)."""

    position = f"{max(seq, 0)}{PART_MARK}{taken}" if taken > 0 and seq > 0 else str(max(seq, 0))
    return f"{turn_id}@{epoch}:{position}"


def history_cursor(turn_id: str, epoch: str, position: int) -> str:
    return f"{turn_id}@{epoch}:{HISTORY_MARK}{max(position, 0)}"


def parse_cursor(cursor: str | None) -> ParsedCursor | None:
    """The parts of a live or history cursor; None for an unreadable one."""

    if not cursor:
        return None
    turn, separator, rest = cursor.rpartition("@")
    if not separator or not turn:
        return None
    epoch, sep2, position = rest.partition(":")
    if not sep2 or not epoch or not position:
        return None
    history = position.startswith(HISTORY_MARK)
    seq_text, part_sep, taken_text = position.partition(PART_MARK)
    try:
        value = int(position[1:] if history else seq_text)
        taken = int(taken_text) if part_sep else 0
    except ValueError:
        return None
    if value < 0 or taken < 0 or (part_sep and (history or taken == 0 or value == 0)):
        return None
    if history:
        return ParsedCursor(turn, epoch, -1, value)
    return ParsedCursor(turn, epoch, value, None, taken)


def is_delta(method: str) -> bool:
    return any(marker in method for marker in _DELTA_MARKERS)


# Live events whose MP-13 key would repeat across app-server processes or within one turn:
# `serverRequest/resolved` is keyed by a connection-scoped JSON-RPC id, and a turn may compact
# more than once. Their keys, like every delta's, carry the connection epoch and event seq.
CONNECTION_SCOPED_KEYS: frozenset[str] = frozenset({"serverRequest/resolved", "thread/compacted"})


def observations_for(
    event: InboundEvent,
    *,
    root_thread_id: str,
    counter: UnknownKindCounter | None,
    epoch: str | None = None,
) -> tuple[FrameObservation, ...]:
    """MP-13 observations of one event. Deltas and connection-scoped events are keyed by the
    connection epoch (when live) and the event sequence as well, so a relaunch that reuses a
    JSON-RPC id or a second compaction in one turn is never dropped as a duplicate."""

    observations = codex_observations(
        event.method, event.params, root_thread_id=root_thread_id, counter=counter
    )
    if not is_delta(event.method) and event.method not in CONNECTION_SCOPED_KEYS:
        return observations
    position = f"{epoch}:{event.seq}" if epoch is not None else str(event.seq)
    return tuple(
        observation.model_copy(
            update={"provider_key": bounded_key(observation.provider_key, "seq", position)}
        )
        for observation in observations
    )


def lane_frame(
    observation: FrameObservation,
    *,
    harness_execution_id: str,
    generation: int,
    cursor: str,
    terminal: bool,
) -> LaneFrame:
    body = observation.body if observation.body is not None else {}
    return LaneFrame(
        harness_execution_id=harness_execution_id,
        generation=generation,
        provider_key=observation.provider_key[:512],
        cursor=cursor[:512],
        kind=observation.raw_kind[:64],
        raw_kind=observation.raw_kind,
        body=body,
        terminal=terminal,
        digest=sha256_digest(body),
        native_turn_ref=observation.native_turn_ref,
        tool_call_ref=observation.tool_call_ref,
        subordinate_ref=observation.subordinate_ref,
    )


def turn_completed_event(seq: int, thread_id: str, turn: Mapping[str, Any]) -> InboundEvent:
    """A synthetic `turn/completed` (history resync) with the same key as the live one."""

    return InboundEvent(
        seq, "notification", N_TURN_COMPLETED, {"threadId": thread_id, "turn": dict(turn)}
    )


def item_completed_event(
    seq: int, thread_id: str, turn_id: str, item: Mapping[str, Any]
) -> InboundEvent:
    return InboundEvent(
        seq,
        "notification",
        "item/completed",
        {"threadId": thread_id, "turnId": turn_id, "item": dict(item)},
    )


def usage_report(
    usage: ThreadTokenUsage | None, *, baseline: TokenUsageBreakdown | None = None
) -> UsageReport:
    """Attribute the thread counter's increase to a turn with a known start baseline.

    ``last`` describes one model call, whereas a native turn can make many calls. A
    cumulative counter without its turn boundary cannot establish attributable usage.
    """

    if usage is None or baseline is None:
        return UsageReport(disposition="unknown")
    current = usage.total
    names = tuple(TokenUsageBreakdown.model_fields)
    if any(getattr(current, name) < getattr(baseline, name) for name in names):
        return UsageReport(disposition="unknown")
    for counter in (baseline, current):
        if any(getattr(counter, name) < 0 for name in names) or (
            counter.total_tokens != counter.input_tokens + counter.output_tokens
        ):
            return UsageReport(disposition="unknown")
    total = current.total_tokens - baseline.total_tokens
    if total <= 0:
        return UsageReport(disposition="unknown")
    return UsageReport(
        disposition="estimated",
        input_tokens=current.input_tokens - baseline.input_tokens,
        output_tokens=current.output_tokens - baseline.output_tokens,
        total_tokens=total,
        cache_read_tokens=current.cached_input_tokens - baseline.cached_input_tokens,
        cache_write_tokens=current.cache_write_input_tokens - baseline.cache_write_input_tokens,
    )


@dataclass(frozen=True)
class AttributedTurnUsage:
    baseline: TokenUsageBreakdown | None
    current: ThreadTokenUsage
    baseline_source: str
    valid: bool = True
    root_thread_id: str | None = None
    invalidates_turn_ref: str | None = None

    def report(self) -> UsageReport:
        return (
            usage_report(self.current, baseline=self.baseline)
            if self.valid
            else UsageReport(disposition="unknown")
        )

    def provenance(self) -> dict[str, Any]:
        return {
            "schema_version": "mc.codex.turn_usage.v1",
            "root_thread_id": self.root_thread_id,
            "baseline_source": self.baseline_source,
            "baseline_total": self.baseline.wire() if self.baseline is not None else None,
            "current_total": self.current.total.wire(),
            "monotonic": self.valid,
            "invalidates_turn_ref": self.invalidates_turn_ref,
        }


@dataclass
class TurnUsageTracker:
    """Connection-independent turn baselines, with immutable per-event snapshots.

    Only an explicit new ``thread/start`` establishes zero. Native history has no usage
    counters at this protocol pin. Reconnect preserves an already known turn baseline,
    but cannot establish the next turn's baseline across a gap in observation.
    """

    thread_id: str | None = None
    current_turn: str | None = None
    counter_turn: str | None = None
    counter: TokenUsageBreakdown | None = None
    fresh: bool = False
    baselines: dict[str, tuple[TokenUsageBreakdown | None, str]] = field(default_factory=dict)
    latest: dict[str, AttributedTurnUsage] = field(default_factory=dict)
    snapshots: dict[tuple[str, int], AttributedTurnUsage] = field(default_factory=dict)
    invalid: set[str] = field(default_factory=set)

    def start_thread(self, thread_id: str) -> None:
        self.thread_id = thread_id
        self.current_turn = self.counter_turn = None
        self.counter = TokenUsageBreakdown()
        self.fresh = True

    def resume_thread(self, thread_id: str) -> None:
        self.thread_id = thread_id
        self.current_turn = self.counter_turn = None
        self.counter = None
        self.fresh = False

    def begin(self, turn_id: str) -> None:
        if turn_id in self.baselines:
            return
        known = self.counter is not None and (
            self.fresh or (self.current_turn is not None and self.counter_turn == self.current_turn)
        )
        baseline = self.counter if known else None
        source = "fresh_thread" if self.fresh else "previous_turn_total" if known else "unknown"
        self.baselines[turn_id] = (baseline, source)
        self.current_turn = turn_id
        self.fresh = False

    def record(
        self, turn_id: str, usage: ThreadTokenUsage, *, epoch: str, seq: int
    ) -> AttributedTurnUsage:
        position = (epoch, seq)
        if position in self.snapshots:
            return self.snapshots[position]
        self.begin(turn_id)
        prior = self.latest.get(turn_id)
        if prior is not None and prior.current.total == usage.total:
            # Repeated notification of an already attributed counter is not a late
            # increment of a predecessor turn. Do not move the thread watermark back.
            value = AttributedTurnUsage(
                prior.baseline,
                usage,
                prior.baseline_source,
                prior.valid and turn_id not in self.invalid,
                self.thread_id,
                prior.invalidates_turn_ref,
            )
            self.snapshots[position] = value
            return value
        baseline, source = self.baselines[turn_id]
        names = tuple(TokenUsageBreakdown.model_fields)
        regressed = self.counter is not None and any(
            getattr(usage.total, name) < getattr(self.counter, name) for name in names
        )
        if regressed:
            self.invalid.add(turn_id)
            source = "counter_regression"
        if any(getattr(usage.total, name) < 0 for name in names) or (
            usage.total.total_tokens != usage.total.input_tokens + usage.total.output_tokens
        ):
            self.invalid.add(turn_id)
            source = "invalid_counter"
        if self.current_turn != turn_id:
            # A previous turn's late increment makes an already captured next baseline
            # incomplete. Refuse attribution instead of billing that increment twice.
            if self.current_turn is not None:
                self.invalid.add(self.current_turn)
                self.invalid.add(turn_id)
                source = "late_previous_turn_usage"
        value = AttributedTurnUsage(
            baseline,
            usage,
            source,
            turn_id not in self.invalid,
            self.thread_id,
            self.current_turn if self.current_turn != turn_id else None,
        )
        self.snapshots[position] = value
        self.latest[turn_id] = value
        self.counter = usage.total if value.valid else None
        self.counter_turn = turn_id
        return value

    def report(self, turn_id: str | None) -> UsageReport:
        value = self.latest.get(turn_id or "")
        return (
            value.report()
            if value is not None and turn_id not in self.invalid
            else UsageReport(disposition="unknown")
        )


def attributed_usage_observation(
    raw: FrameObservation, attribution: AttributedTurnUsage
) -> FrameObservation:
    """A companion USAGE frame; preserve the provider's original observation untouched."""

    provenance = attribution.provenance()
    return raw.model_copy(
        update={
            "provider_key": bounded_key(raw.provider_key, "attributed", sha256_digest(provenance)),
            "body": {
                "threadId": (raw.body or {}).get("threadId"),
                "turnId": raw.native_turn_ref,
                "usage": attribution.report().model_dump(mode="json"),
                "codex_usage_provenance": provenance,
            },
        }
    )


def occupancy_from_usage(usage: ThreadTokenUsage | None) -> ContextOccupancy:
    """The live context occupancy from the last `thread/tokenUsage/updated` (MP-12).

    `used` is the LAST model call's `totalTokens` (input incl. the replayed history, plus its
    output), never the cumulative `total` breakdown (a billed sum, not an occupancy), against
    the reported `modelContextWindow`; without that window the occupancy is `unknown`.
    DRILL (docs/qualification/lanes/codex/README.md step 5): confirm that `last.totalTokens`
    is what Codex itself compares with `modelContextWindow` (the TUI's context meter) and
    whether reasoning output tokens count; until then this reading is UNVERIFIED.
    """

    if usage is None:
        return ContextOccupancy.unknown("no thread/tokenUsage/updated observed on this session")
    window = usage.model_context_window
    if window is None or window <= 0:
        return ContextOccupancy.unknown("thread/tokenUsage/updated carried no modelContextWindow")
    last = usage.last
    used = last.total_tokens or (last.input_tokens + last.output_tokens)
    if used <= 0:
        return ContextOccupancy.unknown("the last token usage reported no tokens")
    return ContextOccupancy.measured(used, window, "provider_context_window")


def agent_text(items: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> str | None:
    text: str | None = None
    for item in items:
        if isinstance(item, Mapping) and item.get("type") == "agentMessage":
            value = item.get("text")
            if isinstance(value, str) and value:
                text = value
    return text


def closing_facts(
    turn: Turn,
    *,
    usage: ThreadTokenUsage | None,
    last_agent_text: str | None,
    model: str | None,
    attributed_usage: UsageReport | None = None,
) -> ClosingFacts:
    """`Turn` (terminal) to the closing facts the reducer and settlement read."""

    status = _STATUS.get(turn.status, "error")
    report = attributed_usage if attributed_usage is not None else usage_report(usage)
    error_code: str | None = None
    error_message: str | None = None
    if status == "error":
        info = turn.error.codex_error_info if turn.error is not None else None
        name = codex_error_info(info)
        if limit_signal_from_error_info(info, source="codex.turn_error") is not None:
            error_code = CAPACITY_ERROR_CODE
        else:
            error_code = (name or "provider_error")[:128]
        error_message = (turn.error.message if turn.error is not None else "")[:1_024] or None
    excerpt = last_agent_text or agent_text(turn.items) or ""
    return ClosingFacts(
        native_status=status,
        result_excerpt=excerpt[:MAX_EXCERPT_CHARS],
        usage=report,
        cost_disposition="estimated" if report.disposition != "unknown" else "unknown",
        error_code=error_code,
        error_message=error_message,
        duration_ms=turn.duration_ms
        if turn.duration_ms is not None and turn.duration_ms >= 0
        else None,
        model=model,
    )


def turn_is_terminal(turn: Mapping[str, Any]) -> bool:
    return str(turn.get("status")) in TERMINAL_TURN_STATUSES


__all__ = [
    "CAPACITY_ERROR_CODE",
    "HISTORY_MARK",
    "PART_MARK",
    "RESULT_SUFFIX",
    "AttributedTurnUsage",
    "ParsedCursor",
    "TurnUsageTracker",
    "agent_text",
    "attributed_usage_observation",
    "closing_facts",
    "composite_cursor",
    "history_cursor",
    "is_delta",
    "item_completed_event",
    "lane_frame",
    "observations_for",
    "occupancy_from_usage",
    "parse_cursor",
    "turn_completed_event",
    "turn_is_terminal",
    "usage_report",
]

"""`mc.cognition_coordinate.v1`, `mc.cognition_point.v1` and `mc.state_as_of.v1` (P1 turn 4).

The provider lifecycle is indexed, not abstracted (DESIGN P1-S4/S5). A **coordinate** names
one observable point of one unit generation: the run, the unit, the generation, optionally
the session turn, and a `point` that is a tagged union the kernel never interprets and the
lane reads exactly:

- `checkpoint`: a LangGraph root checkpoint (Deep Agents);
- `session_cursor`: a provider session and turn (Claude Agent SDK, hosted agent APIs);
- `thread_item`: a provider thread and item (Codex);
- `workspace_snapshot`: a frozen workspace (Cursor; the coordinate's substance for a lane
  with no provider-side state is our turn ledger plus the snapshot).

A **point record** is the coordinate plus what the kernel knows about it: the denormalized
unit location (stage or role, cycle or iteration, session generation) so a coordinator can
filter by them, the Temporal activity attempt that wrote it, the frames recorded while it
ran, and redacted facts folded from the lane's state at write time. Rows are written by the
lane adapter at settlement (from the `CognitionPointObservation`s it returns with its
`RuntimeResult`), enriched by the frame writer, re-derived by a reconciler when a crash left
a lineage unsettled, and seeded by a fork. Points are evidence: a point never settles
anything (ADR 0007).

`StateAsOf` is what `read_as_of` returns: the graph state at the point with secrets and
oversized content hidden, never counts only (owner, 2026-10-21): messages with their roles,
tool calls and text, files with digests, the state channels, pending tasks and interrupts.
Everything here is pure, frozen and secret-free.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Final, Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.execution.lanes import LaneProfileName, RestoreLevel
from mission_control.domain.graph_runtime.identities import (
    DIGEST_PATTERN,
    UNIT_KEY_PATTERN,
    GoalDirectedUnitLocation,
    QualifiedCheckpointKey,
    RuntimeUnitIdentity,
    StageGraphUnitLocation,
)

COGNITION_COORDINATE_SCHEMA: Final = "mc.cognition_coordinate.v1"
COGNITION_POINT_SCHEMA: Final = "mc.cognition_point.v1"
STATE_AS_OF_SCHEMA: Final = "mc.state_as_of.v1"

CognitionPointKind = Literal["checkpoint", "session_cursor", "thread_item", "workspace_snapshot"]
PointRole = Literal[
    "input",  # the first checkpoint of the submission (LangGraph `source: input`)
    "intermediate",
    "leaf",  # the last checkpoint the attempt wrote
    "result",  # the settled result checkpoint (the transition's result key)
    "source",  # the expected source the lineage continued from (another unit's result)
    "interrupted",  # the leaf an `interrupt_and_inject` cancelled
    "replacement_start",  # the first checkpoint of the replacement turn
    "fork_seed",  # the point a fork seeded a derived unit from
    "rollover_start",  # the first checkpoint of a fresh session generation
    "cycle_start",  # the first checkpoint of a Stage Graph cycle after the first
    "reused",  # a unit a fork settled by reference to the source run's result point
    "subagent_root",  # the first checkpoint of a sync subagent's nested namespace
]
PointWriter = Literal["adapter", "frame_writer", "reconciler", "fork_seed"]
PointFamily = Literal["stage_graph", "goal_directed"]
PointSource = Literal["input", "loop", "update", "fork", "interrupt", "resume", "compaction"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- The point union -----------------------------------------------------------------------


class CheckpointPoint(Contract):
    """A LangGraph checkpoint of a cognitive namespace (Deep Agents): a root checkpoint of
    the unit's thread, or (1.4.4) a checkpoint of a sync subagent's nested namespace, which
    then names the subagent it belongs to."""

    kind: Literal["checkpoint"] = "checkpoint"
    key: QualifiedCheckpointKey
    subordinate_ref: str | None = Field(default=None, min_length=1, max_length=1024)

    @property
    def locator(self) -> str:
        return self.key.checkpoint_id

    @property
    def is_root(self) -> bool:
        return self.key.is_root

    @model_validator(mode="after")
    def root_or_subordinate(self) -> CheckpointPoint:
        if self.key.is_root and self.subordinate_ref is not None:
            raise ValueError("a root checkpoint point names no subordinate")
        if not self.key.is_root and self.subordinate_ref is None:
            raise ValueError(
                "a cognition point names a root checkpoint, or a nested one with its subordinate"
            )
        return self


class SessionCursorPoint(Contract):
    """A provider session and the turn within it (Claude Agent SDK, Cursor, hosted agent APIs).

    Cross-provider control (2026-11-05): `step_ref` names one observable step inside the turn
    (the provider key of the step frame that closed it: a tool call, a model message, the
    turn end), so a session lane writes one point per step boundary, as Deep Agents writes one
    per root checkpoint. Without it the point is the whole turn (the pre-existing shape).
    """

    kind: Literal["session_cursor"] = "session_cursor"
    session_ref: str = Field(min_length=1, max_length=512)
    turn_ref: str = Field(min_length=1, max_length=512)
    step_ref: str | None = Field(default=None, min_length=1, max_length=256)

    @property
    def locator(self) -> str:
        base = f"{self.session_ref}#{self.turn_ref}"
        return base if self.step_ref is None else f"{base}#{self.step_ref}"


class ThreadItemPoint(Contract):
    """A provider thread and an item within it (Codex)."""

    kind: Literal["thread_item"] = "thread_item"
    thread_ref: str = Field(min_length=1, max_length=512)
    item_ref: str = Field(min_length=1, max_length=512)

    @property
    def locator(self) -> str:
        return f"{self.thread_ref}#{self.item_ref}"


class WorkspaceSnapshotPoint(Contract):
    """A frozen workspace (Cursor); with `turn_no` on the coordinate, the turn it closed.

    Cross-provider control (2026-11-05): `session_ref` and `turn_ref` name the native session
    and turn the snapshot closed when the lane knows them, so a workspace point joins the
    session-cursor points of the same turn.
    """

    kind: Literal["workspace_snapshot"] = "workspace_snapshot"
    snapshot_ref: str = Field(min_length=1, max_length=1024)
    session_ref: str | None = Field(default=None, min_length=1, max_length=512)
    turn_ref: str | None = Field(default=None, min_length=1, max_length=512)

    @property
    def locator(self) -> str:
        return self.snapshot_ref


CognitionPointRef = Annotated[
    CheckpointPoint | SessionCursorPoint | ThreadItemPoint | WorkspaceSnapshotPoint,
    Field(discriminator="kind"),
]


# --- The coordinate ----------------------------------------------------------------------


class CognitionCoordinate(Contract):
    """One point of one unit generation, exact to the lane and opaque to the kernel."""

    schema_version: Literal["mc.cognition_coordinate.v1"] = COGNITION_COORDINATE_SCHEMA
    run_id: str = Field(min_length=1, max_length=512)
    unit_key: str = Field(pattern=UNIT_KEY_PATTERN)
    execution_generation: int = Field(ge=1)
    harness_execution_id: str | None = Field(default=None, min_length=1, max_length=256)
    turn_no: int | None = Field(default=None, ge=1)
    point: CognitionPointRef

    @property
    def locator(self) -> str:
        return self.point.locator

    @property
    def kind(self) -> CognitionPointKind:
        return self.point.kind


class UnitLocationFacts(Contract):
    """The unit's semantic location, denormalized for filters (one shape for both families).

    Stage Graph: `node_key` is the stage id, `iteration` the workflow cycle ordinal, `cycle`
    the stage cycle ordinal (each cycle visit is a new unit key at generation 1). Goal
    Directed: `node_key` is the role, `iteration` the goal iteration, `cycle` 0, and
    `session_generation` the shared-thread session the role runs in.
    """

    family: PointFamily
    node_key: str = Field(min_length=1, max_length=512)
    iteration: int = Field(ge=0)
    cycle: int = Field(ge=0)
    session_generation: int | None = Field(default=None, ge=1)


def location_facts(unit: RuntimeUnitIdentity) -> UnitLocationFacts:
    location = unit.location
    if isinstance(location, StageGraphUnitLocation):
        return UnitLocationFacts(
            family="stage_graph",
            node_key=location.stage_id,
            iteration=location.workflow_cycle_ordinal,
            cycle=location.stage_cycle_ordinal,
        )
    assert isinstance(location, GoalDirectedUnitLocation)
    return UnitLocationFacts(
        family="goal_directed",
        node_key=location.operation_role,
        iteration=location.goal_iteration,
        cycle=0,
        session_generation=location.session_generation,
    )


class AttemptFacts(Contract):
    """The Temporal activity attempt that wrote the point (from its observation)."""

    activity_attempt_observation_id: str = Field(min_length=1, max_length=256)
    temporal_workflow_id: str = Field(min_length=1, max_length=1024)
    temporal_run_id: str = Field(min_length=1, max_length=256)
    temporal_activity_id: str = Field(min_length=1, max_length=256)
    activity_attempt: int = Field(ge=1)
    task_queue: str | None = Field(default=None, min_length=1, max_length=512)


class FrameRange(Contract):
    """Arrival ordinals of the frames recorded while the point's step ran (inclusive)."""

    from_ordinal: int = Field(ge=1)
    to_ordinal: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> FrameRange:
        if self.to_ordinal < self.from_ordinal:
            raise ValueError("a frame range ends at or after its start")
        return self


# --- What a lane reports, and what the kernel records -----------------------------------


class CognitionPointObservation(Contract):
    """One point as the lane observed it in its own lineage (lane-side, settlement input).

    The lane knows the point, its parent in the lineage, the step facts and what it folded
    from its state; the settlement adds the run, the unit location, the attempt and the frame
    ordinals. `parent_locator` names the parent point of the same unit generation;
    `parent_point` names a parent outside it (the expected source another unit settled, or
    the point a fresh thread continued from).
    """

    point: CognitionPointRef
    parent_locator: str | None = Field(default=None, min_length=1, max_length=1024)
    parent_point: CognitionPointRef | None = None
    ordinal: int | None = None
    source: PointSource | None = None
    roles: tuple[PointRole, ...] = ()
    attempt_ref: str | None = Field(default=None, min_length=1, max_length=256)
    # The native identity the frame writer keyed this invocation's turn by, so the
    # repository resolves the session turn without the lane knowing the turn ledger.
    harness_execution_id: str | None = Field(default=None, min_length=1, max_length=256)
    native_turn_ref: str | None = Field(default=None, min_length=1, max_length=512)
    # Provider keys of the frames recorded while this step ran (unique per execution and
    # generation); the repository resolves their arrival ordinals into the frame range.
    frame_keys: tuple[str, ...] = Field(default=(), max_length=4_096)
    message_count: int | None = Field(default=None, ge=0)
    channel_facts: dict[str, Any] = Field(default_factory=dict)
    files_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    usage_delta: dict[str, int] = Field(default_factory=dict)
    seedable: bool = False
    # 1.4.4 (TR-D6): the workspace candidates the lane registered for the result point.
    workspace_checkpoint_ref: str | None = Field(default=None, min_length=1, max_length=1024)
    # When the lane wrote the point (a LangGraph checkpoint's `ts`): the reconciler brackets
    # the frames of a step between consecutive points when the live recorder's keys are gone.
    native_observed_at: AwareDatetime | None = None

    @property
    def locator(self) -> str:
        return self.point.locator

    @property
    def subordinate_ref(self) -> str | None:
        return point_subordinate_ref(self.point)


def point_subordinate_ref(point: CognitionPointRef) -> str | None:
    """The subagent a nested point belongs to; None for every root point."""

    return point.subordinate_ref if isinstance(point, CheckpointPoint) else None


class CognitionPointRecord(Contract):
    """One persisted point (`mc.cognition_point.v1`): the coordinate plus the kernel's facts."""

    schema_version: Literal["mc.cognition_point.v1"] = COGNITION_POINT_SCHEMA
    point_id: str = Field(min_length=1, max_length=64)
    coordinate: CognitionCoordinate
    lane_profile: LaneProfileName
    location: UnitLocationFacts
    parent_point_id: str | None = Field(default=None, min_length=1, max_length=64)
    # The parent's locator as the lane reported it; the repository resolves it to a row of
    # the same run when `parent_point_id` is unknown (the lineage root's expected source).
    parent_locator: str | None = Field(default=None, min_length=1, max_length=1024)
    parent_coordinate: CognitionCoordinate | None = None
    ordinal: int | None = None
    source: PointSource | None = None
    roles: tuple[PointRole, ...] = ()
    turn_id: str | None = Field(default=None, min_length=1, max_length=64)
    attempt: AttemptFacts | None = None
    frames: FrameRange | None = None
    message_count: int | None = Field(default=None, ge=0)
    channel_facts: dict[str, Any] = Field(default_factory=dict)
    files_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    usage_delta: dict[str, int] = Field(default_factory=dict)
    budget_snapshot: dict[str, Any] | None = None
    workspace_checkpoint_ref: str | None = Field(default=None, min_length=1, max_length=1024)
    seedable: bool = False
    written_by: PointWriter
    recorded_at: AwareDatetime
    version: int = Field(default=1, ge=1)
    # A `fork_seed` or `rollover_start` point: how much of its `parent_coordinate` the lane
    # restored into this unit's namespace and whether the step history came with it.
    restore_level: RestoreLevel | None = None
    history: Literal["native", "reconstructed"] | None = None
    # 1.4.4 (TR-D17): set by the pruning session when the point's native state was pruned;
    # the reconciler reports such rows as `pruned`, never as missing.
    pruned_at: AwareDatetime | None = None

    @property
    def subordinate_ref(self) -> str | None:
        return point_subordinate_ref(self.coordinate.point)

    @model_validator(mode="after")
    def identity_is_derived(self) -> CognitionPointRecord:
        expected = point_id_for(
            self.coordinate.run_id,
            self.coordinate.unit_key,
            self.coordinate.execution_generation,
            self.coordinate.kind,
            self.coordinate.locator,
        )
        if self.point_id != expected:
            raise ValueError("point id is not derived from its coordinate")
        return self


def point_id_for(
    run_id: str, unit_key: str, execution_generation: int, kind: str, locator: str
) -> str:
    """Deterministic point identity: the same coordinate always has the same row."""

    identity = f"mc.cognition_point.v1|{run_id}|{unit_key}|{execution_generation}|{kind}|{locator}"
    return str(uuid5(NAMESPACE_URL, identity))


class CognitionPointFilter(Contract):
    """What `GET .../runs/{id}/points` accepts; every field narrows."""

    unit_key: str | None = Field(default=None, pattern=UNIT_KEY_PATTERN)
    execution_generation: int | None = Field(default=None, ge=1)
    node_key: str | None = Field(default=None, min_length=1, max_length=512)
    iteration: int | None = Field(default=None, ge=0)
    cycle: int | None = Field(default=None, ge=0)
    session_generation: int | None = Field(default=None, ge=1)
    kind: CognitionPointKind | None = None
    role: PointRole | None = None
    seedable_only: bool = False


class CognitionPointPage(Contract):
    run_id: str = Field(min_length=1)
    entries: tuple[CognitionPointRecord, ...] = ()
    next_cursor: str | None = None


# --- State as of a point ------------------------------------------------------------------


class ToolCallFact(Contract):
    id: str | None = None
    name: str = Field(min_length=1, max_length=256)
    arguments: dict[str, Any] | None = None
    arguments_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    arguments_bytes: int = Field(default=0, ge=0)
    truncated: bool = False


class StateMessage(Contract):
    """One message of the state at the point: role, name, tool calls and redacted text."""

    id: str | None = None
    role: str = Field(min_length=1, max_length=32)
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCallFact, ...] = ()
    text: str | None = None
    text_bytes: int = Field(default=0, ge=0)
    text_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    truncated: bool = False
    redactions: int = Field(default=0, ge=0)
    usage: dict[str, int] = Field(default_factory=dict)


StateFileSource = Literal["state_channel", "sandbox_upload", "closure"]


class StateFile(Contract):
    path: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=0)
    digest: str = Field(pattern=DIGEST_PATTERN)
    encoding: str = Field(default="utf-8", max_length=32)
    # 1.4.4 (TR-D8): where the file lived at the point: the `files` state channel the
    # checkpoint holds, or a sandbox upload the materialization manifest names (digest only);
    # OVE-204: or the result point's Workspace Closure (`closure`, sandbox files included).
    source: StateFileSource | None = None
    # OVE-204: the promoted body of a closure file (`closure-body://...`), read run-bound
    # through the artifact body reader; absent when the body was withheld or not promoted.
    body_ref: str | None = Field(default=None, min_length=1, max_length=2048)


class GraphStateAsOf(Contract):
    """The lane's state at the point, redacted: the graph state a Deep Agents checkpoint holds."""

    messages: tuple[StateMessage, ...] = ()
    files: tuple[StateFile, ...] = ()
    # Named state channels other than messages and files (`todos`, `artifact_index`,
    # `child_result_index`, `context_manifest`, `skills_metadata`, ...), redacted values.
    channels: dict[str, Any] = Field(default_factory=dict)
    pending_tasks: tuple[str, ...] = ()
    interrupts: tuple[dict[str, Any], ...] = ()
    step: int | None = None
    source: str | None = None
    stamps: dict[str, str | int] = Field(default_factory=dict)
    withheld: tuple[str, ...] = ()


class StateAsOf(Contract):
    """`mc.state_as_of.v1`: everything one point row answers, plus the lane's state read."""

    schema_version: Literal["mc.state_as_of.v1"] = STATE_AS_OF_SCHEMA
    point: CognitionPointRecord
    restore_level: RestoreLevel
    history: Literal["native", "reconstructed"] = "native"
    state: GraphStateAsOf
    usage_to_point: dict[str, int] = Field(default_factory=dict)
    # 1.4.4 (TR-D8): the digest of the attempt's `environment_materialized` manifest (the
    # input point's `channel_facts.materialization_digest`, or the manifest frame itself).
    materialization_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    # OVE-204: the point's `workspace-closure://` reference when its files came from a closure.
    closure_ref: str | None = Field(default=None, min_length=1, max_length=1024)
    observed_at: AwareDatetime


class KeyedFrame(Protocol):
    """What the key rule reads of a provider frame."""

    @property
    def provider_key(self) -> str: ...

    @property
    def arrival_ordinal(self) -> int: ...


def deep_agents_key_facts(provider_key: str, thread: str) -> tuple[str, str] | None:
    """`(checkpoint_id, step)` of a root Deep Agents key `thread::checkpoint:step:item:kind`."""

    prefix = f"{thread}::"
    if not provider_key.startswith(prefix):
        return None
    parts = provider_key[len(prefix) :].split(":", 2)
    if len(parts) < 3:
        return None
    return parts[0], parts[1]


def frames_of_point[F: KeyedFrame](
    point: CognitionPointObservation | CognitionPointRecord, frames: Sequence[F]
) -> tuple[F, ...]:
    """The root frames a point's step wrote, by key (1.4.4).

    The key's checkpoint slot names the last root checkpoint the recorder had seen (the point
    the frame *followed*, so the point's parent); the finish and backfill frames name the
    result checkpoint itself; a streamed frame names its step. Shared by the reconciler and,
    since tracing Stage 2 (F-S2-6), the settlement writer for a point the recorder gave no
    keys.
    """

    ref = point.point if isinstance(point, CognitionPointObservation) else point.coordinate.point
    if not isinstance(ref, CheckpointPoint):
        return ()  # only the Deep Agents key carries a checkpoint id and a step
    thread = ref.key.thread_id
    locator = ref.locator
    ordinal = point.ordinal
    matched: list[F] = []
    for frame in frames:
        facts = deep_agents_key_facts(frame.provider_key, thread)
        if facts is None:
            continue
        checkpoint_id, step = facts
        if (
            checkpoint_id
            and (
                checkpoint_id == point.parent_locator
                or (checkpoint_id == locator and "result" in point.roles)
            )
        ) or (ordinal is not None and step == str(ordinal)):
            matched.append(frame)
    return tuple(matched)


def frame_range_of(frames: Sequence[KeyedFrame]) -> FrameRange | None:
    if not frames:
        return None
    ordinals = [frame.arrival_ordinal for frame in frames]
    return FrameRange(from_ordinal=min(ordinals), to_ordinal=max(ordinals))


__all__ = [
    "COGNITION_COORDINATE_SCHEMA",
    "COGNITION_POINT_SCHEMA",
    "STATE_AS_OF_SCHEMA",
    "AttemptFacts",
    "CheckpointPoint",
    "CognitionCoordinate",
    "CognitionPointFilter",
    "CognitionPointKind",
    "CognitionPointObservation",
    "CognitionPointPage",
    "CognitionPointRecord",
    "CognitionPointRef",
    "FrameRange",
    "GraphStateAsOf",
    "KeyedFrame",
    "PointFamily",
    "PointRole",
    "PointSource",
    "PointWriter",
    "SessionCursorPoint",
    "StateAsOf",
    "StateFile",
    "StateFileSource",
    "StateMessage",
    "ThreadItemPoint",
    "ToolCallFact",
    "UnitLocationFacts",
    "WorkspaceSnapshotPoint",
    "deep_agents_key_facts",
    "frame_range_of",
    "frames_of_point",
    "location_facts",
    "point_id_for",
]

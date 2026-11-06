"""Claude Agent SDK time travel: `read_as_of`, `seed_fork` and `collect_points` over
`session_cursor` points.

Cross-provider control (2026-11-05, DESIGN §4.2, §5). The `claude_agent_sdk` lane's
`TimeTravelLane`:

- `read_as_of` returns the conversation as of the point at the level it can reach. **R1**
  (always): the messages reconstructed from the persisted frames up to the point (user and
  assistant messages with their tool calls, tool results, errors), redacted and bounded,
  `history: reconstructed`. **R2**: plus the files of the turn's continuation workspace
  snapshot (`claude-workspace:` manifest, digests) when the point names one. **R3**: when the
  state-root transcript mirror of the session is readable on this worker
  (`ClaudeTranscriptReader`, the JSONL the pinned SDK wrote through `ClaudeAgentOptions.
  session_store`), the mirror's entries up to the point's message uuid, `history: native`.
  The level actually reached is the receipt's `restore_level`; the describe declares the
  maximum.
- `seed_fork` creates the derived unit's starting state: the mirror truncated at the point
  (every entry through the point's message uuid), rewritten under a **new session id**
  (`uuid5(fork_request_id)`, deterministic, so a repeated fork names the same session) and
  staged as an artifact the derived `prepare` writes into its own state root; the derived
  `start` then resumes it (`ClaudeAgentOptions(resume=<new id>)`: the lane's transport
  restores the mirror into the CLI's config dir before the spawn, MO-73). The CLI loads the
  truncated history as its own, so the level is R3 with `history: reconstructed` (the file
  was cut by Mission Control, not by the CLI). `fork_session` is not set: the new id is
  minted here, and the source session's transcript is never written or resumed. Without a
  readable mirror the transcript is reconstructed from the frames (R1): the same JSONL
  shape, labelled `reconstructed_from: frames`. The injected message (`request.message`)
  travels as a preamble of the derived unit's first turn, never as a transcript entry (an
  unanswered user entry would be replayed by the CLI as a pending prompt).
- `collect_points` re-derives one generation's points from its persisted frames with the
  same fold the settlement used (`cognition_points.generation_points`).

Reads and seeds need the caller's request scope (frames are tenant-scoped rows):
`ScopedTimeTravelLane.for_scope` binds one.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID, uuid5

from mission_control.adapters.claude import cognition_points as points
from mission_control.application.execution.harness.time_travel import (
    SEED_HEAD_MESSAGE_COUNT,
    ForkSeedReceipt,
    ForkSeedRequest,
    TimeTravelUnsupported,
)
from mission_control.application.frames.sink import FrameReader
from mission_control.domain.execution.cognition_points import (
    CognitionCoordinate,
    CognitionPointObservation,
    CognitionPointRecord,
    GraphStateAsOf,
    SessionCursorPoint,
    StateAsOf,
    StateFile,
    StateMessage,
    ToolCallFact,
)
from mission_control.domain.execution.lanes import RestoreLevel
from mission_control.domain.frames.body import redact_text, redact_value
from mission_control.domain.frames.contracts import (
    DEFAULT_EXCERPT_CAP_BYTES,
    FrameKind,
    ProviderFrame,
)

_LOGGER = logging.getLogger(__name__)
LANE_PROFILE: Final = "claude_agent_sdk"
# `continuation.WORKSPACE_SNAPSHOT_PREFIX` (not imported: `continuation` imports the harness,
# which implements this module's transcript port); the unit suite holds the two equal.
WORKSPACE_SNAPSHOT_PREFIX: Final = "claude-workspace:"
ARTIFACT_LABEL: Final = "claude-time-travel"
SEED_KIND_MIRROR: Final = "transcript_mirror"
SEED_KIND_FRAMES: Final = "transcript_frames"
_SESSION_NAMESPACE: Final = UUID("5b1a1a7e-4a1e-4b6a-9f3c-2d7e9c0b6f41")
MAX_HYDRATION_MESSAGES: Final = 256
MAX_SNAPSHOT_FILES: Final = 4_096
# Native artifact names (`LaneSeedHead.native_artifacts`; never a credential).
A_SEED_KIND: Final = "seed_kind"
A_SOURCE_SESSION: Final = "source_session_id"
A_DERIVED_SESSION: Final = "derived_session_id"
A_TRANSCRIPT_REF: Final = "transcript_ref"
A_TRANSCRIPT_ENTRIES: Final = "transcript_entries"
A_TRUNCATED_AT: Final = "truncated_at_uuid"
A_TRUNCATION: Final = "truncation"
A_POINT_TURN: Final = "point_turn_uuid"
A_SEED_HEAD: Final = "seed_head"


class SeedArtifactStore(Protocol):
    async def stage(
        self, *, request_scope: str, name: str, content: bytes, media_type: str
    ) -> str: ...

    async def retrieve(self, durable_ref: str) -> bytes: ...


class ClaudeTranscriptReader(Protocol):
    """R3 reads and seeds: the state-root transcript mirror of a session this worker can
    read (`ClaudeAgentSdkHarness.transcript_entries`), as the JSONL entries the SDK wrote."""

    async def transcript_entries(self, session_ref: str) -> list[dict[str, Any]] | None: ...


def derived_session_id(fork_request_id: str) -> str:
    """The derived session id: deterministic per fork request, a UUID the CLI accepts."""

    return str(uuid5(_SESSION_NAMESPACE, f"mc.fork_seed|{fork_request_id}"))


class ClaudeTimeTravel:
    """`TimeTravelLane` (and `ScopedTimeTravelLane`) for the `claude_agent_sdk` lane."""

    def __init__(
        self,
        frames: FrameReader,
        store: SeedArtifactStore | None = None,
        *,
        transcripts: ClaudeTranscriptReader | None = None,
        request_scope: str | None = None,
        excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES,
        seeded: dict[str, ForkSeedReceipt] | None = None,
    ) -> None:
        self._frames = frames
        self._store = store
        self._transcripts = transcripts
        self._scope = request_scope
        self._cap = excerpt_cap_bytes
        self._seeded: dict[str, ForkSeedReceipt] = seeded if seeded is not None else {}

    @property
    def lane_profile(self) -> str:
        return LANE_PROFILE

    @property
    def request_scope(self) -> str | None:
        return self._scope

    def for_scope(self, request_scope: str) -> ClaudeTimeTravel:
        if request_scope == self._scope:
            return self
        return ClaudeTimeTravel(
            self._frames,
            self._store,
            transcripts=self._transcripts,
            request_scope=request_scope,
            excerpt_cap_bytes=self._cap,
            seeded=self._seeded,
        )

    # --- frames -------------------------------------------------------------------------

    def _scope_or_refuse(self, given: str | None = None) -> str:
        scope = given or self._scope
        if scope is None:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="request_scope_required")
        return scope

    async def _generation_frames(
        self, harness_execution_id: str | None, generation: int, *, scope: str
    ) -> tuple[ProviderFrame, ...]:
        if harness_execution_id is None:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="execution_unknown")
        try:
            execution = UUID(harness_execution_id)
        except ValueError:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="execution_unknown") from None
        collected: list[ProviderFrame] = []
        after = 0
        while True:
            page = await self._frames.frames_for_execution(
                scope, execution, generation, after_ordinal=after, limit=10_000
            )
            if not page:
                break
            collected.extend(page)
            after = page[-1].arrival_ordinal
            if len(page) < 10_000:
                break
        collected.sort(key=lambda frame: frame.arrival_ordinal)
        return tuple(collected)

    # --- read_as_of ---------------------------------------------------------------------

    async def read_as_of(self, record: CognitionPointRecord) -> StateAsOf:
        point = record.coordinate.point
        if not isinstance(point, SessionCursorPoint):
            raise TimeTravelUnsupported(LANE_PROFILE, reason="point_kind_not_session_cursor")
        scope = self._scope_or_refuse()
        frames = await self._generation_frames(
            record.coordinate.harness_execution_id,
            record.coordinate.execution_generation,
            scope=scope,
        )
        cut = _cut_ordinal(record, frames)
        prefix = tuple(frame for frame in frames if frame.arrival_ordinal <= cut)
        if not prefix:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="frames_missing")
        withheld: list[str] = []
        level: RestoreLevel = "R1"
        history = "reconstructed"
        uuid = _message_uuid(record)
        entries = await self._mirror(point.session_ref)
        messages: tuple[StateMessage, ...] = ()
        if entries is not None:
            kept = truncate_entries(entries, uuid)
            if kept is not None:
                messages = tuple(self._messages_from_entries(kept))
                level, history = "R3", "native"
            else:
                withheld.append("transcript mirror does not hold the point's message; frames used")
        if level == "R1":
            messages = tuple(self._messages_from_frames(prefix, withheld))
        files, snapshot_ref = await self._snapshot_files(record, withheld)
        if files and level == "R1":
            level = "R2"
        usage: dict[str, int] = {}
        for frame in prefix:
            for name, amount in points.assistant_usage(frame).items():
                usage[name] = usage.get(name, 0) + amount
        channels: dict[str, Any] = {
            "session_id": point.session_ref,
            "turn_uuid": point.turn_ref,
        }
        if point.step_ref is not None:
            channels["step_ref"] = point.step_ref
        if uuid is not None:
            channels["message_uuid"] = uuid
        if snapshot_ref is not None:
            channels["workspace_snapshot_ref"] = snapshot_ref
        withheld.append("secret_values_unknown_at_read: pattern redaction only")
        state = GraphStateAsOf(
            messages=messages,
            files=tuple(files),
            channels=channels,
            step=record.ordinal,
            source=record.source,
            stamps={"lane_profile": LANE_PROFILE, "frames_to_ordinal": cut},
            withheld=tuple(dict.fromkeys(withheld)),
        )
        return StateAsOf(
            point=record,
            restore_level=level,
            history=history,
            state=state,
            usage_to_point=usage,
            observed_at=datetime.now(UTC),
        )

    async def _mirror(self, session_ref: str) -> list[dict[str, Any]] | None:
        if self._transcripts is None:
            return None
        try:
            entries = await self._transcripts.transcript_entries(session_ref)
        except Exception:  # an unreadable mirror is an R1 read, never a failure
            _LOGGER.warning("claude transcript mirror of %s unreadable; frames used", session_ref)
            return None
        return entries or None

    async def _snapshot_files(
        self, record: CognitionPointRecord, withheld: list[str]
    ) -> tuple[list[StateFile], str | None]:
        ref = record.workspace_checkpoint_ref
        if not isinstance(ref, str) or not ref.startswith(WORKSPACE_SNAPSHOT_PREFIX):
            facts_ref = record.channel_facts.get("workspace_snapshot_ref")
            ref = facts_ref if isinstance(facts_ref, str) else None
        if ref is None or not ref.startswith(WORKSPACE_SNAPSHOT_PREFIX):
            return [], None
        if self._store is None:
            withheld.append("workspace snapshot unread: no artifact store composed")
            return [], ref
        try:
            raw = await self._store.retrieve(ref.removeprefix(WORKSPACE_SNAPSHOT_PREFIX))
            body = json.loads(raw)
        except (LookupError, ValueError):
            withheld.append("workspace snapshot unread: manifest not retrievable")
            return [], ref
        manifest = body.get("manifest") if isinstance(body, Mapping) else None
        durable = body.get("durable_refs") if isinstance(body, Mapping) else None
        files: list[StateFile] = []
        if isinstance(manifest, Mapping):
            for path, digest in sorted(manifest.items())[:MAX_SNAPSHOT_FILES]:
                if not isinstance(path, str) or not isinstance(digest, str):
                    continue
                size = _size_of(durable.get(path) if isinstance(durable, Mapping) else None)
                try:
                    files.append(
                        StateFile(path=path, size_bytes=size, digest=digest, source="closure")
                    )
                except ValueError:
                    continue
        if files:
            withheld.append("workspace files: digests from the snapshot manifest, no bytes")
        return files, ref

    # --- rendering -----------------------------------------------------------------------

    def _messages_from_frames(
        self, frames: Sequence[ProviderFrame], withheld: list[str]
    ) -> list[StateMessage]:
        rendered: list[StateMessage] = []
        for frame in frames:
            if frame.subordinate_ref is not None:
                continue
            body = points.body_of(frame)
            raw = frame.raw_kind
            if raw == points.ASSISTANT_RAW_KIND:
                if not body:
                    withheld.append(f"frame {frame.arrival_ordinal} body excerpted; text withheld")
                    rendered.append(self._message("assistant", None, withheld=True))
                    continue
                rendered.append(self._assistant(body))
            elif raw == "user" and frame.kind is FrameKind.MESSAGE:
                rendered.append(
                    self._message("user", _text_of(body.get("content")), id=_str(body.get("uuid")))
                )
            elif raw == "user.tool_result":
                rendered.append(
                    self._message(
                        "tool",
                        _text_of(body.get("content")),
                        name="tool_result",
                        tool_call_id=_str(body.get("tool_use_id")),
                    )
                )
            elif frame.kind is FrameKind.ERROR:
                rendered.append(self._message("system", str(body.get("error") or "error")))
        return rendered[-MAX_HYDRATION_MESSAGES:]

    def _messages_from_entries(self, entries: Sequence[Mapping[str, Any]]) -> list[StateMessage]:
        rendered: list[StateMessage] = []
        for entry in entries:
            kind = entry.get("type")
            message = entry.get("message")
            if not isinstance(message, Mapping):
                continue
            uuid = _str(entry.get("uuid"))
            if kind == "assistant":
                rendered.append(self._assistant({**message, "uuid": uuid}))
            elif kind == "user":
                content = message.get("content")
                blocks = (
                    [block for block in content if isinstance(block, Mapping)]
                    if isinstance(content, list)
                    else []
                )
                results = [block for block in blocks if block.get("type") == "tool_result"]
                if results:
                    for block in results:
                        rendered.append(
                            self._message(
                                "tool",
                                _text_of(block.get("content")),
                                name="tool_result",
                                tool_call_id=_str(block.get("tool_use_id")),
                            )
                        )
                else:
                    rendered.append(self._message("user", _text_of(content), id=uuid))
        return rendered[-MAX_HYDRATION_MESSAGES:]

    def _assistant(self, body: Mapping[str, Any]) -> StateMessage:
        content = body.get("content")
        calls: list[ToolCallFact] = []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "tool_use":
                    arguments, _found = redact_value(block.get("input"))
                    canonical = points.canonical(arguments)
                    oversized = len(canonical.encode("utf-8")) > self._cap
                    calls.append(
                        ToolCallFact(
                            id=_str(block.get("id")),
                            name=str(block.get("name") or "tool"),
                            arguments=None
                            if oversized
                            else (dict(arguments) if isinstance(arguments, Mapping) else None),
                            arguments_digest="sha256:"
                            + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                            arguments_bytes=len(canonical.encode("utf-8")),
                            truncated=oversized,
                        )
                    )
        usage = points.assistant_usage_of_body(body)
        return self._message(
            "assistant",
            _text_of(content),
            id=_str(body.get("uuid")) or _str(body.get("message_id")) or _str(body.get("id")),
            calls=tuple(calls),
            usage=usage,
        )

    def _message(
        self,
        role: str,
        text: str | None,
        *,
        id: str | None = None,  # noqa: A002 - the StateMessage field
        name: str | None = None,
        tool_call_id: str | None = None,
        calls: tuple[ToolCallFact, ...] = (),
        usage: Mapping[str, int] | None = None,
        withheld: bool = False,
    ) -> StateMessage:
        redacted, redactions = redact_text(text) if text else ("", ())
        encoded = redacted.encode("utf-8")
        truncated = len(encoded) > self._cap
        return StateMessage(
            id=id,
            role=role,
            name=name,
            tool_call_id=tool_call_id,
            tool_calls=calls,
            text=encoded[: self._cap].decode("utf-8", errors="ignore") if text else None,
            text_bytes=len(encoded),
            text_digest=("sha256:" + hashlib.sha256(encoded).hexdigest()) if text else None,
            truncated=truncated or withheld,
            redactions=len(redactions),
            usage=dict(usage or {}),
        )

    # --- seed_fork ------------------------------------------------------------------------

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt:
        memo = self._seeded.get(request.fork_request_id)
        if memo is not None:
            return memo
        record = request.source
        point = record.coordinate.point
        if not isinstance(point, SessionCursorPoint):
            raise TimeTravelUnsupported(LANE_PROFILE, reason="point_kind_not_session_cursor")
        if self._store is None:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="artifact_store_required")
        scope = self._scope_or_refuse(request.request_scope)
        frames = await self._generation_frames(
            record.coordinate.harness_execution_id,
            record.coordinate.execution_generation,
            scope=scope,
        )
        cut = _cut_ordinal(record, frames)
        prefix = tuple(frame for frame in frames if frame.arrival_ordinal <= cut)
        uuid = _message_uuid(record)
        derived_id = derived_session_id(request.fork_request_id)
        artifacts: dict[str, str] = {
            A_SOURCE_SESSION: point.session_ref,
            A_DERIVED_SESSION: derived_id,
            A_POINT_TURN: point.turn_ref,
        }
        if uuid is not None:
            artifacts[A_TRUNCATED_AT] = uuid
        entries = await self._mirror(point.session_ref)
        kept: list[dict[str, Any]] | None = None
        if entries is not None:
            kept = truncate_entries(entries, uuid)
            artifacts[A_TRUNCATION] = "exact" if kept is not None else "point_not_in_mirror"
        level: RestoreLevel
        if kept is not None:
            artifacts[A_SEED_KIND] = SEED_KIND_MIRROR
            level, history = "R3", "reconstructed"
        else:
            kept = entries_from_frames(prefix, session_id=derived_id)
            artifacts[A_SEED_KIND] = SEED_KIND_FRAMES
            level, history = "R1", "reconstructed"
        rewritten = [rewrite_session(entry, derived_id) for entry in kept]
        payload = "".join(
            json.dumps(entry, sort_keys=True, default=str) + "\n" for entry in rewritten
        )
        artifacts[A_TRANSCRIPT_REF] = await self._store.stage(
            request_scope=scope,
            name=f"{ARTIFACT_LABEL}/{request.fork_request_id}/{derived_id}.jsonl",
            content=payload.encode("utf-8"),
            media_type="application/jsonl",
        )
        artifacts[A_TRANSCRIPT_ENTRIES] = str(len(rewritten))
        if request.message is not None:
            artifacts[A_SEED_HEAD] = "injected_message"
        message_entries = sum(
            1 for entry in rewritten if entry.get("type") in {"user", "assistant"}
        )
        artifacts[SEED_HEAD_MESSAGE_COUNT] = str(
            message_entries + (1 if request.message is not None else 0)
        )
        receipt = ForkSeedReceipt(
            restore_level=level,
            history=history,
            derived=CognitionCoordinate(
                run_id=request.derived_run_id,
                unit_key=request.derived_unit_key,
                execution_generation=1,
                point=SessionCursorPoint(
                    session_ref=derived_id,
                    turn_ref=f"fork-seed:{request.fork_request_id}"[:512],
                ),
            ),
            copied_checkpoints=len(rewritten),
            native_artifacts=artifacts,
        )
        self._seeded[request.fork_request_id] = receipt
        return receipt

    # --- collect_points ---------------------------------------------------------------------

    async def collect_points(
        self,
        *,
        namespace: str,
        checkpointer_ref_digest: str,
        source_locator: str | None,
        result_locator: str,
    ) -> tuple[CognitionPointObservation, ...]:
        """K3 convention: `namespace` = harness execution id, `checkpointer_ref_digest` = the
        generation; the same fold the settlement used, over the persisted frames."""

        scope = self._scope_or_refuse()
        try:
            generation = int(checkpointer_ref_digest)
        except ValueError:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="generation_not_numeric") from None
        frames = await self._generation_frames(namespace, generation, scope=scope)
        if not frames:
            raise TimeTravelUnsupported(LANE_PROFILE, reason="frames_missing")
        observed = points.generation_points(
            frames,
            harness_execution_id=namespace,
            generation=generation,
            facts=points.closing_facts_of(frames),
        )
        locators = [item.locator for item in observed]
        start = locators.index(source_locator) + 1 if source_locator in locators else 0
        end = locators.index(result_locator) + 1 if result_locator in locators else len(observed)
        return tuple(observed[start:end])


# --- helpers -----------------------------------------------------------------------------


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _message_uuid(record: CognitionPointRecord) -> str | None:
    value = record.channel_facts.get("message_uuid")
    if isinstance(value, str) and value:
        return value
    point = record.coordinate.point
    if isinstance(point, SessionCursorPoint) and point.step_ref:
        head = point.step_ref.split(":")[0]
        return head or None
    return None


def _cut_ordinal(record: CognitionPointRecord, frames: Sequence[ProviderFrame]) -> int:
    if record.frames is not None:
        return record.frames.to_ordinal
    ordinal = record.channel_facts.get("arrival_ordinal")
    if isinstance(ordinal, int) and not isinstance(ordinal, bool):
        return ordinal
    point = record.coordinate.point
    if isinstance(point, SessionCursorPoint) and point.step_ref is not None:
        for frame in frames:
            if points.step_ref_for(frame) == point.step_ref:
                return frame.arrival_ordinal
    return frames[-1].arrival_ordinal if frames else 0


def _text_of(content: Any) -> str | None:
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        parts = [
            str(block.get("text"))
            for block in content
            if isinstance(block, Mapping) and isinstance(block.get("text"), str)
        ]
        return "\n".join(parts) if parts else None
    return None


def _size_of(durable_ref: Any) -> int:
    if not isinstance(durable_ref, str) or "#" not in durable_ref:
        return 0
    _object, _sep, rest = durable_ref.partition("#")
    _digest, _sep2, size = rest.rpartition(":")
    return int(size) if size.isdigit() else 0


def truncate_entries(
    entries: Sequence[Mapping[str, Any]], uuid: str | None
) -> list[dict[str, Any]] | None:
    """The mirror's entries through the one whose `uuid` is the point's message uuid; None
    when the mirror does not hold it (never a guess at a later cut)."""

    if uuid is None:
        return None
    kept: list[dict[str, Any]] = []
    for entry in entries:
        kept.append(dict(entry))
        if entry.get("uuid") == uuid:
            return kept
    return None


def rewrite_session(entry: Mapping[str, Any], session_id: str) -> dict[str, Any]:
    """The same entry under the derived session id (both spellings the CLI writes)."""

    rewritten = dict(entry)
    for name in ("sessionId", "session_id"):
        if name in rewritten:
            rewritten[name] = session_id
    return rewritten


def entries_from_frames(
    frames: Sequence[ProviderFrame], *, session_id: str
) -> list[dict[str, Any]]:
    """A CLI-shaped transcript (user and assistant entries, parent-linked) rebuilt from the
    persisted frames (R1): the whole body of every `user` and `assistant` message frame,
    labelled `reconstructed_from: frames`; excerpted bodies are left out."""

    entries: list[dict[str, Any]] = []
    parent: str | None = None
    for frame in frames:
        if frame.subordinate_ref is not None:
            continue
        body = points.body_of(frame)
        raw = frame.raw_kind
        if not body or raw not in {"user", "assistant", "user.tool_result"}:
            continue
        uuid = (
            _str(body.get("uuid")) or points.message_uuid_of(frame) or f"mc-{frame.arrival_ordinal}"
        )
        if raw == "user.tool_result":
            # One `user` message carries every tool result block of its step; the lane wrote
            # one frame per block, so the blocks of one uuid merge into one entry.
            block = {name: value for name, value in body.items() if name != "type"}
            block["type"] = "tool_result"
            if entries and entries[-1]["uuid"] == uuid and entries[-1]["type"] == "user":
                entries[-1]["message"]["content"].append(block)
                continue
            kind = "user"
            message: dict[str, Any] = {"role": "user", "content": [block]}
        else:
            kind = raw
            message = {"role": raw, "content": body.get("content")}
            if raw == "assistant":
                for name in ("model", "stop_reason", "usage"):
                    if body.get(name) is not None:
                        message[name] = body[name]
                if body.get("message_id"):
                    message["id"] = body["message_id"]
        entries.append(
            {
                "type": kind,
                "uuid": uuid,
                "parentUuid": parent,
                "sessionId": session_id,
                "message": message,
                "reconstructed_from": "frames",
            }
        )
        parent = uuid
    return entries


__all__ = [
    "ARTIFACT_LABEL",
    "A_DERIVED_SESSION",
    "A_POINT_TURN",
    "A_SEED_HEAD",
    "A_SEED_KIND",
    "A_SOURCE_SESSION",
    "A_TRANSCRIPT_ENTRIES",
    "A_TRANSCRIPT_REF",
    "A_TRUNCATED_AT",
    "A_TRUNCATION",
    "LANE_PROFILE",
    "SEED_KIND_FRAMES",
    "SEED_KIND_MIRROR",
    "WORKSPACE_SNAPSHOT_PREFIX",
    "ClaudeTimeTravel",
    "ClaudeTranscriptReader",
    "SeedArtifactStore",
    "derived_session_id",
    "entries_from_frames",
    "rewrite_session",
    "truncate_entries",
]

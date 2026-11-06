"""Time travel of the hosted session lanes: R1 reads and seeds over persisted frames.

Neither hosted API documents a session fork, a history import or a checkpoint restore
(OPENAI-AGENTS-API-SURFACE-2026-10-30 "Checkpoints, inspection and fork limits"; the Managed
Agents 1.13.0 surface has `create_session` and `send_events` only). What Mission Control
*does* hold for every hosted turn is the Native Event Store: the ordered, redacted Provider
Frames of the session (ADR-0028). `RemoteSessionTimeTravel` is the `TimeTravelLane` the two
hosted lanes share over those frames, at restore level **R1, history `reconstructed`**:

- `read_as_of`: the transcript up to the point, rebuilt from the frames of the point's
  execution generation (every turn of the generation, in arrival order, up to and including
  the point's step frame), as `GraphStateAsOf.messages`; no files (the provider workspace is
  not captured), the native coordinates in `channels["native"]`, and every gap named in
  `withheld` (an excerpted body, the missing workspace);
- `seed_fork`: the derived unit's starting state is a **hydration prompt**: the same
  transcript rendered as text, with the injected message (or a "continue" line) appended,
  bounded and digested, returned in `native_artifacts["seed_prompt"]`. Nothing is written at
  the provider: the derived unit's `start` creates its own session as usual (stamped with the
  fork request) and its first `send_turn` sends the prompt (`seed_turn_text`). Repeating the
  seed is idempotent because it is a pure function of the persisted frames and the request;
  the source session is never touched;
- `collect_points`: the same fold the settlement ran (`remote_session.cognition_points`),
  over the generation's frames, between the source and the result locators.

The kernel convention for session lanes (DESIGN K3): `collect_points(namespace=<harness
execution id>, checkpointer_ref_digest=<generation>)`. Each lane supplies the point rules,
how its frames become messages (`messages_of`) and the derived coordinate a seed stands at.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar, Final
from uuid import UUID

from mission_control.adapters.remote_session.cognition_points import (
    HostedPointRules,
    frame_body,
    generation_points,
)
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
    CognitionPointRef,
    GraphStateAsOf,
    StateAsOf,
    StateMessage,
    ToolCallFact,
)
from mission_control.domain.execution.lanes import LaneSeedHead
from mission_control.domain.frames.body import redact_text, redact_value
from mission_control.domain.frames.contracts import DEFAULT_EXCERPT_CAP_BYTES, ProviderFrame

RESTORE_LEVEL: Final = "R1"
HISTORY: Final = "reconstructed"
# The bound of a hydration prompt (`LaneSeedHead.message` is bounded alike); past it the
# oldest messages are dropped first and the artifact says so.
MAX_SEED_PROMPT_CHARS: Final = 60_000
SEED_PROMPT: Final = "seed_prompt"
SEED_PROMPT_DIGEST: Final = "seed_prompt_digest"
SEED_PROMPT_TRUNCATED: Final = "seed_prompt_truncated"
SEED_HEAD: Final = "seed_head"
SEED_HEAD_INJECTED: Final = "injected_message"
SEED_HEAD_TRANSCRIPT: Final = "transcript"
CONTINUE_LINE: Final = "Continue the work from this point."
PREAMBLE: Final = (
    "You are continuing a previous session of this mission from a recorded point. The "
    "transcript up to that point follows; treat it as your own earlier conversation and "
    "carry on from its end without repeating completed work."
)
FRAME_PAGE: Final = 1_000


class FramesOfExecution:
    """What a hosted time-travel lane reads: the persisted frames of one execution generation."""

    async def frames_of(
        self, harness_execution_id: str, generation: int
    ) -> tuple[ProviderFrame, ...]:
        raise NotImplementedError


class ScopedFrameReader(FramesOfExecution):
    """`FramesOfExecution` over the kernel `FrameReader` for one request scope (the registry
    is composed per deployment; the frame store is scoped per tenant)."""

    def __init__(self, frames: FrameReader, *, request_scope: str, page: int = FRAME_PAGE) -> None:
        self._frames = frames
        self._scope = request_scope
        self._page = page

    async def frames_of(
        self, harness_execution_id: str, generation: int
    ) -> tuple[ProviderFrame, ...]:
        try:
            execution = UUID(harness_execution_id)
        except ValueError:
            return ()
        collected: list[ProviderFrame] = []
        after = 0
        while True:
            page = await self._frames.frames_for_execution(
                self._scope, execution, generation, after_ordinal=after, limit=self._page
            )
            collected.extend(page)
            if len(page) < self._page:
                break
            after = page[-1].arrival_ordinal
        collected.sort(key=lambda frame: frame.arrival_ordinal)
        return tuple(collected)


# --- rendering ---------------------------------------------------------------------------------


def state_message(
    *,
    role: str,
    text: str | None,
    cap: int,
    withheld: list[str],
    message_id: str | None = None,
    name: str | None = None,
    tool_call_id: str | None = None,
    tool_calls: Sequence[tuple[str | None, str, Any]] = (),
    usage: Mapping[str, int] | None = None,
) -> StateMessage:
    """One transcript message, redacted again at read time and excerpted under `cap`."""

    redacted, redactions = redact_text(text) if text else ("", ())
    encoded = redacted.encode("utf-8")
    truncated = len(encoded) > cap
    if truncated:
        withheld.append(f"message {message_id or '?'} text excerpted")
    calls: list[ToolCallFact] = []
    for call_id, call_name, arguments in tool_calls:
        value, _found = redact_value(arguments)
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        oversized = len(canonical.encode("utf-8")) > cap
        calls.append(
            ToolCallFact(
                id=call_id,
                name=(call_name or "tool")[:256],
                arguments=None if oversized or not isinstance(value, dict) else value,
                arguments_digest="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
                arguments_bytes=len(canonical.encode("utf-8")),
                truncated=oversized,
            )
        )
    return StateMessage(
        id=message_id,
        role=role[:32],
        name=name,
        tool_call_id=tool_call_id,
        tool_calls=tuple(calls),
        text=encoded[:cap].decode("utf-8", errors="ignore") if text else None,
        text_bytes=len(encoded),
        text_digest=("sha256:" + hashlib.sha256(encoded).hexdigest()) if text else None,
        truncated=truncated,
        redactions=len(redactions),
        usage=dict(usage or {}),
    )


def render_seed_prompt(
    messages: Sequence[StateMessage],
    *,
    injected: str | None,
    limit: int = MAX_SEED_PROMPT_CHARS,
) -> tuple[str, bool]:
    """The hydration prompt of a seed: preamble, the transcript (oldest dropped first when it
    exceeds `limit`), then the injected message or the continue line."""

    tail = injected.strip() if injected and injected.strip() else CONTINUE_LINE
    lines = [_render_message(message) for message in messages]
    truncated = False
    while lines:
        body = "\n\n".join(lines)
        text = f"{PREAMBLE}\n\n--- transcript ---\n{body}\n--- end of transcript ---\n\n{tail}"
        if len(text) <= limit:
            return text, truncated
        lines.pop(0)
        truncated = True
    text = f"{PREAMBLE}\n\n--- transcript (withheld: oversized) ---\n\n{tail}"
    return text[:limit], True


def _render_message(message: StateMessage) -> str:
    label = f"[{message.role}{' ' + message.name if message.name else ''}]"
    parts = [message.text or ""]
    for call in message.tool_calls:
        arguments = (
            json.dumps(call.arguments, sort_keys=True, default=str)
            if call.arguments is not None
            else f"<arguments withheld: {call.arguments_bytes} bytes>"
        )
        parts.append(f"(tool call {call.name}: {arguments})")
    if message.tool_call_id:
        label = f"[{message.role} for {message.tool_call_id}]"
    return f"{label} " + "\n".join(part for part in parts if part)


def seed_turn_text(seed: LaneSeedHead | None) -> str | None:
    """The first turn's text of a seeded unit (the prompt a hosted `seed_fork` staged), or
    None when the seed carries no prompt (another lane's seed, or none)."""

    if seed is None:
        return None
    prompt = seed.native_artifacts.get(SEED_PROMPT)
    if not prompt:
        return None
    if seed.message and seed.native_artifacts.get(SEED_HEAD) != SEED_HEAD_INJECTED:
        prompt = f"{prompt}\n\n{seed.message}"
    return prompt


def seed_metadata(seed: LaneSeedHead | None) -> dict[str, str]:
    """Secret-free provider metadata naming the fork a seeded session continues."""

    if seed is None:
        return {}
    return {
        "mc_fork_request": seed.fork_request_id[:512],
        "mc_fork_source": f"{seed.source_run_id}/{seed.source_unit_key}"[:512],
        "mc_fork_point": seed.point_locator[:512],
    }


# --- the lane base ------------------------------------------------------------------------------


class RemoteSessionTimeTravel(ABC):
    """`TimeTravelLane` of a hosted session lane at R1 over persisted frames (module doc)."""

    profile: ClassVar[str]
    point_kind: ClassVar[str]
    rules: ClassVar[HostedPointRules]

    def __init__(
        self,
        frames: FramesOfExecution,
        *,
        excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES,
        seed_prompt_chars: int = MAX_SEED_PROMPT_CHARS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._frames = frames
        self._cap = excerpt_cap_bytes
        self._seed_limit = seed_prompt_chars
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def lane_profile(self) -> str:
        return self.profile

    @abstractmethod
    def messages_of(
        self, frame: ProviderFrame, body: Mapping[str, Any], withheld: list[str]
    ) -> tuple[StateMessage, ...]:
        """The transcript messages one frame contributes (empty for status frames)."""

    @abstractmethod
    def derived_point(self, request: ForkSeedRequest) -> CognitionPointRef:
        """The coordinate the derived unit's `fork_seed` point stands at (its session is
        created by `start`; this names the namespace the kernel gave it)."""

    # --- reads -------------------------------------------------------------------------------

    async def read_as_of(self, record: CognitionPointRecord) -> StateAsOf:
        self._check_kind(record.coordinate.point)
        frames, cut = await self._frames_to(record)
        withheld: list[str] = []
        messages = self._messages(frames, withheld)
        points = generation_points(frames, self.rules)
        usage: dict[str, int] = {}
        step: int | None = None
        for index, point in enumerate(points):
            for key, amount in point.usage_delta.items():
                usage[key] = usage.get(key, 0) + int(amount)
            if point.locator == record.coordinate.locator:
                step = index
                break
        withheld.append("workspace_files_not_captured: R1 reconstructs the transcript only")
        withheld.append("secret_values_unknown_at_read: pattern redaction only")
        turns = {frame.native_turn_ref for frame in frames if frame.native_turn_ref}
        state = GraphStateAsOf(
            messages=messages,
            channels={
                "native": {
                    "lane_profile": self.profile,
                    "session_ref": cut.native_session_ref,
                    "turn_ref": cut.native_turn_ref,
                    "point_locator": record.coordinate.locator,
                    "frames_to_point": len(frames),
                    "turns_to_point": len(turns),
                    "last_frame_key": cut.provider_key,
                }
            },
            step=step,
            source=record.source,
            stamps={"mc_restore_level": RESTORE_LEVEL, "mc_history": HISTORY},
            withheld=tuple(dict.fromkeys(withheld)),
        )
        return StateAsOf(
            point=record,
            restore_level=RESTORE_LEVEL,
            history=HISTORY,
            state=state,
            usage_to_point=usage,
            observed_at=self._clock(),
        )

    # --- seeds -------------------------------------------------------------------------------

    async def seed_fork(self, request: ForkSeedRequest) -> ForkSeedReceipt:
        source = request.source
        self._check_kind(source.coordinate.point)
        frames, cut = await self._frames_to(source)
        withheld: list[str] = []
        messages = self._messages(frames, withheld)
        prompt, truncated = render_seed_prompt(
            messages, injected=request.message, limit=self._seed_limit
        )
        artifacts = {
            "source_lane_profile": self.profile,
            "source_session_ref": cut.native_session_ref,
            "source_turn_ref": cut.native_turn_ref or "",
            "source_point_locator": source.coordinate.locator,
            "source_harness_execution_id": str(cut.harness_execution_id),
            "source_generation": str(cut.generation),
            "frames_to_point": str(len(frames)),
            SEED_PROMPT: prompt,
            SEED_PROMPT_DIGEST: "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            SEED_PROMPT_TRUNCATED: "true" if truncated else "false",
            SEED_HEAD: SEED_HEAD_INJECTED if request.message is not None else SEED_HEAD_TRANSCRIPT,
            SEED_HEAD_MESSAGE_COUNT: str(len(messages) + (1 if request.message is not None else 0)),
            "derived_namespace": request.derived_namespace,
        }
        if withheld:
            artifacts["withheld"] = "; ".join(dict.fromkeys(withheld))[:2_048]
        derived = CognitionCoordinate(
            run_id=request.derived_run_id,
            unit_key=request.derived_unit_key,
            execution_generation=1,
            point=self.derived_point(request),
        )
        return ForkSeedReceipt(
            restore_level=RESTORE_LEVEL,
            history=HISTORY,
            derived=derived,
            copied_checkpoints=len(messages),
            native_artifacts=artifacts,
        )

    # --- re-derivation -----------------------------------------------------------------------

    async def collect_points(
        self,
        *,
        namespace: str,
        checkpointer_ref_digest: str,
        source_locator: str | None,
        result_locator: str,
    ) -> tuple[CognitionPointObservation, ...]:
        if not checkpointer_ref_digest.isdigit():
            raise TimeTravelUnsupported(self.profile, reason="generation_unknown")
        frames = await self._frames.frames_of(namespace, int(checkpointer_ref_digest))
        if not frames:
            raise TimeTravelUnsupported(self.profile, reason="frames_missing")
        points = generation_points(frames, self.rules)
        locators = [point.locator for point in points]
        if result_locator not in locators:
            raise TimeTravelUnsupported(self.profile, reason="result_point_missing")
        end = locators.index(result_locator)
        start = locators.index(source_locator) + 1 if source_locator in locators else 0
        return tuple(points[start : end + 1])

    # --- internals ---------------------------------------------------------------------------

    def _check_kind(self, point: CognitionPointRef) -> None:
        if point.kind != self.point_kind:
            raise TimeTravelUnsupported(self.profile, reason=f"point_kind_not_{self.point_kind}")

    async def _frames_to(
        self, record: CognitionPointRecord
    ) -> tuple[tuple[ProviderFrame, ...], ProviderFrame]:
        """The generation's frames up to and including the point's step frame, and that frame."""

        execution = record.coordinate.harness_execution_id
        if execution is None:
            raise TimeTravelUnsupported(self.profile, reason="execution_unknown")
        frames = await self._frames.frames_of(execution, record.coordinate.execution_generation)
        if not frames:
            raise TimeTravelUnsupported(self.profile, reason="frames_missing")
        locator = record.coordinate.locator
        for frame in frames:
            if frame.native_turn_ref is None:
                continue
            point = self.rules.point_for(frame, frame.native_session_ref, frame.native_turn_ref)
            if point.locator == locator:
                return tuple(f for f in frames if f.arrival_ordinal <= frame.arrival_ordinal), frame
        raise TimeTravelUnsupported(self.profile, reason="point_frame_missing")

    def _messages(
        self, frames: Sequence[ProviderFrame], withheld: list[str]
    ) -> tuple[StateMessage, ...]:
        messages: list[StateMessage] = []
        for frame in frames:
            body = frame_body(frame)
            if (
                not body
                and frame.body_bytes
                and len(frame.body_excerpt.encode()) < frame.body_bytes
            ):
                withheld.append(f"frame {frame.provider_key} body excerpted")
            messages.extend(self.messages_of(frame, body, withheld))
        return tuple(messages)


__all__ = [
    "CONTINUE_LINE",
    "HISTORY",
    "MAX_SEED_PROMPT_CHARS",
    "RESTORE_LEVEL",
    "SEED_HEAD",
    "SEED_HEAD_INJECTED",
    "SEED_HEAD_TRANSCRIPT",
    "SEED_PROMPT",
    "SEED_PROMPT_DIGEST",
    "SEED_PROMPT_TRUNCATED",
    "FramesOfExecution",
    "RemoteSessionTimeTravel",
    "ScopedFrameReader",
    "render_seed_prompt",
    "seed_metadata",
    "seed_turn_text",
    "state_message",
]

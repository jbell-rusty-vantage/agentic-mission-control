"""Frame capture profiles: what a `FrameWriter` promotes, at which cap (1.4.4, TR-D2a).

Capture behaviour is a system lever, never a manifest field: the deployment setting
`MISSION_CONTROL_FRAME_CAPTURE_PROFILE` (`bootstrap/settings.py`) names one profile and
`bootstrap/frame_capture.py::compose_frame_capture` builds the `FrameCapture` (the chosen
policy and the promoter) that composition hands the writer sites it wires. Coordinator agents
and `provider_options` carry nothing about capture.

Two extension points cover "different transcript storage behaviour", both chosen in
composition:

- a new `FrameCapturePolicy` entry in `CAPTURE_PROFILES` (which kinds are promoted, the
  excerpt cap, the body ceiling, whether whole model-request batches are kept);
- a new `FrameBodyPromoter` implementation (where promoted bodies go and how they are
  referenced; `adapters/storage/frame_body_promoter.py` is the payload-store one).

The writer, the recorder and the Transcript reader do not change for either.

`standard` (the default) promotes the per-message objects of a `model_request` plus the
batch digest, and the oversized bodies of tool results, messages, run results, the
materialized environment and a subagent's closing frame. `full_requests` is `standard` plus
the whole batch of every `model_request`: the byte-exact record for T0 proofs and
investigations; its storage grows with the square of the turn length.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Protocol

from mission_control.domain.frames.contracts import (
    DEFAULT_EXCERPT_CAP_BYTES,
    FULL_BODY_KINDS,
    FrameKind,
    HarnessExecutionHandle,
)

FULL_BODY_MAX_BYTES = 2 * 1024 * 1024


class FrameBodyPromoter(Protocol):
    """Stores one promoted frame body and returns the reference the frame row records."""

    async def promote_frame_body(
        self,
        handle: HarnessExecutionHandle,
        *,
        promotion_key: str,
        kind: FrameKind,
        digest: str,
        media_type: str,
        payload: bytes,
    ) -> str: ...


@dataclass(frozen=True)
class FrameCapturePolicy:
    """One capture profile."""

    name: str
    excerpt_cap_bytes: int
    """The profile's excerpt cap; the writer's own `excerpt_cap_bytes` is what it applies."""
    promote_kinds: frozenset[FrameKind]
    max_body_bytes: int
    full_requests: bool
    """Promote the whole `[system, *messages]` batch of every `model_request`."""
    message_objects: bool
    """Promote each human/system message of a `model_request` once, by digest."""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a capture profile needs a name")
        if self.excerpt_cap_bytes <= 0 or self.max_body_bytes <= 0:
            raise ValueError("capture caps must be positive")
        object.__setattr__(self, "promote_kinds", frozenset(self.promote_kinds))

    def eligible(self, kind: FrameKind, body_bytes: int, cap: int) -> bool:
        """Oversized-body promotion: a promoted kind that may carry a full body, larger than
        the excerpt cap and within the ceiling. Deltas never qualify."""

        return (
            kind in self.promote_kinds
            and kind in FULL_BODY_KINDS
            and cap < body_bytes <= self.max_body_bytes
        )


STANDARD_PROFILE = FrameCapturePolicy(
    name="standard",
    excerpt_cap_bytes=DEFAULT_EXCERPT_CAP_BYTES,
    promote_kinds=frozenset(
        {
            FrameKind.MODEL_REQUEST,
            FrameKind.TOOL_CALL_COMPLETED,
            FrameKind.TOOL_CALL_FAILED,
            FrameKind.MESSAGE,
            FrameKind.RUN_RESULT,
            FrameKind.ENVIRONMENT_MATERIALIZED,
            FrameKind.SUBAGENT_ENDED,
        }
    ),
    max_body_bytes=FULL_BODY_MAX_BYTES,
    full_requests=False,
    message_objects=True,
)

FULL_REQUESTS_PROFILE = replace(STANDARD_PROFILE, name="full_requests", full_requests=True)

CAPTURE_PROFILES: Mapping[str, FrameCapturePolicy] = MappingProxyType(
    {
        STANDARD_PROFILE.name: STANDARD_PROFILE,
        FULL_REQUESTS_PROFILE.name: FULL_REQUESTS_PROFILE,
    }
)

DEFAULT_CAPTURE_PROFILE = STANDARD_PROFILE.name


def capture_profile(name: str) -> FrameCapturePolicy:
    """The registered profile; `ValueError` names the known profiles for an unknown name."""

    try:
        return CAPTURE_PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(CAPTURE_PROFILES))
        raise ValueError(f"unknown frame capture profile {name!r}; known: {known}") from None


@dataclass(frozen=True)
class FrameCapture:
    """What composition hands a writer site: the policy and, when bodies can be stored,
    the promoter (`FrameWriter(..., capture=policy, promoter=promoter)`). Without a promoter
    the writer keeps excerpts only."""

    policy: FrameCapturePolicy
    promoter: FrameBodyPromoter | None = None


__all__ = [
    "CAPTURE_PROFILES",
    "DEFAULT_CAPTURE_PROFILE",
    "FULL_BODY_MAX_BYTES",
    "FULL_REQUESTS_PROFILE",
    "STANDARD_PROFILE",
    "FrameBodyPromoter",
    "FrameCapture",
    "FrameCapturePolicy",
    "capture_profile",
]

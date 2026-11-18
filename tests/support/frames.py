"""Seed the src `InMemoryFrameStore` with already-built provider frames.

A reader test that only needs frames to exist (replay, point reconciliation) holds them in the
one in-memory frame store rather than a tuple-backed reader of its own: each frame's run and
activation are registered, its harness execution is opened at its first generation, and the
frames are appended through the store's own `append`, so scope, generation and ordinal rules
apply as they do to frames a lane writes.
"""

from __future__ import annotations

from collections.abc import Iterable

from mission_control.application.frames.sink import InMemoryFrameStore
from mission_control.domain.frames.contracts import HarnessExecutionStart, ProviderFrame

_DIGEST = "sha256:" + "0" * 64


async def hold_frames(store: InMemoryFrameStore, frames: Iterable[ProviderFrame]) -> None:
    """Append `frames` to `store`, registering the runs and executions they name."""

    ordered = sorted(frames, key=lambda frame: (frame.generation, frame.arrival_ordinal))
    opened: set[object] = set()
    for frame in ordered:
        request_scope = frame.scope.request_scope
        run_key = str(frame.run_id)
        activation_key = str(frame.activation_id)
        if frame.harness_execution_id not in opened:
            store.register_run(
                request_scope, run_key, frame.run_id, {activation_key: frame.activation_id}
            )
            await store.open_execution(
                HarnessExecutionStart(
                    harness_execution_id=frame.harness_execution_id,
                    request_scope=request_scope,
                    run_key=run_key,
                    activation_key=activation_key,
                    attempt_no=frame.attempt_no,
                    generation=frame.generation,
                    lane_profile=frame.lane_profile,
                    native_session_ref=frame.native_session_ref,
                    runtime_kind="fixture",
                    provider_kind="fixture",
                    placement_kind="local_in_worker",
                    intended_binding_digest=_DIGEST,
                )
            )
            opened.add(frame.harness_execution_id)
    await store.append(ordered)


async def store_holding(frames: Iterable[ProviderFrame]) -> InMemoryFrameStore:
    """A fresh `InMemoryFrameStore` holding exactly `frames`."""

    store = InMemoryFrameStore()
    await hold_frames(store, frames)
    return store


__all__ = ["hold_frames", "store_holding"]

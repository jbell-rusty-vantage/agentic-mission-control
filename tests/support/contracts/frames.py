"""Frame store contract: `InMemoryFrameStore` versus `PostgresFrameRepository` (SPEC-03).

The scenarios open a harness execution for an admitted run, append provider frames and read them
back, and assert what a lane writer and a reader observe: the append receipt, ordering by
arrival ordinal, idempotency on `(execution, generation, provider_key)`, ordinal continuation
past the persisted cursor, the generation fence, refusals and scoping by tenant.

Runners: `tests/unit/frames/test_frame_store_contract.py` (in memory) and
`tests/integration/postgres/test_frame_store_contract_postgres.py` (PostgreSQL).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest

from mission_control.application.frames.sink import (
    FrameOrdinalConflict,
    HarnessExecutionNotFound,
)
from mission_control.domain.frames.body import frame_body
from mission_control.domain.frames.contracts import (
    FrameKind,
    FrameScope,
    HarnessExecutionHandle,
    HarnessExecutionStart,
    ProviderFrame,
    is_closing,
)
from tests.fixtures.provider_frames import FRAME_NOW


@dataclass
class FrameStoreSubject:
    """The store under test (FrameStore + FrameReader) and the start of one harness execution
    whose run, activation and attempt the store knows, plus a second tenant scope."""

    store: Any
    start: HarnessExecutionStart
    other_scope: str

    def at(self, generation: int) -> HarnessExecutionStart:
        return self.start.model_copy(update={"generation": generation})


Scenario = Callable[[FrameStoreSubject], Awaitable[None]]


def frame(
    handle: HarnessExecutionHandle,
    ordinal: int,
    key: str,
    kind: FrameKind = FrameKind.MESSAGE_DELTA,
    *,
    generation: int | None = None,
    seconds: int | None = None,
    body: Any = None,
    **updates: Any,
) -> ProviderFrame:
    """A persisted-shape frame stamped with the handle's identity."""

    generation = generation or handle.generation
    payload = frame_body(body if body is not None else {"key": key})
    values: dict[str, Any] = {
        "frame_id": uuid5(handle.harness_execution_id, f"{generation}:{key}:{uuid4()}"),
        "scope": handle.scope,
        "run_id": handle.run_id,
        "activation_id": handle.activation_id,
        "attempt_no": handle.attempt_no,
        "harness_execution_id": handle.harness_execution_id,
        "generation": generation,
        "lane_profile": handle.lane_profile,
        "native_session_ref": handle.native_session_ref,
        "native_turn_ref": "turn-1",
        "provider_key": key,
        "arrival_ordinal": ordinal,
        "observed_at": FRAME_NOW + timedelta(seconds=ordinal if seconds is None else seconds),
        "kind": kind,
        "closing": is_closing(kind),
        "body_digest": payload.digest,
        "body_bytes": payload.body_bytes,
        "body_media_type": "application/json",
        "body_excerpt": payload.excerpt,
        "redactions": payload.redactions,
        "raw_kind": f"fixture.{kind.value}",
    }
    values.update(updates)
    return ProviderFrame(**values)


def _keys(frames: tuple[ProviderFrame, ...]) -> list[tuple[int, str]]:
    return [(item.arrival_ordinal, item.provider_key) for item in frames]


async def frames_are_appended_and_read_in_order(subject: FrameStoreSubject) -> None:
    store, scope = subject.store, subject.start.request_scope
    handle = await store.open_execution(subject.at(1))
    assert handle.harness_execution_id == subject.start.harness_execution_id
    assert handle.generation == 1 and handle.last_cursor is None
    batch = [
        frame(handle, 1, "a"),
        frame(handle, 2, "b"),
        frame(handle, 3, "c", FrameKind.RUN_RESULT),
    ]
    receipt = await store.append(batch)
    assert (receipt.new, receipt.duplicate, receipt.stale) == (3, 0, 0)
    assert receipt.new_frame_ids == tuple(item.frame_id for item in batch)
    stored = await store.frames_for_execution(scope, handle.harness_execution_id, 1)
    assert stored == tuple(batch)
    assert _keys(
        await store.frames_for_execution(scope, handle.harness_execution_id, 1, after_ordinal=1)
    ) == [(2, "b"), (3, "c")]
    assert _keys(
        await store.frames_for_execution(scope, handle.harness_execution_id, 1, closing_only=True)
    ) == [(3, "c")]
    assert _keys(
        await store.frames_for_execution(scope, handle.harness_execution_id, 1, limit=2)
    ) == [(1, "a"), (2, "b")]
    cursor = await store.last_cursor(handle.harness_execution_id, 1, request_scope=scope)
    assert cursor is not None and (cursor.arrival_ordinal, cursor.provider_key) == (3, "c")
    assert await store.current_generation(scope, handle.harness_execution_id) == 1
    assert await store.frames_for_run(scope, handle.run_id) == tuple(batch)
    assert _keys(await store.frames_for_run(scope, handle.run_id, closing_only=True)) == [(3, "c")]
    # Reopening resumes from the persisted cursor.
    reopened = await store.open_execution(subject.at(1))
    assert reopened.last_cursor == cursor
    assert await store.append([]) == type(receipt)(new=0, duplicate=0, stale=0)


async def append_is_idempotent_on_the_provider_key(subject: FrameStoreSubject) -> None:
    store, scope = subject.store, subject.start.request_scope
    handle = await store.open_execution(subject.at(1))
    batch = [frame(handle, 1, "a"), frame(handle, 2, "b")]
    await store.append(batch)
    replay = await store.append(batch)
    assert (replay.new, replay.duplicate, replay.stale) == (0, 2, 0)
    assert replay.new_frame_ids == ()
    # The first write of a provider key wins: a changed body under the same key is a duplicate.
    changed = frame(handle, 3, "a", body={"changed": True})
    assert (await store.append([changed])).duplicate == 1
    assert await store.frames_for_execution(scope, handle.harness_execution_id, 1) == tuple(batch)


async def a_new_frame_continues_past_the_persisted_cursor(subject: FrameStoreSubject) -> None:
    store, scope = subject.store, subject.start.request_scope
    handle = await store.open_execution(subject.at(1))
    await store.append([frame(handle, 1, "a"), frame(handle, 2, "b")])
    # A second writer that read an old cursor proposes ordinals already taken: the batch is
    # shifted past the persisted cursor, keeping its order and gaps.
    late = [frame(handle, 1, "c"), frame(handle, 3, "d")]
    receipt = await store.append(late)
    assert receipt.new == 2
    assert receipt.new_frame_ids == tuple(item.frame_id for item in late)
    assert _keys(await store.frames_for_execution(scope, handle.harness_execution_id, 1)) == [
        (1, "a"),
        (2, "b"),
        (3, "c"),
        (5, "d"),
    ]
    cursor = await store.last_cursor(handle.harness_execution_id, 1, request_scope=scope)
    assert cursor is not None and (cursor.arrival_ordinal, cursor.provider_key) == (5, "d")


async def a_malformed_batch_is_refused_whole(subject: FrameStoreSubject) -> None:
    store, scope = subject.store, subject.start.request_scope
    handle = await store.open_execution(subject.at(1))
    await store.append([frame(handle, 1, "a")])
    with pytest.raises(FrameOrdinalConflict):
        await store.append([frame(handle, 2, "b"), frame(handle, 2, "c")])
    assert _keys(await store.frames_for_execution(scope, handle.harness_execution_id, 1)) == [
        (1, "a")
    ]
    foreign_run = frame(handle, 2, "x", run_id=UUID(int=7))
    with pytest.raises(ValueError):
        await store.append([foreign_run])
    assert _keys(await store.frames_for_execution(scope, handle.harness_execution_id, 1)) == [
        (1, "a")
    ]


async def an_older_generation_is_fenced(subject: FrameStoreSubject) -> None:
    store, scope = subject.store, subject.start.request_scope
    first = await store.open_execution(subject.at(1))
    await store.append([frame(first, 1, "g1-a"), frame(first, 2, "g1-b")])
    second = await store.open_execution(subject.at(2))
    assert second.generation == 2 and second.last_cursor is None
    assert await store.current_generation(scope, first.harness_execution_id) == 2
    stale = await store.append([frame(first, 3, "g1-late")])
    assert (stale.new, stale.duplicate, stale.stale) == (0, 0, 1)
    fresh = await store.append([frame(second, 1, "g2-a")])
    assert fresh.new == 1
    assert _keys(await store.frames_for_execution(scope, first.harness_execution_id, 1)) == [
        (1, "g1-a"),
        (2, "g1-b"),
    ]
    assert _keys(await store.frames_for_execution(scope, first.harness_execution_id, 2)) == [
        (1, "g2-a")
    ]
    # Reopening an older generation never lowers the current one.
    await store.open_execution(subject.at(1))
    assert await store.current_generation(scope, first.harness_execution_id) == 2
    # A frame of a newer generation advances the execution to it.
    assert (await store.append([frame(second, 1, "g3-a", generation=3)])).new == 1
    assert await store.current_generation(scope, first.harness_execution_id) == 3
    assert (await store.append([frame(second, 2, "g2-late")])).stale == 1


async def frames_for_run_are_ordered_by_time_then_generation(
    subject: FrameStoreSubject,
) -> None:
    store, scope = subject.store, subject.start.request_scope
    first = await store.open_execution(subject.at(1))
    await store.append([frame(first, 1, "g1-a", seconds=1), frame(first, 2, "g1-b", seconds=5)])
    second = await store.open_execution(subject.at(2))
    await store.append([frame(second, 1, "g2-a", seconds=5), frame(second, 2, "g2-b", seconds=2)])
    ordered = await store.frames_for_run(scope, first.run_id)
    assert [item.provider_key for item in ordered] == ["g1-a", "g2-b", "g1-b", "g2-a"]
    assert [
        item.provider_key for item in await store.frames_for_run(scope, first.run_id, limit=2)
    ] == [
        "g1-a",
        "g2-b",
    ]


async def unknown_executions_and_bindings_are_refused(subject: FrameStoreSubject) -> None:
    store = subject.store
    handle = await store.open_execution(subject.at(1))
    unopened = handle.model_copy(update={"harness_execution_id": uuid4()})
    with pytest.raises(HarnessExecutionNotFound):
        await store.append([frame(unopened, 1, "a")])
    with pytest.raises(HarnessExecutionNotFound):
        await store.open_execution(
            subject.start.model_copy(
                update={"harness_execution_id": uuid4(), "run_key": "run-never-admitted"}
            )
        )
    with pytest.raises(HarnessExecutionNotFound):
        await store.open_execution(
            subject.start.model_copy(
                update={"harness_execution_id": uuid4(), "activation_key": "unit-never-recorded"}
            )
        )
    # The same execution identity cannot be reopened under another binding.
    with pytest.raises(ValueError):
        await store.open_execution(
            subject.start.model_copy(update={"intended_binding_digest": "sha256:" + "9" * 64})
        )


async def scopes_are_isolated(subject: FrameStoreSubject) -> None:
    store, scope, other = subject.store, subject.start.request_scope, subject.other_scope
    handle = await store.open_execution(subject.at(1))
    await store.append([frame(handle, 1, "a")])
    execution = handle.harness_execution_id
    assert await store.frames_for_execution(other, execution, 1) == ()
    assert await store.frames_for_run(other, handle.run_id) == ()
    assert await store.last_cursor(execution, 1, request_scope=other) is None
    assert await store.current_generation(other, execution) is None
    with pytest.raises(HarnessExecutionNotFound):
        await store.open_execution(subject.start.model_copy(update={"request_scope": other}))
    # A frame stamped with another tenant's scope cannot reach this execution.
    foreign = frame(handle, 2, "b", scope=FrameScope.from_request_scope(other))
    with pytest.raises(HarnessExecutionNotFound):
        await store.append([foreign])
    assert _keys(await store.frames_for_execution(scope, execution, 1)) == [(1, "a")]


SCENARIOS: tuple[Scenario, ...] = (
    frames_are_appended_and_read_in_order,
    append_is_idempotent_on_the_provider_key,
    a_new_frame_continues_past_the_persisted_cursor,
    a_malformed_batch_is_refused_whole,
    an_older_generation_is_fenced,
    frames_for_run_are_ordered_by_time_then_generation,
    unknown_executions_and_bindings_are_refused,
    scopes_are_isolated,
)

__all__ = ["SCENARIOS", "FrameStoreSubject", "Scenario", "frame"]

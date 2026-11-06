"""WP-TR-5 (TRACING-PROPOSAL §P6): the remote saver's bounds and typed outcomes on the Deep
Agents lane, over the in-memory saver.

The locator digest names where a saver lives without its DSN; a budgeted points walk folds
the result point and records `points_status: incomplete`; a lane refuses a point whose key
names a location it does not serve (`saver_not_served`) and reports a saver that does not
answer as `saver_unreachable`, never as a bare driver error. Tracing Stage 3: the digest's
host normalisation (R2-12) and a programming error that is not an unreachable saver (R2-21).
"""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from mission_control.adapters.deep_agents.checkpoint_reads import ROOT_CHECKPOINT_NS
from mission_control.adapters.deep_agents.cognition_points import (
    collect_points,
    points_incomplete,
    walk_points,
)
from mission_control.adapters.deep_agents.persistence import (
    RUNTIME_SCHEMA,
    saver_locator_digest,
)
from mission_control.adapters.deep_agents.time_travel import DeepAgentsTimeTravel
from mission_control.application.execution.harness.time_travel import TimeTravelUnsupported
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.checkpoint_lineage import CheckpointCapture
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from tests.unit.deep_agents.test_cognition_points_collector import (
    DIGEST,
    THREAD,
    _graph,
    _lineage,
    _plan,
)

LOCATOR = "sha256:" + "1" * 64
OTHER = "sha256:" + "2" * 64


class SlowSaver:
    """The in-memory saver with a per-read delay (a remote saver on a slow link)."""

    def __init__(self, inner: InMemorySaver, delay: float) -> None:
        self._inner = inner
        self.delay = delay
        self.reads = 0

    async def aget_tuple(self, config: Any) -> Any:
        self.reads += 1
        await asyncio.sleep(self.delay)
        return await self._inner.aget_tuple(config)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class UnreachableSaver:
    def __init__(self, inner: InMemorySaver) -> None:
        self._inner = inner

    async def aget_tuple(self, config: Any) -> Any:
        raise psycopg.OperationalError("connection refused")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def _run(saver: InMemorySaver) -> tuple[Any, str, str, str | None]:
    agent = _graph(saver)
    plan = _plan("activity-attempt:11111111-1111-5111-8111-111111111111")
    config = {
        "configurable": {"thread_id": THREAD, "checkpoint_ns": ROOT_CHECKPOINT_NS},
        "metadata": plan.invocation_metadata(),
    }
    await agent.ainvoke({"messages": [HumanMessage(content="one", id="h-1")]}, config=config)
    lineage = await _lineage(saver)
    return plan, lineage[0][0], lineage[-1][0], lineage[-1][1]


def test_locator_digest_names_the_location_never_the_secret() -> None:
    first = saver_locator_digest("postgresql://user:secret@db.example:5433/runtime")
    assert first == saver_locator_digest("postgresql://other:pw@db.example:5433/runtime")
    assert first != saver_locator_digest("postgresql://user:secret@db.example:5434/runtime")
    assert first != saver_locator_digest("postgresql://user:secret@db.example:5433/other")
    assert first != saver_locator_digest(
        "postgresql://user:secret@db.example:5433/runtime?options=-c%20search_path%3Dmc_test"
    )
    assert first.startswith("sha256:") and "secret" not in first


@pytest.mark.asyncio
async def test_a_budgeted_walk_keeps_the_result_point_and_records_the_gap() -> None:
    saver = InMemorySaver()
    _plan, first_id, result_id, _parent = await _run(saver)
    complete = await walk_points(
        saver,
        thread=THREAD,
        checkpointer_ref_digest=DIGEST,
        source_id=None,
        result_id=result_id,
        saver_locator_digest=LOCATOR,
    )
    assert len(complete) >= 3
    assert not points_incomplete(complete[-1])
    assert all(point.point.key.saver_locator_digest == LOCATOR for point in complete)

    slow = SlowSaver(saver, delay=0.02)
    partial = await walk_points(
        slow,  # type: ignore[arg-type]
        thread=THREAD,
        checkpointer_ref_digest=DIGEST,
        source_id=None,
        result_id=result_id,
        saver_locator_digest=LOCATOR,
        budget_seconds=0.005,
    )
    result = partial[-1]
    assert result.point.key.checkpoint_id == result_id
    assert "result" in result.roles
    assert points_incomplete(result)
    assert result.channel_facts["points_walked"] == len(partial)
    assert len(partial) < len(complete)
    assert first_id not in {point.point.key.checkpoint_id for point in partial}
    # The reconciler's walk (no budget) completes the same lineage from the same saver.
    again = await walk_points(
        slow,  # type: ignore[arg-type]
        thread=THREAD,
        checkpointer_ref_digest=DIGEST,
        source_id=None,
        result_id=result_id,
    )
    assert [point.point.key.checkpoint_id for point in again] == [
        point.point.key.checkpoint_id for point in complete
    ]


@pytest.mark.asyncio
async def test_collect_points_passes_the_budget_and_skips_nested_walks_when_exhausted() -> None:
    saver = InMemorySaver()
    plan, _first, result_id, parent_id = await _run(saver)
    capture = CheckpointCapture(
        namespace=THREAD,
        invocation_id=plan.invocation_id,
        source_key=None,
        result_key=QualifiedCheckpointKey(
            checkpointer_ref_digest=DIGEST,
            thread_id=THREAD,
            checkpoint_id=result_id,
            parent_checkpoint_id=parent_id,
        ),
        ancestry_verified=True,
        stamped_checkpoint_count=1,
        redacted_summary_digest=DIGEST,
    )
    slow = SlowSaver(saver, delay=0.02)
    points = await collect_points(
        slow,  # type: ignore[arg-type]
        plan,
        capture,
        recorder=None,
        saver_locator_digest=LOCATOR,
        budget_seconds=0.001,
    )
    assert points and points_incomplete(points[-1])
    assert points[-1].point.key.saver_locator_digest == LOCATOR


@pytest.mark.asyncio
async def test_the_lane_refuses_a_point_of_another_location_and_names_an_unreachable_saver() -> (
    None
):
    saver = InMemorySaver()
    _plan, _first, result_id, _parent = await _run(saver)
    lane = DeepAgentsTimeTravel({DIGEST: saver}, locators={DIGEST: LOCATOR})
    served = QualifiedCheckpointKey(
        checkpointer_ref_digest=DIGEST,
        thread_id=THREAD,
        checkpoint_id=result_id,
        saver_locator_digest=LOCATOR,
    )
    assert lane._saver_for(served) is saver
    legacy = served.model_copy(update={"saver_locator_digest": None})
    assert lane._saver_for(legacy) is saver  # keys recorded before 1.4.4 name no location
    elsewhere = served.model_copy(update={"saver_locator_digest": OTHER})
    with pytest.raises(TimeTravelUnsupported) as refused:
        lane._saver_for(elsewhere)
    assert refused.value.reason == "saver_not_served" and refused.value.saver == DIGEST
    unknown = served.model_copy(update={"checkpointer_ref_digest": OTHER})
    with pytest.raises(TimeTravelUnsupported, match="checkpointer_not_registered"):
        lane._saver_for(unknown)
    # The reconciler's walk through the lane stamps the served locator on every key.
    walked = await lane.collect_points(
        namespace=THREAD,
        checkpointer_ref_digest=DIGEST,
        source_locator=None,
        result_locator=result_id,
    )
    assert {point.point.key.saver_locator_digest for point in walked} == {LOCATOR}

    down = DeepAgentsTimeTravel({DIGEST: UnreachableSaver(saver)}, locators={DIGEST: LOCATOR})  # type: ignore[dict-item]
    with pytest.raises(TimeTravelUnsupported) as unreachable:
        await down.collect_points(
            namespace=THREAD,
            checkpointer_ref_digest=DIGEST,
            source_locator=None,
            result_locator=result_id,
        )
    assert unreachable.value.reason == "saver_unreachable" and unreachable.value.saver == DIGEST


def test_the_locator_digest_ignores_host_spelling_and_keeps_the_local_stack_digest() -> None:
    """Tracing Stage 3 (R2-12): the API and the workers compute the digest from their own
    DSNs; case, credentials, the default port and the loopback aliases do not count, and the
    local stack's `127.0.0.1` digest is the one recorded before the normalisation."""

    local = saver_locator_digest("postgresql://belllabs:pw@127.0.0.1:55432/belllabs")
    assert local == sha256_digest(
        {"host": "127.0.0.1", "port": "55432", "dbname": "belllabs", "schema": RUNTIME_SCHEMA}
    )
    assert local == saver_locator_digest("postgresql://other:x@localhost:55432/belllabs")
    assert local == saver_locator_digest("postgresql://other:x@LOCALHOST:55432/belllabs")
    assert saver_locator_digest("postgresql://u@DB.Example/runtime") == saver_locator_digest(
        "postgresql://v:pw@db.example:5432/runtime?sslmode=require"
    )
    # Two names of one remote server stay two locations: configure both processes alike.
    assert saver_locator_digest("postgresql://u@db.example/runtime") != saver_locator_digest(
        "postgresql://u@10.0.0.5/runtime"
    )


class BrokenQuerySaver:
    """A saver whose query is wrong (a programming error, not an unreachable server)."""

    def __init__(self, inner: InMemorySaver) -> None:
        self._inner = inner

    async def aget_tuple(self, config: Any) -> Any:
        raise psycopg.errors.UndefinedTable("relation checkpoints does not exist")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.mark.asyncio
async def test_a_programming_error_is_not_reported_as_an_unreachable_saver() -> None:
    """Tracing Stage 3 (R2-21)."""

    saver = InMemorySaver()
    _plan, _first, result_id, _parent = await _run(saver)
    broken = DeepAgentsTimeTravel({DIGEST: BrokenQuerySaver(saver)})  # type: ignore[dict-item]
    with pytest.raises(psycopg.errors.UndefinedTable):
        await broken.collect_points(
            namespace=THREAD,
            checkpointer_ref_digest=DIGEST,
            source_locator=None,
            result_locator=result_id,
        )

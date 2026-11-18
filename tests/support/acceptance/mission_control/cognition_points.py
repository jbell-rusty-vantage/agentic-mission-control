"""Builders, constants and fakes that other test files import.

Moved from tests/acceptance/mission_control/test_cognition_points.py.
"""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import pairwise
from typing import Any
from uuid import uuid4

from tests.fixtures.scoped_api_stack import ScopedStack, inspect, prepare_run

BASE = "/v1/applications/biotech/runs"


def locator(point: dict[str, Any]) -> str:
    """The point's locator (a checkpoint id on this lane); a property, not a serialized field."""

    return str(point["coordinate"]["point"]["key"]["checkpoint_id"])


def is_root(point: dict[str, Any]) -> bool:
    """A root checkpoint point (1.4.4: a sync subagent's nested checkpoints are points too)."""

    return point["coordinate"]["point"]["key"].get("checkpoint_ns", "") == ""


async def launch(stack: ScopedStack, family: str) -> str:
    run_id, body = await prepare_run(stack, family)
    launched = await stack.http.post(f"{BASE}/{run_id}/launch", json=body)
    assert launched.status_code == 202, launched.text
    return run_id


async def completed(stack: ScopedStack, run_id: str) -> bool:
    state = await inspect(stack, run_id)
    assert state["lifecycle"] not in {"failed", "cancelled"}, state
    return state["lifecycle"] == "completed"


async def at_wait(stack: ScopedStack, run_id: str) -> bool:
    state = await inspect(stack, run_id)
    assert state["lifecycle"] != "completed", state
    return bool(state["projection"]["active_waits"])


async def satisfy_wait(stack: ScopedStack, run_id: str) -> None:
    state = await inspect(stack, run_id)
    wait = state["projection"]["active_waits"][0]
    body = {
        "request_id": str(uuid4()),
        "expected_version": state["version"],
        "expected_generation": state["execution_generation"],
        "target": {"kind": "run", "id": run_id},
        "kind": "satisfy_wait",
        "payload": {
            "condition_id": wait["condition_id"],
            "verification_evidence_ref": "evidence:points-review",
            "runnable_work_remains": True,
        },
        "reason": "FX-DA-POINTS-SG release",
    }
    response = await stack.http.post(f"{BASE}/{run_id}/commands", json=body)
    assert response.status_code == 202, response.text


async def all_points(stack: ScopedStack, run_id: str, **params: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        query = {"limit": 50, **params, **({"cursor": cursor} if cursor else {})}
        response = await stack.http.get(f"{BASE}/{run_id}/points", params=query)
        assert response.status_code == 200, response.text
        page = response.json()
        entries.extend(page["entries"])
        cursor = page.get("next_cursor")
        if not cursor:
            return entries


async def saver_root_checkpoints(stack: ScopedStack) -> dict[str, list[dict[str, Any]]]:
    """Root checkpoints of every thread, oldest first, from the runtime schema (owner read)."""

    async with stack.owner_pool.acquire() as connection:
        rows = await connection.fetch(
            "SELECT thread_id, checkpoint_id, parent_checkpoint_id, metadata "
            "FROM mission_control_runtime.checkpoints WHERE checkpoint_ns = '' "
            "ORDER BY thread_id, checkpoint_id"
        )
    threads: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        metadata = row["metadata"]
        metadata = json.loads(metadata) if isinstance(metadata, str) else dict(metadata)
        threads[row["thread_id"]].append(
            {
                "checkpoint_id": row["checkpoint_id"],
                "parent": row["parent_checkpoint_id"],
                "step": metadata.get("step"),
                "unit_key": metadata.get("belllabs_unit_key"),
                "attempt_ref": metadata.get("belllabs_attempt_ref"),
            }
        )
    return threads


def assert_points_index_the_saver(
    points: list[dict[str, Any]], saver: dict[str, list[dict[str, Any]]], *, unit_key: str
) -> None:
    """Exactly one point per stamped root checkpoint of the unit, with attempt and facts."""

    mine = [
        item
        for item in points
        if item["coordinate"]["unit_key"] == unit_key
        # 1.4.4: a sync subagent's nested checkpoints are points too; the saver index
        # below compares root checkpoints only.
        and item["coordinate"]["point"]["key"].get("checkpoint_ns", "") == ""
    ]
    assert mine, f"no points for unit {unit_key}"
    thread = mine[0]["coordinate"]["point"]["key"]["thread_id"]
    stamped = [item for item in saver[thread] if item["unit_key"] == unit_key]
    assert {locator(item) for item in mine} == {item["checkpoint_id"] for item in stamped}
    assert len(mine) == len(stamped)
    by_locator = {locator(item): item for item in mine}
    for checkpoint in stamped:
        point = by_locator[checkpoint["checkpoint_id"]]
        assert point["ordinal"] == checkpoint["step"]
        assert point["attempt"] is not None
        assert point["attempt"]["activity_attempt"] >= 1
        assert point["attempt"]["temporal_activity_id"]
        assert point["attempt"]["task_queue"]
        # LangGraph's `input` checkpoint holds the state before the input is applied: a
        # fresh thread's first point has no messages yet; every later point has.
        assert point["message_count"] is not None
        if "input" not in point["roles"]:
            assert point["message_count"] >= 1
        assert point["coordinate"]["turn_no"] is not None
        assert point["turn_id"] is not None
        parent = checkpoint["parent"]
        if parent in by_locator:
            assert point["parent_point_id"] == by_locator[parent]["point_id"]
    roles = {role for item in mine for role in item["roles"]}
    assert {"input", "leaf", "result"} <= roles
    # Frame ranges: the steps that stream nothing (`__start__` and the Deep Agents middleware
    # nodes before the first model call) have none; the input point carries the session and
    # turn frames, the result point the finish frames, and the ranges of one unit never
    # overlap and advance with the steps.
    ranged = sorted(
        (item["ordinal"], item["frames"]["from_ordinal"], item["frames"]["to_ordinal"])
        for item in mine
        if item["frames"] is not None
    )
    assert len(ranged) * 2 >= len(mine), [item["ordinal"] for item in mine]
    assert next(item for item in mine if "input" in item["roles"])["frames"] is not None
    result = next(item for item in mine if "result" in item["roles"])
    assert result["frames"] is not None
    for (_a, _a_from, a_to), (_b, b_from, _b_to) in pairwise(ranged):
        assert b_from > a_to, ranged


async def snapshot(stack: ScopedStack, run_id: str) -> dict[str, Any]:
    state = await inspect(stack, run_id)
    response = await stack.http.post(
        f"{BASE}/{run_id}/snapshots", json={"expected_version": state["version"]}
    )
    assert response.status_code == 201, response.text
    return response.json()["snapshot"]

"""FX-DA-POINTS and FX-DA-POINTS-SG (P1 turn 4, WP-1): the cognition coordinate on the
production offline stack.

The signed scoped stack (`tests/fixtures/scoped_api_stack.py`): a fresh common database on
the disposable cluster (release 1.4.3), a local Temporal dev server, the production workers
with deterministic Deep Agents cognition (no provider call) and the configured API over real
loopback HTTP. A Goal Directed run (two iterations, executor and verifier on shared role
threads) and a Stage Graph run (draft, declared wait, review in fresh threads) are driven to
completion; then the operator API's `points` and `state-as-of` are compared with the saver:
every root checkpoint of iteration 2 (and of stage 2) has exactly one point row carrying its
Temporal activity attempt, frame range and message count, and `state-as-of` returns the
graph state at the result point (messages with the scripted tool calls, the written file).
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from tests.fixtures.scoped_api_stack import ScopedStack, inspect, prepare_run, scoped_stack, until

pytestmark = pytest.mark.common_db
BASE = "/v1/applications/biotech/runs"


def locator(point: dict[str, Any]) -> str:
    """The point's locator (a checkpoint id on this lane); a property, not a serialized field."""

    return str(point["coordinate"]["point"]["key"]["checkpoint_id"])


def is_root(point: dict[str, Any]) -> bool:
    """A root checkpoint point (1.4.4: a sync subagent's nested checkpoints are points too)."""

    return point["coordinate"]["point"]["key"].get("checkpoint_ns", "") == ""


def _write_evidence(path: Path, payload: dict[str, Any]) -> None:
    """The drill evidence file (git-ignored), written synchronously before the assertions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


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


@pytest.mark.asyncio
async def test_goal_directed_points_index_every_root_checkpoint_of_iteration_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await launch(stack, "GoalDirected")
        await until(lambda: completed(stack, run_id), seconds=600)
        points = await all_points(stack, run_id)
        assert points, "the run recorded no cognition points"
        saver = await saver_root_checkpoints(stack)
        # Both iterations, both roles: one row per stamped root checkpoint, all on the two
        # shared role threads; iteration 2 continues iteration 1's thread (same thread id).
        units = {
            (item["location"]["iteration"], item["location"]["node_key"]): item["coordinate"][
                "unit_key"
            ]
            for item in points
        }
        assert set(units) == {(1, "executor"), (1, "verifier"), (2, "executor"), (2, "verifier")}
        for unit_key in units.values():
            assert_points_index_the_saver(points, saver, unit_key=unit_key)
        executor_2 = [
            item
            for item in points
            if item["location"]["iteration"] == 2 and item["location"]["node_key"] == "executor"
        ]
        executor_1 = [
            item
            for item in points
            if item["location"]["iteration"] == 1 and item["location"]["node_key"] == "executor"
        ]
        assert (
            executor_2[0]["coordinate"]["point"]["key"]["thread_id"]
            == (executor_1[0]["coordinate"]["point"]["key"]["thread_id"])
        )
        # The lineage root of iteration 2 continues from iteration 1's result point.
        first = next(item for item in executor_2 if "input" in item["roles"] and is_root(item))
        result_1 = next(item for item in executor_1 if "result" in item["roles"])
        assert first["parent_point_id"] == result_1["point_id"]
        assert all(item["location"]["session_generation"] == 1 for item in points)
        # Filters: iteration, node and role narrow exactly.
        filtered = await all_points(stack, run_id, iteration=2, node="executor", role="result")
        assert (
            len(filtered) == 1 and filtered[0]["coordinate"]["unit_key"] == units[(2, "executor")]
        )
        # state-as-of at iteration 2's result: the graph state, redacted, from the saver.
        result_2 = filtered[0]
        response = await stack.http.get(
            f"{BASE}/{run_id}/points/{result_2['point_id']}/state-as-of"
        )
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["restore_level"] == "R3" and state["history"] == "native"
        messages = state["state"]["messages"]
        assert len(messages) == result_2["message_count"]
        assert len({item["id"] for item in messages}) == len(messages)
        assert messages[0]["role"] == "human" and messages[-1]["role"] == "ai"
        names = {call["name"] for item in messages for call in item["tool_calls"]}
        assert {"task", "write_file", "lookup_binding_marker"} <= names
        assert any(item["role"] == "tool" for item in messages)
        assert any(path["path"].startswith("/goal/") for path in state["state"]["files"])
        assert state["state"]["stamps"]["belllabs_unit_key"] == units[(2, "executor")]
        assert state["usage_to_point"].get("tokens.total_tokens", 0) > 0
        assert "secret_values_unknown_at_read: pattern redaction only" in state["state"]["withheld"]
        # One point row answers the Temporal coordinate too.
        assert result_2["attempt"]["temporal_workflow_id"].endswith(
            "/operation/"
            + str(result_2["attempt"]["temporal_workflow_id"].rsplit("/operation/", 1)[-1])
        )
        # The CLI-visible shapes: a single point by id.
        one = await stack.http.get(f"{BASE}/{run_id}/points/{result_2['point_id']}")
        assert one.status_code == 200 and one.json()["point_id"] == result_2["point_id"]
        missing = await stack.http.get(f"{BASE}/{run_id}/points/{uuid4()}")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_stage_graph_points_index_each_stage_in_its_own_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await launch(stack, "StageGraph")
        await until(lambda: at_wait(stack, run_id), seconds=600)
        await satisfy_wait(stack, run_id)
        await until(lambda: completed(stack, run_id), seconds=600)
        points = await all_points(stack, run_id)
        saver = await saver_root_checkpoints(stack)
        stages = {item["location"]["node_key"] for item in points}
        assert len(stages) == 2, stages
        assert all(item["location"]["family"] == "stage_graph" for item in points)
        assert all(item["location"]["cycle"] == 0 for item in points)
        assert all(item["location"]["session_generation"] is None for item in points)
        threads = {
            item["location"]["node_key"]: item["coordinate"]["point"]["key"]["thread_id"]
            for item in points
        }
        assert len(set(threads.values())) == 2, "each stage unit runs in its own thread"
        for unit_key in {item["coordinate"]["unit_key"] for item in points}:
            assert_points_index_the_saver(points, saver, unit_key=unit_key)
        # A fresh stage thread has no parent point for its input checkpoint.
        for stage in stages:
            first = next(
                item
                for item in points
                if item["location"]["node_key"] == stage
                and "input" in item["roles"]
                and is_root(item)
            )
            assert first["parent_point_id"] is None and first["parent_locator"] is None
        # The second stage's result state names the first stage's accepted output as input.
        last_stage = max(
            stages,
            key=lambda stage: min(
                item["recorded_at"] for item in points if item["location"]["node_key"] == stage
            ),
        )
        result = next(
            item
            for item in points
            if item["location"]["node_key"] == last_stage and "result" in item["roles"]
        )
        response = await stack.http.get(f"{BASE}/{run_id}/points/{result['point_id']}/state-as-of")
        assert response.status_code == 200, response.text
        files = [item["path"] for item in response.json()["state"]["files"]]
        # The sealed stage packet (`.mission/context.md`, `.mission/inputs.json`, where the
        # technical fixture's upstream output arrives as a reference) and the stage's own
        # written output are the graph state's files at its result point.
        assert "/.mission/inputs.json" in files and "/.mission/context.md" in files, files
        assert any(path.startswith("/workspace/output/") for path in files), files


async def snapshot(stack: ScopedStack, run_id: str) -> dict[str, Any]:
    state = await inspect(stack, run_id)
    response = await stack.http.post(
        f"{BASE}/{run_id}/snapshots", json={"expected_version": state["version"]}
    )
    assert response.status_code == 201, response.text
    return response.json()["snapshot"]


@pytest.mark.asyncio
async def test_stage_graph_fork_from_a_point_continues_the_copied_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FX-DA-FORK (WP-2): fork at (stage 2, step K) with an instruction; the derived stage's
    first attempt pins to the copied point and its first model call sees the instruction."""

    from dataclasses import asdict

    from tests.fixtures import rrm009_production_stack as technical

    from mission_control.application.execution.run_launch import fork_semantic_input_binding_ref

    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await launch(stack, "StageGraph")
        await until(lambda: at_wait(stack, run_id), seconds=600)
        await satisfy_wait(stack, run_id)
        await until(lambda: completed(stack, run_id), seconds=600)
        points = await all_points(stack, run_id)
        stages = sorted({item["location"]["node_key"] for item in points})
        second = max(
            stages,
            key=lambda stage: min(
                item["recorded_at"] for item in points if item["location"]["node_key"] == stage
            ),
        )
        stage_points = sorted(
            (item for item in points if item["location"]["node_key"] == second),
            key=lambda item: item["ordinal"],
        )
        # The point after the child's `task` call and before the file write: step K.
        seed = next(item for item in stage_points if item["ordinal"] == 4)
        assert seed["seedable"]
        manifest = await snapshot(stack, run_id)
        assert manifest["boundary_kind"] == "stage_settled"
        instruction = "Fork instruction: continue from the copied point and cite the prior draft."
        fork = await stack.http.post(
            f"{BASE}/{run_id}/forks",
            json={
                "request_id": str(uuid4()),
                "snapshot_id": manifest["snapshot_id"],
                "snapshot_digest": manifest["snapshot_digest"],
                "invalidation_frontier": [second],
                "cognitive_seed": {
                    "unit_key": seed["coordinate"]["unit_key"],
                    "checkpoint": seed["coordinate"]["point"]["key"],
                },
                "instruction": {"text": instruction},
                "baseline_reservations": {"tokens.total": 20},
                "sponsorship_ref": "sponsorship:test",
                "approval_refs": ["approval:test"],
                "reason": "FX-DA-FORK: fork from a cognition point",
            },
        )
        assert fork.status_code == 202, fork.text
        receipt = fork.json()["receipt"]
        derived_run = receipt["target_run_id"]
        # 1.4.4 (P5): the fork records its position, the closed frontier and the delivery.
        assert (receipt["at"]["stage"], receipt["at"]["cycle"]) == (
            second,
            seed["location"]["cycle"],
        ), receipt["at"]
        assert receipt["frontier_requested"] == [second]
        assert second in receipt["frontier_closed"]
        assert receipt["message_delivery"] == "seed_head"
        assert receipt["seed_point"] == seed["coordinate"]["point"]["key"]["checkpoint_id"]
        assert receipt["start_position"]["stage_cycle_ordinals"] == {
            second: seed["location"]["cycle"]
        }
        assert fork.json()["seed"]["instruction_command_id"] is None
        # The derived run already holds the seeded point before it is launched: the head
        # after the copied point whose `messages` write is the injected instruction.
        seeded = await all_points(stack, derived_run, role="fork_seed")
        assert len(seeded) == 1, seeded
        assert seeded[0]["parent_coordinate"]["point"]["key"] == seed["coordinate"]["point"]["key"]
        assert seeded[0]["restore_level"] == "R3" and seeded[0]["history"] == "native"
        assert (
            seeded[0]["coordinate"]["point"]["key"]["thread_id"]
            != (seed["coordinate"]["point"]["key"]["thread_id"])
        )
        assert (
            seeded[0]["coordinate"]["point"]["key"]["parent_checkpoint_id"]
            == (seed["coordinate"]["point"]["key"]["checkpoint_id"])
        )
        assert seeded[0]["message_count"] == seed["message_count"] + 1
        # A fork without an admitted seed on this lane is still refused as before.
        catalog = stack.catalogs["StageGraph"]
        launched = await stack.http.post(
            f"{BASE}/{derived_run}/launch",
            json={
                "family": "StageGraph",
                "stagegraph": asdict(
                    technical.stage_input(
                        catalog,
                        derived_run,
                        fork_semantic_input_binding_ref(receipt["request_id"]),
                        1,
                    )
                ),
                "source_semantic_input_binding_ref": f"semantic-input:scoped-proof:{run_id}",
            },
        )
        assert launched.status_code == 202, launched.text
        # The re-run stage declares its wait again on the derived run; release it as before.
        await until(lambda: at_wait(stack, derived_run), seconds=600)
        await satisfy_wait(stack, derived_run)
        await until(lambda: completed(stack, derived_run), seconds=600)
        derived_points = await all_points(stack, derived_run, node=second)
        first = next(item for item in derived_points if "input" in item["roles"] and is_root(item))
        # The derived stage's lineage root descends from the seeded head (new thread).
        assert first["parent_point_id"] == seeded[0]["point_id"]
        assert (
            first["coordinate"]["point"]["key"]["parent_checkpoint_id"]
            == (seeded[0]["coordinate"]["point"]["key"]["checkpoint_id"])
        )
        assert (
            first["coordinate"]["point"]["key"]["thread_id"]
            == (seeded[0]["coordinate"]["point"]["key"]["thread_id"])
        )
        # Its state at the input point is the copied conversation up to step K (messages by
        # identity), and the derived stage's first model call saw the fork instruction.
        response = await stack.http.get(
            f"{BASE}/{derived_run}/points/{first['point_id']}/state-as-of"
        )
        assert response.status_code == 200, response.text
        copied = response.json()["state"]["messages"]
        assert len(copied) >= seed["message_count"] + 1
        assert [item["role"] for item in copied][:2] == ["human", "ai"]
        # 1.4.4 (P5.3): the injected instruction is the seeded head's last human message.
        humans = [item for item in copied if item["role"] == "human"]
        assert humans and instruction in (humans[-1]["text"] or ""), humans[-1]
        # The derived stage's result state holds the copied conversation plus its own work,
        # and the fork instruction reached its cognition through the first packet.
        result = next(item for item in derived_points if "result" in item["roles"])
        response = await stack.http.get(
            f"{BASE}/{derived_run}/points/{result['point_id']}/state-as-of"
        )
        assert response.status_code == 200, response.text
        messages = response.json()["state"]["messages"]
        assert len(messages) > len(copied)
        assert any(instruction in (item["text"] or "") for item in messages), [
            (item["role"], (item["text"] or "")[:80]) for item in messages
        ]
        # The source run is untouched: its points and thread are as before the fork.
        assert await all_points(stack, run_id) == points


@pytest.mark.asyncio
async def test_interrupt_and_inject_into_running_cognition_marks_the_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FX-DA-INJECT (intervention): an `interrupt_and_inject` lands inside the executor's
    running turn on the production stack; the lane cancels and replaces the turn on the same
    thread, the points record the interrupted leaf and the replacement's first checkpoint,
    and the injected text is in the executor's state."""

    import os

    monkeypatch.setenv("MISSION_CONTROL_TECHNICAL_MODEL_DELAY_SECONDS", "2.5")
    assert os.environ["MISSION_CONTROL_TECHNICAL_MODEL_DELAY_SECONDS"] == "2.5"
    injected = "Injected mid-turn: switch to the second evidence source before writing."
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await launch(stack, "GoalDirected")

        async def executor_running() -> bool:
            state = await inspect(stack, run_id)
            return state["lifecycle"] == "running" and state.get("phase") == "active"

        await until(executor_running, seconds=300)
        # Land inside the turn, not at its start: with the model delay, 6 s is the second or
        # third of the executor's four model calls, after its first checkpoints exist.
        await asyncio.sleep(6.0)
        body: dict[str, Any] = {}
        for _attempt in range(12):
            # The run keeps moving while the executor works: a stale expected version is
            # re-read, as any operator client does.
            state = await inspect(stack, run_id)
            body = {
                "request_id": str(uuid4()),
                "expected_version": state["version"],
                "expected_generation": state["execution_generation"],
                "target": {"kind": "run", "id": run_id},
                "kind": "interrupt_and_inject",
                "payload": {"content": {"text": injected}, "node_key": "goal/executor"},
                "reason": "FX-DA-INJECT",
            }
            response = await stack.http.post(f"{BASE}/{run_id}/commands", json=body)
            if response.status_code == 202:
                break
            assert response.status_code == 409, response.text
        assert response.status_code == 202, response.text
        await until(lambda: completed(stack, run_id), seconds=600)
        commands = (await stack.http.get(f"{BASE}/{run_id}/commands")).json()["commands"]
        entry = next(
            item for item in commands if item["command"]["command_id"] == body["request_id"]
        )
        states = [receipt["state"] for receipt in entry["receipts"]]
        assert states[-1] == "applied", states
        points = await all_points(stack, run_id, node="executor")
        evidence = {
            "receipts": entry["receipts"],
            "points": [
                (
                    item["location"]["iteration"],
                    item["ordinal"],
                    item["roles"],
                    item["message_count"],
                )
                for item in points
            ],
        }
        evidence_path = Path(".scratch/pc-p1-deep-agents/turn4/inject-evidence.json")
        _write_evidence(evidence_path, evidence)
        assert "cancel_and_replace" in json.dumps(evidence, default=str), evidence_path
        roles = {role for item in points for role in item["roles"]}
        assert {"interrupted", "replacement_start"} <= roles, evidence_path
        interrupted = next(item for item in points if "interrupted" in item["roles"])
        replacement = next(item for item in points if "replacement_start" in item["roles"])
        # The replacement continues the interrupted leaf on the same thread.
        assert replacement["parent_point_id"] == interrupted["point_id"]
        assert (
            replacement["coordinate"]["point"]["key"]["thread_id"]
            == (interrupted["coordinate"]["point"]["key"]["thread_id"])
        )
        result = next(
            item
            for item in points
            if "result" in item["roles"]
            and item["coordinate"]["unit_key"] == interrupted["coordinate"]["unit_key"]
        )
        response = await stack.http.get(f"{BASE}/{run_id}/points/{result['point_id']}/state-as-of")
        assert response.status_code == 200, response.text
        messages = response.json()["state"]["messages"]
        assert any(injected in (item["text"] or "") for item in messages if item["role"] == "human")

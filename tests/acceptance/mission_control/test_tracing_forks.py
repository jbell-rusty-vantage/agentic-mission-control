"""FX-TR-FORK-GD (TRACING-PROPOSAL §P5.4, §P5.7; WP-TR-4): the precise Goal Directed fork
on the production offline stack.

The signed scoped stack (`tests/fixtures/scoped_api_stack.py`): a fresh common database on
the disposable cluster, a local Temporal dev server, the production workers with
deterministic Deep Agents cognition (no provider call) and the configured API over loopback
HTTP. A Goal Directed run (`rrm009_production_stack.goal_blueprint`, `max_iterations=2`:
executor then verifier at iterations 1 and 2, on shared role threads) is driven to
completion; a fork is taken at `{iteration: 2, session_generation}` from a root point P of
the iteration-2 executor with an injected message; the derived run is launched with the
receipt's `derived_goal_revision_id`, the source's envelope digest and the receipt's
`start_position` (option B: iterations below the position settle by reference, the executor
of the position runs first on the seeded thread, pinned to the recorded counters).

Claims (one `failures` entry each; the evidence file under `.scratch/tracing-stage-1/`):

- the receipt names `start_position.goal_iteration == 2`, a non-empty
  `derived_goal_revision_id`, `message_delivery == "seed_head"`, exactly the iteration-1
  executor and verifier as `reused_units` (by `source_unit_key`, each with its
  `source_result_point`), and an invalidated set that is exactly the derived iteration-2 units;
- the derived run's iteration-1 units settle by reference: their points carry the `reused`
  role with `parent_coordinate` equal to the source unit's result point;
- the derived iteration-2 executor's first root input point descends from the derived
  `fork_seed` point, and `state-as-of` there is the copied conversation whose last human
  message is the injected marker; the iteration-2 verifier runs fresh;
- the source run's points are unchanged.

The lead runs this proof once the fork core (`SemanticForkService` with `at`, the seeded
head and the `reused` points) lands; it is not part of the unit suite.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from tests.acceptance.mission_control.test_cognition_points import (
    BASE,
    all_points,
    completed,
    is_root,
    launch,
    snapshot,
)
from tests.fixtures import rrm009_production_stack as technical
from tests.fixtures.scoped_api_stack import ScopedStack, scoped_stack, until

from mission_control.adapters.postgres.orchestration.goal_directed_repository import (
    PostgresGoalDirectedDocumentRepository,
)
from mission_control.application.execution.run_launch import fork_semantic_input_binding_ref
from mission_control.domain.programs.contracts import GoalDirectedStartPosition

pytestmark = pytest.mark.common_db

EVIDENCE_ROOT = Path(".scratch/tracing-stage-1")
# Under the 900 s pytest-timeout safety net; a run takes 60-200 s on the host.
RUN_SECONDS = 600
# The objective `scoped_api_stack.prepare_run` admits for a Goal Directed run; the derived
# run carries the same objective (the fork patches nothing).
OBJECTIVE = "Produce one independently verified technical record."
FORK_ITERATION = 2
MARKER = "FX-TR-FORK-GD marker: stop after one more revision and cite the prior record."


def _write_evidence(name: str, payload: dict[str, Any]) -> Path:
    path = EVIDENCE_ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def _units(points: list[dict[str, Any]]) -> dict[tuple[int, str], str]:
    """`(iteration, role) -> unit key` over the run's points."""

    return {
        (int(item["location"]["iteration"]), str(item["location"]["node_key"])): str(
            item["coordinate"]["unit_key"]
        )
        for item in points
    }


def _result_point(points: list[dict[str, Any]], unit_key: str) -> dict[str, Any]:
    return next(
        item
        for item in points
        if item["coordinate"]["unit_key"] == unit_key and "result" in item["roles"]
    )


def _point_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "point_id": item["point_id"],
        "unit_key": item["coordinate"]["unit_key"],
        "location": item["location"],
        "ordinal": item["ordinal"],
        "roles": item["roles"],
        "source": item.get("source"),
        "written_by": item.get("written_by"),
        "parent_point_id": item.get("parent_point_id"),
        "message_count": item.get("message_count"),
        "seedable": item.get("seedable"),
    }


async def persist_derived_goal_templates(
    stack: ScopedStack, catalog: technical.TechnicalCatalog, binding_ref: str
) -> None:
    """The derived run's executor and verifier documents under the fork's binding ref.

    `RunLaunchService._apply_fork` derives Stage Graph templates only; a Goal Directed launch
    reads its role documents by `semantic_input_binding_ref`, so the proof persists the
    technical templates for the derived binding the way `prepare_run` does for the source.
    """

    templates = {
        name: value.model_copy(update={"request_scope": stack.scope})
        for name, value in technical.goal_templates(stack.binding, catalog).items()
    }
    await PostgresGoalDirectedDocumentRepository(stack.pool).persist_templates(
        request_scope=stack.scope,
        semantic_input_binding_ref=binding_ref,
        executor=templates["executor"],
        verifier=templates["verifier"],
        recorded_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_goal_directed_fork_at_an_iteration_reuses_earlier_iterations_and_pins_the_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FX-TR-FORK-GD: fork at (iteration 2, session 1, point P) with an injected message."""

    failures: list[str] = []
    evidence: dict[str, Any] = {"proof": "FX-TR-FORK-GD", "marker": MARKER}
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        # --- The source run: two iterations, executor then verifier, on shared role threads.
        run_id = await launch(stack, "GoalDirected")
        await until(lambda: completed(stack, run_id), seconds=RUN_SECONDS)
        points = await all_points(stack, run_id)
        assert points, "the source run recorded no cognition points"
        units = _units(points)
        assert set(units) == {(1, "executor"), (1, "verifier"), (2, "executor"), (2, "verifier")}
        source_results = {key: _result_point(points, unit_key) for key, unit_key in units.items()}
        evidence["source_run"] = run_id
        evidence["source_units"] = {f"{it}/{role}": key for (it, role), key in units.items()}

        # --- P: a root, seedable point of the iteration-2 executor (its input point, or the
        # earliest seedable step when the input point cannot be seeded on this lane).
        executor_2 = sorted(
            (
                item
                for item in points
                if item["location"]["iteration"] == FORK_ITERATION
                and item["location"]["node_key"] == "executor"
                and is_root(item)
                and item["seedable"]
            ),
            key=lambda item: item["ordinal"],
        )
        assert executor_2, "the iteration-2 executor has no seedable root point"
        seed = next((item for item in executor_2 if "input" in item["roles"]), executor_2[0])
        seed_key = seed["coordinate"]["point"]["key"]
        evidence["seed_point"] = _point_summary(seed)

        # --- The fork: at the executor's iteration and session, seeded at P, with the message.
        manifest = await snapshot(stack, run_id)
        fork = await stack.http.post(
            f"{BASE}/{run_id}/forks",
            json={
                "request_id": str(uuid4()),
                "snapshot_id": manifest["snapshot_id"],
                "snapshot_digest": manifest["snapshot_digest"],
                "at": {
                    "iteration": FORK_ITERATION,
                    "session_generation": seed["location"]["session_generation"],
                },
                "cognitive_seed": {
                    "unit_key": seed["coordinate"]["unit_key"],
                    "checkpoint": seed_key,
                },
                "message": {"text": MARKER},
                "baseline_reservations": technical.baseline_reservation("GoalDirected"),
                "sponsorship_ref": "sponsorship:test",
                "approval_refs": ["approval:test"],
                "reason": "FX-TR-FORK-GD: fork a Goal Directed run at an iteration",
            },
        )
        assert fork.status_code == 202, fork.text
        receipt = fork.json()["receipt"]
        derived_run = receipt["target_run_id"]
        evidence["receipt"] = receipt

        # --- The receipt: position, derived revision, delivery, reuse and invalidation.
        start_position = receipt.get("start_position") or {}
        if start_position.get("goal_iteration") != FORK_ITERATION:
            failures.append(f"receipt start_position {start_position} is not iteration 2")
        derived_revision_id = receipt.get("derived_goal_revision_id")
        if not isinstance(derived_revision_id, str) or not derived_revision_id:
            failures.append(f"receipt derived_goal_revision_id {derived_revision_id!r} is not set")
        if receipt.get("message_delivery") != "seed_head":
            failures.append(f"receipt message_delivery {receipt.get('message_delivery')!r}")
        reused_units = receipt.get("reused_units") or []
        reused_sources = {item["source_unit_key"] for item in reused_units}
        expected_reused = {units[(1, "executor")], units[(1, "verifier")]}
        if reused_sources != expected_reused:
            failures.append(
                f"reused_units name {sorted(reused_sources)}, expected the iteration-1 "
                f"executor and verifier {sorted(expected_reused)}"
            )
        for item in reused_units:
            if not item.get("source_result_point"):
                failures.append(f"reused unit {item.get('unit_key')} has no source_result_point")
        reused_derived = {item["unit_key"] for item in reused_units}
        invalidated = set(receipt["lineage"]["invalidated_unit_keys"])
        if len(invalidated) != 2 or invalidated & reused_derived:
            failures.append(
                f"invalidated set {sorted(invalidated)} is not two units disjoint from the "
                f"reused ones {sorted(reused_derived)}"
            )

        # --- The derived run already holds the seeded point before it is launched.
        seeded = await all_points(stack, derived_run, role="fork_seed")
        assert len(seeded) == 1, seeded
        if seeded[0]["parent_coordinate"]["point"]["key"] != seed_key:
            failures.append("the fork_seed point does not descend from P")
        if seeded[0]["coordinate"]["point"]["key"]["thread_id"] == seed_key["thread_id"]:
            failures.append("the fork_seed point lies on the source thread")
        evidence["fork_seed_point"] = _point_summary(seeded[0])

        # --- Launch the derived run: the fork's binding, the derived revision id, the
        # source's envelope digest and the receipt's start position (P5.4, option B).
        catalog = stack.catalogs["GoalDirected"]
        derived_binding = fork_semantic_input_binding_ref(receipt["request_id"])
        await persist_derived_goal_templates(stack, catalog, derived_binding)
        source_envelope = technical.goal_revision(run_id, OBJECTIVE).envelope_digest
        position = GoalDirectedStartPosition(
            goal_iteration=int(start_position.get("goal_iteration") or FORK_ITERATION),
            session_generation=int(start_position.get("session_generation") or 1),
            agent_run=int(start_position.get("agent_run") or 1),
        )
        evidence["derived_start_position"] = asdict(position)
        launched = await stack.http.post(
            f"{BASE}/{derived_run}/launch",
            json={
                "family": "GoalDirected",
                "goal_directed": asdict(
                    technical.goal_input(
                        catalog,
                        derived_run,
                        derived_binding,
                        1,
                        OBJECTIVE,
                        revision_id=derived_revision_id or None,
                        envelope_digest=source_envelope,
                        start_position=position,
                    )
                ),
            },
        )
        assert launched.status_code == 202, launched.text
        await until(lambda: completed(stack, derived_run), seconds=RUN_SECONDS)
        derived_points = await all_points(stack, derived_run)
        evidence["derived_run"] = derived_run
        evidence["derived_points"] = [_point_summary(item) for item in derived_points]
        derived_units = _units(derived_points)

        # --- Iterations below the position settle by reference: one `reused` point per
        # unit whose parent coordinate is the source unit's result point.
        for role in ("executor", "verifier"):
            source_result = source_results[(1, role)]
            mine = [
                item
                for item in derived_points
                if item["location"]["iteration"] == 1 and item["location"]["node_key"] == role
            ]
            reused = [item for item in mine if "reused" in item["roles"]]
            if len(reused) != 1 or len(mine) != 1:
                failures.append(
                    f"derived iteration-1 {role} has {len(mine)} points, "
                    f"{len(reused)} reused: {[item['roles'] for item in mine]}"
                )
                continue
            if reused[0]["parent_coordinate"] != source_result["coordinate"]:
                failures.append(
                    f"derived iteration-1 {role} reused point parent_coordinate "
                    f"{reused[0]['parent_coordinate']} is not the source result point "
                    f"{source_result['coordinate']}"
                )
            if reused[0].get("source") != "fork":
                failures.append(f"derived iteration-1 {role} reused point source is not `fork`")

        # --- The invalidated set is exactly the derived iteration-2 units.
        derived_iteration_2 = {
            key for (iteration, _role), key in derived_units.items() if iteration == 2
        }
        if invalidated != derived_iteration_2:
            failures.append(
                f"invalidated {sorted(invalidated)} is not the derived iteration-2 units "
                f"{sorted(derived_iteration_2)}"
            )

        # --- The derived iteration-2 executor continues the seeded thread from the seed.
        derived_executor_2 = [
            item
            for item in derived_points
            if item["location"]["iteration"] == FORK_ITERATION
            and item["location"]["node_key"] == "executor"
            and "reused" not in item["roles"]
        ]
        first = next(
            (item for item in derived_executor_2 if "input" in item["roles"] and is_root(item)),
            None,
        )
        if first is None:
            failures.append("the derived iteration-2 executor has no root input point")
        else:
            if first["parent_point_id"] != seeded[0]["point_id"]:
                failures.append(
                    f"derived executor input point parent {first['parent_point_id']} is not "
                    f"the fork_seed point {seeded[0]['point_id']}"
                )
            if (
                first["coordinate"]["point"]["key"]["thread_id"]
                != seeded[0]["coordinate"]["point"]["key"]["thread_id"]
            ):
                failures.append("the derived executor does not run on the seeded thread")
            if first["location"]["session_generation"] != position.session_generation:
                failures.append(
                    f"derived executor session generation {first['location']} is not the "
                    f"pinned {position.session_generation}"
                )
            response = await stack.http.get(
                f"{BASE}/{derived_run}/points/{first['point_id']}/state-as-of"
            )
            if response.status_code != 200:
                failures.append(f"state-as-of at the derived input point: {response.text}")
            else:
                state = response.json()
                messages = state["state"]["messages"]
                humans = [item for item in messages if item["role"] == "human"]
                evidence["derived_input_state"] = {
                    "restore_level": state.get("restore_level"),
                    "history": state.get("history"),
                    "messages": [(item["role"], (item["text"] or "")[:80]) for item in messages],
                }
                if len(messages) < int(seed["message_count"] or 0):
                    failures.append(
                        f"the copied conversation has {len(messages)} messages, fewer than "
                        f"P's {seed['message_count']}"
                    )
                if not humans or MARKER not in (humans[-1]["text"] or ""):
                    failures.append(
                        "the last human message of the copied conversation is not the marker: "
                        f"{(humans[-1]['text'] if humans else None)!r}"
                    )
        # The iteration-2 verifier runs fresh after the seeded executor.
        verifier_2 = [
            item
            for item in derived_points
            if item["location"]["iteration"] == FORK_ITERATION
            and item["location"]["node_key"] == "verifier"
        ]
        if not any("result" in item["roles"] for item in verifier_2) or any(
            "reused" in item["roles"] for item in verifier_2
        ):
            failures.append(
                f"the derived iteration-2 verifier did not run fresh: "
                f"{[item['roles'] for item in verifier_2]}"
            )

        # --- The source run is untouched.
        if await all_points(stack, run_id) != points:
            failures.append("the source run's points changed after the fork")

        evidence["failures"] = failures
        print(
            f"FX-TR-FORK-GD: evidence at {_write_evidence('fx-tr-fork-gd.json', evidence)}",
            flush=True,
        )
        assert not failures, "\n".join(failures)

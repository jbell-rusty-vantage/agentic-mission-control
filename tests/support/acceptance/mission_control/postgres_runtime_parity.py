"""Builders, constants and fakes that other test files import.

Moved from tests/acceptance/mission_control/test_postgres_runtime_parity.py.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from mission_control.adapters.postgres.orchestration.goal_directed_repository import (
    PostgresGoalDirectedDocumentRepository,
)
from mission_control.domain.policies.contracts import RunOutcome
from tests.fixtures.rrm009_production_harness import (
    ProductionStack,
    _admit,
    _calls,
    _launch,
    _replay,
    _run,
    _terminal,
    _visible,
    _wait_for,
    canonical_evidence,
    record_parity_trace,
)
from tests.fixtures.rrm009_production_stack import (
    SCOPE,
    goal_input,
    goal_templates,
    publish_technical_catalog,
)


async def goal_directed_two_iterations_scenario(stack: ProductionStack) -> None:
    """RRM-009 GoalDirected: two iterations through the production composition."""

    catalog = await publish_technical_catalog(
        stack.control_plane, family="GoalDirected", now=datetime.now(UTC)
    )
    run_id = await _admit(stack, catalog, "rrm009-goal-source")
    binding_ref = f"semantic-input:rrm009:{run_id}"
    templates = goal_templates(stack.technical, catalog)
    await PostgresGoalDirectedDocumentRepository(stack.worker_pool).persist_templates(
        request_scope=SCOPE,
        semantic_input_binding_ref=binding_ref,
        executor=templates["executor"],
        verifier=templates["verifier"],
        recorded_at=datetime.now(UTC),
    )
    objective = "Produce one independently verified technical record."
    receipt = await _launch(
        stack,
        run_id,
        {
            "request_scope": SCOPE,
            "run_id": run_id,
            "family": "GoalDirected",
            "goal_directed": asdict(goal_input(catalog, run_id, binding_ref, 1, objective)),
        },
    )
    assert receipt["workflow_id"] == f"belllabs-run/{run_id}"
    await _wait_for(stack, run_id, lambda: _terminal(stack, run_id), 300)
    run = await _run(stack, run_id)
    assert (run["phase"], run["terminal_outcome"]) == ("terminal", RunOutcome.COMPLETED.value)
    # RRM-019: only the final executor's verified outputs are promoted.
    assert [item["output_ref"] for item in run["accepted_output_evidence"]] == [
        "artifact:rrm009-goal:2"
    ]
    assert len(run["accepted_operation_settlement_evidence"]) == 4
    calls = _calls(stack, run_id)
    assert len(calls) == 4 and all(value == {"parent": 4, "child": 1} for value in calls.values())
    assert await _visible(stack.client, f"BellLabsRunId = '{run_id}'", 6) == 6
    budget = await stack.http.get(
        f"/run-control/v1/runs/{run_id}/budget", params={"request_scope": SCOPE}
    )
    assert budget.status_code == 200
    replayed = await _replay(stack.client, [f"belllabs-run/{run_id}", f"family/{run_id}/1"])
    rows = await canonical_evidence(stack, run_id)
    assert rows["terminal_outcome"] == "succeeded", rows
    assert rows["counts"]["settled_claims"] == 4, rows
    assert rows["counts"]["operation_receipt"] >= 4, rows
    record_parity_trace("goal_directed_two_iterations", rows)
    print(
        "RRM-009 EVIDENCE goal_directed:",
        json.dumps(
            {
                "run": run_id,
                "accepted_outputs": [
                    item["output_ref"] for item in run["accepted_output_evidence"]
                ],
                "settlements": len(run["accepted_operation_settlement_evidence"]),
                "model_calls": calls,
                "consumed": budget.json()["consumed"],
                "replayed_events": replayed,
            },
            sort_keys=True,
        ),
    )

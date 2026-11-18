"""Scenarios and read-backs of the PostgreSQL runtime parity acceptance.

`goal_directed_two_iterations_scenario` is the RRM-009 GoalDirected scenario (run with and
without the `lane.turn` segment loop); `run_authority_digest` is a content digest of one
run's authority rows and saver checkpoints.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

import asyncpg

from mission_control.adapters.postgres.orchestration.goal_directed_repository import (
    PostgresGoalDirectedDocumentRepository,
)
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.policies.contracts import RunOutcome
from tests.fixtures.rrm009_production_stack import (
    goal_input,
    goal_templates,
    publish_technical_catalog,
)
from tests.support.ids import SCOPE
from tests.support.stack import (
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


# --- Authority digest ---------------------------------------------------------------------------
_RUN = (
    "SELECT r.run_id FROM mission_control.mission_run r"
    " WHERE (r.installation_id, r.application_id, r.tenant_id) = ($2, $3, $4)"
    " AND r.run_key = $1"
)
_UNITS = (
    "SELECT a.activation_key FROM mission_control.activation a"
    " WHERE (a.installation_id, a.application_id, a.tenant_id) = ($2, $3, $4)"
    f" AND a.run_id = ({_RUN})"
)
_SCOPED = "(installation_id, application_id, tenant_id) = ($2, $3, $4)"
_NAMESPACES = (
    "SELECT g.cognitive_namespace FROM mission_control.runtime_unit_generation g"
    f" WHERE (g.installation_id, g.application_id, g.tenant_id) = ($2, $3, $4)"
    f" AND g.unit_key IN ({_UNITS})"
)


async def run_authority_digest(
    pool: asyncpg.Pool,
    run_id: str,
    *,
    saver_schema: str = "mission_control_runtime",
    request_scope: str,
) -> dict[str, str]:
    """A content digest of every authority row of one run (owner reads bypass RLS).

    Its canonical run, budget and effect ledgers, family heads, runtime units (activations)
    with their results and checkpoint transitions, operation claims, cognitive namespaces and
    LangGraph checkpoints, all read from the common ``mission_control`` component. Equal
    digests prove the run's authority did not change between two reads.
    """

    queries = {
        "mission_run": (
            f"SELECT * FROM mission_control.mission_run WHERE {_SCOPED} AND run_key = $1"
        ),
        "budget_account": (
            f"SELECT * FROM mission_control.budget_account WHERE {_SCOPED} AND run_id = ({_RUN})"
        ),
        "effect_ledger": (
            f"SELECT * FROM mission_control.effect_ledger WHERE {_SCOPED} AND run_key = $1"
        ),
        "family_admission_head": (
            f"SELECT * FROM mission_control.family_admission_head WHERE {_SCOPED} AND run_key = $1"
        ),
        "activation": (
            f"SELECT * FROM mission_control.activation WHERE {_SCOPED} AND run_id = ({_RUN})"
        ),
        "unit_result_observation": (
            f"SELECT * FROM mission_control.unit_result_observation"
            f" WHERE {_SCOPED} AND unit_key IN ({_UNITS})"
        ),
        "checkpoint_transition": (
            f"SELECT * FROM mission_control.checkpoint_transition"
            f" WHERE {_SCOPED} AND unit_key IN ({_UNITS})"
        ),
        "operation_claim": (
            f"SELECT * FROM mission_control.operation_claim WHERE {_SCOPED} AND run_key = $1"
        ),
        "cognitive_namespace": (
            f"SELECT * FROM mission_control.cognitive_namespace"
            f" WHERE {_SCOPED} AND namespace_key IN ({_NAMESPACES})"
        ),
        "saver_checkpoints": (
            f"SELECT c.thread_id, c.checkpoint_id, c.metadata FROM {saver_schema}.checkpoints c"
            f" WHERE c.thread_id IN ({_NAMESPACES})"
        ),
    }
    scope = parse_request_scope(request_scope)
    async with pool.acquire() as connection:
        return {
            name: await connection.fetchval(
                f"SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), ''))"
                f" FROM ({query}) t",
                run_id,
                scope.installation_id,
                scope.application_id,
                scope.tenant_id,
            )
            for name, query in queries.items()
        }

"""Assert persisted exact transfer/fulfillment evidence for the live seven-stage graph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.fixtures.qualia_full_manifest import stage_tool_names

from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
from mission_control.adapters.postgres.knowledge.output_contracts import PostgresOutputContractStore
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.domain.context.transfer import SealedTransferPlan
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    OperationExecutionBinding,
)


async def verify_capabilities(
    stack: Any,
    scope: str,
    run_id: str,
    root: Path,
    *,
    vendor: str,
    interventions: bool,
    expected: dict[str, set[str]] | None = None,
    skill_prefix: str = "qualia",
) -> None:
    """Compare actual persisted operation bindings against the per-stage selection."""
    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        rows = await connection.fetch(
            "SELECT payload FROM mission_control.runtime_document WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
            "AND contract='operation.binding/1' AND payload->>'run_id'=$4",
            *args,
            run_id,
        )
    if expected is None:
        expected = stage_tool_names(vendor, interventions=interventions)
    observed = []
    for row in rows:
        binding = OperationExecutionBinding.model_validate(mc.load(row["payload"]))
        unit = binding.runtime_unit
        stage = getattr(unit.location, "stage_id", None) if unit is not None else None
        if stage not in expected:
            continue
        deep = DeepAgentExecutionBinding.carried_by(binding)
        assert deep is not None, (stage, "not a Deep Agents binding")
        tool_names = {tool.tool_name for tool in deep.tools}
        skill_names = {skill.skill_name for skill in deep.skills}
        assert tool_names == expected[stage], (stage, tool_names, expected[stage])
        assert skill_names == {f"{skill_prefix}-{vendor}-research"}, (stage, skill_names)
        observed.append(
            {
                "stage": stage,
                "binding_id": binding.binding_id,
                "tools": sorted(tool_names),
                "skills": sorted(skill_names),
                "lane_binding_digest": binding.lane_binding.digest
                if binding.lane_binding is not None
                else None,
            }
        )
    assert set(expected) <= {row["stage"] for row in observed}
    (root / f"capability-proof-{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "qualified": False, "bindings": observed}, indent=2),
        encoding="utf-8",
    )


async def verify_transfers(
    stack: Any,
    scope: str,
    run_id: str,
    outputs: Any,
    root: Path,
    *,
    dependents: frozenset[str] = frozenset(
        {"formulations", "studies", "synthesize", "verify", "ingest", "finalize"}
    ),
    synthesis_bindings: frozenset[str] = frozenset({"formulation", "appraisal"}),
) -> None:
    store = PostgresOutputContractStore(stack.worker_pool)
    decisions = {}
    for obligation in await store.active_obligations(scope, run_id):
        latest = await store.latest_fulfillment(scope, run_id, obligation.key, obligation.revision)
        assert latest is not None, obligation.key
        decision = latest[1]
        decisions[obligation.key] = decision.model_dump(mode="json")
        if obligation.key == "discover.optional_background":
            assert decision.enforcement.value == "optional" and not decision.submitted
        else:
            assert decision.disposition == "fulfilled", (obligation.key, decision)
    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        rows = await connection.fetch(
            "SELECT plan FROM mission_control.transfer_plan WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 AND run_id=$4::uuid",
            *args,
            run_id,
        )
    plans = [SealedTransferPlan.model_validate(mc.load(row["plan"])) for row in rows]
    expected = set(dependents)
    dependent = [plan for plan in plans if plan.receiver_position in expected]
    assert expected <= {plan.receiver_position for plan in dependent}
    revisions = {output.revision_id: output for output in outputs}
    receipts: list[dict[str, Any]] = []
    for plan in dependent:
        assert plan.exact_sources, plan.receiver_position
        for member in plan.exact_sources:
            assert member.admission == "accepted", member
            assert member.source_ref in revisions, member
            revision = revisions[member.source_ref]
            assert member.revision == f"{revision.deliverable_id}@{revision.revision}", member
            assert member.digest == revision.content_digest, member
        delivered = await PostgresTransferPlanStore(stack.worker_pool).receipts(scope, plan.plan_id)
        assert delivered and all(item.result == "ready" for item in delivered), (
            plan.receiver_position
        )
        receipts.extend(item.model_dump(mode="json") for item in delivered)
    synthesis = [plan for plan in dependent if plan.receiver_position == "synthesize"]
    assert all(
        {member.binding for member in plan.exact_sources} == synthesis_bindings
        for plan in synthesis
    )
    assert all(any(item.binding == "background" for item in plan.omissions) for plan in synthesis)
    (root / f"transfer-proof-{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "qualified": False,
                "fulfillments": decisions,
                "plans": [plan.model_dump(mode="json") for plan in dependent],
                "receipts": receipts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

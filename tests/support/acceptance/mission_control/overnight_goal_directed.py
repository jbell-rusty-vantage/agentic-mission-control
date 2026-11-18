"""Builders, constants and fakes that other test files import.

Moved from tests/acceptance/mission_control/test_overnight_goal_directed.py.
"""

from __future__ import annotations

import json
from typing import Any

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.execution.contracts import StructuredOutputBinding
from mission_control.domain.programs.goal_directed_runtime import (
    GoalNamedExecutorObservation,
    GoalVerifierObservation,
)
from tests.support.acceptance.mission_control.overnight_stagegraph import (
    ROOT,
    overnight_launch_bindings,
    stagegraph_manifest,
)


def goal_manifest(pack: dict[str, Any]) -> str:
    template = ROOT / "tests/fixtures/manifests/sprint-oc-w1/ai-engineer.report.mission.yml"
    document = load_manifest_yaml(
        template.read_text()
        .replace("__PACK__", json.dumps(pack))
        .replace("__PRODUCER__", "frontier.default")
    )
    mission = document["mission"]
    mission["key"] = "overnight-goal-exact-repair"
    mission["title"] = "Two-iteration grounded report repair"
    mission["program"]["verifier"]["environment"]["model"]["profile"] = "frontier.default"
    mission["environment"]["capabilities"] = load_manifest_yaml(stagegraph_manifest(pack))[
        "mission"
    ]["environment"]["capabilities"]
    mission["environment"]["governors"].update(iterations=2, patience=2)
    mission["environment"]["budget"]["tool_calls"] = 40
    return canonical_manifest_bytes(document).decode()


def goal_launch_bindings(technical: Any) -> Any:
    bindings = overnight_launch_bindings(technical)
    schemas = {
        role: StructuredOutputBinding(
            schema_id=f"overnight-goal-{role}",
            revision=1,
            schema_digest=sha256_digest(model.model_json_schema()),
        )
        for role, model in (
            ("executor", GoalNamedExecutorObservation),
            ("verifier", GoalVerifierObservation),
        )
    }
    return bindings.model_copy(
        update={
            "deep_agents": bindings.deep_agents.model_copy(update={"goal_output_schemas": schemas})
        }
    )


async def goal_records(stack: Any, scope: str, run_id: str) -> dict[str, Any]:
    from mission_control.adapters.postgres.run_control import canonical as mc

    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        documents = await connection.fetch(
            "SELECT contract,payload FROM mission_control.runtime_document WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
            "AND contract LIKE 'goal.%' AND identity::jsonb->>0=$4",
            *args,
            run_id,
        )
        result = await connection.fetchrow(
            "SELECT result_digest,result_payload FROM mission_control.coordinator_workflow_result "
            "WHERE installation_id=$1 AND application_id=$2 AND tenant_id=$3 AND run_key=$4",
            *args,
            run_id,
        )
    payload = mc.load(result["result_payload"]) if result else None
    if result:
        assert sha256_digest(payload) == result["result_digest"]
    return {
        "result": payload,
        "documents": [
            {"contract": row["contract"], "payload": mc.load(row["payload"])} for row in documents
        ],
    }

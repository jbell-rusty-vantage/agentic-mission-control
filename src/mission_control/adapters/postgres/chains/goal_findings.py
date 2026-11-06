"""Pin actual Goal verifier findings to a finalized exported submission's exact attempt."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import asyncpg
from pydantic import TypeAdapter

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.transfer import LinkedGoalFindingSnapshot
from mission_control.domain.execution.contracts import OperationExecutionBinding
from mission_control.domain.graph_runtime.identities import GoalDirectedUnitLocation
from mission_control.domain.programs.contracts import GoalExecutionResult, GoalVerificationResult
from mission_control.domain.programs.runtime_units import goal_operation_id


def checked_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict) or sha256_digest(payload) != row["digest"]:
        raise ValueError("linked Goal document digest mismatch")
    return payload


def bind_goal_findings(
    *,
    scope: str,
    run_id: str,
    operation_ref: str,
    operation_attempt: int,
    execution_generation: int,
    binding_row: Mapping[str, Any],
    iteration_row: Mapping[str, Any],
    verification_rows: Sequence[Mapping[str, Any]],
) -> tuple[LinkedGoalFindingSnapshot, ...]:
    binding = OperationExecutionBinding.model_validate(checked_payload(binding_row))
    iteration = checked_payload(iteration_row)
    source = TypeAdapter(GoalExecutionResult).validate_python(iteration["result"])
    identity = source.identity.iteration
    unit = binding.runtime_unit
    location = None if unit is None else unit.location
    if (
        binding.request_scope != scope
        or binding.run_id != run_id
        or binding.operation_id != operation_ref
        or binding.operation_attempt != operation_attempt
        or binding.lane_dispatch is None
        or binding.lane_dispatch.execution_generation != execution_generation
        or binding.semantic_attempt_key != binding_row["identity"]
        or source.operation_identity != binding.semantic_attempt_key
        or source.operation_binding_ref != binding.binding_id
        or source.disposition != "completed"
        or identity.run_id != run_id
        or iteration.get("goal_revision_id") != identity.goal_revision_id
        or json.loads(iteration_row["identity"]) != [run_id, source.identity.semantic_key]
        or operation_ref != goal_operation_id(identity.goal_iteration, "executor")
        or binding.session_id != source.session_id
        or binding.workspace.workspace_id != source.workspace_id
        or unit is None
        or unit.unit_kind != "goal_executor"
        or unit.execution_epoch != identity.execution_epoch
        or not isinstance(location, GoalDirectedUnitLocation)
        or location.goal_iteration != identity.goal_iteration
        or location.goal_revision_id != identity.goal_revision_id
        or location.operation_role != "executor"
        or location.agent_run != source.identity.agent_run
        or location.session_generation != source.identity.session_generation
    ):
        raise ValueError("linked Goal findings do not bind the exact submitted executor attempt")
    snapshots = []
    for row in verification_rows:
        payload = checked_payload(row)
        raw = payload["verification"]
        verification = TypeAdapter(GoalVerificationResult).validate_python(raw)
        if (
            payload.get("goal_revision_id") != identity.goal_revision_id
            or verification.executor_identity != source.identity
            or json.loads(row["identity"]) != [run_id, verification.verification_id]
            or verification.verification_digest
            != sha256_digest(
                {key: value for key, value in raw.items() if key != "verification_digest"}
            )
        ):
            raise ValueError("linked Goal verification is stale, sibling, or digest-mismatched")
        snapshots.append(
            LinkedGoalFindingSnapshot(
                document_identity=row["identity"],
                document_digest=row["digest"],
                payload=payload,
                iteration_identity=iteration_row["identity"],
                iteration_digest=iteration_row["digest"],
                binding_identity=binding_row["identity"],
                binding_digest=binding_row["digest"],
            )
        )
    if not snapshots:
        raise ValueError("linked Goal repair requires its full actual verifier findings")
    return tuple(sorted(snapshots, key=lambda item: item.document_identity))


async def load_goal_findings(
    connection: asyncpg.Connection,
    args: tuple,
    *,
    scope: str,
    run_id: str,
    operation_ref: str,
    operation_attempt: int,
    execution_generation: int,
) -> tuple[LinkedGoalFindingSnapshot, ...] | None:
    if not operation_ref.startswith("goal-iteration/"):
        return None
    prefix = (
        "SELECT identity,payload,digest FROM mission_control.runtime_document "
        "WHERE installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
    )
    bindings = await connection.fetch(
        prefix + "AND contract='operation.binding/1' AND payload->>'run_id'=$4 "
        "AND payload->>'operation_id'=$5 AND (payload->>'operation_attempt')::int=$6 "
        "AND (payload#>>'{lane_dispatch,execution_generation}')::int=$7",
        *args,
        run_id,
        operation_ref,
        operation_attempt,
        execution_generation,
    )
    if len(bindings) != 1:
        raise ValueError("linked Goal source has no unique exact operation binding")
    binding = checked_payload(bindings[0])
    iterations = await connection.fetch(
        prefix + "AND contract='goal.iteration/1' "
        "AND payload#>>'{result,identity,iteration,run_id}'=$4 "
        "AND payload#>>'{result,operation_identity}'=$5 "
        "AND payload#>>'{result,operation_binding_ref}'=$6",
        *args,
        run_id,
        binding["semantic_attempt_key"],
        binding["binding_id"],
    )
    if len(iterations) != 1:
        raise ValueError("linked Goal source has no unique exact completed iteration")
    source = checked_payload(iterations[0])["result"]
    verifications = await connection.fetch(
        prefix + "AND contract='goal.verification/1' "
        "AND payload#>'{verification,executor_identity}'=$4::jsonb ORDER BY identity",
        *args,
        json.dumps(source["identity"]),
    )
    return bind_goal_findings(
        scope=scope,
        run_id=run_id,
        operation_ref=operation_ref,
        operation_attempt=operation_attempt,
        execution_generation=execution_generation,
        binding_row=bindings[0],
        iteration_row=iterations[0],
        verification_rows=verifications,
    )

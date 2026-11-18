"""Builders, constants and fakes that other test files import.

Moved from tests/unit/frames/test_deep_agents_frames.py.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid5

from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
)
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.frames.sink import InMemoryFrameStore
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    MaterializedWorkspace,
    OperationAttemptIdentity,
    OperationExecutionRequest,
    RuntimeInvocation,
)
from tests.support.checkpoint_lineage import activity_attempt, bind_unit, stage_unit
from tests.support.deep_agents import exact_fixture
from tests.support.ids import INSTALLATION, SCOPE
from tests.support.lane_bindings import lane_fields
from tests.support.operations import operation_request


def _unit_binding():  # type: ignore[no-untyped-def]
    binding, _profile, bundle = exact_fixture()
    unit = stage_unit(request_scope=SCOPE, run_id=binding.run_id, operation_id=binding.operation_id)
    return bind_unit(binding, unit), bundle, unit


async def _planned(binding: Any, lineage: CheckpointLineageService) -> RuntimeInvocation:
    payload = operation_request().model_dump(mode="python")
    payload.update(
        request_scope=SCOPE,
        identity=OperationAttemptIdentity(
            run_id=binding.run_id,
            operation_id=binding.operation_id,
            operation_attempt=binding.operation_attempt,
        ),
        execution_runtime="deep_agent",
        native_placement=None,
        **lane_fields(binding),
        runtime_unit=binding.runtime_unit,
    )
    request = OperationExecutionRequest.model_validate(payload)
    bound = bind_operation_execution_request(request)
    plan = await lineage.observe_attempt(bound, activity_attempt(1), dispatching=True)
    return RuntimeInvocation(
        binding=bound,
        prompt_segments=request.prompt_segments,
        workspace=MaterializedWorkspace(
            workspace_id=request.workspace.workspace_id,
            namespace_id=request.workspace.namespace_id,
            provider=request.workspace.provider,
            runtime_digest=request.workspace.runtime_digest,
            image_digest=request.workspace.image_digest,
            mount_manifest_digest=sha256_digest("mounts"),
        ),
        checkpoint_plan=plan,
    )


def _store_for(unit: Any) -> InMemoryFrameStore:
    store = InMemoryFrameStore()
    run_id = uuid5(INSTALLATION, unit.belllabs_run_id)
    store.register_run(SCOPE, unit.belllabs_run_id, run_id, {unit.unit_key: uuid5(run_id, "a")})
    return store

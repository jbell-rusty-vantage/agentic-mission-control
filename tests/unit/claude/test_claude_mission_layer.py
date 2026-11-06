"""MO-12 on `claude_agent_sdk`: the bootstrap entrypoint runs the kit's mission layer in the
leased worktree before the session starts, and a kit that does not reach `prepared` refuses
the start. The mission layer runs under the host's real bash; the SDK client is the FIXTURE."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.claude.harness import ClaudeLaneError
from mission_control.application.environments.mission_layer import ENVIRONMENT_NOT_PREPARED
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.domain.authoring.environment_kits import (
    MISSION_SETUP_RECEIPT,
    MissionSetupReceipt,
)
from mission_control.domain.execution.lanes import PreparedSession, PrepareRequest
from tests.fixtures.environment_kits import (
    BASH,
    kit_document,
    kit_pin,
    mission_layer_service,
    published_kit,
    setup_environ,
)
from tests.unit.claude.fixtures import (
    PROFILE,
    ClaudeStack,
    base_operation,
    claude_binding,
    claude_operation,
    claude_stack,
    materialization_digest_for,
)

pytestmark = pytest.mark.skipif(BASH is None, reason="the mission layer runs under bash")


def _stack(tmp_path: Path, pin: str, **changes: Any) -> ClaudeStack:
    binding = claude_binding(
        materialization_digest=materialization_digest_for(base_operation()),
        environment={
            "kind": "local_workspace",
            "host_profile": "worker.linux.default",
            "setup_pin": pin,
        },
    )
    return claude_stack(
        tmp_path, operation=claude_operation(binding=binding), environ=setup_environ(), **changes
    )


def _request(stack: ClaudeStack) -> PrepareRequest:
    heid = str(LaneExecutionIdentity.of(stack.operation, PROFILE, 1).harness_execution_id)
    return PrepareRequest(
        scope=harness_scope(stack.operation.request_scope),
        lane_profile=PROFILE,
        harness_execution_id=heid,
        binding_digest=stack.operation.effective_configuration_digest,
        idempotency_key=f"{heid}:1:prepare",
        generation=1,
        run_id=stack.operation.identity.run_id,
        operation_id=stack.operation.identity.operation_id,
        attempt_no=1,
    )


async def _prepare(stack: ClaudeStack) -> PreparedSession:
    request = _request(stack)
    stack.harness.stage(request.harness_execution_id, stack.operation)
    return await stack.harness.prepare(request)


async def test_prepare_runs_the_mission_layer_and_records_its_receipt(tmp_path: Path) -> None:
    published = published_kit()
    pin = kit_pin(published)
    stack = _stack(tmp_path, pin, mission_layer=mission_layer_service(published))

    prepared = await _prepare(stack)

    (lease,) = stack.workspace.registry.values()
    root = Path(lease.path)
    receipt = MissionSetupReceipt.parse((root / MISSION_SETUP_RECEIPT).read_bytes())
    assert receipt.kit_pin == pin and receipt.outcome == "prepared"
    assert (root / "marker.txt").is_file()
    assert prepared.projection_digests["setup_receipt_digest"].startswith("sha256:")
    assert prepared.projection_digests["setup_digest"].startswith("sha256:")
    # Idempotent per generation: a second prepare reuses the prepared session.
    assert await stack.harness.prepare(_request(stack)) == prepared


async def test_a_kit_that_is_not_prepared_refuses_the_session(tmp_path: Path) -> None:
    failing = published_kit(
        kit_document(mission={"steps": [{"name": "broken", "run": "exit 4"}], "timeout_s": 30})
    )
    stack = _stack(tmp_path, kit_pin(failing), mission_layer=mission_layer_service(failing))
    with pytest.raises(ClaudeLaneError) as raised:
        await _prepare(stack)
    assert raised.value.code == ENVIRONMENT_NOT_PREPARED
    assert "step broken ran (exit 4)" in str(raised.value)
    assert stack.factory.clients == []


async def test_a_pinned_kit_without_a_mission_layer_service_is_refused(tmp_path: Path) -> None:
    stack = _stack(tmp_path, kit_pin(published_kit()))
    with pytest.raises(ClaudeLaneError) as raised:
        await _prepare(stack)
    assert raised.value.code == ENVIRONMENT_NOT_PREPARED

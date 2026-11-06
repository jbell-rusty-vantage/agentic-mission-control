"""MO-12 on `cursor_local`: a binding that pins an Environment Kit runs the kit's mission layer
in the leased worktree before the bridge starts, with the bridge's allowlisted environment, and
a kit that does not reach `prepared` refuses the session. The mission layer runs under the
host's real bash; the bridge is the FIXTURE replay launcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.adapters.cursor.projection import LaneProjectionError
from mission_control.application.environments.mission_layer import (
    ENVIRONMENT_NOT_PREPARED,
    MissionLayerService,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.authoring.environment_kits import (
    MISSION_SETUP_RECEIPT,
    MissionSetupReceipt,
)
from mission_control.domain.execution.lanes import PreparedSession, PrepareRequest
from tests.fixtures.cursor_controls import harness_fields, started_session
from tests.fixtures.cursor_local import LocalStack, local_stack
from tests.fixtures.environment_kits import (
    BASH,
    kit_document,
    kit_pin,
    mission_layer_service,
    published_kit,
    setup_environ,
)

pytestmark = pytest.mark.skipif(BASH is None, reason="the mission layer runs under bash")

# A worker-only variable the allowlist must keep out of the setup child.
WORKER_ONLY = {"MC_WORKER_ONLY_DSN": "postgresql://worker-only"}


def _stack(tmp_path: Path, pin: str, mission_layer: MissionLayerService | None) -> LocalStack:
    return local_stack(
        tmp_path,
        binding_changes={"setup_pin": pin},
        settings_changes={"worker_environ": setup_environ(**WORKER_ONLY)},
        mission_layer=mission_layer,
    )


async def _prepare(stack: LocalStack) -> tuple[PreparedSession, Path]:
    operation = stack.operation
    heid = str(LaneExecutionIdentity.of(operation, "cursor_local", 1).harness_execution_id)
    stack.harness.stage(heid, operation)
    prepared = await stack.harness.prepare(
        PrepareRequest(
            **harness_fields(operation, heid),
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
        )
    )
    return prepared, Path(stack.harness.lease_path(heid))


async def test_prepare_runs_the_mission_layer_and_records_its_receipt(tmp_path: Path) -> None:
    published = published_kit(
        kit_document(
            mission={
                "steps": [{"name": "marker", "run": "echo ready > marker.txt"}],
                # The setup child sees the bridge's allowlist, never the worker's own variables.
                "health": [{"name": "allowlist", "run": 'test -z "${MC_WORKER_ONLY_DSN:-}"'}],
                "timeout_s": 60,
            }
        )
    )
    pin = kit_pin(published)
    stack = _stack(tmp_path, pin, mission_layer_service(published))

    prepared, root = await _prepare(stack)

    receipt = MissionSetupReceipt.parse((root / MISSION_SETUP_RECEIPT).read_bytes())
    assert receipt.kit_pin == pin and receipt.outcome == "prepared"
    assert [(check.name, check.passed) for check in receipt.health] == [("allowlist", True)]
    assert (root / "marker.txt").is_file()
    assert prepared.projection_digests["setup_digest"].startswith("sha256:")
    assert prepared.projection_digests["setup_receipt_digest"].startswith("sha256:")
    assert stack.launcher.launches == []


async def test_a_kit_that_is_not_prepared_refuses_the_session(tmp_path: Path) -> None:
    failing = published_kit(
        kit_document(mission={"steps": [{"name": "broken", "run": "exit 3"}], "timeout_s": 30})
    )
    stack = _stack(tmp_path, kit_pin(failing), mission_layer_service(failing))
    with pytest.raises(LaneProjectionError) as raised:
        await _prepare(stack)
    assert raised.value.code == ENVIRONMENT_NOT_PREPARED
    assert "step broken ran (exit 3)" in str(raised.value)
    assert stack.launcher.launches == []


async def test_a_pinned_kit_without_a_mission_layer_service_is_refused(tmp_path: Path) -> None:
    stack = _stack(tmp_path, kit_pin(published_kit()), None)
    with pytest.raises(LaneProjectionError) as raised:
        await _prepare(stack)
    assert raised.value.code == ENVIRONMENT_NOT_PREPARED


async def test_a_binding_without_a_kit_starts_without_a_mission_layer(tmp_path: Path) -> None:
    stack = local_stack(tmp_path)
    heid, _ = await started_session(stack)
    root = Path(stack.harness.lease_path(heid))
    assert not (root / MISSION_SETUP_RECEIPT).exists()
    assert stack.launcher.launches

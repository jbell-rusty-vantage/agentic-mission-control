"""MO-12 on `codex`: the kit's mission layer runs in the leased worktree before app-server
starts, and a kit that does not reach `prepared` refuses the start. The mission layer runs
under the host's real bash; app-server is the FIXTURE launcher (never started here)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.adapters.cursor.projection import LaneProjectionError
from mission_control.application.environments.mission_layer import (
    ENVIRONMENT_NOT_PREPARED,
    MissionLayerService,
)
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
from tests.unit.codex.fixture_app_server import FixtureLauncher
from tests.unit.codex.support import (
    PROFILE,
    build_harness,
    codex_binding,
    codex_operation,
    fixture_settings,
)

pytestmark = pytest.mark.skipif(BASH is None, reason="the mission layer runs under bash")


async def _prepare(
    tmp_path: Path, pin: str, mission_layer: MissionLayerService | None
) -> tuple[PreparedSession, Path]:
    operation = codex_operation(
        codex_binding(
            environment={
                "kind": "local_workspace",
                "host_profile": "worker.linux.wsl",
                "setup_pin": pin,
            }
        )
    )
    harness, *_ = build_harness(
        tmp_path,
        FixtureLauncher(),
        settings=fixture_settings(tmp_path, worker_environ=setup_environ()),
        mission_layer=mission_layer,
    )
    heid = str(LaneExecutionIdentity.of(operation, PROFILE, 1).harness_execution_id)
    harness.stage(heid, operation)
    prepared = await harness.prepare(
        PrepareRequest(
            scope=harness_scope(operation.request_scope),
            lane_profile=PROFILE,
            harness_execution_id=heid,
            binding_digest=operation.effective_configuration_digest,
            idempotency_key=f"{heid}:1:prepare",
            generation=1,
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
        )
    )
    (root,) = (path for path in (tmp_path / "leases").iterdir() if path.is_dir())
    return prepared, root


async def test_prepare_runs_the_mission_layer_before_app_server(tmp_path: Path) -> None:
    published = published_kit()
    pin = kit_pin(published)
    prepared, root = await _prepare(tmp_path, pin, mission_layer_service(published))
    receipt = MissionSetupReceipt.parse((root / MISSION_SETUP_RECEIPT).read_bytes())
    assert receipt.kit_pin == pin and receipt.outcome == "prepared"
    assert (root / "marker.txt").is_file()
    assert prepared.projection_digests["setup_receipt_digest"].startswith("sha256:")


async def test_a_kit_that_is_not_prepared_refuses_the_start(tmp_path: Path) -> None:
    failing = published_kit(
        kit_document(mission={"health": [{"name": "absent", "run": "test -d nowhere"}]})
    )
    with pytest.raises(LaneProjectionError) as raised:
        await _prepare(tmp_path, kit_pin(failing), mission_layer_service(failing))
    assert raised.value.code == ENVIRONMENT_NOT_PREPARED
    assert "health absent (exit 1)" in str(raised.value)

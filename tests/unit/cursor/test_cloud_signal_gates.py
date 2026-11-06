"""Gated Cursor create requests carry scoped per-attempt envVars, never committed bytes."""

from pathlib import Path

import pytest

from mission_control.application.agentic_components.placement import LaneProjectionError
from mission_control.domain.capabilities.gates import SignalGatePolicy
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.cursor_controls import started_session


async def test_gated_launch_delivers_the_attempt_credential_once(tmp_path: Path) -> None:
    attempts = []

    async def delivery(operation, identity):
        attempts.append(identity)
        assert identity.request_scope == operation.request_scope
        assert identity.lane_profile == "cursor_cloud"
        return {
            "MC_SIGNAL_URL": "https://ingress.example/v1/ingress/biotech/signals",
            "MC_SIGNAL_TOKEN": "mct_" + "g" * 43,
        }

    stack = cloud_stack(
        tmp_path,
        gates=SignalGatePolicy(),
        cloud_changes={"client_agent_id": False},
        harness_changes={"signal_environment": delivery},
    )
    await started_session(stack)
    assert len(attempts) == 1
    (create,) = stack.api.creates
    assert create["envVars"]["MC_SIGNAL_TOKEN"] == "mct_" + "g" * 43
    assert create["envVars"]["MC_SIGNAL_URL"].startswith("https://ingress.example/")


@pytest.mark.parametrize("client_id", [True, False])
async def test_a_gate_without_a_deliverable_per_run_credential_refuses_before_create(
    tmp_path: Path, client_id: bool
) -> None:
    stack = cloud_stack(
        tmp_path, gates=SignalGatePolicy(), cloud_changes={"client_agent_id": client_id}
    )
    with pytest.raises(LaneProjectionError, match="per-run|configured ingress"):
        await started_session(stack)
    assert stack.api.creates == []

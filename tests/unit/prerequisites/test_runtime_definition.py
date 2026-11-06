"""Generic native runtime admission remains guarded without pretending it is a manifest."""

from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest

from mission_control.application.execution.run_launch import RunLaunchRequest
from mission_control.application.prerequisites.preflight import (
    PrerequisitePreflight,
    PrerequisitesUnmet,
    StoredPrerequisiteLaunchGuard,
)
from mission_control.application.prerequisites.service import InMemoryOwnerPrerequisiteRepository
from mission_control.domain.programs.contracts import StageGraphRunInput
from tests.fixtures.managed_lane import managed_binding, managed_operation
from tests.unit.run_control.test_run_control import request
from tests.unit.run_control.test_run_launch import _input


def generic_definition():
    admitted = request()
    return {
        "contract": "mc.run-request-definition/1",
        "request_scope": admitted.request_scope,
        "idempotency_issuer": admitted.idempotency_issuer,
        "request_id": admitted.request_id,
        "workflow_type_ref": admitted.workflow_type_ref.model_dump(mode="json"),
        "effective_configuration_digest": admitted.effective_configuration_digest,
        "input_manifest": admitted.input_manifest.model_dump(mode="json"),
        "obligation_revision": "1",
        "required_obligation_refs": [],
        "budget_limits": [],
        "baseline_reservations": {},
        "parent_budget_account": None,
    }


@pytest.mark.parametrize("blocked", [False, True])
async def test_generic_contract_uses_fresh_installation_check(blocked):
    check = AsyncMock(return_value=("stale installer",) if blocked else ())
    stored = AsyncMock(return_value={"definition": generic_definition()})
    guard = StoredPrerequisiteLaunchGuard(
        stored,
        PrerequisitePreflight(InMemoryOwnerPrerequisiteRepository(), installation_check=check),
        runtime_templates=AsyncMock(return_value=()),
    )
    workflow = StageGraphRunInput(**_input("run-1"))
    launch = RunLaunchRequest(
        request_scope="tenant-1", run_id="run-1", family="StageGraph", stagegraph=asdict(workflow)
    )
    if blocked:
        with pytest.raises(PrerequisitesUnmet):
            await guard.require_launch(launch, workflow)
    else:
        await guard.require_launch(launch, workflow)
    check.assert_awaited_once()


async def test_generic_provider_template_does_not_bypass_owner_prerequisites():
    stored = AsyncMock(
        return_value={
            "definition": generic_definition(),
            "runtime_operations": [
                managed_operation(managed_binding("sha256:" + "1" * 64)).model_dump(mode="json")
            ],
        }
    )
    guard = StoredPrerequisiteLaunchGuard(
        stored,
        PrerequisitePreflight(InMemoryOwnerPrerequisiteRepository()),
        runtime_templates=AsyncMock(
            return_value=(managed_operation(managed_binding("sha256:" + "1" * 64)),)
        ),
    )
    workflow = StageGraphRunInput(**_input("run-1"))
    launch = RunLaunchRequest(
        request_scope="tenant-1", run_id="run-1", family="StageGraph", stagegraph=asdict(workflow)
    )
    with pytest.raises(PrerequisitesUnmet):
        await guard.require_launch(launch, workflow)

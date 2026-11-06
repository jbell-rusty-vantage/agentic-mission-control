from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from tests.unit.recovery.test_closed_workflow import setup_recovery
from tests.unit.run_control.test_run_control import actor

from mission_control.application.missions.runtime import MissionControlRuntimeService
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    get_mission_principal,
    get_runtime_service,
    router,
)


@pytest.mark.asyncio
async def test_normal_public_route_strict_intent_readback_and_explicit_permission():
    recovery, _, _, _, _, body, run_id = await setup_recovery()
    facade = MissionControlRuntimeService(
        AsyncMock(), AsyncMock(), request_scope="tenant-1", closed_workflow_recovery=recovery
    )
    caller = MissionPrincipal(
        application_id="app",
        installation_id=uuid4(),
        tenant_id=uuid4(),
        issuer="https://issuer.invalid",
        audiences={"authenticated"},
        actor=actor(),
    )
    app = FastAPI()
    app.include_router(router)
    # Transport unit only: existing JWT/registry tests cover actual issuer/grants.
    app.dependency_overrides[get_mission_principal] = lambda: caller
    app.dependency_overrides[get_runtime_service] = lambda: facade
    base = f"/v1/applications/app/runs/{run_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        forged = await client.post(
            base + "/recover-closed-workflow",
            json={**body.model_dump(mode="json"), "cancellation_settled": True},
        )
        assert forged.status_code == 422
        mismatch = await client.post(
            base + "/recover-closed-workflow",
            json=body.model_dump(mode="json"),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert mismatch.status_code == 409
        recovered = await client.post(
            base + "/recover-closed-workflow", json=body.model_dump(mode="json")
        )
        assert recovered.status_code == 202, recovered.text
        replay = await client.post(
            base + "/recover-closed-workflow", json=body.model_dump(mode="json")
        )
        assert replay.json() == recovered.json()
        retained = await client.get(base + f"/closed-workflow-recovery/{body.request_id}")
        assert retained.json() == recovered.json()
        absent = await client.get(base + f"/closed-workflow-recovery/{uuid4()}")
        assert absent.status_code == 404
        caller = caller.model_copy(
            update={"actor": actor().model_copy(update={"permissions": frozenset()})}
        )
        denied = await client.post(
            base + "/recover-closed-workflow", json=body.model_dump(mode="json")
        )
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_unconfigured_trusted_observer_fails_closed():
    _, _, _, _, _, body, run_id = await setup_recovery()
    facade = MissionControlRuntimeService(AsyncMock(), AsyncMock(), request_scope="tenant-1")
    from mission_control.contracts.contracts import MissionControlRejected

    with pytest.raises(MissionControlRejected, match="not configured"):
        await facade.recover_closed_workflow(run_id, body, actor())

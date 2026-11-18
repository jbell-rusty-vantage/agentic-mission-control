"""Builders, constants and fakes that other test files import.

Moved from tests/unit/approvals/test_approval_task_interfaces.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.approvals_memory import (
    InMemoryApprovalStore,
    StaticApprovalContext,
)
from mission_control.application.human_tasks.memory import InMemoryHumanTaskRepository
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.http.human_tasks import router
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from tests.fixtures.provider_frames import INSTALLATION, SCOPE, TENANT
from tests.unit.approvals.fixtures import POLICY, REVIEWER
from tests.unit.human_tasks.fixtures import activation

BASE = "/v1/applications/biotech"


def _principal(actor: str = REVIEWER) -> MissionPrincipal:
    return MissionPrincipal(
        installation_id=INSTALLATION,
        application_id="biotech",
        tenant_id=TENANT,
        issuer="https://issuer.invalid",
        audiences=frozenset({"authenticated"}),
        actor=ActorContext(actor_id=actor),
    )


def _app(service: HumanTaskService, actor: str = REVIEWER) -> FastAPI:
    registry = ApplicationRegistry(
        (
            ApplicationBinding.seal(
                application_id="biotech",
                installation_id=INSTALLATION,
                binding_version="1",
                supabase_project_ref="project",
                database_secret_ref="TEST_DATABASE_URL",
                accepted_issuers={"https://issuer.invalid"},
                accepted_audiences={"authenticated"},
                required_component_version="1",
            ),
        )
    )
    registry.observe(
        "biotech", InstallationObservation(INSTALLATION, "biotech", "project", frozenset({"1"}))
    )
    app = FastAPI()
    app.include_router(router)
    app.state.mission_control_registry = registry
    app.state.mission_control_human_task_services = {(INSTALLATION, "biotech", TENANT): service}
    app.dependency_overrides[get_mission_principal] = lambda: _principal(actor)
    return app


async def _compose() -> tuple[HumanTaskService, ApprovalBroker, Any, Any]:
    store = InMemoryApprovalStore()
    broker = ApprovalBroker(
        store,
        store,
        probe=StaticApprovalContext(1, POLICY),
        connection_ref="worker-a#1",
        poll_seconds=0.01,
    )
    gates = InMemoryHumanTaskRepository()
    gate = await gates.open(activation(scope=SCOPE, run_id="run-1"), actor_ref="runtime")
    service = HumanTaskService(
        gates, request_scope=SCOPE, approvals=store, approval_wake=broker.hub
    )
    return service, broker, store, gate

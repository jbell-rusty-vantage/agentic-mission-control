"""Builders, constants and fakes that other test files import.

Moved from tests/unit/run_control/test_ft_f1_command_mailbox.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastmcp import Context

from mission_control.application.execution.boundary_interventions import BoundaryInterventionService
from mission_control.application.execution.mailbox import MailboxDeliveryService
from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
)
from mission_control.application.missions.service import MissionControlService
from mission_control.contracts.contracts import MissionCommandRequest
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.policies.contracts import (
    ActorContext,
    CommandStatus,
    ExecutionTarget,
    LifecycleCommand,
    RunProjection,
    StartAction,
)
from mission_control.domain.policies.mailbox import MailboxEntry
from mission_control.interfaces.http.mission_control import (
    MissionPrincipal,
    get_mission_principal,
    router,
)
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal
from tests.support.clock import SECOND, Clock
from tests.support.run_control import actor as control_actor
from tests.support.run_control import request as run_request
from tests.support.run_control import service

INSTALLATION = "00000000-0000-7000-8000-0000000000aa"
TENANT = "00000000-0000-7000-8000-0000000000bb"
SCOPE = f"mc/{INSTALLATION}/biotech/{TENANT}"
NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
TARGET = ExecutionTarget(
    family="GoalDirected",
    family_workflow_id="family/run/1",
    root_workflow_id="root/run",
    execution_epoch=1,
)


def operator() -> ActorContext:
    source = control_actor()
    return source.model_copy(
        update={"permissions": source.permissions | {"workflow_run.read", "workflow_run.control"}}
    )


class World:
    def __init__(self) -> None:
        self.authority, self.repository = service()
        self.clock = Clock(NOW + SECOND, step=SECOND)
        self.mailbox = MailboxDeliveryService(
            self.repository.mailbox, self.authority, clock=self.clock
        )
        self.facade = MissionControlService(
            self.authority,
            BoundaryInterventionService(self.authority),
            request_scope=SCOPE,
            mailbox=self.mailbox,
        )
        self.run_id = ""

    async def start(self, request_id: str = "f1-run", target: ExecutionTarget | None = TARGET):
        admitted = await self.authority.admit(
            run_request(request_scope=SCOPE, request_id=request_id)
        )
        assert admitted.run_id is not None
        self.run_id = admitted.run_id
        started = await self.authority.execute(
            self.lifecycle("start", 1, StartAction(execution_target=target))
        )
        assert started.status == CommandStatus.ACCEPTED
        return self

    def lifecycle(self, command_id: str, version: int, action: object) -> LifecycleCommand:
        return LifecycleCommand(
            command_id=command_id,
            idempotency_issuer="operator",
            request_scope=SCOPE,
            run_id=self.run_id,
            expected_run_version=version,
            actor=control_actor(),
            action=action,  # type: ignore[arg-type]
            reason=f"test {command_id}",
            occurred_at=NOW + timedelta(minutes=version),
            correlation_id="correlation-1",
        )

    async def projection(self) -> RunProjection:
        return await self.authority.get_run(SCOPE, self.run_id)

    async def entries(self) -> tuple[MailboxEntry, ...]:
        return await self.repository.mailbox.list_entries(SCOPE, self.run_id)

    async def queue(
        self,
        text: str = "Also update the README with the new flag",
        *,
        kind: str = "queue_instruction",
        boundary: str = "next_turn",
        version: int | None = None,
        **payload: Any,
    ) -> Any:
        projection = await self.projection()
        return await self.facade.command(
            self.run_id,
            self.request(
                kind,
                {"boundary": boundary, "content": {"text": text}, **payload},
                version=version or projection.version,
            ),
            operator(),
        )

    def request(
        self, kind: str, payload: dict[str, Any], *, version: int, generation: int = 1
    ) -> MissionCommandRequest:
        return MissionCommandRequest.model_validate(
            {
                "request_id": str(uuid4()),
                "expected_version": version,
                "expected_generation": generation,
                "target": {"kind": "run", "id": self.run_id},
                "kind": kind,
                "payload": payload,
                "reason": "operator steering",
            }
        )


def _app(world: World, actor: ActorContext | None = None) -> tuple[FastAPI, Any]:
    installation, tenant = parse_request_scope(SCOPE).installation_id, uuid4()
    del tenant
    scope = parse_request_scope(SCOPE)
    registry = ApplicationRegistry(
        (
            ApplicationBinding.seal(
                application_id="biotech",
                installation_id=installation,
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
        "biotech", InstallationObservation(installation, "biotech", "project", frozenset({"1"}))
    )
    app = FastAPI()
    app.include_router(router)
    app.state.mission_control_registry = registry
    app.state.mission_control_services = {(installation, "biotech", scope.tenant_id): world.facade}
    app.dependency_overrides[get_mission_principal] = lambda: MissionPrincipal(
        installation_id=installation,
        application_id="biotech",
        tenant_id=scope.tenant_id,
        issuer="https://issuer.invalid",
        audiences={"authenticated"},
        actor=actor or operator(),
    )
    return app, scope


class Resolver:
    def __init__(self, permissions: frozenset[str]) -> None:
        self.principal = CoordinatorPrincipal(
            actor_id="operator",
            tenant_scope="tenant",
            roles=frozenset({"operator"}),
            permissions=permissions,
            request_scope=SCOPE,
        )

    async def resolve(self, _context: Context) -> CoordinatorPrincipal:
        return self.principal

"""Application-scoped Mission Control HTTP transport.

Composition installs an authenticated principal resolver and a per-application/tenant
service map. A path/header alone can never select a database or grant authority.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.execution.operations.unit_reconciliation import (
    UnitReconciliationRejected,
)
from mission_control.application.execution.run_launch import RunLaunchReceipt, RunLaunchRejected
from mission_control.application.installations.registry import (
    ApplicationRegistry,
    ApplicationScopeDenied,
    InstallationUnavailable,
    VerifiedApplicationIdentity,
    request_scope,
)
from mission_control.application.missions.admission import MissionAdmissionService
from mission_control.application.missions.runtime import MissionControlRuntimeService
from mission_control.application.missions.service import MissionControlService
from mission_control.application.recovery.run_forks import ForkSnapshotNotFound
from mission_control.application.subscriptions.coordinator_service import (
    CoordinatorInboxService,
)
from mission_control.application.subscriptions.launcher import (
    LauncherInbox,
    LaunchNotify,
    subscribe_launcher,
)
from mission_control.contracts.admission_contracts import (
    MissionAdmissionRequest,
    MissionLaunchRequest,
)
from mission_control.contracts.contracts import (
    MissionCommandReceipt,
    MissionCommandRequest,
    MissionControlRejected,
    MissionInspection,
)
from mission_control.contracts.json import parse_json_object
from mission_control.contracts.runtime_contracts import (
    ClosedWorkflowRecoveryRequest,
    MissionForkReceipt,
    MissionForkRequest,
    MissionReconciliationRequest,
    MissionSnapshotRequest,
)
from mission_control.domain.execution.workspace_closure import RunClosureSummary
from mission_control.domain.policies.contracts import (
    ActorContext,
    AdmissionDecision,
    BoundaryCommandStatus,
    CommandResult,
    CommandStatus,
)
from mission_control.domain.policies.errors import (
    AdmissionRejected,
    CommandRejected,
    ConfigurationVerificationFailed,
    IdempotencyConflict,
    RunControlNotFound,
    RunVersionConflict,
)
from mission_control.domain.policies.forks import ForkRejected, RunSnapshotManifest

router = APIRouter(prefix="/v1/applications/{application_id}", tags=["mission-control"])


class MissionPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    installation_id: UUID
    application_id: str = Field(min_length=1)
    tenant_id: UUID
    issuer: str = Field(min_length=1)
    audiences: frozenset[str] = Field(min_length=1)
    actor: ActorContext
    sponsorship_refs: frozenset[str] = frozenset()
    approval_refs: frozenset[str] = frozenset()


class ScopedInspection(MissionInspection):
    application_id: str
    # OVE-204 slice 5: the run's Workspace Closures (count, incomplete, newest), when the
    # tenant's point service has a closure reader; absent otherwise.
    workspace_closures: RunClosureSummary | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ScopedCommandReceipt(MissionCommandReceipt):
    application_id: str


class ScopedSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    application_id: str
    snapshot: RunSnapshotManifest


class ScopedForkReceipt(MissionForkReceipt):
    application_id: str


class ScopedCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    application_id: str
    result: CommandResult


class ScopedAdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    application_id: str
    admission: AdmissionDecision


class ScopedLaunchReceipt(RunLaunchReceipt):
    application_id: str
    coordinator_inbox: LauncherInbox


class ScopedCommands(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    application_id: str
    commands: tuple[BoundaryCommandStatus, ...]


async def require_strict_json_body(request: Request) -> None:
    try:
        parse_json_object(await request.body())
    except ValueError:
        raise HTTPException(status_code=400, detail={"code": "invalid_json_object"}) from None


async def get_mission_principal() -> MissionPrincipal:
    """Override with issuer/audience verification and current application grants."""
    raise HTTPException(status_code=503, detail={"code": "authentication_not_configured"})


def authorize_application(
    application_id: str,
    request: Request,
    principal: MissionPrincipal,
) -> None:
    # Authorization completes before consulting a connection/service registry.
    if principal.application_id != application_id:
        raise HTTPException(status_code=403, detail={"code": "application_scope_denied"})
    bindings = getattr(request.app.state, "mission_control_registry", None)
    if not isinstance(bindings, ApplicationRegistry):
        raise HTTPException(status_code=503, detail={"code": "application_registry_unavailable"})
    try:
        bindings.resolve(
            application_id,
            VerifiedApplicationIdentity(
                issuer=principal.issuer,
                audiences=principal.audiences,
                application_id=principal.application_id,
                installation_id=principal.installation_id,
                tenant_id=principal.tenant_id,
            ),
        )
    except ApplicationScopeDenied:
        raise HTTPException(status_code=403, detail={"code": "application_scope_denied"}) from None
    except InstallationUnavailable:
        raise HTTPException(status_code=503, detail={"code": "application_unavailable"}) from None


def principal_request_scope(principal: MissionPrincipal) -> str:
    return request_scope(
        VerifiedApplicationIdentity(
            issuer=principal.issuer,
            audiences=principal.audiences,
            application_id=principal.application_id,
            installation_id=principal.installation_id,
            tenant_id=principal.tenant_id,
        )
    )


# Tracing Stage 3 (clean code): one registry name and one permission check for the routes
# that read run evidence (artifacts, transcript `full=true`, points, replay).
ARTIFACT_BODY_READERS = "mission_control_artifact_body_readers"
"""`app.state` map of each tenant's `GrantedArtifactBodyReader`, keyed like the services."""


def forbidden(permission: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": "forbidden", "permission": permission})


def require_permission(principal: MissionPrincipal, permission: str) -> None:
    if permission not in principal.actor.permissions:
        raise forbidden(permission)


def get_mission_service(
    application_id: str,
    request: Request,
    principal: Annotated[MissionPrincipal, Depends(get_mission_principal)],
) -> MissionControlService:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, "mission_control_services", {})
    key = (principal.installation_id, application_id, principal.tenant_id)
    service = registry.get(key)
    if not isinstance(service, MissionControlService):
        raise HTTPException(status_code=503, detail={"code": "application_unavailable"})
    if service.request_scope != principal_request_scope(principal):
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return service


_LOG = logging.getLogger(__name__)
Principal = Annotated[MissionPrincipal, Depends(get_mission_principal)]
Service = Annotated[MissionControlService, Depends(get_mission_service)]


def get_runtime_service(
    application_id: str,
    request: Request,
    principal: Principal,
) -> MissionControlRuntimeService:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, "mission_control_runtime_services", {})
    service = registry.get((principal.installation_id, application_id, principal.tenant_id))
    if not isinstance(service, MissionControlRuntimeService):
        raise HTTPException(status_code=503, detail={"code": "runtime_services_unavailable"})
    if service.request_scope != principal_request_scope(principal):
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return service


RuntimeService = Annotated[MissionControlRuntimeService, Depends(get_runtime_service)]


def get_admission_service(
    application_id: str,
    request: Request,
    principal: Principal,
) -> MissionAdmissionService:
    authorize_application(application_id, request, principal)
    registry = getattr(request.app.state, "mission_control_admission_services", {})
    service = registry.get((principal.installation_id, application_id, principal.tenant_id))
    if not isinstance(service, MissionAdmissionService):
        raise HTTPException(status_code=503, detail={"code": "admission_services_unavailable"})
    if service.request_scope != principal_request_scope(principal):
        raise HTTPException(status_code=503, detail={"code": "service_scope_mismatch"})
    return service


AdmissionService = Annotated[MissionAdmissionService, Depends(get_admission_service)]


def launcher_inbox_service(
    request: Request, principal: MissionPrincipal
) -> CoordinatorInboxService | None:
    """The tenant's coordinator inbox service for a launch's auto-subscribe (None if absent).

    Launch routes authorize the principal through their own service dependency first; an
    application database without the inbox tables (release < 1.2.0) has none composed.
    """

    registry = getattr(request.app.state, "mission_control_coordinator_inbox_services", {})
    service = registry.get(
        (principal.installation_id, principal.application_id, principal.tenant_id)
    )
    if not isinstance(service, CoordinatorInboxService):
        return None
    if service.request_scope != principal_request_scope(principal):
        return None
    return service


NotifyQuery = Annotated[LaunchNotify, Query(description="`none` skips the launcher's inbox")]


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, MissionControlRejected):
        status = {
            "unauthorized": 403,
            "unavailable": 503,
            "stale_version": 409,
            "stale_generation": 409,
            # SPEC-06: inline mailbox content above the cap is a typed 413.
            "content_too_large": 413,
        }.get(exc.code, 422)
        detail: dict[str, object] = {"code": exc.code, "message": str(exc)}
        if exc.frontier is not None:
            detail["frontier"] = exc.frontier
        return HTTPException(status_code=status, detail=detail)
    if isinstance(exc, (RunControlNotFound, ForkSnapshotNotFound)):
        return HTTPException(status_code=404, detail={"code": "resource_not_found"})
    if isinstance(exc, (IdempotencyConflict, RunVersionConflict)):
        return HTTPException(status_code=409, detail={"code": "request_conflict"})
    if isinstance(exc, ForkRejected):
        status = {
            "unauthorized": 403,
            "cross_scope_fork": 404,
            "protected_field": 422,
            "field_not_patchable": 422,
            "invalid_patch": 422,
            "cognitive_seed_not_supported": 422,
            "frontier_not_closed": 422,
            "fork_position_unavailable": 422,
            "frontier_closure_unavailable": 503,
            "cognitive_seed_unavailable": 503,
            "fork_materialization_ambiguous": 503,
        }.get(exc.code, 409)
        fork_detail: dict[str, object] = {"code": exc.code, "message": str(exc)}
        if exc.reasons:
            # 1.4.4 (P5.2): a `strict` refusal names the stages the frontier must add.
            fork_detail["reasons"] = list(exc.reasons)
        return HTTPException(status_code=status, detail=fork_detail)
    if isinstance(exc, UnitReconciliationRejected):
        return HTTPException(status_code=409, detail={"code": "reconciliation_rejected"})
    if isinstance(exc, RunLaunchRejected):
        return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=422, detail={"code": "command_rejected"})


_EXPECTED_ERRORS = (
    MissionControlRejected,
    RunControlNotFound,
    IdempotencyConflict,
    RunVersionConflict,
    CommandRejected,
    ForkSnapshotNotFound,
    ForkRejected,
    UnitReconciliationRejected,
    AdmissionRejected,
    ConfigurationVerificationFailed,
    RunLaunchRejected,
)


@router.get("/runs/{run_id}/inspection", response_model=ScopedInspection)
async def inspect_run(
    run_id: str,
    principal: Principal,
    service: Service,
    request: Request,
) -> dict[str, Any]:
    try:
        inspection = await service.inspect(run_id, principal.actor)
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    payload = {"application_id": principal.application_id, **inspection.model_dump(mode="json")}
    closures = await _closure_summary(request, principal, run_id)
    if closures is not None:
        payload["workspace_closures"] = closures.model_dump(mode="json")
    return payload


async def _closure_summary(
    request: Request, principal: MissionPrincipal, run_id: str
) -> RunClosureSummary | None:
    """OVE-204 slice 5: best effort; an inspection never fails on closure evidence."""

    services = getattr(request.app.state, "mission_control_cognition_point_services", {})
    points = services.get(
        (principal.installation_id, principal.application_id, principal.tenant_id)
    )
    if points is None or getattr(points, "closure_reader", None) is None:
        return None
    try:
        return RunClosureSummary.of(await points.closures(run_id))
    except Exception:
        _LOG.warning("workspace closures of %s were not summarized", run_id, exc_info=True)
        return None


@router.get("/runs/{run_id}/commands", response_model=ScopedCommands)
async def list_commands(
    run_id: str,
    principal: Principal,
    service: Service,
) -> dict[str, Any]:
    try:
        commands = await service.commands(run_id, principal.actor)
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    return {
        "application_id": principal.application_id,
        "commands": [command.model_dump(mode="json") for command in commands],
    }


@router.post(
    "/runs/{run_id}/commands",
    response_model=ScopedCommandReceipt,
    dependencies=[Depends(require_strict_json_body)],
)
async def send_command(
    run_id: str,
    body: MissionCommandRequest,
    response: Response,
    principal: Principal,
    service: Service,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if idempotency_key is not None and idempotency_key != str(body.request_id):
        raise HTTPException(status_code=409, detail={"code": "idempotency_key_mismatch"})
    try:
        receipt = await service.command(run_id, body, principal.actor)
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    if receipt.admission.status == CommandStatus.STALE:
        response.status_code = 409
    elif receipt.admission.status == CommandStatus.REJECTED:
        response.status_code = 422
    else:
        response.status_code = 200 if receipt.replay else 202
    return {"application_id": principal.application_id, **receipt.model_dump(mode="json")}


@router.post(
    "/runs/{run_id}/snapshots",
    status_code=201,
    response_model=ScopedSnapshot,
    dependencies=[Depends(require_strict_json_body)],
)
async def create_snapshot(
    run_id: str,
    body: MissionSnapshotRequest,
    principal: Principal,
    service: RuntimeService,
) -> dict[str, Any]:
    try:
        snapshot = await service.snapshot(run_id, body, principal.actor)
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    return {
        "application_id": principal.application_id,
        "snapshot": snapshot.model_dump(mode="json"),
    }


@router.get("/runs/{run_id}/snapshots/{snapshot_id:path}", response_model=ScopedSnapshot)
async def get_snapshot(
    run_id: str,
    snapshot_id: str,
    principal: Principal,
    service: RuntimeService,
) -> dict[str, Any]:
    try:
        snapshot = await service.get_snapshot(run_id, snapshot_id, principal.actor)
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    return {
        "application_id": principal.application_id,
        "snapshot": snapshot.model_dump(mode="json"),
    }


@router.post(
    "/runs/{run_id}/forks",
    status_code=202,
    response_model=ScopedForkReceipt,
    dependencies=[Depends(require_strict_json_body)],
)
async def fork_run(
    run_id: str,
    body: MissionForkRequest,
    principal: Principal,
    service: RuntimeService,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if idempotency_key is not None and idempotency_key != str(body.request_id):
        raise HTTPException(status_code=409, detail={"code": "idempotency_key_mismatch"})
    try:
        receipt = await service.fork(
            run_id,
            body,
            principal.actor,
            sponsorship_refs=principal.sponsorship_refs,
            approval_refs=principal.approval_refs,
        )
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    return {"application_id": principal.application_id, **receipt.model_dump(mode="json")}


@router.post(
    "/runs/{run_id}/reconcile-unit",
    response_model=ScopedCommandResult,
    dependencies=[Depends(require_strict_json_body)],
)
async def reconcile_unit(
    run_id: str,
    body: MissionReconciliationRequest,
    response: Response,
    principal: Principal,
    service: RuntimeService,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if idempotency_key is not None and idempotency_key != str(body.request_id):
        raise HTTPException(status_code=409, detail={"code": "idempotency_key_mismatch"})
    try:
        result = await service.reconcile(run_id, body, principal.actor)
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    response.status_code = {
        CommandStatus.ACCEPTED: 202,
        CommandStatus.REJECTED: 422,
        CommandStatus.STALE: 409,
    }[result.status]
    return {"application_id": principal.application_id, "result": result.model_dump(mode="json")}


@router.post(
    "/runs/{run_id}/recover-closed-workflow",
    response_model=ScopedCommandResult,
    dependencies=[Depends(require_strict_json_body)],
)
async def recover_closed_workflow(
    run_id: str,
    body: ClosedWorkflowRecoveryRequest,
    response: Response,
    principal: Principal,
    service: RuntimeService,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if idempotency_key is not None and idempotency_key != str(body.request_id):
        raise HTTPException(status_code=409, detail={"code": "idempotency_key_mismatch"})
    try:
        result = await service.recover_closed_workflow(run_id, body, principal.actor)
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    response.status_code = {
        CommandStatus.ACCEPTED: 202,
        CommandStatus.REJECTED: 422,
        CommandStatus.STALE: 409,
    }[result.status]
    return {"application_id": principal.application_id, "result": result.model_dump(mode="json")}


@router.get(
    "/runs/{run_id}/closed-workflow-recovery/{request_id}", response_model=ScopedCommandResult
)
async def closed_workflow_recovery_result(
    run_id: str,
    request_id: UUID,
    principal: Principal,
    service: RuntimeService,
) -> dict[str, Any]:
    try:
        result = await service.closed_workflow_recovery_result(
            run_id, str(request_id), principal.actor
        )
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "resource_not_found"})
    return {"application_id": principal.application_id, "result": result.model_dump(mode="json")}


@router.post(
    "/run-requests",
    response_model=ScopedAdmissionDecision,
    dependencies=[Depends(require_strict_json_body)],
)
async def admit_run(
    body: MissionAdmissionRequest,
    response: Response,
    principal: Principal,
    service: AdmissionService,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if idempotency_key is not None and idempotency_key != str(body.request_id):
        raise HTTPException(status_code=409, detail={"code": "idempotency_key_mismatch"})
    try:
        decision = await service.admit(
            body,
            principal.actor,
            sponsorship_refs=principal.sponsorship_refs,
            approval_refs=principal.approval_refs,
        )
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    response.status_code = 201 if decision.status == "accepted" else 422
    return {
        "application_id": principal.application_id,
        "admission": decision.model_dump(mode="json"),
    }


@router.post(
    "/runs/{run_id}/launch",
    response_model=ScopedLaunchReceipt,
    status_code=202,
    dependencies=[Depends(require_strict_json_body)],
)
async def launch_run(
    run_id: str,
    body: MissionLaunchRequest,
    request: Request,
    principal: Principal,
    service: AdmissionService,
    notify: NotifyQuery = "inbox",
) -> dict[str, Any]:
    # SPEC-04 §6: the launcher's inbox exists before the launch, so no event precedes it.
    inbox = await subscribe_launcher(
        launcher_inbox_service(request, principal), run_id, principal.actor, notify=notify
    )
    try:
        receipt = await service.launch(run_id, body, principal.actor)
    except _EXPECTED_ERRORS as exc:
        raise _error(exc) from None
    return {
        "application_id": principal.application_id,
        **receipt.model_dump(mode="json"),
        "coordinator_inbox": inbox.model_dump(mode="json"),
    }

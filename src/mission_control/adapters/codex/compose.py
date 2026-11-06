"""Composition helpers for the `codex` lane (MP-08).

`bootstrap/**` and `adapters/temporal/deployment_composition.py` are integrator-owned; the
integrator's `compose_codex_local_lane` calls `compose_codex_local` below with the worker's
pieces: the workspace leaser, the projection source and its catalog `rows` resolver (MP-03
required executables), the artifact sink, MP-05's auth admission (`AdmissionServiceSource`),
`application.execution.child_environment.provider_child_environment` as `child_environment`
(the MO-04 allowlist), the worker's MP-11 `ApprovalBroker` and its Kernel Hook callback
service (G11; the one `cursor_local` shares) with the loopback URL it listens on. Without a
broker the lane's approvals fail closed; without a hook service a projection with Kernel
Hooks is refused; a `codex --version` other than the pin is refused at start unless
`allow_version_mismatch` is passed explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from mission_control.adapters.codex.approvals import (
    DEFAULT_APPROVAL_REVIEWERS,
    DEFAULT_APPROVAL_WAIT_SECONDS,
)
from mission_control.adapters.codex.harness import (
    DEFAULT_HOOK_CALLBACK_BASE_URL,
    ArtifactSink,
    AuthAdmissionSource,
    CodexHomeMode,
    CodexLocalHarness,
    CodexLocalSettings,
    WorkspaceLeaser,
)
from mission_control.adapters.codex.launcher import AppServerLauncher, SubprocessAppServerLauncher
from mission_control.application.agentic_components.placement import (
    DurableInputReader,
    ProjectionSource,
    RowsResolver,
)
from mission_control.application.environments.mission_layer import MissionLayerService
from mission_control.application.execution.approvals_broker import ApprovalBroker
from mission_control.application.execution.auth_admission import AuthAdmission, AuthAdmissionService
from mission_control.application.execution.child_environment import ChildEnvironmentBuilder
from mission_control.application.execution.harness.hook_callbacks import HookCallbackService
from mission_control.application.execution.operations.lane_outputs import LaneOutputCustody
from mission_control.application.secrets.delivery import ProcessSecretDelivery
from mission_control.domain.execution.bindings import ProviderExecutionBinding


class AdmissionServiceSource:
    """`AuthAdmissionSource` over MP-05's `AuthAdmissionService` (profile from the binding)."""

    def __init__(self, service: AuthAdmissionService) -> None:
        self._service = service

    async def admit(self, binding: ProviderExecutionBinding) -> AuthAdmission:
        return await self._service.admit("codex", binding.auth.profile)


def compose_codex_local(
    *,
    leaser: WorkspaceLeaser,
    projections: ProjectionSource,
    artifacts: ArtifactSink,
    auth: AuthAdmissionSource,
    lease_root: Path,
    inputs: DurableInputReader | None = None,
    rows: RowsResolver | None = None,
    launcher: AppServerLauncher | None = None,
    codex_binary: str = "codex",
    codex_home_mode: CodexHomeMode = "isolated",
    owner_codex_home: Path | None = None,
    default_repository: str | None = None,
    child_environment: ChildEnvironmentBuilder,
    environ: Mapping[str, str] | None = None,
    broker: ApprovalBroker | None = None,
    approval_wait_seconds: float = DEFAULT_APPROVAL_WAIT_SECONDS,
    allow_version_mismatch: bool = False,
    approval_reviewers: tuple[str, ...] = DEFAULT_APPROVAL_REVIEWERS,
    outputs: LaneOutputCustody | None = None,
    hooks: HookCallbackService | None = None,
    hook_callback_base_url: str = DEFAULT_HOOK_CALLBACK_BASE_URL,
    secrets: ProcessSecretDelivery | None = None,
    mission_layer: MissionLayerService | None = None,
) -> CodexLocalHarness:
    """The `codex` harness.

    `rows` enables MP-03's required-executables check (production passes the catalog rows
    resolver); `environ` is the worker environment the child's allow-listed names are read
    from (`os.environ` when None); `broker` is the worker's MP-11 approval broker (approvals
    fail closed without one); `approval_wait_seconds` bounds each native approval wait and
    must stay below the `lane.turn` segment budget; `allow_version_mismatch` is the explicit
    override of the `codex-cli 0.162.1` pin (only for the subprocess launcher built here);
    `approval_reviewers` names who may resolve a codex approval task (a principal or a
    `reviewer:<role>` grant; the deployment's `mission_control_approval_reviewers`); `hooks`
    answers the projected Kernel Hooks at `hook_callback_base_url` (the worker's loopback
    listener); `mission_layer` runs the mission layer of a binding that pins an Environment
    Kit before app-server starts (a pinned kit without one is refused).
    """

    if approval_wait_seconds <= 0:
        raise ValueError("approval_wait_seconds is a positive bound")
    if not approval_reviewers or not all(approval_reviewers):
        raise ValueError("approval_reviewers names at least one non-empty reviewer")
    settings = CodexLocalSettings(
        lease_root=lease_root,
        codex_home_mode=codex_home_mode,
        owner_codex_home=owner_codex_home,
        default_repository=default_repository,
        worker_environ=environ,
        approval_wait_seconds=approval_wait_seconds,
        approval_reviewers=tuple(approval_reviewers),
        hook_callback_base_url=hook_callback_base_url,
    )
    return CodexLocalHarness(
        launcher=launcher
        or SubprocessAppServerLauncher(codex_binary, allow_version_mismatch=allow_version_mismatch),
        leaser=leaser,
        projections=projections,
        artifacts=artifacts,
        auth=auth,
        settings=settings,
        child_environment=child_environment,
        inputs=inputs,
        rows=rows,
        broker=broker,
        outputs=outputs,
        hooks=hooks,
        secrets=secrets,
        mission_layer=mission_layer,
    )


__all__ = ["AdmissionServiceSource", "compose_codex_local"]

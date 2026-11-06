"""The mission layer of a local lane: render, deliver, run and read back (ADR-0042).

On ``cursor_local``, ``claude_agent_sdk`` and ``codex`` the bootstrap entrypoint is Mission
Control's own prepare step (SPEC-01 section 1). Given the binding's Environment Kit pin it

1. renders ``.mission/setup/run`` from the kit's mission steps (readiness ``rendered``);
2. writes it into the leased worktree, removing any earlier receipt (``delivered``);
3. runs it once, in the worktree, before the session starts, with the allowlisted child
   environment plus the binding's ``setup``-phase secrets (the Cursor binding carries no
   broker-delivered secrets yet, so ``cursor_local`` runs it with the bridge's allowlist);
4. reads ``.mission/setup/receipt.json``; only a receipt for this exact pin with every step and
   health check passing lifts readiness to ``prepared``.

Local launch policy requires ``prepared`` (SPEC-01 section 8): a lane whose binding pins a kit
never starts a session on a weaker level, and a kit pin without a composed service is refused
rather than skipped.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from pydantic import ValidationError

from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.execution.child_environment import ChildEnvironmentBuilder
from mission_control.application.secrets.delivery import AttemptIdentity, ProcessSecretDelivery
from mission_control.domain.authoring.environment_kits import (
    MISSION_SETUP_RECEIPT,
    MISSION_SETUP_RUN,
    MissionSetupReceipt,
    ReadinessLevel,
    RenderedMissionLayer,
    SetupPhase,
    receipt_readiness,
    render_mission_layer,
)
from mission_control.domain.capabilities.bundles import sha256_hex
from mission_control.domain.execution.bindings import EnvironmentBinding

ENVIRONMENT_NOT_PREPARED: Final = "ENVIRONMENT_NOT_PREPARED"
# Extra time the runner allows beyond the kit's own bound before it stops the script.
RUNNER_GRACE_S: Final = 30.0


class EnvironmentNotPrepared(RuntimeError):
    """The binding pins a kit and its mission layer did not reach ``prepared``."""

    code = ENVIRONMENT_NOT_PREPARED

    def __init__(self, detail: str) -> None:
        super().__init__(f"{ENVIRONMENT_NOT_PREPARED}: {detail}")
        self.detail = detail


class MissionSetupRunner(Protocol):
    """Runs ``bash .mission/setup/run --phase <phase>`` in ``root``; returns its exit code."""

    async def run(
        self,
        root: Path,
        *,
        phase: SetupPhase,
        environment: Mapping[str, str],
        timeout_s: float,
    ) -> int: ...


@dataclass(frozen=True)
class MissionLayerOutcome:
    kit_pin: str
    setup_digest: str
    readiness: ReadinessLevel
    exit_code: int
    receipt: MissionSetupReceipt | None
    receipt_digest: str | None
    reasons: tuple[str, ...] = ()

    def digests(self) -> dict[str, str]:
        """What a prepared session records beside its projection digests."""

        digests = {"setup_digest": self.setup_digest}
        if self.receipt_digest is not None:
            digests["setup_receipt_digest"] = self.receipt_digest
        return digests


def _deliver(root: Path, rendered: RenderedMissionLayer) -> None:
    (root / MISSION_SETUP_RECEIPT).unlink(missing_ok=True)
    for relative, content in rendered.files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    (root / MISSION_SETUP_RUN).chmod(0o755)


def _read_receipt(root: Path) -> tuple[MissionSetupReceipt | None, str | None, str | None]:
    path = root / MISSION_SETUP_RECEIPT
    if not path.is_file():
        return None, None, None
    content = path.read_bytes()
    digest = "sha256:" + sha256_hex(content)
    try:
        return MissionSetupReceipt.parse(content), digest, None
    except (ValueError, ValidationError):
        return None, digest, f"{MISSION_SETUP_RECEIPT} is not a mc.mission_setup_receipt.v1"


class MissionLayerService:
    def __init__(self, kits: EnvironmentKitCatalog, runner: MissionSetupRunner) -> None:
        self._kits = kits
        self._runner = runner

    async def prepare(
        self,
        root: Path,
        *,
        kit_pin: str,
        environment: Mapping[str, str],
        phase: SetupPhase = "prepare",
    ) -> MissionLayerOutcome:
        definition = await self._kits.resolve(kit_pin)
        if definition is None:
            raise EnvironmentNotPrepared(f"environment kit {kit_pin} is not published")
        rendered = render_mission_layer(definition.kit, pin=kit_pin)
        await asyncio.to_thread(_deliver, root, rendered)
        exit_code = await self._runner.run(
            root,
            phase=phase,
            environment=environment,
            timeout_s=definition.kit.mission.timeout_s + RUNNER_GRACE_S,
        )
        receipt, receipt_digest, unreadable = await asyncio.to_thread(_read_receipt, root)
        readiness, reasons = receipt_readiness(receipt, kit_pin=rendered.kit_pin)
        if unreadable is not None:
            reasons = (unreadable,)
        return MissionLayerOutcome(
            kit_pin=rendered.kit_pin,
            setup_digest=rendered.setup_digest,
            readiness=readiness,
            exit_code=exit_code,
            receipt=receipt,
            receipt_digest=receipt_digest,
            reasons=reasons,
        )


async def run_mission_layer(
    service: MissionLayerService | None,
    kit_pin: str | None,
    root: Path,
    *,
    environment: Mapping[str, str],
) -> MissionLayerOutcome | None:
    """The local bootstrap entrypoint of one lane's prepare step.

    None when the binding pins no kit. Otherwise the mission layer runs with ``environment``
    (the lane's allowlisted child environment) and must reach ``prepared``; anything less
    raises :class:`EnvironmentNotPrepared` naming why.
    """

    if kit_pin is None:
        return None
    if service is None:
        raise EnvironmentNotPrepared(
            f"the binding pins environment kit {kit_pin} but no mission layer service is composed"
        )
    outcome = await service.prepare(root, kit_pin=kit_pin, environment=environment)
    if not outcome.readiness.at_least(ReadinessLevel.PREPARED):
        raise EnvironmentNotPrepared(
            f"{outcome.kit_pin} reached {outcome.readiness.value}: " + "; ".join(outcome.reasons)
        )
    return outcome


async def prepare_lane_environment(
    service: MissionLayerService | None,
    environment: EnvironmentBinding,
    root: Path,
    *,
    identity: AttemptIdentity,
    environ: Mapping[str, str],
    child_environment: ChildEnvironmentBuilder,
    secrets: ProcessSecretDelivery | None,
) -> MissionLayerOutcome | None:
    """:func:`run_mission_layer` for a lane bound by ``mc.environment_binding.v1``: the
    allowlisted child environment plus the binding's ``setup``-phase secrets."""

    if environment.setup_pin is None:
        return None
    values: dict[str, str] = {}
    if service is not None and secrets is not None:
        delivered = await secrets.environment(environment, identity, phase="setup")
        values.update(delivered.values)
    return await run_mission_layer(
        service,
        environment.setup_pin,
        root,
        environment=child_environment(environ, None, extra=values),
    )


__all__ = [
    "ENVIRONMENT_NOT_PREPARED",
    "RUNNER_GRACE_S",
    "EnvironmentNotPrepared",
    "MissionLayerOutcome",
    "MissionLayerService",
    "MissionSetupRunner",
    "prepare_lane_environment",
    "run_mission_layer",
]

"""Governed cancellation preserves accepted commands across outbox redelivery."""

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from mission_control.application.chains.cancellation import RunControlChainCanceller
from mission_control.application.chains.relay import ChainIntent
from mission_control.application.execution.boundary_interventions import BoundaryInterventionService
from mission_control.application.execution.service import RunControlService
from mission_control.domain.policies.contracts import CommandStatus, RunPhase


def intent() -> ChainIntent:
    chain = uuid4()
    return ChainIntent(
        intent_kind="cancel_run",
        delivery_key="cancel:receiver",
        request_scope="scope",
        chain_id=chain,
        mission_id=uuid4(),
        run_id=uuid4(),
        run_key="receiver",
        actor_ref=f"chain:{chain}",
        reason="upstream_cancelled",
    )


class Control:
    def __init__(self) -> None:
        self.version = 1
        self.phase = RunPhase.ACTIVE
        self.commands: list[Any] = []
        self.accepted: list[Any] = []
        self.redeliveries = 0
        self.stale = False
        self.crash = False
        self.reject = False

    async def get_run(self, scope: str, run: str) -> Any:
        assert (scope, run) == ("scope", "receiver")
        return SimpleNamespace(version=self.version, phase=self.phase)

    async def list_boundary_commands(self, scope: str, run: str) -> Any:
        return self.accepted

    async def execute(self, command: Any) -> Any:
        self.commands.append(command)
        self.version += 1
        if self.stale:
            self.stale = False
            return SimpleNamespace(status=CommandStatus.STALE)
        if self.reject:
            return SimpleNamespace(status=CommandStatus.REJECTED, reason_code="denied")
        self.accepted.append(
            SimpleNamespace(
                command=SimpleNamespace(
                    idempotency_issuer=command.idempotency_issuer,
                    command_id=command.command_id,
                    target_sequence=1,
                )
            )
        )
        if self.crash:
            self.crash = False
            raise ConnectionError("accepted before transport interruption")
        return SimpleNamespace(status=CommandStatus.ACCEPTED)

    async def redeliver(self, scope: str, run: str) -> None:
        assert (scope, run) == ("scope", "receiver")
        self.redeliveries += 1

    def canceller(self) -> RunControlChainCanceller:
        return RunControlChainCanceller(
            cast(RunControlService, self), cast(BoundaryInterventionService, self)
        )


@pytest.mark.asyncio
async def test_accepted_cancel_replays_without_new_command_after_delivery_crash() -> None:
    control = Control()
    control.crash = True
    release = intent()
    with pytest.raises(ConnectionError):
        await control.canceller().cancel(release)
    await control.canceller().cancel(release)
    assert len(control.commands) == 1
    assert control.redeliveries == 1
    command = control.commands[0]
    assert command.run_id == "receiver"
    assert command.action.kind == "cancel"
    assert command.actor.actor_id == release.actor_ref
    assert command.actor.permissions == frozenset({"workflow_run.cancel"})
    assert command.causation_id == release.delivery_key


@pytest.mark.asyncio
async def test_stale_version_uses_new_identity_then_replays_accepted_command() -> None:
    control = Control()
    control.stale = True
    release = intent()
    await control.canceller().cancel(release)
    await control.canceller().cancel(release)
    assert len(control.commands) == 2
    assert control.commands[0].command_id.endswith(":v1")
    assert control.commands[1].command_id.endswith(":v2")
    assert control.redeliveries == 1


@pytest.mark.asyncio
async def test_terminal_receiver_never_gets_new_cancellation() -> None:
    control = Control()
    control.phase = RunPhase.TERMINAL
    await control.canceller().cancel(intent())
    assert not control.commands


@pytest.mark.asyncio
async def test_refused_command_is_not_acknowledged() -> None:
    control = Control()
    control.reject = True
    with pytest.raises(RuntimeError, match="denied"):
        await control.canceller().cancel(intent())


@pytest.mark.asyncio
async def test_non_chain_actor_is_refused() -> None:
    control = Control()
    with pytest.raises(ValueError, match="chain actor"):
        await control.canceller().cancel(intent().model_copy(update={"actor_ref": "other"}))
    assert not control.commands

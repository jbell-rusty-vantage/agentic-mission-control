"""Governed cancellation preserves accepted commands across outbox redelivery.

`RunControlChainCanceller` runs over the real `RunControlService` (in-memory repository) and
the real `BoundaryInterventionService` with its delivery service; only the Temporal transport
is a scripted boundary double. A crash or a concurrent command is injected by a subclass of the
intervention service that performs the real call first (OVE-238: replaces the hand-written
`Control` stand-in for run control).
"""

from uuid import uuid4

import pytest

from mission_control.application.chains.cancellation import RunControlChainCanceller
from mission_control.application.chains.relay import ChainIntent
from mission_control.application.execution.boundary_interventions import (
    BoundaryCommandDeliveryService,
    BoundaryInterventionService,
)
from mission_control.application.execution.service import RunControlService
from mission_control.application.execution.unstarted_cancellation import (
    UnstartedRunCancellation,
)
from mission_control.domain.policies.contracts import (
    CancelAction,
    CommandResult,
    CommandStatus,
    LifecycleCommand,
    ReserveBudgetAction,
    RunPhase,
)
from tests.support.boundary_commands import TARGET, ScriptedTransport, started
from tests.support.run_control import actor, command, request, service

SCOPE = "tenant-1"


def intent(run_key: str) -> ChainIntent:
    chain = uuid4()
    return ChainIntent(
        intent_kind="cancel_run",
        delivery_key=f"cancel:{run_key}",
        request_scope=SCOPE,
        chain_id=chain,
        mission_id=uuid4(),
        run_id=uuid4(),
        run_key=run_key,
        actor_ref=f"chain:{chain}",
        reason="upstream_cancelled",
    )


class Interventions(BoundaryInterventionService):
    """The real intervention service; `crash_once` loses the response after acceptance and
    `race_once` lets a concurrent operator command move the run version first."""

    def __init__(self, run_control: RunControlService, transport: ScriptedTransport) -> None:
        super().__init__(run_control, BoundaryCommandDeliveryService(run_control, transport))
        self.run_control = run_control
        self.commands: list[LifecycleCommand] = []
        self.redeliveries = 0
        self.crash_once = False
        self.race_once = False
        self.refuse_with: str | None = None

    async def execute(
        self, command_: LifecycleCommand, *, mailbox_text: str | None = None
    ) -> CommandResult:
        self.commands.append(command_)
        if self.race_once:
            self.race_once = False
            run = await self.run_control.get_run(SCOPE, command_.run_id)
            reserve = ReserveBudgetAction(reservation_id="race", amounts={"tokens.total": 1})
            await self.run_control.execute(command(command_.run_id, run.version, "race", reserve))
        if self.refuse_with is not None:
            # A policy refusal of run control (the in-memory policies admit every cancel).
            run = await self.run_control.get_run(SCOPE, command_.run_id)
            return CommandResult(
                command_id=command_.command_id,
                idempotency_issuer=command_.idempotency_issuer,
                run_id=command_.run_id,
                command_fingerprint="sha256:" + "0" * 64,
                status=CommandStatus.REJECTED,
                resulting_run_version=run.version,
                phase=run.phase,
                reason_code=self.refuse_with,
                reason="refused by policy",
                recorded_at=command_.occurred_at,
            )
        result = await super().execute(command_, mailbox_text=mailbox_text)
        if self.crash_once:
            self.crash_once = False
            raise ConnectionError("accepted before transport interruption")
        return result

    async def redeliver(self, request_scope: str, run_id: str):  # type: ignore[no-untyped-def]
        self.redeliveries += 1
        return await super().redeliver(request_scope, run_id)


async def receiver() -> tuple[RunControlService, Interventions, ScriptedTransport, str]:
    run_control, _ = service()
    run_id = await started(run_control, f"chain-receiver-{uuid4()}", TARGET)
    transport = ScriptedTransport()
    return run_control, Interventions(run_control, transport), transport, run_id


@pytest.mark.asyncio
async def test_accepted_cancel_replays_without_new_command_after_delivery_crash() -> None:
    run_control, interventions, transport, run_id = await receiver()
    interventions.crash_once = True
    release = intent(run_id)
    canceller = RunControlChainCanceller(run_control, interventions)
    with pytest.raises(ConnectionError):
        await canceller.cancel(release)
    await canceller.cancel(release)

    assert len(interventions.commands) == 1
    assert interventions.redeliveries == 1
    command_ = interventions.commands[0]
    assert command_.run_id == run_id
    assert command_.action.kind == "cancel"
    assert command_.actor.actor_id == release.actor_ref
    assert command_.actor.permissions == frozenset({"workflow_run.cancel"})
    assert command_.causation_id == release.delivery_key
    assert (await run_control.get_run(SCOPE, run_id)).phase == RunPhase.CANCELLING
    # Delivered once by the accepting pass, and not again by the redelivery.
    assert transport.deliveries.count(command_.command_id) == 1


@pytest.mark.asyncio
async def test_stale_version_uses_new_identity_then_replays_accepted_command() -> None:
    run_control, interventions, _transport, run_id = await receiver()
    interventions.race_once = True
    version = (await run_control.get_run(SCOPE, run_id)).version
    release = intent(run_id)
    canceller = RunControlChainCanceller(run_control, interventions)
    await canceller.cancel(release)
    await canceller.cancel(release)

    assert len(interventions.commands) == 2
    first, second = (item.command_id for item in interventions.commands)
    assert first.endswith(f":v{version}")
    assert second.endswith(f":v{version + 1}")
    assert interventions.redeliveries == 1
    assert (await run_control.get_run(SCOPE, run_id)).phase == RunPhase.CANCELLING


@pytest.mark.asyncio
async def test_terminal_receiver_never_gets_new_cancellation() -> None:
    run_control, interventions, _transport, _ = await receiver()
    admitted = await run_control.admit(request(request_id=f"chain-terminal-{uuid4()}"))
    assert admitted.run_id is not None
    run_id = admitted.run_id
    # An unstarted receiver cancelled and closed by its owner is terminal.
    run = await run_control.get_run(SCOPE, run_id)
    await run_control.execute(command(run_id, run.version, "cancel", CancelAction()))
    assert await UnstartedRunCancellation(run_control, actor()).close(SCOPE, run_id) == "closed"
    transitions = await run_control.list_transitions(SCOPE, run_id)
    await RunControlChainCanceller(run_control, interventions).cancel(intent(run_id))
    assert interventions.commands == []
    assert await run_control.list_transitions(SCOPE, run_id) == transitions


@pytest.mark.asyncio
async def test_refused_command_is_not_acknowledged() -> None:
    run_control, interventions, transport, run_id = await receiver()
    interventions.refuse_with = "denied"
    with pytest.raises(RuntimeError, match="denied"):
        await RunControlChainCanceller(run_control, interventions).cancel(intent(run_id))
    assert (await run_control.get_run(SCOPE, run_id)).phase == RunPhase.ACTIVE
    assert transport.deliveries == []


@pytest.mark.asyncio
async def test_non_chain_actor_is_refused() -> None:
    run_control, interventions, _transport, run_id = await receiver()
    with pytest.raises(ValueError, match="chain actor"):
        await RunControlChainCanceller(run_control, interventions).cancel(
            intent(run_id).model_copy(update={"actor_ref": "other"})
        )
    assert interventions.commands == []

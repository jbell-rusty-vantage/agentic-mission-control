"""Deliver admitted chain cancellation intents through ordinary governed run control."""

from datetime import UTC, datetime

from mission_control.application.chains.relay import ChainIntent
from mission_control.application.execution.boundary_interventions import BoundaryInterventionService
from mission_control.application.execution.service import RunControlService
from mission_control.application.execution.unstarted_cancellation import UnstartedRunCancellation
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import (
    ActorContext,
    CancelAction,
    CommandStatus,
    LifecycleCommand,
    RunPhase,
)


class RunControlChainCanceller:
    """A released cancellation is an independent run command, never a child cancellation."""

    def __init__(
        self,
        run_control: RunControlService,
        interventions: BoundaryInterventionService,
        unstarted: UnstartedRunCancellation | None = None,
    ) -> None:
        self._run_control = run_control
        self._interventions = interventions
        self._unstarted = unstarted

    async def cancel(self, intent: ChainIntent) -> None:
        if intent.intent_kind != "cancel_run" or intent.actor_ref != f"chain:{intent.chain_id}":
            raise ValueError(
                "chain cancellation requires an admitted chain actor and cancel intent"
            )
        issuer = f"chain:{intent.chain_id}"
        key = "chain-cancel:" + sha256_digest(
            {"delivery": intent.delivery_key, "run": intent.run_key, "reason": intent.reason}
        ).removeprefix("sha256:")
        for _ in range(4):
            # An accepted boundary command survives a crash before outbox acknowledgement.
            # Re-deliver it instead of issuing another cancellation at the newer run version.
            commands = await self._run_control.list_boundary_commands(
                intent.request_scope, intent.run_key
            )
            if any(
                status.command.idempotency_issuer == issuer
                and status.command.command_id.startswith(key + ":v")
                and status.command.target_sequence > 0
                for status in commands
            ):
                await self._interventions.redeliver(intent.request_scope, intent.run_key)
                if self._unstarted is not None:
                    await self._unstarted.close(intent.request_scope, intent.run_key)
                return
            run = await self._run_control.get_run(intent.request_scope, intent.run_key)
            if run.phase == RunPhase.TERMINAL:
                return
            result = await self._interventions.execute(
                LifecycleCommand(
                    command_id=f"{key}:v{run.version}",
                    idempotency_issuer=issuer,
                    request_scope=intent.request_scope,
                    run_id=intent.run_key,
                    expected_run_version=run.version,
                    actor=ActorContext(
                        actor_id=intent.actor_ref,
                        authority_refs=frozenset({f"authority:{intent.actor_ref}"}),
                        permissions=frozenset({"workflow_run.cancel"}),
                    ),
                    action=CancelAction(),
                    reason=intent.reason or "Explicit chain upstream cancellation propagation",
                    occurred_at=datetime.now(UTC),
                    correlation_id=f"chain:{intent.chain_id}",
                    causation_id=intent.delivery_key,
                )
            )
            if result.status == CommandStatus.ACCEPTED:
                if self._unstarted is not None:
                    await self._unstarted.close(intent.request_scope, intent.run_key)
                return
            if result.status != CommandStatus.STALE:
                raise RuntimeError(f"chain cancellation refused: {result.reason_code}")
        raise RuntimeError("chain cancellation run version remained stale")

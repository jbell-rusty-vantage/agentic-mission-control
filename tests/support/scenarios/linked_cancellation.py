"""Observe governed cancellation across independent linked runs; never edit run state."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from mission_control.adapters.temporal.boundary_commands import TemporalBoundaryCommandTransport
from mission_control.application.chains.cancellation import RunControlChainCanceller
from mission_control.application.chains.relay import ChainRelayReport
from mission_control.application.execution.boundary_interventions import (
    BoundaryCommandDeliveryService,
    BoundaryInterventionService,
)
from mission_control.domain.policies.contracts import (
    ActorContext,
    CancelAction,
    CommandStatus,
    LifecycleCommand,
)


@dataclass
class LinkedCancellationProbe:
    """Pause actual lifecycle transport after source Goal acceptance, before terminal commit.

    The source Goal terminal activity pauses after genuine accepted-obligation commits.
    ``pending`` holds start delivery until source cancellation; ``continue`` and
    ``propagate`` pause the consumer's saved cognition before ordinary settlement.
    The runner authors cancel_downstream only for ``propagate``, composes ``canceller``,
    and accepts cancelled terminal roots rather than the positive fixture's all-completed rule.
    """

    mode: str
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    source_entered: asyncio.Event = field(default_factory=asyncio.Event)
    source_release: asyncio.Event = field(default_factory=asyncio.Event)
    source_terminal_request: dict[str, Any] | None = None
    requested: bool = False
    verified: bool = False
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    commands: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        assert self.mode in {"pending", "continue", "propagate"}

    def install(self, lane: Any, monkeypatch: Any, script: Any) -> None:
        from mission_control.application.programs.service import RunControlLifecycleGateway

        execute = RunControlLifecycleGateway.execute

        async def pause_terminal(gateway: Any, request: Any) -> Any:
            if (
                request.run_id == script.source_run
                and request.action.get("kind") == "terminalize"
                and request.command_id.startswith("goal:terminalization:")
                and self.source_terminal_request is None
            ):
                self.source_terminal_request = asdict(request)
                self.source_entered.set()
                await self.source_release.wait()
            return await execute(gateway, request)

        monkeypatch.setattr(RunControlLifecycleGateway, "execute", pause_terminal)
        settle = lane.toolset.settle_saved

        async def pause(live: Any, *, fenced: bool = False) -> Any:
            if self.mode != "pending" and ":stage:consume:" in live.operation_id and not fenced:
                self.entered.set()
                await self.release.wait()
            return await settle(live, fenced=fenced)

        lane.toolset.settle_saved = pause

    @staticmethod
    def interventions(stack: Any) -> BoundaryInterventionService:
        from mission_control.bootstrap.technical_api import api

        control = api.state.run_control_service
        return BoundaryInterventionService(
            control,
            BoundaryCommandDeliveryService(control, TemporalBoundaryCommandTransport(stack.client)),
        )

    def canceller(self, stack: Any) -> RunControlChainCanceller:
        from mission_control.application.execution.unstarted_cancellation import (
            UnstartedRunCancellation,
        )
        from mission_control.application.programs.service import orchestration_lifecycle_actor
        from mission_control.bootstrap.technical_api import api

        control = api.state.run_control_service
        return RunControlChainCanceller(
            control,
            self.interventions(stack),
            unstarted=UnstartedRunCancellation(control, orchestration_lifecycle_actor()),
        )

    async def allow_review(
        self,
        stack: Any,
        scope: str,
        run_id: str,
        *,
        source_run: str,
        chain: Any,
        service: Any,
        actor: Any,
    ) -> bool:
        if run_id != source_run:
            return self.mode == "continue" and self.requested and self.release.is_set()
        return True

    async def relay_once(self, relay: Any, scope: str, *, now: datetime) -> ChainRelayReport:
        if self.mode == "pending" and not self.requested:
            return ChainRelayReport()
        return await relay.relay_once(scope, now=now)

    async def snapshot(self, stack: Any, scope: str, runs: dict[str, str]) -> dict[str, Any]:
        from mission_control.adapters.postgres.knowledge.output_contracts import (
            PostgresOutputContractStore,
        )
        from mission_control.adapters.postgres.run_control import canonical as mc
        from mission_control.bootstrap.technical_api import api

        control = api.state.run_control_service
        async with stack.worker_pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            exports = await connection.fetch(
                "SELECT identity,payload,digest FROM mission_control.runtime_document WHERE "
                "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
                "AND contract='linked.export/1' AND payload->>'receiver_run_id'=$4 "
                "ORDER BY identity",
                *args,
                runs["consumer"],
            )
            plans = await connection.fetch(
                "SELECT transfer_plan_id::text,plan_digest FROM mission_control.transfer_plan "
                "WHERE installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
                "AND run_id=$4::uuid AND receiver_position='consume' ORDER BY transfer_plan_id",
                *args,
                runs["consumer"],
            )
        return {
            "linked": {
                "exports": [dict(row) for row in exports],
                "plans": [dict(row) for row in plans],
                "source_outputs": [
                    row.model_dump(mode="json")
                    for row in await PostgresOutputContractStore(
                        stack.worker_pool
                    ).accepted_outputs(scope, runs["source"])
                ],
            },
            "runs": {
                name: (await control.get_run(scope, run_id)).model_dump(mode="json")
                for name, run_id in runs.items()
            },
            "boundary_commands": {
                name: [
                    row.model_dump(mode="json")
                    for row in await control.list_boundary_commands(scope, run_id)
                ]
                for name, run_id in runs.items()
            },
        }

    async def progress(self, stack: Any, scope: str, runs: dict[str, str], script: Any) -> None:
        from mission_control.bootstrap.technical_api import api

        if "consumer" not in runs or not self.source_entered.is_set():
            return
        control = api.state.run_control_service
        if not self.requested:
            if self.mode != "pending" and not self.entered.is_set():
                return
            self.before = await self.snapshot(stack, scope, runs)
            source, consumer = self.before["runs"]["source"], self.before["runs"]["consumer"]
            assert source["phase"] != "terminal", "source must remain live after goal acceptance"
            assert self.before["linked"]["exports"], "cancel only after an actual exact release"
            if self.mode == "pending":
                assert consumer["phase"] == "pending" and not script.consumer.calls
            else:
                assert consumer["phase"] in {"active", "waiting"}
                assert self.before["linked"]["plans"] and script.consumer.reads
            # A stale governed command remains a fact; a new version gets a distinct identity.
            run = await control.get_run(scope, runs["source"])
            command = LifecycleCommand(
                command_id=f"overnight-linked-source-cancel:{runs['source']}:v{run.version}",
                idempotency_issuer="overnight-linked-cancellation",
                request_scope=scope,
                run_id=runs["source"],
                expected_run_version=run.version,
                actor=ActorContext(
                    actor_id="owner", permissions=frozenset({"workflow_run.cancel"})
                ),
                action=CancelAction(),
                reason="Exercise authored independent linked cancellation",
                occurred_at=datetime.now(UTC),
                correlation_id=f"linked-cancel:{runs['source']}",
            )
            result = await self.interventions(stack).execute(command)
            self.commands.append(
                {
                    "command": command.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                }
            )
            if result.status == CommandStatus.STALE:
                return
            assert result.status == CommandStatus.ACCEPTED, result
            self.requested = True
            self.source_release.set()
        source = await control.get_run(scope, runs["source"])
        consumer = await control.get_run(scope, runs["consumer"])
        observed = {
            "source_phase": source.phase.value,
            "consumer_phase": consumer.phase.value,
            "source_outcome": source.terminal_outcome,
            "consumer_outcome": consumer.terminal_outcome,
        }
        if not self.observations or self.observations[-1] != observed:
            self.observations.append(observed)
        if source.phase.value == "terminal":
            assert source.terminal_outcome == "cancelled"
            if self.mode == "continue":
                assert (
                    consumer.phase.value not in {"cancelling", "terminal"} or self.release.is_set()
                )
                self.release.set()
            elif consumer.phase.value in {"cancelling", "terminal"}:
                self.release.set()

    async def verify(self, stack: Any, scope: str, runs: dict[str, str], script: Any) -> None:
        assert self.requested and self.before is not None
        self.after = await self.snapshot(stack, scope, runs)
        source, consumer = self.after["runs"]["source"], self.after["runs"]["consumer"]
        assert source["terminal_outcome"] == "cancelled"
        assert consumer["terminal_outcome"] == (
            "completed" if self.mode == "continue" else "cancelled"
        )
        assert self.before["linked"]["exports"] == self.after["linked"]["exports"]
        if self.mode == "continue":
            assert self.before["linked"]["plans"] == self.after["linked"]["plans"]
            assert not any(
                row["command"]["kind"] == "cancel"
                for row in self.after["boundary_commands"]["consumer"]
            )
        elif self.mode == "pending":
            assert not self.after["linked"]["plans"] and not script.consumer.calls
        else:
            assert any(
                row["command"]["kind"] == "cancel"
                for row in self.after["boundary_commands"]["consumer"]
            )
        self.verified = True

    def evidence(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "requested": self.requested,
            "verified": self.verified,
            "before": self.before,
            "after": self.after,
            "commands": self.commands,
            "observations": self.observations,
            "source_terminal_request": self.source_terminal_request,
        }

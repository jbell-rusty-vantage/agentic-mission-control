"""Fixture probes around ordinary chain ports; all releases and launches remain governed."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from tests.fixtures.overnight_stagegraph_recovery import SavedConsumerRestart

from mission_control.adapters.postgres.chains.exports import PostgresLinkedExports
from mission_control.adapters.postgres.knowledge.output_contracts import PostgresOutputContractStore
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.chains.relay import ChainRelayReport
from mission_control.contracts.identities import mission_root_id


class DeliveryAcknowledgementLost(ConnectionError):
    """Injected transport failure after a real start and before its outbox acknowledgement."""


@dataclass
class LinkedProbe:
    mode: str
    gate_observations: list[dict[str, Any]] = field(default_factory=list)
    starts: list[dict[str, Any]] = field(default_factory=list)
    acknowledgement_lost: bool = False
    lost_delivery_key: str | None = None
    verified: bool = False
    restart: SavedConsumerRestart | None = None
    linked_before: dict[str, Any] | None = None
    linked_after: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        assert self.mode in {"positive", "gate", "duplicate", "restart"}
        if self.mode == "restart":
            self.restart = SavedConsumerRestart()

    def install(self, lane: Any) -> None:
        if self.restart is not None:
            self.restart.install(lane.toolset)

    def store(self, ordinary: Any) -> Any:
        return LostAcknowledgementStore(ordinary, self) if self.mode == "duplicate" else ordinary

    def starter(self, ordinary: Any, stack: Any) -> Any:
        return ObservedStarter(ordinary, self, stack) if self.mode == "duplicate" else ordinary

    async def relay_once(self, relay: Any, scope: str, *, now: datetime) -> ChainRelayReport:
        try:
            return await relay.relay_once(scope, now=now)
        except DeliveryAcknowledgementLost:
            assert self.mode == "duplicate" and self.acknowledgement_lost
            return ChainRelayReport()

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
        if self.mode != "gate" or run_id != source_run or len(self.gate_observations) >= 3:
            return True
        tasks = await service.list(actor, run_id=source_run, lifecycle="open")
        if not tasks:
            return True
        consumer = next(member for member in chain.members if member.mission_key == "consumer")
        assert consumer.run_key is None, "consumer admission must wait for source human acceptance"
        assert all(link.state.value == "armed" for link in chain.chain.links)
        source = await PostgresOutputContractStore(stack.worker_pool).accepted_outputs(
            scope, source_run
        )
        report = next(item for item in source if item.obligation_key == "root.report")
        async with stack.worker_pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            intents = await connection.fetchval(
                "SELECT count(*) FROM mission_control.outbox WHERE installation_id=$1 "
                "AND application_id=$2 AND tenant_id=$3 AND destination_kind='mc.chain.start_run' "
                "AND payload->>'chain_id'=$4",
                *args,
                str(chain.chain.chain_id),
            )
            exports = await connection.fetchval(
                "SELECT count(*) FROM mission_control.runtime_document WHERE installation_id=$1 "
                "AND application_id=$2 AND tenant_id=$3 AND contract='linked.export/1' "
                "AND payload->>'chain_id'=$4",
                *args,
                str(chain.chain.chain_id),
            )
        assert intents == exports == 0
        self.gate_observations.append(
            {
                "source_accepted_revision": report.revision_id,
                "source_report_digest": report.content_digest,
                "open_review_task_ids": [task.human_task_id for task in tasks],
                "review_packet_digests": [task.activation.packet_digest for task in tasks],
                "consumer_run_key": consumer.run_key,
                "start_intents": intents,
                "exports": exports,
            }
        )
        return False

    async def linked_snapshot(self, stack: Any, scope: str, runs: dict[str, str]) -> dict[str, Any]:
        exports = await PostgresLinkedExports(stack.worker_pool).released_for(
            scope, runs["consumer"], "consume"
        )
        outputs = await PostgresOutputContractStore(stack.worker_pool).accepted_outputs(
            scope, runs["source"]
        )
        async with stack.worker_pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            plans = await connection.fetch(
                "SELECT transfer_plan_id::text,plan_digest FROM mission_control.transfer_plan "
                "WHERE "
                "installation_id=$1 AND application_id=$2 AND tenant_id=$3 AND run_id=$4::uuid "
                "AND receiver_position='consume' ORDER BY transfer_plan_id",
                *args,
                runs["consumer"],
            )
            source_effects = await connection.fetch(
                "SELECT effect_key,bound_effect_digest,terminal_receipt_ref,receipt_digest,state "
                "FROM mission_control.knowledge_operation_journal WHERE installation_id=$1 "
                "AND application_id=$2 AND tenant_id=$3 "
                "AND originating_origin#>>'{mission,runId}'=$4 ORDER BY effect_key",
                *args,
                runs["source"],
            )
        return {
            "source_model_calls": [
                row for row in stack.model_log if row["run_id"] == runs["source"]
            ],
            "source_effects": [dict(row) for row in source_effects],
            "exports": [
                {"digest": item.digest, "export": item.model_dump(mode="json")} for item in exports
            ],
            "source_outputs": [item.model_dump(mode="json") for item in outputs],
            "plans": [dict(row) for row in plans],
        }

    async def progress(self, stack: Any, scope: str, runs: dict[str, str], script: Any) -> None:
        if self.restart is None or "consumer" not in runs:
            return
        if self.restart.entered.is_set() and not self.restart.restarted:
            self.linked_before = await self.linked_snapshot(stack, scope, runs)
        await self.restart.progress(stack, scope, runs["consumer"], script.consumer)

    async def verify(self, stack: Any, scope: str, runs: dict[str, str], script: Any) -> None:
        if self.mode == "gate":
            assert len(self.gate_observations) == 3
        elif self.mode == "duplicate":
            assert self.acknowledgement_lost and self.lost_delivery_key
            assert len(self.starts) == 2
            assert [item["receipt"]["already_started"] for item in self.starts] == [False, True]
            assert len({item["root_run_id"] for item in self.starts}) == 1
            assert {item["delivery_key"] for item in self.starts} == {self.lost_delivery_key}
            assert sum(call["tool"] == "report_register" for call in script.source.calls) == 1
            for tool in ("read_file", "knowledge_read", "submit_output"):
                assert sum(call["tool"] == tool for call in script.consumer.calls) == 1
        elif self.restart is not None:
            await self.restart.verify(stack, scope, runs["consumer"], script.consumer)
            self.linked_after = await self.linked_snapshot(stack, scope, runs)
            assert self.linked_before == self.linked_after, (
                "worker replacement changed linked identity"
            )
        self.verified = True

    def evidence(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "verified": self.verified,
            "gate_observations": self.gate_observations,
            "starts": self.starts,
            "acknowledgement_lost": self.acknowledgement_lost,
            "lost_delivery_key": self.lost_delivery_key,
            "restart": None
            if self.restart is None
            else {
                "restarted": self.restart.restarted,
                "before": self.restart.before,
                "after": self.restart.after,
                "linked_before": self.linked_before,
                "linked_after": self.linked_after,
            },
        }


class LostAcknowledgementStore:
    def __init__(self, ordinary: Any, probe: LinkedProbe) -> None:
        self.ordinary, self.probe = ordinary, probe

    async def lease(self, *args: Any, **kwargs: Any) -> Any:
        return await self.ordinary.lease(*args, **kwargs)

    async def mark_failed(self, *args: Any, **kwargs: Any) -> Any:
        return await self.ordinary.mark_failed(*args, **kwargs)

    async def mark_delivered(self, scope: str, key: str, **kwargs: Any) -> None:
        if not self.probe.acknowledgement_lost:
            assert self.probe.starts, "lost acknowledgement must follow a real start receipt"
            self.probe.acknowledgement_lost = True
            self.probe.lost_delivery_key = key
            raise DeliveryAcknowledgementLost(
                "fixture lost outbox delivery ACK after governed start"
            )
        await self.ordinary.mark_delivered(scope, key, **kwargs)


class ObservedStarter:
    def __init__(self, ordinary: Any, probe: LinkedProbe, stack: Any) -> None:
        self.ordinary, self.probe, self.stack = ordinary, probe, stack

    async def start(self, intent: Any) -> Any:
        receipt = await self.ordinary.start(intent)
        root = await self.stack.client.get_workflow_handle(
            mission_root_id(intent.request_scope, intent.run_key)
        ).describe()
        self.probe.starts.append(
            {
                "delivery_key": intent.delivery_key,
                "run_id": intent.run_key,
                "root_run_id": root.run_id,
                "receipt": asdict(receipt),
            }
        )
        return receipt

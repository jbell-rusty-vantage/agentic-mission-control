"""Knowledge gateway and knowledge-lane builders, from test_gateway and test_knowledge_tools.

origin, harness, call, TENANT and TRANSPORTS drive the gateway seam; lane, Lane, RUN,
MISSION and _runtime_invocation build the Deep Agents lane with knowledge tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from mission_control.adapters.deep_agents.knowledge_tools import KnowledgeLaneSupport
from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore
from mission_control.adapters.knowledge.invocation_locator import InMemoryInvocationLocator
from mission_control.adapters.knowledge.memory import (
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    InMemoryLineageStore,
    InMemorySubmissionStore,
)
from mission_control.application.knowledge.access import (
    InvocationAccess,
    RecoveryAccess,
    RecoveryGrant,
)
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.operations import KnowledgeCall
from mission_control.application.knowledge.toolset import KnowledgeToolset, LiveInvocation
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.ports.knowledge import RecordedUseDecision
from mission_control.contracts.knowledge_protocol import Governors, digest_bytes
from mission_control.domain.knowledge.origin import InvocationOrigin
from tests.support.clock import Clock
from tests.support.knowledge.binding import FakeKnowledgeBinding, http_client_over
from tests.support.knowledge.credentials import (
    AUDIENCE,
    BINDING,
    KNOWLEDGE_NOW,
    Issuer,
    RecordingMinter,
    knowledge_port,
)
from tests.support.lane_bindings import lane_fields

INSTALLATION = "00000000-0000-7000-8000-000000000001"
TENANT = "00000000-0000-7000-8000-0000000000aa"


TRANSPORTS = ["direct", "http"]


def origin(attempt: int = 1, **updates: object) -> InvocationOrigin:
    values: dict[str, object] = {
        "issuer": "mission-control",
        "installation_id": INSTALLATION,
        "application_id": "biotech",
        "tenant_id": TENANT,
        "mission_id": "11111111-1111-4111-8111-111111111111",
        "run_id": "22222222-2222-4222-8222-222222222222",
        "activation_id": "33333333-3333-4333-8333-333333333333",
        "operation_id": "op-research-1",
        "attempt": attempt,
        "generation": 1,
        "lane": "deep_agents",
        **updates,
    }
    return InvocationOrigin.model_validate(values)


@dataclass
class Harness:
    clock: Clock
    issuer: Issuer
    minter: RecordingMinter
    client: FakeKnowledgeBinding
    journal: InMemoryKnowledgeJournal
    handles: InMemoryKnowledgeHandleStore
    gateway: KnowledgeGateway
    sleeps: list[float]

    def access(
        self, attempt: int = 1, grant: RecoveryGrant | None = None, invocation: str = "inv-0001"
    ) -> InvocationAccess:
        return InvocationAccess(
            origin=origin(attempt),
            subject="mission-control-runtime",
            invocation_id=invocation,
            authenticated_at=self.clock.now,
            recovery_grant=grant,
        )

    def recovery(self, issuer: str = "mission-control") -> RecoveryAccess:
        return RecoveryAccess(
            installation_id=INSTALLATION,
            application_id="biotech",
            tenant_id=TENANT,
            issuer=issuer,
            subject="mission-control-reconciler",
            authority_ref="recovery-grant-7",
            invocation_id="inv-0009",
            authenticated_at=self.clock.now,
        )

    async def transitions(self, effect_key: str) -> list[tuple[object, object]]:
        return list(await self.journal.transitions(self.access().scope, effect_key))


def harness(transport: str = "direct", max_polls: int = 3, **drift: object) -> Harness:
    clock = Clock(KNOWLEDGE_NOW)
    issuer = Issuer(clock=clock)
    minter = RecordingMinter(issuer.minter(), drift=dict(drift))
    fake = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    journal = InMemoryKnowledgeJournal()
    handles = InMemoryKnowledgeHandleStore()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = fake if transport == "direct" else http_client_over(fake, sleep=sleep)
    gateway = KnowledgeGateway(
        client=client,
        journal=journal,
        handles=handles,
        minter=minter,
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        max_polls=max_polls,
        clock=clock,
        sleep=sleep,
    )
    return Harness(clock, issuer, minter, fake, journal, handles, gateway, sleeps)


def call(payload: object | None = None, **updates: object) -> KnowledgeCall:
    values: dict[str, object] = {
        "operation": "knowledge.apply",
        "capability_pin": "ai-engineer.research@1:knowledge.apply",
        "native_contract": {"name": "knowledge-ingestion-intent", "version": "v1"},
        "payload": {"intent": "add", "claims": ["c-1"]} if payload is None else payload,
        "governors": Governors(
            deadline="2026-10-24T20:10:00Z",
            maxItems=64,
            partialResults="forbid",
            budget={"calls": 10, "tokens": 1000, "costUsd": "0.50"},
        ),
        **updates,
    }
    return KnowledgeCall.model_validate(values)


RUN = "22222222-2222-4222-8222-222222222222"
# Provenance slice 1: the run's ledger mission and the activation row of its runtime unit.
MISSION = "44444444-4444-4444-8444-444444444444"
UNIT = "unit:stage/draft"
ACTIVATION = "55555555-5555-4555-8555-555555555555"


@dataclass
class Lane:
    clock: Clock
    fake: FakeKnowledgeBinding
    journal: InMemoryKnowledgeJournal
    store: InMemorySubmissionStore
    minter: RecordingMinter
    support: KnowledgeLaneSupport
    toolset: KnowledgeToolset
    decisions: InMemoryUseDecisionStore
    sleeps: list[float]
    locator: InMemoryInvocationLocator

    def live(self, attempt: int = 1, generation: int = 1) -> LiveInvocation:
        """The located live attempt (the ids the locator resolves for RUN and UNIT)."""

        return LiveInvocation(
            request_scope=f"mc/{INSTALLATION}/biotech/{TENANT}",
            run_id=RUN,
            operation_id="stage/draft",
            operation_attempt=attempt,
            execution_generation=generation,
            lane="deep_agents",
            obligations=("report",),
            mission_id=MISSION,
            activation_id=ACTIVATION,
            unit_key=UNIT,
        )

    async def decide(self, name: str) -> str:
        """The host records an exact use decision (a trusted step); the agent gets its handle."""

        handle = f"kh:{BINDING}/decision/{name}@use-decision.v1"
        await self.decisions.record(
            self.toolset.access(self.live()).scope,
            RecordedUseDecision(
                handle=handle,
                binding_id=BINDING,
                tenant_id=TENANT,
                use_decision_id=name,
                bound_effect_digest=digest_bytes(name.encode()),
                processed_epoch=0,
                plan={
                    "schemaVersion": "knowledge-ingestion-intent.v1",
                    "intentId": name,
                    "context": {"tenantId": TENANT},
                    "proposals": [{"kind": "claim.add", "claim": name}],
                },
                normalized_values_digest=digest_bytes(b"normalized"),
            ),
        )
        return handle

    async def call(self, name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
        message = await self.support.tools[name].ainvoke(
            {"name": name, "args": args, "id": call_id, "type": "tool_call"}
        )
        return json.loads(message.content)


def lane() -> Lane:
    clock = Clock(KNOWLEDGE_NOW, step=timedelta(milliseconds=1))
    issuer = Issuer(clock=clock)
    fake = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    journal = InMemoryKnowledgeJournal()
    minter = RecordingMinter(issuer.minter())

    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    decisions = InMemoryUseDecisionStore()
    gateway = KnowledgeGateway(
        client=fake,
        journal=journal,
        handles=InMemoryKnowledgeHandleStore(),
        minter=minter,
        content=fake,
        decisions=decisions,
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        clock=clock,
        sleep=sleep,
    )
    store = InMemorySubmissionStore()
    locator = InMemoryInvocationLocator({RUN: MISSION}, {(RUN, UNIT): ACTIVATION})
    toolset = KnowledgeToolset(
        gateway=gateway,
        submissions=SubmissionService(store, assessor=gateway, clock=clock),
        issuer="mission-control",
        clock=clock,
        lineage=InMemoryLineageStore(),
        sleep=sleep,
        locator=locator,
    )
    return Lane(
        clock,
        fake,
        journal,
        store,
        minter,
        KnowledgeLaneSupport(toolset),
        toolset,
        decisions,
        sleeps,
        locator,
    )


def _runtime_invocation(live: LiveInvocation, *, tool_names: tuple[str, ...]) -> Any:
    deep = SimpleNamespace(
        execution_generation=live.execution_generation,
        tools=tuple(SimpleNamespace(tool_name=name) for name in tool_names),
    )
    return SimpleNamespace(
        binding=SimpleNamespace(
            request_scope=live.request_scope,
            run_id=live.run_id,
            operation_id=live.operation_id,
            operation_attempt=live.operation_attempt,
            transfer=None,
            runtime_unit=None if live.unit_key is None else SimpleNamespace(unit_key=live.unit_key),
            **lane_fields(deep),
        )
    )

"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_native_write.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.judgment import UseSpec
from mission_control.application.knowledge.native_write import (
    ClaimMaterializeIntentBuilder,
    NativePlanDigest,
    NativeWriteService,
)
from mission_control.application.knowledge.trusted_settlement import TrustedPlan
from mission_control.contracts.knowledge_assessment import DecisionResolution
from mission_control.contracts.knowledge_protocol import Ref
from mission_control.domain.knowledge.judgment import CognitionIdentity
from tests.support.knowledge.gateway import TENANT
from tests.support.unit.outputs.w1_d28_d29 import (
    HANDLE,
    bridge_judges,
    make_stack,
    report_candidate,
    report_promise,
)
from tests.unit.outputs.scenario import digest_of

BINDING = "aiengineer-postgres"
RUN_DECISION = "ud-run-77-0123456789abcdef"
DIGEST = digest_of("r1")


def ref(kind: str, item: str, version: str = "research-core.record.v1") -> Ref:
    return Ref(
        kind=kind, id=item, version=version, digest=digest_of(item), tenant=TENANT, binding=BINDING
    )


def resolution(decision: Ref, *, pending: bool, admitted: bool = True) -> DecisionResolution:
    return DecisionResolution.model_validate(
        {
            "schema": "use-decision-resolution.v1",
            "requested": decision.model_dump(mode="json"),
            "current": decision.model_dump(mode="json"),
            "chain": [decision.model_dump(mode="json")],
            "report": ref("report", "w1-aie-s10-r1", "research-report.v2")
            .model_copy(update={"digest": DIGEST})
            .model_dump(mode="json"),
            "subject": ref("report", "w1-aie-s10-r1", "research-report.v2")
            .model_copy(update={"digest": DIGEST})
            .model_dump(mode="json"),
            "use": "engineering_reference.model_facts",
            "audience": "official",
            "useClass": "official",
            "disposition": "admitted" if admitted else "rejected",
            "conditions": ["review_required"] if pending else [],
            "admissibility": {
                "status": "held" if pending else ("admitted" if admitted else "rejected"),
                "reason": "review_required" if pending else None,
            },
            "reviewPending": pending,
            "reviewer": None,
            "judgment": [],
            "revocationEpoch": 3,
            "checkedAt": "2026-10-29T09:00:00Z",
            "runId": "run-77",
        }
    )


@dataclass
class Bridge:
    store: InMemoryUseDecisionStore
    pending: bool = False
    decided: list[dict[str, Any]] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)

    def decision(self, bound: str) -> Ref:
        return ref("use_decision", "ud-native-" + bound[7:23], "research-core.use_decision.v2")

    async def decide_native_plan(self, host, report, use, **kwargs):  # type: ignore[no-untyped-def]
        self.decided.append({"report": report.id, "use": use.use} | kwargs)
        decision = self.decision(kwargs["bound_effect_digest"])
        return decision, resolution(decision, pending=self.pending)

    async def resolve(self, access, decision, *, attempt, fresh=False):  # type: ignore[no-untyped-def]
        self.resolved.append(decision.id)
        return resolution(decision, pending=self.pending and decision.id != RUN_DECISION)

    async def record_apply_decision(self, access, decision):  # type: ignore[no-untyped-def]
        return await self.store.record(access.scope, decision)


class Plans:
    async def plan(self, access: InvocationAccess, revision: Any) -> TrustedPlan:
        return TrustedPlan(
            evaluators=(),
            use=UseSpec(
                use="engineering_reference.model_facts",
                audience="official",
                policy=ref("policy", "p"),
                rubric=ref("rubric", "r"),
            ),
            producer=CognitionIdentity(
                credential_ref="p", subject="s", operation_ref="op", vendor="anthropic"
            ),
        )


class Reports:
    async def resolve(self, item: Any, access: Any, *, purpose: str) -> Any:
        assert item.ref == HANDLE and item.digest == DIGEST and purpose == "official"
        members = [
            SimpleNamespace(record={"id": "w1-asr-1", "proposition": "Model A has 7B params."}),
            SimpleNamespace(record={"id": "w1-asr-2", "proposition": "Model B has 70B params."}),
        ]
        return SimpleNamespace(package=SimpleNamespace(assertions=members))


@dataclass
class Preview:
    calls: list[tuple[dict[str, Any], str]] = field(default_factory=list)

    async def preview(self, plan, *, effect_key, access):  # type: ignore[no-untyped-def]
        self.calls.append((dict(plan), effect_key))
        return NativePlanDigest(
            semantic_payload_digest=digest_of("payload"),
            bound_effect_digest=digest_of("bound-" + access.invocation_ref),
            normalized_values_digest=digest_of("values"),
            processed_epoch=5,
        )


async def accepted_report() -> Any:
    stack = await make_stack(report_promise())
    ack = await stack.submit("k1", "root.report", report_candidate(), position="root")
    revision = ack.revisions[0]
    await bridge_judges(stack, revision.revision_id, revision.content_digest, "pass", RUN_DECISION)
    await stack.accept(ack, "root.report")
    return stack


def service(stack: Any, bridge: Bridge, *, builder: Any = None, preview: Any = None) -> Any:
    return NativeWriteService(
        bridge=bridge,  # type: ignore[arg-type]
        plans=Plans(),
        outputs=stack.store,
        reports=Reports(),  # type: ignore[arg-type]
        port=SimpleNamespace(  # type: ignore[arg-type]
            binding_id=BINDING,
            apply_contract_name="knowledge-ingestion-intent",
            apply_contract_version="v1",
        ),
        builder=builder or ClaimMaterializeIntentBuilder("knowledge-ingestion-intent.v1"),
        preview=preview or Preview(),
        decisions=bridge.store,
    )


class Applier:
    def __init__(self) -> None:
        self.handles: list[str] = []

    async def __call__(self, handle: str) -> str:
        self.handles.append(handle)
        return f"applied:{handle}"


PLAN = {HANDLE: DIGEST}

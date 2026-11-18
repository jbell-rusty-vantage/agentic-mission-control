"""Builders, constants and fakes that other test files import.

Moved from tests/unit/outputs/test_w1_d28_d29.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.fulfillment import (
    AssessmentInput,
    HostAccess,
    TrustedReferenceUses,
)
from mission_control.domain.knowledge.judgment import TRUSTED_BRIDGE_ACTOR, decision_evidence
from mission_control.domain.outputs.contracts import (
    CandidateRef,
    OutputForm,
    OutputObligation,
    Requirement,
)
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.support.knowledge.gateway import origin
from tests.unit.outputs.scenario import Stack, build_stack, digest_of, obligation

AT = datetime(2026, 10, 29, 9, tzinfo=UTC)
PIN = "knowledge.report.assess@1"
HANDLE = "kh:aiengineer-postgres/report/w1-aie-s10-r1@research-report.v2"


def invocation() -> InvocationAccess:
    return InvocationAccess(
        origin=origin(1),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=AT,
    )


def report_promise() -> OutputObligation:
    return obligation(
        "root.report",
        OutputForm.REFERENCE,
        position="root",
        requirements=(Requirement(key="assessed", validator=PIN),),
    )


def report_candidate(digest: str = digest_of("r1")) -> CandidateRef:
    return CandidateRef(
        deliverable_id="report", form=OutputForm.REFERENCE, kind="handle", ref=HANDLE, digest=digest
    )


class Lineage:
    async def successor_chain(self, decision_evidence: str) -> tuple[str, ...]:
        held = decision_evidence.removeprefix("ks-use-decision:").split("@", 1)[0]
        return (held, f"{held}-adjudicated", f"{held}-revoked")


def bridge(stack: Stack) -> HostAccess:
    return HostAccess(
        scope=stack.host.scope,
        actor_ref=TRUSTED_BRIDGE_ACTOR,
        origin_ref="ks:aiengineer-postgres/use_decision/ud-1",
        role="assessor",
    )


async def bridge_judges(
    stack: Stack, revision_id: str, digest: str, result: str, decision: str, *, supersedes=None
) -> Any:  # type: ignore[no-untyped-def]
    receipt = await stack.outputs.record_assessment(
        bridge(stack),
        AssessmentInput(
            run_id=stack.run_id,
            subject_kind="output_revision",
            subject_id=revision_id,
            subject_digest=digest,
            requirement_results={"assessed": result},  # type: ignore[dict-item]
            method_pin=PIN,
            policy_pin="policy@1",
            evidence_refs=(decision_evidence(decision, digest),),
            supersedes=supersedes,
        ),
        lineage=Lineage(),
    )
    assert receipt.status == "recorded", receipt.error
    return receipt.assessment


async def make_stack(*items: OutputObligation) -> Stack:
    store = InMemoryOutputContractStore()
    stack = await build_stack(store, store.submissions, invocation(), *items)
    stack.outputs._reference_uses = TrustedReferenceUses(store)
    return stack

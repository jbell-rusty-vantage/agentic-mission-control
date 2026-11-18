"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_independent_evaluators.py.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mission_control.adapters.deep_agents.evaluators import AssertionVerdict as Verdict
from mission_control.adapters.deep_agents.evaluators import CallUsage
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.evaluator_plans import (
    PRODUCER_CREDENTIAL,
    ConfiguredTrustedPlans,
    EvaluationContext,
    RolePin,
)
from mission_control.application.knowledge.judgment import JudgmentSubject, UseSpec
from mission_control.contracts.knowledge_protocol import Ref
from mission_control.domain.knowledge.judgment import CognitionIdentity
from mission_control.domain.outputs.contracts import ExactOutput
from tests.support.knowledge.gateway import TENANT, origin

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
JUDGE = RolePin("judge.default", "openai", "gpt-5.6-terra", "tool_forced", "responses")
AUDITOR = RolePin("auditor.default", "anthropic", "claude-haiku-5-5", "tool_forced")
DIGEST = "sha256:" + "a" * 64
BODY = "## Findings\n\nThe trial enrolled 120 adults — all completed.\n"
BODY_DIGEST = "sha256:" + hashlib.sha256(BODY.encode()).hexdigest()


def ref(kind: str, item: str, digest: str = DIGEST) -> Ref:
    return Ref(
        kind=kind,  # type: ignore[arg-type]
        id=item,
        version=f"research-core.{kind}.v2",
        digest=digest,
        tenant=TENANT,
        binding="biotech-graph",
    )


REPORT = ref("report", "report-1")


def use() -> UseSpec:
    return UseSpec(
        use="knowledge_ingestion.report",
        audience="official",
        policy=ref("policy", "policy-1"),
        rubric=ref("rubric", "rubric-1"),
    )


def assertion_member() -> dict[str, Any]:
    return {
        "handle": ref("assertion", "a-1").model_dump(mode="json"),
        "record": {"statement": "120 adults enrolled"},
        "qualifiersDigest": "sha256:" + "c" * 64,
    }


def support_member() -> dict[str, Any]:
    return {
        "handle": ref("support_set", "s-1").model_dump(mode="json"),
        "record": {"assertion": ref("assertion", "a-1").model_dump(mode="json")},
    }


@dataclass
class Context:
    value: EvaluationContext
    loads: list[str] = field(default_factory=list)

    async def load(self, evaluator: Any, report: Ref) -> EvaluationContext:
        self.loads.append(evaluator.role)
        return self.value


def context(**updates: Any) -> Context:
    values: dict[str, Any] = {
        "report": REPORT,
        "body_artifact": ref("artifact", "body-1", BODY_DIGEST),
        "body_text": BODY,
        "assertions": (assertion_member(),),
        "fragments": (
            {"handle": ref("fragment", "f-1").model_dump(mode="json"), "record": {"text": "120"}},
        ),
        "support_sets": (support_member(),),
        "units": (),
        "use": use(),
        **updates,
    }
    return Context(EvaluationContext(**values))


def producer_access() -> InvocationAccess:
    return InvocationAccess(
        origin=origin(),
        subject="mission-control-runtime",
        invocation_id="inv-producer",
        authenticated_at=NOW,
    )


def revision() -> ExactOutput:
    return ExactOutput(
        revision_id="rev-1",
        run_id="22222222-2222-4222-8222-222222222222",
        obligation_key="draft.report",
        obligation_revision=1,
        deliverable_id="draft.report",
        revision=1,
        form="reference",  # type: ignore[arg-type]
        content_digest=DIGEST,
        candidate={"kind": "handle", "ref": "kh:biotech-graph/report/report-1@x.v2"},
        producer_origin_ref="op-research-1",
    )


def plans(source: Context) -> ConfiguredTrustedPlans:
    return ConfiguredTrustedPlans(
        producer_vendor="anthropic",
        judge=JUDGE,
        auditor=AUDITOR,
        context=source,
        report_of=lambda _revision, _tenant: REPORT,
        clock=lambda: NOW,
    )


async def bindings() -> tuple[Any, Any]:
    plan = await plans(context()).plan(producer_access(), revision())
    return plan.evaluators[0], plan.evaluators[1]


def subject() -> JudgmentSubject:
    producer = CognitionIdentity(
        PRODUCER_CREDENTIAL, "mission-control-runtime", "op-research-1", "anthropic"
    )
    return JudgmentSubject(
        run_id="run", revision=revision(), report=REPORT, producer=producer, generation=1
    )


class Invoker:
    """A fake Deep Agents run: a queue of answers, each with its token usage."""

    def __init__(self, *answers: Any, usage: tuple[int, int] = (1000, 200)) -> None:
        self.answers = list(answers)
        self.usage = usage
        self.calls: list[str] = []

    async def __call__(self, evaluator: Any, prompt: str, body: str, schema: Any) -> Any:
        self.calls.append(evaluator.role)
        return self.answers.pop(0), CallUsage((self.usage,))


def verdict(**updates: Any) -> Verdict:
    values: dict[str, Any] = {
        "assertion": 0,
        "attribution": "correct",
        "support": "full_support",
        "cited_fragments": ["f-1"],
        "rationale": "the fragment states it",
        **updates,
    }
    return Verdict(**values)

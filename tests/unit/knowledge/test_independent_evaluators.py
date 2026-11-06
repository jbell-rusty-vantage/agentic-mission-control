"""OVE-169: production independent evaluators (plans, Deep Agents runner, pricing, composition).

Deterministic: the agent is a fake invoker (the production invoker is checked to build a Deep
Agents agent with a structured response and no tools), KS is not called. Proves separate evaluator
identities and credential names, the auditor-first order, the KS evaluation context bound to the
exact revision and role, complete judge batches (retried, never partial), the KS wire shapes
(attribution + support observations; census occurrences with UTF-16 spans), catalog pricing with
long-prompt tiers, and the startup refusals of the composition.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
from pydantic import SecretStr

from mission_control.adapters.deep_agents import evaluators
from mission_control.adapters.deep_agents.evaluators import AssertionVerdict as Verdict
from mission_control.adapters.deep_agents.evaluators import (
    AuditorAnswer,
    CallUsage,
    FoundClaim,
    JudgeAnswer,
    ModelEvaluatorRunner,
    Price,
    context_from_document,
    usage_document,
    utf16_offset,
)
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.evaluator_plans import (
    AUDITOR_CREDENTIAL,
    JUDGE_CREDENTIAL,
    PRODUCER_CREDENTIAL,
    ConfiguredTrustedPlans,
    EvaluationContext,
    RolePin,
    family_of,
)
from mission_control.application.knowledge.judgment import (
    EvaluatorUnavailable,
    JudgmentSubject,
    TrustedJudgmentRefused,
    UseSpec,
)
from mission_control.bootstrap.settings import Settings
from mission_control.bootstrap.trusted_judgment import (
    TrustedCompositionError,
    compose_trusted_settlement,
)
from mission_control.contracts.knowledge_protocol import Ref
from mission_control.domain.knowledge.judgment import (
    CognitionIdentity,
    EvaluatorPin,
    evaluator_refusals,
)
from mission_control.domain.outputs.contracts import ExactOutput
from tests.unit.knowledge.test_gateway import TENANT, origin

pytestmark = pytest.mark.asyncio
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
JUDGE = RolePin("judge.default", "openai", "gpt-5.6-terra", "tool_forced", "responses")
AUDITOR = RolePin("auditor.default", "anthropic", "claude-haiku-5-5", "tool_forced")
DIGEST = "sha256:" + "a" * 64
BODY = "## Findings\n\nThe trial enrolled 120 adults — all completed.\n"
BODY_DIGEST = "sha256:" + hashlib.sha256(BODY.encode()).hexdigest()
PRICES = {"gpt-5.6-terra": Price(2.0, 12.0), "claude-haiku-5-5": Price(0.1, 0.5)}


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


async def test_plans_admit_separate_independent_evaluators_auditor_first() -> None:
    source = context()
    plan = await plans(source).plan(producer_access(), revision())
    auditor, judge = plan.evaluators
    assert (auditor.role, judge.role) == ("auditor", "judge")
    assert plan.producer.credential_ref == PRODUCER_CREDENTIAL and plan.use == use()
    assert {auditor.credential_ref, judge.credential_ref} == {AUDITOR_CREDENTIAL, JUDGE_CREDENTIAL}
    assert len({auditor.access.subject, judge.access.subject, plan.producer.subject}) == 3
    assert auditor.access.origin.operation_id == "op-research-1/auditor"
    pin = EvaluatorPin(profile="judge.default", vendor="openai", model_id="gpt-5.6-terra")
    for evaluator in plan.evaluators:
        refusals = evaluator_refusals(
            plan.producer, evaluator.identity(), role=evaluator.role, judge_pin=pin
        )
        assert refusals == ()
    assert (judge.family, auditor.family) == (family_of("gpt-5.6-terra"), "claude-haiku")
    assert source.loads == ["auditor"]  # the context is read under the evaluator's own grant


async def test_plans_wait_without_the_ks_use_and_refuse_a_shared_credential_name() -> None:
    with pytest.raises(EvaluatorUnavailable, match="EVALUATION_CONTEXT_INCOMPLETE"):
        await plans(context(use=None)).plan(producer_access(), revision())
    with pytest.raises(ValueError, match="EVALUATOR_CREDENTIAL_SHARED"):
        ConfiguredTrustedPlans(
            producer_vendor="anthropic",
            judge=JUDGE,
            auditor=AUDITOR,
            context=context(),
            report_of=lambda *_: REPORT,
            auditor_credential=PRODUCER_CREDENTIAL,
        )


async def test_the_judge_emits_attribution_and_support_with_catalog_cost() -> None:
    invoke = Invoker(JudgeAnswer(verdicts=[verdict(cited_fragments=["f-1", "nope"])]))
    prices = {"gpt-5.6-terra": Price(2.0, 12.0, ((272_000, 4.0, 18.0),))}
    runner = ModelEvaluatorRunner(
        context=context(), invoke=invoke, prices=prices, clock=lambda: NOW
    )
    _auditor, judge = await bindings()
    output = await runner.evaluate(judge, subject())
    assert invoke.calls == ["judge"] and output.census is None
    attribution, support = output.observations
    assert attribution["property"] == "attribution" and attribution["target"]["id"] == "a-1"
    assert support["property"] == "support" and support["target"]["id"] == "s-1"
    assert support["outcome"]["verdict"] == "full_support"
    assert [item["id"] for item in support["outcome"]["citedFragments"]] == ["f-1"]
    assert support["qualifiersDigest"] == assertion_member()["qualifiersDigest"]
    identity = support["evaluator"]
    assert (identity["kind"], identity["provider"], identity["family"]) == (
        "model",
        "openai",
        "gpt-5.6",
    )
    # 1000 in x $2 + 200 out x $12 per million = $0.0044, carried once.
    assert attribution["usage"] == {"providerCalls": 1, "tokens": 1200, "costUsd": "0.0044"}
    assert (
        support["usage"]["costUsd"] == "0" and attribution["recordedAt"] == "2026-10-28T12:00:00Z"
    )


async def test_an_incomplete_or_invalid_judge_batch_is_retried_then_waits() -> None:
    """S2: a partial batch would lock the judge role at KS; it is never observed. W1 D23: one
    evaluation is one agent run; the incomplete answer raises a billed wait naming the problem
    and the bridge's bounded retry runs the next evaluation."""

    second = JudgeAnswer(verdicts=[verdict()])
    invoke = Invoker(JudgeAnswer(verdicts=[]), second)
    runner = ModelEvaluatorRunner(prices=PRICES, context=context(), invoke=invoke)
    _auditor, judge = await bindings()
    with pytest.raises(EvaluatorUnavailable, match="do not cover every assertion") as first:
        await runner.evaluate(judge, subject())
    assert first.value.billed and invoke.calls == ["judge"]
    output = await runner.evaluate(judge, subject())
    assert len(output.observations) == 2 and invoke.calls == ["judge", "judge"]
    invalid = JudgeAnswer(verdicts=[verdict(support="contradiction", contradicting_fragments=[])])
    stuck = ModelEvaluatorRunner(prices=PRICES, context=context(), invoke=Invoker(invalid, invalid))
    with pytest.raises(EvaluatorUnavailable, match="contradiction names no fragment"):
        await stuck.evaluate(judge, subject())


async def test_the_auditor_waits_without_units_before_any_agent_run() -> None:
    invoke = Invoker()
    runner = ModelEvaluatorRunner(prices=PRICES, context=context(units=()), invoke=invoke)
    auditor, _judge = await bindings()
    with pytest.raises(EvaluatorUnavailable, match="the census needs units"):
        await runner.evaluate(auditor, subject())
    assert invoke.calls == []


async def test_the_auditor_census_locates_quotes_in_utf16_units() -> None:
    quote = "120 adults — all completed"
    at = BODY.index(quote)
    paragraph = (
        "s1/p1",
        utf16_offset(BODY, BODY.index("The trial")),
        utf16_offset(BODY, len(BODY) - 1),
    )
    answer = AuditorAnswer(
        claims=[FoundClaim(quote=quote, assertion=0), FoundClaim(quote="not in the body")],
        rationale="one factual claim",
    )
    runner = ModelEvaluatorRunner(
        prices=PRICES,
        context=context(units=(("s1/h", 0, 11), paragraph), support_sets=None, fragments=()),
        invoke=Invoker(answer),
    )
    auditor, _judge = await bindings()
    output = await runner.evaluate(auditor, subject())
    assert output.observations == () and output.census is not None
    (occurrence,) = output.census["occurrences"]
    assert occurrence["blockPath"] == "s1/p1" and occurrence["assertion"]["id"] == "a-1"
    assert occurrence["span"] == {
        "basis": "utf16-code-units-v1",
        "start": at,
        "end": at + len(quote),
    }
    assert occurrence["quoteDigest"] == "sha256:" + hashlib.sha256(quote.encode()).hexdigest()
    assert any("not in the body" in item for item in output.census["limitations"])
    assert utf16_offset("a\U0001f600b", 2) == 3  # an astral character is two UTF-16 units


def test_pricing_uses_the_long_prompt_tier_and_six_decimals() -> None:
    price = Price(2.0, 12.0, ((272_000, 4.0, 18.0),))
    assert price.cost(272_000, 0) == Decimal("0.544")
    assert price.cost(272_001, 1_000) == Decimal(272_001 * 4 + 1_000 * 18) / Decimal(1_000_000)
    two_calls = usage_document(CallUsage(((1, 1), (2, 2))), Price(0.1, 0.5))
    assert two_calls == {"providerCalls": 2, "tokens": 6, "costUsd": "0.000002"}
    assert usage_document(CallUsage(()), None)["costUsd"] == "0"


def test_the_ks_context_must_bind_the_exact_revision_and_role() -> None:
    document: dict[str, Any] = {
        "schema": "research-evaluation-context.v1",
        "report": REPORT.model_dump(mode="json"),
        "role": "auditor",
        "task": {
            "use": "knowledge_ingestion.report",
            "audience": "official",
            "policy": ref("policy", "policy-1").model_dump(mode="json"),
            "rubric": ref("rubric", "rubric-1").model_dump(mode="json"),
        },
        "body": {
            "artifact": ref("artifact", "b", BODY_DIGEST).model_dump(mode="json"),
            "digest": BODY_DIGEST,
            "text": BODY,
        },
        "units": [
            {"path": "s1/p1", "span": {"start": 0, "end": 5}},
            {"path": "s1/t", "span": None},
        ],
        "assertions": [assertion_member()],
        "supportSets": None,
        "evidence": None,
    }
    loaded = context_from_document(document, REPORT, "auditor")
    assert (
        loaded.units == (("s1/p1", 0, 5),) and loaded.support_sets is None and loaded.use == use()
    )
    for audience in ("internal", "official"):
        exact = {**document, "task": {**document["task"], "audience": audience}}
        loaded_use = context_from_document(exact, REPORT, "auditor").use
        assert loaded_use is not None and loaded_use.audience == audience
    for invalid_audience in (None, "", 42, "Official", "bad audience", "a" * 121):
        invalid = {**document, "task": {**document["task"], "audience": invalid_audience}}
        with pytest.raises(EvaluatorUnavailable, match="exact task audience"):
            context_from_document(invalid, REPORT, "auditor")
    missing = {**document, "task": {k: v for k, v in document["task"].items() if k != "audience"}}
    with pytest.raises(EvaluatorUnavailable, match="exact task audience"):
        context_from_document(missing, REPORT, "auditor")
    with pytest.raises(EvaluatorUnavailable):
        context_from_document(document, REPORT, "judge")  # another role's context
    tampered = {**document, "body": {**document["body"], "text": BODY + "x"}}
    with pytest.raises(EvaluatorUnavailable):
        context_from_document(tampered, REPORT, "auditor")


async def test_the_production_invoker_is_a_deep_agent_with_a_structured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class Agent:
        async def ainvoke(self, state: Any, config: Any) -> Any:
            seen["config"] = config

            class Message:
                usage_metadata = {"input_tokens": 10, "output_tokens": 5}

            return {"messages": [Message()], "structured_response": JudgeAnswer(verdicts=[])}

    def create_deep_agent(**kwargs: Any) -> Agent:
        seen.update(kwargs)
        return Agent()

    import deepagents

    monkeypatch.setattr(deepagents, "create_deep_agent", create_deep_agent)
    monkeypatch.setattr(evaluators, "chat_model", lambda evaluator, credentials: "model")
    _auditor, judge = await bindings()
    invoke = evaluators.deep_agents_invoker({JUDGE_CREDENTIAL: "k"})
    parsed, usage = await invoke(judge, "prompt", "body", JudgeAnswer)
    assert isinstance(parsed, JudgeAnswer) and usage.calls == ((10, 5),)
    # W1 D16: the judge row's declared strategy wraps the schema (never a raw schema).
    strategy = seen["response_format"]
    assert seen["tools"] == [] and seen["subagents"] == []
    # D18 review: the tool validates through the coercing subclass (same JSON Schema).
    assert isinstance(strategy, ToolStrategy) and issubclass(strategy.schema, JudgeAnswer)
    assert strategy.schema.model_json_schema() == JudgeAnswer.model_json_schema()
    assert (
        seen["model"] == "model" and seen["config"]["recursion_limit"] == evaluators.RECURSION_LIMIT
    )


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("tool_forced", ToolStrategy),
        ("provider_native", ProviderStrategy),
        ("tool_auto", ToolStrategy),
        (None, None),
    ],
)
async def test_the_invoker_binds_the_rows_declared_structured_output_strategy(
    monkeypatch: pytest.MonkeyPatch, declared: str | None, expected: type | None
) -> None:
    """W1 D16: a Sonnet 5.5 evaluator row (provider_native) must never be bound as a forced
    tool; a row without a declared strategy refuses before any model call."""

    from dataclasses import replace

    seen: dict[str, Any] = {}

    class Agent:
        async def ainvoke(self, state: Any, config: Any) -> Any:
            return {"messages": [], "structured_response": JudgeAnswer(verdicts=[])}

    def create_deep_agent(**kwargs: Any) -> Agent:
        seen.update(kwargs)
        return Agent()

    import deepagents

    monkeypatch.setattr(deepagents, "create_deep_agent", create_deep_agent)
    from langchain_anthropic import ChatAnthropic

    offline = ChatAnthropic(model_name="claude-sonnet-5-5", api_key=SecretStr("k"), max_tokens=64)
    monkeypatch.setattr(evaluators, "chat_model", lambda evaluator, credentials: offline)
    _auditor, judge = await bindings()
    judge = replace(judge, structured_output=declared)
    invoke = evaluators.deep_agents_invoker({JUDGE_CREDENTIAL: "k"})
    if expected is None:
        with pytest.raises(TrustedJudgmentRefused, match="declares no structured_output"):
            await invoke(judge, "prompt", "body", JudgeAnswer)
        assert "response_format" not in seen
        return
    await invoke(judge, "prompt", "body", JudgeAnswer)
    assert type(seen["response_format"]) is expected
    schema = seen["response_format"].schema
    assert schema is JudgeAnswer or issubclass(schema, JudgeAnswer)
    enforced = [type(item).__name__ for item in seen["middleware"]]
    assert ("RequireStructuredResponse" in enforced) is (declared == "tool_auto")


# ---------------------------------------------------------------------- composition guards


def settings(**values: Any) -> Settings:
    base = {"mission_control_deployments_root": Path(__file__).resolve().parents[3] / "deployments"}
    return Settings.model_construct(**{**Settings().model_dump(), **base, **values})


KEYS = {"mc_judge_openai_api_key": SecretStr("j"), "anthropic_api_key": SecretStr("p")}


@pytest.mark.parametrize(
    ("values", "kind", "message"),
    [
        ({"mc_judge_openai_api_key": SecretStr("j")}, "independent", "needs both"),
        ({**KEYS, "mc_auditor_anthropic_api_key": SecretStr("p")}, "independent", "SHARED"),
        ({**KEYS, "mc_auditor_anthropic_api_key": SecretStr("a")}, "scripted", "scripted census"),
    ],
)
def test_composition_refuses_unsafe_evaluator_configuration(
    values: dict[str, Any], kind: str, message: str
) -> None:
    with pytest.raises(TrustedCompositionError, match=message):
        compose_trusted_settlement(
            settings(**values),
            None,  # type: ignore[arg-type]
            application_id="biotech",
            gateway=None,
            output_store=None,
            submissions=None,
            auditor_kind=kind,
            clock=lambda: NOW,
        )


def test_composition_is_absent_without_evaluator_credentials_and_real_with_both() -> None:
    none = compose_trusted_settlement(
        settings(mc_judge_openai_api_key=None, mc_auditor_anthropic_api_key=None),
        None,  # type: ignore[arg-type]
        application_id="biotech",
        gateway=None,
        output_store=None,
        submissions=None,
        auditor_kind="independent",
        clock=lambda: NOW,
    )
    assert none is None

    class Gateway:
        decisions = None

    composed = compose_trusted_settlement(
        settings(**KEYS, mc_auditor_anthropic_api_key=SecretStr("a")),
        None,  # type: ignore[arg-type]
        application_id="biotech",
        gateway=Gateway(),
        output_store=object(),
        submissions=object(),
        auditor_kind="none",
        clock=lambda: NOW,
    )
    assert composed is not None and composed._pin == "knowledge.report.assess@1"
    runner = composed._bridge._runner
    assert runner._prices["gpt-5.6-terra"].input == 2.0  # priced from models.toml
    # W1 D28 review: the settlement's output service decides reference promises from the
    # bridge's adjudicated record (the production reference-use port, not none).
    from mission_control.application.outputs.fulfillment import TrustedReferenceUses

    fulfillment = composed._bridge._fulfillment
    assert isinstance(fulfillment._reference_uses, TrustedReferenceUses)
    assert fulfillment._reference_uses._store is composed._store


# ---------------------------------------------------------------------- round 3 review fixes


async def test_assertions_above_the_cap_wait_instead_of_truncating() -> None:
    """Review B1: a silent truncation would judge part of a report."""

    many = tuple(assertion_member() for _ in range(evaluators.MAX_ASSERTIONS + 1))
    invoke = Invoker()
    runner = ModelEvaluatorRunner(prices=PRICES, context=context(assertions=many), invoke=invoke)
    auditor, judge = await bindings()
    for evaluator in (judge, auditor):
        with pytest.raises(EvaluatorUnavailable, match="EVALUATION_CONTEXT_INCOMPLETE"):
            await ModelEvaluatorRunner(
                prices=PRICES,
                context=context(assertions=many, units=(("u", 0, 10),)),
                invoke=invoke,
            ).evaluate(evaluator, subject())
    assert invoke.calls == [] and runner is not None


async def test_a_model_without_a_price_row_fails_closed() -> None:
    """Review S2: spend that cannot be priced is never recorded as zero."""

    runner = ModelEvaluatorRunner(
        context=context(), invoke=Invoker(JudgeAnswer(verdicts=[verdict()])), prices={}
    )
    _auditor, judge = await bindings()
    with pytest.raises(EvaluatorUnavailable, match="no models.toml price"):
        await runner.evaluate(judge, subject())


def test_the_evaluator_agent_exposes_no_tool_and_no_subagent() -> None:
    """Review S1: Deep Agents registers todo, filesystem and `task` (subagent) tools; the
    evaluator's middleware strips every one from each model request."""

    from types import SimpleNamespace

    seen: list[Any] = []

    class Request(SimpleNamespace):
        def override(self, **changes: Any) -> Any:
            return Request(**{**self.__dict__, **changes})

    request = Request(tools=["write_todos", "ls", "read_file", "task"], response_format="schema")
    middleware = evaluators.NoToolsMiddleware()
    middleware.wrap_model_call(request, seen.append)
    assert seen[0].tools == [] and seen[0].response_format == "schema"


def test_the_production_composition_prices_every_evaluator_row_and_gates_dependent_inputs() -> None:
    """Review S2/N2: the composable decision is the composition's own result."""

    from mission_control.bootstrap.trusted_judgment import trusted_settlement_composable

    assert not trusted_settlement_composable(
        settings(mc_judge_openai_api_key=None, mc_auditor_anthropic_api_key=None), "biotech"
    )
    shared = settings(**KEYS, mc_auditor_anthropic_api_key=SecretStr("p"))
    assert not trusted_settlement_composable(shared, "biotech")  # composition refuses
    good = settings(**KEYS, mc_auditor_anthropic_api_key=SecretStr("a"))
    assert trusted_settlement_composable(good, "ai-engineer")

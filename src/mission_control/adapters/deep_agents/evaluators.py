"""The MC-hosted independent judge and auditor on the Deep Agents harness (OVE-169, OC-D108/IA-09).

:class:`ModelEvaluatorRunner` is the production
:class:`~mission_control.application.knowledge.judgment.EvaluatorRunner`. Each evaluation is one
bounded Deep Agents run (``create_deep_agent`` with a structured ``response_format``, no added
tools, a recursion limit) hosted by Mission Control under the evaluator's OWN credential
(``MC_JUDGE_OPENAI_API_KEY`` / ``MC_AUDITOR_ANTHROPIC_API_KEY``) and ``models.toml`` pin
(``judge.default`` / ``auditor.default``). The agent answers a small typed verdict; this module
turns it deterministically into the KS wire documents ``report.observe`` validates:

* **judge**: per assertion one ``attribution`` observation and, per support set of that
  assertion, one ``support`` observation (verdict, cited and contradicting fragments,
  qualification, bound to the assertion's qualifier digest). Every assertion must be answered
  with a verdict that satisfies the research-core rules; otherwise the run is retried within
  :data:`MAX_EVALUATION_ATTEMPTS` and then waits (never a partial batch: KS locks a role after its
  first batch).
* **auditor**: the independent census (``SubmittedCensus``): the quotes it finds in the frozen
  body, located by exact text search, with UTF-16 spans (KS indexes JavaScript strings), the
  renderer unit containing each span and ``quoteDigest`` over the UTF-8 quote bytes.

The context is KS ``knowledge.read`` ``evaluation-context-read/v1`` under the evaluator's own access
AND grant (``KnowledgeEvaluationContextSource``): KS scopes it by role (the auditor never sees
support sets, fragments or the ledger) and MC re-verifies the body digest. ``usage.costUsd`` is
priced from the ``models.toml`` row (base or long-prompt tier by input tokens) for every model
call the agent made.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from mission_control.adapters.deep_agents.model_retry import (
    SENT_TRANSPORT,
    UNSENT_TRANSPORT,
    causes,
)
from mission_control.application.knowledge.evaluator_plans import (
    EvaluationContext,
    EvaluationContextSource,
)
from mission_control.application.knowledge.judgment import (
    EvaluatorBinding,
    EvaluatorOutput,
    EvaluatorUnavailable,
    JudgmentSubject,
    TrustedJudgmentRefused,
    UseSpec,
)
from mission_control.contracts.knowledge_protocol import Ref, digest_canonical

OBSERVATION_SCHEMA = "research-core.observation.v2"
OCCURRENCE_SCHEMA = "research-core.discovered_occurrence.v1"
# research-core `SpanSchema` (W1 D20): every span names its basis. KS hands the context units as
# bare {start, end}; a discovered occurrence must carry the basis or the census is refused
# ("the census is not a valid discovery").
SPAN_BASIS = "utf16-code-units-v1"
METHOD_VERSION = "mc-deep-agents-evaluator.v1"
EVALUATION_CONTEXT_SCHEMA = "research-evaluation-context.v1"
MAX_ASSERTIONS = 64
MAX_QUOTES = 256
# PROOFS §6: at most 2 infrastructure retries per logical operation. W1 D23: one evaluation is
# exactly one agent run; the trusted bridge (`EvaluatorRetryPolicy`) owns the retry and bounds the
# billed runs per exact revision and role across settlement passes.
MAX_EVALUATION_ATTEMPTS = 2
RECURSION_LIMIT = 12
# The bounded, redacted length of a recorded failure cause (W1 D23).
MAX_CAUSE_CHARS = 400
ACCEPTING = {"full_support", "qualified_support"}

JUDGE_INSTRUCTIONS = (
    "You are an independent judge of a research report you did not write. For EVERY numbered "
    "assertion, decide from the quoted evidence fragments only (never outside knowledge) whether "
    "it is correctly attributed and how well its support set's evidence supports it. Cite "
    "fragment ids "
    "exactly as given: a full or qualified support cites at least one fragment, a contradiction "
    "names the contradicting fragments, a qualified support states its qualification. Answer each "
    "assertion exactly once in the structured response; use no tools."
)
AUDITOR_INSTRUCTIONS = (
    "You are an independent auditor. Read the report body and list every distinct factual claim "
    "it makes, quoting each claim EXACTLY as it appears in the body (a verbatim substring). Map a "
    "claim to the numbered assertion it states when one matches; otherwise leave it unmapped. "
    "Mark negated or interrogative quotes. Do not paraphrase. Answer in the structured response; "
    "use no tools."
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _instant(value: datetime) -> str:
    from mission_control.application.knowledge.access import instant

    return instant(value)


def _digest_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------- typed answers


class AssertionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertion: int = Field(ge=0, description="The assertion number")
    attribution: Literal["correct", "misattributed", "missing", "not_applicable"]
    support: Literal[
        "full_support",
        "qualified_support",
        "partial_or_context_only",
        "contradiction",
        "conflict",
        "insufficient_evidence",
        "unable_to_assess",
    ]
    cited_fragments: list[str] = Field(default_factory=list, max_length=32)
    contradicting_fragments: list[str] = Field(default_factory=list, max_length=32)
    qualification: str | None = Field(default=None, max_length=280)
    rationale: str = Field(min_length=1, max_length=2000)


class JudgeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdicts: list[AssertionVerdict] = Field(max_length=MAX_ASSERTIONS)


class FoundClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote: str = Field(min_length=1, max_length=4000)
    assertion: int | None = Field(default=None, ge=0)
    negated: bool = False
    interrogative: bool = False


class AuditorAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[FoundClaim] = Field(max_length=MAX_QUOTES)
    rationale: str = Field(min_length=1, max_length=4000)


@dataclass(frozen=True)
class CallUsage:
    """Token usage of every model call one evaluation made (the agent may make several)."""

    calls: tuple[tuple[int, int], ...]  # (input tokens, output tokens) per call

    @property
    def tokens(self) -> int:
        return sum(i + o for i, o in self.calls)


AgentInvoker = Callable[
    [EvaluatorBinding, str, str, type[BaseModel]], Awaitable[tuple[BaseModel | None, CallUsage]]
]


# ---------------------------------------------------------------------- pricing (PROOFS §6)


@dataclass(frozen=True)
class Price:
    """One ``models.toml`` row's list prices (USD per million tokens) and long-prompt tiers."""

    input: float
    output: float
    tiers: tuple[tuple[int, float, float], ...] = ()  # (above_input_tokens, input, output)

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        rate_in, rate_out = self.input, self.output
        for above, tier_in, tier_out in sorted(self.tiers):
            if input_tokens > above:  # the whole request is billed at the tier
                rate_in, rate_out = tier_in, tier_out
        return (
            Decimal(str(rate_in)) * input_tokens + Decimal(str(rate_out)) * output_tokens
        ) / Decimal(1_000_000)


def usage_document(usage: CallUsage, price: Price | None) -> dict[str, Any]:
    """KS ``Usage``: provider calls, tokens and USD (at most 6 decimals, rounded half up)."""

    total = sum((price.cost(i, o) for i, o in usage.calls), Decimal(0)) if price else Decimal(0)
    cost = total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP).normalize()
    text = format(cost, "f")
    return {"providerCalls": len(usage.calls), "tokens": usage.tokens, "costUsd": text or "0"}


# ---------------------------------------------------------------------- Deep Agents harness


def chat_model(evaluator: EvaluatorBinding, credentials: Mapping[str, str]) -> Any:
    key = credentials.get(evaluator.credential_ref)
    if not key or evaluator.model_id is None:
        raise EvaluatorUnavailable(f"{evaluator.credential_ref} is not configured")
    if evaluator.vendor == "openai":
        from langchain_openai import ChatOpenAI

        # W1 D24: a tool-calling OpenAI evaluator uses the Responses API (chat completions
        # refuses function tools with reasoning on gpt-5.6-terra); the row declares it.
        return ChatOpenAI(
            model=evaluator.model_id,
            api_key=SecretStr(key),
            max_retries=1,
            use_responses_api=getattr(evaluator, "api_surface", None) == "responses",
        )
    if evaluator.vendor == "anthropic":
        from langchain_anthropic import ChatAnthropic

        settings: dict[str, Any] = {"max_tokens": 8192}
        return ChatAnthropic(
            model_name=evaluator.model_id, api_key=SecretStr(key), max_retries=1, **settings
        )
    raise EvaluatorUnavailable(f"no evaluator client for vendor {evaluator.vendor}")


def _no_tools_middleware_base() -> type:
    from langchain.agents.middleware.types import AgentMiddleware

    return AgentMiddleware


class NoToolsMiddleware(_no_tools_middleware_base()):  # type: ignore[misc]
    """Strip every tool from each model request (review S1): Deep Agents 0.7.5 always registers
    its todo and filesystem tools and the `task` tool of the auto-added general-purpose subagent;
    an evaluator may call none of them (so no subagent can run). The structured response is the
    request's response format, not a tool, and stays.

    ``model_settings`` are merged into each request's bind settings (W1 D23: the OpenAI judge binds
    ``parallel_tool_calls=False``, so its one forced response tool is called exactly once)."""

    name = "mc_evaluator_no_tools"

    def __init__(self, model_settings: Mapping[str, Any] | None = None) -> None:
        super().__init__()
        self.model_settings = dict(model_settings or {})

    def _strip(self, request: Any) -> Any:
        if not self.model_settings:
            return request.override(tools=[])
        merged = {**(getattr(request, "model_settings", None) or {}), **self.model_settings}
        return request.override(tools=[], model_settings=merged)

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(self._strip(request))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await handler(self._strip(request))


def evaluator_model_settings(evaluator: EvaluatorBinding) -> dict[str, Any]:
    """Bind settings of the evaluator's response call (W1 D23).

    An OpenAI chat model may answer a forced tool with several parallel calls (one per assertion
    is typical for a list schema); LangChain refuses them as ``MultipleStructuredOutputsError``.
    ``parallel_tool_calls=False`` (the Chat Completions request field; langchain-openai 1.3
    ``bind_tools``) makes the one response call the only call."""

    return {"parallel_tool_calls": False} if evaluator.vendor == "openai" else {}


# W1 fix G S3: the transport classes live with the lane's unsent-transport retry (D40).
_UNSENT_TRANSPORT = UNSENT_TRANSPORT
_SENT_TRANSPORT = SENT_TRANSPORT
_causes = causes


def _billed(error: BaseException) -> bool:
    """Whether a failed agent run may have been billed (W1 D23, fix G S3).

    Unbilled: the request never reached the provider, or the provider refused it. That is an
    httpx connect/pool/proxy failure or a builtin ``ConnectionError`` anywhere in the cause chain
    (the vendor SDKs wrap these as ``APIConnectionError``, and ``APITimeoutError`` for a connect
    or pool timeout), any other ``APIConnectionError``, and an ``APIStatusError`` (HTTP 4xx/5xx
    answers no tokens). Billed: a timeout or transport failure after the request was sent
    (``ReadTimeout``/``WriteTimeout``/``ReadError``/``RemoteProtocolError``: the provider may
    have processed it and bills generated tokens even when the answer is lost), a bare
    ``APITimeoutError``/``TimeoutError`` whose cause is unknown (it may have been sent), and
    anything raised after the model answered (structured-output validation, multiple response
    calls, a recursion limit). Unknown errors count as billed, so the bound errs toward less
    spend."""

    for item in _causes(error):
        root = type(item).__module__.split(".", 1)[0]
        if root in {"httpx", "httpcore"}:
            if type(item).__name__ in _UNSENT_TRANSPORT:
                return False
            if type(item).__name__ in _SENT_TRANSPORT:
                return True
        elif isinstance(item, ConnectionError):  # refused, reset or aborted before an answer
            return False
    # By the vendor SDKs' class names (both SDKs share them), without importing a transitive SDK.
    names = {
        cls.__name__
        for cls in type(error).__mro__
        if cls.__module__.split(".", 1)[0] in {"openai", "anthropic"}
    }
    if "APITimeoutError" in names:
        return True
    return not names & {"APIStatusError", "APIConnectionError"}


def failure_cause(error: BaseException) -> str:
    """``<ExceptionClass>: <message>``, whitespace-collapsed, redacted and bounded."""

    from mission_control.application.knowledge.redaction import redacted

    text = " ".join(str(error).split())
    named = f"{type(error).__name__}: {text}" if text else type(error).__name__
    return redacted(named, MAX_CAUSE_CHARS)


def no_response_cause(messages: Sequence[Any]) -> str:
    """Why a finished agent run carries no structured response (W1 D23): the last model
    message's refusal, finish reason, tool calls and text, bounded and redacted."""

    from mission_control.application.knowledge.redaction import redacted

    last = next((m for m in reversed(messages) if getattr(m, "type", None) == "ai"), None)
    if last is None:
        return "no structured response: the model returned no message"
    extra = getattr(last, "additional_kwargs", None) or {}
    metadata = getattr(last, "response_metadata", None) or {}
    parts = ["no structured response"]
    refusal = extra.get("refusal")
    if not refusal and isinstance(last.content, list):  # Responses API content blocks (W1 D24)
        refusal = next(
            (
                block.get("refusal")
                for block in last.content
                if isinstance(block, dict) and block.get("type") == "refusal"
            ),
            None,
        )
    if refusal:
        parts.append(f"refusal: {refusal}")
    finish = metadata.get("finish_reason") or metadata.get("stop_reason")
    if finish:
        parts.append(f"finish_reason: {finish}")
    parts.append(f"tool calls: {[call.get('name') for call in last.tool_calls or []]}")
    invalid = getattr(last, "invalid_tool_calls", None) or []
    if invalid:
        parts.append(
            "invalid tool calls: "
            + "; ".join(f"{item.get('name')}: {item.get('error')}" for item in invalid[:3])
        )
    content = last.content if isinstance(last.content, str) else str(last.content)
    if content.strip():
        parts.append(f"text: {' '.join(content.split())[:160]}")
    return redacted("; ".join(parts), MAX_CAUSE_CHARS)


def deep_agents_invoker(credentials: Mapping[str, str]) -> AgentInvoker:
    """One bounded Deep Agents run per evaluation: the role's model and credential, its
    instructions as the system prompt, no added tools or subagents, a structured response."""

    async def invoke(
        evaluator: EvaluatorBinding, prompt: str, body: str, schema: type[BaseModel]
    ) -> tuple[BaseModel | None, CallUsage]:
        from deepagents import create_deep_agent
        from langchain.agents.structured_output import ProviderStrategy, ToolStrategy

        # W1 D16/D18: the strategy the evaluator's model row declares, never auto-detection.
        model = chat_model(evaluator, credentials)
        middleware: list[Any] = [NoToolsMiddleware(evaluator_model_settings(evaluator))]
        from langchain_core.language_models import BaseChatModel

        if evaluator.vendor and isinstance(model, BaseChatModel):
            # W1 D23, "No harness profile matched pre-built model ChatOpenAI (gpt-5.6-terra)":
            # no harness profile covered the OpenAI judge (the producer lane registers only its
            # own provider), so Deep Agents compiled its implicit general-purpose child into every
            # judge run. The lane's registration (the provider's profile with that child
            # disabled, verified by a replayed lookup) now covers each evaluator's provider.
            from mission_control.adapters.deep_agents.adapter import (
                _disable_implicit_general_purpose_child,
            )

            _disable_implicit_general_purpose_child(model, evaluator.vendor)
        from mission_control.adapters.deep_agents.structured_response import (
            RequireStructuredResponse,
            response_schema,
            with_auto_tool_choice,
        )

        # W1 D23: `handle_errors=False`. With LangChain's default an invalid or repeated response
        # call is answered with an error message and the model asked again inside the same run,
        # until the recursion limit: 11 billed calls, then a bare GraphRecursionError (reproduced
        # offline over a mocked OpenAI transport). Now the run ends at the first invalid answer
        # with its validation error, and the trusted bridge's bounded retry decides.
        if evaluator.structured_output == "tool_forced":
            response_format: Any = ToolStrategy(response_schema(schema), handle_errors=False)
        elif evaluator.structured_output == "tool_auto":
            response_format = ToolStrategy(response_schema(schema), handle_errors=False)
            model = with_auto_tool_choice(model)
            middleware.append(
                RequireStructuredResponse([spec.name for spec in response_format.schema_specs])
            )
        elif evaluator.structured_output == "provider_native":
            if evaluator.vendor == "anthropic":
                from mission_control.adapters.deep_agents.output_format import (
                    AnthropicOutputSchemaRefused,
                    anthropic_output_schema,
                )

                try:
                    anthropic_output_schema(schema)
                except AnthropicOutputSchemaRefused as refused:
                    raise TrustedJudgmentRefused(
                        "OUTPUT_SCHEMA_UNSUPPORTED",
                        f"{evaluator.role} schema cannot bind provider_native: {refused}",
                    ) from None
            response_format = ProviderStrategy(schema)
        else:
            # A configuration fault, not a wait: retrying the same row cannot succeed.
            raise TrustedJudgmentRefused(
                "OUTPUT_SCHEMA_UNSUPPORTED",
                f"{evaluator.role} model {evaluator.model_id} declares no structured_output "
                "strategy in models.toml",
            )
        agent = create_deep_agent(
            model=model,
            tools=[],
            system_prompt=prompt,
            subagents=[],
            middleware=middleware,
            response_format=response_format,
            name=f"mc-{evaluator.role}",
        )
        try:
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": body}]},
                config={"recursion_limit": RECURSION_LIMIT},
            )
        except (EvaluatorUnavailable, TrustedJudgmentRefused):
            raise
        except Exception as error:
            # W1 D23: the concrete cause (class, message, validation errors) and whether the
            # failed run was billed (the bridge bounds billed runs).
            raise EvaluatorUnavailable(
                f"{evaluator.role} run failed: {failure_cause(error)}", billed=_billed(error)
            ) from None
        messages = result.get("messages", [])
        calls = []
        for message in messages:
            metadata = getattr(message, "usage_metadata", None)
            if isinstance(metadata, dict):
                calls.append(
                    (int(metadata.get("input_tokens", 0)), int(metadata.get("output_tokens", 0)))
                )
        parsed = result.get("structured_response")
        if not isinstance(parsed, schema):
            raise EvaluatorUnavailable(
                f"{evaluator.role} answer incomplete: {no_response_cause(messages)}", billed=True
            )
        return parsed, CallUsage(tuple(calls))

    return invoke


# ---------------------------------------------------------------------- KS context


class KnowledgeEvaluationContextSource:
    """KS ``knowledge.read`` ``evaluation-context-read/v1`` under the evaluator's access/grant."""

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway  # application.knowledge.gateway.KnowledgeGateway

    async def load(self, evaluator: EvaluatorBinding, report: Ref) -> EvaluationContext:
        from mission_control.application.knowledge.judgment import (
            TRUSTED_CAPABILITY_PIN,
            _governors,
            _key,
        )
        from mission_control.application.knowledge.operations import KnowledgeRefused
        from mission_control.contracts.knowledge_assessment import EvaluationContextRequest

        request = EvaluationContextRequest(schema_="evaluation-context-read.v1", report=report)
        try:
            answer = await self._gateway.trusted(
                "knowledge.read",
                request,
                evaluator.access,
                evaluation=evaluator.grant(),
                request_key=_key("context", report.id, report.digest, evaluator.role),
                governors=_governors(_utcnow),
                capability_pin=TRUSTED_CAPABILITY_PIN,
                subject_ref=f"report:{report.id}",
            )
        except KnowledgeRefused as refused:
            raise EvaluatorUnavailable(f"evaluation context refused: {refused.code}") from None
        document = answer.document
        if document is None:
            code = None if answer.refusal is None else answer.refusal.code
            raise EvaluatorUnavailable(f"evaluation context unavailable: {code}")
        return context_from_document(document, report, evaluator.role)


def context_from_document(document: Mapping[str, Any], report: Ref, role: str) -> EvaluationContext:
    """Validate a ``research-evaluation-context.v1`` against the exact report and role."""

    body = document.get("body") or {}
    text = body.get("text")
    if (
        document.get("schema") != EVALUATION_CONTEXT_SCHEMA
        or document.get("role") != role
        or Ref.model_validate(document.get("report")) != report
        or not isinstance(text, str)
        or _digest_bytes(text.encode("utf-8")) != body.get("digest")
    ):
        raise EvaluatorUnavailable("evaluation context does not bind the exact revision")
    task = document.get("task")
    audience = task.get("audience") if isinstance(task, Mapping) else None
    if not isinstance(audience, str) or re.fullmatch(r"[a-z][a-z0-9_.-]{0,119}", audience) is None:
        raise EvaluatorUnavailable("evaluation context has no valid exact task audience")
    assert isinstance(task, Mapping)
    units = tuple(
        (str(unit["path"]), int(unit["span"]["start"]), int(unit["span"]["end"]))
        for unit in document.get("units", [])
        if unit.get("span") is not None
    )
    support_sets = document.get("supportSets")
    evidence = document.get("evidence")
    return EvaluationContext(
        report=report,
        body_artifact=Ref.model_validate(body["artifact"]),
        body_text=text,
        assertions=tuple(document.get("assertions", [])),
        fragments=tuple(evidence or ()),
        units=units,
        support_sets=None if support_sets is None else tuple(support_sets),
        use=UseSpec(
            use=str(task["use"]),
            audience=audience,
            policy=Ref.model_validate(task["policy"]),
            rubric=Ref.model_validate(task["rubric"]),
        ),
    )


# ---------------------------------------------------------------------- the runner


def _within_cap(assertions: Sequence[Mapping[str, Any]]) -> Sequence[Mapping[str, Any]]:
    """Every assertion or none (review B1): a silent truncation would judge part of a report."""

    if len(assertions) > MAX_ASSERTIONS:
        raise EvaluatorUnavailable(
            f"EVALUATION_CONTEXT_INCOMPLETE: {len(assertions)} assertions exceed the "
            f"{MAX_ASSERTIONS}-assertion evaluator cap"
        )
    return assertions


def utf16_offset(text: str, index: int) -> int:
    """The JavaScript (UTF-16 code unit) offset of Python code-point ``index`` in ``text``."""

    return len(text[:index].encode("utf-16-le")) // 2


def _statement(item: Mapping[str, Any]) -> str:
    """What the evaluator reads of a context member: an assertion's proposition, a fragment's
    selected text (W1 D20: research-core records carry no ``statement``/``text`` field, so the
    whole record dict was printed before)."""

    record = item.get("record") or {}
    if not isinstance(record, Mapping):
        return str(record)
    selector = record.get("selector")
    for value in (
        record.get("proposition"),
        selector.get("value") if isinstance(selector, Mapping) else None,
        record.get("statement"),
        record.get("text"),
    ):
        if isinstance(value, str) and value:
            return value
    return str(record)


class ModelEvaluatorRunner:
    def __init__(
        self,
        *,
        context: EvaluationContextSource,
        invoke: AgentInvoker,
        prices: Mapping[str, Price] | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._context = context
        self._invoke = invoke
        self._prices = dict(prices or {})
        self._clock = clock

    async def evaluate(
        self, evaluator: EvaluatorBinding, subject: JudgmentSubject
    ) -> EvaluatorOutput:
        context = await self._context.load(evaluator, subject.report)
        if evaluator.role == "auditor":
            if not context.units:
                raise EvaluatorUnavailable("EVALUATION_CONTEXT_INCOMPLETE: the census needs units")
            return await self._audit(evaluator, context)
        if evaluator.role in {"judge", "second_family_judge"}:
            missing = context.missing("support_sets")
            if missing or not context.assertions:
                raise EvaluatorUnavailable(
                    "EVALUATION_CONTEXT_INCOMPLETE: the judge needs assertions and support sets"
                )
            return await self._judge(evaluator, context)
        raise EvaluatorUnavailable(f"{evaluator.role} is not a model evaluator")

    # ------------------------------------------------------------------ shared

    def _identity(self, evaluator: EvaluatorBinding, prompt: str) -> dict[str, Any]:
        config = {"model": evaluator.model_id, "method": METHOD_VERSION, "role": evaluator.role}
        return {
            "role": evaluator.role,
            "kind": "model",
            "provider": evaluator.vendor,
            "family": evaluator.family,
            "model": evaluator.model_id,
            "deployment": None,
            "reviewerId": None,
            "methodVersion": METHOD_VERSION,
            "promptDigest": _digest_bytes(prompt.encode("utf-8")),
            "configDigest": digest_canonical(config),
        }

    def _method(self, evaluator: EvaluatorBinding, report: Ref) -> dict[str, Any]:
        return {
            "kind": "method",
            "id": f"mc-deep-agents-{evaluator.role}",
            "version": METHOD_VERSION,
            "digest": digest_canonical({"method": METHOD_VERSION, "role": evaluator.role}),
            "tenant": report.tenant,
            "binding": report.binding,
        }

    async def _call(
        self,
        evaluator: EvaluatorBinding,
        schema: type[BaseModel],
        prompt: str,
        body: str,
        accept: Callable[[Any], str | None],
    ) -> tuple[Any, dict[str, Any]]:
        """Run the agent once and accept its answer only when complete and valid (``accept``
        returns no problem). W1 D23: one agent run per evaluation; an incomplete or invalid
        answer raises a billed :class:`EvaluatorUnavailable` naming the problem, and the trusted
        bridge decides a retry within its persisted per-revision bound."""

        try:
            parsed, usage = await self._invoke(evaluator, prompt, body, schema)
        except (EvaluatorUnavailable, TrustedJudgmentRefused):
            raise  # a typed refusal (W1 D16 schema fault) is never a durable wait
        except Exception as error:  # provider down, quota, timeout: a durable wait
            raise EvaluatorUnavailable(
                f"{evaluator.role} call failed: {failure_cause(error)}", billed=_billed(error)
            ) from None
        problem = "no structured response" if parsed is None else (accept(parsed) or "")
        if problem:
            raise EvaluatorUnavailable(
                f"{evaluator.role} answer incomplete: {problem}", billed=True
            )
        price = self._prices.get(evaluator.model_id or "")
        if price is None:
            raise EvaluatorUnavailable(
                f"no models.toml price for {evaluator.model_id}: spend cannot be accounted",
                billed=True,
            )
        return parsed, usage_document(CallUsage(tuple(usage.calls)), price)

    # ------------------------------------------------------------------ judge

    async def _judge(
        self, evaluator: EvaluatorBinding, context: EvaluationContext
    ) -> EvaluatorOutput:
        assertions = _within_cap(context.assertions)
        fragment_ids = {str(item["handle"]["id"]): item["handle"] for item in context.fragments}
        sets = context.support_sets or ()
        lines = ["# Assertions"]
        for index, item in enumerate(assertions):
            lines.append(f"{index}. {_statement(item)}")
        lines.append("# Evidence fragments")
        for item in context.fragments:
            lines.append(f"[{item['handle']['id']}] {_statement(item)}")

        def accept(answer: JudgeAnswer) -> str | None:
            numbers = sorted(verdict.assertion for verdict in answer.verdicts)
            if numbers != list(range(len(assertions))):
                return "verdicts do not cover every assertion exactly once"
            for verdict in answer.verdicts:
                cited = [f for f in verdict.cited_fragments if f in fragment_ids]
                contrary = [f for f in verdict.contradicting_fragments if f in fragment_ids]
                if verdict.support in ACCEPTING and not cited:
                    return f"assertion {verdict.assertion}: support cites no known fragment"
                if verdict.support == "contradiction" and not contrary:
                    return f"assertion {verdict.assertion}: contradiction names no fragment"
                if verdict.support == "qualified_support" and not verdict.qualification:
                    return f"assertion {verdict.assertion}: qualified support without qualification"
            return None

        answer, usage = await self._call(
            evaluator, JudgeAnswer, JUDGE_INSTRUCTIONS, "\n".join(lines), accept
        )
        identity = self._identity(evaluator, JUDGE_INSTRUCTIONS)
        method = self._method(evaluator, context.report)
        recorded = _instant(self._clock())
        zero = {**usage, "providerCalls": 0, "tokens": 0, "costUsd": "0"}
        observations: list[dict[str, Any]] = []

        def observation(
            target: Mapping[str, Any], prop: str, outcome: dict[str, Any], **extra: Any
        ) -> dict[str, Any]:
            return {
                "schemaVersion": OBSERVATION_SCHEMA,
                "id": f"obs-{evaluator.role}-{prop}-{target['id']}"[:200],
                "tenant": context.report.tenant,
                "binding": context.report.binding,
                "target": dict(target),
                "inputDigest": digest_canonical(
                    {"target": target["digest"], "body": context.body_artifact.digest}
                ),
                "qualifiersDigest": extra.get("qualifiers"),
                "method": method,
                "evaluator": identity,
                "rationale": extra["rationale"],
                "limitations": [],
                "evidence": extra.get("evidence", []),
                "rawResponse": None,
                # The whole evaluation's usage is carried once; the others record zero.
                "usage": usage if not observations else zero,
                "recordedAt": recorded,
                "property": prop,
                "outcome": outcome,
            }

        for verdict in sorted(answer.verdicts, key=lambda item: item.assertion):
            item = assertions[verdict.assertion]
            target = item["handle"]
            cited = [fragment_ids[f] for f in verdict.cited_fragments if f in fragment_ids]
            contrary = [
                fragment_ids[f] for f in verdict.contradicting_fragments if f in fragment_ids
            ]
            observations.append(
                observation(
                    target,
                    "attribution",
                    {
                        "result": verdict.attribution,
                        "attributedTo": None,
                        "expectedAttribution": None,
                    },
                    rationale=verdict.rationale,
                    evidence=cited,
                )
            )
            for support in sets:
                record = support.get("record") or {}
                assertion_ref = record.get("assertion") or {}
                if assertion_ref.get("id") != target["id"]:
                    continue
                observations.append(
                    observation(
                        support["handle"],
                        "support",
                        {
                            "verdict": verdict.support,
                            "premise": None,
                            "citedFragments": cited if verdict.support in ACCEPTING else [],
                            "contradictingFragments": contrary,
                            "unsupportedFacets": [],
                            "qualification": verdict.qualification
                            if verdict.support == "qualified_support"
                            else None,
                        },
                        rationale=verdict.rationale,
                        evidence=cited + contrary,
                        qualifiers=item.get("qualifiersDigest"),
                    )
                )
        return EvaluatorOutput(observations=tuple(observations))

    # ------------------------------------------------------------------ auditor

    async def _audit(
        self, evaluator: EvaluatorBinding, context: EvaluationContext
    ) -> EvaluatorOutput:
        units = context.units or ()
        assertions = _within_cap(context.assertions)
        lines = ["# Assertions"]
        for index, item in enumerate(assertions):
            lines.append(f"{index}. {_statement(item)}")
        lines += ["# Report body", context.body_text]
        answer, usage = await self._call(
            evaluator,
            AuditorAnswer,
            AUDITOR_INSTRUCTIONS,
            "\n".join(lines),
            lambda _answer: None,
        )
        text = context.body_text
        occurrences: list[dict[str, Any]] = []
        unlocated: list[str] = []
        for number, claim in enumerate(answer.claims):
            at = text.find(claim.quote)
            if at < 0:
                unlocated.append(claim.quote[:120])
                continue
            start, end = utf16_offset(text, at), utf16_offset(text, at + len(claim.quote))
            unit = next((path for path, low, high in units if low <= start and end <= high), None)
            if unit is None:
                unlocated.append(claim.quote[:120])
                continue
            mapped = (
                assertions[claim.assertion]["handle"]
                if claim.assertion is not None and claim.assertion < len(assertions)
                else None
            )
            occurrences.append(
                {
                    "schemaVersion": OCCURRENCE_SCHEMA,
                    "id": f"aud-{number}-{start}",
                    "body": context.body_artifact.model_dump(mode="json"),
                    "span": {"basis": SPAN_BASIS, "start": start, "end": end},
                    "blockPath": unit,
                    "quoteDigest": _digest_bytes(claim.quote.encode("utf-8")),
                    "candidateAssertion": claim.quote,
                    "assertion": mapped,
                    "negated": claim.negated,
                    "interrogative": claim.interrogative,
                }
            )
        census = {
            "evaluator": self._identity(evaluator, AUDITOR_INSTRUCTIONS),
            "method": self._method(evaluator, context.report),
            "occurrences": occurrences,
            "explanations": [],
            "unitExplanations": [],
            "recall": {"label": "unmeasured", "reason": "no calibration set for this auditor"},
            "rationale": answer.rationale,
            "limitations": [f"quote not found verbatim: {quote}" for quote in unlocated[:16]],
            "usage": usage,
            "rawResponse": None,
        }
        return EvaluatorOutput(census=census)


def prices_from_rows(rows: Sequence[Any]) -> dict[str, Price]:
    """``models.toml`` rows (Model Profiles) by model id -> their list prices and tiers."""

    return {
        row.model_id: Price(
            row.cost_per_million_input,
            row.cost_per_million_output,
            tuple(
                (tier.above_input_tokens, tier.cost_per_million_input, tier.cost_per_million_output)
                for tier in row.price_tiers
            ),
        )
        for row in rows
    }


__all__ = [
    "AuditorAnswer",
    "CallUsage",
    "JudgeAnswer",
    "KnowledgeEvaluationContextSource",
    "ModelEvaluatorRunner",
    "Price",
    "context_from_document",
    "deep_agents_invoker",
    "prices_from_rows",
    "usage_document",
    "utf16_offset",
]

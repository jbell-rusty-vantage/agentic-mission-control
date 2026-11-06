"""W1 D23 (OVE-169): the trusted judge's request shape, recorded causes and bounded paid attempts.

Offline only. The judge request is built by the real production invoker (``deep_agents_invoker``:
Deep Agents 0.7.5, langchain-openai 1.3, openai 2.x) for the PROOFS §6 judge pin
``gpt-5.6-terra`` over a mocked OpenAI HTTP transport, so the exact Chat Completions body is
checked without a network call. The bridge tests run the in-memory trusted world of
``test_trusted_judgment``: every failed evaluator run records its concrete cause on the revision's
one standing wait assessment, a billed run counts against the role's bound for that exact
revision, and a pass after the bound never re-runs the paid evaluator; the settlement wait then
names the cause (``code``, ``reason``, ``issues``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from mission_control.adapters.deep_agents import evaluators
from mission_control.adapters.deep_agents.evaluators import JudgeAnswer
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.judgment import (
    ATTEMPTS_PREFIX,
    EvaluatorBinding,
    EvaluatorOutput,
    EvaluatorRetryPolicy,
    EvaluatorUnavailable,
    JudgmentSubject,
    TrustedJudgmentBridge,
)
from mission_control.application.knowledge.trusted_settlement import (
    TrustedSettlementPass,
    pending_or_raise,
)
from mission_control.domain.execution.invocation_settlement import SettlementOutcome, WaitReason
from tests.fixtures.knowledge_binding import (
    AUDIENCE,
    BINDING,
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    knowledge_port,
)
from tests.fixtures.trusted_knowledge import TrustedKnowledgeDouble
from tests.unit.knowledge.test_independent_evaluators import JUDGE_CREDENTIAL, bindings
from tests.unit.knowledge.test_trusted_judgment import (
    JUDGE_PIN,
    PROFILES,
    ScriptedRunner,
    World,
    world,
)
from tests.unit.knowledge.test_trusted_judgment import (
    evaluators as trusted_evaluators,
)

pytestmark = pytest.mark.asyncio

VERDICT = {
    "assertion": 0,
    "attribution": "correct",
    "support": "full_support",
    "cited_fragments": ["f-1"],
    "contradicting_fragments": [],
    "qualification": None,
    "rationale": "the fragment states it",
}


class OpenAITransport:
    """A mocked OpenAI endpoint: records each request body and answers by mode, in the shape of
    the endpoint called (W1 D24: the judge calls /v1/responses; chat completions refuses
    function tools with reasoning on gpt-5.6-terra)."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        url = str(request.url)
        self.bodies.append({"url": url, **body})
        if url.endswith("/chat/completions") and body.get("tools"):
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Function tools with reasoning_effort are not supported for "
                        "gpt-5.6-terra in /v1/chat/completions. To use function tools, use "
                        "/v1/responses or set reasoning_effort to 'none'.",
                        "type": "invalid_request_error",
                        "param": "tools",
                        "code": None,
                    }
                },
            )
        if self.mode == "bad_request":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported parameter: 'tool_choice'.",
                        "type": "invalid_request_error",
                        "param": "tool_choice",
                        "code": "unsupported_parameter",
                    }
                },
            )
        name = body["tools"][0]["name"]
        arguments = (
            {"verdicts": [{"assertion": 0}]} if self.mode == "invalid" else {"verdicts": [VERDICT]}
        )
        if self.mode == "refusal":
            output: list[dict[str, Any]] = [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": "I can't assist with that."}],
                }
            ]
        else:
            output = [{"type": "reasoning", "id": "rs_1", "summary": []}] + [
                {
                    "type": "function_call",
                    "id": f"fc_{index}",
                    "call_id": f"call_{index}",
                    "name": name,
                    "arguments": json.dumps(arguments),
                    "status": "completed",
                }
                for index in range(2 if self.mode == "parallel" else 1)
            ]
        return httpx.Response(
            200,
            json={
                "id": "resp_offline",
                "object": "response",
                "created_at": 1,
                "model": body["model"],
                "status": "completed",
                "parallel_tool_calls": False,
                "tool_choice": "required",
                "tools": [],
                "output": output,
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "total_tokens": 1200,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 120},
                },
            },
        )


def offline_judge(monkeypatch: pytest.MonkeyPatch, mode: str) -> OpenAITransport:
    """The production `chat_model` row settings over a mocked transport (no network)."""

    from langchain_openai import ChatOpenAI

    transport = OpenAITransport(mode)
    real = evaluators.chat_model

    def chat_model(evaluator: Any, credentials: Any) -> Any:
        configured = real(evaluator, credentials)
        assert isinstance(configured, ChatOpenAI)
        return ChatOpenAI(
            model=configured.model_name,
            api_key=SecretStr("sk-offline-not-a-key"),
            max_retries=configured.max_retries,
            use_responses_api=configured.use_responses_api,
            http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )

    monkeypatch.setattr(evaluators, "chat_model", chat_model)
    return transport


async def test_the_judge_request_is_one_forced_single_call_on_the_responses_api(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """W1 D24: gpt-5.6-terra refuses function tools with reasoning on /v1/chat/completions; the
    judge row declares the Responses API, so the forced response tool goes to /v1/responses with
    the model's own reasoning (never `reasoning_effort: none`)."""

    transport = offline_judge(monkeypatch, "ok")
    _auditor, judge = await bindings()
    assert (judge.vendor, judge.model_id, judge.structured_output, judge.api_surface) == (
        "openai",
        "gpt-5.6-terra",
        "tool_forced",
        "responses",
    )
    invoke = evaluators.deep_agents_invoker({JUDGE_CREDENTIAL: "k"})
    with caplog.at_level(logging.WARNING):
        parsed, usage = await invoke(
            judge, evaluators.JUDGE_INSTRUCTIONS, "# Assertions", JudgeAnswer
        )
    assert isinstance(parsed, JudgeAnswer) and usage.calls == ((1000, 200),)
    assert not [r for r in caplog.records if "No harness profile matched" in r.getMessage()]
    (body,) = transport.bodies
    assert body["url"] == "https://api.openai.com/v1/responses"
    assert body["model"] == "gpt-5.6-terra"
    assert body["tool_choice"] == "required" and body["parallel_tool_calls"] is False
    (tool,) = body["tools"]
    assert (tool["type"], tool["name"]) == ("function", "JudgeAnswer")
    assert tool["parameters"]["required"] == ["verdicts"]
    assert [(item["type"], item["role"]) for item in body["input"]] == [
        ("message", "system"),
        ("message", "user"),
    ]
    assert body["input"][0]["content"].startswith("You are an independent judge")
    # The model keeps its reasoning: nothing turns it off, nothing chat-completions-only is sent.
    assert body.get("reasoning", {}).get("effort") != "none"
    for absent in ("reasoning_effort", "messages", "temperature", "functions", "response_format"):
        assert absent not in body, absent


async def test_the_chat_completions_surface_reproduces_d24(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    transport = offline_judge(monkeypatch, "ok")
    _auditor, judge = await bindings()
    invoke = evaluators.deep_agents_invoker({JUDGE_CREDENTIAL: "k"})
    with pytest.raises(EvaluatorUnavailable, match="Function tools with reasoning_effort"):
        await invoke(replace(judge, api_surface=None), "p", "# Assertions", JudgeAnswer)
    assert transport.bodies[0]["url"].endswith("/v1/chat/completions")


@pytest.mark.parametrize(
    ("mode", "billed", "cause"),
    [
        ("invalid", True, "StructuredOutputValidationError: Failed to parse structured output"),
        ("parallel", True, "MultipleStructuredOutputsError"),
        ("refusal", True, "no structured response; refusal: I can't assist with that."),
        ("bad_request", False, "BadRequestError: Error code: 400"),
    ],
)
async def test_an_unusable_judge_answer_ends_the_run_with_its_concrete_cause(
    monkeypatch: pytest.MonkeyPatch, mode: str, billed: bool, cause: str
) -> None:
    """Before D23 an invalid or repeated response call looped inside one run until the recursion
    limit (11 billed calls, then a bare GraphRecursionError the settlement never named)."""

    transport = offline_judge(monkeypatch, mode)
    _auditor, judge = await bindings()
    invoke = evaluators.deep_agents_invoker({JUDGE_CREDENTIAL: "k"})
    with pytest.raises(EvaluatorUnavailable) as caught:
        await invoke(judge, evaluators.JUDGE_INSTRUCTIONS, "# Assertions", JudgeAnswer)
    assert len(transport.bodies) == 1  # one request; ChatOpenAI's own retry skips a 400
    assert caught.value.billed is billed
    assert cause in str(caught.value) and len(str(caught.value)) <= 450
    assert "sk-offline" not in str(caught.value)


# ---------------------------------------------------------------------- bridge: bound and causes


class FailingRunner(ScriptedRunner):
    """A judge whose every run fails with ``cause``; the auditor answers."""

    def __init__(self, cause: str, *, billed: bool) -> None:
        super().__init__({"judge": "full_support"})
        self.cause = cause
        self.billed = billed

    async def evaluate(
        self, evaluator: EvaluatorBinding, subject: JudgmentSubject
    ) -> EvaluatorOutput:
        if evaluator.role == "judge":
            self.calls.append("judge")
            raise EvaluatorUnavailable(self.cause, billed=self.billed)
        return await super().evaluate(evaluator, subject)


def standing_waits(rows: Any, subject: JudgmentSubject) -> list[Any]:
    mine = [row for row in rows if row.subject_id == subject.revision.revision_id]
    superseded = {row.supersedes for row in mine if row.supersedes}
    return [
        row for row in mine if row.result == "unavailable" and row.assessment_id not in superseded
    ]


CAUSE = (
    "judge run failed: StructuredOutputValidationError: Failed to parse structured output for "
    "tool 'JudgeAnswer': 1 validation error for JudgeAnswer verdicts.0.rationale Field required"
)


async def test_billed_judge_attempts_are_bounded_per_revision_across_passes() -> None:
    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    first = FailingRunner(CAUSE, billed=True)
    waiting = await w.bridge(first).assess(subject, trusted_evaluators(w), host, use)
    assert first.calls == ["judge", "judge"]  # the bound: 2 billed runs
    assert (waiting.state, waiting.reason, waiting.result) == (
        "waiting",
        "evaluator_unavailable",
        "unavailable",
    )
    assert waiting.exhausted and waiting.causes == (f"judge: {CAUSE}",)
    assert waiting.assessment is not None
    assert f"{ATTEMPTS_PREFIX}judge:2" in waiting.assessment.evidence_refs
    (finding,) = waiting.assessment.findings
    assert (finding.code, finding.pointer) == ("evaluator_attempts_exhausted", "judge")
    assert finding.message == f"judge: {CAUSE}"

    # Later settlement passes (fresh processes over the same stores) never re-run the paid
    # judge; they wait with the recorded cause.
    for _pass in range(3):
        again = FailingRunner(CAUSE, billed=True)
        later = await w.bridge(again).assess(subject, trusted_evaluators(w), host, use)
        assert again.calls == [] and later.exhausted and later.causes == waiting.causes
    rows = await w.stack.store.output_assessments(host.scope, subject.run_id)
    (standing,) = standing_waits(rows, subject)  # one standing wait; earlier ones superseded
    assert standing.assessment_id == waiting.assessment.assessment_id
    assert not [call for call in w.ks.calls if call[0] == "report.seal"]

    # The settlement wait names the cause and that the attempts are exhausted.
    revision = subject.revision.revision_id
    passed = TrustedSettlementPass(
        unavailable=(revision,),
        causes=tuple(f"{revision}: {item}" for item in later.causes),
        exhausted=(revision,),
    )
    with pytest.raises(EvaluatorUnavailable) as raised:
        pending_or_raise(passed)
    detail = SettlementOutcome.unavailable(raised.value)
    assert detail.reason is WaitReason.SETTLEMENT_UNAVAILABLE
    assert detail.detail["code"] == "EVALUATOR_UNAVAILABLE"
    assert detail.detail["reason"] == "evaluator_attempts_exhausted"
    assert detail.detail["issues"] == [f"{revision}: judge: {CAUSE}"[:300]]
    assert "attempts exhausted" in str(raised.value)


async def test_unbilled_failures_record_their_cause_but_do_not_spend_the_bound() -> None:
    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    down = FailingRunner("judge call failed: APIConnectionError: Connection error.", billed=False)
    waiting = await w.bridge(down).assess(subject, trusted_evaluators(w), host, use)
    assert down.calls == ["judge", "judge"] and not waiting.exhausted
    assert waiting.causes == ("judge: judge call failed: APIConnectionError: Connection error.",)
    assert waiting.assessment is not None
    assert not [ref for ref in waiting.assessment.evidence_refs if ref.startswith(ATTEMPTS_PREFIX)]
    assert waiting.assessment.findings[0].code == "evaluator_unavailable"
    # The same unbilled cause again records nothing new; the wait stands.
    repeat = await w.bridge(down).assess(subject, trusted_evaluators(w), host, use)
    assert repeat.assessment == waiting.assessment
    # The provider is back: the judge runs, and the verdict supersedes the one standing wait.
    later = await w.bridge(ScriptedRunner({"judge": "full_support"})).assess(
        subject, trusted_evaluators(w), host, use
    )
    assert later.result == "pass" and later.promoted
    assert later.assessment is not None
    rows = await w.stack.store.output_assessments(host.scope, subject.run_id)
    assert waiting.assessment.assessment_id in {row.supersedes for row in rows}
    assert standing_waits(rows, subject) == []


class FailingObserveHandles(InMemoryKnowledgeHandleStore):
    """The W1 D22 shape: KS accepted the observation handle, the host could not record it."""

    async def record(self, candidate: Any) -> Any:
        if candidate.operation == "report.observe":
            raise RuntimeError(
                'new row for relation "knowledge_operation_handle" violates check constraint '
                '"knowledge_operation_handle_operation_check"'
            )
        return await super().record(candidate)


def failing_bridge(w: World, runner: ScriptedRunner) -> TrustedJudgmentBridge:
    client = TrustedKnowledgeDouble(
        w.ks, verify=w.issuer.verifier().verify, clock=w.clock, binding=BINDING
    )
    gateway = KnowledgeGateway(
        client=client,
        journal=InMemoryKnowledgeJournal(),
        handles=FailingObserveHandles(),
        minter=w.issuer.minter(),
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        clock=w.clock,
    )
    return TrustedJudgmentBridge(
        gateway=gateway,
        fulfillment=w.stack.outputs,
        store=w.stack.store,
        profile=PROFILES[w.application],
        runner=runner,
        judge_pin=JUDGE_PIN,
        retry=EvaluatorRetryPolicy(max_attempts=2),
        clock=w.clock,
    )


async def test_a_lost_observation_handle_is_recovered_without_a_rerun() -> None:
    """W1 (session 6 -> 7): KS accepted an observation, recording its handle failed (D22). The
    next pass reads the operation KS holds for the durable request id (`operation.get`) and
    records its handle: no second KS observation, no extra billed evaluator run, no attempt
    counted; the seal and decision proceed."""

    from mission_control.application.knowledge.judgment import DISPATCH_PREFIX

    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    first = ScriptedRunner({"judge": "full_support"})
    with pytest.raises(RuntimeError, match="knowledge_operation_handle_operation_check"):
        await failing_bridge(w, first).assess(subject, trusted_evaluators(w), host, use)
    assert first.calls == ["judge"]
    observed = [call for call in w.ks.calls if call[0] == "report.observe"]
    assert observed == [("report.observe", "judge", "mc-judge")]  # KS accepted it
    rows = await w.stack.store.output_assessments(host.scope, subject.run_id)
    (wait,) = standing_waits(rows, subject)
    assert any(ref.startswith(f"{DISPATCH_PREFIX}judge:") for ref in wait.evidence_refs)
    assert not [ref for ref in wait.evidence_refs if ref.startswith(ATTEMPTS_PREFIX)]
    assert wait.findings[0].message.startswith("judge: report.observe failed: RuntimeError:")

    # The next pass (healthy handle store): recovered, recorded, judged, no rerun.
    again = ScriptedRunner({"judge": "full_support"})
    bridge = w.bridge(again)
    outcome = await bridge.assess(subject, trusted_evaluators(w), host, use)
    assert again.calls == ["auditor"]  # the judge never ran again
    judged = [call for call in w.ks.calls if call[0] == "report.observe" and call[1] == "judge"]
    assert len(judged) == 1  # no duplicate KS observation
    handles = bridge._gateway._handles.rows.values()  # type: ignore[attr-defined]
    recovered = [h for h in handles if h.operation == "report.observe" and h.state == "succeeded"]
    assert {h.handle.operationId for h in recovered} & set(w.ks.gets)
    assert outcome.result == "pass" and outcome.promoted
    rows = await w.stack.store.output_assessments(host.scope, subject.run_id)
    # The verdict names the recovered role's batch as standing (it was not observed again).
    assert outcome.locked_roles == ("judge",)
    assert standing_waits(rows, subject) == []


async def test_a_dispatch_ks_never_received_lets_the_evaluator_run_again() -> None:
    from mission_control.application.knowledge.judgment import DISPATCH_PREFIX

    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    w.ks.unreachable = True
    first = ScriptedRunner({"judge": "full_support"})
    waiting = await w.bridge(first).assess(subject, trusted_evaluators(w), host, use)
    assert waiting.reason == "evaluator_unavailable" and first.calls == ["judge"]
    assert waiting.assessment is not None
    assert any(r.startswith(f"{DISPATCH_PREFIX}judge:") for r in waiting.assessment.evidence_refs)
    w.ks.unreachable = False
    again = ScriptedRunner({"judge": "full_support"})
    outcome = await w.bridge(again).assess(subject, trusted_evaluators(w), host, use)
    assert again.calls == ["judge", "auditor"] and outcome.result == "pass"
    assert w.ks.gets  # it looked for the dispatched operation first (KS held none)


# ---------------------------------------------------------------------- W1 fix G: S1-S3, N1


async def test_an_unrecordable_wait_is_typed_never_swallowed() -> None:
    from mission_control.application.knowledge.judgment import EvaluatorWaitUnrecorded

    w, subject = await world(review_required=False)
    bridge = w.bridge(FailingRunner(CAUSE, billed=True))

    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("connection reset by peer")

    w.stack.store.record_output_assessment = broken  # type: ignore[method-assign]
    with pytest.raises(EvaluatorWaitUnrecorded) as caught:
        await bridge.assess(subject, trusted_evaluators(w), w.stack.access, w.use())
    assert caught.value.billed and caught.value.code == "EVALUATOR_WAIT_UNRECORDED"


async def test_the_operator_reset_is_audited_and_frees_the_bound() -> None:
    from mission_control.application.knowledge.judgment import (
        RESET_FINDING,
        RESET_PREFIX,
        EvaluatorAttemptReset,
        EvaluatorResetRefused,
    )

    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    exhausted = await w.bridge(FailingRunner(CAUSE, billed=True)).assess(
        subject, trusted_evaluators(w), host, use
    )
    assert exhausted.exhausted and exhausted.assessment is not None
    reset = EvaluatorAttemptReset(w.stack.outputs, w.stack.store, clock=lambda: w.clock.now)
    with pytest.raises(EvaluatorResetRefused) as unknown:
        await reset.reset(
            host.scope, subject.run_id, "no-such-revision", "judge", operator="op-1", reason="x"
        )
    assert unknown.value.code == "not_found"
    with pytest.raises(EvaluatorResetRefused) as idle:
        await reset.reset(
            host.scope,
            subject.run_id,
            subject.revision.revision_id,
            "auditor",
            operator="op-1",
            reason="x",
        )
    assert idle.value.code == "nothing_to_reset"
    recorded = await reset.reset(
        host.scope,
        subject.run_id,
        subject.revision.revision_id,
        "judge",
        operator="op-1",
        reason="judge schema fixed",
    )
    assert recorded.supersedes == exhausted.assessment.assessment_id
    assert recorded.assessor_origin_ref == f"{RESET_PREFIX}{subject.revision.revision_id}:op-1"
    assert [f.message for f in recorded.findings if f.code == RESET_FINDING] == [
        "judge: attempts reset by op-1: judge schema fixed"
    ]
    assert any(ref.startswith(f"{RESET_PREFIX}judge:") for ref in recorded.evidence_refs)
    assert not [ref for ref in recorded.evidence_refs if ref.startswith(ATTEMPTS_PREFIX)]
    with pytest.raises(EvaluatorResetRefused):  # nothing left to reset
        await reset.reset(
            host.scope,
            subject.run_id,
            subject.revision.revision_id,
            "judge",
            operator="op-1",
            reason="again",
        )
    later = ScriptedRunner({"judge": "full_support"})
    passed = await w.bridge(later).assess(subject, trusted_evaluators(w), host, use)
    assert later.calls == ["judge", "auditor"] and passed.result == "pass"
    rows = await w.stack.store.output_assessments(host.scope, subject.run_id)
    assert passed.assessment is not None and recorded.assessment_id in {r.supersedes for r in rows}
    assert standing_waits(rows, subject) == []


async def test_a_ks_refusal_stays_on_every_later_wait() -> None:
    from mission_control.application.knowledge.judgment import (
        KS_REFUSAL_PREFIX,
        TrustedJudgmentRefused,
    )

    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    bridge = w.bridge(FailingRunner(CAUSE, billed=True))
    refused = TrustedJudgmentRefused(
        "INVALID_ENVELOPE",
        "the census is not a valid discovery",
        reason="census_invalid",
        issues=("occurrences.0.span: Required",),
        billed=True,
    )
    await bridge._refused_record(subject, host, use, "auditor", refused)
    await bridge._record_wait(subject, host, use, "judge", CAUSE, billed=True)
    rows = await w.stack.store.output_assessments(host.scope, subject.run_id)
    from mission_control.application.knowledge.judgment import standing_wait

    wait = standing_wait(rows, subject.revision)
    assert wait is not None
    assert any(
        ref.startswith(f"{KS_REFUSAL_PREFIX}auditor:INVALID_ENVELOPE") for ref in wait.evidence_refs
    )
    assert {f.code for f in wait.findings} >= {
        "ks_invalid_envelope",
        "ks_issue",
        "evaluator_unavailable",
    }
    assert f"{ATTEMPTS_PREFIX}auditor:1" in wait.evidence_refs  # the refused billed run counted
    assert f"{ATTEMPTS_PREFIX}judge:1" in wait.evidence_refs


def _wrapped(inner: BaseException, outer: type) -> BaseException:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    try:
        try:
            raise inner
        except BaseException as error:
            raise outer(request=request) from error
    except BaseException as wrapped:
        return wrapped


def test_unsent_transport_failures_are_unbilled_and_sent_timeouts_billed() -> None:
    import openai

    billed = evaluators._billed
    assert not billed(_wrapped(httpx.ConnectTimeout("connect"), openai.APITimeoutError))
    assert not billed(_wrapped(httpx.PoolTimeout("pool"), openai.APITimeoutError))
    assert billed(_wrapped(httpx.ReadTimeout("read"), openai.APITimeoutError))
    assert not billed(_wrapped(httpx.ConnectError("refused"), openai.APIConnectionError))
    assert not billed(httpx.ConnectError("raw transport, not wrapped"))
    assert not billed(ConnectionResetError("reset before an answer"))
    assert billed(TimeoutError())  # unknown whether it was sent: counted
    assert billed(RuntimeError("after the model answered"))


async def test_recovery_while_ks_is_unreachable_waits_and_never_reruns() -> None:
    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    with pytest.raises(RuntimeError):
        await failing_bridge(w, ScriptedRunner({"judge": "full_support"})).assess(
            subject, trusted_evaluators(w), host, use
        )
    w.ks.unreachable = True
    blocked = ScriptedRunner({"judge": "full_support"})
    with pytest.raises(EvaluatorUnavailable, match="recovering the judge observation failed"):
        await w.bridge(blocked).assess(subject, trusted_evaluators(w), host, use)
    assert blocked.calls == []  # unknown whether KS holds it: no paid rerun


async def test_a_recovered_operation_naming_another_id_is_refused_typed() -> None:
    from mission_control.application.knowledge.judgment import TrustedJudgmentRefused

    w, subject = await world(review_required=False)
    host, use = w.stack.access, w.use()
    with pytest.raises(RuntimeError):
        await failing_bridge(w, ScriptedRunner({"judge": "full_support"})).assess(
            subject, trusted_evaluators(w), host, use
        )
    (op_id,) = [key for key in w.ks.operations if key.startswith("op-report-observe-")]
    status = w.ks.operations[op_id]
    forged = status.handle.model_copy(update={"operationId": "op-report-observe-forged"})
    w.ks.operations[op_id] = status.model_copy(update={"handle": forged})
    runner = ScriptedRunner({"judge": "full_support"})
    with pytest.raises(TrustedJudgmentRefused, match="answered op-report-observe-forged"):
        await w.bridge(runner).assess(subject, trusted_evaluators(w), host, use)
    assert runner.calls == []  # never adopted, never re-run

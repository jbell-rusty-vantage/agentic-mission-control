"""W1 D18 review: the host enforcement of ``tool_auto`` (structured_response.py).

S1 a JSON string for an object-typed field of the response tool is parsed once (D17 rules) and a
refused call is retried within one bound; S2 a response call made together with other tool calls
is refused (append-only) so the other calls run first; S3 the attempt count survives an
interleaved human message; S4 the pins and sealed components of every row this change does not
target are byte-identical to the base (golden digests computed at 77783f30); N3 the wrapped
client keeps the model's own identity. No network: scripted fake models and offline clients.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.load import dumpd
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, SecretStr, ValidationError

from mission_control.adapters.deep_agents.structured_response import (
    ATTEMPT_MARKER,
    MAX_ATTEMPTS,
    RequireStructuredResponse,
    response_schema,
    with_auto_tool_choice,
)

DEPLOYMENTS = Path(__file__).resolve().parents[3] / "deployments"


class Detail(BaseModel):
    reason: str


class Verdict(BaseModel):
    met: bool
    detail: Detail


@tool
def ping(text: str) -> str:
    """Echo the text."""
    return f"pong {text}"


class _Scripted(GenericFakeChatModel):
    calls: int = 0

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        del tools, kwargs
        return self

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        type(self).calls += 1
        return await super()._agenerate(*args, **kwargs)


def _call(args: Any, call_id: str, name: str = "Verdict") -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id}


def _agent(answers: list[AIMessage]) -> Any:
    _Scripted.calls = 0
    return create_agent(
        _Scripted(messages=iter(answers)),
        tools=[ping],
        response_format=ToolStrategy(response_schema(Verdict)),
        middleware=[RequireStructuredResponse(["Verdict"])],
    )


async def _run(agent: Any) -> dict[str, Any]:
    return await agent.ainvoke({"messages": [{"role": "user", "content": "go"}]})


# -- S1 -------------------------------------------------------------------------------------------


def test_the_response_schema_keeps_the_model_facing_schema_and_parses_json_strings() -> None:
    coercing = response_schema(Verdict)
    assert coercing.model_json_schema() == Verdict.model_json_schema()
    parsed = coercing.model_validate({"met": True, "detail": '{"reason": "quoted"}'})
    assert parsed.detail == Detail(reason="quoted")
    for bad in ('{"reason": "x"} trailing', '["not", "an object"]', '{"reason": 1, "reason": 2}'):
        with pytest.raises(ValidationError, match="detail"):
            coercing.model_validate({"met": True, "detail": bad})
    assert response_schema({"type": "object"}) == {"type": "object"}


@pytest.mark.asyncio
async def test_a_string_valued_nested_object_becomes_the_callers_own_schema() -> None:
    result = await _run(
        _agent(
            [
                AIMessage(
                    content="", tool_calls=[_call({"met": True, "detail": '{"reason": "r"}'}, "v1")]
                )
            ]
        )
    )
    assert type(result["structured_response"]) is Verdict
    assert result["structured_response"] == Verdict(met=True, detail=Detail(reason="r"))


@pytest.mark.asyncio
async def test_refused_response_calls_are_retried_within_one_bound() -> None:
    invalid = [
        AIMessage(content="", tool_calls=[_call({"met": True, "detail": "{broken"}, f"v{i}")])
        for i in range(MAX_ATTEMPTS + 3)
    ]
    result = await _run(_agent(invalid))
    assert result.get("structured_response") is None
    assert _Scripted.calls == MAX_ATTEMPTS  # never an unbounded validation loop
    refused = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(refused) == MAX_ATTEMPTS
    assert all(ATTEMPT_MARKER in m.additional_kwargs for m in refused)


# -- S2 -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_response_call_mixed_with_other_calls_is_refused_and_the_others_run() -> None:
    answers = [
        AIMessage(
            content="",
            tool_calls=[
                _call({"text": "a"}, "p1", name="ping"),
                _call({"met": False, "detail": {"reason": "early"}}, "v1"),
            ],
        ),
        AIMessage(
            content="", tool_calls=[_call({"met": True, "detail": {"reason": "late"}}, "v2")]
        ),
    ]
    result = await _run(_agent(answers))
    assert result["structured_response"] == Verdict(met=True, detail=Detail(reason="late"))
    by_id = {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}
    assert by_id["p1"].content == "pong a"  # the other call ran
    assert by_id["v1"].status == "error" and "alone" in str(by_id["v1"].content)
    first = next(m for m in result["messages"] if isinstance(m, AIMessage))
    assert [c["id"] for c in first.tool_calls] == ["p1", "v1"]  # never edited (append-only)


# -- S3 -------------------------------------------------------------------------------------------


def test_an_interleaved_human_message_never_resets_the_attempt_count() -> None:
    middleware = RequireStructuredResponse(["Verdict"])
    marked = {ATTEMPT_MARKER: "unscoped"}
    messages: list[Any] = [HumanMessage(content="go")]
    for index in range(MAX_ATTEMPTS):
        messages += [
            AIMessage(content=f"text {index}"),
            HumanMessage(content="r", additional_kwargs=marked),
        ]
    messages += [HumanMessage(content="operator note"), AIMessage(content="still text")]
    assert middleware._decision({"messages": messages}) is None  # spent: no further reminder
    other_scope = [
        HumanMessage(content="r", additional_kwargs={ATTEMPT_MARKER: "earlier-invocation"})
        for _ in range(MAX_ATTEMPTS)
    ]
    fresh = middleware._decision({"messages": [*other_scope, AIMessage(content="text")]})
    assert fresh is not None and fresh["jump_to"] == "model"  # another invocation's count


# -- N3 -------------------------------------------------------------------------------------------


def test_the_wrapped_client_keeps_the_models_identity_through_copy_and_bind() -> None:
    original = ChatAnthropic(model_name="claude-sonnet-5-5", api_key=SecretStr("k"), max_tokens=64)
    wrapped = with_auto_tool_choice(original)
    assert (
        type(wrapped).__name__ == "ChatAnthropic" and type(wrapped).__qualname__ == "ChatAnthropic"
    )
    assert type(wrapped).lc_id() == type(original).lc_id()
    assert dumpd(wrapped)["id"] == dumpd(original)["id"]
    assert wrapped._get_invocation_params() == original._get_invocation_params()  # type: ignore[attr-defined]
    assert wrapped._get_llm_string() == original._get_llm_string()  # type: ignore[attr-defined]
    copied = wrapped.model_copy()
    assert type(copied) is type(wrapped) and with_auto_tool_choice(copied) is copied
    bound = copied.bind_tools([ping], tool_choice="any")
    assert bound.kwargs["tool_choice"] == {"type": "auto"}  # type: ignore[attr-defined]
    assert type(bound.bound) is type(wrapped)  # type: ignore[attr-defined]
    assert original.bind_tools([ping], tool_choice="any").kwargs["tool_choice"] == {"type": "any"}  # type: ignore[attr-defined]


# -- S4 -------------------------------------------------------------------------------------------

# (pin digest, sealed DeepAgentModelComponent digest) per row this change does not target,
# computed at base 77783f30 with the same code below; both applications carry the same rows.
GOLDEN = {
    "producer.fallback": (
        "sha256:463bb573342859a9a5c82dff648d26d722e642d3798c046225d09ad0a3bfeb86",
        "sha256:359f025de7362cb5305b78cbcbb6cb102e4b1a48bdd3ac0455e5f23c3eeb9d28",
    ),
    "judge.default": (
        "sha256:a2e19b2908cb61624e06c80279275546f43b0a5cda1c02bd4cbc294aa46d1505",
        "sha256:1ea657abd20cf3fc87805bb638e27ed96973093e0a36f1047a9eeaca3f6e1bac",
    ),
    "judge.fallback": (
        "sha256:b3cec59b7b3c1329504653c6285115509fd61832b949ceab402741e6446963a9",
        "sha256:497e66a5b188619bcddd41ac7bc58eb1886bf8feff2ce0cd6adc6363987e7cf2",
    ),
    "auditor.default": (
        "sha256:530ddb9b51f43253c178e62a8c4d29074088c91474b5fb6f4506a658231e1fb9",
        "sha256:359f025de7362cb5305b78cbcbb6cb102e4b1a48bdd3ac0455e5f23c3eeb9d28",
    ),
    "child.default": (
        "sha256:587d6cc1e9bd4416589824a1a4c2728089a2870402b0d6aa5899d7a5fa41be7c",
        "sha256:359f025de7362cb5305b78cbcbb6cb102e4b1a48bdd3ac0455e5f23c3eeb9d28",
    ),
    "child.fallback": (
        "sha256:ba6ae209f53b3cefab169706d561d5b6f2d14b55060b042213ab46bba2f9afad",
        "sha256:497e66a5b188619bcddd41ac7bc58eb1886bf8feff2ce0cd6adc6363987e7cf2",
    ),
    "probe.default": (
        "sha256:dd6540006eec43871438394f464752f4462c2e2970b7e647b4a56e908840de83",
        "sha256:497e66a5b188619bcddd41ac7bc58eb1886bf8feff2ce0cd6adc6363987e7cf2",
    ),
    "probe.fallback": (
        "sha256:af4f69a780ed4e08b66849b6551c81ccba20b25b533ac40303c2b7fa9f408807",
        "sha256:e10d51a0c24e32d216cd7094fae7feaa21b1312f994e632429f51fe8da81c72b",
    ),
}
GOLDEN_OTHER_LANE_ROUTES = "sha256:4a2df56906964a20a597d1fbcaa7d4d6e1886e7b77a97e45901d593f7fc3419c"


@pytest.mark.parametrize("application", ["ai-engineer", "biotech"])
def test_rows_this_change_does_not_target_keep_their_pin_and_component_digests(
    application: str,
) -> None:
    from mission_control.adapters.claude.describe import _CLAUDE_ROUTES
    from mission_control.adapters.cursor.describe import _CURSOR_ROUTES
    from mission_control.bootstrap.model_profiles import load_model_catalog_file
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
    from mission_control.domain.execution.contracts import DeepAgentModelComponent

    ref = ExactDefinitionRef(
        kind=DefinitionKind.MODEL,
        logical_id="model.golden",
        revision=1,
        digest=sha256_digest("golden"),
    )
    rows = load_model_catalog_file(DEPLOYMENTS / application / "models.toml").models
    seen = {}
    for row in rows:
        if row.model_id == "claude-sonnet-5-5":
            continue  # the rows D18 targets (tool_auto)
        component = DeepAgentModelComponent(
            ref=ref,
            provider=row.vendor,
            model_name=row.model_id,
            structured_output=row.structured_output,
        )
        seen[row.profile] = (sha256_digest(row.pin()), sha256_digest(component))
    assert seen == GOLDEN
    routes = [route.model_dump(mode="json") for route in (*_CLAUDE_ROUTES, *_CURSOR_ROUTES)]
    assert sha256_digest(routes) == GOLDEN_OTHER_LANE_ROUTES
    assert json.dumps(routes)  # serializable as the listing serves it

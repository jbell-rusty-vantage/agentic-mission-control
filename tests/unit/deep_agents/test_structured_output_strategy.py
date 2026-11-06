"""W1 D16: the structured-output strategy is a declared per-model capability.

The pinned producer (`claude-sonnet-5-5`) answered the lane's first model call with 400
`tool_choice: type "tool" and "any" are not supported for this model` (run 0da30ad0): the lane
passed a raw schema, LangChain auto-detection found no profile for the model and chose
`ToolStrategy`, which forces `tool_choice` any. Each `models.toml` row now declares
`tool_forced` or `provider_native`; the compile carries it into the sealed model component,
the materializer wraps the schema in exactly that strategy, and a missing or unrouted strategy
fails closed. No paid call: the Anthropic request payload is built offline.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import BaseModel, SecretStr, ValidationError

from mission_control.adapters.deep_agents import compile as compile_module
from mission_control.adapters.deep_agents.compile import DeepAgentsCompileAdapter
from mission_control.adapters.deep_agents.materializer import response_format_for
from mission_control.adapters.deep_agents.output_format import (
    AnthropicOutputSchemaRefused,
    anthropic_output_schema,
    output_schema_issues,
)
from mission_control.adapters.deep_agents.routes import DEEP_AGENTS_MODEL_ROUTES
from mission_control.bootstrap.model_profiles import load_model_catalog_file
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.execution.contracts import DeepAgentModelComponent
from mission_control.domain.execution.errors import DeepAgentMaterializationError
from mission_control.domain.programs.goal_directed_runtime import GoalExecutorObservation
from mission_control.domain.resolution.profiles import ModelProfile, ModelRoute
from mission_control.domain.resolution.resolved import LaneCompileRefused

DEPLOYMENTS = Path(__file__).resolve().parents[3] / "deployments"


class Verdict(BaseModel):
    met: bool


def _row(**values: Any) -> dict[str, Any]:
    return {
        "profile": "producer.default",
        "vendor": "anthropic",
        "model_id": "claude-sonnet-5-5",
        "context_window_tokens": 1_000_000,
        "max_input_tokens": 1_000_000,
        "cost_per_million_input": 2.0,
        "cost_per_million_output": 10.0,
        "supports": ("structured_output", "tool_use"),
        "structured_output": "provider_native",
        "data_class_ceiling": "internal",
        **values,
    }


def _component(strategy: str | None, model: str = "claude-sonnet-5-5") -> DeepAgentModelComponent:
    return DeepAgentModelComponent(
        ref=ExactDefinitionRef(
            kind=DefinitionKind.MODEL, logical_id=f"model.{model}", revision=1, digest=_DIGEST
        ),
        provider="anthropic",
        model_name=model,
        structured_output=strategy,  # type: ignore[arg-type]
    )


_DIGEST = sha256_digest({"model": "fixture"})

# -- the catalog row ----------------------------------------------------------------------------


def test_a_row_supporting_structured_output_must_declare_its_strategy() -> None:
    assert ModelProfile.model_validate(_row()).structured_output == "provider_native"
    with pytest.raises(ValidationError, match="declares no structured_output strategy"):
        ModelProfile.model_validate(_row(structured_output=None))
    with pytest.raises(ValidationError, match="supports omits structured_output"):
        ModelProfile.model_validate(_row(supports=("tool_use",)))
    with pytest.raises(ValidationError):
        ModelProfile.model_validate(_row(structured_output="json_mode"))


@pytest.mark.parametrize("application", ["ai-engineer", "biotech"])
def test_the_checked_in_rows_declare_the_vendor_supported_strategy(application: str) -> None:
    rows = load_model_catalog_file(DEPLOYMENTS / application / "models.toml").models
    for row in rows:
        assert row.structured_output is not None, row.profile
    by_model = {row.model_id: row.structured_output for row in rows}
    # Sonnet 5.5 rejects forced tool choice; Haiku 5.5 accepts it (W1 runs 361d04a8/3081b3e4).
    # D18: Sonnet 5.5 compiled the executor observation as "Schema is too complex".
    assert by_model["claude-sonnet-5-5"] == "tool_auto"
    assert by_model["claude-haiku-5-5"] == "tool_forced"
    assert {row.profile for row in rows if row.model_id == "claude-sonnet-5-5"} >= {
        "producer.default"
    }


def test_the_pin_carries_the_strategy_and_an_undeclared_pin_keeps_its_digest() -> None:
    row = ModelProfile.model_validate(_row())
    assert row.pin().structured_output == "provider_native"
    bare = ModelProfile.model_validate(_row(supports=("tool_use",), structured_output=None)).pin()
    assert "structured_output" not in bare.model_dump()
    assert sha256_digest(bare) == sha256_digest(bare.model_copy(update={"structured_output": None}))
    # A component without a strategy keeps the digest it had before the field existed.
    legacy = _component(None)
    assert "structured_output" not in legacy.model_dump()


# -- the materializer ---------------------------------------------------------------------------


def test_the_materializer_wraps_the_schema_in_the_declared_strategy() -> None:
    forced = response_format_for(Verdict, _component("tool_forced", "claude-haiku-5-5"))
    native = response_format_for(Verdict, _component("provider_native"))
    assert isinstance(forced, ToolStrategy) and forced.schema is Verdict
    assert isinstance(native, ProviderStrategy) and native.schema is Verdict
    with pytest.raises(DeepAgentMaterializationError, match="declares no structured_output"):
        response_format_for(Verdict, _component(None))


class _RecordingModel(GenericFakeChatModel):
    """Records what `create_agent` binds; answers from its scripted messages."""

    bound: list[dict[str, Any]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        type(self).bound.append({"tools": [getattr(t, "name", t) for t in tools], **kwargs})
        return self


@tool
def ping(text: str) -> str:
    """Echo the text."""
    return text


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["tool_forced", "provider_native"])
async def test_only_tool_forced_forces_tool_choice(strategy: str) -> None:
    _RecordingModel.bound = []
    answer = (
        AIMessage(content="", tool_calls=[{"name": "Verdict", "args": {"met": True}, "id": "v"}])
        if strategy == "tool_forced"
        else AIMessage(content='{"met": true}')
    )
    agent = create_agent(
        _RecordingModel(messages=iter([answer])),
        tools=[ping],
        response_format=response_format_for(Verdict, _component(strategy)),
    )
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "go"}]})
    assert result["structured_response"] == Verdict(met=True)
    (bound,) = _RecordingModel.bound
    if strategy == "tool_forced":
        assert bound["tool_choice"] == "any" and "Verdict" in bound["tools"]
    else:
        assert bound.get("tool_choice") is None and "Verdict" not in bound["tools"]
        assert bound["response_format"]["type"] == "json_schema"


def test_provider_native_on_sonnet_sends_output_config_format_and_no_tool_choice() -> None:
    """Offline: the exact Anthropic request body langchain-anthropic builds for a schema inside
    the subset (the judge answer) under `provider_native` (no network, no key)."""

    from mission_control.adapters.deep_agents.evaluators import JudgeAnswer

    model = ChatAnthropic(
        model_name="claude-sonnet-5-5", api_key=SecretStr("offline"), max_tokens=1024
    )
    strategy = response_format_for(JudgeAnswer, _component("provider_native"))
    assert isinstance(strategy, ProviderStrategy)
    bound = model.bind_tools([ping], **strategy.to_model_kwargs())
    payload = model._get_request_payload([("user", "go")], **bound.kwargs)  # type: ignore[attr-defined]
    assert "tool_choice" not in payload
    assert payload["output_config"]["format"]["type"] == "json_schema"
    assert payload["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert [item["name"] for item in payload["tools"]] == ["ping"]


# -- the compile ---------------------------------------------------------------------------------


def _compile_model(pin_strategy: str | None, routes: tuple[ModelRoute, ...]) -> Any:
    pin = SimpleNamespace(
        vendor="anthropic",
        profile="producer.default",
        model_id="claude-sonnet-5-5",
        settings={},
        structured_output=pin_strategy,
    )
    served = _component(None)
    facts = SimpleNamespace(
        model_profiles={"producer.default": served},
        served=SimpleNamespace(models={served.ref.digest}),
    )
    declaration = SimpleNamespace(
        route=lambda vendor: next(r for r in routes if r.vendor == vendor)
    )
    original = compile_module.DEEP_AGENTS_DECLARATION
    compile_module.DEEP_AGENTS_DECLARATION = declaration  # type: ignore[assignment]
    try:
        return DeepAgentsCompileAdapter._model(SimpleNamespace(model=pin), facts)  # type: ignore[arg-type]
    finally:
        compile_module.DEEP_AGENTS_DECLARATION = original


def test_the_compile_seals_the_pins_strategy_into_the_model_component() -> None:
    component, _, _ = _compile_model("provider_native", DEEP_AGENTS_MODEL_ROUTES)
    assert component.structured_output == "provider_native"
    assert component.model_name == "claude-sonnet-5-5"


def test_the_compile_refuses_a_strategy_the_lane_route_does_not_realize() -> None:
    routes = (ModelRoute(vendor="anthropic", verdict="native", mechanism="chat_anthropic_factory"),)
    with pytest.raises(LaneCompileRefused, match="does not realize the provider_native") as raised:
        _compile_model("provider_native", routes)
    assert raised.value.refusal.code == "MODEL_ROUTE_UNSUPPORTED"


def test_the_deep_agents_routes_realize_every_strategy() -> None:
    for route in DEEP_AGENTS_MODEL_ROUTES:
        assert set(route.structured_output) == {"tool_forced", "provider_native", "tool_auto"}


# -- the Anthropic output_config.format subset (review S3) -------------------------------------


def _every_registered_schema() -> list[type[BaseModel]]:
    from mission_control.adapters.deep_agents.evaluators import AuditorAnswer, JudgeAnswer
    from mission_control.adapters.temporal.deployment_composition import goal_output_schemas

    return [*goal_output_schemas().values(), JudgeAnswer, AuditorAnswer]


def _anthropic_rows() -> list[tuple[str, str, str]]:
    from mission_control.bootstrap.model_profiles import load_model_catalog_file

    rows = []
    for application in ("ai-engineer", "biotech"):
        for row in load_model_catalog_file(DEPLOYMENTS / application / "models.toml").models:
            rows.append((application, row.profile, row.vendor))
    return rows


@pytest.mark.parametrize("schema", _every_registered_schema(), ids=lambda model: model.__name__)
@pytest.mark.parametrize(("application", "profile", "vendor"), _anthropic_rows())
def test_every_registered_schema_binds_on_every_model_row(
    schema: type[BaseModel], application: str, profile: str, vendor: str
) -> None:
    """D18: every real executor, verifier and evaluator schema binds on every checked-in row
    through that row's declared strategy, offline, before any call (no row can reach the wire
    with a schema its strategy cannot carry)."""

    from mission_control.bootstrap.model_profiles import load_model_catalog_file

    row = next(
        item
        for item in load_model_catalog_file(DEPLOYMENTS / application / "models.toml").models
        if item.profile == profile
    )
    component = DeepAgentModelComponent(
        ref=ExactDefinitionRef(
            kind=DefinitionKind.MODEL, logical_id="model.row", revision=1, digest=_DIGEST
        ),
        provider=row.vendor,
        model_name=row.model_id,
        structured_output=row.structured_output,
    )
    strategy = response_format_for(schema, component)  # raises OutputSchemaUnsupported if not
    if row.structured_output in ("tool_forced", "tool_auto"):
        assert isinstance(strategy, ToolStrategy)
    else:
        assert isinstance(strategy, ProviderStrategy)


@pytest.mark.parametrize("schema", _every_registered_schema(), ids=lambda model: model.__name__)
def test_the_complexity_check_matches_what_anthropic_compiles(schema: type[BaseModel]) -> None:
    """The goal observations exceed the grammar budget (the executor's failed live, D18); the
    evaluator answers are inside the subset and are sent byte for byte as checked."""

    if schema.__name__.startswith("Goal"):
        with pytest.raises(AnthropicOutputSchemaRefused, match="too complex"):
            anthropic_output_schema(schema)
        with pytest.raises(DeepAgentMaterializationError, match="tool_auto"):
            response_format_for(schema, _component("provider_native"))
        return
    sent = anthropic_output_schema(schema)
    assert output_schema_issues(sent) == ()
    model = ChatAnthropic(
        model_name="claude-sonnet-5-5", api_key=SecretStr("offline"), max_tokens=1024
    )
    bound = model.bind_tools([ping], **ProviderStrategy(schema).to_model_kwargs())
    payload = model._get_request_payload([("user", "go")], **bound.kwargs)  # type: ignore[attr-defined]
    assert payload["output_config"]["format"]["schema"] == sent


class _Node(BaseModel):
    label: str
    children: list[_Node] = []


def test_a_schema_outside_the_subset_is_refused_before_any_model_call() -> None:
    with pytest.raises(AnthropicOutputSchemaRefused, match="recursive"):
        anthropic_output_schema(_Node)
    with pytest.raises(DeepAgentMaterializationError, match="cannot bind provider_native"):
        response_format_for(_Node, _component("provider_native"))
    # tool_forced binds the tool schema, not output_config.format: no subset check applies.
    assert isinstance(response_format_for(_Node, _component("tool_forced")), ToolStrategy)
    issues = output_schema_issues(
        {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 1}, "s": {"format": "ipv9"}},
            "additionalProperties": True,
        }
    )
    assert any("additionalProperties false" in item for item in issues)
    assert any("minimum" in item for item in issues)
    assert any("ipv9" in item for item in issues)


def test_the_trusted_path_refuses_to_compose_an_unbindable_evaluator_row() -> None:
    """Review S3-b, moved earlier: the evaluator rows and answer schemas are known at
    composition, so a row without a strategy never becomes a durable evaluator wait."""

    from mission_control.bootstrap.trusted_judgment import (
        TrustedCompositionError,
        _check_evaluator_schemas,
    )

    judge = ModelProfile.model_validate(
        _row(
            profile="judge.default",
            vendor="openai",
            model_id="gpt-5.6-terra",
            structured_output="tool_forced",
            api_surface="responses",
        )
    )
    auditor = ModelProfile.model_validate(_row(profile="auditor.default"))
    _check_evaluator_schemas(judge, auditor)  # both bind
    # W1 D24: an OpenAI tool-calling judge on chat completions never composes.
    chat = judge.model_copy(update={"api_surface": None})
    with pytest.raises(TrustedCompositionError, match="API_SURFACE_UNSUPPORTED"):
        _check_evaluator_schemas(chat, auditor)
    bare = auditor.model_copy(update={"supports": ("tool_use",), "structured_output": None})
    with pytest.raises(TrustedCompositionError, match="OUTPUT_SCHEMA_UNSUPPORTED"):
        _check_evaluator_schemas(judge, bare)


# -- tool_auto (W1 D18) ------------------------------------------------------------------------


def test_the_executor_schema_at_the_published_limits_is_refused_typed() -> None:
    from mission_control.adapters.deep_agents.output_format import complexity
    from mission_control.domain.execution.errors import OutputSchemaUnsupported

    properties, optional, unions = complexity(_transformed(GoalExecutorObservation))
    assert (properties, optional, unions) == (30, 23, 1)  # inside the published 24/16 limits
    with pytest.raises(OutputSchemaUnsupported, match="too complex"):
        response_format_for(GoalExecutorObservation, _component("provider_native"))


def _transformed(schema: type[BaseModel]) -> dict[str, Any]:
    from langchain_anthropic.chat_models import _convert_to_anthropic_output_config_format

    return _convert_to_anthropic_output_config_format(schema)["schema"]


def test_tool_auto_never_forces_the_tool_in_the_anthropic_request() -> None:
    """Offline: Sonnet 5.5 under `tool_auto` gets the observation as an ordinary tool with
    `tool_choice` auto and no `output_config.format` (no grammar to compile)."""

    from mission_control.adapters.deep_agents.structured_response import with_auto_tool_choice

    model = with_auto_tool_choice(
        ChatAnthropic(model_name="claude-sonnet-5-5", api_key=SecretStr("offline"), max_tokens=64)
    )
    assert model.model == "claude-sonnet-5-5"  # same client, same settings
    strategy = response_format_for(GoalExecutorObservation, _component("tool_auto"))
    assert isinstance(strategy, ToolStrategy)
    tool = strategy.schema_specs[0]
    bound = model.bind_tools([ping, tool.json_schema | {"title": tool.name}], tool_choice="any")
    payload = model._get_request_payload([("user", "go")], **bound.kwargs)  # type: ignore[attr-defined]
    assert payload["tool_choice"] == {"type": "auto"}
    assert "output_config" not in payload or "format" not in payload["output_config"]
    assert {item["name"] for item in payload["tools"]} == {"ping", tool.name}


class _AutoModel(GenericFakeChatModel):
    bound: list[dict[str, Any]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        type(self).bound.append({"tools": [getattr(t, "name", t) for t in tools], **kwargs})
        return self


@pytest.mark.asyncio
async def test_tool_auto_reminds_a_turn_that_ends_without_the_call_then_gives_up() -> None:
    from mission_control.adapters.deep_agents.structured_response import (
        MAX_REMINDERS,
        REMINDER_PREFIX,
        RequireStructuredResponse,
        with_auto_tool_choice,
    )

    _AutoModel.bound = []
    answers = [
        AIMessage(content="done, I think"),
        AIMessage(content="", tool_calls=[{"name": "Verdict", "args": {"met": True}, "id": "v"}]),
    ]
    strategy = response_format_for(Verdict, _component("tool_auto"))
    agent = create_agent(
        with_auto_tool_choice(_AutoModel(messages=iter(answers))),
        tools=[ping],
        response_format=strategy,
        middleware=[RequireStructuredResponse(["Verdict"])],
    )
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "go"}]})
    assert result["structured_response"] == Verdict(met=True)
    reminders = [
        m for m in result["messages"] if str(getattr(m, "content", "")).startswith(REMINDER_PREFIX)
    ]
    assert len(reminders) == 1
    assert all(item["tool_choice"] == "auto" for item in _AutoModel.bound)

    # A model that never calls it: bounded reminders, then the turn ends without a result.
    _AutoModel.bound = []
    silent = [AIMessage(content=f"text {i}") for i in range(MAX_REMINDERS + 1)]
    agent = create_agent(
        with_auto_tool_choice(_AutoModel(messages=iter(silent))),
        tools=[ping],
        response_format=strategy,
        middleware=[RequireStructuredResponse(["Verdict"])],
    )
    ended = await agent.ainvoke({"messages": [{"role": "user", "content": "go"}]})
    assert "structured_response" not in ended or ended["structured_response"] is None
    assert len(_AutoModel.bound) == MAX_REMINDERS + 1

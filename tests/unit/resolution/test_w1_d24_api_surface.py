"""W1 D24 (OVE-169): OpenAI rows with tool use declare the Responses API, fail closed otherwise.

OpenAI answered every judge call on /v1/chat/completions with 400 "Function tools with
reasoning_effort are not supported for gpt-5.6-terra in /v1/chat/completions. To use function
tools, use /v1/responses or set reasoning_effort to 'none'." A Model Catalog row now names its API
surface; an OpenAI row whose calls carry function tools (tool use, or a tool-based structured-output
strategy) must declare `responses`, refused at catalog load (before compile or launch); the lane
compiles the row's surface into the model component (`use_responses_api`), and the evaluator
composition refuses a chat-completions judge.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.adapters.deep_agents.compile import catalog_model_components
from mission_control.bootstrap.model_profiles import ModelCatalogFile, compose_model_catalog
from mission_control.domain.resolution.profiles import ModelProfile
from tests.fixtures.models import DEPLOYMENTS, fixture_model_catalog
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings


def row(**values: Any) -> dict[str, Any]:
    return {
        "profile": "judge.default",
        "vendor": "openai",
        "model_id": "gpt-5.6-terra",
        "context_window_tokens": 1_050_000,
        "max_input_tokens": 922_000,
        "cost_per_million_input": 2.0,
        "cost_per_million_output": 12.0,
        "supports": ["structured_output", "tool_use", "images"],
        "structured_output": "tool_forced",
        "api_surface": "responses",
        "data_class_ceiling": "internal",
        **values,
    }


@pytest.mark.parametrize("application", ["ai-engineer", "biotech"])
def test_every_checked_in_openai_row_uses_the_responses_api(application: str) -> None:
    catalog = compose_model_catalog(DEPLOYMENTS, application)
    openai = [
        catalog.get(name) for name in catalog.profiles() if catalog.get(name).vendor == "openai"
    ]
    assert {item.model_id for item in openai} == {"gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.4-mini"}
    assert all(item.api_surface == "responses" for item in openai)
    others = [
        catalog.get(name) for name in catalog.profiles() if catalog.get(name).vendor != "openai"
    ]
    assert all(item.api_surface is None for item in others)


@pytest.mark.parametrize(
    "values",
    [
        {"api_surface": None},
        {"api_surface": "chat_completions"},
        {"model_id": "gpt-5.4-mini", "structured_output": "provider_native", "api_surface": None},
    ],
)
def test_a_tool_calling_openai_row_on_chat_completions_is_refused_at_load(
    values: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="API_SURFACE_UNSUPPORTED"):
        ModelCatalogFile.model_validate({"models": [row(**values)]})


def test_a_toolless_openai_row_may_use_chat_completions_and_others_never_declare() -> None:
    plain = row(supports=["images"], structured_output=None, api_surface="chat_completions")
    assert ModelCatalogFile.model_validate({"models": [plain]}).models[0].api_surface == (
        "chat_completions"
    )
    with pytest.raises(ValueError, match="only OpenAI rows"):
        ModelProfile.model_validate(
            row(vendor="anthropic", model_id="claude-haiku-5-5", api_surface="responses")
        )


def test_the_lane_compiles_the_rows_responses_surface_into_the_model_component() -> None:
    bindings = fixture_bindings()
    responses = ModelProfile.model_validate(row(profile="frontier.default"))
    # The contrast row is an Anthropic row: an OpenAI tool-using row must itself name `responses`.
    catalog = fixture_model_catalog(
        ("frontier.long_context",),
        vendor="anthropic",
        model_id="claude-haiku-5-5",
        rows=(responses,),
    )
    components = catalog_model_components(bindings.model_profiles, catalog)
    assert components["frontier.default"].settings.get("use_responses_api") is True
    assert "use_responses_api" not in components["frontier.long_context"].settings


async def test_the_lane_model_built_from_the_row_requests_v1_responses() -> None:
    """N1: the exact OpenAI factory turns the compiled component into a Responses client; a tool
    call made through it goes to /v1/responses with the function tool (never chat completions)."""

    import json

    import httpx
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI

    from mission_control.adapters.deep_agents.materializer import OpenAIExactModelFactory
    from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture

    catalog = compose_model_catalog(DEPLOYMENTS, "ai-engineer")
    luna = catalog.get("child.fallback")
    responses = ModelProfile.model_validate(
        row(profile="frontier.default", model_id=luna.model_id, api_surface=luna.api_surface)
    )
    component = catalog_model_components(
        fixture_bindings().model_profiles,
        fixture_model_catalog(("frontier.long_context",), rows=(responses,)),
    )["frontier.default"]
    binding, _profile, _bundle = exact_fixture()
    sealed = binding.model_copy(
        update={
            "model": binding.model.model_copy(
                update={
                    "provider": "openai",
                    "model_name": component.model_name,
                    "settings": component.settings,
                }
            )
        }
    )
    built = OpenAIExactModelFactory()(sealed, {"environment:OPENAI_API_KEY": "sk-offline"})
    assert isinstance(built, ChatOpenAI) and built.use_responses_api is True
    bodies: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        bodies.append({"url": str(request.url), **json.loads(request.content)})
        return httpx.Response(
            200,
            json={
                "id": "resp_lane",
                "object": "response",
                "created_at": 1,
                "model": "gpt-5.6-luna",
                "status": "completed",
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc_1",
                        "call_id": "call_1",
                        "name": "lookup",
                        "arguments": '{"q": "x"}',
                        "status": "completed",
                    }
                ],
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    @tool
    def lookup(q: str) -> str:
        """Look something up."""
        return q

    # The factory's own client settings, over a mocked transport (no network).
    client = ChatOpenAI(
        model=built.model_name,
        api_key=built.openai_api_key,
        max_retries=0,
        use_responses_api=built.use_responses_api,
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)),
    )
    message = await client.bind_tools([lookup]).ainvoke("look up x")
    assert message.tool_calls and message.tool_calls[0]["name"] == "lookup"
    (body,) = bodies
    assert body["url"] == "https://api.openai.com/v1/responses"
    assert [item["name"] for item in body["tools"]] == ["lookup"] and "messages" not in body

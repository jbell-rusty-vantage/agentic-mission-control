"""The agent capability registry (sprint B): every row is classified and realizable, the
selection resolves to a sealed configuration with defaults, and the manifest's
`provider_options.deep_agents.lane_features` / `.model_tools` are validated against it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mission_control.adapters.deep_agents.features.builders import builder_coverage
from mission_control.adapters.deep_agents.routes import AGENT_FEATURES
from mission_control.domain.authoring.provider_options import parse_provider_options
from mission_control.domain.capabilities.features import (
    AgentConfiguration,
    AgentConfigurationRefused,
    CapabilityDomain,
    CapabilityFacet,
    FeatureAxis,
    FeatureStatus,
    Mechanism,
    resolve_agent_configuration,
)


def test_every_row_is_classified_on_both_axes_and_has_a_builder() -> None:
    assert len(AGENT_FEATURES) >= 20
    for row in AGENT_FEATURES:
        namespace = row.id.split(".", 1)[0]
        if row.axis is FeatureAxis.LANE_FEATURE:
            assert row.lane == namespace == "deep_agents" and row.model_provider is None
        else:
            assert row.model_provider == namespace and row.lane is None
        assert isinstance(row.category, CapabilityDomain)
        assert isinstance(row.facet, CapabilityFacet)
        assert row.config_model.model_json_schema()["type"] == "object"
        if row.status is not FeatureStatus.AVAILABLE:
            assert row.requires, f"{row.id} must say what it waits for"
    assert builder_coverage() == (), "an available row without a builder"


def test_categories_and_facets_make_context_editing_findable() -> None:
    editing = {row.id for row in AGENT_FEATURES.by_facet(CapabilityFacet.CONTEXT_EDITING)}
    assert editing == {"deep_agents.context_editing", "anthropic.clear_tool_uses"}
    context = {row.id for row in AGENT_FEATURES.by_category(CapabilityDomain.CONTEXT_MANAGEMENT)}
    assert editing < context
    assert {"openai.compaction", "anthropic.compaction", "deep_agents.summarization"} < context
    assert {row.id for row in AGENT_FEATURES.search("shell")} == {
        "deep_agents.bash",
        "anthropic.bash",
    }
    described = AGENT_FEATURES.describe()
    assert {row["id"] for row in described} == {row.id for row in AGENT_FEATURES}
    assert all("config_schema" in row and "mechanism" in row for row in described)


def test_defaults_are_the_file_tools_a_sandbox_shell_and_anthropic_caching() -> None:
    openai_sandboxed = [
        r.id for r in AGENT_FEATURES.defaults(lane="deep_agents", model_provider="openai")
    ]
    assert openai_sandboxed == ["deep_agents.filesystem", "deep_agents.bash"]
    openai_state = [
        r.id
        for r in AGENT_FEATURES.defaults(
            lane="deep_agents", model_provider="openai", sandboxed=False
        )
    ]
    assert openai_state == ["deep_agents.filesystem"]
    anthropic = [
        r.id for r in AGENT_FEATURES.defaults(lane="deep_agents", model_provider="anthropic")
    ]
    assert anthropic == ["deep_agents.filesystem", "deep_agents.bash", "anthropic.prompt_caching"]


def test_resolution_seals_defaults_and_selection_with_receipt_notes() -> None:
    configuration, notes = resolve_agent_configuration(
        AGENT_FEATURES,
        lane="deep_agents",
        model_provider="anthropic",
        sandbox_backend="docker",
        lane_features={"todo_list": {}, "call_limits": {"model_calls_per_run": 12}},
        model_tools={"anthropic": {"web_search": {"max_uses": 2}}},
    )
    assert [item.id for item in configuration.items] == [
        "deep_agents.filesystem",
        "deep_agents.bash",
        "deep_agents.todo_list",
        "deep_agents.call_limits",
        "anthropic.prompt_caching",
        "anthropic.web_search",
    ]
    by_id = {note.selection.id: note for note in notes}
    assert by_id["deep_agents.bash"].verdict == "native"
    assert by_id["deep_agents.bash"].native_locator == "docker backend execute tool"
    assert by_id["deep_agents.filesystem"].selection.by_default is True
    assert by_id["anthropic.web_search"].selection.config["max_uses"] == 2
    assert by_id["anthropic.web_search"].selection.mechanism is Mechanism.PROVIDER_TOOL
    # The sealed configuration is content-addressed and round-trips.
    again = AgentConfiguration.model_validate(configuration.model_dump(mode="json"))
    assert again.configuration_digest == configuration.configuration_digest
    assert configuration.selected(Mechanism.MIDDLEWARE)[0].id == "deep_agents.filesystem"


def test_a_state_backend_shell_is_degraded_only_when_named() -> None:
    silent, notes = resolve_agent_configuration(
        AGENT_FEATURES,
        lane="deep_agents",
        model_provider="openai",
        sandbox_backend="state",
        lane_features=None,
        model_tools=None,
    )
    assert [item.id for item in silent.items] == ["deep_agents.filesystem"]
    assert all(note.verdict == "native" for note in notes)
    named, notes = resolve_agent_configuration(
        AGENT_FEATURES,
        lane="deep_agents",
        model_provider="openai",
        sandbox_backend="state",
        lane_features={"bash": {}},
        model_tools=None,
    )
    (bash,) = [note for note in notes if note.selection.id == "deep_agents.bash"]
    assert bash.verdict == "degraded" and bash.reason and "state backend" in bash.reason
    assert named.get("deep_agents.bash") is not None


@pytest.mark.parametrize(
    ("lane_features", "model_tools", "pointer", "message"),
    [
        ({"bogus": {}}, None, "/lane_features/bogus", "unknown agent capability"),
        (
            {"filesystem_permissions": {}},
            None,
            "/lane_features/filesystem_permissions",
            "needs_upgrade",
        ),
        (None, {"anthropic": {"web_search": {}}}, "/model_tools/anthropic", "provider_mismatch"),
        (
            None,
            {"openai": {"file_search": {}}},
            "/model_tools/openai/file_search",
            "vector_store_ids",
        ),
        ({"call_limits": {}}, None, "/lane_features/call_limits", "at least one limit"),
    ],
)
def test_refusals_name_the_pointer_and_the_reason(
    lane_features: dict | None, model_tools: dict | None, pointer: str, message: str
) -> None:
    with pytest.raises(AgentConfigurationRefused) as error:
        resolve_agent_configuration(
            AGENT_FEATURES,
            lane="deep_agents",
            model_provider="openai",
            sandbox_backend="docker",
            lane_features=lane_features,
            model_tools=model_tools,
        )
    assert error.value.pointer == pointer
    assert message in error.value.message


def test_provider_options_validate_selections_and_store_canonical_configs() -> None:
    options = parse_provider_options(
        "deep_agents",
        {
            "lane_features": {"context_editing": {"trigger_tokens": 60_000, "keep_tool_uses": 4}},
            "model_tools": {"openai": {"web_search": {"search_context_size": "low"}}},
        },
    )
    assert options.lane_features["context_editing"]["clear_tool_inputs"] is False
    # OC-R6: model tools are the lane's model-route features (`adapters/deep_agents/routes.py`):
    # the options keep the authored selection and the lane canonicalizes it at launch.
    assert options.model_tools["openai"]["web_search"] == {"search_context_size": "low"}
    configuration, _notes = resolve_agent_configuration(
        AGENT_FEATURES,
        lane="deep_agents",
        model_provider="openai",
        sandbox_backend="state",
        lane_features=None,
        model_tools=options.model_tools,
    )
    (web_search,) = [item for item in configuration.items if item.id == "openai.web_search"]
    assert web_search.config["allowed_domains"] == []
    with pytest.raises(ValidationError, match="unknown deep_agents feature"):
        parse_provider_options("deep_agents", {"lane_features": {"web_search": {}}})
    with pytest.raises(AgentConfigurationRefused, match="unknown agent capability openai.todo"):
        resolve_agent_configuration(
            AGENT_FEATURES,
            lane="deep_agents",
            model_provider="openai",
            sandbox_backend="state",
            lane_features=None,
            model_tools={"openai": {"todo_list": {}}},
        )
    with pytest.raises(ValidationError, match="configured twice"):
        parse_provider_options(
            "deep_agents",
            {
                "summarization": {"trigger_messages": 30},
                "lane_features": {"summarization": {"trigger_messages": 12}},
            },
        )
    same = parse_provider_options(
        "deep_agents", {"lane_features": {"summarization": {"trigger_messages": 12}}}
    )
    assert same.effective_summarization is not None
    assert same.effective_summarization.trigger_messages == 12

"""The Deep Agents lane adapter seals `mc.agent_configuration.v1` (sprint B): defaults are
explicit, every item is receipted, a model tool of the wrong provider is refused at the
manifest pointer, and the configuration travels into the exact binding digest."""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.adapters.deep_agents.lane import (
    DeepAgentsAdaptationRefused,
    DeepAgentsLaneAdapter,
)
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    DeepAgentModelComponent,
    DeepAgentProfile,
)
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture
from tests.unit.deep_agents.test_lane_adapter import POINTER, _inputs


def _anthropic(model: DeepAgentModelComponent) -> DeepAgentModelComponent:
    return model.model_copy(update={"provider": "anthropic", "model_name": "claude-haiku-5-5"})


def test_defaults_are_sealed_and_receipted_without_any_selection() -> None:
    adaptation = DeepAgentsLaneAdapter().adapt(_inputs())
    configuration = adaptation.agent_configuration
    assert configuration.lane == "deep_agents" and configuration.model_provider == "openai"
    # The fixture sandbox is the state backend: the file tools only, no shell row.
    assert [item.id for item in configuration.items] == ["deep_agents.filesystem"]
    (item,) = [row for row in adaptation.receipt.items if row.kind == "feature"]
    assert (item.name, item.verdict) == ("deep_agents.filesystem", "native")
    assert item.digest == configuration.items[0].config_digest
    assert adaptation.applied_degradations == ()


def test_selected_features_and_tools_are_receipted_by_kind() -> None:
    inputs = _inputs(
        model=_anthropic(_inputs().model),
        provider_options={
            "lane_features": {"todo_list": {}, "bash": {"execution": "docker"}},
            "model_tools": {"anthropic": {"web_search": {"max_uses": 3}, "memory": {}}},
        },
    )
    adaptation = DeepAgentsLaneAdapter().adapt(inputs)
    ids = [item.id for item in adaptation.agent_configuration.items]
    assert ids == [
        "deep_agents.filesystem",
        "deep_agents.bash",
        "deep_agents.todo_list",
        "anthropic.prompt_caching",
        "anthropic.web_search",
        "anthropic.memory",
    ]
    receipt = {(row.kind, row.name): row for row in adaptation.receipt.items}
    assert receipt[("feature", "deep_agents.bash")].verdict == "native"
    assert receipt[("feature", "deep_agents.bash")].native_locator == (
        "ShellToolMiddleware bash (docker)"
    )
    assert receipt[("model_tool", "anthropic.web_search")].verdict == "native"
    assert receipt[("model_tool", "anthropic.prompt_caching")].verdict == "native"
    assert adaptation.applied_degradations == ()


def test_a_model_tool_of_another_provider_is_refused_at_the_pointer() -> None:
    with pytest.raises(DeepAgentsAdaptationRefused) as error:
        DeepAgentsLaneAdapter().adapt(
            _inputs(provider_options={"model_tools": {"anthropic": {"web_search": {}}}})
        )
    assert error.value.pointer == f"{POINTER}/provider_options/deep_agents/model_tools/anthropic"
    assert "model_tool_provider_mismatch" in error.value.message


def test_a_host_shell_is_a_degradation_the_binding_carries() -> None:
    adaptation = DeepAgentsLaneAdapter().adapt(
        _inputs(provider_options={"lane_features": {"bash": {"execution": "host"}}})
    )
    (line,) = adaptation.applied_degradations
    assert line.startswith("feature:deep_agents.bash:degraded:commands run on the worker host")


def test_the_configuration_is_part_of_the_exact_binding_digest() -> None:
    binding, profile, _bundle = exact_fixture()
    without = DeepAgentsLaneAdapter().adapt(_inputs(provider_options=None))
    with_todo = DeepAgentsLaneAdapter().adapt(
        _inputs(provider_options={"lane_features": {"todo_list": {}}})
    )
    digests: list[str] = []
    for adaptation in (without, with_todo):
        values: dict[str, Any] = profile.model_dump(mode="python", exclude={"profile_digest"})
        values["agent_configuration"] = adaptation.agent_configuration
        sealed = DeepAgentProfile.create(**values)
        digests.append(sealed.profile_digest)
        rebound = DeepAgentExecutionBinding.create(
            **{
                **binding.model_dump(mode="python", exclude={"binding_digest"}),
                "agent_configuration": adaptation.agent_configuration,
            }
        )
        assert rebound.agent_configuration == adaptation.agent_configuration
        assert rebound.binding_digest != binding.binding_digest
    assert digests[0] != digests[1]
    # A profile sealed before sprint B keeps its digest: the field is excluded while absent.
    assert "agent_configuration" not in profile.model_dump(mode="json")

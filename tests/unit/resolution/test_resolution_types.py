"""The frozen resolution shapes refuse inexact content (ADR-0063, R0)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mission_control.domain.execution.materialization_receipt import MaterializationReceipt
from mission_control.domain.resolution.configuration import (
    CONFIGURATION_ITEM_KINDS,
    RECEIPT_KIND,
    AgentConfiguration,
    ConfigurationItem,
)
from mission_control.domain.resolution.profiles import LaneDeclaration
from mission_control.domain.resolution.resolved import ResolvedRuntime, SealedLaneBinding
from mission_control.domain.resolution.selection import RuntimeSelection
from tests.conformance.lanes.compile.fixtures import CANONICAL_ITEMS, canonical_agent
from tests.conformance.lanes.compile.stub import STUB_DECLARATION, StubLaneAdapter
from tests.conformance.resolution.fixtures import AI_ENGINEER


def test_every_item_kind_has_a_receipt_kind() -> None:
    assert set(RECEIPT_KIND) == set(CONFIGURATION_ITEM_KINDS)


def test_an_item_pin_must_end_in_its_digest() -> None:
    item = CANONICAL_ITEMS[0]
    with pytest.raises(ValidationError, match="must end in its digest"):
        ConfigurationItem.model_validate({**item.model_dump(), "digest": "sha256:" + "1" * 64})


def test_an_item_config_is_sealed_by_its_digest() -> None:
    item = CANONICAL_ITEMS[1]
    with pytest.raises(ValidationError, match="configuration digest mismatch"):
        ConfigurationItem.model_validate({**item.model_dump(), "config": {"tools": ["all"]}})


def test_agent_configuration_is_ordered_unique_and_digest_sealed() -> None:
    agent = canonical_agent("deep_agents")
    assert [(i.kind, i.name) for i in agent.items] == sorted((i.kind, i.name) for i in agent.items)
    assert AgentConfiguration.model_validate(agent.model_dump()) == agent

    with pytest.raises(ValidationError, match="digest mismatch"):
        AgentConfiguration.model_validate({**agent.model_dump(), "data_class": "public"})
    duplicate = (*agent.items, agent.items[0])
    with pytest.raises(ValidationError, match="names each item once"):
        AgentConfiguration.create(
            lane_profile="deep_agents",
            node_ref="n",
            instructions_ref=agent.instructions_ref,
            model=agent.model,
            items=duplicate,
            data_class="internal",
            data_class_source="declared",
        )


def test_the_same_configuration_has_the_same_digest_whatever_the_item_order() -> None:
    forward = canonical_agent("deep_agents")
    reverse = canonical_agent("deep_agents", items=tuple(reversed(CANONICAL_ITEMS)))
    assert forward.configuration_digest == reverse.configuration_digest


def test_a_sealed_binding_refuses_altered_bytes() -> None:
    binding = SealedLaneBinding.seal(lane_profile="deep_agents", schema_id="s.v1", payload=b"{}")
    with pytest.raises(ValidationError, match="digest mismatch"):
        SealedLaneBinding.model_validate({**binding.model_dump(), "payload": b"{ }"})


def test_a_lane_declaration_names_every_item_kind_and_family() -> None:
    items = dict(STUB_DECLARATION.items)
    items.pop("middleware")
    with pytest.raises(ValidationError, match="declares exactly"):
        LaneDeclaration.model_validate({**STUB_DECLARATION.model_dump(), "items": items})


def _selection(agent: AgentConfiguration) -> RuntimeSelection:
    return RuntimeSelection(
        lane_profile=agent.lane_profile,
        model_profile=agent.model.profile,
        family="GoalDirected",
        node_role="executor",
        application_id="ai-engineer",
        agent=agent,
    )


def test_a_selection_names_one_lane_and_one_model() -> None:
    selection = _selection(canonical_agent("deep_agents")).model_dump()
    with pytest.raises(ValidationError, match="different lanes"):
        RuntimeSelection.model_validate({**selection, "lane_profile": "codex"})
    with pytest.raises(ValidationError, match="different models"):
        RuntimeSelection.model_validate({**selection, "model_profile": "judge.default"})


def test_a_sealed_binding_round_trips_through_json_and_refuses_non_json_bytes() -> None:
    binding = StubLaneAdapter().compile(canonical_agent("deep_agents"), {})[0]
    assert SealedLaneBinding.model_validate_json(binding.model_dump_json()) == binding
    assert SealedLaneBinding.model_validate(binding.model_dump(mode="json")) == binding
    with pytest.raises(ValidationError, match="not UTF-8 JSON"):
        SealedLaneBinding.seal(
            lane_profile="deep_agents", schema_id="s.v1", payload=bytes([255, 0])
        )


def _runtime(**overrides: object) -> ResolvedRuntime:
    agent = canonical_agent("deep_agents")
    binding, receipt = StubLaneAdapter().compile(agent, {})
    fields: dict[str, object] = {
        "selection_digest": _selection(agent).digest(),
        "agent": agent,
        "lane_binding": binding,
        "knowledge": AI_ENGINEER.knowledge,
        "outputs": AI_ENGINEER.outputs,
        "transfer": AI_ENGINEER.transfer,
        "receipt": receipt,
        "application_revision": AI_ENGINEER.revision,
    }
    return ResolvedRuntime.create(**{**fields, **overrides})


def test_resolved_runtime_digest_covers_the_application_revision() -> None:
    first = _runtime()
    second = _runtime(application_revision=2)
    assert first.runtime_digest != second.runtime_digest
    assert ResolvedRuntime.model_validate(first.model_dump()) == first


def test_resolved_runtime_refuses_another_lanes_receipt() -> None:
    agent = canonical_agent("deep_agents")
    foreign = MaterializationReceipt.create(lane_profile="codex", items=())
    binding, _ = StubLaneAdapter().compile(agent, {})
    with pytest.raises(ValidationError, match="another lane"):
        _runtime(receipt=foreign, lane_binding=binding)

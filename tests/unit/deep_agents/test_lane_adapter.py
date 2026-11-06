"""The Deep Agents lane adapter (P1-S2/S3): contract → children, options, slices, receipt.

Pure over its inputs: the parent's exact components come from the WP-CP-040 fixture binding,
the subagent profiles are ``mc.subagent_profile.v1`` rows, and the result is sealed through
``compile_deep_agent_execution_binding`` to prove the adaptation is an exact binding input.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.adapters.deep_agents.lane import (
    AsyncSubagentGraphBinding,
    DeepAgentsAdaptationRefused,
    DeepAgentsLaneAdapter,
    DeepAgentsNodeInputs,
    SelectedSubagent,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.subagents import SubagentProfile
from mission_control.domain.execution.contracts import DeepAgentProfile
from mission_control.domain.execution.materialization import compile_deep_agent_execution_binding
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings

POINTER = "/mission/program/nodes/0"


def _inputs(**overrides: Any) -> DeepAgentsNodeInputs:
    binding, profile, _bundle = exact_fixture(include_mcp=True)
    values: dict[str, Any] = {
        "pointer": POINTER,
        "model": binding.model,
        "sandbox": binding.sandbox,
        "mcp_servers": binding.mcp_servers,
        "skills": binding.skills,
        "tools": binding.tools,
        "subagents": (),
        "provider_options": None,
        "delegation_ceiling": profile.delegation_ceiling,
        "state_schema": binding.cognitive_state_schema,
        "context_schema": binding.cognitive_context_schema,
        "placement_sandbox_backends": frozenset({"state"}),
        "authority_refs": binding.authority_refs,
        "model_profiles": {},
        "served_models": frozenset({binding.model.ref.digest}),
        "async_graphs": {},
    }
    values.update(overrides)
    return DeepAgentsNodeInputs(**values)


def _profile(**overrides: Any) -> SubagentProfile:
    values: dict[str, Any] = {
        "name": "reviewer",
        "description": "Reviews the draft.",
        "prompt": "You review drafts and answer with findings.",
    }
    values.update(overrides)
    return SubagentProfile.model_validate(values)


def _selected(profile: SubagentProfile) -> SelectedSubagent:
    return SelectedSubagent(
        pointer=f"{POINTER}/environment/agents/0",
        capability_id=f"subagent.{profile.name}",
        profile=profile,
    )


def test_a_sync_profile_becomes_an_exact_child_with_inline_prompt_and_slices() -> None:
    inputs = _inputs()
    (server,) = inputs.mcp_servers
    (skill,) = inputs.skills
    profile = _profile(mcp_servers=(server.server_name,), skills=(skill.skill_name,))
    adaptation = DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(profile),)))
    (child,) = adaptation.sync_subagents
    assert child.system_prompt == profile.prompt
    assert child.system_prompt_ref.digest == sha256_digest(profile.prompt)
    assert child.model == inputs.model
    assert child.mcp_server_refs == (server.ref,)
    assert child.skill_refs == (skill.ref,)
    assert child.writable_paths == ("/subagents/reviewer",)
    assert {item.slice_id for item in adaptation.state_schema.subagent_slices} == {
        child.state_slice_id
    }
    assert {item.slice_id for item in adaptation.context_schema.subagent_slices} == {
        child.context_slice_id
    }
    receipt = adaptation.receipt
    subagent_items = [item for item in receipt.items if item.kind == "subagent"]
    assert [(item.name, item.verdict) for item in subagent_items] == [("reviewer", "native")]
    assert {item.kind for item in receipt.items} >= {"model", "sandbox", "mcp_server", "skill"}
    assert receipt.lane_profile == "deep_agents"
    assert adaptation.applied_degradations == ()


def test_the_adaptation_is_an_exact_binding_input() -> None:
    bound = fixture_bindings()
    scaffold = bound.deep_agents
    assert scaffold is not None
    binding, _fixture_profile, _bundle = exact_fixture(include_mcp=True)
    profile = _profile(tools=(), readonly=True, max_turns=3)
    adaptation = DeepAgentsLaneAdapter().adapt(
        _inputs(
            subagents=(_selected(profile),),
            provider_options={
                "sandbox_backend": "state",
                "summarization": {"trigger_messages": 12, "keep_messages": 4},
                "interrupt_on": ("write_file",),
            },
            delegation_ceiling=scaffold.profile.delegation_ceiling,
            state_schema=scaffold.state_schema,
            context_schema=scaffold.context_schema,
        )
    )
    adapted_profile = DeepAgentProfile.create(
        **{
            **scaffold.profile.model_dump(mode="python", exclude={"profile_digest"}),
            "model": binding.model,
            "sandbox": binding.sandbox,
            "mcp_servers": binding.mcp_servers,
            "skills": binding.skills,
            "tools": binding.tools,
            "sync_subagents": adaptation.sync_subagents,
            "provider_options": adaptation.provider_options,
        }
    )
    sealed = compile_deep_agent_execution_binding(
        profile=adapted_profile,
        placement=scaffold.placement,
        state_schema=adaptation.state_schema,
        context_schema=adaptation.context_schema,
        context_values=dict(scaffold.context_values),
        run_id="run-1",
        operation_id="stage/draft",
        operation_attempt=1,
        execution_generation=1,
        erc_digest=binding.erc_digest,
        control_revision=1,
        workspace=binding.workspace,
        capability_grant=binding.capability_grant,
        reservation_id="reservation:run-1",
        authority_refs=scaffold.authority_refs,
        redaction_policy_ref=scaffold.redaction_policy_ref,
        initial_context_manifest=scaffold.initial_context_manifest,
        applied_degradations=adaptation.applied_degradations,
        materialization_receipt=adaptation.receipt,
    )
    assert sealed.provider_options is not None
    assert sealed.provider_options.summarization is not None
    assert sealed.provider_options.summarization.trigger_messages == 12
    assert sealed.materialization_receipt == adaptation.receipt
    # A degraded child and the declared interrupt both leave a line in the binding.
    assert any(
        line.startswith("subagent:reviewer:degraded:") for line in sealed.applied_degradations
    )
    assert any(
        line.startswith("human_control:interrupt_on:degraded:")
        for line in sealed.applied_degradations
    )
    # The sealed binding round-trips with its digest; the receipt is part of the identity.
    assert sealed.content_digest() == sealed.binding_digest
    assert sealed.model_validate(sealed.model_dump(mode="json")) == sealed


def test_lossy_fields_are_degraded_with_reasons_never_dropped_silently() -> None:
    profile = _profile(
        readonly=True,
        background=True,
        context_mode="fork",
        max_turns=5,
        sandbox="own",
        budget={"tokens.total": 1_000},
    )
    adaptation = DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(profile),)))
    (item,) = [item for item in adaptation.receipt.items if item.kind == "subagent"]
    assert item.verdict == "degraded"
    assert item.reason is not None
    for fragment in (
        "readonly",
        "sync child runs to completion",
        "fork",
        "max_turns",
        "sandbox",
        "budget",
    ):
        assert fragment in item.reason, fragment
    (child,) = adaptation.sync_subagents
    assert child.budget_limits == {}  # the fixture ceiling grants no dimension


def test_an_unknown_tool_name_is_refused_at_the_profile_pointer() -> None:
    profile = _profile(tools=("nonexistent_tool",))
    with pytest.raises(DeepAgentsAdaptationRefused) as raised:
        DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(profile),)))
    assert raised.value.pointer == f"{POINTER}/environment/agents/0"
    assert "nonexistent_tool" in raised.value.message


def test_a_bundle_prompt_and_a_linked_run_are_refused() -> None:
    bundle = _profile(prompt=None, prompt_bundle_ref="bundle:reviewer")
    with pytest.raises(DeepAgentsAdaptationRefused, match="inline prompts only"):
        DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(bundle),)))
    linked = _profile(kind="linked_run")
    with pytest.raises(DeepAgentsAdaptationRefused, match="linked_run"):
        DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(linked),)))


def test_an_async_profile_needs_a_served_graph_and_then_seals_a_contract() -> None:
    profile = _profile(name="researcher", kind="async", tools=("lookup_binding_marker",))
    with pytest.raises(DeepAgentsAdaptationRefused, match="no served Agent Server graph"):
        DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(profile),)))
    graph = AsyncSubagentGraphBinding(
        graph_id="belllabs_async_technical_child",
        graph_revision="1",
        graph_binding_digest=sha256_digest("child-binding"),
        agent_protocol_url="http://127.0.0.1:2024",
        objective_schema_ref="schema:objective@1",
        result_schema_ref="schema:result@1",
        result_admission_policy_ref="policy:result-admission@1",
        default_budget_limits={"tokens.total": 50_000},
    )
    adaptation = DeepAgentsLaneAdapter().adapt(
        _inputs(subagents=(_selected(profile),), async_graphs={"researcher": graph})
    )
    (contract,) = adaptation.async_subagents
    assert contract.graph_id == graph.graph_id
    assert contract.capability_ceiling.tool_ids == frozenset({"lookup_binding_marker"})
    assert contract.budget_limits == {"tokens.total": 50_000}
    assert contract.state_slice_id == "subagent:researcher:state"
    (item,) = [item for item in adaptation.receipt.items if item.kind == "subagent"]
    assert item.native_locator == "agent_server:belllabs_async_technical_child@1"


def test_provider_options_pin_the_sandbox_backend_or_refuse() -> None:
    with pytest.raises(DeepAgentsAdaptationRefused) as raised:
        DeepAgentsLaneAdapter().adapt(_inputs(provider_options={"sandbox_backend": "docker"}))
    assert raised.value.pointer.endswith("/provider_options/deep_agents/sandbox_backend")
    with pytest.raises(DeepAgentsAdaptationRefused, match="unknown"):
        DeepAgentsLaneAdapter().adapt(_inputs(provider_options={"unknown": True}))
    adaptation = DeepAgentsLaneAdapter().adapt(
        _inputs(provider_options={"summarization": {"trigger_tokens": 20_000}})
    )
    assert adaptation.provider_options is not None
    (compaction,) = [item for item in adaptation.receipt.items if item.kind == "compaction"]
    assert compaction.native_locator == "node summarization trigger"


def test_the_receipt_is_content_addressed_and_order_stable() -> None:
    first = DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(_profile()),)))
    second = DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(_profile()),)))
    assert first.receipt == second.receipt
    assert first.receipt.content_digest() == first.receipt.receipt_digest
    kinds = [item.kind for item in first.receipt.items]
    assert kinds == sorted(kinds)

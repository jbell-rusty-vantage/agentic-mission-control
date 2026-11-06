"""OVE-184: a dynamic async child's own exact configuration, sealed at launch.

The lane adapter seals a ``kind: async`` profile bound to the generic sealed-child graph into a
``SealedAsyncChildBinding`` inside its contract: the profile's prompt, its own model, tools,
Skills and MCP servers (or the parent's whole set for an inheriting child), the registry's
lane features, all digest-exact; a requirement the hosted child cannot honour refuses.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.adapters.deep_agents.child_binding import SEALED_CHILD_SANDBOX
from mission_control.adapters.deep_agents.lane import (
    INHERIT_CHILD_PROMPT,
    DeepAgentsAdaptationRefused,
    DeepAgentsLaneAdapter,
    SeedComponents,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.execution.async_subagent_reconciliation import (
    AsyncServedGraphIdentity,
)
from mission_control.domain.execution.contracts import (
    AsyncSubagentContract,
    DeepAgentModelComponent,
    SealedAsyncChildBinding,
)
from tests.unit.deep_agents.test_lane_adapter import _inputs, _profile
from tests.unit.deep_agents.test_lane_adapter_children import (
    _graph,
    _seed_server,
    _seed_skill,
    _selected,
)

SEALED_GRAPH = {
    "graph_id": "belllabs_async_child",
    "graph_revision": "sealed-child@1",
    "binding_mode": "sealed_child",
    "result_admission_policy_ref": "policy:async-result:typed-manifest@1",
}
HAIKU = DeepAgentModelComponent(
    ref=ExactDefinitionRef(
        kind=DefinitionKind.MODEL,
        logical_id="model.claude-haiku-5-5",
        revision=1,
        digest=sha256_digest("model.claude-haiku-5-5"),
    ),
    provider="anthropic",
    model_name="claude-haiku-5-5",
)


def _adapt(profile: Any, **extra: Any) -> Any:
    selected_extra = extra.pop("selected", {})
    inputs = _inputs(
        subagents=(_selected(profile, **selected_extra),),
        async_graphs={profile.name: _graph(**SEALED_GRAPH)},
        **extra,
    )
    return DeepAgentsLaneAdapter().adapt(inputs), inputs


def test_a_seeded_async_child_seals_its_own_prompt_model_and_components() -> None:
    profile = _profile(
        name="researcher",
        kind="async",
        model="child.default",
        tools=(),
        mcp_servers=(),
        max_turns=6,
        prompt="Research the bounded question and answer in one paragraph.",
    )
    inputs = _inputs()
    seeds = SeedComponents(mcp_servers=(_seed_server(),), skills=(_seed_skill(inputs),))
    adaptation, inputs = _adapt(
        profile,
        selected={"seeds": seeds},
        model_profiles={"child.default": HAIKU},
        served_models=frozenset({inputs.model.ref.digest, HAIKU.ref.digest}),
    )
    (contract,) = adaptation.async_subagents
    sealed = contract.child_binding
    assert isinstance(sealed, SealedAsyncChildBinding)
    assert contract.sealed and contract.graph_binding_digest == sealed.sealed_digest
    assert sealed.shape == "seeded"
    assert sealed.system_prompt == profile.prompt
    binding = sealed.binding
    # The child's own model and seeds, never the parent's set; its own state backend.
    assert binding.model == HAIKU != inputs.model
    assert [server.server_name for server in binding.mcp_servers] == ["child_only"]
    assert [skill.skill_name for skill in binding.skills] == ["child-only"]
    assert binding.tools == ()
    assert binding.sandbox == SEALED_CHILD_SANDBOX
    assert binding.placement == "remote_langsmith_deployment"
    # OVE-148: the registry's rows, defaults inserted and `max_turns` as a native call limit.
    assert binding.agent_configuration is not None
    features = {item.id: item for item in binding.agent_configuration.items}
    assert "deep_agents.filesystem" in features
    assert features["deep_agents.call_limits"].config["model_calls_per_run"] == 6
    # The receipt names the child's model, features and components.
    names = {item.name: item for item in adaptation.receipt.items}
    assert names["researcher"].native_locator.startswith("agent_server:belllabs_async_child")
    assert "researcher/model.claude-haiku-5-5" in names
    assert "researcher/child_only" in names
    assert "researcher/deep_agents.call_limits" in names
    # Exact and stable: the same configuration seals the same digest, and it round-trips.
    again, _ = _adapt(
        profile,
        selected={"seeds": seeds},
        model_profiles={"child.default": HAIKU},
        served_models=frozenset({inputs.model.ref.digest, HAIKU.ref.digest}),
    )
    assert again.async_subagents[0].contract_digest == contract.contract_digest
    assert AsyncSubagentContract.model_validate_json(contract.model_dump_json()) == contract


def test_an_inheriting_async_child_takes_the_parents_set_and_the_general_prompt() -> None:
    profile = _profile(name="general", kind="async", capabilities="inherit", prompt=None)
    adaptation, inputs = _adapt(profile)
    sealed = adaptation.async_subagents[0].child_binding
    assert sealed is not None and sealed.shape == "inherit"
    assert sealed.system_prompt == INHERIT_CHILD_PROMPT
    assert sealed.binding.model == inputs.model
    assert sealed.binding.tools == inputs.tools
    assert sealed.binding.skills == inputs.skills
    assert sealed.binding.mcp_servers == inputs.mcp_servers


def test_a_requirement_the_hosted_child_cannot_honour_refuses() -> None:
    gated = _profile(name="gated", kind="async", interrupt_on=("write_file",))
    with pytest.raises(DeepAgentsAdaptationRefused, match="approval gates"):
        _adapt(gated)
    bundled = _profile(
        name="bundled", kind="async", prompt=None, prompt_bundle_ref="bundle://prompt@1"
    )
    with pytest.raises(DeepAgentsAdaptationRefused, match="inline prompts only"):
        _adapt(bundled)
    unknown = _profile(name="unknown", kind="async", tools=("not_a_parent_tool",))
    with pytest.raises(DeepAgentsAdaptationRefused, match="does not select"):
        _adapt(unknown)


def test_an_exact_graph_keeps_its_one_served_binding_and_reports_the_loss() -> None:
    profile = _profile(name="researcher", kind="async")
    inputs = _inputs()
    adaptation = DeepAgentsLaneAdapter().adapt(
        _inputs(
            subagents=(_selected(profile, seeds=SeedComponents(skills=(_seed_skill(inputs),))),),
            async_graphs={"researcher": _graph()},
        )
    )
    (contract,) = adaptation.async_subagents
    assert contract.child_binding is None and not contract.sealed
    (item,) = [item for item in adaptation.receipt.items if item.name == "researcher"]
    assert item.verdict == "degraded" and "binding_mode: sealed_child" in (item.reason or "")


def test_the_served_identity_admits_sealed_contracts_and_the_stamp_matches_exactly() -> None:
    profile = _profile(name="researcher", kind="async")
    adaptation, _ = _adapt(profile)
    (contract,) = adaptation.async_subagents
    host = AsyncServedGraphIdentity(
        graph_id="belllabs_async_child",
        graph_revision="sealed-child@1",
        graph_binding_digest=sha256_digest("host-template"),
        deepagents_version="0.7.5",
        binding_mode="sealed_child",
    )
    assert host.admits(contract) and not host.matches(contract)
    stamp = host.model_copy(update={"graph_binding_digest": contract.graph_binding_digest})
    assert stamp.matches(contract)
    other = stamp.model_copy(update={"graph_binding_digest": sha256_digest("another child")})
    assert not other.matches(contract)
    static = host.model_copy(update={"binding_mode": "exact"})
    assert not static.admits(contract)

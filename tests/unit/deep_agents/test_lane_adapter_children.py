"""The Deep Agents lane adapter's two child shapes (P1 subagents, Q2/Q7): the explicit inherit
child, seeded children with their own components inside the delegation ceiling, typed
per-lane overrides, the async graph's registered policy and its launch credential."""

from __future__ import annotations

import pytest

from mission_control.adapters.deep_agents.lane import (
    INHERIT_CHILD_PROMPT,
    SUBAGENT_FIELDS,
    DeepAgentsAdaptationRefused,
    DeepAgentsLaneAdapter,
    SeedComponents,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import SecretRef
from mission_control.domain.capabilities.subagents import SUBAGENT_FIELDS as VOCABULARY
from mission_control.domain.capabilities.subagents import SubagentProfile
from mission_control.domain.execution.contracts import (
    AsyncSubagentDependencyClass,
    DeepAgentMCPToolComponent,
    DelegationCeiling,
)
from tests.support.unit.deep_agents.lane_adapter import _inputs, _profile
from tests.support.unit.deep_agents.lane_adapter_children import (
    _graph,
    _seed_server,
    _seed_skill,
    _selected,
)

SKILL_PIN = "skill.probe@1#sha256:" + "a" * 64


def test_the_lane_declares_every_field_of_the_shared_vocabulary() -> None:
    assert tuple(SUBAGENT_FIELDS) == VOCABULARY
    assert SUBAGENT_FIELDS["capabilities.inherit"] == "native"
    assert SUBAGENT_FIELDS["kind.linked_run"] == "unsupported"


def test_an_inherit_child_is_explicit_receipted_and_takes_the_lane_default_prompt() -> None:
    general = SubagentProfile.model_validate(
        {"name": "general", "description": "General.", "capabilities": "inherit"}
    )
    inputs = _inputs(subagents=(_selected(general),))
    adaptation = DeepAgentsLaneAdapter().adapt(inputs)
    (child,) = adaptation.sync_subagents
    assert child.inherits_parent and child.system_prompt == INHERIT_CHILD_PROMPT
    assert child.system_prompt_ref.digest == sha256_digest(INHERIT_CHILD_PROMPT)
    assert child.tool_refs == () and child.mcp_server_refs == () and child.skill_refs == ()
    assert child.model == inputs.model
    (row,) = [item for item in adaptation.receipt.items if item.kind == "subagent"]
    assert row.verdict == "native" and "inheriting every parent tool" in (row.native_locator or "")
    # A profile that writes its own prompt for the inherit child keeps it.
    prompted = SubagentProfile.model_validate(
        {"name": "general", "description": "General.", "capabilities": "inherit", "prompt": "Mine."}
    )
    (child,) = (
        DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(prompted),))).sync_subagents
    )
    assert child.system_prompt == "Mine."


def test_a_seeded_child_carries_its_own_components_and_the_receipt_names_each() -> None:
    inputs = _inputs()
    server = _seed_server()
    skill = _seed_skill(inputs)
    profile = _profile(seeds={"skills": [SKILL_PIN]})
    selected = _selected(
        profile,
        seeds=SeedComponents(
            mcp_servers=(server,), skills=(skill,), deferred=(("hook", "hook.probe"),)
        ),
    )
    adaptation = DeepAgentsLaneAdapter().adapt(_inputs(subagents=(selected,)))
    (child,) = adaptation.sync_subagents
    assert child.seeded_mcp_servers == (server,) and child.seeded_skills == (skill,)
    assert child.inherits_parent is False
    rows = {(item.kind, item.name): item for item in adaptation.receipt.items}
    assert rows[("mcp_server", "reviewer/child_only")].verdict == "native"
    assert rows[("skill", "reviewer/child-only")].verdict == "native"
    # The deferred plugin member is a documented loss on the child, never a silent drop.
    child_row = rows[("subagent", "reviewer")]
    assert child_row.verdict == "degraded" and "hook.probe" in (child_row.reason or "")
    # The parent's own rows are untouched by the child's.
    assert ("mcp_server", "qualification") in rows


def test_seeds_outside_the_delegation_ceiling_or_colliding_with_the_parent_are_refused() -> None:
    inputs = _inputs()
    selected = _selected(_profile(), seeds=SeedComponents(mcp_servers=(_seed_server(),)))
    fenced = _inputs(
        subagents=(selected,),
        delegation_ceiling=DelegationCeiling(mcp_server_ids=frozenset({"allowed_only"})),
    )
    with pytest.raises(DeepAgentsAdaptationRefused, match="outside the delegation ceiling"):
        DeepAgentsLaneAdapter().adapt(fenced)
    (parent_server,) = inputs.mcp_servers
    colliding = _seed_server().model_copy(
        update={
            "tools": (
                DeepAgentMCPToolComponent(
                    tool_name=parent_server.tools[0].tool_name, schema_digest=sha256_digest("y")
                ),
            )
        }
    )
    with pytest.raises(DeepAgentsAdaptationRefused, match="names the parent already has"):
        DeepAgentsLaneAdapter().adapt(
            _inputs(
                subagents=(_selected(_profile(), seeds=SeedComponents(mcp_servers=(colliding,))),)
            )
        )


def test_typed_overrides_move_the_writable_root_and_widen_the_state_slice() -> None:
    profile = _profile(
        provider_overrides={
            "deep_agents": {"writable_root": "/work/reviewer", "state_channels": ["artifact_index"]}
        }
    )
    adaptation = DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(profile),)))
    (child,) = adaptation.sync_subagents
    assert child.writable_paths == ("/work/reviewer",)
    unknown = _profile(provider_overrides={"deep_agents": {"state_channels": ["no_such_channel"]}})
    with pytest.raises(DeepAgentsAdaptationRefused, match="state channels the parent schema"):
        DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(unknown),)))


def test_the_manifest_overlay_degrades_readonly_for_one_node() -> None:
    adaptation = DeepAgentsLaneAdapter().adapt(
        _inputs(subagents=(_selected(_profile(), overlay={"readonly": True}),))
    )
    (row,) = [item for item in adaptation.receipt.items if item.kind == "subagent"]
    assert row.verdict == "degraded" and "readonly" in (row.reason or "")


def test_an_async_graph_needs_a_registered_policy_and_yields_its_launch_credential() -> None:
    researcher = _profile(name="researcher", kind="async")
    graphs = {"researcher": _graph()}
    adaptation = DeepAgentsLaneAdapter().adapt(
        _inputs(
            subagents=(_selected(researcher),),
            async_graphs=graphs,
            async_result_policy_refs=frozenset({"policy:async-result:technical-child@1"}),
        )
    )
    (contract,) = adaptation.async_subagents
    assert contract.dependency_classes == frozenset(
        {AsyncSubagentDependencyClass.REQUIRED_BLOCKING}
    )
    assert adaptation.secret_refs == (
        SecretRef(provider="environment", key="BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN"),
    )
    with pytest.raises(DeepAgentsAdaptationRefused, match="does not register"):
        DeepAgentsLaneAdapter().adapt(
            _inputs(
                subagents=(_selected(researcher),),
                async_graphs=graphs,
                async_result_policy_refs=frozenset({"policy:other@1"}),
            )
        )
    # Without a registry handed in (unit callers), the check is the caller's.
    DeepAgentsLaneAdapter().adapt(_inputs(subagents=(_selected(researcher),), async_graphs=graphs))

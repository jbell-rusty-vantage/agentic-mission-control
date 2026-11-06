"""The Deep Agents lane adapter's two child shapes (P1 subagents, Q2/Q7): the explicit inherit
child, seeded children with their own components inside the delegation ceiling, typed
per-lane overrides, the async graph's registered policy and its launch credential."""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.adapters.deep_agents.lane import (
    INHERIT_CHILD_PROMPT,
    SUBAGENT_FIELDS,
    AsyncSubagentGraphBinding,
    DeepAgentsAdaptationRefused,
    DeepAgentsLaneAdapter,
    SeedComponents,
    SelectedSubagent,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef, SecretRef
from mission_control.domain.capabilities.subagents import SUBAGENT_FIELDS as VOCABULARY
from mission_control.domain.capabilities.subagents import SubagentProfile
from mission_control.domain.execution.contracts import (
    AsyncSubagentDependencyClass,
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
    DeepAgentSkillComponent,
    DelegationCeiling,
)
from tests.unit.deep_agents.test_lane_adapter import POINTER, _inputs, _profile

SKILL_PIN = "skill.probe@1#sha256:" + "a" * 64


def _selected(profile: SubagentProfile, **extra: Any) -> SelectedSubagent:
    return SelectedSubagent(
        pointer=f"{POINTER}/environment/agents/0",
        capability_id=f"subagent.{profile.name}",
        profile=profile,
        **extra,
    )


def _seed_server(name: str = "child_only") -> DeepAgentMCPServerComponent:
    return DeepAgentMCPServerComponent(
        ref=ExactDefinitionRef(
            kind=DefinitionKind.MCP_SERVER,
            logical_id=f"mcp.{name}",
            revision=1,
            digest=sha256_digest(f"mcp.{name}"),
        ),
        server_name=name,
        transport="stdio",
        command="python",
        arguments=("-m", name),
        credential_refs=(SecretRef(provider="environment", key="CHILD_ONLY_TOKEN"),),
        tools=(
            DeepAgentMCPToolComponent(tool_name=f"{name}_lookup", schema_digest=sha256_digest("x")),
        ),
        schema_digest=sha256_digest(f"{name}-schema"),
        attachment_target="agent.subagent.reviewer",
    )


def _seed_skill(inputs: Any) -> DeepAgentSkillComponent:
    (parent_skill,) = inputs.skills
    return DeepAgentSkillComponent(
        **{
            **parent_skill.model_dump(mode="python"),
            "ref": ExactDefinitionRef(
                kind=DefinitionKind.SKILL,
                logical_id="skill.child-only",
                revision=1,
                digest=sha256_digest("skill.child-only"),
            ),
            "skill_name": "child-only",
            "mount_root": "/skills/children/child-only",
        }
    )


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


def _graph(**overrides: Any) -> AsyncSubagentGraphBinding:
    values: dict[str, Any] = {
        "graph_id": "belllabs_async_technical_child",
        "graph_revision": "agent.async-technical-child@1",
        "graph_binding_digest": "sha256:" + "e" * 64,
        "agent_protocol_url": "http://127.0.0.1:2024",
        "deployment_credential_ref": "environment:BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN",
        "objective_schema_ref": "schema:objective@1",
        "result_schema_ref": "schema:result@1",
        "result_admission_policy_ref": "policy:async-result:technical-child@1",
        "default_budget_limits": {"tokens.total": 1000},
    }
    values.update(overrides)
    return AsyncSubagentGraphBinding(**values)


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

"""Builders, constants and fakes that other test files import.

Moved from tests/unit/deep_agents/test_lane_adapter_children.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.adapters.deep_agents.lane import AsyncSubagentGraphBinding, SelectedSubagent
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef, SecretRef
from mission_control.domain.capabilities.subagents import SubagentProfile
from mission_control.domain.execution.contracts import (
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
    DeepAgentSkillComponent,
)
from tests.support.unit.deep_agents.lane_adapter import POINTER


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

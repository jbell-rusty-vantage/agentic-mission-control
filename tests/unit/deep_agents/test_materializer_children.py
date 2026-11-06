"""The materializer honours what the lane adapter sealed (P1-S2/S3, P1 subagents): an inline
child prompt, a child's MCP tools narrowed from the parent's loaded tools, a seeded child's own
MCP tools and Skill roots, an inheriting child's whole parent set, the node summarization
trigger, and no implicit `general-purpose` child. Nothing here invokes a model."""

from __future__ import annotations

from typing import Any

import pytest
from deepagents.backends import StateBackend
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from mission_control.adapters.capabilities.capability_bundles import bytes_digest
from mission_control.adapters.deep_agents import (
    ExactComponentRegistry,
    ExactDeepAgentMaterializer,
    StateSandboxFactory,
)
from mission_control.adapters.deep_agents.adapter import _compile, _subagent_specs
from mission_control.adapters.deep_agents.materializer import (
    MaterializedDeepAgentArguments,
    _summarization_overrides,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.authoring.provider_options import DeepAgentsProviderOptions
from mission_control.domain.execution.contracts import (
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
    DeepAgentSkillComponent,
    SyncSubagentProfile,
)
from tests.acceptance.control_plane.test_wp_cp_040 import (
    SkillReadingModel,
    exact_fixture,
    skill_bundle,
)


def _child(prompt: str, **overrides: Any) -> SyncSubagentProfile:
    binding, _profile, _bundle = exact_fixture(include_mcp=True)
    values: dict[str, Any] = {
        "name": "reviewer",
        "description": "Reviews drafts.",
        "system_prompt_ref": ExactDefinitionRef(
            kind=DefinitionKind.PROMPT,
            logical_id="prompt.subagent.reviewer",
            revision=1,
            digest=sha256_digest(prompt),
        ),
        "system_prompt": prompt,
        "model": binding.model,
        "state_slice_id": "child-state",
        "context_slice_id": "child-context",
        "workspace_id": "subagent:reviewer",
        "writable_paths": ("/subagents/reviewer",),
    }
    values.update(overrides)
    return SyncSubagentProfile(**values)


def _registry(binding: Any, bundle: Any, **extra: Any) -> ExactComponentRegistry:
    return ExactComponentRegistry(
        model_factories={binding.model.ref.digest: lambda _b, _s: SkillReadingModel()},
        skill_bundles={bundle.bundle_digest: bundle, **extra.get("skill_bundles", {})},
        sandbox_factories={binding.sandbox.ref.digest: StateSandboxFactory()},
        checkpointers={binding.checkpointer_ref.digest: InMemorySaver()},
        stores={binding.store_ref.digest: InMemoryStore()},
    )


def _probe_tools(server: DeepAgentMCPServerComponent) -> list[BaseTool]:
    return [
        StructuredTool.from_function(
            func=lambda code: f"marker:{code}", name=tool.tool_name, description="probe"
        )
        for tool in server.tools
    ]


def test_an_inline_prompt_must_hash_to_its_pinned_digest() -> None:
    with pytest.raises(ValueError, match="differs from its pinned digest"):
        _child("Review.", system_prompt="Something else.")


async def test_children_get_their_inline_prompt_and_the_parents_loaded_mcp_tools() -> None:
    probe, _profile, _bundle = exact_fixture(include_mcp=True)
    (server,) = probe.mcp_servers
    child = _child("Review the draft.", mcp_server_refs=(server.ref,))
    binding, _profile, bundle = exact_fixture(
        include_mcp=True, sync_subagents=(child,), with_child_slices=True
    )
    loaded = _probe_tools(server)
    (materialized,), files, _rows = await ExactDeepAgentMaterializer(
        _registry(binding, bundle)
    )._materialize_subagents(binding, {}, (), StateBackend(), mcp_tools=loaded)
    assert files == {}
    assert materialized["system_prompt"] == "Review the draft."
    assert [tool.name for tool in materialized["tools"]] == [t.tool_name for t in server.tools]  # type: ignore[union-attr]


async def test_an_inheriting_child_receives_every_parent_tool_mcp_tool_and_skill_root() -> None:
    probe, _profile, _bundle = exact_fixture(include_mcp=True)
    (server,) = probe.mcp_servers
    general = _child("You are the general child.", name="general", inherits_parent=True)
    binding, _profile, bundle = exact_fixture(
        include_mcp=True, sync_subagents=(general,), with_child_slices=True
    )
    parent_tool = StructuredTool.from_function(
        func=lambda x: x, name="parent_tool", description="the parent's own tool"
    )
    (materialized,), _files, _rows = await ExactDeepAgentMaterializer(
        _registry(binding, bundle)
    )._materialize_subagents(
        binding,
        {},
        ("/skills/mission",),
        StateBackend(),
        mcp_tools=_probe_tools(server),
        parent_tools=(parent_tool,),
    )
    assert [tool.name for tool in materialized["tools"]] == [  # type: ignore[union-attr]
        "parent_tool",
        *(t.tool_name for t in server.tools),
    ]
    assert materialized["skills"] == ["/skills/mission"]
    assert materialized["name"] == "general"


async def test_a_seeded_child_loads_its_own_mcp_tools_and_mounts_its_own_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding_probe, _profile, _parent_bundle = exact_fixture()
    seeded_server = DeepAgentMCPServerComponent(
        ref=ExactDefinitionRef(
            kind=DefinitionKind.MCP_SERVER,
            logical_id="mcp.child-only",
            revision=1,
            digest=sha256_digest("mcp.child-only"),
        ),
        server_name="child_only",
        transport="stdio",
        command="python",
        arguments=("-m", "child_only_server"),
        tools=(
            DeepAgentMCPToolComponent(tool_name="child_lookup", schema_digest=sha256_digest("x")),
        ),
        schema_digest=sha256_digest("child-only-schema"),
        attachment_target="agent.subagent.reviewer",
    )
    child_bundle = skill_bundle()
    seeded_skill = DeepAgentSkillComponent(
        ref=ExactDefinitionRef(
            kind=DefinitionKind.SKILL,
            logical_id="skill.child-only",
            revision=1,
            digest=sha256_digest("skill.child-only"),
        ),
        skill_name="child-only",
        bundle_digest=child_bundle.bundle_digest,
        skill_md_digest=binding_probe.skills[0].skill_md_digest,
        mount_root="/skills/children/child-only",
        attachment_target="agent.subagent.reviewer",
    )
    child = _child(
        "Review with your own tools.",
        seeded_mcp_servers=(seeded_server,),
        seeded_skills=(seeded_skill,),
    )
    binding, _profile, bundle = exact_fixture(sync_subagents=(child,), with_child_slices=True)
    materializer = ExactDeepAgentMaterializer(_registry(binding, bundle))
    loaded: list[tuple[str, ...]] = []

    async def fake_load(servers: Any, secrets: Any) -> tuple[BaseTool, ...]:
        loaded.append(tuple(server.server_name for server in servers))
        return tuple(
            StructuredTool.from_function(func=lambda q: q, name=t.tool_name, description="seed")
            for server in servers
            for t in server.tools
        )

    monkeypatch.setattr(materializer, "_load_mcp_tools", fake_load)
    backend = StateBackend()
    (materialized,), files, _rows = await materializer._materialize_subagents(
        binding, {}, ("/skills/mission",), backend, mcp_tools=(), parent_tools=()
    )
    assert loaded == [("child_only",)]
    assert [tool.name for tool in materialized["tools"]] == ["child_lookup"]  # type: ignore[union-attr]
    assert materialized["skills"] == ["/skills/children"]
    # The child's bundle landed on the shared state backend under its own root only.
    assert set(files) == {f"/skills/children/child-only/{path}" for path, _ in child_bundle.files}


def test_summarization_overrides_come_from_the_sealed_provider_options() -> None:
    binding, _profile, _bundle = exact_fixture()
    assert _summarization_overrides(binding) == (None, None)
    with_options = binding.model_copy(
        update={
            "provider_options": DeepAgentsProviderOptions(
                summarization={"trigger_messages": 40, "keep_messages": 10}
            )
        }
    )
    assert _summarization_overrides(with_options) == (("messages", 40), ("messages", 10))


async def test_manifest_facts_are_stable_across_two_prepares_of_the_same_binding() -> None:
    """P3.7: what the materializer knows about the environment (the `environment_materialized`
    frame's body) names the Skill mounted, the model resolved and every Skill file it put into
    the `files` state channel by path, bytes and digest, identically on every prepare."""

    binding, _profile, bundle = exact_fixture()
    materializer = ExactDeepAgentMaterializer(_registry(binding, bundle))
    facts: list[dict[str, Any]] = []
    seeded: list[set[str]] = []
    for _ in range(2):
        async with materializer.prepare(binding, {}) as materialized:
            facts.append(materialized.manifest_facts)
            seeded.append(set(materialized.initial_state.get("files", {})))  # type: ignore[arg-type]
    first, second = facts
    assert first == second
    assert sha256_digest(first) == sha256_digest(second)
    (skill,) = binding.skills
    assert first["skills"] == [
        {
            "name": skill.skill_name,
            "mount_root": skill.mount_root,
            "bundle_digest": skill.bundle_digest,
        }
    ]
    assert first["mcp_servers"] == []
    assert first["model"] == {
        "logical_id": binding.model.ref.logical_id,
        "revision": binding.model.ref.revision,
        "digest": binding.model.ref.digest,
        "provider": binding.model.provider,
    }
    # Sprint B: a binding sealed without a configuration says so (never an implicit stack).
    assert first["agent_configuration"] is None
    ((_path, content),) = bundle.files
    assert first["state_files"] == [
        {
            "path": f"{skill.mount_root}/SKILL.md",
            "bytes": len(content),
            "digest": bytes_digest(content),
        }
    ]
    assert first["sandbox_files"] == []
    assert seeded[0] == seeded[1] == {row["path"] for row in first["state_files"]}


def _materialized(binding: Any, subagents: tuple[dict[str, object], ...]) -> Any:
    return MaterializedDeepAgentArguments(
        model=SkillReadingModel(),
        tools=(),
        middleware=(),
        subagents=subagents,
        skills=(),
        backend=StateBackend(),
        state_schema=None,  # type: ignore[arg-type]
        context_schema=None,  # type: ignore[arg-type]
        context=None,
        checkpointer=InMemorySaver(),
        store=InMemoryStore(),
        initial_state={},
        resolved_attachments=(),
        response_format=None,
    )


def _task_tool(agent: Any) -> Any:
    """The compiled parent's `task` tool, or None when the parent has no children."""

    tools_node = agent.nodes.get("tools")
    if tools_node is None:
        return None
    return getattr(tools_node.bound, "tools_by_name", {}).get("task")


def test_the_implicit_general_purpose_child_is_never_added() -> None:
    """deepagents 0.7.5 auto-adds `general-purpose`; Mission Control declares its children.

    A parent with no declared children exposes no `task` tool; a parent with one declared
    child offers exactly that child.
    """

    binding, _profile, _bundle = exact_fixture()
    bare = _compile(
        _materialized(binding, ()),
        binding,
        system_prompt="parent",
        extra_middleware=[],
        name="bare",
    )
    assert _task_tool(bare) is None
    declared = _compile(
        _materialized(
            binding,
            (
                {
                    "name": "general",
                    "description": "The declared general child.",
                    "system_prompt": "general",
                    "model": SkillReadingModel(),
                    "tools": [],
                    "skills": [],
                },
            ),
        ),
        binding,
        system_prompt="parent",
        extra_middleware=[],
        name="declared",
    )
    task = _task_tool(declared)
    assert task is not None
    listed = [
        line[2:].split(":", 1)[0].strip()
        for line in task.description.splitlines()
        if line.startswith("- ") and ":" in line
    ]
    assert "general" in listed and "general-purpose" not in listed
    assert _subagent_specs(_materialized(binding, ())) == []

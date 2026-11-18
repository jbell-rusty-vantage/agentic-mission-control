"""IP-011: a plugin selected on a Deep Agents node is run as its members.

Compiled by the real `ManifestCompileService` over one installation's seeded catalog (common
and application seeds, every revision) and resolved by the real launch author with FIXTURE
deployment components: each Skill and MCP server member binds through its own launch binding,
exactly as a direct selection would, each subagent member is a child, and a member the lane
cannot run (a hook script) is a compile blocker that names the member. No model is called and
no server is started.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    CapabilityComponentBinding,
    ManifestLaunchBindingError,
    ManifestLaunchBindings,
    ServedComponents,
)
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.domain.agentic_components.projection import ResolvedCapability
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    ExactDefinitionRef,
    HookScriptDefinition,
    PluginDefinition,
    SecretRef,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.capabilities.plugins import (
    PluginManifest,
    PluginMember,
    PluginMemberRole,
)
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
    DeepAgentSkillComponent,
)
from tests.fixtures.catalog.fast_track_catalog import NOW, fast_track_catalog
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.support.manifests.launch_inputs import resolver
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings, fixture_served

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"
# The application the canonical test scope authenticates.
APPLICATION = "biotech"
SCOPE = canonical_scope("tenant-1")
CAPTURE_ENDPOINT = "http://127.0.0.1:4310/mcp"
PLUGINS = (
    {"pin": "plugin.cognition-knowledge@latest", "as": "knowledge_cognition"},
    {"pin": "plugin.code-research@latest", "as": "code_research"},
)


def manifest(plugins: tuple[dict[str, str], ...]) -> str:
    """The minimal Stage Graph on `deep_agents`, selecting only `plugins`."""

    document = yaml.safe_load(MINIMAL.read_text(encoding="utf-8"))
    mission = document["mission"]
    mission["application"] = APPLICATION
    environment = mission["environment"]
    del environment["capabilities"]
    environment["sandbox"] = {"profile": "research.standard"}
    environment["plugins"] = list(plugins)
    collect = mission["program"]["nodes"][0]
    collect["action_space"] = [plugin["as"] for plugin in plugins]
    return canonical_manifest_bytes(document).decode("utf-8")


async def compiled(plugins: tuple[dict[str, str], ...], *, extra: tuple[Any, ...] = ()) -> Any:
    definitions, search = await fast_track_catalog(directories=("common", APPLICATION))
    for definition in extra:
        await definitions.publish(definition, "fixture", NOW, 0)
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    compilation = await service.compile(
        manifest(plugins),
        ManifestScope(request_scope=SCOPE, actor_id="owner", at=datetime(2026, 11, 16, tzinfo=UTC)),
    )
    published = {
        item.ref.digest: item.definition for item in await definitions.list_published_definitions()
    }
    return compilation, published


def _members(definition: MissionDefinition) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for item in definition.capabilities:
        role = item.attributes.get("plugin_member_role")
        if role is not None:
            grouped.setdefault(str(role), []).append(item)
    return grouped


def _ref(kind: DefinitionKind, logical_id: str) -> ExactDefinitionRef:
    return ExactDefinitionRef(
        kind=kind, logical_id=logical_id, revision=1, digest=sha256_digest(f"served:{logical_id}")
    )


def bound(
    definition: MissionDefinition, published: dict[str, Any]
) -> tuple[ManifestLaunchBindings, ServedComponents]:
    """FIXTURE launch bindings: one exact component per Skill and MCP server member, as an
    operator would bind it. The capture server is bound the way its catalog row requires: a
    remote endpoint, its allowlist and the `allowlist` tool filter."""

    members = _members(definition)
    capabilities: dict[str, CapabilityComponentBinding] = {}
    for item in members["skill"]:
        name = item.resolved.capability_id.removeprefix("skill.")
        capabilities[item.resolved.capability_id] = CapabilityComponentBinding(
            catalog_digest=item.resolved.digest,
            kind="skill",
            skill=DeepAgentSkillComponent(
                ref=_ref(DefinitionKind.SKILL, item.resolved.capability_id),
                skill_name=name,
                bundle_digest=sha256_digest(f"bundle:{name}"),
                skill_md_digest=sha256_digest(f"skill-md:{name}"),
                mount_root=f"/skills/{name}",
                attachment_target="agent.main",
            ),
        )
    for item in members["mcp_server"]:
        logical_id = item.resolved.capability_id
        row = published[item.resolved.digest]
        names = sorted(row.tool_allowlist or row.allowed_tools)
        remote = row.transport != "stdio"
        capabilities[logical_id] = CapabilityComponentBinding(
            catalog_digest=item.resolved.digest,
            kind="mcp_server",
            mcp_server=DeepAgentMCPServerComponent(
                ref=_ref(DefinitionKind.MCP_SERVER, logical_id),
                server_name=logical_id.removeprefix("mcp.").replace("-", "_"),
                transport=row.transport,
                endpoint=CAPTURE_ENDPOINT if remote else None,
                command=None if remote else "/opt/mcp/" + logical_id,
                arguments=() if remote else tuple(row.launch_template[1:]),
                credential_refs=tuple(
                    SecretRef(provider="environment", key=name) for name in row.secret_refs
                ),
                tools=tuple(
                    DeepAgentMCPToolComponent(
                        tool_name=name, schema_digest=sha256_digest(f"{logical_id}:{name}")
                    )
                    for name in names
                ),
                schema_digest=sha256_digest(f"schema:{logical_id}"),
                attachment_target="agent.main",
                tool_filter="allowlist" if row.tool_allowlist is not None else "exact",
            ),
        )
    bindings = fixture_bindings().model_copy(update={"capabilities": capabilities})
    served = replace(
        fixture_served(bindings),
        mcp_servers=frozenset(
            item.mcp_server.ref.digest for item in capabilities.values() if item.mcp_server
        ),
        skills=frozenset(item.skill.bundle_digest for item in capabilities.values() if item.skill),
    )
    return bindings, served


def subagent_rows(
    definition: MissionDefinition, published: dict[str, Any]
) -> dict[str, ResolvedCapability]:
    rows = {}
    for item in _members(definition).get("subagent", ()):
        pin = item.resolved
        rows[f"{pin.capability_id}@{pin.version}#{pin.digest}"] = ResolvedCapability.model_validate(
            {"pin": pin.model_dump(mode="json"), "definition": published[pin.digest]}
        )
    return rows


async def test_every_member_of_a_node_plugin_is_bound_on_the_deep_agents_lane() -> None:
    compilation, published = await compiled(PLUGINS)
    assert compilation.report.blockers == (), compilation.report.blockers
    (definition,) = compilation.definitions
    (program,) = compilation.programs
    members = _members(definition)
    assert {role: len(items) for role, items in members.items()} == {
        "skill": 3,
        "mcp_server": 3,
        "subagent": 2,
    }
    bindings, served = bound(definition, published)

    templates = resolver(bindings, served=served).stage_templates(
        definition,
        AdmittedLaunch.from_configuration(SCOPE, "run-ip011", program.configuration),
        rows=subagent_rows(definition, published),
    )

    assert set(templates) == {"collect/execute/default", "synthesize/execute/default"}
    for template in templates.values():
        deep = DeepAgentExecutionBinding.carried_by(template)
        assert deep is not None
        # Each Skill and MCP server member is the exact component its own binding names.
        assert {skill.ref.logical_id for skill in deep.skills} == {
            item.resolved.capability_id for item in members["skill"]
        }
        servers = {server.ref.logical_id: server for server in deep.mcp_servers}
        assert set(servers) == {"mcp.context7", "mcp.github", "mcp.knowledge-capture"}
        for logical_id, server in servers.items():
            assert server == bindings.capabilities[logical_id].mcp_server
        capture = servers["mcp.knowledge-capture"]
        assert (capture.transport, capture.tool_filter) == ("streamable_http", "allowlist")
        assert len(capture.tools) == 23
        assert {"source_prepare_captured", "evidence_units", "chain_write"} <= {
            tool.tool_name for tool in capture.tools
        }
        assert not {"ingest_apply", "db_sql_readonly"} & {tool.tool_name for tool in capture.tools}
        assert (
            servers["mcp.github"].tool_filter == "exact" and len(servers["mcp.github"].tools) == 22
        )
        # Each subagent member is a child of the node.
        assert sorted(child.name for child in deep.sync_subagents) == [
            "mc-source-verifier",
            "mc-summarizer",
        ]
        # The operation is granted exactly the bound servers, and resolves their credentials.
        assert template.capability_grant.mcp_server_ids == {
            server.server_name for server in servers.values()
        }
        # The receipt names every member, none of them unsupported.
        receipt = deep.materialization_receipt
        assert receipt is not None
        assert not [item for item in receipt.items if item.verdict == "unsupported"]


async def test_a_member_without_a_launch_binding_refuses_at_the_member_not_the_plugin() -> None:
    compilation, published = await compiled(PLUGINS)
    (definition,) = compilation.definitions
    (program,) = compilation.programs
    bindings, served = bound(definition, published)
    unbound = bindings.model_copy(
        update={
            "capabilities": {
                key: value
                for key, value in bindings.capabilities.items()
                if key != "mcp.knowledge-capture"
            }
        }
    )

    with pytest.raises(ManifestLaunchBindingError) as refused:
        resolver(unbound, served=served).stage_templates(
            definition,
            AdmittedLaunch.from_configuration(SCOPE, "run-ip011", program.configuration),
            rows=subagent_rows(definition, published),
        )

    (capture,) = [
        item
        for item in definition.capabilities
        if item.resolved is not None and item.resolved.capability_id == "mcp.knowledge-capture"
    ]
    assert refused.value.pointer == capture.pointer
    assert "/plugins/0/members/" in refused.value.pointer
    assert "mcp.knowledge-capture" in refused.value.reason
    assert "has no deployment component binding" in refused.value.reason


async def test_a_hook_member_is_refused_at_compile_by_name() -> None:
    """A plugin with a hook script member, selected on a Deep Agents node: the compile blocks
    at the member and says which member and why; nothing waits for launch."""

    definitions, _search = await fast_track_catalog(directories=("common", APPLICATION))
    by_id = {item.ref.logical_id: item for item in await definitions.list_published_definitions()}
    hook = by_id["hook.shell-policy"]
    skill = by_id["skill.knowledge-research"]
    assert isinstance(hook.definition, HookScriptDefinition)
    plugin = PluginDefinition(
        logical_id="plugin.guarded-research",
        title="Research with a shell policy hook",
        description="The research method skill with a shell policy hook script.",
        manifest=PluginManifest(
            members=(
                PluginMember(pin=capability_pin(skill), role=PluginMemberRole.SKILL),
                PluginMember(pin=capability_pin(hook), role=PluginMemberRole.HOOK),
            )
        ),
        host_support=hook.definition.host_support,
    )

    compilation, _published = await compiled(
        ({"pin": "plugin.guarded-research@latest", "as": "guarded"},), extra=(plugin,)
    )

    blockers = [
        item
        for item in compilation.report.blockers
        if item.reason == "plugin_member_unsupported_on_lane"
    ]
    (blocker,) = blockers
    assert blocker.pointer == "/mission/environment/plugins/0/members/1"
    assert capability_pin(hook).render() in blocker.message
    assert "is a hook member of plugin plugin.guarded-research@" in blocker.message
    assert "deep_agents" in blocker.message
    assert not compilation.ok
    # The plugin's runnable member still resolved; only the hook is refused.
    assert compilation.resolution is not None
    resolved = {
        item.result.capability_id
        for item in compilation.resolution.resolved
        if item.result is not None
    }
    assert "skill.knowledge-research" in resolved and "hook.shell-policy" not in resolved


async def test_an_optional_member_without_a_launch_binding_is_unsupported_not_refused() -> None:
    """A member its plugin marks optional, unbound on this installation: the launch records it
    `unsupported` in the node's receipt, by name and reason, and does not mount it; the
    preflight's launch-binding check names it as a degradation, not a blocker."""

    from mission_control.application.authoring.manifest_launch_inputs import (
        deep_agents_binding_gaps,
    )

    definitions, _search = await fast_track_catalog(directories=("common", APPLICATION))
    by_id = {item.ref.logical_id: item for item in await definitions.list_published_definitions()}
    skill = by_id["skill.knowledge-research"]
    github = by_id["mcp.github"]
    plugin = PluginDefinition(
        logical_id="plugin.optional-code",
        title="Research with optional code search",
        description="The research method skill and an optional GitHub server.",
        manifest=PluginManifest(
            members=(
                PluginMember(pin=capability_pin(skill), role=PluginMemberRole.SKILL),
                PluginMember(
                    pin=capability_pin(github), role=PluginMemberRole.MCP_SERVER, optional=True
                ),
            )
        ),
        host_support=skill.definition.host_support,
    )
    compilation, published = await compiled(
        ({"pin": "plugin.optional-code@latest", "as": "code"},), extra=(plugin,)
    )
    assert compilation.report.blockers == (), compilation.report.blockers
    (definition,) = compilation.definitions
    (program,) = compilation.programs
    bindings, served = bound(definition, published)
    unbound = bindings.model_copy(
        update={
            "capabilities": {
                key: value for key, value in bindings.capabilities.items() if key != "mcp.github"
            }
        }
    )

    blockers, degradations = deep_agents_binding_gaps(definition, unbound)
    assert blockers == ()
    assert degradations and all("mcp.github@" in item for item in degradations)
    assert all("optional member of plugin plugin.optional-code" in item for item in degradations)
    assert deep_agents_binding_gaps(definition, bindings) == ((), ())

    templates = resolver(unbound, served=served).stage_templates(
        definition,
        AdmittedLaunch.from_configuration(SCOPE, "run-optional", program.configuration),
        rows=subagent_rows(definition, published),
    )
    for template in templates.values():
        deep = DeepAgentExecutionBinding.carried_by(template)
        assert deep is not None
        assert "mcp.github" not in {server.ref.logical_id for server in deep.mcp_servers}
        assert {skill.ref.logical_id for skill in deep.skills} == {"skill.knowledge-research"}
        receipt = deep.materialization_receipt
        assert receipt is not None
        (row,) = [item for item in receipt.items if item.verdict == "unsupported"]
        assert row.name.startswith("mcp.github")
        assert row.reason is not None and row.reason.startswith("optional: ")

    # Required, the same unbound member refuses the launch at the member, by name.
    required = PluginDefinition.model_validate(
        {
            **plugin.model_dump(mode="python"),
            "logical_id": "plugin.required-code",
            "manifest": PluginManifest(
                members=(
                    PluginMember(pin=capability_pin(skill), role=PluginMemberRole.SKILL),
                    PluginMember(pin=capability_pin(github), role=PluginMemberRole.MCP_SERVER),
                )
            ),
        }
    )
    compilation, published = await compiled(
        ({"pin": "plugin.required-code@latest", "as": "code"},), extra=(required,)
    )
    (definition,) = compilation.definitions
    (program,) = compilation.programs
    bindings, served = bound(definition, published)
    unbound = bindings.model_copy(
        update={
            "capabilities": {
                key: value for key, value in bindings.capabilities.items() if key != "mcp.github"
            }
        }
    )
    blockers, degradations = deep_agents_binding_gaps(definition, unbound)
    assert blockers and degradations == ()
    with pytest.raises(ManifestLaunchBindingError) as refused:
        resolver(unbound, served=served).stage_templates(
            definition,
            AdmittedLaunch.from_configuration(SCOPE, "run-required", program.configuration),
            rows=subagent_rows(definition, published),
        )
    assert "mcp.github" in refused.value.reason


async def test_a_deep_agents_executor_promising_outputs_without_submit_output_is_warned() -> None:
    """Its final message is not a submission: compile names the node and the remedy. Only a
    text promise is checked (a structured one can also be published through artifact custody)."""

    definitions, search = await fast_track_catalog(directories=("common", APPLICATION))
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )

    async def warnings(document: dict[str, Any]) -> list[Any]:
        compilation = await service.compile(
            canonical_manifest_bytes(document).decode("utf-8"),
            ManifestScope(
                request_scope=SCOPE, actor_id="owner", at=datetime(2026, 11, 16, tzinfo=UTC)
            ),
        )
        return [
            item
            for item in compilation.report.warnings
            if item.reason == "output_submission_missing"
        ]

    document = yaml.safe_load(manifest(PLUGINS))
    # The schema outputs of the minimal manifest are not checked.
    assert await warnings(document) == []
    synthesize = document["mission"]["program"]["nodes"][1]
    synthesize["outputs"].append({"name": "summary", "form": "text"})
    (warning,) = await warnings(document)
    assert warning.pointer == "/mission/program/nodes/1/outputs"
    assert "synthesize promises summary" in warning.message
    assert "tool.knowledge-submit-output@latest" in warning.message

    document["mission"]["environment"]["capabilities"] = [
        {"pin": "tool.knowledge-submit-output@latest", "kind": "tool", "as": "submit_output"}
    ]
    assert await warnings(document) == []

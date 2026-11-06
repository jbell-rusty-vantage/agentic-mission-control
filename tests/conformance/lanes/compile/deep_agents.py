"""The Deep Agents compile conformance entry: the real lane compile on the canonical fixtures.

`DeepAgentsCompileAdapter` (``adapters/deep_agents/compile.py``) is driven exactly as the launch
author drives it, so the entry supplies what that author always adds before resolution and what
a deployment serves:

- **deployment facts** (FIXTURE): the manifest-launch fixture scaffold, one model component per
  vendor pin, the canonical skill and MCP pins bound to served components (named by the item
  names, as a deployment names them), a served Agent Server graph for the async child;
- **the author's part of each item** (`AuthoredDeepAgentsAdapter`): the catalog body of each
  subagent profile (an inherit, a seeded and an async child, the shapes the fixture names) and
  the node's sandbox profile, which a Deep Agents manifest node always selects.

The canonical hook script, environment kit (and any context bundle) are `unsupported` on this
lane: not required in the fixtures they become `unsupported` receipt rows; required, they refuse.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from mission_control.adapters.deep_agents.compile import (
    DEEP_AGENTS_DECLARATION,
    DeepAgentsCompileAdapter,
    DeepAgentsDeploymentFacts,
)
from mission_control.application.agentic_components.layering import RepoView
from mission_control.application.authoring.manifest_launch_inputs import (
    AsyncSubagentGraphBinding,
    CapabilityComponentBinding,
    DeepAgentModelBinding,
    ServedComponents,
)
from mission_control.domain.agentic_components.projection import HostProjection
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.capabilities.subagents import SubagentProfile
from mission_control.domain.execution.contracts import (
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
    DeepAgentSkillComponent,
)
from mission_control.domain.execution.materialization_receipt import MaterializationReceipt
from mission_control.domain.resolution import item_config
from mission_control.domain.resolution.configuration import (
    AgentConfiguration,
    ConfigurationItem,
)
from mission_control.domain.resolution.profiles import LaneDeclaration
from mission_control.domain.resolution.resolved import SealedLaneBinding
from tests.conformance.lanes.compile.contract import CompileCheck
from tests.conformance.lanes.compile.fixtures import CANONICAL_ITEMS, VENDOR_PINS
from tests.conformance.lanes.contract import DeclaredException
from tests.fixtures.models import checked_in_catalog
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings, fixture_served

SANDBOX_PROFILE: Final = "research.standard"

# The catalog bodies of the canonical subagent items (by item name).
CHILD_PROFILES: Final[Mapping[str, SubagentProfile]] = {
    "summarizer": SubagentProfile.model_validate(
        {
            "name": "summarizer",
            "description": "Summarizes with the parent's tools.",
            "capabilities": "inherit",
        }
    ),
    "verifier": SubagentProfile.model_validate(
        {
            "name": "verifier",
            "description": "Verifies claims in the browser.",
            "prompt": "You verify each claim against its cited page and report findings.",
            "mcp_servers": ["browser"],
        }
    ),
    "async-verifier": SubagentProfile.model_validate(
        {
            "name": "async-verifier",
            "description": "Verifies claims on the Agent Server.",
            "prompt": "You verify each claim and return a structured verdict.",
            "kind": "async",
            "placement": "agent_server",
            "sandbox": "own",
        }
    ),
}


def _ref(kind: DefinitionKind, logical_id: str) -> ExactDefinitionRef:
    return ExactDefinitionRef(
        kind=kind, logical_id=logical_id, revision=1, digest=sha256_digest(logical_id)
    )


def _pin_parts(item: ConfigurationItem) -> tuple[str, str]:
    capability_id, _, rest = item.pin.partition("@")
    return capability_id, rest.partition("#")[2]


def _components() -> dict[str, CapabilityComponentBinding]:
    by_name = {item.name: item for item in CANONICAL_ITEMS}
    skill, browser, firecrawl = (
        by_name["agent-browser-skill"],
        by_name["browser"],
        by_name["firecrawl"],
    )
    tools = tuple(
        DeepAgentMCPToolComponent(tool_name=name, schema_digest=sha256_digest(name))
        for name in ("open", "snapshot")
    )
    return {
        _pin_parts(skill)[0]: CapabilityComponentBinding(
            catalog_digest=skill.digest,
            kind="skill",
            skill=DeepAgentSkillComponent(
                ref=_ref(DefinitionKind.SKILL, _pin_parts(skill)[0]),
                skill_name="agent-browser-skill",
                bundle_digest=sha256_digest("agent-browser-bundle"),
                skill_md_digest=sha256_digest("agent-browser-skill-md"),
                mount_root="/skills/agent-browser-skill",
                attachment_target="agent.parent",
            ),
        ),
        _pin_parts(browser)[0]: CapabilityComponentBinding(
            catalog_digest=browser.digest,
            kind="mcp_server",
            mcp_server=DeepAgentMCPServerComponent(
                ref=_ref(DefinitionKind.MCP_SERVER, _pin_parts(browser)[0]),
                server_name="browser",
                transport="stdio",
                command="agent-browser-mcp",
                tools=tools,
                schema_digest=sha256_digest("browser-schema"),
                attachment_target="agent.parent",
            ),
        ),
        _pin_parts(firecrawl)[0]: CapabilityComponentBinding(
            catalog_digest=firecrawl.digest,
            kind="mcp_server",
            mcp_server=DeepAgentMCPServerComponent(
                ref=_ref(DefinitionKind.MCP_SERVER, _pin_parts(firecrawl)[0]),
                server_name="firecrawl",
                transport="streamable_http",
                endpoint="https://mcp.firecrawl.example/mcp",
                tools=(
                    DeepAgentMCPToolComponent(
                        tool_name="scrape", schema_digest=sha256_digest("scrape")
                    ),
                ),
                schema_digest=sha256_digest("firecrawl-schema"),
                attachment_target="agent.parent",
            ),
        ),
    }


def deep_agents_facts() -> DeepAgentsDeploymentFacts:
    """FIXTURE deployment facts serving every canonical item this lane supports."""

    bindings = fixture_bindings(model_profiles=(), sandbox_profiles=(SANDBOX_PROFILE,))
    base = fixture_bindings().model_profiles["frontier.default"]
    # OC-R6: references to the checked-in Model Catalog, one served definition per vendor pin.
    models = {
        pin.profile: DeepAgentModelBinding(
            ref=_ref(DefinitionKind.MODEL, f"model.{pin.model_id}"), settings=dict(base.settings)
        )
        for pin in VENDOR_PINS.values()
    }
    components = _components()
    bindings = bindings.model_copy(update={"model_profiles": models, "capabilities": components})
    served = fixture_served(bindings)
    served = ServedComponents(
        qualification=True,  # OC-R6: an explicit test composition
        models=served.models,
        sandboxes=served.sandboxes,
        checkpointers=served.checkpointers,
        stores=served.stores,
        mcp_servers=frozenset(
            item.mcp_server.ref.digest for item in components.values() if item.mcp_server
        ),
        skills=frozenset(item.skill.bundle_digest for item in components.values() if item.skill),
    )
    graph = AsyncSubagentGraphBinding(
        graph_id="belllabs_async_technical_child",
        graph_revision="agent.async-technical-child@1",
        graph_binding_digest=sha256_digest("async-verifier-graph"),
        agent_protocol_url="http://127.0.0.1:2024",
        objective_schema_ref="schema:objective@1",
        result_schema_ref="schema:result@1",
        result_admission_policy_ref="policy:async-result:technical-child@1",
        default_budget_limits={"tokens.total": 1000},
    )
    return DeepAgentsDeploymentFacts.from_bindings(
        bindings.model_copy(update={"deep_agents_async_graphs": {"async-verifier": graph}}),
        served,
        models=checked_in_catalog(),
        async_result_policy_refs=frozenset({graph.result_admission_policy_ref}),
    )


def authored(agent: AgentConfiguration) -> AgentConfiguration:
    """What the launch author adds before resolution: children's catalog bodies, the sandbox."""

    items: list[ConfigurationItem] = []
    for position, item in enumerate(agent.items):
        profile = CHILD_PROFILES.get(item.name)
        if item.kind == "subagent_profile" and profile is not None:
            item = ConfigurationItem.create(
                kind=item.kind,
                name=item.name,
                pin=item.pin,
                required=item.required,
                config={
                    **item.config,
                    item_config.ROLE: "agent",
                    item_config.PROFILE: profile.model_dump(mode="json"),
                    item_config.POSITION: position,
                },
            )
        items.append(item)
    digest = sha256_digest({"kind": "sandbox_profile", "profile": SANDBOX_PROFILE})
    items.append(
        ConfigurationItem.create(
            kind="sandbox_profile",
            name=f"sandbox_profile:{SANDBOX_PROFILE}",
            pin=f"sandbox-profile.{SANDBOX_PROFILE}@selected#{digest}",
            required=True,
            config={item_config.PROFILE_NAME: SANDBOX_PROFILE},
        )
    )
    return AgentConfiguration.create(
        lane_profile=agent.lane_profile,
        node_ref=agent.node_ref,
        instructions_ref=agent.instructions_ref,
        model=agent.model,
        items=items,
        budgets=agent.budgets,
        data_class=agent.data_class,
        data_class_source=agent.data_class_source,
    )


class AuthoredDeepAgentsAdapter:
    """The real compile, given the canonical agent as the launch author completes it."""

    def __init__(self) -> None:
        self._adapter = DeepAgentsCompileAdapter(deep_agents_facts())

    @property
    def profile(self) -> str:
        return self._adapter.profile

    def compile(
        self, agent: AgentConfiguration, lane_options: Mapping[str, Any]
    ) -> tuple[SealedLaneBinding, MaterializationReceipt]:
        return self._adapter.compile(authored(agent), lane_options)

    def project(
        self, agent: AgentConfiguration, repo_view: RepoView | None
    ) -> HostProjection | None:
        return self._adapter.project(agent, repo_view)


class DeepAgentsCompileConformance:
    @property
    def profile(self) -> str:
        return "deep_agents"

    def adapter(self) -> AuthoredDeepAgentsAdapter:
        return AuthoredDeepAgentsAdapter()

    def declaration(self) -> LaneDeclaration:
        return DEEP_AGENTS_DECLARATION

    def options(self) -> Mapping[str, Any]:
        return {}

    @property
    def exceptions(self) -> Mapping[CompileCheck, DeclaredException]:
        return {
            CompileCheck.RECEIPT_ITEM_DIGESTS: DeclaredException(
                reason=(
                    "the Deep Agents receipt records the digest of what it materialized (an MCP "
                    "server's schema digest, a Skill bundle digest, a child's inline prompt "
                    "digest, an async graph binding digest), not the catalog pin digest; the "
                    "pin travels on the neutral item and in the sealed profile"
                ),
                evidence=(
                    "tests/unit/deep_agents/test_lane_adapter.py",
                    "tests/unit/deep_agents/test_lane_adapter_children.py",
                ),
            )
        }


__all__ = [
    "CHILD_PROFILES",
    "AuthoredDeepAgentsAdapter",
    "DeepAgentsCompileConformance",
    "authored",
    "deep_agents_facts",
]

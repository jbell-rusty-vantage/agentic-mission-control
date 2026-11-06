"""The launch author's side of the resolution seam (OC-R1 review S1, S3).

Refusal pointers map back to the manifest pointer per pointer class; the refusals the resolver
owns (application, model, lane qualification) surface at launch at those pointers; the node's
Data Class is the manifest's declared class, or, failing closed (OC-R4), the most sensitive
class the lane and the application's ceiling admit; a lane that admits only declared classes
refuses an undeclared mission.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mission_control.adapters.deep_agents.binding import DEEP_AGENTS_LANE_BINDINGS
from mission_control.adapters.deep_agents.compile import (
    DEEP_AGENTS_DECLARATION,
    DeepAgentsCompileAdapter,
    DeepAgentsDeploymentFacts,
)
from mission_control.adapters.deep_agents.describe import DEEP_AGENTS_DESCRIBE
from mission_control.application.authoring.manifest_launch_inputs import (
    LaunchResolution,
    ManifestLaunchBindingError,
    ManifestLaunchBindings,
    ManifestLaunchResolver,
    _manifest_pointer,
    launch_data_class,
)
from mission_control.application.resolution.ports import LaneRegistration
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    DescribeOnlyLane,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.domain.authoring.mission_definition import (
    CapabilityPin,
    DefinitionCapability,
    MissionDefinition,
)
from mission_control.domain.resolution.resolved import ResolvedRuntime
from tests.fixtures.applications import installed_applications
from tests.fixtures.models import bindings_catalog
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings, pubmed_bound
from tests.unit.authoring.test_manifest_launch_inputs import (
    MINIMAL,
    admitted,
    compile_programs,
    pubmed_digest,
    served_with_mcp,
)
from tests.unit.authoring.test_manifest_v2_launch import compiled_ok, edited, example

ITEMS = {
    "/items/0": "/mission/environment/capabilities/0",
    "/items/1": "/mission/environment/plugins/0/members/1",
}
NODE = "/mission/program/nodes/1/environment"
CONTEXT = {
    "items": ITEMS,
    "lane": NODE + "/lane",
    "model": NODE + "/model/profile",
    "node": NODE,
    "mission": "/mission",
}


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("/items/0", "/mission/environment/capabilities/0"),
        ("/items/0/seeds/skills/0", "/mission/environment/capabilities/0/seeds/skills/0"),
        ("/items/1/plugin", "/mission/environment/plugins/0"),
        ("/items/0/plugin", "/mission/environment/capabilities/0/plugin"),
        ("/lane", NODE + "/lane"),
        ("/model/profile", NODE + "/model/profile"),
        (
            "/model/settings/temperature",
            NODE + "/model/settings/temperature",
        ),
        (
            "/provider_options/deep_agents/x",
            NODE + "/provider_options/deep_agents/x",
        ),
        ("/application", "/mission/application"),
        ("/data_class", "/mission/data_class"),
        ("/items", NODE + "/items"),
        ("/items/9", NODE + "/items/9"),
        ("/behavior", NODE + "/behavior"),
    ],
    ids=[
        "item",
        "item-suffix",
        "plugin-row",
        "plugin-suffix-not-a-member",
        "lane",
        "model-profile",
        "model-beside",
        "lane-options",
        "mission-application",
        "mission-data-class",
        "items-count",
        "unknown-item-index",
        "node-other",
    ],
)
def test_each_pointer_class_maps_to_its_manifest_pointer(pointer: str, expected: str) -> None:
    assert _manifest_pointer(pointer, **CONTEXT) == expected


# --- launch-level refusals the resolver owns --------------------------------------------------


@pytest.fixture(scope="module")
def minimal() -> tuple[MissionDefinition, Any]:
    definitions, programs = asyncio.run(compile_programs(MINIMAL.read_text(encoding="utf-8")))
    return definitions[0], programs[0]


def _bound(definition: MissionDefinition) -> ManifestLaunchBindings:
    return pubmed_bound(fixture_bindings(), pubmed_digest(definition))


def _resolver(
    bindings: ManifestLaunchBindings,
    *,
    registration: LaneRegistration | None = None,
    applications: ApplicationRegistry | None = None,
    resolver_models: ModelCatalog | None = None,
) -> ManifestLaunchResolver:
    models = bindings_catalog(bindings)
    facts = DeepAgentsDeploymentFacts.from_bindings(
        bindings, served_with_mcp(bindings), models=models
    )
    registration = registration or LaneRegistration(
        profile="deep_agents",
        declaration=DEEP_AGENTS_DECLARATION,
        adapter=DeepAgentsCompileAdapter(facts),
        harness_factory=lambda _deps: DescribeOnlyLane(DEEP_AGENTS_DESCRIBE),
    )
    lanes = LaneRegistry()
    lanes.register(registration, DescribeOnlyLane(registration.declaration.describe))
    registry = applications if applications is not None else installed_applications()
    return ManifestLaunchResolver(
        bindings,
        provider_secret_env={"openai": "OPENAI_API_KEY"},
        resolution=LaunchResolution(
            runtime=RuntimeResolver(
                lanes,
                registry,
                resolver_models if resolver_models is not None else models,
                allow_unqualified_lanes=False,
            ),
            models=models,
            applications=registry,
            templates=DEEP_AGENTS_LANE_BINDINGS,
        ),
    )


def _refused(resolver: ManifestLaunchResolver, minimal: Any) -> ManifestLaunchBindingError:
    definition, program = minimal
    with pytest.raises(ManifestLaunchBindingError) as raised:
        resolver.stage_templates(definition, admitted(program))
    return raised.value


def test_an_unregistered_application_refuses_at_the_mission_application(minimal: Any) -> None:
    applications = installed_applications("ai-engineer")
    refused = _refused(_resolver(_bound(minimal[0]), applications=applications), minimal)
    assert refused.pointer == "/mission/application"
    assert "application biotech is not registered" in refused.reason


def test_a_model_the_resolver_does_not_catalog_refuses_at_the_model_profile(
    minimal: Any,
) -> None:
    refused = _refused(_resolver(_bound(minimal[0]), resolver_models=ModelCatalog()), minimal)
    assert refused.pointer.endswith("/environment/model/profile")
    assert "is not in the model catalog" in refused.reason


def test_an_unqualified_lane_refuses_at_the_lane(minimal: Any) -> None:
    bindings = _bound(minimal[0])
    facts = DeepAgentsDeploymentFacts.from_bindings(
        bindings, served_with_mcp(bindings), models=bindings_catalog(bindings)
    )
    unqualified = DEEP_AGENTS_DESCRIBE.unqualified()
    registration = LaneRegistration(
        profile="deep_agents",
        declaration=DEEP_AGENTS_DECLARATION.model_copy(update={"describe": unqualified}),
        adapter=DeepAgentsCompileAdapter(facts),
        harness_factory=lambda _deps: DescribeOnlyLane(unqualified),
    )
    refused = _refused(_resolver(bindings, registration=registration), minimal)
    assert refused.pointer.endswith("/environment/lane")
    assert "has no recorded qualification" in refused.reason


# --- the node's Data Class (S1) ---------------------------------------------------------------


def _with_ceiling(ceiling: str) -> ApplicationRegistry:
    """The checked-in profiles, the minimal mission's application at another ceiling."""

    installed = installed_applications()
    return ApplicationRegistry(
        installed.get(app).model_copy(update={"data_class_ceiling": ceiling})
        if app == "biotech"
        else installed.get(app)
        for app in installed.applications()
    )


def _node_runtime(
    minimal: Any, definition: MissionDefinition, applications: ApplicationRegistry | None = None
) -> ResolvedRuntime:
    _, program = minimal
    root = definition.program
    resolved = _resolver(_bound(definition), applications=applications).deep_agents_node(
        definition, (root, root.nodes[0]), verifier=False, admitted=admitted(program)
    )
    return resolved.runtime


def _node_data_class(
    minimal: Any, definition: MissionDefinition, applications: ApplicationRegistry | None = None
) -> str:
    return _node_runtime(minimal, definition, applications).agent.data_class


def test_an_undeclared_and_a_declared_internal_mission_seal_differently(minimal: Any) -> None:
    """OC-R4 review B1: the class's provenance enters the configuration digest, so a mission
    defaulted to an `internal` ceiling never seals to the same runtime as a declared one."""

    undeclared = _node_runtime(minimal, minimal[0])
    declared = _node_runtime(minimal, minimal[0].model_copy(update={"data_class": "internal"}))

    assert undeclared.agent.data_class == declared.agent.data_class == "internal"
    assert undeclared.agent.data_class_source == "ceiling_default"
    assert declared.agent.data_class_source == "declared"
    assert undeclared.agent.configuration_digest != declared.agent.configuration_digest
    assert undeclared.runtime_digest != declared.runtime_digest


def test_a_declared_data_class_is_the_configurations(minimal: Any) -> None:
    assert minimal[0].application == "biotech"
    declared = minimal[0].model_copy(update={"data_class": "public"})
    assert _node_data_class(minimal, declared) == "public"
    wider = minimal[0].model_copy(update={"data_class": "confidential"})
    assert _node_data_class(minimal, wider, _with_ceiling("confidential")) == "confidential"


def test_a_declared_class_above_the_installed_ceiling_is_refused(minimal: Any) -> None:
    """The checked-in Biotech profile admits up to `internal` (R4 engineering default)."""

    definition, program = minimal
    wider = definition.model_copy(update={"data_class": "confidential"})
    with pytest.raises(ManifestLaunchBindingError) as raised:
        _resolver(_bound(definition)).stage_templates(wider, admitted(program))
    assert raised.value.pointer == "/mission/data_class"
    assert "application biotech admits data up to internal" in raised.value.reason


def test_an_undeclared_mission_fails_closed_to_the_application_ceiling(minimal: Any) -> None:
    """OC-R4 (R1 review prerequisite): no stand-in. An undeclared mission is handled as the
    most sensitive class its lane and application admit, so it follows the ceiling where a
    declared `internal` mission does not."""

    undeclared = minimal[0]
    assert undeclared.data_class is None
    declared_internal = undeclared.model_copy(update={"data_class": "internal"})
    assert _node_data_class(minimal, undeclared) == "internal"  # the installed ceiling
    raised = _with_ceiling("confidential")
    assert _node_data_class(minimal, undeclared, raised) == "confidential"
    assert _node_data_class(minimal, declared_internal, raised) == "internal"
    secret = _with_ceiling("secret")
    assert _node_data_class(minimal, undeclared, secret) == "secret"


def test_an_undeclared_mission_is_refused_by_a_model_below_the_ceiling(minimal: Any) -> None:
    definition, program = minimal
    bindings = _bound(definition)
    narrow = ModelCatalog(
        profile.model_copy(update={"data_class_ceiling": "internal"})
        for profile in (
            bindings_catalog(bindings).get(name) for name in bindings_catalog(bindings).profiles()
        )
    )
    resolver = _resolver(
        bindings, applications=_with_ceiling("confidential"), resolver_models=narrow
    )
    with pytest.raises(ManifestLaunchBindingError) as raised:
        resolver.stage_templates(definition, admitted(program))
    assert raised.value.pointer == "/mission/data_class"
    assert "admits data up to internal; the mission's data class is confidential" in (
        raised.value.reason
    )


@pytest.mark.parametrize("lane", ["claude_managed", "codex_agents"])
def test_a_hosted_agent_api_refuses_an_undeclared_mission(minimal: Any, lane: str) -> None:
    with pytest.raises(ManifestLaunchBindingError) as raised:
        launch_data_class(
            minimal[0], lane, pointer="/mission/environment/lane", ceiling="confidential"
        )
    assert raised.value.pointer == "/mission/environment/lane"
    assert raised.value.reason.startswith("DATA_CLASS_UNDECLARED: ")
    assert launch_data_class(
        minimal[0].model_copy(update={"data_class": "internal"}),
        lane,
        pointer="/x",
        ceiling="confidential",
    ) == ("internal", "declared")
    assert launch_data_class(minimal[0], "deep_agents", pointer="/x", ceiling="confidential") == (
        "confidential",
        "ceiling_default",
    )


def test_compile_carries_the_manifest_data_class_onto_the_definition() -> None:
    declared = compiled_ok(
        edited(
            example("codex", "stage-graph"),
            lambda document: document["mission"].__setitem__("data_class", "confidential"),
        )
    )
    assert declared.definitions[0].data_class == "confidential"
    undeclared = compiled_ok(example("codex", "stage-graph").read_text(encoding="utf-8"))
    assert undeclared.definitions[0].data_class is None
    assert "data_class" not in undeclared.definitions[0].model_dump(mode="json")


def test_a_plugin_that_expanded_to_no_members_does_not_pass_silently(minimal: Any) -> None:
    definition, program = minimal
    row = DefinitionCapability(
        pointer="/mission/environment/plugins/0",
        role="plugin",
        pin=CapabilityPin(
            capability_id="plugin.empty", version="1.0.0", digest="sha256:" + "a" * 64
        ),
    )
    bare = definition.model_copy(update={"capabilities": (*definition.capabilities, row)})
    with pytest.raises(ManifestLaunchBindingError) as raised:
        _resolver(_bound(definition)).stage_templates(bare, admitted(program))
    assert raised.value.pointer == "/mission/environment/plugins/0"
    assert "plugin plugin.empty@1.0.0 expanded to no members" in raised.value.reason

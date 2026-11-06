"""W1 D9: the launch authors serve the knowledge tool components the worker registers.

Before D9 the API's launch author (``bootstrap/api.py``) and the worker's chain-relay author
composed ``compose_manifest_launch_inputs`` with no ``additional``, so their served set held only
the pin file's tools and a manifest selecting ``tool.knowledge-report-register@1`` was refused
at start ("binds a component this deployment does not serve"), while the worker registered the
tools. Now one shared definition (``served_knowledge_tools``) serves them wherever the knowledge
binding is configured, and nowhere else.

The launch author is composed here exactly as the API and the chain relay compose it (settings,
the real pin file, the bindings file, no ``additional``); the served set it hands the resolver is
recorded. Admission then runs the knowledge-tools manifest against that served tool set (the
fixture's own model/sandbox components stand in for the worker's qualification models).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from mission_control.adapters.capabilities.capability_pins import CapabilityPins
from mission_control.adapters.deep_agents.knowledge_tools import (
    knowledge_launch_bindings,
    knowledge_tool_components,
    knowledge_tools,
    served_knowledge_tools,
)
from mission_control.adapters.knowledge.credentials import (
    CredentialVerifier,
    generate_signing_key,
    publish_jwks,
    write_private_jwk,
)
from mission_control.application.authoring.manifest_launch_inputs import ServedComponents
from mission_control.application.knowledge.toolset import TOOL_NAMES
from mission_control.bootstrap import manifests
from mission_control.bootstrap.composition import (
    KnowledgeConfigurationError,
    compose_knowledge_lane,
)
from mission_control.domain.execution.contracts import DeepAgentExecutionBinding
from tests.fixtures.isolated_settings import isolated_settings
from tests.fixtures.knowledge_binding import FakeKnowledgeBinding, SteppingClock
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings
from tests.unit.authoring.test_manifest_launch_inputs import (
    admitted,
    compile_programs,
    fixture_served,
    resolver,
)
from tests.unit.knowledge.test_knowledge_manifest import MANIFEST, SCOPE

APP = "ai-engineer"
CATALOG = "mc/00000000-0000-7000-8000-000000000001/ai-engineer/catalog"
REGISTER = "tool.knowledge-report-register"


def knowledge_settings(tmp_path: Path, bindings_file: Path, **overrides: Any):
    active = generate_signing_key("mc-k2")
    write_private_jwk(active, tmp_path / "active.jwk.json")
    settings = isolated_settings(
        knowledge_binding_url="http://127.0.0.1:4310",
        knowledge_binding_audience="knowledge-services-executor.ai-engineer",
        knowledge_issuer="mission-control.ai-engineer",
        knowledge_issuer_key_file=tmp_path / "active.jwk.json",
        manifest_launch_bindings_path=bindings_file,
        mission_control_catalog_scope=CATALOG,
        **overrides,
    )
    return settings, active


@pytest.fixture(scope="module")
def compiled() -> tuple[Any, Any]:
    definitions, programs = asyncio.run(
        compile_programs(MANIFEST.read_text(encoding="utf-8"), scope=SCOPE)
    )
    return definitions[0], programs[0]


def bindings_file(tmp_path: Path, compiled: tuple[Any, Any]) -> tuple[Path, Any]:
    """The deployment's launch bindings: the fixture scaffold plus the catalog knowledge rows
    bound to the served tool definitions (`knowledge_launch_bindings`)."""

    definition, _program = compiled
    pins = {
        item.resolved.capability_id: item.resolved.digest
        for item in definition.capabilities
        if item.resolved is not None
    }
    bindings = fixture_bindings().model_copy(
        update={"capabilities": knowledge_launch_bindings(pins, knowledge_tools(cast(Any, None)))}
    )
    # The file the deployment names: no fixture model rows (the installation's Model Catalog
    # declares its own); admission below uses the full fixture bindings.
    deployed = bindings.model_copy(update={"model_profiles": {}})
    path = tmp_path / "launch-bindings.json"
    path.write_text(deployed.model_dump_json(), encoding="utf-8")
    return path, bindings


def served_by_production_author(
    monkeypatch: pytest.MonkeyPatch, settings: Any, application_id: str = APP
) -> ServedComponents:
    """Compose the launch author as the API and the chain relay do; return what it serves."""

    recorded: list[ServedComponents] = []
    real = manifests.compose_manifest_launch_resolver

    def record(bindings: Any, served: ServedComponents, **kwargs: Any) -> Any:
        recorded.append(served)
        return real(bindings, served, **kwargs)

    monkeypatch.setattr(manifests, "compose_manifest_launch_resolver", record)
    author = manifests.compose_manifest_launch_inputs(
        cast(Any, object()),
        settings=settings,
        application_id=application_id,
        run_control=cast(Any, object()),
        control_plane=cast(Any, object()),
    )
    assert author is not None
    (served,) = recorded
    return served


def test_the_production_author_admits_a_manifest_selecting_report_register(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, compiled: tuple[Any, Any]
) -> None:
    path, bindings = bindings_file(tmp_path, compiled)
    settings, _active = knowledge_settings(tmp_path, path)
    served = served_by_production_author(monkeypatch, settings)
    definitions = served_knowledge_tools()
    knowledge = set(definitions)
    current = {
        component.ref.digest
        for component in knowledge_tool_components(knowledge_tools(cast(Any, None)))
    }
    legacy_submit_digest = "sha256:16d044dda28c3bb0e82a703e55cbc151cfd8cd70c986e283208c6c42e2823bc0"
    assert len(TOOL_NAMES) == 7  # + knowledge_read_intent (OVE-204 slice 4)
    assert {tool.name for tool in definitions.values()} == set(TOOL_NAMES)
    assert knowledge == current | {legacy_submit_digest}
    legacy = definitions[legacy_submit_digest]
    assert legacy.name == "submit_output"
    schema = legacy.tool_call_schema.model_json_schema()
    assert set(schema["properties"]) == {"obligation", "deliverable", "items"}
    assert set(schema["required"]) == {"obligation", "items"}
    assert knowledge <= served.tools
    pin_tools = {item.ref.digest for item in CapabilityPins.from_settings(settings).tools}
    assert served.tools == frozenset(pin_tools | knowledge)

    definition, program = compiled
    templates = resolver(
        bindings, served=replace(fixture_served(bindings), tools=served.tools)
    ).stage_templates(definition, admitted(program, scope=SCOPE))
    draft = DeepAgentExecutionBinding.carried_by(next(iter(templates.values())))
    assert draft is not None
    registered = {
        item.tool_name: item for item in knowledge_tool_components(knowledge_tools(cast(Any, None)))
    }
    by_name = {tool.tool_name: tool for tool in draft.tools}
    assert by_name["report_register"] == registered["report_register"]
    assert bindings.capabilities[REGISTER].tool == registered["report_register"]


def test_without_a_knowledge_binding_no_knowledge_tool_is_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, compiled: tuple[Any, Any]
) -> None:
    from mission_control.application.authoring.manifest_launch_inputs import (
        ManifestLaunchBindingError,
    )

    path, bindings = bindings_file(tmp_path, compiled)
    settings = isolated_settings(
        manifest_launch_bindings_path=path, mission_control_catalog_scope=CATALOG
    )
    served = served_by_production_author(monkeypatch, settings)
    assert not set(served_knowledge_tools()) & served.tools
    definition, program = compiled
    with pytest.raises(ManifestLaunchBindingError, match="does not serve"):
        resolver(
            bindings, served=replace(fixture_served(bindings), tools=served.tools)
        ).stage_templates(definition, admitted(program, scope=SCOPE))
    # A required binding that is incomplete refuses at composition, as the worker does.
    required = isolated_settings(
        manifest_launch_bindings_path=path,
        mission_control_catalog_scope=CATALOG,
        knowledge_gateway_required=True,
    )
    with pytest.raises(KnowledgeConfigurationError, match="KNOWLEDGE_BINDING_URL"):
        served_by_production_author(monkeypatch, required)


async def test_api_relay_and_worker_serve_the_same_knowledge_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, compiled: tuple[Any, Any]
) -> None:
    """Parity: the API launch author, the worker's chain-relay author (both
    `compose_manifest_launch_inputs`) and the worker's exact registry (`compose_knowledge_lane`
    registry tools beside the pins) serve one tool set."""

    path, _bindings = bindings_file(tmp_path, compiled)
    settings, active = knowledge_settings(tmp_path, path)
    api = served_by_production_author(monkeypatch, settings)
    relay = served_by_production_author(monkeypatch, settings)
    clock = SteppingClock()
    fake = FakeKnowledgeBinding(
        verifier=CredentialVerifier(
            issuer="mission-control.ai-engineer",
            audience="knowledge-services-executor.ai-engineer",
            jwks=publish_jwks(active),
            clock=clock,
        ),
        clock=clock,
        binding="aiengineer-postgres",
        application=APP,
    )
    lane = await compose_knowledge_lane(
        settings,
        cast(Any, object()),
        application_id=APP,
        installation_id="00000000-0000-7000-8000-000000000001",
        client=fake,
        clock=clock,
    )
    assert lane is not None
    pin_tools = {item.ref.digest for item in CapabilityPins.from_settings(settings).tools}
    worker = frozenset(pin_tools | set(lane.registry_tools))
    assert api.tools == relay.tools == worker
    assert json.dumps(sorted(api.tools))  # digests only, no live toolset state


def _fake(clock: SteppingClock, active: Any) -> FakeKnowledgeBinding:
    return FakeKnowledgeBinding(
        verifier=CredentialVerifier(
            issuer="mission-control.ai-engineer",
            audience="knowledge-services-executor.ai-engineer",
            jwks=publish_jwks(active),
            clock=clock,
        ),
        clock=clock,
        binding="aiengineer-postgres",
        application=APP,
    )


async def test_bound_read_intent_needs_a_binding_that_serves_it(
    tmp_path: Path, compiled: tuple[Any, Any]
) -> None:
    """OVE-204 slice 4: launch bindings that bind `knowledge_read_intent` refuse a descriptor
    without `knowledge.read_intent` at the describe preflight; unbound, the lane composes."""

    path, bindings = bindings_file(tmp_path, compiled)
    assert "tool.knowledge-read-intent" in bindings.capabilities
    settings, active = knowledge_settings(tmp_path, path)
    clock = SteppingClock()
    fake = _fake(clock, active)
    fake.serves_read_intent = False
    with pytest.raises(KnowledgeConfigurationError, match="knowledge.read_intent"):
        await compose_knowledge_lane(
            settings,
            cast(Any, object()),
            application_id=APP,
            installation_id="00000000-0000-7000-8000-000000000001",
            client=fake,
            clock=clock,
        )

    unbound = bindings.model_copy(
        update={
            "model_profiles": {},
            "capabilities": {
                key: value
                for key, value in bindings.capabilities.items()
                if key != "tool.knowledge-read-intent"
            },
        }
    )
    path.write_text(unbound.model_dump_json(), encoding="utf-8")
    lane = await compose_knowledge_lane(
        settings,
        cast(Any, object()),
        application_id=APP,
        installation_id="00000000-0000-7000-8000-000000000001",
        client=fake,
        clock=clock,
    )
    assert lane is not None and lane.startup_receipt["read_intent_served"] is False
    assert lane.toolset.retained_reads is not None
